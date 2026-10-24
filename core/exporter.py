import os
import shutil
import logging
import threading
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Callable

from core.utils import sanitize_filename
from core.transcoder import transcode_audio, get_extension_for_format

logger = logging.getLogger("core.exporter")


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

        for idx, t in enumerate(tracks, start=1):
            if cancel_event and cancel_event.is_set():
                result.cancelled = True
                logger.info("Export cancelled by user.")
                break

            # Resolve source file and metadata
            if isinstance(t, dict):
                src_file = t.get("file_path", "")
                title = t.get("title", "Unknown Track")
                artist = t.get("artist", "Unknown Artist")
                dur_ms = t.get("duration_ms", 0) or 0
            elif hasattr(t, "track") and t.track:
                src_file = getattr(t, "output_path", "")
                title = t.track.title or "Unknown Track"
                artist = getattr(t.track, "artist_str", "") or (", ".join(t.track.artists) if hasattr(t.track, "artists") else "Unknown Artist")
                dur_ms = getattr(t.track, "duration_ms", 0) or 0
            else:
                src_file = getattr(t, "output_path", "") or getattr(t, "file_path", "")
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

            # Determine destination filename
            fmt = (config.target_format or "original").strip().lower()
            if fmt in ("original", "", "native"):
                dest_name = os.path.basename(src_file)
            else:
                target_ext = get_extension_for_format(fmt) or ".mp3"
                base_name = os.path.splitext(os.path.basename(src_file))[0]
                dest_name = f"{base_name}{target_ext}"

            dest_path = os.path.join(export_dir, dest_name)

            # Check skip existing
            if config.skip_existing and os.path.isfile(dest_path) and os.path.getsize(dest_path) > 1024:
                result.skipped += 1
                exported_m3u_entries.append({
                    "filename": dest_name,
                    "title": title,
                    "artist": artist,
                    "duration_s": dur_s
                })
                if progress_callback:
                    progress_callback(idx, result.total, f"Skipped (already exists): {title}")
                continue

            # Perform Copy or Transcode
            try:
                action_verb = "Copying" if fmt in ("original", "", "native") else f"Converting to {fmt.upper()}"
                if progress_callback:
                    progress_callback(idx, result.total, f"{action_verb}: {title} - {artist}")

                if fmt in ("original", "", "native"):
                    shutil.copy2(src_file, dest_path)
                else:
                    transcode_audio(
                        input_file=src_file,
                        target_format=fmt,
                        delete_source=False,
                        output_file=dest_path
                    )

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
                logger.error(f"Failed to export '{src_file}' -> '{dest_path}': {e_exp}")
                result.failed += 1
                result.errors.append(f"{title}: {e_exp}")

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
