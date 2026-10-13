import os
import shutil
import subprocess
import logging
from typing import Optional

from core.utils import ensure_ffmpeg, is_valid_audio_file
from core.exceptions import TranscodeError

logger = logging.getLogger("core.transcoder")

SUPPORTED_TARGET_FORMATS = {
    "original": None,
    "alac": {"ext": ".m4a", "codec": "alac", "extra_args": []},
    "mp3": {"ext": ".mp3", "codec": "libmp3lame", "extra_args": ["-b:a", "320k"]},
    "mp3_320": {"ext": ".mp3", "codec": "libmp3lame", "extra_args": ["-b:a", "320k"]},
    "flac": {"ext": ".flac", "codec": "flac", "extra_args": []},
    "opus": {"ext": ".opus", "codec": "libopus", "extra_args": ["-b:a", "256k"]},
}


def get_extension_for_format(target_format: str) -> Optional[str]:
    """Returns the expected file extension for a supported target format, or None."""
    target = (target_format or "").strip().lower()
    cfg = SUPPORTED_TARGET_FORMATS.get(target)
    return cfg["ext"] if cfg else None


class AudioTranscoder:
    """High-performance audio transcoder wrapping FFmpeg for lossless and lossy conversion."""

    @staticmethod
    def transcode(input_file: str, target_format: str = "original", delete_source: bool = True) -> str:
        return transcode_audio(input_file, target_format, delete_source)

    @staticmethod
    def get_extension_for_format(target_format: str) -> Optional[str]:
        return get_extension_for_format(target_format)


def transcode_audio(
    input_file: str,
    target_format: str = "original",
    delete_source: bool = True
) -> str:
    """
    Transcodes a downloaded audio file to a user-specified target format
    (e.g. Apple Lossless ALAC .m4a, MP3 320k CBR, FLAC, or Opus) using FFmpeg.
    Returns the absolute path of the converted file (or original file if format is 'original' or identical).
    """
    target = (target_format or "original").strip().lower()
    if target in ("original", "", "native"):
        return input_file

    if not os.path.isfile(input_file):
        raise TranscodeError(f"Source audio file not found for transcoding: {input_file}")

    target_cfg = SUPPORTED_TARGET_FORMATS.get(target)
    if not target_cfg:
        logger.warning(f"Unsupported transcode target '{target_format}'. Keeping original format.")
        return input_file

    target_ext = target_cfg["ext"]
    src_ext = os.path.splitext(input_file)[1].lower()

    # If the file is already in the requested target format and matches codec expectation, bypass transcoding
    if src_ext == target_ext and target != "alac":
        return input_file

    ffmpeg_bin = ensure_ffmpeg()
    if not ffmpeg_bin:
        logger.warning("FFmpeg binary not detected; cannot transcode audio. Keeping source format.")
        return input_file

    base_name = os.path.splitext(input_file)[0]
    output_file = f"{base_name}{target_ext}"
    if os.path.normpath(output_file) == os.path.normpath(input_file):
        output_file = f"{base_name}_transcoded{target_ext}"

    cmd = [
        ffmpeg_bin,
        "-y",
        "-nostats",
        "-i", input_file,
        "-c:a", target_cfg["codec"],
        *target_cfg["extra_args"],
        output_file
    ]

    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    logger.info(f"Transcoding '{os.path.basename(input_file)}' -> {target.upper()} ({target_ext})...")

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            creationflags=flags
        )
        if proc.returncode != 0:
            err_msg = proc.stderr.strip() if proc.stderr else f"Exit code {proc.returncode}"
            raise TranscodeError(f"FFmpeg transcode error: {err_msg}")

        if not os.path.isfile(output_file) or os.path.getsize(output_file) < 1024:
            raise TranscodeError(f"Transcoding output file is missing or empty: {output_file}")

        is_valid, reason = is_valid_audio_file(output_file, min_size=1024)
        if not is_valid:
            if os.path.exists(output_file):
                try:
                    os.remove(output_file)
                except Exception:
                    pass
            raise TranscodeError(f"Transcoded audio failed integrity verification: {reason}")

        if delete_source and os.path.normpath(input_file) != os.path.normpath(output_file):
            try:
                os.remove(input_file)
                logger.debug(f"Removed pre-transcode source file: {input_file}")
            except Exception as e_del:
                logger.debug(f"Could not remove source file after transcode: {e_del}")

        logger.info(f"Successfully transcoded to {target.upper()}: {output_file}")
        return output_file

    except Exception as e:
        if os.path.exists(output_file) and os.path.normpath(input_file) != os.path.normpath(output_file):
            try:
                os.remove(output_file)
            except Exception:
                pass
        logger.error(f"Failed to transcode '{input_file}': {e}")
        raise TranscodeError(f"Failed to transcode '{input_file}': {e}") from e
