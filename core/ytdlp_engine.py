import os
import re
import time
import shutil
import logging
from dataclasses import dataclass, field
from typing import Optional, Callable, Dict, Any, List
import yt_dlp

from core.spotify_client import TrackMetadata
from core.utils import clean_watermarks, format_bytes, ensure_ffmpeg

logger = logging.getLogger("core.ytdlp")


@dataclass
class YtdlpSource:
    video_id: str
    title: str
    duration: int
    url: str
    audio_format: str  # "opus" or "m4a"
    candidate_urls: List[str] = field(default_factory=list)


class YtdlpEngine:
    """
    YouTube / YouTube Music Fallback Engine using yt-dlp.
    Implements:
    - Search query strategy with audio prioritization
    - Strict duration validation (±5 seconds vs Spotify metadata) with smart fallback
    - Negative version modifier filter (avoids instrumental/karaoke/cover when unwanted)
    - Multi-candidate resilience (tries next match if a video is unavailable)
    - Untouched native stream extraction (M4A/Opus) without lossy re-encoding
    - Real-time progress hooks (percent, speed, ETA)
    """

    DURATION_TOLERANCE_SEC = 5.0

    def __init__(self, output_dir: str = ""):
        self.output_dir = output_dir
        self.ffmpeg_path = ensure_ffmpeg()

    def resolve_track(self, track: TrackMetadata) -> Optional[YtdlpSource]:
        """
        Queries YouTube for matching audio tracks within tolerance.
        Returns YtdlpSource with prioritized candidate URLs.
        """
        clean_title = clean_watermarks(track.title)
        clean_title_lower = clean_title.lower()
        artist = track.primary_artist
        queries = [
            f"ytsearch8:{artist} - {clean_title} official audio",
            f"ytsearch8:{artist} - {clean_title} topic",
            f"ytsearch8:{artist} - {clean_title}"
        ]

        node_path = shutil.which("node")
        ydl_opts = {
            "extract_flat": True,
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "remote_components": {"ejs:github"},
        }
        if node_path:
            ydl_opts["js_runtimes"] = {"node": {"path": node_path}}

        matched_candidates = []
        seen_ids = set()
        target_sec = track.duration_sec

        for query in queries:
            try:
                logger.info(f"Searching YouTube with query: '{query}'")
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    res = ydl.extract_info(query, download=False)
                    entries = res.get("entries", []) if res else []

                for entry in entries:
                    if not entry:
                        continue
                    cand_id = entry.get("id")
                    if not cand_id or cand_id in seen_ids:
                        continue
                    seen_ids.add(cand_id)

                    cand_dur = entry.get("duration")
                    cand_title = entry.get("title", "")
                    if cand_dur is None:
                        continue

                    cand_lower = cand_title.lower()
                    # Filter out unwanted version modifiers if not in track title
                    unwanted = any(
                        m in cand_lower
                        for m in ["instrumental", "karaoke", "cover", "workout", "slowed", "reverb"]
                        if m not in clean_title_lower
                    )

                    diff = abs(cand_dur - target_sec)
                    if diff <= self.DURATION_TOLERANCE_SEC:
                        effective_score = diff + (50.0 if unwanted else 0.0)
                        if "official audio" in cand_lower or "topic" in cand_lower:
                            effective_score -= 1.0
                        matched_candidates.append((effective_score, cand_id, cand_title, int(cand_dur)))

                if matched_candidates:
                    break

            except Exception as e:
                logger.error(f"Error querying YouTube for '{query}': {e}")

        # Fallback pass with ±10s tolerance if strict ±5s found nothing
        if not matched_candidates:
            logger.info(f"Strict ±5s tolerance found no matches for '{track.title}'. Trying ±10s tolerance...")
            for query in [f"ytsearch8:{artist} - {clean_title} topic", f"ytsearch8:{artist} - {clean_title} official audio"]:
                try:
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        res = ydl.extract_info(query, download=False)
                        entries = res.get("entries", []) if res else []
                    for entry in entries:
                        if not entry:
                            continue
                        cand_id = entry.get("id")
                        if not cand_id or cand_id in seen_ids:
                            continue
                        seen_ids.add(cand_id)
                        cand_dur = entry.get("duration")
                        cand_title = entry.get("title", "")
                        if cand_dur is None:
                            continue
                        cand_lower = cand_title.lower()
                        unwanted = any(m in cand_lower for m in ["instrumental", "karaoke", "cover"] if m not in clean_title_lower)
                        if unwanted:
                            continue
                        diff = abs(cand_dur - target_sec)
                        if diff <= 10.0:
                            matched_candidates.append((diff, cand_id, cand_title, int(cand_dur)))
                    if matched_candidates:
                        break
                except Exception:
                    pass

        if not matched_candidates:
            logger.warning(f"No YouTube candidate met tolerance for '{track.title}'")
            return None

        # Sort by candidate score (duration difference + modifiers)
        matched_candidates.sort(key=lambda x: x[0])
        best_score, best_id, best_title, best_dur = matched_candidates[0]
        candidate_urls = [f"https://www.youtube.com/watch?v={c[1]}" for c in matched_candidates]

        logger.info(f"Found {len(matched_candidates)} YouTube candidate(s). Best: '{best_title}' (ID: {best_id})")
        return YtdlpSource(
            video_id=best_id,
            title=best_title,
            duration=best_dur,
            url=f"https://www.youtube.com/watch?v={best_id}",
            audio_format="m4a",
            candidate_urls=candidate_urls
        )

    def download_track(
        self,
        source: YtdlpSource,
        output_template_without_ext: str,
        progress_callback: Optional[Callable[[float, str, str], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
        pause_wait: Optional[Callable[[], None]] = None
    ) -> Optional[str]:
        """
        Downloads the best audio stream directly to disk without lossy re-encoding.
        If the primary candidate fails (e.g. video unavailable), automatically tries remaining candidates.
        """
        urls_to_try = source.candidate_urls if source.candidate_urls else [source.url]

        for url in urls_to_try:
            downloaded_file = None

            def ydl_hook(d: Dict[str, Any]):
                nonlocal downloaded_file
                if cancel_check and cancel_check():
                    raise yt_dlp.utils.DownloadCancelled("Download cancelled by user.")
                if pause_wait:
                    pause_wait()

                status = d.get("status")
                if status == "downloading":
                    total_bytes = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                    downloaded = d.get("downloaded_bytes") or 0
                    speed = d.get("speed") or 0
                    eta = d.get("eta") or 0

                    percent = (downloaded / total_bytes * 100.0) if total_bytes > 0 else 0.0
                    speed_str = f"{format_bytes(speed)}/s" if speed else "-- KB/s"
                    eta_str = f"{int(eta) // 60:02d}:{int(eta) % 60:02d}" if eta else "--:--"

                    if progress_callback:
                        progress_callback(percent, speed_str, eta_str)

                elif status == "finished":
                    downloaded_file = d.get("filename")
                    if progress_callback:
                        progress_callback(100.0, "-- KB/s", "00:00")

            outtmpl = output_template_without_ext + ".%(ext)s"
            node_path = shutil.which("node")

            postprocessors = []
            if self.ffmpeg_path:
                postprocessors.append({
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "best",
                })

            ydl_opts = {
                "format": "bestaudio/best",
                "outtmpl": outtmpl,
                "quiet": True,
                "no_warnings": True,
                "noplaylist": True,
                "progress_hooks": [ydl_hook],
                "remote_components": {"ejs:github"},
                "postprocessors": postprocessors,
            }

            if node_path:
                ydl_opts["js_runtimes"] = {"node": {"path": node_path}}

            if self.ffmpeg_path:
                ydl_opts["ffmpeg_location"] = self.ffmpeg_path

            try:
                logger.info(f"Attempting yt-dlp download from: {url}")
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([url])

                # Check if file was written
                for ext in ["opus", "m4a", "webm", "mp3", "flac", "ogg"]:
                    candidate = f"{output_template_without_ext}.{ext}"
                    if os.path.isfile(candidate):
                        return candidate

                if downloaded_file and os.path.isfile(downloaded_file):
                    return downloaded_file

            except yt_dlp.utils.DownloadCancelled:
                logger.info("yt-dlp download cancelled.")
                return None
            except Exception as e:
                logger.warning(f"Download candidate {url} failed: {e}. Trying next candidate...")

        logger.error("All YouTube download candidates failed.")
        return None
