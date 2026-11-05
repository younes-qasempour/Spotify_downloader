"""Shared output naming and non-mutating batch previews."""
import os
from pathlib import Path
from typing import Iterable, Optional

from core.config import config
from core.transcoder import get_extension_for_format
from core.utils import sanitize_filename


def format_track_basename(track, naming_template: str = "{artist} - {title}") -> str:
    artist = sanitize_filename(track.primary_artist, max_length=40)
    title = sanitize_filename(track.title, max_length=40)
    album = sanitize_filename(track.album, max_length=40)
    track_number = f"{track.track_number:02d}"
    disc_number = f"{getattr(track, 'disc_number', 1) or 1:02d}"
    is_album = getattr(track, "collection_type", "track") == "album"
    template = naming_template
    if is_album and track.track_number > 0 and template == "{artist} - {title}":
        template = config.get("download.album_naming_template", "{track_num}. {artist} - {title}")
    try:
        name = template.format(
            artist=artist, title=title, album=album,
            track_num=track_number, track_number=track_number, track=track_number,
            disc_num=disc_number, disc_number=disc_number,
        )
    except (KeyError, ValueError, IndexError, AttributeError):
        prefix = f"{track_number}. " if is_album and track.track_number > 0 else ""
        name = f"{prefix}{artist} - {title}"
    return sanitize_filename(name, max_length=120)


def track_output_directory(track, output_dir: str) -> str:
    subfolder = getattr(track, "target_folder", "") if config.get("download.save_in_subfolders", False) else ""
    if subfolder:
        subfolder = sanitize_filename(subfolder)
        if os.path.basename(os.path.normpath(output_dir)).lower() != subfolder.lower():
            return os.path.join(output_dir, subfolder)
    return output_dir


def next_output_path(path: str, reserved: Optional[set[str]] = None) -> str:
    reserved = reserved if reserved is not None else set()
    stem, extension = os.path.splitext(path)
    candidate = path
    cur_stem = stem
    suffix = 2
    audio_extensions = (".flac", ".mp3", ".m4a", ".opus", ".ogg", ".wav")

    def _is_collision(p: str, s: str) -> bool:
        if os.path.lexists(p) or os.path.normcase(os.path.abspath(p)) in reserved:
            return True
        if extension == ".<native>":
            for ext in audio_extensions:
                cand_path = s + ext
                if os.path.lexists(cand_path) or os.path.normcase(os.path.abspath(cand_path)) in reserved:
                    return True
        return False

    while _is_collision(candidate, cur_stem):
        cur_stem = f"{stem} ({suffix})"
        candidate = f"{cur_stem}{extension}"
        suffix += 1
    return candidate


def preview_outputs(tracks: Iterable, output_dir: str, naming_template: Optional[str] = None,
                    target_format: Optional[str] = None) -> list[dict]:
    template = naming_template if naming_template is not None else config.get("download.naming_template", "{artist} - {title}")
    requested_format = target_format if target_format is not None else config.get("download.target_format", "original")
    reserved: set[str] = set()
    previews = []
    for track in tracks:
        directory = track_output_directory(track, output_dir)
        basename = format_track_basename(track, template)
        target_extension = get_extension_for_format(requested_format)
        provisional = target_extension is None
        extension = target_extension or ".<native>"
        if requested_format == "original":
            format_label = "Native source format (determined at resolution)"
        elif provisional:
            format_label = f"Unsupported format {requested_format}; native source format will be retained"
        else:
            format_label = requested_format.upper()
        original_path = str(Path(directory) / (basename + extension))
        path = next_output_path(original_path, reserved)
        reserved.add(os.path.normcase(os.path.abspath(path)))
        previews.append({
            "track_id": track.id,
            "title": track.title,
            "directory": directory,
            "path": path,
            "format": format_label,
            "provisional": provisional,
            "collision_detected": path != original_path,
            "collision_policy": "Keep existing files; append (2), (3), … if the final path exists. Rechecked at publication.",
        })
    return previews