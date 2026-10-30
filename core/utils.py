import os
import sys
import re
import shutil
import subprocess
import logging
import gzip
import urllib.request
from pathlib import Path
from typing import Optional, Tuple, Callable

from core.paths import get_resource_path, get_user_bin_dir

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
    return str(get_resource_path(relative_path))


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


def sanitize_path_template(path_str: str, max_segment_length: int = 80) -> str:
    """
    Sanitizes a hierarchical path template (e.g. '{artist}/{album}/{title}') by
    splitting on directory separators and sanitizing each segment individually.
    """
    if not path_str:
        return "unnamed_track"

    # Normalize slashes
    norm = path_str.replace('\\', '/')
    segments = norm.split('/')
    cleaned_segments = [sanitize_filename(seg, max_length=max_segment_length) for seg in segments if seg.strip()]

    if not cleaned_segments:
        return "track"

    return os.path.normpath(os.path.join(*cleaned_segments))


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
    user_bin = os.path.join(str(get_user_bin_dir()), "ffmpeg.exe")
    local_candidates = [
        str(get_resource_path("bin", "ffmpeg.exe")),
        str(get_resource_path("ffmpeg.exe")),
        user_bin,
        os.path.join(app_root, "bin", "ffmpeg.exe"),
        os.path.join(app_root, "ffmpeg.exe"),
        os.path.join(os.getcwd(), "bin", "ffmpeg.exe"),
        os.path.join(os.getcwd(), "ffmpeg.exe"),
        os.path.join(os.path.dirname(sys.executable), "bin", "ffmpeg.exe"),
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
    executable into %LOCALAPPDATA%/Flacify/bin/ffmpeg.exe (~29MB compressed).
    Returns absolute path to ffmpeg.exe or None on failure.
    """
    if not dest_dir:
        dest_dir = str(get_user_bin_dir())

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
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        proc = subprocess.run([target_exe, "-version"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=5, creationflags=flags)
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


def extract_embedded_cover(file_path: str) -> Optional[bytes]:
    """Extracts embedded front cover artwork bytes directly from a local audio file."""
    if not file_path or not os.path.isfile(file_path):
        return None
    try:
        import base64
        ext = os.path.splitext(file_path)[1].lower()
        if ext == ".flac":
            from mutagen.flac import FLAC
            audio = FLAC(file_path)
            if audio.pictures:
                return audio.pictures[0].data
        elif ext == ".mp3":
            from mutagen.mp3 import MP3
            audio = MP3(file_path)
            if audio.tags:
                apics = audio.tags.getall("APIC")
                if apics:
                    return apics[0].data
        elif ext in (".opus", ".ogg"):
            import mutagen
            from mutagen.flac import Picture
            audio = mutagen.File(file_path)
            if audio:
                pics = audio.get("metadata_block_picture", []) or audio.get("METADATA_BLOCK_PICTURE", [])
                if pics:
                    pic_entry = pics[0]
                    try:
                        if isinstance(pic_entry, (bytes, bytearray)):
                            try:
                                return Picture(pic_entry).data
                            except Exception:
                                return bytes(pic_entry)
                        raw = base64.b64decode(pic_entry)
                        return Picture(raw).data
                    except Exception:
                        pass
        elif ext == ".m4a":
            from mutagen.mp4 import MP4
            audio = MP4(file_path)
            covr = audio.get("covr", [])
            if covr:
                return bytes(covr[0])
    except Exception:
        pass
    return None


def detect_audio_header(header_or_path: bytes | str | Path) -> Optional[str]:
    """
    Inspects the initial bytes of a stream or file to determine if it is a genuine audio stream.
    Supports either raw bytes or a file path string/Path.
    Rejects HTML, JSON, or plain text error pages.
    """
    if isinstance(header_or_path, (str, Path)):
        if not os.path.isfile(str(header_or_path)):
            return None
        try:
            with open(str(header_or_path), "rb") as f:
                header = f.read(512)
        except Exception:
            return None
    else:
        header = header_or_path

    if not header or len(header) < 4:
        return None

    h_low = header[:256].lower()
    if b"<!doctype html" in h_low or b"<html" in h_low or b"<head" in h_low or b"<body" in h_low:
        return None
    if h_low.startswith(b"{\"") or h_low.startswith(b"[{\""):
        return None

    if header.startswith(b"fLaC"):
        return "flac"
    if header.startswith(b"ID3") or (len(header) > 2 and header[0] == 0xFF and (header[1] & 0xE0) == 0xE0):
        return "mp3"
    if header.startswith(b"OggS"):
        return "opus"
    if b"ftyp" in header[:16]:
        return "m4a"
    if header.startswith(b"RIFF"):
        return "wav"
    if header.startswith(b"\x1a\x45\xdf\xa3"):
        return "webm"

    return None


def is_valid_audio_file(file_path: str, min_size: int = 150 * 1024) -> Tuple[bool, str]:
    """
    Verifies that a local file exists, meets minimum audio size threshold,
    possesses genuine audio container headers, and contains no HTML error text.
    """
    if not file_path or not os.path.isfile(file_path):
        return False, "File does not exist"

    try:
        sz = os.path.getsize(file_path)
        if sz < min_size:
            return False, f"File size too small ({format_bytes(sz)} < {format_bytes(min_size)})"

        with open(file_path, "rb") as f:
            header = f.read(512)

        fmt = detect_audio_header(header)
        if not fmt:
            if b"<!doctype html" in header.lower() or b"<html" in header.lower():
                return False, "Corrupt file: HTML webpage detected instead of audio"
            return False, "Unrecognized audio header"

        # Additional mutagen verification
        try:
            import mutagen
            m = mutagen.File(file_path)
            if m is None and fmt not in ("flac", "webm"):
                pass
        except Exception as e:
            return False, f"Mutagen audio verification failed: {e}"

        return True, fmt

    except Exception as e:
        return False, f"Integrity check error: {e}"


def generate_m3u8_file(folder_path: str, playlist_name: str = "") -> Optional[str]:
    """
    Generates or updates a standard UTF-8 .m3u8 playlist file in the target folder.
    Sorts audio tracks by track number or filename, writing #EXTM3U and #EXTINF metadata.
    """
    if not folder_path or not os.path.isdir(folder_path):
        return None

    try:
        import mutagen
        valid_exts = {".flac", ".mp3", ".m4a", ".opus", ".ogg", ".webm"}
        files = []
        for fname in os.listdir(folder_path):
            ext = os.path.splitext(fname)[1].lower()
            if ext in valid_exts and not fname.startswith("."):
                files.append(fname)

        if not files:
            return None

        # Gather metadata and sort order
        tracks_data = []
        for fname in files:
            fpath = os.path.join(folder_path, fname)
            ext = os.path.splitext(fname)[1].lower()
            duration = 0
            title = os.path.splitext(fname)[0]
            artist = "Unknown Artist"
            track_num = 999
            try:
                m = mutagen.File(fpath)
                if m is not None:
                    duration = int(m.info.length) if hasattr(m.info, "length") else 0
                    if ext == ".mp3" and m.tags:
                        title = str(m.tags.get("TIT2", title))
                        artist = str(m.tags.get("TPE1", artist))
                        trck = str(m.tags.get("TRCK", ""))
                        if trck and trck.split("/")[0].isdigit():
                            track_num = int(trck.split("/")[0])
                    elif ext in (".flac", ".ogg", ".opus") and m.tags:
                        title = m.tags.get("TITLE", [title])[0]
                        artist = m.tags.get("ARTIST", [artist])[0]
                        trck = m.tags.get("TRACKNUMBER", [""])[0]
                        if trck and trck.split("/")[0].isdigit():
                            track_num = int(trck.split("/")[0])
                    elif ext == ".m4a" and m.tags:
                        title = m.tags.get("\xa9nam", [title])[0]
                        artist = m.tags.get("\xa9ART", [artist])[0]
                        trck = m.tags.get("trkn", [(0, 0)])[0][0]
                        if trck:
                            track_num = int(trck)
            except Exception:
                pass

            if track_num == 999:
                match = re.match(r'^(\d+)[\.\s\-]', fname)
                if match:
                    track_num = int(match.group(1))

            tracks_data.append((track_num, fname, duration, f"{artist} - {title}"))

        tracks_data.sort(key=lambda x: (x[0], x[1]))

        pl_title = playlist_name or os.path.basename(os.path.normpath(folder_path))
        safe_pl_title = sanitize_filename(pl_title, max_length=60)
        m3u8_path = os.path.join(folder_path, f"{safe_pl_title}.m3u8")

        lines = ["#EXTM3U", f"#PLAYLIST:{pl_title}"]
        for _, fname, dur, label in tracks_data:
            lines.append(f"#EXTINF:{dur},{label}")
            lines.append(fname)

        with open(m3u8_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

        logger.info(f"Generated .m3u8 playlist: {m3u8_path} ({len(tracks_data)} tracks)")
        return m3u8_path
    except Exception as e:
        logger.warning(f"Could not generate .m3u8 playlist: {e}")
        return None


def measure_audio_loudness(audio_file_path: str, fast_window: bool = True) -> Optional[Tuple[float, float]]:
    """
    Measures EBU R128 integrated loudness (LUFS) and True Peak (dBFS) using FFmpeg ebur128 filter.
    When `fast_window=True` and the track is longer than 65s, samples the 45-second core body of the track
    (skipping quiet intros/outros) for 4x faster analysis and more accurate perceived loudness.
    Returns (integrated_lufs, true_peak_dbfs), e.g. (-14.2, -0.4).
    """
    if not audio_file_path or not os.path.isfile(audio_file_path):
        return None

    ffmpeg_bin = ensure_ffmpeg()
    if not ffmpeg_bin:
        return None

    seek_args = []
    if fast_window:
        try:
            import mutagen
            m_info = mutagen.File(audio_file_path)
            dur = float(getattr(getattr(m_info, "info", None), "length", 0) or 0)
            if dur > 65.0:
                start_sec = max(12, int(dur * 0.22))
                seek_args = ["-ss", str(start_sec), "-t", "45"]
        except Exception:
            pass

    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    cmd = [
        ffmpeg_bin,
        "-nostats",
        *seek_args,
        "-i", audio_file_path,
        "-filter_complex", "ebur128=peak=true",
        "-f", "null",
        "-"
    ]

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=45, creationflags=flags)
        stderr = proc.stderr or ""

        i_matches = re.findall(r'Integrated loudness:\s+I:\s+([-\d\.]+)\s+LUFS', stderr)
        if not i_matches:
            i_matches = re.findall(r'\bI:\s+([-\d\.]+)\s+LUFS', stderr)
        peak_matches = re.findall(r'True peak:\s+Peak:\s+([-\d\.]+)\s+dBFS', stderr)
        if not peak_matches:
            peak_matches = re.findall(r'\bPeak:\s+([-\d\.]+)\s+dBFS', stderr)

        if not i_matches:
            return None

        integrated_lufs = float(i_matches[-1])
        if integrated_lufs <= -70.0:
            return None

        peak_dbfs = float(peak_matches[-1]) if peak_matches else 0.0
        return integrated_lufs, peak_dbfs
    except Exception as e:
        logger.debug(f"Loudness measurement failed for {audio_file_path}: {e}")
        return None


def calculate_replaygain(audio_file_path: str) -> Optional[Tuple[str, str]]:
    """
    Computes EBU R128 loudness and true peak using FFmpeg ebur128 filter.
    Returns (gain_str, peak_str), e.g. ("-3.45 dB", "0.985210").
    Reference loudness is ReplayGain 2.0 standard (-18.0 LUFS).
    """
    measured = measure_audio_loudness(audio_file_path)
    if not measured:
        return None

    integrated_lufs, peak_dbfs = measured
    gain_db = -18.0 - integrated_lufs
    gain_str = f"{gain_db:+.2f} dB"
    peak_linear = 10.0 ** (peak_dbfs / 20.0)
    peak_str = f"{peak_linear:.6f}"
    return gain_str, peak_str


def normalize_audio_loudness(
    file_path: str,
    target_lufs: float = -9.0,
    max_gain_db: float = 13.5,
    min_gain_db: float = -6.5,
    force: bool = False
) -> Optional[Tuple[float, float]]:
    """
    High-fidelity EBU R128 loudness booster and balancer.
    1. Measures integrated loudness (LUFS) and True Peak (dBFS).
    2. Computes optimal linear gain to reach `target_lufs` (default -9.0 LUFS for modern loud/balanced playback)
       paired with a transparent 5ms lookahead brickwall limiter at -0.4 dBFS (0.95) to prevent any clipping.
    3. Preserves 100% of embedded cover artwork, synced/unsynced lyrics, genres, and ID3/Vorbis/MP4 metadata.
    Returns (orig_lufs, applied_gain_db) on success, or None on error.
    """
    if not file_path or not os.path.isfile(file_path):
        return None

    ffmpeg_bin = ensure_ffmpeg()
    if not ffmpeg_bin:
        return None

    ext = os.path.splitext(file_path)[1].lower()
    if ext not in (".flac", ".mp3", ".opus", ".ogg", ".m4a"):
        return None

    target_tag_val = f"{target_lufs:.1f}"
    if not force:
        try:
            import mutagen
            m_chk = mutagen.File(file_path)
            if m_chk and m_chk.tags:
                if ext == ".mp3":
                    txxx = m_chk.tags.get("TXXX:FLACIFY_NORMALIZED")
                    if txxx and getattr(txxx, "text", None) and str(txxx.text[0]).strip() == target_tag_val:
                        return target_lufs, 0.0
                elif ext in (".flac", ".opus", ".ogg"):
                    norm_v = m_chk.tags.get("FLACIFY_NORMALIZED") or m_chk.tags.get("flacify_normalized")
                    if norm_v and str(norm_v[0] if isinstance(norm_v, list) else norm_v).strip() == target_tag_val:
                        return target_lufs, 0.0
                elif ext == ".m4a":
                    norm_v = m_chk.tags.get("----:com.apple.iTunes:FLACIFY_NORMALIZED")
                    if norm_v and bytes(norm_v[0]).decode("utf-8", errors="ignore").strip() == target_tag_val:
                        return target_lufs, 0.0
        except Exception:
            pass

    measured = measure_audio_loudness(file_path)
    if not measured:
        return None

    orig_lufs, orig_peak = measured
    raw_gain_db = target_lufs - orig_lufs
    gain_db = max(min_gain_db, min(max_gain_db, raw_gain_db))

    # Skip re-encoding if already within +/- 1.2 dB of target_lufs and not clipping
    if not force and abs(raw_gain_db) <= 1.2 and orig_peak <= 0.2:
        try:
            if ext == ".mp3":
                from mutagen.id3 import ID3, TXXX
                id3_t = ID3(file_path)
                id3_t.add(TXXX(encoding=3, desc="FLACIFY_NORMALIZED", text=[target_tag_val]))
                id3_t.save(file_path, v2_version=3)
            elif ext == ".flac":
                from mutagen.flac import FLAC
                fl_t = FLAC(file_path)
                fl_t["FLACIFY_NORMALIZED"] = target_tag_val
                fl_t.save()
            elif ext in (".opus", ".ogg"):
                import mutagen
                og_t = mutagen.File(file_path)
                if og_t is not None:
                    og_t["FLACIFY_NORMALIZED"] = [target_tag_val]
                    if ext == ".opus":
                        og_t["R128_TRACK_GAIN"] = ["0"]
                    og_t.save()
            elif ext == ".m4a":
                from mutagen.mp4 import MP4, MP4FreeForm
                mp4_t = MP4(file_path)
                if mp4_t.tags is None:
                    mp4_t.add_tags()
                mp4_t.tags["----:com.apple.iTunes:FLACIFY_NORMALIZED"] = [MP4FreeForm(target_tag_val.encode("utf-8"))]
                mp4_t.save()
        except Exception:
            pass
        return orig_lufs, 0.0

    # Snapshot all existing metadata and embedded artwork before modifying file
    saved_id3 = None
    saved_flac_tags = None
    saved_flac_pics = None
    saved_ogg_tags = None
    saved_mp4_tags = None

    try:
        if ext == ".mp3":
            from mutagen.id3 import ID3
            try:
                saved_id3 = ID3(file_path)
            except Exception:
                saved_id3 = None
        elif ext == ".flac":
            from mutagen.flac import FLAC
            orig_flac = FLAC(file_path)
            saved_flac_tags = dict(orig_flac.tags) if orig_flac.tags else {}
            saved_flac_pics = list(orig_flac.pictures)
        elif ext in (".opus", ".ogg"):
            import mutagen
            orig_ogg = mutagen.File(file_path)
            if orig_ogg and orig_ogg.tags:
                saved_ogg_tags = dict(orig_ogg.tags)
        elif ext == ".m4a":
            from mutagen.mp4 import MP4
            orig_mp4 = MP4(file_path)
            if orig_mp4.tags:
                saved_mp4_tags = dict(orig_mp4.tags)
    except Exception as e_snap:
        logger.debug(f"Metadata snapshot note for {file_path}: {e_snap}")

    temp_out = f"{file_path}.norm_tmp{ext}"
    if os.path.exists(temp_out):
        try:
            os.remove(temp_out)
        except Exception:
            pass

    # Build transparent gain + lookahead brickwall peak limiter filter
    af_filter = f"volume={gain_db:.2f}dB,alimiter=limit=0.95:attack=5:release=50:level=false"

    codec_args = []
    if ext == ".flac":
        codec_args = ["-map", "0:a:0", "-c:a", "flac", "-compression_level", "8"]
    elif ext == ".mp3":
        codec_args = ["-map", "0:a:0", "-c:a", "libmp3lame", "-b:a", "320k", "-q:a", "0"]
    elif ext == ".opus":
        codec_args = ["-map", "0:a:0", "-c:a", "libopus", "-b:a", "192k", "-vbr", "on", "-compression_level", "10"]
    elif ext == ".ogg":
        codec_args = ["-map", "0:a:0", "-c:a", "libvorbis", "-q:a", "9"]
    elif ext == ".m4a":
        codec_args = ["-map", "0:a:0", "-c:a", "aac", "-b:a", "256k", "-movflags", "+faststart"]

    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    cmd = [
        ffmpeg_bin,
        "-y",
        "-nostats",
        "-i", file_path,
        "-af", af_filter,
        *codec_args,
        temp_out
    ]

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120, creationflags=flags)
        if proc.returncode != 0 or not os.path.isfile(temp_out) or os.path.getsize(temp_out) < 32 * 1024:
            if os.path.exists(temp_out):
                try:
                    os.remove(temp_out)
                except Exception:
                    pass
            logger.warning(f"Loudness normalization failed for {file_path}: {proc.stderr[-300:] if proc.stderr else 'Unknown error'}")
            return None

        # Atomically replace original file with normalized file
        os.replace(temp_out, file_path)

        # Restore all snapshotted metadata, lyrics, genres, and cover art
        est_new_lufs = min(target_lufs, orig_lufs + gain_db)
        rg_gain_str = f"{-18.0 - est_new_lufs:+.2f} dB"
        rg_peak_str = "0.950000"

        try:
            if ext == ".mp3" and saved_id3 is not None:
                from mutagen.id3 import TXXX
                saved_id3.add(TXXX(encoding=3, desc="REPLAYGAIN_TRACK_GAIN", text=[rg_gain_str]))
                saved_id3.add(TXXX(encoding=3, desc="REPLAYGAIN_TRACK_PEAK", text=[rg_peak_str]))
                saved_id3.add(TXXX(encoding=3, desc="FLACIFY_NORMALIZED", text=[f"{target_lufs:.1f}"]))
                saved_id3.save(file_path, v2_version=3)
            elif ext == ".flac" and saved_flac_tags is not None:
                from mutagen.flac import FLAC
                new_flac = FLAC(file_path)
                for k, v in saved_flac_tags.items():
                    new_flac[k] = v
                new_flac["REPLAYGAIN_TRACK_GAIN"] = rg_gain_str
                new_flac["REPLAYGAIN_TRACK_PEAK"] = rg_peak_str
                new_flac["FLACIFY_NORMALIZED"] = f"{target_lufs:.1f}"
                if saved_flac_pics:
                    new_flac.clear_pictures()
                    for pic in saved_flac_pics:
                        new_flac.add_picture(pic)
                new_flac.save()
            elif ext in (".opus", ".ogg") and saved_ogg_tags is not None:
                import mutagen
                new_ogg = mutagen.File(file_path)
                if new_ogg is not None:
                    for k, v in saved_ogg_tags.items():
                        new_ogg[k] = v
                    new_ogg["REPLAYGAIN_TRACK_GAIN"] = [rg_gain_str]
                    new_ogg["REPLAYGAIN_TRACK_PEAK"] = [rg_peak_str]
                    new_ogg["FLACIFY_NORMALIZED"] = [f"{target_lufs:.1f}"]
                    if ext == ".opus":
                        new_ogg["R128_TRACK_GAIN"] = ["0"]
                    new_ogg.save()
            elif ext == ".m4a" and saved_mp4_tags is not None:
                from mutagen.mp4 import MP4, MP4FreeForm
                new_mp4 = MP4(file_path)
                if new_mp4.tags is None:
                    new_mp4.add_tags()
                for k, v in saved_mp4_tags.items():
                    new_mp4.tags[k] = v
                new_mp4.tags["----:com.apple.iTunes:replaygain_track_gain"] = [MP4FreeForm(rg_gain_str.encode("utf-8"))]
                new_mp4.tags["----:com.apple.iTunes:replaygain_track_peak"] = [MP4FreeForm(rg_peak_str.encode("utf-8"))]
                new_mp4.tags["----:com.apple.iTunes:FLACIFY_NORMALIZED"] = [MP4FreeForm(f"{target_lufs:.1f}".encode("utf-8"))]
                new_mp4.save()
        except Exception as e_rest:
            logger.warning(f"Metadata restore warning after loudness normalization for {file_path}: {e_rest}")

        logger.info(
            f"Normalized volume for '{os.path.basename(file_path)}': "
            f"{orig_lufs:.1f} LUFS -> ~{est_new_lufs:.1f} LUFS (gain: {gain_db:+.1f} dB)"
        )
        return orig_lufs, gain_db

    except Exception as e:
        if os.path.exists(temp_out):
            try:
                os.remove(temp_out)
            except Exception:
                pass
        logger.debug(f"Loudness normalization error for {file_path}: {e}")
        return None


# -------------------------------------------------------------------------
# Persian / Multilingual Transliteration & Normalization Utilities
# -------------------------------------------------------------------------

PERSIAN_TO_LATIN = {
    'آ': 'a', 'ا': 'a', 'ب': 'b', 'پ': 'p', 'ت': 't', 'ث': 's', 'ج': 'j', 'چ': 'ch',
    'ح': 'h', 'خ': 'kh', 'د': 'd', 'ذ': 'z', 'ر': 'r', 'ز': 'z', 'ژ': 'zh', 'س': 's',
    'ش': 'sh', 'ص': 's', 'ض': 'z', 'ط': 't', 'ظ': 'z', 'ع': 'a', 'غ': 'gh', 'ف': 'f',
    'ق': 'gh', 'ک': 'k', 'گ': 'g', 'ل': 'l', 'م': 'm', 'ن': 'n', 'و': 'o', 'ه': 'h',
    'ی': 'y', 'ي': 'y', 'ك': 'k', 'ئ': 'e', 'ء': '', '‌': ' ',
    '۰': '0', '۱': '1', '۲': '2', '۳': '3', '۴': '4', '۵': '5', '۶': '6', '۷': '7', '۸': '8', '۹': '9'
}

PERSIAN_ARTIST_ALIASES = {
    "mohammad reza shajarian": ["shajarian", "محمدرضا شجریان", "شجریان", "استاد شجریان"],
    "mohammad-reza shajarian": ["shajarian", "محمدرضا شجریان", "شجریان", "استاد شجریان"],
    "homayoun shajarian": ["همایون شجریان", "شجریان"],
    "parviz meshkatian": ["پرویز مشکاتیان", "مشکاتیان"],
    "aref band": ["گروه عارف", "عارف", "گروه شیدا و عارف"],
    "jalal hemmati": ["جلال همتی", "همتی", "jalal hemati", "jalal hemmati"],
    "jalal hemati": ["جلال همتی", "همتی", "jalal hemati", "jalal hemmati"],
    "fereydoon foroughi": ["فریدون فروغی", "فروغی", "foroughi", "fereidoon foroughi"],
    "fereidoon foroughi": ["فریدون فروغی", "فروغی", "foroughi", "fereidoon foroughi"],
    "ahmadreza nabizadeh": ["احمدرضا نبی زاده", "احمد رضا نبی زاده", "احمد نبی زاده", "نبی زاده", "nabizadeh"],
    "ahmad reza nabizadeh": ["احمدرضا نبی زاده", "احمد رضا نبی زاده", "احمد نبی زاده", "نبی زاده", "nabizadeh"],
    "ghazal shakeri": ["غزل شاکری", "شاکری", "ghazal shakeri", "غزل"],
    "iman heydari": ["ایمان حیدری", "حیدری", "iman heydari", "moslem fattahi", "مسلم فتاحی"],
    "moslem fattahi": ["مسلم فتاحی", "فتاحی", "moslem fattahi", "moslem fatahi"],
    "moslem fatahi": ["مسلم فتاحی", "فتاحی", "moslem fattahi", "moslem fatahi"],
    "hayedeh": ["هایده", "بانو هایده", "haydeh"],
    "mahasti": ["مهستی", "بانو مهستی"],
    "moein": ["معین", "استاد معین"],
    "mohsen chavoshi": ["چاوشی", "محسن چاوشی", "chavoshi"],
    "siavash ghomayshi": ["قمیشی", "سیاوش قمیشی", "ghomayshi"],
    "dariush": ["داریوش", "داریوش اقبالی", "eghbali"],
    "ebi": ["ابی", "ابراهیم حامدی"],
    "googoosh": ["گوگوش", "فائقه آتشین"],
    "banan": ["بنان", "غلامحسین بنان", "gholam hossein banan"],
    "gholam hossein banan": ["بنان", "غلامحسین بنان"],
    "shahram nazeri": ["ناظری", "شهرام ناظری", "nazeri"],
    "alireza ghorbani": ["علیرضا قربانی", "ghorbani"],
    "kayhan kalhor": ["کیهان کلهر", "kalhor"],
    "hossein alizadeh": ["حسین علیزاده", "alizadeh"],
    "farhad": ["فرهاد", "فرهاد مهراد", "farhad mehrad"],
    "reza sadeghi": ["رضا صادقی", "sadeghi"],
    "shadmehr aghili": ["شادمهر عقیلی", "شادمهر", "shadmehr"],
    "hassan shamaizadeh": ["شماعی زاده", "حسن شماعی زاده", "shamaizadeh"],
    "morteza pashaei": ["مرتضی پاشایی", "pashaei"],
    "salar aghili": ["سالار عقیلی", "aghili"],
    "mohammad esfahani": ["محمد اصفهانی", "esfahani"],
    "delkash": ["دلکش"],
    "marzieh": ["مرضیه"],
    "kourosh yaghmaei": ["کوروش یغمایی", "yaghmaei"],
    "vigen": ["ویگن", "viguen"],
    "aref": ["عارف"],
    "simin ghanem": ["سیمین غانم"],
    "mansour": ["منصور"],
    "shakila": ["شکیلا"],
    "pouya": ["پویا"],
    "omid": ["امید"],
    "bijan mortazavi": ["بیژن مرتضوی"],
    "leila forouhar": ["لیلا فروهر"],
    "habib": ["حبیب"],
    "andy": ["اندی"],
    "kouros": ["کورس"],
    "nooshafarin": ["نوش آفرین"],
    "sattar": ["ستار"],
    "shahram shabpareh": ["شهرام شب پره"],
}

PERSIAN_TITLE_MAPPINGS = {
    "bad-i saba": "باد صبا",
    "bad-ı saba": "باد صبا",
    "bade saba": "باد صبا",
    "bad e saba": "باد صبا",
    "naro maryam": "نرو مریم",
    "chaharmezrab": "چهارمضراب",
    "del angiz": "دل انگیز",
    "chahar mezrab": "چهارمضراب",
}


def is_persian_or_arabic(text: str) -> bool:
    return bool(re.search(r'[\u0600-\u06ff\u0750-\u077f\ufb50-\ufdff\ufe70-\ufeff]', text))


def transliterate_persian(text: str) -> str:
    return "".join(PERSIAN_TO_LATIN.get(c, c) for c in text)


def consonant_skeleton(text: str) -> str:
    return re.sub(r'[^bcdfghjklmnpqrstvwxz0-9]', '', text.lower())


KATAKANA_DIGRAPHS = {
    'キャ': 'kya', 'キュ': 'kyu', 'キョ': 'kyo',
    'シャ': 'sha', 'シュ': 'shu', 'ショ': 'sho',
    'チャ': 'cha', 'チュ': 'chu', 'チョ': 'cho',
    'ニャ': 'nya', 'ニュ': 'nyu', 'ニョ': 'nyo',
    'ヒャ': 'hya', 'ヒュ': 'hyu', 'ヒョ': 'hyo',
    'ミャ': 'mya', 'ミュ': 'myu', 'ミョ': 'myo',
    'リャ': 'rya', 'リュ': 'ryu', 'リョ': 'ryo',
    'ギャ': 'gya', 'ギュ': 'gyu', 'ギョ': 'gyo',
    'ジャ': 'ja', 'ジュ': 'ju', 'ジョ': 'jo',
    'ビャ': 'bya', 'ビュ': 'byu', 'ビョ': 'byo',
    'ピャ': 'pya', 'ピュ': 'pyu', 'ピョ': 'pyo',
    'ティ': 'ti', 'ディ': 'di', 'トゥ': 'tu', 'ドゥ': 'du',
    'ファ': 'fa', 'フィ': 'fi', 'フェ': 'fe', 'フォ': 'fo', 'フュ': 'fyu',
    'ヴァ': 'va', 'ヴィ': 'vi', 'ヴェ': 've', 'ヴォ': 'vo', 'ヴ': 'vu',
    'ウィ': 'wi', 'ウェ': 'we', 'ウォ': 'wo',
    'シェ': 'she', 'ジェ': 'je', 'チェ': 'che',
    'ツァ': 'tsa', 'ツィ': 'tsi', 'ツェ': 'tse', 'ツォ': 'tso',
    'スィ': 'si', 'ズィ': 'zi',
}

KATAKANA_MONOGRAPHS = {
    'ア': 'a', 'イ': 'i', 'ウ': 'u', 'エ': 'e', 'オ': 'o',
    'カ': 'ka', 'キ': 'ki', 'ク': 'ku', 'ケ': 'ke', 'コ': 'ko',
    'サ': 'sa', 'シ': 'shi', 'ス': 'su', 'セ': 'se', 'ソ': 'so',
    'タ': 'ta', 'チ': 'chi', 'ツ': 'tsu', 'テ': 'te', 'ト': 'to',
    'ナ': 'na', 'ニ': 'ni', 'ヌ': 'nu', 'ネ': 'ne', 'ノ': 'no',
    'ハ': 'ha', 'ヒ': 'hi', 'フ': 'fu', 'ヘ': 'he', 'ホ': 'ho',
    'マ': 'ma', 'ミ': 'mi', 'ム': 'mu', 'メ': 'me', 'モ': 'mo',
    'ヤ': 'ya', 'ユ': 'yu', 'ヨ': 'yo',
    'ラ': 'ra', 'リ': 'ri', 'ル': 'ru', 'レ': 're', 'ロ': 'ro',
    'ワ': 'wa', 'ヲ': 'o', 'ン': 'n',
    'ガ': 'ga', 'ギ': 'gi', 'グ': 'gu', 'ゲ': 'ge', 'ゴ': 'go',
    'ザ': 'za', 'ジ': 'ji', 'ズ': 'zu', 'ゼ': 'ze', 'ゾ': 'zo',
    'ダ': 'da', 'ヂ': 'ji', 'ヅ': 'zu', 'デ': 'de', 'ド': 'do',
    'バ': 'ba', 'ビ': 'bi', 'ブ': 'bu', 'ベ': 'be', 'ボ': 'bo',
    'パ': 'pa', 'ピ': 'pi', 'プ': 'pu', 'ペ': 'pe', 'ポ': 'po',
    'ァ': 'a', 'ィ': 'i', 'ゥ': 'u', 'ェ': 'e', 'ォ': 'o',
    'ャ': 'ya', 'ュ': 'yu', 'ョ': 'yo', 'ッ': '', 'ー': '', '・': ' ',
}


def has_katakana(text: str) -> bool:
    return bool(re.search(r'[\u30a0-\u30ff]', text or ""))


def romanize_katakana(text: str) -> str:
    """Converts Japanese Katakana characters to Romaji for cross-script loanword matching (e.g. アスタリスク -> asutarisuku)."""
    if not text:
        return ""
    res = text
    for dig, rom in KATAKANA_DIGRAPHS.items():
        if dig in res:
            res = res.replace(dig, rom)
    out = []
    for ch in res:
        out.append(KATAKANA_MONOGRAPHS.get(ch, ch))
    return "".join(out)


def phonetic_skeleton(text: str) -> str:
    """
    Computes a cross-script phonetic consonant skeleton normalizing Katakana, Persian, and Latin equivalents
    (e.g. 'アスタリスク' -> 'strsk' == '*Asterisk' -> 'strsk').
    """
    if not text:
        return ""
    t = romanize_katakana(transliterate_persian(normalize_special_unicode(text))).lower()
    t = t.replace("ph", "f").replace("sh", "s").replace("ch", "c").replace("ts", "s")
    t = t.replace("l", "r").replace("c", "k").replace("q", "k").replace("v", "b")
    skel = re.sub(r'[^bdfghjkmnprstxz0-9]', '', t)
    return re.sub(r'(.)\1+', r'\1', skel)


def normalize_special_unicode(text: str) -> str:
    """Normalizes unusual unicode characters that break search engines (e.g. full-width CJK punctuation, Turkish dotless i, smart quotes, dashes)."""
    if not text:
        return ""
    t = text
    # Convert full-width ASCII characters (\uFF01-\uFF5E, e.g. ＊ -> *, （ -> (, ） -> ), ～ -> ~)
    out_chars = []
    for ch in t:
        code = ord(ch)
        if 0xFF01 <= code <= 0xFF5E:
            out_chars.append(chr(code - 0xFEE0))
        elif code == 0x3000:  # Ideographic space
            out_chars.append(' ')
        elif code == 0x301C:  # Wave dash 〜
            out_chars.append('~')
        else:
            out_chars.append(ch)
    t = "".join(out_chars)
    # Turkish dotless i and dotted capital I
    t = t.replace('\u0131', 'i').replace('\u0130', 'I')
    # Smart quotes & apostrophes
    t = t.replace('’', "'").replace('‘', "'").replace('“', '"').replace('”', '"')
    # Various dashes
    t = t.replace('–', '-').replace('—', '-').replace('―', '-')
    # Non-breaking space & zero-width space
    t = t.replace('\u00a0', ' ').replace('\u200b', '')
    return t


# -------------------------------------------------------------------------
# Embedded Lyrics Extraction, 10-Band Equalizer, Audio Spectrum & Fingerprinting
# -------------------------------------------------------------------------

def extract_embedded_lyrics(file_path: str) -> str:
    """
    Extracts synchronized ([mm:ss.xx]) or plain text lyrics directly from an audio file's
    embedded metadata tags (MP3 SYLT/USLT/TXXX, FLAC/Opus/Ogg LYRICS/UNSYNCEDLYRICS, M4A ©lyr).
    Returns the lyrics text or empty string if none are embedded.
    """
    if not file_path or not os.path.isfile(file_path):
        return ""
    ext = os.path.splitext(file_path)[1].lower()
    try:
        if ext == ".mp3":
            from mutagen.id3 import ID3
            tags = ID3(file_path)
            # 1. Prefer USLT / TXXX:LYRICS if it already contains [mm:ss.xx] LRC lines
            for key, frame in tags.items():
                if key.startswith("USLT") or key.upper() == "TXXX:LYRICS":
                    txt = getattr(frame, "text", "")
                    if isinstance(txt, list):
                        txt = "\n".join(str(x) for x in txt)
                    txt = str(txt or "").strip()
                    if txt and re.search(r'\[\d{1,2}:\d{2}', txt):
                        return txt
            # 2. Check SYLT (binary synchronized lyrics frame)
            for key, frame in tags.items():
                if key.startswith("SYLT") and getattr(frame, "text", None):
                    lines = []
                    for item in frame.text:
                        if isinstance(item, tuple) and len(item) == 2:
                            line_str, ts_ms = item[0], int(item[1])
                            mins = ts_ms // 60000
                            secs = (ts_ms % 60000) // 1000
                            centis = (ts_ms % 1000) // 10
                            lines.append(f"[{mins:02d}:{secs:02d}.{centis:02d}] {line_str}")
                    if lines:
                        return "\n".join(lines)
            # 3. Fallback to plain USLT text
            for key, frame in tags.items():
                if key.startswith("USLT"):
                    txt = str(getattr(frame, "text", "") or "").strip()
                    if txt:
                        return txt
        elif ext in (".flac", ".opus", ".ogg"):
            import mutagen
            audio = mutagen.File(file_path)
            if audio and audio.tags:
                for k in ("LYRICS", "lyrics", "SYNCEDLYRICS", "UNSYNCEDLYRICS", "unsyncedlyrics"):
                    if k in audio.tags and audio.tags[k]:
                        val = audio.tags[k]
                        txt = val[0] if isinstance(val, list) else str(val)
                        if txt and txt.strip():
                            return txt.strip()
        elif ext == ".m4a":
            from mutagen.mp4 import MP4
            audio = MP4(file_path)
            if audio.tags and "\xa9lyr" in audio.tags and audio.tags["\xa9lyr"]:
                txt = str(audio.tags["\xa9lyr"][0] or "").strip()
                if txt:
                    return txt
    except Exception as e:
        logger.debug(f"Could not extract embedded lyrics from {file_path}: {e}")
    return ""


EQ_FREQUENCIES: list[int] = [31, 62, 125, 250, 500, 1000, 2000, 4000, 8000, 16000]

EQ_PRESETS: dict[str, dict[str, object]] = {
    "Flat (Default)": {
        "preamp": 0.0,
        "bass_boost": 0.0,
        "bands": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    },
    "Bass Boost": {
        "preamp": 0.0,
        "bass_boost": 4.5,
        "bands": [6.5, 5.5, 4.0, 1.5, 0.0, 0.0, 0.5, 1.0, 1.5, 1.5],
    },
    "Mega Bass & Sub": {
        "preamp": -1.0,
        "bass_boost": 7.5,
        "bands": [8.5, 7.5, 5.5, 2.0, -0.5, 0.0, 1.0, 2.0, 2.5, 2.0],
    },
    "Treble & Air Boost": {
        "preamp": 0.0,
        "bass_boost": 0.0,
        "bands": [0.0, 0.0, 0.0, 0.0, 0.5, 1.5, 3.0, 4.5, 6.0, 6.5],
    },
    "Vocal Presence": {
        "preamp": 0.5,
        "bass_boost": 0.0,
        "bands": [-2.0, -1.5, -0.5, 1.5, 3.5, 4.5, 4.0, 2.5, 1.0, 0.0],
    },
    "Rock / Metal": {
        "preamp": 0.0,
        "bass_boost": 2.5,
        "bands": [4.5, 3.5, 2.0, -1.0, -1.5, 0.5, 2.5, 4.0, 4.5, 4.5],
    },
    "Electronic / EDM": {
        "preamp": 0.0,
        "bass_boost": 5.0,
        "bands": [6.0, 5.0, 2.5, 0.0, -1.5, 0.5, 2.0, 3.5, 5.0, 5.5],
    },
    "Hip-Hop / Trap": {
        "preamp": 0.0,
        "bass_boost": 6.0,
        "bands": [7.0, 6.0, 3.5, 1.0, -1.0, -0.5, 1.5, 2.5, 3.5, 4.0],
    },
    "Acoustic / Warm": {
        "preamp": 0.5,
        "bass_boost": 1.5,
        "bands": [3.5, 3.0, 2.0, 1.0, 1.5, 1.5, 2.5, 3.0, 2.5, 2.0],
    },
    "Classical / Orchestral": {
        "preamp": 1.0,
        "bass_boost": 1.0,
        "bands": [3.5, 2.5, 1.5, 0.5, 0.0, 0.0, 1.0, 2.0, 3.0, 3.5],
    },
    "V-Shape (Loudness)": {
        "preamp": 0.0,
        "bass_boost": 4.0,
        "bands": [5.5, 4.5, 2.5, -1.0, -2.0, -1.0, 1.5, 3.5, 5.0, 5.5],
    },
    "Night Mode (Soft Dynamics)": {
        "preamp": 1.5,
        "bass_boost": -2.0,
        "bands": [-3.5, -2.5, -1.0, 1.0, 2.0, 2.5, 1.5, 0.0, -1.5, -2.5],
    },
}


def build_equalizer_af_filter(
    bands: list[float] | dict,
    preamp_db: float = 0.0,
    bass_boost_db: float = 0.0
) -> str:
    """
    Constructs a studio-grade FFmpeg audio filter graph for the 10-Band Equalizer & Bass Boost,
    followed by a 5ms lookahead brickwall peak limiter so heavy bass boosts never clip.
    """
    if isinstance(bands, dict):
        if preamp_db == 0.0 and "preamp" in bands:
            preamp_db = float(bands.get("preamp", 0.0))
        if bass_boost_db == 0.0 and "bass_boost" in bands:
            bass_boost_db = float(bands.get("bass_boost", 0.0))
        bands = bands.get("bands", [0.0] * 10)
    chain = []
    if abs(preamp_db) >= 0.1:
        chain.append(f"volume={preamp_db:.2f}dB")
    if abs(bass_boost_db) >= 0.1:
        chain.append(f"bass=g={bass_boost_db:.2f}:f=85:w=0.6")
    for idx, freq in enumerate(EQ_FREQUENCIES):
        gain = float(bands[idx]) if idx < len(bands) else 0.0
        if abs(gain) >= 0.1:
            chain.append(f"equalizer=f={freq}:t=o:w=1.0:g={gain:.2f}")
    if not chain:
        return "anull"
    chain.append("alimiter=limit=0.95:attack=5:release=50:level=false")
    return ",".join(chain)


def render_equalizer_preview(
    file_path: str,
    bands: list[float],
    preamp_db: float = 0.0,
    bass_boost_db: float = 0.0
) -> Optional[str]:
    """
    Renders a fast cached EQ preview stream in <cache_dir>/eq_preview/ for live playback in MiniPlayerBar.
    Returns the path to the rendered preview file, or the original file_path if EQ is flat.
    """
    if not file_path or not os.path.isfile(file_path):
        return None
    af_filter = build_equalizer_af_filter(bands, preamp_db, bass_boost_db)
    if af_filter == "anull":
        return file_path

    ffmpeg_bin = ensure_ffmpeg()
    if not ffmpeg_bin:
        return file_path

    import hashlib
    from core.paths import get_cache_dir
    eq_dir = os.path.join(str(get_cache_dir()), "eq_preview")
    os.makedirs(eq_dir, exist_ok=True)

    try:
        mtime = int(os.path.getmtime(file_path))
    except Exception:
        mtime = 0
    key_str = f"{os.path.abspath(file_path)}|{mtime}|{af_filter}"
    digest = hashlib.sha1(key_str.encode("utf-8")).hexdigest()[:16]
    out_path = os.path.join(eq_dir, f"eq_{digest}.mp3")
    if os.path.isfile(out_path) and os.path.getsize(out_path) > 16 * 1024:
        return out_path

    # Clean old cached preview files (> 12 files) so cache stays tiny
    try:
        existing = sorted(
            [os.path.join(eq_dir, f) for f in os.listdir(eq_dir) if f.startswith("eq_")],
            key=lambda p: os.path.getmtime(p) if os.path.exists(p) else 0
        )
        while len(existing) >= 12:
            old_f = existing.pop(0)
            try:
                os.remove(old_f)
            except Exception:
                pass
    except Exception:
        pass

    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    temp_out = f"{out_path}.tmp.mp3"
    cmd = [
        ffmpeg_bin,
        "-y",
        "-nostats",
        "-i", file_path,
        "-af", af_filter,
        "-map", "0:a:0",
        "-c:a", "libmp3lame",
        "-b:a", "320k",
        "-q:a", "2",
        temp_out
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90, creationflags=flags)
        if proc.returncode == 0 and os.path.isfile(temp_out) and os.path.getsize(temp_out) > 16 * 1024:
            os.replace(temp_out, out_path)
            return out_path
    except Exception as e:
        logger.debug(f"EQ preview render failed: {e}")
    finally:
        if os.path.exists(temp_out):
            try:
                os.remove(temp_out)
            except Exception:
                pass
    return file_path


def apply_equalizer_to_file(
    file_path: str,
    bands: list[float],
    preamp_db: float = 0.0,
    bass_boost_db: float = 0.0
) -> bool:
    """
    Permanently applies the 10-Band Equalizer & Bass Boost curve to an audio file on disk
    while preserving 100% of embedded cover art, synchronized lyrics, genres, and metadata tags.
    """
    if not file_path or not os.path.isfile(file_path):
        return False
    af_filter = build_equalizer_af_filter(bands, preamp_db, bass_boost_db)
    if af_filter == "anull":
        return True

    ffmpeg_bin = ensure_ffmpeg()
    if not ffmpeg_bin:
        return False

    ext = os.path.splitext(file_path)[1].lower()
    if ext not in (".flac", ".mp3", ".opus", ".ogg", ".m4a"):
        return False

    # Snapshot metadata & artwork
    saved_id3 = None
    saved_flac_tags = None
    saved_flac_pics = None
    saved_ogg_tags = None
    saved_mp4_tags = None
    try:
        if ext == ".mp3":
            from mutagen.id3 import ID3
            try:
                saved_id3 = ID3(file_path)
            except Exception:
                saved_id3 = None
        elif ext == ".flac":
            from mutagen.flac import FLAC
            orig_flac = FLAC(file_path)
            saved_flac_tags = dict(orig_flac.tags) if orig_flac.tags else {}
            saved_flac_pics = list(orig_flac.pictures)
        elif ext in (".opus", ".ogg"):
            import mutagen
            orig_ogg = mutagen.File(file_path)
            if orig_ogg and orig_ogg.tags:
                saved_ogg_tags = dict(orig_ogg.tags)
        elif ext == ".m4a":
            from mutagen.mp4 import MP4
            orig_mp4 = MP4(file_path)
            if orig_mp4.tags:
                saved_mp4_tags = dict(orig_mp4.tags)
    except Exception:
        pass

    codec_args = []
    if ext == ".flac":
        codec_args = ["-map", "0:a:0", "-c:a", "flac", "-compression_level", "8"]
    elif ext == ".mp3":
        codec_args = ["-map", "0:a:0", "-c:a", "libmp3lame", "-b:a", "320k", "-q:a", "0"]
    elif ext == ".opus":
        codec_args = ["-map", "0:a:0", "-c:a", "libopus", "-b:a", "192k", "-vbr", "on", "-compression_level", "10"]
    elif ext == ".ogg":
        codec_args = ["-map", "0:a:0", "-c:a", "libvorbis", "-q:a", "9"]
    elif ext == ".m4a":
        codec_args = ["-map", "0:a:0", "-c:a", "aac", "-b:a", "256k", "-movflags", "+faststart"]

    temp_out = f"{file_path}.eq_tmp{ext}"
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    cmd = [
        ffmpeg_bin,
        "-y",
        "-nostats",
        "-i", file_path,
        "-af", af_filter,
        *codec_args,
        temp_out
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120, creationflags=flags)
        if proc.returncode != 0 or not os.path.isfile(temp_out) or os.path.getsize(temp_out) < 32 * 1024:
            if os.path.exists(temp_out):
                try:
                    os.remove(temp_out)
                except Exception:
                    pass
            return False

        os.replace(temp_out, file_path)

        # Restore tags & cover art
        try:
            if ext == ".mp3" and saved_id3 is not None:
                saved_id3.save(file_path, v2_version=3)
            elif ext == ".flac" and saved_flac_tags is not None:
                from mutagen.flac import FLAC
                new_flac = FLAC(file_path)
                for k, v in saved_flac_tags.items():
                    new_flac[k] = v
                if saved_flac_pics:
                    new_flac.clear_pictures()
                    for pic in saved_flac_pics:
                        new_flac.add_picture(pic)
                new_flac.save()
            elif ext in (".opus", ".ogg") and saved_ogg_tags is not None:
                import mutagen
                new_ogg = mutagen.File(file_path)
                if new_ogg is not None:
                    for k, v in saved_ogg_tags.items():
                        new_ogg[k] = v
                    new_ogg.save()
            elif ext == ".m4a" and saved_mp4_tags is not None:
                from mutagen.mp4 import MP4
                new_mp4 = MP4(file_path)
                if new_mp4.tags is None:
                    new_mp4.add_tags()
                for k, v in saved_mp4_tags.items():
                    new_mp4.tags[k] = v
                new_mp4.save()
        except Exception as e_rest:
            logger.debug(f"Metadata restore note after EQ apply: {e_rest}")
        return True
    except Exception as e:
        if os.path.exists(temp_out):
            try:
                os.remove(temp_out)
            except Exception:
                pass
        logger.debug(f"Failed applying EQ to file {file_path}: {e}")
        return False


def inspect_audio_spectrum(file_path: str, generate_spectrogram: bool = True) -> Optional[dict]:
    """
    Analyzes an audio file's true ultrasonic frequency cutoff and spectral energy distribution
    to detect whether a file is true Lossless / 320 kbps or an upscaled/transcoded low-bitrate stream.
    Optionally renders a visual RGB spectrogram image via FFmpeg `showspectrumpic`.
    """
    if not file_path or not os.path.isfile(file_path):
        return None
    ffmpeg_bin = ensure_ffmpeg()
    if not ffmpeg_bin:
        return None

    import array
    import hashlib
    import math
    import mutagen
    from core.paths import get_cache_dir

    ext = os.path.splitext(file_path)[1].lower()
    sample_rate = 44100
    channels = 2
    bitrate_kbps = 0
    duration_sec = 0.0
    bits_per_sample = 16
    codec_name = ext.lstrip(".").upper()

    try:
        m = mutagen.File(file_path)
        if m and m.info:
            sample_rate = getattr(m.info, "sample_rate", 44100) or 44100
            channels = getattr(m.info, "channels", 2) or 2
            duration_sec = float(getattr(m.info, "length", 0.0) or 0.0)
            bits_per_sample = getattr(m.info, "bits_per_sample", 16) or 16
            br = getattr(m.info, "bitrate", 0) or 0
            if br > 0:
                bitrate_kbps = int(round(br / 1000.0))
            elif duration_sec > 0:
                bitrate_kbps = int(round((os.path.getsize(file_path) * 8) / (duration_sec * 1000.0)))
    except Exception:
        pass

    # Decode a 10-second representative slice from the core of the song at 44,100 Hz mono s16le
    start_sec = max(0.0, (duration_sec * 0.35) if duration_sec > 25.0 else 0.0)
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    cmd = [
        ffmpeg_bin,
        "-nostats",
        "-ss", f"{start_sec:.1f}",
        "-t", "10",
        "-i", file_path,
        "-vn",
        "-ac", "1",
        "-ar", "44100",
        "-f", "s16le",
        "-"
    ]
    probe_freqs = [2000, 4000, 8000, 12000, 14000, 15000, 16000, 17000, 18000, 19000, 19800, 20500, 21200]
    band_db: dict[int, float] = {f: -95.0 for f in probe_freqs}

    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=25, creationflags=flags)
        pcm_bytes = proc.stdout or b""
        if len(pcm_bytes) >= 4096:
            samples = array.array("h")
            samples.frombytes(pcm_bytes[: (len(pcm_bytes) // 2) * 2])
            # Analyze up to 45 windows of N=1024 samples spaced across the 10-second slice using Goertzel
            n_win = 1024
            total_samples = len(samples)
            num_windows = min(45, max(1, total_samples // n_win))
            stride = max(n_win, (total_samples - n_win) // max(1, num_windows))

            accum_power = {f: 0.0 for f in probe_freqs}
            coeffs = {}
            for f in probe_freqs:
                k = int(round((n_win * f) / 44100.0))
                omega = (2.0 * math.pi * k) / n_win
                coeffs[f] = 2.0 * math.cos(omega)

            valid_wins = 0
            for w_idx in range(num_windows):
                offset = w_idx * stride
                if offset + n_win > total_samples:
                    break
                win_slice = samples[offset: offset + n_win]
                # Skip silent windows
                peak_s = max(abs(win_slice[0]), abs(win_slice[n_win // 2]), abs(win_slice[-1]))
                if peak_s < 150:
                    continue
                valid_wins += 1
                for f in probe_freqs:
                    c = coeffs[f]
                    s1 = 0.0
                    s2 = 0.0
                    for x in win_slice:
                        s0 = (x / 32768.0) + c * s1 - s2
                        s2 = s1
                        s1 = s0
                    power = max(1e-12, (s1 * s1 + s2 * s2 - c * s1 * s2) / (n_win * n_win))
                    accum_power[f] += power

            if valid_wins > 0:
                for f in probe_freqs:
                    avg_p = accum_power[f] / valid_wins
                    band_db[f] = round(max(-95.0, 10.0 * math.log10(max(1e-10, avg_p))), 1)
    except Exception as e:
        logger.debug(f"Spectrum Goertzel probe note for {file_path}: {e}")

    # Determine effective ultrasonic cutoff frequency (kHz) relative to mid-band reference (2-8 kHz)
    mid_ref_db = max(band_db.get(2000, -50.0), band_db.get(4000, -50.0), band_db.get(8000, -50.0))
    threshold_db = max(-78.0, mid_ref_db - 44.0)

    cutoff_hz = 12000
    for f in probe_freqs:
        if f >= 12000 and band_db.get(f, -95.0) >= threshold_db:
            cutoff_hz = f
    cutoff_khz = round(cutoff_hz / 1000.0, 1)

    # Evaluate true quality verdict vs container claims
    is_lossless_container = ext in (".flac", ".wav")
    if cutoff_khz >= 19.8:
        verdict = "authentic"
        verdict_title = "Authentic Lossless / 320 kbps Master" if is_lossless_container or bitrate_kbps >= 280 else "Authentic Full-Spectrum Audio"
        estimated_true_kbps = bitrate_kbps if bitrate_kbps >= 256 else 320
    elif cutoff_khz >= 18.5:
        verdict = "authentic" if not is_lossless_container else "good"
        verdict_title = "True High-Fidelity (256–320 kbps / Opus Fullband)"
        estimated_true_kbps = max(256, min(320, bitrate_kbps or 256))
    elif cutoff_khz >= 16.8:
        verdict = "upscaled" if (is_lossless_container or bitrate_kbps >= 300) else "good"
        verdict_title = "Medium-High Bitrate (160–192 kbps Transcode)" if verdict == "upscaled" else "Standard High Quality (192 kbps)"
        estimated_true_kbps = 192
    else:
        verdict = "upscaled"
        verdict_title = f"Upscaled / Low-Bitrate Transcode (~128 kbps shelf at {cutoff_khz} kHz)"
        estimated_true_kbps = 128

    spectrogram_path = ""
    if generate_spectrogram:
        try:
            spec_dir = os.path.join(str(get_cache_dir()), "spectrograms")
            os.makedirs(spec_dir, exist_ok=True)
            digest = hashlib.sha1(f"{os.path.abspath(file_path)}|{os.path.getsize(file_path)}".encode("utf-8")).hexdigest()[:16]
            spec_out = os.path.join(spec_dir, f"spec_{digest}.png")
            if not (os.path.isfile(spec_out) and os.path.getsize(spec_out) > 2048):
                spec_cmd = [
                    ffmpeg_bin,
                    "-y",
                    "-nostats",
                    "-ss", f"{start_sec:.1f}",
                    "-t", "30",
                    "-i", file_path,
                    "-lavfi", "showspectrumpic=s=640x220:mode=combined:color=fire:scale=lin:legend=1",
                    "-frames:v", "1",
                    spec_out
                ]
                subprocess.run(spec_cmd, capture_output=True, timeout=25, creationflags=flags)
            if os.path.isfile(spec_out) and os.path.getsize(spec_out) > 2048:
                spectrogram_path = spec_out
        except Exception as e_spec:
            logger.debug(f"Could not generate spectrogram image for {file_path}: {e_spec}")

    return {
        "file_path": file_path,
        "codec": codec_name,
        "sample_rate": sample_rate,
        "channels": channels,
        "bits_per_sample": bits_per_sample,
        "container_bitrate_kbps": bitrate_kbps,
        "estimated_true_kbps": estimated_true_kbps,
        "duration_sec": round(duration_sec, 1),
        "cutoff_khz": cutoff_khz,
        "verdict": verdict,  # "authentic", "good", "upscaled"
        "verdict_title": verdict_title,
        "band_db": band_db,
        "spectrogram_path": spectrogram_path,
    }


def compute_acoustic_fingerprint(file_path: str) -> Optional[str]:
    """
    Computes a volume-normalized 64-bit acoustic energy & zero-crossing envelope fingerprint
    from the core 20 seconds of an audio file so identical recordings across Single/Album
    releases or formats can be matched even when tags or loudness differ.
    """
    if not file_path or not os.path.isfile(file_path):
        return None
    ffmpeg_bin = ensure_ffmpeg()
    if not ffmpeg_bin:
        return None

    import array
    import math
    import mutagen

    duration_sec = 0.0
    try:
        m = mutagen.File(file_path)
        if m and m.info:
            duration_sec = float(getattr(m.info, "length", 0.0) or 0.0)
    except Exception:
        pass

    start_sec = 15.0 if duration_sec > 45.0 else 0.0
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    cmd = [
        ffmpeg_bin,
        "-nostats",
        "-ss", f"{start_sec:.1f}",
        "-t", "20",
        "-i", file_path,
        "-vn",
        "-ac", "1",
        "-ar", "8000",
        "-f", "s16le",
        "-"
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=20, creationflags=flags)
        pcm = proc.stdout or b""
        if len(pcm) < 8000:
            return None
        samples = array.array("h")
        samples.frombytes(pcm[: (len(pcm) // 2) * 2])
        n_buckets = 33
        bucket_len = len(samples) // n_buckets
        if bucket_len < 100:
            return None

        rms_vals = []
        zcr_vals = []
        for b in range(n_buckets):
            chunk = samples[b * bucket_len: (b + 1) * bucket_len]
            sq_sum = 0.0
            zc = 0
            prev = chunk[0]
            for s in chunk:
                sq_sum += float(s) * float(s)
                if (s >= 0 and prev < 0) or (s < 0 and prev >= 0):
                    zc += 1
                prev = s
            rms_vals.append(math.sqrt(sq_sum / bucket_len))
            zcr_vals.append(zc / float(bucket_len))

        # Differential bit encoding across adjacent buckets (32 bits RMS slope + 32 bits ZCR slope = 64-bit hex)
        bits = 0
        for i in range(32):
            if rms_vals[i + 1] >= rms_vals[i]:
                bits |= (1 << i)
            if zcr_vals[i + 1] >= zcr_vals[i]:
                bits |= (1 << (32 + i))
        return f"{bits:016x}"
    except Exception as e:
        logger.debug(f"Acoustic fingerprint failed for {file_path}: {e}")
        return None


def fingerprint_similarity(fp1: str, fp2: str) -> float:
    """Returns normalized Hamming similarity (0.0 to 1.0) between two 64-bit hex acoustic fingerprints."""
    if not fp1 or not fp2 or len(fp1) != 16 or len(fp2) != 16:
        return 0.0
    try:
        v1 = int(fp1, 16)
        v2 = int(fp2, 16)
        xor_bits = bin(v1 ^ v2).count("1")
        return 1.0 - (xor_bits / 64.0)
    except Exception:
        return 0.0

