import os
import shutil
import tempfile
import logging
from typing import Optional, Callable

from core.utils import ensure_ffmpeg, is_valid_audio_file, run_ffmpeg, AudioProcessingCancelled
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
    def transcode(input_file: str, target_format: str = "original", delete_source: bool = True, output_file: Optional[str] = None, cancel_check: Optional[Callable[[], bool]] = None) -> str:
        return transcode_audio(input_file, target_format, delete_source, output_file=output_file, cancel_check=cancel_check)

    @staticmethod
    def get_extension_for_format(target_format: str) -> Optional[str]:
        return get_extension_for_format(target_format)


def transcode_audio(
    input_file: str,
    target_format: str = "original",
    delete_source: bool = True,
    output_file: Optional[str] = None,
    cancel_check: Optional[Callable[[], bool]] = None
) -> str:
    """
    Transcodes a downloaded audio file to a user-specified target format
    (e.g. Apple Lossless ALAC .m4a, MP3 320k CBR, FLAC, or Opus) using FFmpeg.
    Publishes the destination only after successful conversion and verification.
    Returns the absolute path of the converted file (or original file if format is 'original' or identical).
    """
    target = (target_format or "original").strip().lower()
    if cancel_check and cancel_check():
        raise AudioProcessingCancelled("Audio processing cancelled.")
    if not os.path.isfile(input_file):
        raise TranscodeError(f"Source audio file not found for transcoding: {input_file}")

    def same_path(first: str, second: str) -> bool:
        return os.path.normcase(os.path.realpath(first)) == os.path.normcase(os.path.realpath(second))

    def copy_original() -> str:
        if not output_file or same_path(input_file, output_file):
            return input_file
        os.makedirs(os.path.dirname(os.path.abspath(output_file)), exist_ok=True)
        fd, temp_copy = tempfile.mkstemp(prefix=".transcode-", suffix=os.path.splitext(input_file)[1], dir=os.path.dirname(os.path.abspath(output_file)))
        os.close(fd)
        try:
            shutil.copy2(input_file, temp_copy)
            if cancel_check and cancel_check():
                raise AudioProcessingCancelled("Audio processing cancelled.")
            os.replace(temp_copy, output_file)
            return output_file
        finally:
            if os.path.exists(temp_copy):
                os.remove(temp_copy)

    if target in ("original", "", "native"):
        return copy_original()

    target_cfg = SUPPORTED_TARGET_FORMATS.get(target)
    if not target_cfg:
        logger.warning(f"Unsupported transcode target '{target_format}'. Keeping original format.")
        return copy_original()

    target_ext = target_cfg["ext"]
    src_ext = os.path.splitext(input_file)[1].lower()

    # If the file is already in the requested target format and matches codec expectation, bypass transcoding
    if src_ext == target_ext and target != "alac":
        return copy_original()

    ffmpeg_bin = ensure_ffmpeg()
    if not ffmpeg_bin:
        logger.warning("FFmpeg binary not detected; cannot transcode audio. Keeping source format.")
        return input_file

    if output_file:
        os.makedirs(os.path.dirname(os.path.abspath(output_file)), exist_ok=True)
    else:
        base_name = os.path.splitext(input_file)[0]
        output_file = f"{base_name}{target_ext}"
        if same_path(output_file, input_file):
            output_file = f"{base_name}_transcoded{target_ext}"

    fd, temp_output = tempfile.mkstemp(prefix=".transcode-", suffix=target_ext, dir=os.path.dirname(os.path.abspath(output_file)))
    os.close(fd)
    cmd = [
        ffmpeg_bin,
        "-y",
        "-nostats",
        "-i", input_file,
        "-c:a", target_cfg["codec"],
        *target_cfg["extra_args"],
        temp_output
    ]

    logger.info(f"Transcoding '{os.path.basename(input_file)}' -> {target.upper()} ({target_ext})...")

    try:
        proc = run_ffmpeg(cmd, timeout=120, cancel_check=cancel_check)
        if proc.returncode != 0:
            err_msg = proc.stderr.strip() if proc.stderr else f"Exit code {proc.returncode}"
            raise TranscodeError(f"FFmpeg transcode error: {err_msg}")

        if not os.path.isfile(temp_output) or os.path.getsize(temp_output) < 1024:
            raise TranscodeError(f"Transcoding output file is missing or empty: {output_file}")

        is_valid, reason = is_valid_audio_file(temp_output, min_size=1024)
        if not is_valid:
            raise TranscodeError(f"Transcoded audio failed integrity verification: {reason}")

        if cancel_check and cancel_check():
            raise AudioProcessingCancelled("Audio processing cancelled.")
        os.replace(temp_output, output_file)
        if delete_source and not same_path(input_file, output_file):
            try:
                os.remove(input_file)
                logger.debug(f"Removed pre-transcode source file: {input_file}")
            except Exception as e_del:
                logger.debug(f"Could not remove source file after transcode: {e_del}")

        logger.info(f"Successfully transcoded to {target.upper()}: {output_file}")
        return output_file

    except AudioProcessingCancelled:
        raise
    except Exception as e:
        logger.error(f"Failed to transcode '{input_file}': {e}")
        raise TranscodeError(f"Failed to transcode '{input_file}': {e}") from e
    finally:
        if os.path.exists(temp_output):
            try:
                os.remove(temp_output)
            except Exception:
                pass
