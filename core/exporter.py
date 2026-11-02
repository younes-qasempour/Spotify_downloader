import os
import shutil
import logging
import hashlib
import tempfile
import threading
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Callable

from core.utils import sanitize_filename
from core.transcoder import transcode_audio, get_extension_for_format

logger = logging.getLogger("core.exporter")


def _source_path(track: Any) -> str:
    if isinstance(track, dict):
        return track.get("file_path", "")
    if getattr(track, "track", None):
        return getattr(track, "output_path", "")
    return getattr(track, "output_path", "") or getattr(track, "file_path", "")


def _path_key(path: str) -> str:
    return os.path.normcase(os.path.realpath(path))


def _same_file(source: str, destination: str) -> bool:
    if _path_key(source) == _path_key(destination):
        return True
    try:
        return os.path.samefile(source, destination)
    except OSError:
        return False


def _same_content(source: str, destination: str) -> bool:
    if os.path.getsize(source) != os.path.getsize(destination):
        return False
    with open(source, "rb") as original, open(destination, "rb") as exported:
        while True:
            chunk = original.read(1024 * 1024)
            if chunk != exported.read(1024 * 1024):
                return False
            if not chunk:
                return True


def _destination_names(sources: List[str], export_dir: str, fmt: str) -> Dict[str, str]:
    copying = fmt in ("original", "", "native")
    names = {}
    groups = {}
    source_paths = {_path_key(source): source for source in sources if source}
    for key, source in source_paths.items():
        name = os.path.basename(source)
        if not copying:
            name = os.path.splitext(name)[0] + (get_extension_for_format(fmt) or ".mp3")
        names[key] = name
        groups.setdefault(name.casefold(), set()).add(key)

    reserved = {name.casefold() for name in names.values()}
    for key in sorted(names):
        name = names[key]
        destination = os.path.join(export_dir, name)
        protects_source = _path_key(destination) in source_paths and not (
            copying and _path_key(destination) == key
        )
        if len(groups[name.casefold()]) > 1 or protects_source or (
            not copying and _same_file(source_paths[key], destination)
        ):
            stem, ext = os.path.splitext(name)
            suffix = hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]
            candidate = f"{stem} [{suffix}]{ext}"
            index = 2
            while candidate.casefold() in reserved or _path_key(os.path.join(export_dir, candidate)) in source_paths:
                candidate = f"{stem} [{suffix}-{index}]{ext}"
                index += 1
            names[key] = candidate
            reserved.add(candidate.casefold())
    return names


@dataclass
class ExportConfig:
    destination_dir: str
    create_playlist_subfolder: bool = True
    target_format: str = "original"       # "original", "mp3", "flac", "opus", "alac"
    generate_m3u8: bool = True
    skip_existing: bool = True


@dataclass
class ExportResult:
    total: int = 0
    exported: int = 0
    skipped: int = 0
    failed: int = 0
    export_dir: str = ""
    m3u8_path: Optional[str] = None
    errors: List[str] = field(default_factory=list)
    cancelled: bool = False


class PlaylistExporter:
    """
    Headless exporter service that copies or converts downloaded tracks
    from the central archive to external devices, USB drives, or folders.
    Guarantees that master library files are never modified or removed.
    """

    @staticmethod
    def export_tracks(
        playlist_name: str,
        tracks: List[Dict[str, Any]],
        config: ExportConfig,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
        cancel_event: Optional[threading.Event] = None
    ) -> ExportResult:
        if not config.destination_dir:
            raise ValueError("Destination directory must be specified for export.")

        safe_pl_name = sanitize_filename(playlist_name, max_length=60) or "Exported Playlist"
        if config.create_playlist_subfolder:
            export_dir = os.path.join(config.destination_dir, safe_pl_name)
        else:
            export_dir = config.destination_dir

        os.makedirs(export_dir, exist_ok=True)

        result = ExportResult(
            total=len(tracks),
            export_dir=export_dir
        )

        exported_m3u_entries: List[Dict[str, Any]] = []
        fmt = (config.target_format or "original").strip().lower()
        copying = fmt in ("original", "", "native")
        sources = [_source_path(track) for track in tracks]
        destination_names = _destination_names(sources, export_dir, fmt)

        for idx, t in enumerate(tracks, start=1):
            if cancel_event and cancel_event.is_set():
                result.cancelled = True
                logger.info("Export cancelled by user.")
                break

            # Resolve source file and metadata
            src_file = sources[idx - 1]
            if isinstance(t, dict):
                title = t.get("title", "Unknown Track")
                artist = t.get("artist", "Unknown Artist")
                dur_ms = t.get("duration_ms", 0) or 0
            elif hasattr(t, "track") and t.track:
                title = t.track.title or "Unknown Track"
                artist = getattr(t.track, "artist_str", "") or (", ".join(t.track.artists) if hasattr(t.track, "artists") else "Unknown Artist")
                dur_ms = getattr(t.track, "duration_ms", 0) or 0
            else:
                title = getattr(t, "title", "Unknown Track")
                artist = getattr(t, "artist", "Unknown Artist")
                dur_ms = getattr(t, "duration_ms", 0) or 0

            dur_s = max(0, int(dur_ms // 1000))

            if not src_file or not os.path.isfile(src_file):
                logger.warning(f"Export skipped missing file for '{artist} - {title}': {src_file}")
                result.failed += 1
                result.errors.append(f"Missing file: {title}")
                if progress_callback:
                    progress_callback(idx, result.total, f"Skipped (missing): {title}")
                continue

            dest_name = destination_names[_path_key(src_file)]
            dest_path = os.path.join(export_dir, dest_name)

            staging_path = None
            staging_dir = None
            try:
                # Only byte-identical copies are verifiably complete. Rebuild conversions.
                if copying and (_same_file(src_file, dest_path) or (
                    config.skip_existing and os.path.isfile(dest_path) and _same_content(src_file, dest_path)
                )):
                    result.skipped += 1
                    exported_m3u_entries.append({
                        "filename": dest_name,
                        "title": title,
                        "artist": artist,
                        "duration_s": dur_s
                    })
                    if progress_callback:
                        progress_callback(idx, result.total, f"Skipped (verified existing): {title}")
                    continue

                action_verb = "Copying" if copying else f"Converting to {fmt.upper()}"
                if progress_callback:
                    progress_callback(idx, result.total, f"{action_verb}: {title} - {artist}")

                if cancel_event and cancel_event.is_set():
                    result.cancelled = True
                    break
                staging_dir = tempfile.TemporaryDirectory(prefix=".export-", dir=export_dir)
                staging_path = os.path.join(staging_dir.name, dest_name)
                if copying:
                    shutil.copy2(src_file, staging_path)
                    if os.path.getsize(staging_path) != os.path.getsize(src_file):
                        raise OSError("Export copy is incomplete")
                else:
                    output = transcode_audio(
                        input_file=src_file,
                        target_format=fmt,
                        delete_source=False,
                        output_file=staging_path,
                        cancel_check=cancel_event.is_set if cancel_event else None
                    )
                    if not output or _path_key(output) != _path_key(staging_path):
                        raise OSError("Transcoder did not produce the requested export")

                if cancel_event and cancel_event.is_set():
                    result.cancelled = True
                    break
                if not os.path.isfile(staging_path) or os.path.getsize(staging_path) == 0:
                    raise OSError("Export output is missing or empty")
                os.replace(staging_path, dest_path)

                result.exported += 1
                exported_m3u_entries.append({
                    "filename": dest_name,
                    "title": title,
                    "artist": artist,
                    "duration_s": dur_s
                })
                if progress_callback:
                    progress_callback(idx, result.total, f"Finished ({idx}/{result.total}): {title}")
            except Exception as e_exp:
                if cancel_event and cancel_event.is_set():
                    result.cancelled = True
                    break
                logger.error(f"Failed to export '{src_file}' -> '{dest_path}': {e_exp}")
                result.failed += 1
                result.errors.append(f"{title}: {e_exp}")
            finally:
                if staging_dir is not None:
                    try:
                        staging_dir.cleanup()
                    except OSError as cleanup_error:
                        logger.warning(f"Could not remove staged export '{staging_path}': {cleanup_error}")

        # Optional: Generate M3U8 inside the export folder
        if config.generate_m3u8 and exported_m3u_entries:
            try:
                m3u_path = os.path.join(export_dir, f"{safe_pl_name}.m3u8")
                with open(m3u_path, "w", encoding="utf-8") as f:
                    f.write("#EXTM3U\n")
                    f.write(f"#PLAYLIST:{playlist_name}\n\n")
                    for entry in exported_m3u_entries:
                        f.write(f"#EXTINF:{entry['duration_s']},{entry['artist']} - {entry['title']}\n")
                        f.write(f"{entry['filename']}\n")
                result.m3u8_path = m3u_path
                logger.info(f"Generated export playlist M3U8 at: {m3u_path}")
            except Exception as e_m3u:
                logger.warning(f"Could not write export M3U8 file: {e_m3u}")

        return result
