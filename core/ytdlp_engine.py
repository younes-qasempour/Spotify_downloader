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
        Queries YouTube for matching audio tracks within duration tolerance.
        Returns YtdlpSource with prioritized candidate URLs.
        """
        clean_title = clean_watermarks(track.title).strip()
        clean_title_lower = clean_title.lower()
        artist = track.primary_artist.strip()
        clean_artist = re.sub(r'^(?:the|a)\s+', '', artist, flags=re.IGNORECASE).strip()

        queries = [
            f"ytsearch10:{artist} - {clean_title} official audio",
            f"ytsearch10:{artist} - {clean_title} topic",
            f"ytsearch10:{artist} - {clean_title}",
            f"ytsearch10:{artist} {clean_title} audio",
            f"ytsearch10:{artist} {clean_title} music video",
            f"ytsearch10:{artist} {clean_title}",
        ]
        if clean_artist != artist:
            queries.append(f"ytsearch10:{clean_artist} {clean_title}")

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

        target_sec = track.duration_sec
        candidates: Dict[str, Dict[str, Any]] = {}
        unwanted_keywords = ["instrumental", "karaoke", "cover", "workout", "slowed", "reverb"]

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
                    if not cand_id or cand_id in candidates:
                        continue

                    cand_dur = entry.get("duration")
                    cand_title = entry.get("title", "")
                    if cand_dur is None:
                        continue

                    cand_lower = cand_title.lower()
                    # Filter out unwanted version modifiers if not in track title
                    unwanted = any(
                        m in cand_lower
                        for m in unwanted_keywords
                        if m not in clean_title_lower
                    )
                    if unwanted:
                        continue

                    diff = abs(cand_dur - target_sec)
                    # Exclude videos with extreme duration mismatch (> 22 seconds)
                    if diff > 22.0:
                        continue

                    # Score candidate
                    # Duration component: closer is better
                    if diff <= 3.0:
                        score = 100.0 - (diff * 2.0)
                    elif diff <= 6.0:
                        score = 85.0 - (diff * 2.0)
                    elif diff <= 12.0:
                        score = 70.0 - (diff * 1.5)
                    else:
                        score = 50.0 - diff

                    # Title relevance
                    if "official audio" in cand_lower or "topic" in cand_lower:
                        score += 20.0
                    elif "official video" in cand_lower or "music video" in cand_lower:
                        score += 15.0

                    # Artist name in candidate title
                    if clean_artist.lower() in cand_lower or artist.lower() in cand_lower:
                        score += 15.0

                    candidates[cand_id] = {
                        "score": score,
                        "id": cand_id,
                        "title": cand_title,
                        "duration": int(cand_dur),
                        "diff": diff
                    }

                # If we found an ideal match (diff <= 3s and high confidence), stop searching further queries
                best_so_far = max(candidates.values(), key=lambda x: x["score"]) if candidates else None
                if best_so_far and best_so_far["score"] >= 100.0 and best_so_far["diff"] <= 3.0:
                    logger.info(f"Found immediate high-confidence YouTube candidate: '{best_so_far['title']}'")
                    break

            except Exception as e:
                logger.error(f"Error querying YouTube for '{query}': {e}")

        if not candidates:
            logger.warning(f"No YouTube candidate met tolerance for '{track.title}'")
            return None

        # Sort by candidate score descending
        sorted_candidates = sorted(candidates.values(), key=lambda x: x["score"], reverse=True)
        best = sorted_candidates[0]
        candidate_urls = [f"https://www.youtube.com/watch?v={c['id']}" for c in sorted_candidates]

        logger.info(f"Found {len(sorted_candidates)} YouTube candidate(s). Best: '{best['title']}' (ID: {best['id']}, dur: {best['duration']}s, diff: {best['diff']:.1f}s, score: {best['score']:.1f})")
        return YtdlpSource(
            video_id=best["id"],
            title=best["title"],
            duration=best["duration"],
            url=f"https://www.youtube.com/watch?v={best['id']}",
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

        def _clean_part_files():
            base_dir = os.path.dirname(output_template_without_ext)
            base_file = os.path.basename(output_template_without_ext)
            if os.path.isdir(base_dir):
                for fname in os.listdir(base_dir):
                    if fname.startswith(base_file) and fname.endswith(".part"):
                        try:
                            os.remove(os.path.join(base_dir, fname))
                        except Exception:
                            pass

        for url in urls_to_try:
            downloaded_file = None
            _clean_part_files()

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
                "continuedl": False,
                "overwrites": True,
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
                _clean_part_files()
                return None
            except Exception as e:
                _clean_part_files()
                logger.warning(f"Download candidate {url} failed: {e}. Trying next candidate...")

        logger.error("All YouTube download candidates failed.")
        return None
