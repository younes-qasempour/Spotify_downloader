import os
import logging
from dataclasses import dataclass
from typing import Optional
import requests

from core.spotify_client import TrackMetadata
from core.utils import clean_watermarks

logger = logging.getLogger("core.lyrics")


@dataclass
class LyricsData:
    synced_lyrics: Optional[str] = None
    plain_lyrics: Optional[str] = None
    instrumental: bool = False


class LyricsEngine:
    """
    LRCLIB REST API integration (https://lrclib.net/api/get).
    Provides:
    - Synchronized lyrics ([mm:ss.xx] timestamped format)
    - Unsynchronized plain text lyrics for ID3/Vorbis embedding
    - Companion .lrc file exporter
    """

    API_URL = "https://lrclib.net/api/get"
    SEARCH_URL = "https://lrclib.net/api/search"
    USER_AGENT = "SpotifyDownloader/1.0.0 (https://github.com/spotify-downloader)"

    def __init__(self, session: Optional[requests.Session] = None):
        self.session = session or requests.Session()
        self.session.headers.update({
            "User-Agent": self.USER_AGENT,
            "Accept": "application/json",
        })

    def fetch_lyrics(self, track: TrackMetadata) -> Optional[LyricsData]:
        """
        Queries LRCLIB for lyrics using title, artist, album, and duration.
        If exact match is not found or is flagged instrumental without lyrics,
        falls back to searching LRCLIB with fuzzy title/bilingual variants.
        """
        import re
        clean_title = clean_watermarks(track.title)
        clean_album = clean_watermarks(track.album)
        params = {
            "track_name": clean_title,
            "artist_name": track.primary_artist,
            "album_name": clean_album,
            "duration": int(track.duration_sec),
        }

        try:
            resp = self.session.get(self.API_URL, params=params, timeout=10)
            if resp.status_code == 404:
                # Retry without album name
                params.pop("album_name", None)
                resp = self.session.get(self.API_URL, params=params, timeout=10)

            if resp.status_code == 200:
                data = resp.json()
                synced = data.get("syncedLyrics")
                plain = data.get("plainLyrics")
                instrumental = bool(data.get("instrumental", False))

                if synced or plain:
                    logger.info(f"Lyrics found via exact get for '{track.title}' (synced={bool(synced)})")
                    return LyricsData(
                        synced_lyrics=synced,
                        plain_lyrics=plain,
                        instrumental=instrumental
                    )
                elif instrumental:
                    logger.info(f"Track '{track.title}' is confirmed instrumental via exact LRCLIB match")
                    return LyricsData(
                        synced_lyrics="[00:00.00] ♪ Instrumental ♪",
                        plain_lyrics="[Instrumental]",
                        instrumental=True
                    )
            else:
                logger.info(f"Exact lyrics get missed on LRCLIB for '{track.title}' (status {resp.status_code})")

        except Exception as e:
            logger.warning(f"Error in exact lyrics fetch for '{track.title}': {e}")

        # Search fallback across fuzzy queries & bilingual variants
        return self._search_lyrics(track, clean_title)

    def _search_lyrics(self, track: TrackMetadata, clean_title: str) -> Optional[LyricsData]:
        import re
        target_dur = track.duration_sec
        feat_clean = re.sub(r'[\(\[]\s*(?:feat\.?|ft\.?|with|prod\.?|featuring)\b[^\]\)]*[\)\]]', '', clean_title, flags=re.IGNORECASE).strip()
        queries = [f"{feat_clean} {track.primary_artist}".strip()]
        if clean_title != feat_clean:
            queries.append(f"{clean_title} {track.primary_artist}".strip())

        # Bilingual / split parts (e.g. "オトノケ - Otonoke", "青のすみか - Where Our Blue Is")
        for sep in (" - ", " / ", " | ", " : "):
            for src_t in (feat_clean, clean_title):
                if sep in src_t:
                    for part in src_t.split(sep):
                        p_c = part.strip()
                        if len(p_c) >= 2:
                            q_cand = f"{p_c} {track.primary_artist}".strip()
                            if q_cand not in queries:
                                queries.append(q_cand)
                            if p_c not in queries:
                                queries.append(p_c)

        if feat_clean not in queries:
            queries.append(feat_clean)

        instrumental_match = False

        for q in queries:
            try:
                r = self.session.get(self.SEARCH_URL, params={"q": q}, timeout=8)
                if r.status_code == 200:
                    results = r.json()
                    # Filter items with lyrics
                    valid_with_lyrics = [c for c in results if (c.get("syncedLyrics") or c.get("plainLyrics"))]

                    # Filter candidates within duration window (±15s or missing duration)
                    candidates = []
                    for c in valid_with_lyrics:
                        c_dur = c.get("duration")
                        diff = abs(c_dur - target_dur) if (c_dur and target_dur > 0) else 0.0
                        if target_dur <= 0 or diff <= 15.0 or c_dur is None:
                            candidates.append((diff, 0 if c.get("syncedLyrics") else 1, c))

                    if candidates:
                        # Best is synced first, then closest duration
                        candidates.sort(key=lambda x: (x[1], x[0]))
                        best = candidates[0][2]
                        diff = candidates[0][0]
                        logger.info(f"LRCLIB search fallback found lyrics for '{track.title}' (diff={diff:.1f}s, query='{q}')")
                        return LyricsData(
                            synced_lyrics=best.get("syncedLyrics"),
                            plain_lyrics=best.get("plainLyrics"),
                            instrumental=False
                        )

                    # Check if search indicated instrumental
                    if not instrumental_match:
                        for c in results:
                            if c.get("instrumental", False):
                                c_dur = c.get("duration")
                                diff = abs(c_dur - target_dur) if (c_dur and target_dur > 0) else 0.0
                                if target_dur <= 0 or diff <= 15.0 or c_dur is None:
                                    instrumental_match = True
                                    break
            except Exception as e_search:
                logger.debug(f"LRCLIB search query '{q}' error: {e_search}")

        if instrumental_match:
            logger.info(f"LRCLIB search fallback determined '{track.title}' is instrumental")
            return LyricsData(
                synced_lyrics="[00:00.00] ♪ Instrumental ♪",
                plain_lyrics="[Instrumental]",
                instrumental=True
            )

        return None

    def save_companion_lrc(
        self,
        audio_file_path: str,
        lyrics_data: LyricsData,
        target_dir: Optional[str] = None
    ) -> Optional[str]:
        """
        Saves companion .lrc file.
        If target_dir is specified (e.g. lyrics/ subfolder), saves it there;
        otherwise saves in the same folder as the audio file.
        """
        if not lyrics_data or not lyrics_data.synced_lyrics:
            return None

        base_name = os.path.splitext(os.path.basename(audio_file_path))[0]
        if target_dir:
            os.makedirs(target_dir, exist_ok=True)
            lrc_path = os.path.join(target_dir, f"{base_name}.lrc")
        else:
            parent_dir = os.path.dirname(audio_file_path)
            lrc_path = os.path.join(parent_dir, f"{base_name}.lrc")

        try:
            with open(lrc_path, "w", encoding="utf-8") as f:
                f.write(lyrics_data.synced_lyrics)
            logger.info(f"Saved companion .lrc to {lrc_path}")
            return lrc_path
        except Exception as e:
            logger.error(f"Failed to write .lrc file {lrc_path}: {e}")
            return None
