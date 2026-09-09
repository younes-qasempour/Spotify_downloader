import re
import json
import time
import logging
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Dict, Any
from concurrent.futures import ThreadPoolExecutor
import requests

try:
    import spotipy
    from spotipy.oauth2 import SpotifyClientCredentials
except ImportError:
    spotipy = None
    SpotifyClientCredentials = None

from core.utils import clean_watermarks, sanitize_filename

logger = logging.getLogger("core.spotify")


@dataclass
class TrackMetadata:
    id: str
    title: str
    artists: List[str]
    album: str
    release_date: str
    duration_ms: int
    track_number: int = 1
    disc_number: int = 1
    isrc: str = ""
    cover_url: str = ""
    collection_type: str = "track"   # "track", "album", "playlist"
    collection_name: str = "Singles" # Playlist title, album title, or "Singles"

    @property
    def primary_artist(self) -> str:
        return self.artists[0] if self.artists else "Unknown Artist"

    @property
    def artist_str(self) -> str:
        return ", ".join(self.artists) if self.artists else "Unknown Artist"

    @property
    def duration_sec(self) -> float:
        return self.duration_ms / 1000.0

    @property
    def target_folder(self) -> str:
        """
        Returns the sanitized relative subfolder for organizing downloads:
        - Playlists: folder named after the playlist (e.g. "Chill Moody Mix")
        - Albums: folder named after the album (e.g. "Random Access Memories")
        - Singles / Standalone Tracks: "Singles"
        """
        if self.collection_type == "playlist" and self.collection_name:
            return sanitize_filename(self.collection_name, max_length=60)
        elif self.collection_type == "album" and self.collection_name:
            return sanitize_filename(self.collection_name, max_length=60)
        elif self.collection_type == "track" or not self.collection_name:
            return "Singles"
        return sanitize_filename(self.collection_name, max_length=60)


class SpotifyClient:
    """
    Dual-mode Spotify Metadata Resolver.
    Supports official Web API (Client Credentials) with pagination for large playlists,
    and automatic anonymous guest embed scraping requiring zero credentials.
    """

    SPOTIFY_URL_PATTERN = re.compile(
        r'(?:https?://open\.spotify\.com/|spotify:)(?P<type>track|album|playlist|artist)[/:](?P<id>[a-zA-Z0-9]+)'
    )

    def __init__(self, client_id: str = "", client_secret: str = ""):
        self.client_id = client_id.strip()
        self.client_secret = client_secret.strip()
        self._sp: Optional[Any] = None
        self._init_api()

        self._session = requests.Session()
        self._session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                          '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
        })

    def _init_api(self):
        if spotipy and self.client_id and self.client_secret:
            try:
                auth_mgr = SpotifyClientCredentials(
                    client_id=self.client_id,
                    client_secret=self.client_secret
                )
                self._sp = spotipy.Spotify(auth_manager=auth_mgr)
                logger.info("Initialized official Spotify Web API client.")
            except Exception as e:
                logger.warning(f"Failed to initialize Spotipy client: {e}. Fallback to guest mode.")
                self._sp = None
        else:
            self._sp = None

    def update_credentials(self, client_id: str, client_secret: str):
        self.client_id = client_id.strip()
        self.client_secret = client_secret.strip()
        self._init_api()

    @classmethod
    def parse_url(cls, url_or_uri: str) -> Optional[Tuple[str, str]]:
        """
        Parses Spotify link/URI into (entity_type, entity_id).
        Returns None if invalid.
        """
        clean = url_or_uri.strip().split('?')[0]
        match = cls.SPOTIFY_URL_PATTERN.search(clean)
        if match:
            return match.group("type"), match.group("id")
        return None

    def resolve(self, url_or_uri: str) -> List[TrackMetadata]:
        """
        Main entry point to resolve a Spotify URL/URI to a list of TrackMetadata.
        """
        parsed = self.parse_url(url_or_uri)
        if not parsed:
            raise ValueError(f"Invalid Spotify URL or URI: {url_or_uri}")

        entity_type, entity_id = parsed
        logger.info(f"Resolving Spotify entity [{entity_type}] with ID: {entity_id}")

        if self._sp:
            try:
                return self._resolve_with_api(entity_type, entity_id)
            except Exception as e:
                logger.warning(f"Web API resolution failed: {e}. Attempting guest scrape fallback.")

        return self._resolve_with_guest(entity_type, entity_id)

    # -------------------------------------------------------------------------
    # Official Spotify Web API Resolver
    # -------------------------------------------------------------------------
    def _resolve_with_api(self, entity_type: str, entity_id: str) -> List[TrackMetadata]:
        if not self._sp:
            raise RuntimeError("Spotipy client not initialized.")

        if entity_type == "track":
            item = self._sp.track(entity_id)
            return [self._format_track_item(item, collection_type="track", collection_name="Singles")]

        elif entity_type == "album":
            album = self._sp.album(entity_id)
            cover_url = album.get("images", [{}])[0].get("url", "")
            release_date = album.get("release_date", "")
            album_name = clean_watermarks(album.get("name", "Unknown Album"))

            tracks: List[TrackMetadata] = []
            results = self._sp.album_tracks(entity_id, limit=50)
            while results:
                for item in results.get("items", []):
                    # Attach album info which isn't full on simplified tracks
                    item["album"] = {
                        "name": album_name,
                        "release_date": release_date,
                        "images": [{"url": cover_url}]
                    }
                    tracks.append(self._format_track_item(
                        item,
                        collection_type="album",
                        collection_name=album_name
                    ))
                if results.get("next"):
                    results = self._sp.next(results)
                else:
                    break
            return tracks

        elif entity_type == "playlist":
            pl_title = "Spotify Playlist"
            try:
                pl_meta = self._sp.playlist(entity_id, fields="name")
                if pl_meta and pl_meta.get("name"):
                    pl_title = clean_watermarks(pl_meta["name"])
            except Exception as e:
                logger.debug(f"Could not fetch playlist title: {e}")

            tracks: List[TrackMetadata] = []
            offset = 0
            limit = 50
            while True:
                retries = 3
                results = None
                while retries > 0:
                    try:
                        results = self._sp.playlist_items(
                            entity_id,
                            offset=offset,
                            limit=limit,
                            additional_types=['track']
                        )
                        break
                    except Exception as e:
                        retries -= 1
                        time.sleep(2.0)
                        if retries == 0:
                            raise e

                if not results or not results.get("items"):
                    break

                for item_wrapper in results["items"]:
                    track_item = item_wrapper.get("track")
                    if track_item and track_item.get("id"):
                        tracks.append(self._format_track_item(
                            track_item,
                            collection_type="playlist",
                            collection_name=pl_title
                        ))

                if results.get("next"):
                    offset += limit
                else:
                    break
            return tracks

        elif entity_type == "artist":
            top_tracks = self._sp.artist_top_tracks(entity_id)
            return [self._format_track_item(item, collection_type="playlist", collection_name="Artist Top Tracks") for item in top_tracks.get("tracks", [])]

        raise ValueError(f"Unsupported entity type: {entity_type}")

    def _format_track_item(
        self,
        item: Dict[str, Any],
        collection_type: str = "track",
        collection_name: str = "Singles"
    ) -> TrackMetadata:
        artists = [a.get("name", "") for a in item.get("artists", []) if a.get("name")]
        album_data = item.get("album", {})
        album_name = album_data.get("name", "")
        release_date = album_data.get("release_date", "")

        images = album_data.get("images", [])
        cover_url = images[0].get("url", "") if images else ""

        external_ids = item.get("external_ids", {})
        isrc = external_ids.get("isrc", "")

        return TrackMetadata(
            id=item.get("id", ""),
            title=clean_watermarks(item.get("name", "")),
            artists=artists,
            album=clean_watermarks(album_name),
            release_date=release_date,
            duration_ms=item.get("duration_ms", 0),
            track_number=item.get("track_number", 1),
            disc_number=item.get("disc_number", 1),
            isrc=isrc,
            cover_url=cover_url,
            collection_type=collection_type,
            collection_name=collection_name
        )

    # -------------------------------------------------------------------------
    # Anonymous Guest Embed Resolver
    # -------------------------------------------------------------------------
    def _resolve_with_guest(self, entity_type: str, entity_id: str) -> List[TrackMetadata]:
        embed_url = f"https://open.spotify.com/embed/{entity_type}/{entity_id}"
        resp = self._session.get(embed_url, timeout=12)
        resp.raise_for_status()

        match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', resp.text)
        if not match:
            raise RuntimeError(f"Could not extract __NEXT_DATA__ from Spotify embed: {embed_url}")

        data = json.loads(match.group(1))
        entity = data.get("props", {}).get("pageProps", {}).get("state", {}).get("data", {}).get("entity", {})

        if entity_type == "track":
            return [self._format_guest_track_entity(entity)]

        elif entity_type in ("playlist", "album"):
            track_list = entity.get("trackList", [])
            cover_url = ""
            visual_id = entity.get("visualIdentity", {})
            images = visual_id.get("image", [])
            if images:
                cover_url = images[0].get("url", "")

            entity_title = clean_watermarks(entity.get("title", ""))
            c_type = "album" if entity_type == "album" else "playlist"
            c_name = entity_title if entity_title else ("Unknown Album" if entity_type == "album" else "Spotify Playlist")

            r_date = entity.get("releaseDate") or ""
            if isinstance(r_date, dict):
                r_date = r_date.get("isoString", "") or str(r_date.get("year", ""))
            if isinstance(r_date, str) and "T" in r_date:
                r_date = r_date.split("T")[0]
            release_date = str(r_date) if r_date else ""

            tracks: List[TrackMetadata] = []
            for idx, t in enumerate(track_list, start=1):
                tid = t.get("uri", "").split(":")[-1] or t.get("id", f"track_{idx}")
                title = clean_watermarks(t.get("title", ""))
                # Subtitle usually contains artist string "Artist 1, Artist 2"
                subtitle = t.get("subtitle", "")
                artists = [a.strip() for a in subtitle.split(",") if a.strip()]
                if not artists and entity.get("subtitle"):
                    artists = [entity.get("subtitle").strip()]

                duration_ms = int(t.get("duration") or 0)

                tracks.append(TrackMetadata(
                    id=tid,
                    title=title,
                    artists=artists if artists else ["Unknown Artist"],
                    album=clean_watermarks(entity_title if entity_type == "album" else "Spotify Playlist"),
                    release_date=release_date,
                    duration_ms=duration_ms,
                    track_number=idx,
                    disc_number=1,
                    isrc="",
                    cover_url=cover_url,
                    collection_type=c_type,
                    collection_name=c_name
                ))

            # If resolving a playlist, fetch unique high-res cover art for each individual track
            if entity_type == "playlist" and tracks:
                logger.info(f"Fetching unique 640x640 cover art for {len(tracks)} playlist tracks...")
                def _resolve_cover(trk: TrackMetadata):
                    if trk.id and not trk.id.startswith("track_"):
                        unique_cover = self._fetch_track_cover(trk.id)
                        if unique_cover:
                            trk.cover_url = unique_cover

                with ThreadPoolExecutor(max_workers=10) as executor:
                    list(executor.map(_resolve_cover, tracks))

            return tracks

    def _fetch_track_cover(self, track_id: str) -> str:
        """Fetches unique 640x640 album artwork for a track via Spotify oEmbed."""
        if not track_id:
            return ""
        try:
            url = f"https://open.spotify.com/oembed?url=https://open.spotify.com/track/{track_id}"
            r = self._session.get(url, timeout=6)
            if r.status_code == 200:
                thumb = r.json().get("thumbnail_url", "")
                if thumb:
                    # Upgrade standard 300x300 thumbnail to pristine 640x640 square cover art
                    return thumb.replace("ab67616d00001e02", "ab67616d0000b273")
        except Exception as e:
            logger.debug(f"Could not fetch individual cover for track {track_id}: {e}")
        return ""

    def _format_guest_track_entity(self, entity: Dict[str, Any]) -> TrackMetadata:
        title = clean_watermarks(entity.get("title") or entity.get("name") or "")
        artists_raw = entity.get("artists", [])
        artists = [a.get("name") for a in artists_raw if a.get("name")]
        if not artists and entity.get("subtitle"):
            artists = [entity.get("subtitle").strip()]

        visual = entity.get("visualIdentity", {})
        images = visual.get("image", [])
        cover_url = images[-1].get("url") if images else ""  # Usually largest is at the end or images[0]
        if images and images[0].get("maxWidth", 0) > images[-1].get("maxWidth", 0):
            cover_url = images[0].get("url")

        r_date = entity.get("releaseDate", "")
        if isinstance(r_date, dict):
            r_date = r_date.get("isoString", "") or str(r_date.get("year", ""))
        if isinstance(r_date, str) and "T" in r_date:
            r_date = r_date.split("T")[0]

        return TrackMetadata(
            id=entity.get("id", ""),
            title=title,
            artists=artists if artists else ["Unknown Artist"],
            album="",
            release_date=str(r_date),
            duration_ms=entity.get("duration", 0),
            track_number=1,
            disc_number=1,
            isrc="",
            cover_url=cover_url,
            collection_type="track",
            collection_name="Singles"
        )

