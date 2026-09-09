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
        """
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

                logger.info(f"Lyrics found for '{track.title}' (synced={bool(synced)})")
                return LyricsData(
                    synced_lyrics=synced,
                    plain_lyrics=plain,
                    instrumental=instrumental
                )
            else:
                logger.info(f"No lyrics found on LRCLIB for '{track.title}' (status {resp.status_code})")
                return None

        except Exception as e:
            logger.error(f"Error fetching lyrics for '{track.title}': {e}")
            return None

    def save_companion_lrc(self, audio_file_path: str, lyrics_data: LyricsData) -> Optional[str]:
        """
        Saves companion .lrc file in the same folder as the audio file with identical basename.
        """
        if not lyrics_data or not lyrics_data.synced_lyrics:
            return None

        base_path, _ = os.path.splitext(audio_file_path)
        lrc_path = f"{base_path}.lrc"

        try:
            with open(lrc_path, "w", encoding="utf-8") as f:
                f.write(lyrics_data.synced_lyrics)
            logger.info(f"Saved companion .lrc to {lrc_path}")
            return lrc_path
        except Exception as e:
            logger.error(f"Failed to write .lrc file {lrc_path}: {e}")
            return None
