import os
import sys
import re
import shutil
import subprocess
import logging
from pathlib import Path

logger = logging.getLogger("core.utils")

# Illegal Windows characters: < > : " / \ | ? * and ASCII 0-31
ILLEGAL_WIN_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
WATERMARK_PATTERNS = [
    re.compile(r'\[\s*musilon(?:\.com)?\s*\]', re.IGNORECASE),
    re.compile(r'\(\s*musilon(?:\.com)?\s*\)', re.IGNORECASE),
    re.compile(r'_\s*musilon(?:\.com)?\s*_', re.IGNORECASE),
    re.compile(r'-\s*musilon(?:\.com)?\s*-', re.IGNORECASE),
]


def resource_path(relative_path: str) -> str:
    """
    Get absolute path to resource, works for dev and for PyInstaller frozen app.
    """
    try:
        base_path = sys._MEIPASS  # type: ignore[attr-defined]
    except Exception:
        # Resolve to directory of current file's grandparent or current working dir
        base_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    return os.path.normpath(os.path.join(base_path, relative_path))


def clean_watermarks(text: str) -> str:
    """
    Remove site tags, watermarks like [Musilon] from title, album or filename.
    """
    if not text:
        return ""
    result = text
    for pat in WATERMARK_PATTERNS:
        result = pat.sub('', result)
    result = re.sub(r'\s+', ' ', result).strip()
    return result


def sanitize_filename(name: str, max_length: int = 80) -> str:
    """
    Strip illegal Windows path characters and truncate base name to prevent MAX_PATH overflow.
    Windows filenames cannot end with a period or space, nor contain <>:"/\\|?*.
    """
    if not name:
        return "unnamed_track"

    cleaned = clean_watermarks(name)
    cleaned = ILLEGAL_WIN_CHARS.sub('', cleaned)
    # Strip leading/trailing spaces and dots
    cleaned = cleaned.strip('. ')
    if not cleaned:
        cleaned = "track"

    # Truncate length
    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length].rstrip('. ')

    return cleaned


from typing import Callable, Optional
import gzip
import urllib.request

FFMPEG_DOWNLOAD_URL = "https://github.com/eugeneware/ffmpeg-static/releases/latest/download/ffmpeg-win32-x64.gz"


def format_duration(ms: int | float) -> str:
    """
    Format milliseconds to MM:SS string.
    """
    if not ms or ms < 0:
        return "00:00"
    total_seconds = int(ms // 1000)
    minutes = total_seconds // 60
    seconds = total_seconds % 60
    return f"{minutes:02d}:{seconds:02d}"


def format_bytes(num_bytes: int | float) -> str:
    """
    Format byte count into human readable units (e.g. 14.2 MB).
    """
    if num_bytes < 0:
        return "0 B"
    for unit in ['B', 'KB', 'MB', 'GB']:
        if num_bytes < 1024.0:
            return f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024.0
    return f"{num_bytes:.1f} TB"


def ensure_ffmpeg() -> str | None:
    """
    Check if ffmpeg is available in:
    1. Bundled / local directory (ffmpeg.exe or bin/ffmpeg.exe)
    2. System PATH
    Returns path to ffmpeg executable or None if not found.
    """
    # 1. Check local directory candidates
    app_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    local_candidates = [
        resource_path("ffmpeg.exe"),
        resource_path("bin/ffmpeg.exe"),
        os.path.join(app_root, "bin", "ffmpeg.exe"),
        os.path.join(app_root, "ffmpeg.exe"),
        os.path.join(os.getcwd(), "bin", "ffmpeg.exe"),
        os.path.join(os.getcwd(), "ffmpeg.exe"),
        os.path.join(os.path.dirname(sys.executable), "ffmpeg.exe")
    ]
    for cand in local_candidates:
        if os.path.isfile(cand) and os.access(cand, os.X_OK):
            return os.path.normpath(cand)

    # 2. Check system PATH
    sys_path = shutil.which("ffmpeg")
    if sys_path:
        return os.path.normpath(sys_path)

    return None


def download_ffmpeg(
    dest_dir: str = "",
    progress_callback: Optional[Callable[[float, str], None]] = None
) -> str | None:
    """
    Automatically downloads and extracts the standalone 64-bit Windows FFmpeg
    executable into bin/ffmpeg.exe (~29MB compressed).
    Returns absolute path to ffmpeg.exe or None on failure.
    """
    if not dest_dir:
        app_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        dest_dir = os.path.join(app_root, "bin")

    os.makedirs(dest_dir, exist_ok=True)
    target_exe = os.path.normpath(os.path.join(dest_dir, "ffmpeg.exe"))
    temp_gz = target_exe + ".gz"

    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

    try:
        if progress_callback:
            progress_callback(0.0, "Connecting to FFmpeg release...")

        req = urllib.request.Request(FFMPEG_DOWNLOAD_URL, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as resp:
            total_size = int(resp.headers.get("Content-Length", 0))
            downloaded = 0
            chunk_size = 64 * 1024

            with open(temp_gz, "wb") as f_out:
                while True:
                    chunk = resp.read(chunk_size)
                    if not chunk:
                        break
                    f_out.write(chunk)
                    downloaded += len(chunk)
                    if progress_callback:
                        pct = (downloaded / total_size * 80.0) if total_size > 0 else 0.0
                        progress_callback(pct, f"Downloading FFmpeg: {format_bytes(downloaded)} / {format_bytes(total_size)}")

        if progress_callback:
            progress_callback(85.0, "Decompressing ffmpeg.exe...")

        with gzip.open(temp_gz, "rb") as f_in:
            with open(target_exe, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)

        if os.path.exists(temp_gz):
            os.remove(temp_gz)

        # Test execution
        proc = subprocess.run([target_exe, "-version"], capture_output=True, text=True, timeout=5)
        if proc.returncode == 0:
            logger.info(f"FFmpeg successfully installed at {target_exe}")
            if progress_callback:
                progress_callback(100.0, "FFmpeg ready!")
            return target_exe
        else:
            logger.error(f"FFmpeg validation failed: {proc.stderr}")
            return None

    except Exception as e:
        logger.error(f"Failed to download FFmpeg: {e}")
        if os.path.exists(temp_gz):
            try:
                os.remove(temp_gz)
            except Exception:
                pass
        return None


def ensure_or_download_ffmpeg(progress_callback: Optional[Callable[[float, str], None]] = None) -> str | None:
    """
    Returns existing ffmpeg executable path, or automatically downloads it if missing.
    """
    existing = ensure_ffmpeg()
    if existing:
        return existing
    logger.info("FFmpeg missing. Initiating automatic download...")
    return download_ffmpeg(progress_callback=progress_callback)

