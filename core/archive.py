import os
import re
import sqlite3
import threading
import logging
import shutil
from contextlib import contextmanager, closing
from typing import Optional, List, Dict, Any, Callable, Tuple
from pathlib import Path

from core.config import config
from core.spotify_client import TrackMetadata
from core.utils import extract_embedded_cover, is_valid_audio_file, sanitize_filename
from core.paths import get_archive_db_path, get_covers_dir, get_default_download_dir

logger = logging.getLogger("core.archive")

TRACK_PREFIX_PATTERN = re.compile(r"^(\d{1,3})[\s.\-_]+")


def normalize_path(path: str) -> str:
    """Normalizes path and ensures uppercase Windows drive letter for consistent deduplication."""
    if not path:
        return ""
    if not os.path.isabs(path):
        base_dir = config.get("download.output_dir") or str(get_default_download_dir())
        path = os.path.join(base_dir, path)
    p = os.path.normpath(os.path.abspath(path))
    if os.name == 'nt' and len(p) > 1 and p[1] == ':':
        p = p[0].upper() + p[1:]
    return p


def resolve_collection_cover(collection_name_or_folder: str, sample_file: str = "") -> str:
    """
    Resolves or extracts collection cover artwork into the dedicated app cache directory:
    cache/covers/{name}.jpg.
    Never writes cover.jpg or any image files inside the user's music folder.
    Returns the path to the cached cover image if found/created, or empty string.
    """
    if not collection_name_or_folder:
        return ""

    # Normalize name: if it's a directory path, use folder name
    # But if folder name is 'downloads' or 'music', it's generic and NOT a valid collection name!
    candidate_name = collection_name_or_folder.strip()
    if os.path.isdir(candidate_name) or ("\\" in candidate_name or "/" in candidate_name):
        candidate_name = os.path.basename(os.path.normpath(candidate_name))

    if candidate_name.lower() in ("downloads", "music", ""):
        # Generic folder; cannot be used as collection name
        return ""

    safe_name = sanitize_filename(candidate_name, max_length=50)
    covers_dir = str(get_covers_dir())
    if not os.path.isdir(covers_dir):
        return ""

    # 1. Check exact matches in covers_dir
    cached_cover = os.path.join(covers_dir, f"{safe_name}.jpg")
    if os.path.isfile(cached_cover) and os.path.getsize(cached_cover) > 500:
        return cached_cover

    for prefix in ("playlist_", "album_"):
        candidate = os.path.join(covers_dir, f"{prefix}{safe_name}.jpg")
        if os.path.isfile(candidate) and os.path.getsize(candidate) > 500:
            return candidate

    # 2. Case-insensitive and prefix match in covers_dir (handles long truncated names & unicode)
    safe_lower = safe_name.lower()
    try:
        for f in os.listdir(covers_dir):
            if not f.lower().endswith((".jpg", ".png", ".jpeg", ".webp")):
                continue
            stem = os.path.splitext(f)[0].lower()
            if stem == safe_lower or stem == f"playlist_{safe_lower}" or stem == f"album_{safe_lower}":
                cp = os.path.join(covers_dir, f)
                if os.path.isfile(cp) and os.path.getsize(cp) > 500:
                    return cp
            # Prefix match for long playlist names (e.g., truncated to 50 chars)
            if len(safe_lower) >= 25 and (stem.startswith(safe_lower[:25]) or safe_lower.startswith(stem[:25])):
                cp = os.path.join(covers_dir, f)
                if os.path.isfile(cp) and os.path.getsize(cp) > 500:
                    return cp
    except Exception:
        pass

    # 3. Check saved_playlists table in DB for cover_url
    try:
        db_p = get_archive_db_path()
        if os.path.isfile(db_p):
            with closing(sqlite3.connect(str(db_p), timeout=5.0)) as conn:
                row = conn.execute(
                    "SELECT cover_url FROM saved_playlists WHERE LOWER(name) = LOWER(?) AND cover_url IS NOT NULL AND cover_url != '' LIMIT 1",
                    (candidate_name,)
                ).fetchone()
                if row and row[0]:
                    import urllib.request
                    urllib.request.urlretrieve(row[0], cached_cover)
                    if os.path.isfile(cached_cover) and os.path.getsize(cached_cover) > 500:
                        return cached_cover
    except Exception as e:
        logger.debug(f"Could not retrieve cover_url for {candidate_name}: {e}")

    # 4. Check if a cover image exists in a directory if collection_name_or_folder was a folder
    if os.path.isdir(collection_name_or_folder) and candidate_name.lower() not in ("downloads", "music"):
        for ext in (".jpg", ".jpeg", ".png", ".webp"):
            old_cov = os.path.join(collection_name_or_folder, f"cover{ext}")
            if os.path.isfile(old_cov) and os.path.getsize(old_cov) > 500:
                try:
                    shutil.copy2(old_cov, cached_cover)
                    return cached_cover
                except Exception:
                    pass

    # 5. Extract from sample_file if provided and cache as {safe_name}.jpg
    target_audio = sample_file if (sample_file and os.path.isfile(sample_file)) else None
    if target_audio and os.path.isfile(target_audio):
        try:
            art_bytes = extract_embedded_cover(target_audio)
            if art_bytes and len(art_bytes) > 500:
                with open(cached_cover, "wb") as f:
                    f.write(art_bytes)
                logger.info(f"Cached collection cover in app cache: {cached_cover}")
                return cached_cover
        except Exception as e:
            logger.debug(f"Could not extract collection cover from audio file: {e}")

    return ""


class ArchiveManager:
    """
    Persistent SQLite Archive & Deduplication Library.
    Remembers all downloaded tracks across sessions, enables instant local reuse
    across multiple playlists without re-downloading, and powers the Completed Library view.
    """

    _instance = None
    _lock = threading.RLock()

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if not cls._instance:
                cls._instance = super(ArchiveManager, cls).__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self, db_path: Optional[str] = None):
        target_path = Path(db_path) if db_path else get_archive_db_path()
        if getattr(self, "_initialized", False) and getattr(self, "db_path", None) == target_path:
            return
        self._initialized = True
        self.db_path = target_path
        self._db_lock = threading.RLock()
        self._init_db()

    _GENERIC_ALBUMS = frozenset({"", "spotify playlist", "singles", "unknown album", "downloads"})

    @staticmethod
    def _is_generic_album(album: Any) -> bool:
        return str(album or "").strip().lower() in ArchiveManager._GENERIC_ALBUMS

    @staticmethod
    def _norm_path_key(file_path: Any, fallback_id: Any = "") -> str:
        fp = str(file_path or "").strip()
        if not fp:
            return f"__id__{fallback_id or ''}"
        return os.path.normcase(os.path.normpath(fp))

    @classmethod
    def _row_richness_key(cls, row: Dict[str, Any]) -> Tuple[int, int, int, int, int, int, int, str]:
        sid = str(row.get("spotify_id") or "")
        src = str(row.get("source_type") or "").strip()
        badge = str(row.get("quality_badge") or "").upper()
        dur = int(row.get("duration_ms") or 0)
        genre = str(row.get("genre") or "").strip()
        album = str(row.get("album") or "")
        ext = os.path.splitext(str(row.get("file_path") or ""))[1].lower()
        if "24" in badge:
            q_tier = 6
        elif ext == ".flac" or "FLAC" in badge:
            q_tier = 5
        elif ext == ".wav" or "WAV" in badge:
            q_tier = 4
        elif "320" in badge or ext == ".mp3":
            q_tier = 3
        elif ext in (".opus", ".m4a") or "OPUS" in badge or "M4A" in badge:
            q_tier = 2
        elif badge:
            q_tier = 1
        else:
            q_tier = 0
        return (
            1 if (sid and not sid.startswith("local_")) else 0,
            1 if src not in ("", "Local File", "Local Archive") else 0,
            1 if src != "Local File" else 0,
            1 if dur > 0 else 0,
            1 if bool(genre) else 0,
            0 if cls._is_generic_album(album) else 1,
            q_tier,
            str(row.get("downloaded_at") or ""),
        )

    @classmethod
    def _dedupe_track_rows(cls, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Collapses rows sharing the same physical file_path into one canonical row,
        selecting the richest metadata record and merging missing fields from siblings.
        """
        if len(rows) <= 1:
            return rows

        groups: Dict[str, List[Dict[str, Any]]] = {}
        order: List[str] = []
        for row in rows:
            key = cls._norm_path_key(row.get("file_path"), row.get("spotify_id"))
            if key not in groups:
                groups[key] = []
                order.append(key)
            groups[key].append(row)

        deduped: List[Dict[str, Any]] = []
        for key in order:
            siblings = groups[key]
            if len(siblings) == 1:
                deduped.append(siblings[0])
                continue
            winner = dict(max(siblings, key=cls._row_richness_key))
            for sib in siblings:
                if (winner.get("duration_ms") or 0) <= 0 and (sib.get("duration_ms") or 0) > 0:
                    winner["duration_ms"] = sib["duration_ms"]
                if not (winner.get("genre") or "").strip() and (sib.get("genre") or "").strip():
                    winner["genre"] = sib["genre"]
                if cls._is_generic_album(winner.get("album")) and not cls._is_generic_album(sib.get("album")):
                    winner["album"] = sib["album"]
                if not (winner.get("isrc") or "").strip() and (sib.get("isrc") or "").strip():
                    winner["isrc"] = sib["isrc"]
                if (winner.get("track_number") or 0) <= 0 and (sib.get("track_number") or 0) > 0:
                    winner["track_number"] = sib["track_number"]
                if (sib.get("file_size") or 0) > (winner.get("file_size") or 0):
                    winner["file_size"] = sib["file_size"]
                if (winner.get("artist") or "") in ("", "Unknown Artist") and (sib.get("artist") or "") not in ("", "Unknown Artist"):
                    winner["artist"] = sib["artist"]
                if (winner.get("source_type") or "") in ("", "Local File") and (sib.get("source_type") or "") not in ("", "Local File", "Local Archive"):
                    winner["source_type"] = sib["source_type"]
                    if sib.get("quality_badge"):
                        winner["quality_badge"] = sib["quality_badge"]
            deduped.append(winner)
        return deduped

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    @contextmanager
    def connection(self):
        """Thread-safe context manager guaranteeing connection closure and transaction cleanup."""
        with self._db_lock:
            conn = self._get_connection()
            try:
                yield conn
            finally:
                try:
                    conn.close()
                except Exception:
                    pass

    def _init_db(self):
        """Initializes database tables, performance indexes, and schema migrations."""
        try:
            with self.connection() as conn:
                with conn:
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS downloaded_tracks (
                            spotify_id TEXT PRIMARY KEY,
                            isrc TEXT,
                            title TEXT NOT NULL,
                            artist TEXT NOT NULL,
                            album TEXT,
                            duration_ms INTEGER,
                            track_number INTEGER DEFAULT 1,
                            disc_number INTEGER DEFAULT 1,
                            file_path TEXT NOT NULL,
                            file_size INTEGER DEFAULT 0,
                            quality_badge TEXT DEFAULT 'FLAC',
                            source_type TEXT DEFAULT 'Musilon',
                            collection_name TEXT,
                            collection_type TEXT,
                            genre TEXT DEFAULT '',
                            downloaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        );
                    """)
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_artist_title ON downloaded_tracks (artist, title);")
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_isrc ON downloaded_tracks (isrc);")
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_downloaded_at ON downloaded_tracks (downloaded_at DESC);")
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_file_path ON downloaded_tracks (file_path COLLATE NOCASE);")
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_downloaded_genre ON downloaded_tracks (genre);")

                    # Saved Playlists & Tracks Metadata Store (Decoupled ingestion from downloading)
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS saved_playlists (
                            id TEXT PRIMARY KEY,
                            name TEXT NOT NULL,
                            spotify_url TEXT,
                            cover_url TEXT,
                            total_tracks INTEGER DEFAULT 0,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        );
                    """)
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS saved_playlist_tracks (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            playlist_id TEXT NOT NULL,
                            spotify_id TEXT NOT NULL,
                            title TEXT NOT NULL,
                            artist TEXT NOT NULL,
                            album TEXT,
                            duration_ms INTEGER DEFAULT 0,
                            track_number INTEGER DEFAULT 1,
                            disc_number INTEGER DEFAULT 1,
                            isrc TEXT,
                            cover_url TEXT,
                            status TEXT DEFAULT 'pending',
                            file_path TEXT DEFAULT '',
                            quality_badge TEXT DEFAULT '',
                            source_type TEXT DEFAULT '',
                            genre TEXT DEFAULT '',
                            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            UNIQUE(playlist_id, spotify_id)
                        );
                    """)
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_saved_playlist_id ON saved_playlist_tracks (playlist_id);")
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_saved_playlist_status ON saved_playlist_tracks (playlist_id, status);")
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_saved_spotify_id ON saved_playlist_tracks (spotify_id);")
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_saved_file_path ON saved_playlist_tracks (file_path COLLATE NOCASE);")
                    # Migrations for existing databases
                    for col_stmt in [
                        "ALTER TABLE downloaded_tracks ADD COLUMN track_number INTEGER DEFAULT 1;",
                        "ALTER TABLE downloaded_tracks ADD COLUMN disc_number INTEGER DEFAULT 1;",
                        "ALTER TABLE downloaded_tracks ADD COLUMN genre TEXT DEFAULT '';",
                        "ALTER TABLE saved_playlist_tracks ADD COLUMN quality_badge TEXT DEFAULT '';",
                        "ALTER TABLE saved_playlist_tracks ADD COLUMN source_type TEXT DEFAULT '';",
                        "ALTER TABLE saved_playlist_tracks ADD COLUMN genre TEXT DEFAULT '';",
                        "ALTER TABLE saved_playlists ADD COLUMN auto_sync INTEGER DEFAULT 0;",
                        "ALTER TABLE saved_playlists ADD COLUMN last_synced_at TIMESTAMP;",
                    ]:
                        try:
                            conn.execute(col_stmt)
                        except sqlite3.OperationalError:
                            pass

                    conn.execute("CREATE INDEX IF NOT EXISTS idx_saved_genre ON saved_playlist_tracks (genre);")

                    # Check if any backfill is needed before running expensive UPDATE statements
                    cur = conn.execute("SELECT 1 FROM saved_playlist_tracks WHERE (quality_badge IS NULL OR quality_badge = '') LIMIT 1")
                    if cur.fetchone():
                        conn.execute("""
                            UPDATE saved_playlist_tracks
                            SET quality_badge = (
                                SELECT quality_badge FROM downloaded_tracks 
                                WHERE downloaded_tracks.spotify_id = saved_playlist_tracks.spotify_id
                                LIMIT 1
                            ),
                            source_type = (
                                SELECT source_type FROM downloaded_tracks 
                                WHERE downloaded_tracks.spotify_id = saved_playlist_tracks.spotify_id
                                LIMIT 1
                            )
                            WHERE (quality_badge IS NULL OR quality_badge = '')
                              AND EXISTS (
                                SELECT 1 FROM downloaded_tracks 
                                WHERE downloaded_tracks.spotify_id = saved_playlist_tracks.spotify_id
                              );
                        """)

                        conn.execute("""
                            UPDATE saved_playlist_tracks
                            SET quality_badge = CASE 
                                WHEN LOWER(file_path) LIKE '%.opus' THEN 'YTM Opus'
                                WHEN LOWER(file_path) LIKE '%.mp3' THEN 'Musilon 320k'
                                WHEN LOWER(file_path) LIKE '%.ogg' THEN 'Musilon 320k'
                                WHEN LOWER(file_path) LIKE '%.m4a' THEN 'YTM M4A'
                                WHEN LOWER(file_path) LIKE '%.flac' THEN 'FLAC 16'
                                ELSE 'FLAC 16'
                            END,
                            source_type = CASE
                                WHEN LOWER(file_path) LIKE '%.opus' THEN 'YouTube Music'
                                WHEN LOWER(file_path) LIKE '%.m4a' THEN 'YouTube Music'
                                ELSE 'Musilon'
                            END
                            WHERE status = 'downloaded' AND (quality_badge IS NULL OR quality_badge = '') AND file_path != '';
                        """)

                        # Auto-repair any .opus or .m4a files misattributed to Musilon
                        conn.execute("""
                            UPDATE downloaded_tracks
                            SET quality_badge = 'YTM Opus', source_type = 'YouTube Music'
                            WHERE LOWER(file_path) LIKE '%.opus' AND source_type != 'YouTube Music';
                        """)
                        conn.execute("""
                            UPDATE downloaded_tracks
                            SET quality_badge = 'YTM M4A', source_type = 'YouTube Music'
                            WHERE LOWER(file_path) LIKE '%.m4a' AND source_type NOT IN ('YouTube', 'YouTube Music');
                        """)
                        conn.execute("""
                            UPDATE saved_playlist_tracks
                            SET quality_badge = 'YTM Opus', source_type = 'YouTube Music'
                            WHERE LOWER(file_path) LIKE '%.opus' AND source_type != 'YouTube Music';
                        """)
                        conn.execute("""
                            UPDATE saved_playlist_tracks
                            SET quality_badge = 'YTM M4A', source_type = 'YouTube Music'
                            WHERE LOWER(file_path) LIKE '%.m4a' AND source_type NOT IN ('YouTube', 'YouTube Music');
                        """)

                    cur_g = conn.execute("SELECT 1 FROM saved_playlist_tracks WHERE (genre IS NULL OR genre = '') LIMIT 1")
                    if cur_g.fetchone():
                        conn.execute("""
                            UPDATE saved_playlist_tracks
                            SET genre = (
                                SELECT genre FROM downloaded_tracks 
                                WHERE downloaded_tracks.spotify_id = saved_playlist_tracks.spotify_id
                                LIMIT 1
                            )
                            WHERE (genre IS NULL OR genre = '')
                              AND EXISTS (
                                SELECT 1 FROM downloaded_tracks 
                                WHERE downloaded_tracks.spotify_id = saved_playlist_tracks.spotify_id
                                  AND downloaded_tracks.genre IS NOT NULL
                                  AND downloaded_tracks.genre != ''
                              );
                        """)

                    # Reset any stale 'queued' or 'stopped' tracks from previous sessions back to 'pending'
                    conn.execute("UPDATE saved_playlist_tracks SET status = 'pending' WHERE status IN ('queued', 'stopped');")

                    # Data integrity cleanup: resolve misclassified collections
                    try:
                        conn.execute("""
                            UPDATE downloaded_tracks
                            SET collection_type = 'playlist'
                            WHERE LOWER(collection_name) IN (
                                SELECT LOWER(name) FROM saved_playlists 
                                WHERE spotify_url NOT LIKE '%/album/%'
                            );
                        """)
                    except Exception as e_clean:
                        logger.debug(f"Data cleanup notice: {e_clean}")

                logger.info(f"Initialized Archive database at: {self.db_path}")
        except Exception as e:
            logger.error(f"Failed to initialize Archive database: {e}")

    def checkpoint_wal(self) -> bool:
        """Executes PRAGMA wal_checkpoint(TRUNCATE) to keep SQLite database files lean and fast."""
        try:
            with self.connection() as conn:
                with conn:
                    conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
            logger.debug("Successfully checkpointed SQLite WAL log.")
            return True
        except Exception as e:
            logger.debug(f"SQLite WAL checkpoint note: {e}")
            return False

    @staticmethod
    def infer_badge_from_file(file_path: str) -> Tuple[str, str]:
        """
        Infers (quality_badge, source_type) from audio file extension and audio headers.
        """
        if not file_path:
            return "", ""
        ext = os.path.splitext(file_path)[1].lower()
        if ext == ".flac":
            quality = "FLAC 16"
            try:
                import mutagen
                audio = mutagen.File(file_path)
                if audio and getattr(audio.info, "bits_per_sample", 16) == 24:
                    quality = "FLAC 24"
            except Exception:
                pass
            return quality, "Musilon"
        elif ext == ".opus":
            return "YTM Opus", "YouTube Music"
        elif ext == ".m4a":
            return "YTM M4A", "YouTube Music"
        elif ext in (".mp3", ".ogg"):
            return "Musilon 320k", "Musilon"
        elif ext == ".wav":
            return "WAV", "Local Archive"
        return "Audio", "Unknown"

    def add_track(
        self,
        track: TrackMetadata,
        file_path: str,
        quality_badge: str,
        source_type: str,
        file_size: int = 0,
        genre: str = ""
    ) -> bool:
        """Records or updates a successfully downloaded track in the archive."""
        if not file_path or not os.path.isfile(file_path):
            return False

        norm_path = normalize_path(file_path)
        ext = os.path.splitext(norm_path)[1].lower()
        if ext == ".opus":
            quality_badge = "YTM Opus"
            source_type = "YouTube Music"
        elif ext == ".m4a" and source_type not in ("YouTube", "YouTube Music"):
            quality_badge = "YTM M4A"
            source_type = "YouTube Music"
        if file_size <= 0:
            try:
                file_size = os.path.getsize(norm_path)
            except Exception:
                file_size = 0

        genre_val = genre or getattr(track, "genre_str", "") or ""
        title_val = track.title
        artist_val = track.artist_str
        album_val = track.album or ""
        dur_val = int(getattr(track, "duration_ms", 0) or 0)
        isrc_val = track.isrc or ""
        coll_name = getattr(track, "collection_name", "") or ""
        coll_type = getattr(track, "collection_type", "track") or "track"
        track_num_val = getattr(track, "track_number", 1) or 1
        disc_num_val = getattr(track, "disc_number", 1) or 1
        is_local_id = str(track.id or "").startswith("local_")

        try:
            with self.connection() as conn:
                with conn:
                    existing_same_fp = conn.execute(
                        "SELECT * FROM downloaded_tracks WHERE file_path = ? COLLATE NOCASE",
                        (norm_path,),
                    ).fetchall()
                    if is_local_id and any(not str(r["spotify_id"] or "").startswith("local_") for r in existing_same_fp):
                        # A real Spotify track record already owns this physical file; avoid adding a duplicate local_ row.
                        if genre_val:
                            conn.execute(
                                "UPDATE downloaded_tracks SET genre = ? WHERE file_path = ? COLLATE NOCASE AND (genre IS NULL OR TRIM(genre) = '')",
                                (genre_val, norm_path),
                            )
                        return True

                    for r in existing_same_fp:
                        if dur_val <= 0 and (r["duration_ms"] or 0) > 0:
                            dur_val = int(r["duration_ms"])
                        if not genre_val and (r["genre"] or "").strip():
                            genre_val = r["genre"].strip()
                        if self._is_generic_album(album_val) and not self._is_generic_album(r["album"]):
                            album_val = r["album"]
                        if not isrc_val and (r["isrc"] or "").strip():
                            isrc_val = r["isrc"].strip()

                    conn.execute("""
                        INSERT OR REPLACE INTO downloaded_tracks (
                            spotify_id, isrc, title, artist, album, duration_ms,
                            track_number, disc_number,
                            file_path, file_size, quality_badge, source_type,
                            collection_name, collection_type, genre, downloaded_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    """, (
                        track.id,
                        isrc_val,
                        title_val,
                        artist_val,
                        album_val,
                        dur_val,
                        track_num_val,
                        disc_num_val,
                        norm_path,
                        file_size,
                        quality_badge,
                        source_type,
                        coll_name,
                        coll_type,
                        genre_val
                    ))
                    if not is_local_id:
                        # Remove stale local_* synthetic rows pointing to this exact file
                        conn.execute(
                            "DELETE FROM downloaded_tracks WHERE spotify_id LIKE 'local_%' AND file_path = ? COLLATE NOCASE",
                            (norm_path,),
                        )
                        # Remove redundant rows in the exact same collection pointing to the same physical file
                        conn.execute(
                            """
                            DELETE FROM downloaded_tracks
                            WHERE spotify_id != ?
                              AND file_path = ? COLLATE NOCASE
                              AND LOWER(COALESCE(collection_name, '')) = LOWER(?)
                              AND COALESCE(collection_type, '') = ?
                            """,
                            (track.id, norm_path, coll_name, coll_type),
                        )
                logger.debug(f"Archived track '{track.title}' (track #{track_num_val}) -> {norm_path} [genre: {genre_val}]")
                return True
        except Exception as e:
            logger.error(f"Failed to record track in archive: {e}")
            return False

    def update_track_genre(self, file_path: str = "", genre: str = "", spotify_id: str = "") -> bool:
        """Updates the genre field for a track in SQLite archive."""
        if not genre:
            return False
        norm_path = normalize_path(file_path) if file_path else ""
        try:
            with self.connection() as conn:
                with conn:
                    if norm_path:
                        conn.execute("UPDATE downloaded_tracks SET genre = ? WHERE file_path = ?", (genre, norm_path))
                        conn.execute("UPDATE saved_playlist_tracks SET genre = ? WHERE file_path = ?", (genre, norm_path))
                    if spotify_id:
                        conn.execute("UPDATE downloaded_tracks SET genre = ? WHERE spotify_id = ?", (genre, spotify_id))
                        conn.execute("UPDATE saved_playlist_tracks SET genre = ? WHERE spotify_id = ?", (genre, spotify_id))
                return True
        except Exception as e:
            logger.error(f"Failed to update track genre in archive: {e}")
            return False

    def find_track(
        self,
        spotify_id: Any = "",
        isrc: str = "",
        title: str = "",
        artist: str = ""
    ) -> Optional[Dict[str, Any]]:
        """
        Queries archive for an existing download.
        Priority:
        1. Spotify Track ID match
        2. ISRC match
        3. Normalized Title + Artist match

        Verifies that the target file exists on disk. If missing, cleans the record.
        """
        if hasattr(spotify_id, "id"):
            track_obj = spotify_id
            spotify_id = getattr(track_obj, "id", "") or ""
            isrc = isrc or getattr(track_obj, "isrc", "") or ""
            title = title or getattr(track_obj, "title", "") or ""
            artist = artist or getattr(track_obj, "primary_artist", "") or ""

        try:
            with self.connection() as conn:
                row = None
                # 1. Check by Spotify ID
                if spotify_id:
                    cur = conn.execute("SELECT * FROM downloaded_tracks WHERE spotify_id = ? LIMIT 1", (spotify_id,))
                    row = cur.fetchone()

                # 2. Check by ISRC
                if not row and isrc:
                    cur = conn.execute("SELECT * FROM downloaded_tracks WHERE isrc = ? LIMIT 1", (isrc,))
                    row = cur.fetchone()

                # 3. Check by Artist & Title
                if not row and title and artist:
                    norm_title = title.strip().lower()
                    norm_artist = artist.strip().lower()
                    cur = conn.execute("""
                        SELECT * FROM downloaded_tracks
                        WHERE LOWER(title) = ? AND LOWER(artist) LIKE ?
                        LIMIT 1
                    """, (norm_title, f"%{norm_artist}%"))
                    row = cur.fetchone()

                if not row:
                    return None

                data = dict(row)
                file_path = data.get("file_path", "")
                if not (file_path and os.path.isfile(file_path)):
                    # Check alternative locations (output_dir or default download dir)
                    bname = os.path.basename(file_path) if file_path else ""
                    if bname:
                        for cand_dir in [
                            config.get("download.output_dir", ""),
                            str(get_default_download_dir()),
                            str(Path.home() / "Music" / "Spotify Downloads"),
                        ]:
                            if not cand_dir or not os.path.isdir(cand_dir):
                                continue
                            # Search direct and subdirectories for the basename
                            cand_p = os.path.join(cand_dir, bname)
                            if os.path.isfile(cand_p):
                                file_path = cand_p
                                norm_cand = normalize_path(cand_p)
                                data["file_path"] = norm_cand
                                with conn:
                                    conn.execute("UPDATE downloaded_tracks SET file_path = ? WHERE spotify_id = ?", (norm_cand, data["spotify_id"]))
                                break
                            # Also check collection subfolders
                            coll_name = data.get("collection_name") or ""
                            if coll_name:
                                cand_sub = os.path.join(cand_dir, coll_name, bname)
                                if os.path.isfile(cand_sub):
                                    file_path = cand_sub
                                    norm_cand = normalize_path(cand_sub)
                                    data["file_path"] = norm_cand
                                    with conn:
                                        conn.execute("UPDATE downloaded_tracks SET file_path = ? WHERE spotify_id = ?", (norm_cand, data["spotify_id"]))
                                    break

                if file_path and os.path.isfile(file_path):
                    is_valid, reason = is_valid_audio_file(file_path)
                    if is_valid:
                        return data
                    else:
                        logger.warning(f"Archived file '{file_path}' failed integrity check ({reason}). Purging corrupt record.")
                        try:
                            os.remove(file_path)
                        except Exception:
                            pass
                        with conn:
                            conn.execute("DELETE FROM downloaded_tracks WHERE spotify_id = ?", (data["spotify_id"],))
                        return None
                else:
                    # File was deleted from disk; remove stale record
                    logger.info(f"Archived file deleted from disk: {file_path}. Cleaning record.")
                    with conn:
                        conn.execute("DELETE FROM downloaded_tracks WHERE spotify_id = ?", (data["spotify_id"],))
                    return None

        except Exception as e:
            logger.error(f"Error querying archive: {e}")
            return None

    def get_track_by_path(self, file_path: str) -> Optional[Dict[str, Any]]:
        """Queries archive for a track by its absolute or normalized file_path."""
        if not file_path:
            return None
        norm_p = normalize_path(file_path)
        try:
            with self.connection() as conn:
                cur = conn.execute("SELECT * FROM downloaded_tracks WHERE file_path = ? COLLATE NOCASE LIMIT 1", (norm_p,))
                row = cur.fetchone()
                if not row:
                    # Also try matching by basename
                    bname = os.path.basename(file_path)
                    cur = conn.execute("SELECT * FROM downloaded_tracks WHERE file_path LIKE ? LIMIT 1", (f"%{bname}%",))
                    row = cur.fetchone()
                return dict(row) if row else None
        except Exception as e:
            logger.debug(f"Error finding track by path: {e}")
            return None

    def get_all_genres(self) -> List[str]:
        """Returns all distinct, sorted genre tokens present across downloaded tracks."""
        try:
            with self.connection() as conn:
                cur = conn.execute("SELECT DISTINCT genre FROM downloaded_tracks WHERE genre IS NOT NULL AND TRIM(genre) != ''")
                genres = set()
                for r in cur.fetchall():
                    raw = r["genre"] if isinstance(r, sqlite3.Row) else r[0]
                    for g in raw.split(";"):
                        g_clean = g.strip()
                        if g_clean:
                            genres.add(g_clean)
                return sorted(list(genres))
        except Exception as e:
            logger.debug(f"Failed to fetch genres: {e}")
            return []

    def get_all_tracks(self, search_query: str = "", genre_filter: str = "") -> List[Dict[str, Any]]:
        """Retrieves all archived tracks, optionally filtered by title/artist/album or genre."""
        try:
            with self.connection() as conn:
                conditions = []
                params = []
                if search_query:
                    q = f"%{search_query.strip().lower()}%"
                    conditions.append("(LOWER(title) LIKE ? OR LOWER(artist) LIKE ? OR LOWER(album) LIKE ? OR LOWER(collection_name) LIKE ?)")
                    params.extend([q, q, q, q])
                if genre_filter and genre_filter.strip().lower() not in ("", "all genres"):
                    g = f"%{genre_filter.strip().lower()}%"
                    conditions.append("LOWER(genre) LIKE ?")
                    params.append(g)

                sql = "SELECT * FROM downloaded_tracks"
                if conditions:
                    sql += " WHERE " + " AND ".join(conditions)
                sql += " ORDER BY downloaded_at DESC"

                cur = conn.execute(sql, tuple(params))
                return self._dedupe_track_rows([dict(row) for row in cur.fetchall()])
        except Exception as e:
            logger.error(f"Failed to fetch archive tracks: {e}")
            return []

    def get_track_count(self) -> int:
        """Returns total unique valid tracks stored in archive."""
        try:
            with self.connection() as conn:
                cur = conn.execute(
                    "SELECT COUNT(DISTINCT COALESCE(NULLIF(LOWER(file_path), ''), spotify_id)) FROM downloaded_tracks"
                )
                return cur.fetchone()[0]
        except Exception:
            return 0

    def get_library_stats(self) -> Dict[str, Any]:
        """Returns high-level statistics for the offline music library."""
        try:
            with self.connection() as conn:
                cur = conn.execute("""
                    SELECT 
                        (
                            SELECT COUNT(*) FROM (
                                SELECT COALESCE(NULLIF(LOWER(file_path), ''), spotify_id) as fp_key
                                FROM downloaded_tracks
                                GROUP BY fp_key
                            )
                        ) as total_tracks,
                        COUNT(DISTINCT CASE WHEN (collection_type = 'playlist' OR (collection_name IS NOT NULL AND collection_name != ''))
                                             AND (collection_type IS NULL OR collection_type != 'album')
                                             AND LOWER(COALESCE(NULLIF(collection_name, ''), 'Singles')) NOT IN (
                                                 SELECT DISTINCT LOWER(COALESCE(NULLIF(album, ''), collection_name))
                                                 FROM downloaded_tracks
                                                 WHERE collection_type = 'album'
                                             )
                                        THEN LOWER(COALESCE(NULLIF(collection_name, ''), 'Singles')) END) as total_playlists,
                        COUNT(DISTINCT CASE WHEN collection_type = 'album'
                                             AND LOWER(COALESCE(NULLIF(album, ''), collection_name)) NOT IN (
                                                 'spotify playlist', 'singles', 'unknown album', 'downloads'
                                             )
                                        THEN LOWER(COALESCE(NULLIF(album, ''), collection_name)) END) as total_albums,
                        (
                            SELECT COALESCE(SUM(max_size), 0) FROM (
                                SELECT MAX(COALESCE(file_size, 0)) as max_size
                                FROM downloaded_tracks
                                GROUP BY COALESCE(NULLIF(LOWER(file_path), ''), spotify_id)
                            )
                        ) as total_bytes
                    FROM downloaded_tracks
                """)
                row = cur.fetchone()
                total_bytes = row["total_bytes"]
                if total_bytes >= 1024 * 1024 * 1024:
                    size_str = f"{total_bytes / (1024 ** 3):.2f} GB"
                else:
                    size_str = f"{total_bytes / (1024 ** 2):.1f} MB"

                return {
                    "total_tracks": row["total_tracks"],
                    "total_playlists": row["total_playlists"],
                    "total_albums": row["total_albums"],
                    "total_bytes": total_bytes,
                    "size_str": size_str
                }
        except Exception as e:
            logger.error(f"Failed to fetch library stats: {e}")
            return {"total_tracks": 0, "total_playlists": 0, "total_albums": 0, "total_bytes": 0, "size_str": "0 MB"}

    def get_playlists(self, search_query: str = "", genre_filter: str = "") -> List[Dict[str, Any]]:
        """
        Aggregates downloaded tracks by collection / playlist folder.
        Returns a list of playlists with track counts, total size, folder paths, sample tracks, and genres.
        Excludes albums (which strictly belong in get_albums).
        """
        try:
            with self.connection() as conn:
                cur = conn.execute("""
                    SELECT 
                        col_name as name,
                        COALESCE(MAX(CASE WHEN collection_type = 'playlist' THEN 'playlist' END), MAX(collection_type)) as collection_type,
                        COUNT(*) as track_count,
                        COALESCE(SUM(file_size), 0) as total_size,
                        MIN(file_path) as sample_file,
                        MAX(downloaded_at) as latest_download,
                        GROUP_CONCAT(DISTINCT genre) as all_genres
                    FROM (
                        SELECT
                            COALESCE(NULLIF(collection_name, ''), 'Singles') as col_name,
                            LOWER(COALESCE(NULLIF(collection_name, ''), 'Singles')) as col_key,
                            COALESCE(NULLIF(LOWER(file_path), ''), spotify_id) as fp_key,
                            MAX(collection_type) as collection_type,
                            MAX(COALESCE(file_size, 0)) as file_size,
                            MIN(file_path) as file_path,
                            MAX(downloaded_at) as downloaded_at,
                            GROUP_CONCAT(DISTINCT NULLIF(genre, '')) as genre
                        FROM downloaded_tracks
                        WHERE (collection_type IS NULL OR collection_type != 'album')
                          AND LOWER(COALESCE(NULLIF(collection_name, ''), 'Singles')) NOT IN (
                              SELECT DISTINCT LOWER(COALESCE(NULLIF(album, ''), collection_name))
                              FROM downloaded_tracks
                              WHERE collection_type = 'album'
                          )
                        GROUP BY col_key, fp_key
                    )
                    GROUP BY col_key
                    ORDER BY latest_download DESC
                """)
                rows = cur.fetchall()
                results: List[Dict[str, Any]] = []
                q = search_query.strip().lower()

                for r in rows:
                    pl_name = r["name"]
                    if q and q not in pl_name.lower():
                        continue

                    # Parse genres
                    all_genres_raw = r["all_genres"] or ""
                    genre_tokens = set()
                    for g_chunk in all_genres_raw.split(";"):
                        for token in g_chunk.split(","):
                            clean_t = token.strip()
                            if clean_t:
                                genre_tokens.add(clean_t)

                    if genre_filter and genre_filter.strip().lower() not in ("", "all genres"):
                        gf_lower = genre_filter.strip().lower()
                        if not any(gf_lower in t.lower() for t in genre_tokens):
                            continue

                    primary_genre = sorted(list(genre_tokens))[0] if genre_tokens else ""

                    sample_file = r["sample_file"] or ""
                    folder_path = os.path.dirname(sample_file) if sample_file else ""
                    if not folder_path or not os.path.isdir(folder_path):
                        base_dir = config.get("download.output_dir", "downloads")
                        folder_path = os.path.join(base_dir, pl_name)

                    sz_bytes = r["total_size"]
                    if sz_bytes >= 1024 * 1024 * 1024:
                        sz_str = f"{sz_bytes / (1024 ** 3):.2f} GB"
                    else:
                        sz_str = f"{sz_bytes / (1024 ** 2):.1f} MB"

                    cover_path = resolve_collection_cover(pl_name, sample_file)

                    results.append({
                        "name": pl_name,
                        "collection_type": r["collection_type"] or "playlist",
                        "track_count": r["track_count"],
                        "total_size_bytes": sz_bytes,
                        "size_str": sz_str,
                        "folder_path": folder_path,
                        "cover_path": cover_path,
                        "latest_download": r["latest_download"],
                        "genre": primary_genre,
                        "genres": sorted(list(genre_tokens))
                    })
                return results
        except Exception as e:
            logger.error(f"Failed to aggregate playlists: {e}")
            return []

    def get_albums(self, search_query: str = "", genre_filter: str = "") -> List[Dict[str, Any]]:
        """
        Aggregates downloaded tracks by album.
        Only returns genuine albums (grouped by album name with predominant artist),
        excluding playlists, singles, and compilation placeholders.
        """
        try:
            with self.connection() as conn:
                cur = conn.execute("""
                    SELECT 
                        alb_name as name,
                        COUNT(*) as track_count,
                        COALESCE(SUM(file_size), 0) as total_size,
                        MIN(file_path) as sample_file,
                        MAX(downloaded_at) as latest_download,
                        GROUP_CONCAT(DISTINCT genre) as all_genres,
                        (
                            SELECT t2.artist 
                            FROM downloaded_tracks t2 
                            WHERE LOWER(COALESCE(NULLIF(t2.album, ''), t2.collection_name)) = sub.alb_key
                            GROUP BY t2.artist 
                            ORDER BY COUNT(*) DESC, MIN(t2.track_number) ASC 
                            LIMIT 1
                        ) as primary_artist
                    FROM (
                        SELECT
                            COALESCE(NULLIF(album, ''), collection_name) as alb_name,
                            LOWER(COALESCE(NULLIF(album, ''), collection_name)) as alb_key,
                            COALESCE(NULLIF(LOWER(file_path), ''), spotify_id) as fp_key,
                            MAX(COALESCE(file_size, 0)) as file_size,
                            MIN(file_path) as file_path,
                            MAX(downloaded_at) as downloaded_at,
                            GROUP_CONCAT(DISTINCT NULLIF(genre, '')) as genre
                        FROM downloaded_tracks
                        WHERE collection_type = 'album'
                          AND LOWER(COALESCE(NULLIF(album, ''), collection_name)) NOT IN (
                              'spotify playlist', 'singles', 'unknown album', 'downloads'
                          )
                        GROUP BY alb_key, fp_key
                    ) sub
                    GROUP BY alb_key
                    ORDER BY track_count DESC, latest_download DESC
                """)
                rows = cur.fetchall()
                results: List[Dict[str, Any]] = []
                q = search_query.strip().lower()

                for r in rows:
                    alb_name = r["name"]
                    artist_name = r["primary_artist"] or ""
                    if q and (q not in alb_name.lower() and q not in artist_name.lower()):
                        continue

                    # Parse genres
                    all_genres_raw = r["all_genres"] or ""
                    genre_tokens = set()
                    for g_chunk in all_genres_raw.split(";"):
                        for token in g_chunk.split(","):
                            clean_t = token.strip()
                            if clean_t:
                                genre_tokens.add(clean_t)

                    if genre_filter and genre_filter.strip().lower() not in ("", "all genres"):
                        gf_lower = genre_filter.strip().lower()
                        if not any(gf_lower in t.lower() for t in genre_tokens):
                            continue

                    primary_genre = sorted(list(genre_tokens))[0] if genre_tokens else ""

                    sample_file = r["sample_file"] or ""
                    folder_path = os.path.dirname(sample_file) if sample_file else ""

                    sz_bytes = r["total_size"]
                    if sz_bytes >= 1024 * 1024 * 1024:
                        sz_str = f"{sz_bytes / (1024 ** 3):.2f} GB"
                    else:
                        sz_str = f"{sz_bytes / (1024 ** 2):.1f} MB"

                    cover_path = resolve_collection_cover(alb_name, sample_file)

                    results.append({
                        "name": alb_name,
                        "artist": artist_name,
                        "track_count": r["track_count"],
                        "total_size_bytes": sz_bytes,
                        "size_str": sz_str,
                        "folder_path": folder_path,
                        "cover_path": cover_path,
                        "latest_download": r["latest_download"],
                        "genre": primary_genre,
                        "genres": sorted(list(genre_tokens))
                    })
                return results
        except Exception as e:
            logger.error(f"Failed to aggregate albums: {e}")
            return []

    def get_collection_tracks(self, collection_name: str, collection_type: str = "playlist", genre_filter: str = "") -> List[Dict[str, Any]]:
        """Retrieves all tracks belonging to a specific collection (playlist or album) ordered by track number."""
        try:
            with self.connection() as conn:
                if collection_type == "album":
                    cur = conn.execute("""
                        SELECT * FROM downloaded_tracks
                        WHERE (LOWER(album) = LOWER(?) OR LOWER(collection_name) = LOWER(?))
                          AND (collection_type = 'album' OR collection_type IS NULL)
                        ORDER BY disc_number ASC, track_number ASC, title ASC
                    """, (collection_name, collection_name))
                else:
                    cur = conn.execute("""
                        SELECT * FROM downloaded_tracks
                        WHERE (LOWER(collection_name) = LOWER(?)
                           OR (LOWER(?) = 'singles' AND (collection_name IS NULL OR collection_name = '' OR LOWER(collection_name) = 'singles')))
                          AND (collection_type IS NULL OR collection_type != 'album')
                        ORDER BY title ASC, downloaded_at ASC
                    """, (collection_name, collection_name))
                results = []
                gf = genre_filter.strip().lower() if genre_filter and genre_filter.strip().lower() not in ("", "all genres") else ""
                for row in cur.fetchall():
                    item = dict(row)
                    if gf and gf not in (item.get("genre") or "").lower():
                        continue
                    results.append(item)
                return self._dedupe_track_rows(results)
        except Exception as e:
            logger.error(f"Failed to fetch collection tracks for '{collection_name}': {e}")
            return []

    def remove_downloaded_track(self, spotify_id: str, playlist_id: Optional[str] = None) -> bool:
        """
        Removes a track from downloaded_tracks and resets its status in saved_playlist_tracks to 'pending'.
        If playlist_id is provided, only that playlist's track status is reset; otherwise all saved playlists.
        """
        if not spotify_id:
            return False
        try:
            with self.connection() as conn:
                with conn:
                    conn.execute("DELETE FROM downloaded_tracks WHERE spotify_id = ?", (spotify_id,))
                    if playlist_id:
                        conn.execute("""
                            UPDATE saved_playlist_tracks 
                            SET status = 'pending', file_path = '', quality_badge = '', source_type = ''
                            WHERE playlist_id = ? AND spotify_id = ?
                        """, (playlist_id, spotify_id))
                    else:
                        conn.execute("""
                            UPDATE saved_playlist_tracks 
                            SET status = 'pending', file_path = '', quality_badge = '', source_type = ''
                            WHERE spotify_id = ?
                        """, (spotify_id,))

                    if playlist_id:
                        conn.execute("""
                            UPDATE saved_playlists 
                            SET total_tracks = (SELECT COUNT(*) FROM saved_playlist_tracks WHERE playlist_id = ?)
                            WHERE id = ?
                        """, (playlist_id, playlist_id))
                    else:
                        conn.execute("""
                            UPDATE saved_playlists 
                            SET total_tracks = (SELECT COUNT(*) FROM saved_playlist_tracks WHERE playlist_id = saved_playlists.id)
                        """)
                logger.info(f"Removed downloaded track {spotify_id} from archive and reset to pending.")
                return True
        except Exception as e:
            logger.error(f"Failed to remove downloaded track {spotify_id}: {e}")
            return False

    def remove_downloaded_tracks_by_path(self, file_path: str) -> int:
        """
        Removes all downloaded_tracks rows referencing file_path and resets matching
        saved_playlist_tracks rows to pending. Used when a shared file is deleted from disk.
        """
        if not file_path:
            return 0
        norm_fp = normalize_path(file_path)
        try:
            with self.connection() as conn:
                with conn:
                    cur = conn.execute(
                        "DELETE FROM downloaded_tracks WHERE file_path = ? COLLATE NOCASE",
                        (norm_fp,),
                    )
                    conn.execute(
                        """
                        UPDATE saved_playlist_tracks
                        SET status = 'pending', file_path = '', quality_badge = '', source_type = ''
                        WHERE file_path = ? COLLATE NOCASE
                        """,
                        (norm_fp,),
                    )
                    return cur.rowcount or 0
        except Exception as e:
            logger.debug(f"Failed to remove tracks by path '{file_path}': {e}")
            return 0

    def delete_track(self, spotify_id: str) -> bool:
        """Deletes a track from the archive record and resets any associated playlist tracks."""
        return self.remove_downloaded_track(spotify_id)

    def reconcile_playlist_files(self, playlist_id: Optional[str] = None) -> Dict[str, int]:
        """
        Scans saved_playlist_tracks (and downloaded_tracks) and reconciles against files on disk.
        - If a file path was moved/reorganized, updates file_path.
        - If an audio file was deleted from disk, updates status to 'pending' and removes the record
          from downloaded_tracks.
        - Synchronizes saved_playlists.total_tracks with the actual count of tracks in saved_playlist_tracks.
        """
        reconciled = 0
        repaired = 0
        out_dir = config.get("download.output_dir", "downloads")
        cand_dirs = [out_dir]
        try:
            from core.utils import get_default_download_dir
            cand_dirs.append(str(get_default_download_dir()))
        except Exception:
            pass

        try:
            with self.connection() as conn:
                # 1. First ensure total_tracks is synchronized with actual row count in saved_playlist_tracks
                if playlist_id:
                    conn.execute("""
                        UPDATE saved_playlists 
                        SET total_tracks = (
                            SELECT COUNT(*) FROM saved_playlist_tracks WHERE playlist_id = saved_playlists.id
                        )
                        WHERE id = ?
                    """, (playlist_id,))
                else:
                    conn.execute("""
                        UPDATE saved_playlists 
                        SET total_tracks = (
                            SELECT COUNT(*) FROM saved_playlist_tracks WHERE playlist_id = saved_playlists.id
                        )
                    """)

                # 2. Query tracks marked as downloaded
                sql = """
                    SELECT s.id, s.playlist_id, s.spotify_id, s.title, s.artist, s.album,
                           s.file_path as s_path, d.file_path as d_path, p.name as playlist_name
                    FROM saved_playlist_tracks s
                    LEFT JOIN downloaded_tracks d ON s.spotify_id = d.spotify_id
                    LEFT JOIN saved_playlists p ON s.playlist_id = p.id
                    WHERE s.status = 'downloaded'
                """
                params = []
                if playlist_id:
                    sql += " AND s.playlist_id = ?"
                    params.append(playlist_id)

                rows = conn.execute(sql, tuple(params)).fetchall()
                candidates = [dict(r) for r in rows]

            # Reconcile paths outside the read transaction to avoid locks
            missing_row_ids = []
            missing_sp_ids = []
            repaired_paths = []  # (new_path, s_id)

            for r in candidates:
                sp = r.get("s_path")
                dp = r.get("d_path")
                if sp and os.path.isfile(sp):
                    continue
                if dp and os.path.isfile(dp):
                    repaired_paths.append((dp, r["id"]))
                    continue

                bname = os.path.basename(sp) if sp else (os.path.basename(dp) if dp else "")
                found_path = None
                if bname:
                    pl_name = r.get("playlist_name") or ""
                    from core.utils import sanitize_filename
                    safe_pl = sanitize_filename(pl_name) if pl_name else ""
                    for c_dir in cand_dirs:
                        if not c_dir or not os.path.isdir(c_dir):
                            continue
                        if safe_pl:
                            p_sub = os.path.join(c_dir, safe_pl, bname)
                            if os.path.isfile(p_sub):
                                found_path = p_sub
                                break
                        p_direct = os.path.join(c_dir, bname)
                        if os.path.isfile(p_direct):
                            found_path = p_direct
                            break

                if found_path:
                    repaired_paths.append((found_path, r["id"]))
                else:
                    missing_row_ids.append(r["id"])
                    missing_sp_ids.append(r["spotify_id"])

            if repaired_paths or missing_row_ids:
                with self.connection() as conn:
                    with conn:
                        for new_p, sid in repaired_paths:
                            conn.execute("UPDATE saved_playlist_tracks SET file_path = ? WHERE id = ?", (new_p, sid))
                        repaired = len(repaired_paths)

                        if missing_row_ids:
                            chunk_size = 500
                            for i in range(0, len(missing_row_ids), chunk_size):
                                chunk_ids = missing_row_ids[i:i + chunk_size]
                                p = ",".join("?" for _ in chunk_ids)
                                conn.execute(
                                    f"UPDATE saved_playlist_tracks SET status = 'pending', file_path = '', quality_badge = '', source_type = '' WHERE id IN ({p})",
                                    chunk_ids
                                )
                            for i in range(0, len(missing_sp_ids), chunk_size):
                                chunk_sp = missing_sp_ids[i:i + chunk_size]
                                p = ",".join("?" for _ in chunk_sp)
                                conn.execute(
                                    f"DELETE FROM downloaded_tracks WHERE spotify_id IN ({p})",
                                    chunk_sp
                                )
                            reconciled = len(missing_row_ids)

                        if playlist_id:
                            conn.execute("""
                                UPDATE saved_playlists 
                                SET total_tracks = (SELECT COUNT(*) FROM saved_playlist_tracks WHERE playlist_id = ?) 
                                WHERE id = ?
                            """, (playlist_id, playlist_id))
                        else:
                            conn.execute("""
                                UPDATE saved_playlists 
                                SET total_tracks = (SELECT COUNT(*) FROM saved_playlist_tracks WHERE playlist_id = saved_playlists.id)
                            """)

            if reconciled > 0 or repaired > 0:
                logger.info(f"Reconciled playlist files: {repaired} repaired, {reconciled} deleted tracks reset to pending.")
            return {"reconciled": reconciled, "repaired": repaired}
        except Exception as e:
            logger.error(f"Failed to reconcile playlist files: {e}")
            return {"reconciled": 0, "repaired": 0}

    def scan_and_index_directory(self, root_dir: str) -> int:
        """
        Scans a directory (e.g. downloads/) for existing audio files and indexes them.
        Extracts metadata using mutagen or filename patterns.
        Returns the number of newly indexed tracks.
        """
        if not os.path.isdir(root_dir):
            return 0

        audio_exts = {".flac", ".mp3", ".opus", ".m4a", ".wav"}
        indexed_count = 0

        try:
            import mutagen
            from mutagen.flac import FLAC
            from mutagen.mp4 import MP4
            from mutagen.oggopus import OggOpus
        except ImportError:
            mutagen = None

        import hashlib

        # Pre-load existing indexed paths and metadata into memory to avoid thousands
        # of per-file SQLite connections and lock acquisitions during directory walk.
        existing_paths = set()
        existing_meta = set()
        album_collections = set()
        playlist_collections = set()
        try:
            with self.connection() as conn:
                cur = conn.execute("SELECT file_path, LOWER(title), LOWER(artist), LOWER(COALESCE(collection_name, '')), LOWER(COALESCE(album, '')) FROM downloaded_tracks")
                for r_path, r_title, r_artist, r_col, r_alb in cur.fetchall():
                    if r_path:
                        existing_paths.add(os.path.normcase(normalize_path(r_path)))
                    if r_title and r_artist:
                        if r_col:
                            existing_meta.add((r_title, r_artist, r_col))
                        if r_alb:
                            existing_meta.add((r_title, r_artist, r_alb))
                cur2 = conn.execute("SELECT LOWER(collection_name), LOWER(album) FROM downloaded_tracks WHERE collection_type = 'album'")
                for r_col, r_alb in cur2.fetchall():
                    if r_col:
                        album_collections.add(r_col)
                    if r_alb:
                        album_collections.add(r_alb)
                cur3 = conn.execute("SELECT LOWER(name) FROM saved_playlists")
                for r in cur3.fetchall():
                    if r[0]:
                        playlist_collections.add(r[0])
                cur4 = conn.execute("SELECT DISTINCT LOWER(collection_name) FROM downloaded_tracks WHERE collection_type = 'playlist'")
                for r in cur4.fetchall():
                    if r[0]:
                        playlist_collections.add(r[0])
        except Exception as e:
            logger.warning(f"Failed to prefetch existing tracks for scan: {e}")

        skip_dir_names = {"lyrics", "cache", "logs", "bin", "eq_preview", "spectrograms"}
        for dirpath, dirs, filenames in os.walk(root_dir):
            dirs[:] = [d for d in dirs if d.lower() not in skip_dir_names]
            folder_name = os.path.basename(dirpath)
            for fname in filenames:
                fname_lower = fname.lower()
                if fname_lower.endswith(".part") or ".norm_tmp" in fname_lower:
                    continue
                ext = os.path.splitext(fname)[1].lower()
                if ext not in audio_exts:
                    continue

                full_path = normalize_path(os.path.join(dirpath, fname))
                if os.path.normcase(full_path) in existing_paths:
                    continue

                is_valid, _ = is_valid_audio_file(full_path)
                if not is_valid:
                    continue

                # Extract basic tags
                title = os.path.splitext(fname)[0]
                artist = "Unknown Artist"
                album = folder_name
                isrc = ""
                track_num = 0
                disc_num = 1
                duration_ms = 0
                genre_str = ""
                quality = "FLAC 16" if ext == ".flac" else ("320k" if ext == ".mp3" else "Opus")

                if " - " in title:
                    parts = title.split(" - ", 1)
                    artist = parts[0].strip()
                    title = parts[1].strip()

                # Check if already in database by (title, artist, collection)
                f_name_lower = folder_name.lower()
                if (title.lower(), artist.lower(), f_name_lower) in existing_meta:
                    continue

                if mutagen:
                    try:
                        audio = mutagen.File(full_path)
                        if audio:
                            if getattr(audio, "info", None) and getattr(audio.info, "length", 0):
                                duration_ms = int(float(audio.info.length) * 1000)

                            tr_val = audio.get("tracknumber") or audio.get("TRACKNUMBER") or audio.get("trkn") or audio.get("TRCK")
                            if tr_val:
                                raw_t = tr_val[0] if isinstance(tr_val, list) else str(tr_val)
                                if isinstance(raw_t, tuple):
                                    raw_t = raw_t[0]
                                try:
                                    t_parsed = int(str(raw_t).split("/")[0])
                                    if t_parsed > 0:
                                        track_num = t_parsed
                                except Exception:
                                    pass

                            disc_val = audio.get("discnumber") or audio.get("DISCNUMBER") or audio.get("disk") or audio.get("TPOS")
                            if disc_val:
                                raw_d = disc_val[0] if isinstance(disc_val, list) else str(disc_val)
                                if isinstance(raw_d, tuple):
                                    raw_d = raw_d[0]
                                try:
                                    d_parsed = int(str(raw_d).split("/")[0])
                                    if d_parsed > 0:
                                        disc_num = d_parsed
                                except Exception:
                                    pass

                            g_raw = audio.get("genre") or audio.get("GENRE") or audio.get("\xa9gen")
                            if not g_raw and hasattr(audio, "keys"):
                                for gk in audio.keys():
                                    if str(gk).startswith("TCON"):
                                        g_raw = getattr(audio[gk], "text", None)
                                        break
                            if g_raw:
                                if isinstance(g_raw, (list, tuple)):
                                    genre_str = "; ".join(str(x).strip() for x in g_raw if str(x).strip())
                                else:
                                    genre_str = str(g_raw).strip()

                            if ext == ".flac":
                                artist = audio.get("artist", [artist])[0]
                                title = audio.get("title", [title])[0]
                                album = audio.get("album", [album])[0]
                                isrc = audio.get("isrc", [""])[0]
                                quality = "FLAC 24" if getattr(audio.info, "bits_per_sample", 16) == 24 else "FLAC 16"
                            elif ext == ".mp3":
                                artist = audio.get("TPE1", [artist])[0] if hasattr(audio, "get") else artist
                                title = audio.get("TIT2", [title])[0] if hasattr(audio, "get") else title
                                album = audio.get("TALB", [album])[0] if hasattr(audio, "get") else album
                            elif ext == ".opus":
                                artist = audio.get("artist", [artist])[0]
                                title = audio.get("title", [title])[0]
                                album = audio.get("album", [album])[0]
                                quality = "YTM Opus"
                    except Exception:
                        pass

                # Check if this folder belongs to an album (in-memory lookup)
                is_album = False
                if f_name_lower not in playlist_collections and f_name_lower not in ("singles", "downloads"):
                    if f_name_lower in album_collections:
                        is_album = True
                    elif album:
                        alb_lower = album.lower()
                        if alb_lower in album_collections or (f_name_lower == alb_lower and alb_lower not in playlist_collections):
                            is_album = True

                if is_album:
                    c_type = "album"
                    if track_num == 0:
                        m_num = TRACK_PREFIX_PATTERN.match(fname)
                        if m_num:
                            try:
                                track_num = int(m_num.group(1))
                            except Exception:
                                pass
                elif folder_name in ("Singles", "downloads"):
                    c_type = "track"
                    track_num = 0
                else:
                    c_type = "playlist"
                    track_num = 0

                # Deterministic synthetic ID derived from path hash
                path_hash = hashlib.sha256(full_path.lower().encode("utf-8")).hexdigest()[:16]
                synth_id = f"local_{path_hash}"
                genres_list = [g.strip() for g in genre_str.split(";") if g.strip()]
                fake_track = TrackMetadata(
                    id=synth_id,
                    title=title,
                    artists=[artist],
                    album=album,
                    release_date="",
                    duration_ms=duration_ms,
                    track_number=track_num,
                    disc_number=disc_num,
                    isrc=isrc,
                    collection_name=folder_name,
                    collection_type=c_type,
                    genres=genres_list,
                )

                if self.add_track(fake_track, full_path, quality, "Local File", genre=genre_str):
                    indexed_count += 1
                    existing_paths.add(os.path.normcase(full_path))
                    existing_meta.add((title.lower(), artist.lower(), f_name_lower))
                    if is_album:
                        album_collections.add(f_name_lower)

        if indexed_count > 0:
            logger.info(f"Scanned {root_dir} and indexed {indexed_count} existing tracks into Archive.")
        return indexed_count

    def purge_corrupt_and_cleanup_library(self, downloads_dir: Optional[str] = None) -> Dict[str, int]:
        """
        Comprehensive library cleaner and integrity restorer:
        1. Purges all unplayable/corrupt HTML files (< 500KB with HTML header) from disk and archive.db.
        2. Eliminates all hidden .cover_synced marker files.
        3. Migrates folder cover.jpg files to cache/covers/ and removes them from the music folder.
        4. Reorganizes .lrc files into a dedicated lyrics/ subfolder if present.
        Returns a dict of counts for each action performed.
        """
        from core.config import config
        target_dir = downloads_dir or config.get("download.output_dir", "")
        if not target_dir or not os.path.isdir(target_dir):
            return {"purged_corrupt_files": 0, "purged_db_records": 0, "removed_marker_files": 0, "relocated_covers": 0, "reorganized_lyrics": 0}

        covers_dir = str(get_covers_dir())

        stats = {
            "purged_corrupt_files": 0,
            "purged_db_records": 0,
            "removed_marker_files": 0,
            "relocated_covers": 0,
            "reorganized_lyrics": 0
        }

        purged_paths = set()

        # 1. Walk downloads_dir to clean files
        for root, dirs, files in os.walk(target_dir):
            for fname in files:
                fpath = os.path.join(root, fname)
                ext = os.path.splitext(fname)[1].lower()

                # Check for .cover_synced
                if fname == ".cover_synced":
                    try:
                        os.remove(fpath)
                        stats["removed_marker_files"] += 1
                        logger.info(f"Removed marker file: {fpath}")
                    except Exception as e:
                        logger.warning(f"Could not remove marker file {fpath}: {e}")
                    continue

                # Check for cover.jpg / cover.png
                if fname.lower() in ("cover.jpg", "cover.jpeg", "cover.png", "folder.jpg"):
                    folder_name = os.path.basename(root)
                    safe_folder = sanitize_filename(folder_name, max_length=50)
                    cached_dest = os.path.join(covers_dir, f"{safe_folder}.jpg")
                    try:
                        if not os.path.isfile(cached_dest) and os.path.getsize(fpath) > 500:
                            shutil.copy2(fpath, cached_dest)
                        os.remove(fpath)
                        stats["relocated_covers"] += 1
                        logger.info(f"Relocated cover art from {fpath} to {cached_dest}")
                    except Exception as e:
                        logger.warning(f"Could not relocate cover {fpath}: {e}")
                    continue

                # Check audio files for HTML corruption
                if ext in (".flac", ".mp3", ".opus", ".m4a", ".ogg"):
                    valid, reason = is_valid_audio_file(fpath)
                    if not valid:
                        try:
                            os.remove(fpath)
                            purged_paths.add(os.path.normpath(fpath).lower())
                            stats["purged_corrupt_files"] += 1
                            logger.info(f"Purged corrupt non-audio file ({reason}): {fpath}")
                        except Exception as e:
                            logger.warning(f"Could not remove corrupt file {fpath}: {e}")
                    continue

                # Check .lrc files if separate_folder mode is preferred
                if ext == ".lrc" and os.path.basename(root).lower() != "lyrics":
                    lyrics_mode = config.get("download.lyrics_mode", "embedded_only")
                    if lyrics_mode in ("separate_folder", "embedded_only"):
                        # Move to a clean lyrics/ subfolder so user's main song folder is purely audio
                        lyrics_sub = os.path.join(root, "lyrics")
                        os.makedirs(lyrics_sub, exist_ok=True)
                        dest_lrc = os.path.join(lyrics_sub, fname)
                        try:
                            shutil.move(fpath, dest_lrc)
                            stats["reorganized_lyrics"] += 1
                            logger.info(f"Moved .lrc to lyrics subfolder: {dest_lrc}")
                        except Exception as e:
                            logger.warning(f"Could not move .lrc file {fpath}: {e}")

        # 2. Clean database records for purged or non-existent files
        try:
            with self.connection() as conn:
                cur = conn.execute("SELECT spotify_id, file_path FROM downloaded_tracks")
                rows = cur.fetchall()
                ids_to_delete = []
                for r in rows:
                    p = r["file_path"]
                    norm_p = os.path.normpath(p).lower()
                    if norm_p in purged_paths or not os.path.isfile(p):
                        ids_to_delete.append((r["spotify_id"],))
                    else:
                        valid, _ = is_valid_audio_file(p)
                        if not valid:
                            try:
                                os.remove(p)
                            except Exception:
                                pass
                            ids_to_delete.append((r["spotify_id"],))

                if ids_to_delete:
                    with conn:
                        conn.executemany("DELETE FROM downloaded_tracks WHERE spotify_id = ?", ids_to_delete)
                    stats["purged_db_records"] = len(ids_to_delete)
        except Exception as e:
            logger.error(f"Error cleaning database records: {e}")

        logger.info(f"Cleanup finished: {stats}")
        return stats

    def consolidate_and_organize_library(self, target_dir: str = "") -> Dict[str, Any]:
        """
        Consolidates all downloaded audio files into a single flat music folder (`target_dir`),
        removes empty stray source directories, purges missing/temp ghost DB rows,
        eliminates redundant duplicate rows (such as stale `local_*` or same-collection duplicates),
        enriches surviving rows with best available metadata, repairs/resets `saved_playlist_tracks`,
        regenerates portable `.m3u8` playlists, and compacts/vacuums the SQLite archive.
        """
        raw_target = (
            (target_dir or "").strip()
            or config.get("download.output_dir", "")
            or str(get_default_download_dir())
        )
        resolved_target = normalize_path(raw_target)
        os.makedirs(resolved_target, exist_ok=True)
        target_dir_key = os.path.normcase(os.path.normpath(resolved_target))

        stats: Dict[str, Any] = {
            "target_dir": resolved_target,
            "files_moved": 0,
            "duplicate_files_removed": 0,
            "duplicate_db_rows_removed": 0,
            "missing_db_rows_removed": 0,
            "paths_normalized": 0,
            "metadata_enriched": 0,
            "saved_tracks_repaired": 0,
            "saved_tracks_reset": 0,
            "empty_dirs_removed": 0,
            "errors": 0,
        }

        audio_exts = {".flac", ".mp3", ".opus", ".m4a", ".ogg", ".wav"}
        skip_subdir_names = {"playlists", "lyrics", "cache", "logs", "bin", "eq_preview", "spectrograms"}

        # 1. Gather all stray audio files from DB records (any dir != target_dir) and subdirs of target_dir
        candidate_files: List[str] = []
        try:
            with self.connection() as conn:
                for sql in (
                    "SELECT DISTINCT file_path FROM downloaded_tracks WHERE file_path IS NOT NULL AND file_path != ''",
                    "SELECT DISTINCT file_path FROM saved_playlist_tracks WHERE file_path IS NOT NULL AND file_path != ''",
                ):
                    for (raw_fp,) in conn.execute(sql).fetchall():
                        candidate_files.append(raw_fp)
        except Exception as exc:
            logger.warning(f"Could not query paths during organize scan: {exc}")

        for dirpath, dirs, filenames in os.walk(resolved_target):
            dirs[:] = [
                d for d in dirs
                if d.lower() not in skip_subdir_names and not d.startswith(".flacify-")
            ]
            if os.path.normcase(os.path.normpath(dirpath)) == target_dir_key:
                # Clean any stale .norm_tmp remnants sitting in root
                for fn in filenames:
                    if ".norm_tmp" in fn.lower():
                        try:
                            os.remove(os.path.join(dirpath, fn))
                        except OSError:
                            pass
                continue
            for fn in filenames:
                fp_sub = os.path.join(dirpath, fn)
                if ".norm_tmp" in fn.lower():
                    try:
                        os.remove(fp_sub)
                    except OSError:
                        pass
                    continue
                if os.path.splitext(fn)[1].lower() in audio_exts and not fn.lower().endswith(".part"):
                    candidate_files.append(fp_sub)

        seen_src_keys = set()
        stray_sources: List[str] = []
        for raw_fp in candidate_files:
            fp_norm = normalize_path(raw_fp)
            if not fp_norm or ".norm_tmp" in fp_norm.lower() or fp_norm.lower().endswith(".part"):
                continue
            if not os.path.isfile(fp_norm):
                continue
            parent_key = os.path.normcase(os.path.normpath(os.path.dirname(fp_norm)))
            if parent_key == target_dir_key:
                continue
            fp_key = os.path.normcase(fp_norm)
            if fp_key not in seen_src_keys:
                seen_src_keys.add(fp_key)
                stray_sources.append(fp_norm)

        path_remaps: Dict[str, str] = {}
        old_dirs = set()
        for src in stray_sources:
            old_dirs.add(os.path.dirname(src))
            bname = os.path.basename(src)
            stem, ext = os.path.splitext(bname)
            dest = normalize_path(os.path.join(resolved_target, bname))
            try:
                if os.path.isfile(dest):
                    src_st = os.stat(src)
                    dst_st = os.stat(dest)
                    same_inode = bool(
                        src_st.st_ino
                        and src_st.st_ino == dst_st.st_ino
                        and src_st.st_dev == dst_st.st_dev
                    )
                    if same_inode or src_st.st_size == dst_st.st_size:
                        if not same_inode:
                            os.remove(src)
                            stats["duplicate_files_removed"] += 1
                        path_remaps[os.path.normcase(src)] = dest
                        continue

                    idx = 2
                    while os.path.isfile(dest):
                        dest = normalize_path(os.path.join(resolved_target, f"{stem} ({idx}){ext}"))
                        idx += 1

                shutil.move(src, dest)
                src_lrc = os.path.splitext(src)[0] + ".lrc"
                if os.path.isfile(src_lrc):
                    dest_lrc = os.path.splitext(dest)[0] + ".lrc"
                    if not os.path.isfile(dest_lrc):
                        try:
                            shutil.move(src_lrc, dest_lrc)
                        except OSError:
                            pass
                path_remaps[os.path.normcase(src)] = dest
                stats["files_moved"] += 1
            except Exception as move_exc:
                logger.warning(f"Could not move stray audio file '{src}' -> '{dest}': {move_exc}")
                stats["errors"] += 1

        # Apply relocated file paths in SQLite before DB cleanup
        if path_remaps:
            try:
                with self.connection() as conn:
                    with conn:
                        for row in conn.execute("SELECT spotify_id, file_path FROM downloaded_tracks").fetchall():
                            raw_p = row["file_path"] or ""
                            if not raw_p:
                                continue
                            new_p = path_remaps.get(os.path.normcase(normalize_path(raw_p)))
                            if new_p and new_p != raw_p:
                                conn.execute(
                                    "UPDATE downloaded_tracks SET file_path = ? WHERE spotify_id = ?",
                                    (new_p, row["spotify_id"]),
                                )
                        for row in conn.execute(
                            "SELECT id, file_path FROM saved_playlist_tracks WHERE file_path IS NOT NULL AND file_path != ''"
                        ).fetchall():
                            raw_p = row["file_path"] or ""
                            new_p = path_remaps.get(os.path.normcase(normalize_path(raw_p)))
                            if new_p and new_p != raw_p:
                                conn.execute(
                                    "UPDATE saved_playlist_tracks SET file_path = ? WHERE id = ?",
                                    (new_p, row["id"]),
                                )
            except Exception as exc:
                logger.error(f"Failed updating relocated file paths in DB: {exc}")
                stats["errors"] += 1

        # Remove leftover empty source directories (never removing target_dir itself)
        for d in sorted(old_dirs, key=lambda p: len(p), reverse=True):
            d_norm = normalize_path(d)
            if not d_norm or os.path.normcase(d_norm) == target_dir_key or not os.path.isdir(d_norm):
                continue
            try:
                try:
                    in_target = os.path.commonpath([os.path.normcase(d_norm), target_dir_key]) == target_dir_key
                except ValueError:
                    in_target = False
                if not in_target:
                    for sub in os.listdir(d_norm):
                        sub_p = os.path.join(d_norm, sub)
                        if os.path.isdir(sub_p) and not os.listdir(sub_p):
                            try:
                                os.rmdir(sub_p)
                            except OSError:
                                pass
                if not os.listdir(d_norm):
                    os.rmdir(d_norm)
                    stats["empty_dirs_removed"] += 1
            except OSError:
                pass

        # 2. Deduplicate, normalize, purge ghosts, and enrich downloaded_tracks & saved_playlist_tracks
        try:
            import mutagen
        except ImportError:
            mutagen = None

        try:
            with self.connection() as conn:
                dt_rows = [dict(r) for r in conn.execute("SELECT * FROM downloaded_tracks").fetchall()]
                missing_ids: List[str] = []
                valid_by_fp: Dict[str, List[Dict[str, Any]]] = {}

                for r in dt_rows:
                    raw_fp = r.get("file_path") or ""
                    norm_fp = normalize_path(raw_fp)
                    if (
                        not norm_fp
                        or ".norm_tmp" in norm_fp.lower()
                        or norm_fp.lower().endswith(".part")
                        or not os.path.isfile(norm_fp)
                    ):
                        missing_ids.append(r["spotify_id"])
                        stats["missing_db_rows_removed"] += 1
                        continue
                    r["_norm_fp"] = norm_fp
                    valid_by_fp.setdefault(os.path.normcase(norm_fp), []).append(r)

                delete_ids: List[str] = list(missing_ids)
                updates_dt: List[Tuple[Any, ...]] = []
                surviving_rows: List[Dict[str, Any]] = []

                for _fp_key, grp in valid_by_fp.items():
                    canonical_fp = grp[0]["_norm_fp"]
                    try:
                        disk_size = os.path.getsize(canonical_fp)
                    except OSError:
                        disk_size = 0

                    ranked = sorted(grp, key=self._row_richness_key, reverse=True)
                    best_master = ranked[0]
                    best_dur = max((int(r.get("duration_ms") or 0) for r in grp), default=0)
                    if best_dur <= 0 and mutagen:
                        try:
                            aud = mutagen.File(canonical_fp)
                            if aud and getattr(aud, "info", None) and getattr(aud.info, "length", 0):
                                best_dur = int(float(aud.info.length) * 1000)
                        except Exception:
                            pass

                    best_genre = next((r["genre"].strip() for r in ranked if (r.get("genre") or "").strip()), "")
                    best_album = next((r["album"].strip() for r in ranked if not self._is_generic_album(r.get("album"))), "")
                    best_isrc = next((r["isrc"].strip() for r in ranked if (r.get("isrc") or "").strip()), "")
                    best_badge = best_master.get("quality_badge") or ""
                    best_source = best_master.get("source_type") or ""
                    if not best_badge or best_source in ("", "Local File", "Local Archive"):
                        qb_inf, st_inf = self.infer_badge_from_file(canonical_fp)
                        if not best_badge or best_badge in ("FLAC", "Audio"):
                            best_badge = qb_inf or best_badge
                        if best_source in ("", "Local File"):
                            best_source = st_inf or best_source

                    has_real = any(not str(r.get("spotify_id") or "").startswith("local_") for r in grp)
                    survivors_by_col: Dict[Tuple[str, str], Dict[str, Any]] = {}
                    for r in grp:
                        sid = str(r.get("spotify_id") or "")
                        if has_real and sid.startswith("local_"):
                            delete_ids.append(sid)
                            stats["duplicate_db_rows_removed"] += 1
                            continue
                        col_key = (
                            str(r.get("collection_type") or "").strip().lower(),
                            str(r.get("collection_name") or "").strip().lower(),
                        )
                        if col_key not in survivors_by_col:
                            survivors_by_col[col_key] = r
                        else:
                            existing = survivors_by_col[col_key]
                            if self._row_richness_key(r) > self._row_richness_key(existing):
                                delete_ids.append(existing["spotify_id"])
                                survivors_by_col[col_key] = r
                            else:
                                delete_ids.append(sid)
                            stats["duplicate_db_rows_removed"] += 1

                    for keeper in survivors_by_col.values():
                        new_fp = canonical_fp
                        new_dur = int(keeper.get("duration_ms") or 0) or best_dur
                        new_genre = (keeper.get("genre") or "").strip() or best_genre
                        new_album = keeper.get("album") or ""
                        if self._is_generic_album(new_album) and best_album:
                            new_album = best_album
                        new_isrc = (keeper.get("isrc") or "").strip() or best_isrc
                        new_size = disk_size if disk_size > 0 else int(keeper.get("file_size") or 0)
                        new_badge = keeper.get("quality_badge") or best_badge
                        new_source = keeper.get("source_type") or best_source
                        if new_source == "Local File" and best_source and best_source != "Local File":
                            new_source = best_source
                            new_badge = best_badge or new_badge

                        if new_fp != (keeper.get("file_path") or ""):
                            stats["paths_normalized"] += 1
                        if (
                            new_dur != (keeper.get("duration_ms") or 0)
                            or new_genre != (keeper.get("genre") or "")
                            or new_album != (keeper.get("album") or "")
                        ):
                            stats["metadata_enriched"] += 1

                        if (
                            new_fp != (keeper.get("file_path") or "")
                            or new_size != (keeper.get("file_size") or 0)
                            or new_dur != (keeper.get("duration_ms") or 0)
                            or new_genre != (keeper.get("genre") or "")
                            or new_album != (keeper.get("album") or "")
                            or new_isrc != (keeper.get("isrc") or "")
                            or new_badge != (keeper.get("quality_badge") or "")
                            or new_source != (keeper.get("source_type") or "")
                        ):
                            updates_dt.append((
                                new_fp,
                                new_size,
                                new_dur,
                                new_genre,
                                new_album,
                                new_isrc,
                                new_badge,
                                new_source,
                                keeper["spotify_id"],
                            ))

                        updated_copy = dict(keeper)
                        updated_copy.update({
                            "file_path": new_fp,
                            "file_size": new_size,
                            "duration_ms": new_dur,
                            "genre": new_genre,
                            "album": new_album,
                            "isrc": new_isrc,
                            "quality_badge": new_badge,
                            "source_type": new_source,
                        })
                        surviving_rows.append(updated_copy)

                with conn:
                    for i in range(0, len(delete_ids), 500):
                        chunk = delete_ids[i : i + 500]
                        ph = ",".join("?" for _ in chunk)
                        conn.execute(f"DELETE FROM downloaded_tracks WHERE spotify_id IN ({ph})", chunk)

                    if updates_dt:
                        conn.executemany(
                            """
                            UPDATE downloaded_tracks
                            SET file_path = ?, file_size = ?, duration_ms = ?, genre = ?,
                                album = ?, isrc = ?, quality_badge = ?, source_type = ?
                            WHERE spotify_id = ?
                            """,
                            updates_dt,
                        )

                    # Reconcile saved_playlist_tracks paths & badges against surviving library files
                    by_sid: Dict[str, Dict[str, Any]] = {}
                    by_isrc: Dict[str, Dict[str, Any]] = {}
                    by_ta: Dict[Tuple[str, str], Dict[str, Any]] = {}
                    by_fp: Dict[str, Dict[str, Any]] = {}
                    for sr in surviving_rows:
                        by_sid[sr["spotify_id"]] = sr
                        by_fp.setdefault(os.path.normcase(sr["file_path"]), sr)
                        if (sr.get("isrc") or "").strip():
                            by_isrc.setdefault(sr["isrc"].strip().lower(), sr)
                        ta_k = (
                            (sr.get("artist") or "").strip().lower(),
                            (sr.get("title") or "").strip().lower(),
                        )
                        if ta_k[0] and ta_k[1]:
                            by_ta.setdefault(ta_k, sr)

                    sp_rows = [dict(r) for r in conn.execute("SELECT * FROM saved_playlist_tracks").fetchall()]
                    sp_updates: List[Tuple[Any, ...]] = []
                    for sp in sp_rows:
                        cur_status = sp.get("status") or "pending"
                        raw_sp_fp = sp.get("file_path") or ""
                        norm_sp_fp = normalize_path(raw_sp_fp) if raw_sp_fp else ""
                        valid_fp = (
                            bool(norm_sp_fp)
                            and ".norm_tmp" not in norm_sp_fp.lower()
                            and not norm_sp_fp.lower().endswith(".part")
                            and os.path.isfile(norm_sp_fp)
                        )
                        if valid_fp:
                            canon = by_fp.get(os.path.normcase(norm_sp_fp))
                            new_qb = sp.get("quality_badge") or (canon.get("quality_badge") if canon else "") or ""
                            new_st = sp.get("source_type") or (canon.get("source_type") if canon else "") or ""
                            new_gn = sp.get("genre") or (canon.get("genre") if canon else "") or ""
                            if (
                                norm_sp_fp != raw_sp_fp
                                or cur_status != "downloaded"
                                or new_qb != (sp.get("quality_badge") or "")
                                or new_st != (sp.get("source_type") or "")
                                or new_gn != (sp.get("genre") or "")
                            ):
                                sp_updates.append(("downloaded", norm_sp_fp, new_qb, new_st, new_gn, sp["id"]))
                        elif cur_status == "downloaded" or raw_sp_fp:
                            match = (
                                by_sid.get(sp.get("spotify_id") or "")
                                or by_isrc.get((sp.get("isrc") or "").strip().lower())
                                or by_ta.get((
                                    (sp.get("artist") or "").strip().lower(),
                                    (sp.get("title") or "").strip().lower(),
                                ))
                            )
                            if match and os.path.isfile(match["file_path"]):
                                sp_updates.append((
                                    "downloaded",
                                    match["file_path"],
                                    sp.get("quality_badge") or match.get("quality_badge") or "",
                                    sp.get("source_type") or match.get("source_type") or "",
                                    sp.get("genre") or match.get("genre") or "",
                                    sp["id"],
                                ))
                                stats["saved_tracks_repaired"] += 1
                            else:
                                sp_updates.append(("pending", "", "", "", sp.get("genre") or "", sp["id"]))
                                stats["saved_tracks_reset"] += 1

                    if sp_updates:
                        conn.executemany(
                            """
                            UPDATE saved_playlist_tracks
                            SET status = ?, file_path = ?, quality_badge = ?, source_type = ?, genre = ?
                            WHERE id = ?
                            """,
                            sp_updates,
                        )

                    conn.execute("""
                        UPDATE saved_playlists
                        SET total_tracks = (
                            SELECT COUNT(*) FROM saved_playlist_tracks WHERE playlist_id = saved_playlists.id
                        )
                    """)
        except Exception as db_exc:
            logger.error(f"Database organization error: {db_exc}")
            stats["errors"] += 1

        # 3. Regenerate .m3u8 playlists pointing at consolidated folder & compact SQLite
        try:
            self.sync_all_playlist_m3u8_files()
        except Exception as m3u_exc:
            logger.debug(f"M3U8 refresh notice during organize: {m3u_exc}")

        try:
            with self._db_lock:
                vconn = self._get_connection()
                try:
                    vconn.isolation_level = None
                    vconn.execute("PRAGMA optimize;")
                    vconn.execute("VACUUM;")
                    vconn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
                finally:
                    vconn.close()
        except Exception as vac_exc:
            logger.debug(f"SQLite vacuum notice: {vac_exc}")

        logger.info(f"Library consolidation & DB organization finished: {stats}")
        return stats

    def repair_library(
        self,
        root_dir: str = "",
        progress_callback: Optional[Callable[[int, int, str], None]] = None
    ) -> Dict[str, int]:
        """
        Deep scan and auto-repair across user music folders.
        Detects any tracks missing embedded album artwork or lyrics,
        resolves them via multi-tier fallback (including Spotify oEmbed and LRCLIB),
        and safely embeds them into the audio containers without loss.
        """
        from core.tagger import AudioTagger
        from core.lyrics import LyricsEngine
        from core.spotify_client import TrackMetadata

        if not root_dir:
            root_dir = config.get("download.output_dir", "") or str(get_default_download_dir())
            if not os.path.isabs(root_dir):
                root_dir = os.path.normpath(os.path.join(str(get_default_download_dir()), root_dir))

        stats = {
            "scanned": 0,
            "missing_covers_found": 0,
            "missing_lyrics_found": 0,
            "healed_covers": 0,
            "healed_lyrics": 0,
            "errors": 0
        }

        if not os.path.isdir(root_dir):
            return stats

        tagger = AudioTagger()
        lyrics_engine = LyricsEngine()

        audio_files = []
        for root, dirs, files in os.walk(root_dir):
            if os.path.basename(root).lower() in ("lyrics", "cache", "logs", "bin"):
                continue
            for fname in files:
                ext = os.path.splitext(fname)[1].lower()
                if ext in (".flac", ".opus", ".mp3", ".m4a", ".ogg"):
                    audio_files.append(os.path.join(root, fname))

        total_files = len(audio_files)
        logger.info(f"Starting Library Repair across {total_files} audio files in: {root_dir}")

        for idx, fpath in enumerate(audio_files, 1):
            stats["scanned"] += 1
            bname = os.path.basename(fpath)
            if progress_callback:
                progress_callback(idx, total_files, f"Checking {bname}")

            # Check cover
            cov = extract_embedded_cover(fpath)
            has_cover = bool(cov and len(cov) > 500)

            # Check lyrics
            ext = os.path.splitext(fpath)[1].lower()
            has_lyrics = False
            has_synced_lyrics = False
            has_crlf = False
            existing_lyr_text = ""
            try:
                if ext == ".flac":
                    from mutagen.flac import FLAC
                    aud = FLAC(fpath)
                    for k in ["LYRICS", "lyrics", "SYNCEDLYRICS", "UNSYNCEDLYRICS"]:
                        if k in aud and aud[k][0].strip():
                            existing_lyr_text = aud[k][0]
                            has_lyrics = True
                            has_synced_lyrics = "[" in existing_lyr_text and "]" in existing_lyr_text
                            has_crlf = "\r\n" in existing_lyr_text
                            break
                elif ext in (".opus", ".ogg"):
                    try:
                        from mutagen.oggopus import OggOpus
                        aud = OggOpus(fpath)
                    except Exception:
                        from mutagen.oggvorbis import OggVorbis
                        aud = OggVorbis(fpath)
                    for k in ["LYRICS", "lyrics", "SYNCEDLYRICS", "UNSYNCEDLYRICS"]:
                        if k in aud and aud[k][0].strip():
                            existing_lyr_text = aud[k][0]
                            has_lyrics = True
                            has_synced_lyrics = "[" in existing_lyr_text and "]" in existing_lyr_text
                            has_crlf = "\r\n" in existing_lyr_text
                            break
                elif ext == ".mp3":
                    from mutagen.mp3 import MP3
                    aud = MP3(fpath)
                    for k in aud.keys():
                        if k.startswith("USLT") or k.startswith("SYLT"):
                            existing_lyr_text = str(aud[k])
                            has_lyrics = True
                            has_synced_lyrics = "[" in existing_lyr_text and "]" in existing_lyr_text
                            has_crlf = "\r\n" in existing_lyr_text
                            break
                elif ext == ".m4a":
                    from mutagen.mp4 import MP4
                    aud = MP4(fpath)
                    lyr = aud.get("\xa9lyr", [""])[0] if aud.get("\xa9lyr") else ""
                    if lyr and lyr.strip():
                        existing_lyr_text = lyr
                        has_lyrics = True
                        has_synced_lyrics = "[" in existing_lyr_text and "]" in existing_lyr_text
                        has_crlf = "\r\n" in existing_lyr_text
            except Exception:
                pass

            has_genre = False
            try:
                if ext in (".flac", ".opus", ".ogg"):
                    g = aud.get("GENRE") or aud.get("genre")
                    if g and any(x.strip() for x in g):
                        has_genre = True
                elif ext == ".mp3":
                    for k in aud.keys():
                        if k.startswith("TCON"):
                            t = aud[k]
                            if t and any(str(x).strip() for x in getattr(t, "text", [])):
                                has_genre = True
                                break
                elif ext == ".m4a":
                    g = aud.get("\xa9gen")
                    if g and any(str(x).strip() for x in g):
                        has_genre = True
            except Exception:
                pass

            needs_lyric_healing = (not has_lyrics) or (not has_synced_lyrics) or (not has_crlf)
            needs_genre_healing = not has_genre

            if has_cover and not needs_lyric_healing and not needs_genre_healing:
                continue

            if not has_cover:
                stats["missing_covers_found"] += 1
            if needs_lyric_healing:
                stats["missing_lyrics_found"] += 1

            # Resolve track metadata from archive.db or file tags
            meta = self.get_track_by_path(fpath)
            track_meta = None
            if meta:
                track_meta = TrackMetadata(
                    id=meta.get("spotify_id", ""),
                    title=meta.get("title", ""),
                    artists=[meta.get("artist", "")],
                    album=meta.get("album", ""),
                    release_date="",
                    duration_ms=meta.get("duration_ms", 0),
                    track_number=meta.get("track_number", 1),
                    disc_number=meta.get("disc_number", 1),
                    isrc=meta.get("isrc", ""),
                    collection_name=meta.get("collection_name", "")
                )
            else:
                raw_name = os.path.splitext(bname)[0]
                import re
                extracted_track = 1
                m_num = re.match(r"^(\d{1,3})[\s.\-_]+(.*)$", raw_name)
                if m_num:
                    try:
                        extracted_track = int(m_num.group(1))
                        raw_name = m_num.group(2).strip()
                    except Exception:
                        pass
                art = ""
                tit = raw_name
                if " - " in raw_name:
                    art, tit = raw_name.split(" - ", 1)
                track_meta = TrackMetadata(
                    id="",
                    title=tit.strip(),
                    artists=[art.strip()] if art else ["Unknown Artist"],
                    album=os.path.basename(os.path.dirname(fpath)),
                    release_date="",
                    duration_ms=0,
                    track_number=extracted_track
                )

            # Fetch lyrics if needed
            lyr_data = None
            if needs_lyric_healing:
                # If track does not have synced lyrics, query LRCLIB for synchronized timestamps
                if not has_synced_lyrics:
                    try:
                        if progress_callback:
                            progress_callback(idx, total_files, f"Fetching synced lyrics for {bname}")
                        lyr_data = lyrics_engine.fetch_lyrics(track_meta)
                    except Exception as e_lyr:
                        logger.debug(f"Lyrics lookup error during repair for {bname}: {e_lyr}")

                # If we have existing lyrics (already synced or LRCLIB had none), preserve and normalize
                if not lyr_data and existing_lyr_text:
                    from core.lyrics import LyricsData
                    if "[" in existing_lyr_text and "]" in existing_lyr_text:
                        lyr_data = LyricsData(synced_lyrics=existing_lyr_text)
                    else:
                        lyr_data = LyricsData(plain_lyrics=existing_lyr_text)

            try:
                if progress_callback:
                    progress_callback(idx, total_files, f"Healing metadata for {bname}")
                success = tagger.tag_file(
                    file_path=fpath,
                    track=track_meta,
                    lyrics_data=lyr_data,
                    embed_art=not has_cover,
                    embed_lyrics=needs_lyric_healing
                )
                if success:
                    if not has_cover:
                        stats["healed_covers"] += 1
                    if needs_lyric_healing and lyr_data:
                        stats["healed_lyrics"] += 1
                else:
                    stats["errors"] += 1
            except Exception as e_tag:
                logger.error(f"Error healing file {fpath}: {e_tag}")
                stats["errors"] += 1

        logger.info(f"Library repair completed: {stats}")
        return stats

    def retag_all_library_replaygain(
        self,
        root_dir: str = "",
        progress_callback: Optional[Callable[[int, int, str], None]] = None
    ) -> Dict[str, int]:
        """
        Deep scans downloaded audio files, computes EBU R128 integrated loudness & true peak
        using ffmpeg ebur128 filter, and writes non-destructive ReplayGain 2.0 tags.
        """
        from core.utils import calculate_replaygain
        from core.tagger import AudioTagger

        if not root_dir:
            root_dir = config.get("download.output_dir", "") or str(get_default_download_dir())
            if not os.path.isabs(root_dir):
                root_dir = os.path.normpath(os.path.join(str(get_default_download_dir()), root_dir))

        stats = {
            "scanned": 0,
            "calculated": 0,
            "errors": 0
        }

        if not os.path.isdir(root_dir):
            return stats

        tagger = AudioTagger()
        audio_files = []
        for root, dirs, files in os.walk(root_dir):
            if os.path.basename(root).lower() in ("lyrics", "cache", "logs", "bin"):
                continue
            for fname in files:
                ext = os.path.splitext(fname)[1].lower()
                if ext in (".flac", ".opus", ".mp3", ".m4a", ".ogg"):
                    audio_files.append(os.path.join(root, fname))

        total_files = len(audio_files)
        logger.info(f"Starting ReplayGain batch analysis across {total_files} audio files in: {root_dir}")

        for idx, fpath in enumerate(audio_files, 1):
            stats["scanned"] += 1
            bname = os.path.basename(fpath)
            if progress_callback:
                progress_callback(idx, total_files, f"Analyzing {bname}")

            try:
                rg = calculate_replaygain(fpath)
                if rg:
                    gain_str, peak_str = rg
                    ok = tagger.tag_replaygain(fpath, gain_str, peak_str)
                    if ok:
                        stats["calculated"] += 1
                    else:
                        stats["errors"] += 1
                else:
                    stats["errors"] += 1
            except Exception as e:
                logger.error(f"Error calculating ReplayGain for {fpath}: {e}")
                stats["errors"] += 1

        logger.info(f"ReplayGain batch tagging completed: {stats}")
        return stats

    def export_saved_playlist_m3u8(
        self,
        playlist_id: str,
        dest_path: Optional[str] = None,
        path_mode: str = "relative",
        android_prefix: str = "/storage/emulated/0/Music"
    ) -> Optional[str]:
        """
        Exports a saved playlist to a portable standard UTF-8 .m3u8 file.
        Supports:
        - 'filename': Portable filename only (universal for Android players: Poweramp, Musicolet, VLC Android).
        - 'absolute': Full local file paths (for VLC, PotPlayer, KMPlayer on PC).
        - 'relative': Relative paths from playlist file to audio files.
        - 'android_prefix': Path prefixed with Android directory (e.g. /storage/emulated/0/Music/).
        """
        pl = self.get_saved_playlist(playlist_id)
        if not pl:
            return None

        tracks = self.get_saved_playlist_tracks(playlist_id)
        valid_tracks = [t for t in tracks if t.get("file_path") and os.path.isfile(t["file_path"])]
        if not valid_tracks:
            return None

        name = pl.get("name", "Playlist")
        safe_name = sanitize_filename(name, max_length=50)

        if not dest_path:
            output_dir = config.get("download.output_dir", "") or str(get_default_download_dir())
            save_in_subfolders = config.get("download.save_in_subfolders", False)
            if save_in_subfolders:
                pl_folder = os.path.join(output_dir, safe_name)
                dest_path = os.path.join(pl_folder, f"{safe_name}.m3u8")
            else:
                playlists_folder = os.path.join(output_dir, "playlists")
                dest_path = os.path.join(playlists_folder, f"{safe_name}.m3u8")

        return self.export_tracks_to_m3u8(
            playlist_name=name,
            tracks=valid_tracks,
            dest_path=dest_path,
            path_mode=path_mode,
            android_prefix=android_prefix
        )

    def export_tracks_to_m3u8(
        self,
        playlist_name: str,
        tracks: List[Any],
        dest_path: str,
        path_mode: str = "filename",
        android_prefix: str = "/storage/emulated/0/Music"
    ) -> Optional[str]:
        """
        Exports any arbitrary list of tracks (dicts or QueueItems) to a standard .m3u8 file
        preserving exact given track order and metadata.
        """
        if not tracks or not dest_path:
            return None

        valid_tracks = []
        for t in tracks:
            fp = t.get("file_path") if isinstance(t, dict) else getattr(t, "output_path", "")
            if fp and os.path.isfile(fp):
                valid_tracks.append(t)

        if not valid_tracks:
            return None

        try:
            os.makedirs(os.path.dirname(os.path.abspath(dest_path)), exist_ok=True)
            dest_dir = os.path.dirname(os.path.abspath(dest_path))
            with open(dest_path, "w", encoding="utf-8", newline="\n") as f:
                f.write("#EXTM3U\n")
                f.write(f"#PLAYLIST:{playlist_name}\n")
                for t in valid_tracks:
                    if isinstance(t, dict):
                        fp = os.path.abspath(t["file_path"])
                        title = t.get("title", "Unknown")
                        artist = t.get("artist", "Unknown")
                        dur_sec = int(t.get("duration_ms", 0) / 1000) if t.get("duration_ms") else -1
                    elif hasattr(t, "track") and t.track:
                        fp = os.path.abspath(t.output_path)
                        title = t.track.title or "Unknown"
                        artist = getattr(t.track, "artist_str", "") or (", ".join(t.track.artists) if hasattr(t.track, "artists") else "Unknown")
                        dur_ms = getattr(t.track, "duration_ms", 0) or 0
                        dur_sec = int(dur_ms / 1000) if dur_ms else -1
                    else:
                        fp = os.path.abspath(getattr(t, "output_path", "") or getattr(t, "file_path", ""))
                        title = getattr(t, "title", "Unknown")
                        artist = getattr(t, "artist", "Unknown")
                        dur_ms = getattr(t, "duration_ms", 0) or 0
                        dur_sec = int(dur_ms / 1000) if dur_ms else -1

                    f.write(f"#EXTINF:{dur_sec},{artist} - {title}\n")
                    if path_mode == "filename":
                        f.write(f"{os.path.basename(fp)}\n")
                    elif path_mode == "absolute":
                        f.write(f"{fp.replace(os.sep, '/')}\n")
                    elif path_mode == "android_prefix":
                        pfx = (android_prefix or "/storage/emulated/0/Music").rstrip("/\\")
                        f.write(f"{pfx}/{os.path.basename(fp)}\n")
                    else:
                        try:
                            rel_p = os.path.relpath(fp, dest_dir)
                            f.write(f"{rel_p.replace(os.sep, '/')}\n")
                        except Exception:
                            f.write(f"{os.path.basename(fp)}\n")

            logger.info(f"Exported {len(valid_tracks)} tracks to M3U8 '{dest_path}' (mode={path_mode})")
            return dest_path
        except Exception as e:
            logger.error(f"Failed to export tracks to M3U8 '{dest_path}': {e}")
            return None

    def export_collection_m3u8(self, collection_name: str, dest_path: Optional[str] = None) -> Optional[str]:
        """
        Finds a saved playlist matching collection_name and exports/updates its portable .m3u8 file.
        """
        if not collection_name:
            return None
        try:
            with self.connection() as conn:
                row = conn.execute("SELECT id FROM saved_playlists WHERE name = ? COLLATE NOCASE", (collection_name,)).fetchone()
                if row:
                    return self.export_saved_playlist_m3u8(row["id"], dest_path=dest_path)
        except Exception as e:
            logger.debug(f"Could not export collection M3U8 for '{collection_name}': {e}")
        return None

    def sync_all_playlist_m3u8_files(self) -> List[str]:
        """
        Refreshes and regenerates .m3u8 playlist files for all saved playlists in the library.
        Returns a list of exported file paths.
        """
        exported = []
        try:
            playlists = self.get_saved_playlists()
            for pl in playlists:
                p = self.export_saved_playlist_m3u8(pl["id"])
                if p:
                    exported.append(p)
        except Exception as e:
            logger.warning(f"Error syncing playlist M3U8 files: {e}")
        return exported


    # -------------------------------------------------------------------------
    # Saved Playlists & Tracks Management (Decoupled Metadata Storing & On-Demand Batching)
    # -------------------------------------------------------------------------
    def save_playlist(
        self,
        name: str,
        spotify_url: str,
        cover_url: str,
        tracks: List[TrackMetadata],
        playlist_id: str = ""
    ) -> Dict[str, Any]:
        """
        Saves a playlist and all its track metadata into SQLite without starting audio downloads.
        Automatically checks downloaded_tracks to tag tracks that are already downloaded locally.
        """
        if not playlist_id:
            from core.spotify_client import SpotifyClient
            parsed = SpotifyClient.parse_url(spotify_url)
            playlist_id = parsed[1] if parsed else sanitize_filename(name, max_length=40)

        # Cache cover if remote URL exists
        safe_name = sanitize_filename(name, max_length=50)
        covers_dir = str(get_covers_dir())
        local_cover = os.path.join(covers_dir, f"playlist_{safe_name}.jpg")
        if cover_url and not os.path.isfile(local_cover):
            def _fetch_cover():
                try:
                    import requests
                    r = requests.get(cover_url, timeout=5)
                    if r.status_code == 200 and len(r.content) > 500:
                        with open(local_cover, "wb") as f:
                            f.write(r.content)
                except Exception as e:
                    logger.debug(f"Could not cache playlist cover: {e}")
            threading.Thread(target=_fetch_cover, daemon=True, name="CoverFetcher").start()

        try:
            with self.connection() as conn:
                with conn:
                    # 1. Upsert playlist record
                    conn.execute("""
                        INSERT INTO saved_playlists (id, name, spotify_url, cover_url, total_tracks, updated_at)
                        VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                        ON CONFLICT(id) DO UPDATE SET
                            name = excluded.name,
                            spotify_url = excluded.spotify_url,
                            cover_url = excluded.cover_url,
                            total_tracks = excluded.total_tracks,
                            updated_at = CURRENT_TIMESTAMP
                    """, (playlist_id, name, spotify_url, cover_url, len(tracks)))

                    # 2. Query already downloaded tracks map: spotify_id -> info
                    downloaded_map: Dict[str, Dict[str, str]] = {}
                    track_ids = [t.id for t in tracks if t.id]
                    if track_ids:
                        chunk_size = 500
                        for i in range(0, len(track_ids), chunk_size):
                            chunk = track_ids[i:i + chunk_size]
                            placeholders = ",".join("?" for _ in chunk)
                            query = f"SELECT spotify_id, file_path, quality_badge, source_type, genre FROM downloaded_tracks WHERE spotify_id IN ({placeholders})"
                            rows = conn.execute(query, chunk).fetchall()
                            for r in rows:
                                fpath = r["file_path"]
                                if fpath and os.path.isfile(fpath):
                                    downloaded_map[r["spotify_id"]] = {
                                        "file_path": fpath,
                                        "quality_badge": r["quality_badge"] or "",
                                        "source_type": r["source_type"] or "",
                                        "genre": r["genre"] or ""
                                    }

                    # 3. Batch insert/update tracks
                    track_rows = []
                    for idx_t, t in enumerate(tracks, start=1):
                        dl_info = downloaded_map.get(t.id)
                        existing_fp = dl_info["file_path"] if dl_info else ""
                        q_badge = dl_info["quality_badge"] if dl_info else ""
                        s_type = dl_info["source_type"] if dl_info else ""
                        genre_val = (dl_info["genre"] if dl_info else "") or getattr(t, "genre_str", "") or getattr(t, "genre", "") or ""
                        if existing_fp and not q_badge:
                            qb_inf, st_inf = self.infer_badge_from_file(existing_fp)
                            q_badge = qb_inf
                            s_type = s_type or st_inf
                        status = "downloaded" if existing_fp else "pending"
                        trk_num = idx_t if (getattr(t, "collection_type", "") == "playlist" or not getattr(t, "track_number", 0)) else t.track_number
                        track_rows.append((
                            playlist_id,
                            t.id,
                            t.title,
                            t.artist_str,
                            t.album or "",
                            t.duration_ms,
                            trk_num,
                            getattr(t, "disc_number", 1) or 1,
                            t.isrc or "",
                            t.cover_url or "",
                            status,
                            existing_fp,
                            q_badge,
                            s_type,
                            genre_val
                        ))

                    conn.executemany("""
                        INSERT INTO saved_playlist_tracks (
                            playlist_id, spotify_id, title, artist, album,
                            duration_ms, track_number, disc_number, isrc,
                            cover_url, status, file_path, quality_badge, source_type,
                            genre
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(playlist_id, spotify_id) DO UPDATE SET
                            title = excluded.title,
                            artist = excluded.artist,
                            album = excluded.album,
                            duration_ms = excluded.duration_ms,
                            track_number = excluded.track_number,
                            disc_number = excluded.disc_number,
                            isrc = excluded.isrc,
                            cover_url = excluded.cover_url,
                            status = CASE 
                                WHEN excluded.status = 'downloaded' THEN 'downloaded'
                                WHEN saved_playlist_tracks.status = 'downloaded' THEN 'downloaded'
                                ELSE excluded.status 
                            END,
                            file_path = CASE 
                                WHEN excluded.file_path != '' THEN excluded.file_path 
                                WHEN saved_playlist_tracks.file_path != '' THEN saved_playlist_tracks.file_path
                                ELSE '' 
                            END,
                            quality_badge = CASE 
                                WHEN excluded.quality_badge != '' THEN excluded.quality_badge 
                                WHEN saved_playlist_tracks.quality_badge != '' THEN saved_playlist_tracks.quality_badge
                                ELSE '' 
                            END,
                            source_type = CASE 
                                WHEN excluded.source_type != '' THEN excluded.source_type 
                                WHEN saved_playlist_tracks.source_type != '' THEN saved_playlist_tracks.source_type
                                ELSE '' 
                            END,
                            genre = CASE WHEN excluded.genre != '' THEN excluded.genre ELSE saved_playlist_tracks.genre END
                    """, track_rows)

                    # 4. Synchronize total_tracks with actual deduplicated count in saved_playlist_tracks
                    conn.execute("""
                        UPDATE saved_playlists 
                        SET total_tracks = (SELECT COUNT(*) FROM saved_playlist_tracks WHERE playlist_id = ?) 
                        WHERE id = ?
                    """, (playlist_id, playlist_id))

                logger.info(f"Saved playlist '{name}' ({len(tracks)} tracks) into database.")
                return self.get_saved_playlist(playlist_id) or {}
        except Exception as e:
            logger.error(f"Failed to save playlist '{name}': {e}")
            return {}


    def sync_saved_playlist(self, playlist_id: str, new_tracks: List[TrackMetadata]) -> Dict[str, Any]:
        """
        Synchronizes an existing saved playlist with fresh tracks from Spotify/online source.
        Inserts newly added tracks with pending status, keeps downloaded tracks intact,
        removes tracks deleted from playlist, and returns dict: {"added": int, "removed": int, "total": int}.
        """
        if not playlist_id or not new_tracks:
            return {"added": 0, "removed": 0, "total": 0}

        with self._db_lock:
            existing_tracks = self.get_saved_playlist_tracks(playlist_id)
            existing_ids = {t["spotify_id"] for t in existing_tracks}
            new_ids = {t.id for t in new_tracks if t.id}

            added_count = len(new_ids - existing_ids)
            removed_ids = existing_ids - new_ids
            removed_count = len(removed_ids)

            # Safety guard: prevent accidental wiping of library on truncated/partial API responses
            if len(new_tracks) < len(existing_tracks) * 0.5 and len(existing_tracks) > 50:
                logger.warning(
                    f"Sync received only {len(new_tracks)} tracks, but existing playlist has {len(existing_tracks)}. "
                    f"Skipping track deletions to protect library from truncated API response."
                )
                removed_ids = set()
                removed_count = 0

            if removed_ids:
                try:
                    with self.connection() as conn:
                        with conn:
                            placeholders = ",".join("?" for _ in removed_ids)
                            conn.execute(
                                f"DELETE FROM saved_playlist_tracks WHERE playlist_id = ? AND spotify_id IN ({placeholders})",
                                [playlist_id] + list(removed_ids)
                            )
                except Exception as e:
                    logger.debug(f"Failed to delete removed tracks during sync: {e}")

            pl = self.get_saved_playlist(playlist_id)
            name = pl.get("name", "Synced Playlist") if pl else "Synced Playlist"
            spotify_url = pl.get("spotify_url", "") if pl else ""
            cover_url = pl.get("cover_url", "") if pl else (new_tracks[0].cover_url if new_tracks else "")

            self.save_playlist(
                name=name,
                spotify_url=spotify_url,
                cover_url=cover_url,
                tracks=new_tracks,
                playlist_id=playlist_id
            )

            updated_tracks = self.get_saved_playlist_tracks(playlist_id)
            after_count = len(updated_tracks)
            delta_tracks = [t for t in new_tracks if t.id not in existing_ids]
            try:
                with self.connection() as conn:
                    with conn:
                        conn.execute(
                            "UPDATE saved_playlists SET last_synced_at = CURRENT_TIMESTAMP WHERE id = ?",
                            (playlist_id,)
                        )
            except Exception:
                pass
            logger.info(f"Synced playlist '{name}': {added_count} new track(s) added, {removed_count} removed, total {after_count}.")
            return {
                "added": added_count,
                "removed": removed_count,
                "total": after_count,
                "delta_tracks": delta_tracks
            }

    def set_playlist_auto_sync(self, playlist_id: str, enabled: bool) -> bool:
        """Pins or unpins a saved playlist for scheduled background Auto-Sync ('Watch Playlist')."""
        if not playlist_id:
            return False
        try:
            with self.connection() as conn:
                with conn:
                    conn.execute(
                        "UPDATE saved_playlists SET auto_sync = ? WHERE id = ?",
                        (1 if enabled else 0, playlist_id)
                    )
            return True
        except Exception as e:
            logger.error(f"Failed to set auto_sync on playlist {playlist_id}: {e}")
            return False

    def get_watched_playlists(self) -> List[Dict[str, Any]]:
        """Returns all saved playlists that have Auto-Sync ('Watch Playlist') enabled."""
        return [p for p in self.get_saved_playlists() if p.get("auto_sync") and p.get("spotify_url")]

    def get_saved_playlists(self) -> List[Dict[str, Any]]:
        """Returns all saved playlists with aggregate statistics."""
        try:
            with self.connection() as conn:
                query = """
                    SELECT 
                        p.id, p.name, p.spotify_url, p.cover_url, p.total_tracks, p.created_at, p.updated_at,
                        COALESCE(p.auto_sync, 0) as auto_sync, p.last_synced_at,
                        COUNT(t.id) as track_count,
                        SUM(CASE WHEN t.status = 'downloaded' THEN 1 ELSE 0 END) as downloaded_count,
                        SUM(CASE WHEN t.status != 'downloaded' THEN 1 ELSE 0 END) as pending_count
                    FROM saved_playlists p
                    LEFT JOIN saved_playlist_tracks t ON p.id = t.playlist_id
                    GROUP BY p.id
                    ORDER BY COALESCE(p.auto_sync, 0) DESC, p.updated_at DESC
                """
                rows = conn.execute(query).fetchall()
                results = []
                for r in rows:
                    tot = r["track_count"] if (r["track_count"] and r["track_count"] > 0) else (r["total_tracks"] or 0)
                    down = r["downloaded_count"] or 0
                    pend = r["pending_count"] if (tot == 0 or tot == down) else max(0, tot - down)
                    pct = round((down / tot * 100.0), 1) if tot > 0 else 0.0

                    local_cover = resolve_collection_cover(r["name"])
                    
                    results.append({
                        "id": r["id"],
                        "name": r["name"],
                        "spotify_url": r["spotify_url"],
                        "cover_url": r["cover_url"],
                        "local_cover": local_cover,
                        "total_tracks": tot,
                        "downloaded_count": down,
                        "pending_count": pend,
                        "progress_percent": pct,
                        "auto_sync": bool(r["auto_sync"]),
                        "last_synced_at": r["last_synced_at"] or "",
                        "created_at": r["created_at"],
                        "updated_at": r["updated_at"]
                    })
                return results
        except Exception as e:
            logger.error(f"Failed to fetch saved playlists: {e}")
            return []

    def get_saved_playlist(self, playlist_id: str) -> Optional[Dict[str, Any]]:
        """Returns metadata and statistics for a specific playlist."""
        try:
            with self.connection() as conn:
                query = """
                    SELECT 
                        p.id, p.name, p.spotify_url, p.cover_url, p.total_tracks, p.created_at, p.updated_at,
                        COALESCE(p.auto_sync, 0) as auto_sync, p.last_synced_at,
                        COUNT(t.id) as track_count,
                        SUM(CASE WHEN t.status = 'downloaded' THEN 1 ELSE 0 END) as downloaded_count,
                        SUM(CASE WHEN t.status != 'downloaded' THEN 1 ELSE 0 END) as pending_count
                    FROM saved_playlists p
                    LEFT JOIN saved_playlist_tracks t ON p.id = t.playlist_id
                    WHERE p.id = ?
                    GROUP BY p.id
                """
                r = conn.execute(query, (playlist_id,)).fetchone()
                if not r:
                    return None
                tot = r["track_count"] if (r["track_count"] and r["track_count"] > 0) else (r["total_tracks"] or 0)
                down = r["downloaded_count"] or 0
                pend = r["pending_count"] if (tot == 0 or tot == down) else max(0, tot - down)
                pct = round((down / tot * 100.0), 1) if tot > 0 else 0.0

                local_cover = resolve_collection_cover(r["name"])

                return {
                    "id": r["id"],
                    "name": r["name"],
                    "spotify_url": r["spotify_url"],
                    "cover_url": r["cover_url"],
                    "local_cover": local_cover,
                    "total_tracks": tot,
                    "downloaded_count": down,
                    "pending_count": pend,
                    "progress_percent": pct,
                    "auto_sync": bool(r["auto_sync"]),
                    "last_synced_at": r["last_synced_at"] or "",
                    "created_at": r["created_at"],
                    "updated_at": r["updated_at"]
                }
        except Exception as e:
            logger.error(f"Failed to fetch saved playlist {playlist_id}: {e}")
            return None

    def get_saved_playlist_tracks(
        self,
        playlist_id: str,
        status: Optional[str] = None,
        search_query: str = "",
        limit: Optional[int] = None,
        genre_filter: str = ""
    ) -> List[Dict[str, Any]]:
        """Returns all tracks for a saved playlist, optionally filtered by status, search, genre, and limit."""
        try:
            with self.connection() as conn:
                base_sql = """
                    SELECT 
                        s.id, s.playlist_id, s.spotify_id, s.title, s.artist, s.album,
                        s.duration_ms, s.track_number, s.disc_number, s.isrc, s.cover_url,
                        s.status,
                        COALESCE(NULLIF(s.genre, ''), d.genre, '') AS genre,
                        COALESCE(NULLIF(s.file_path, ''), d.file_path, '') AS file_path,
                        s.file_path AS s_file_path,
                        d.file_path AS d_file_path,
                        COALESCE(NULLIF(s.quality_badge, ''), d.quality_badge, '') AS quality_badge,
                        COALESCE(NULLIF(s.source_type, ''), d.source_type, '') AS source_type,
                        s.added_at
                    FROM saved_playlist_tracks s
                    LEFT JOIN downloaded_tracks d ON s.spotify_id = d.spotify_id
                    WHERE s.playlist_id = ?
                """
                params: List[Any] = [playlist_id]
                if status:
                    base_sql += " AND s.status = ?"
                    params.append(status)
                if search_query:
                    base_sql += " AND (s.title LIKE ? OR s.artist LIKE ? OR s.album LIKE ?)"
                    q = f"%{search_query}%"
                    params.extend([q, q, q])
                if genre_filter and genre_filter.strip().lower() not in ("", "all genres"):
                    base_sql += " AND (LOWER(COALESCE(NULLIF(s.genre, ''), d.genre, '')) LIKE ?)"
                    params.append(f"%{genre_filter.strip().lower()}%")
                base_sql += " ORDER BY s.track_number ASC, s.id ASC"
                if limit and limit > 0:
                    base_sql += " LIMIT ?"
                    params.append(limit)

                rows = conn.execute(base_sql, tuple(params)).fetchall()
                res = []
                for r in rows:
                    d_row = dict(r)
                    if d_row.get("status") == "downloaded" and not d_row.get("quality_badge"):
                        qb, st = self.infer_badge_from_file(d_row.get("file_path", ""))
                        if qb:
                            d_row["quality_badge"] = qb
                        if st and not d_row.get("source_type"):
                            d_row["source_type"] = st
                    res.append(d_row)
                return res
        except Exception as e:
            logger.error(f"Failed to fetch saved playlist tracks: {e}")
            return []

    def update_saved_track_status(self, playlist_id: str, spotify_id: str, new_status: str):
        """Updates the status of a specific track in a saved playlist."""
        try:
            with self.connection() as conn:
                with conn:
                    conn.execute("""
                        UPDATE saved_playlist_tracks
                        SET status = ?
                        WHERE playlist_id = ? AND spotify_id = ?
                    """, (new_status, playlist_id, spotify_id))
        except Exception as e:
            logger.debug(f"Failed to update status for {spotify_id}: {e}")

    def delete_saved_playlist(self, playlist_id: str) -> bool:
        """Deletes a saved playlist and all its associated track records."""
        try:
            with self.connection() as conn:
                with conn:
                    conn.execute("DELETE FROM saved_playlist_tracks WHERE playlist_id = ?", (playlist_id,))
                    conn.execute("DELETE FROM saved_playlists WHERE id = ?", (playlist_id,))
                logger.info(f"Deleted saved playlist: {playlist_id}")
                return True
        except Exception as e:
            logger.error(f"Failed to delete playlist {playlist_id}: {e}")
            return False

    def update_saved_playlist(
        self,
        playlist_id: str,
        name: Optional[str] = None,
        cover_url: Optional[str] = None,
        spotify_url: Optional[str] = None,
        local_cover_path: Optional[str] = None
    ) -> bool:
        """
        Updates metadata (name, cover image/URL, Spotify link) for a saved playlist.
        Synchronizes associated downloaded tracks, cover art caches, and directories.
        """
        if not playlist_id:
            return False

        old_pl = self.get_saved_playlist(playlist_id)
        if not old_pl:
            logger.warning(f"Cannot update non-existent playlist {playlist_id}")
            return False

        old_name = old_pl["name"]
        new_name = name.strip() if (name and name.strip()) else old_name
        new_cover_url = cover_url.strip() if cover_url is not None else (old_pl.get("cover_url") or "")
        new_spotify_url = spotify_url.strip() if spotify_url is not None else (old_pl.get("spotify_url") or "")

        covers_dir = str(get_covers_dir())
        os.makedirs(covers_dir, exist_ok=True)
        old_safe = sanitize_filename(old_name, max_length=50)
        new_safe = sanitize_filename(new_name, max_length=50)
        new_cached_cover = os.path.join(covers_dir, f"playlist_{new_safe}.jpg")
        old_cached_cover = os.path.join(covers_dir, f"playlist_{old_safe}.jpg")

        if local_cover_path and os.path.isfile(local_cover_path):
            try:
                shutil.copy2(local_cover_path, new_cached_cover)
            except Exception as e:
                logger.debug(f"Could not copy custom cover artwork: {e}")
        elif new_safe != old_safe and os.path.isfile(old_cached_cover) and not os.path.isfile(new_cached_cover):
            try:
                shutil.copy2(old_cached_cover, new_cached_cover)
            except Exception as e:
                logger.debug(f"Could not migrate cover artwork: {e}")
        elif new_cover_url and new_cover_url != (old_pl.get("cover_url") or ""):
            def _fetch_cover():
                try:
                    import requests
                    r = requests.get(new_cover_url, timeout=5)
                    if r.status_code == 200 and len(r.content) > 500:
                        with open(new_cached_cover, "wb") as f:
                            f.write(r.content)
                except Exception as e:
                    logger.debug(f"Could not fetch updated playlist cover: {e}")
            threading.Thread(target=_fetch_cover, daemon=True, name="CoverFetcher").start()

        try:
            with self.connection() as conn:
                with conn:
                    conn.execute("""
                        UPDATE saved_playlists
                        SET name = ?, cover_url = ?, spotify_url = ?, updated_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                    """, (new_name, new_cover_url, new_spotify_url, playlist_id))

                    if new_name != old_name:
                        conn.execute("""
                            UPDATE downloaded_tracks
                            SET collection_name = ?
                            WHERE collection_name = ?
                        """, (new_name, old_name))

                if new_name != old_name:
                    output_dir = config.get("download.output_dir", "") or str(get_default_download_dir())
                    old_dir = os.path.join(output_dir, old_safe)
                    new_dir = os.path.join(output_dir, new_safe)
                    if os.path.isdir(old_dir) and not os.path.exists(new_dir):
                        try:
                            os.rename(old_dir, new_dir)
                            norm_old = normalize_path(old_dir)
                            norm_new = normalize_path(new_dir)
                            with conn:
                                cur = conn.execute(
                                    "SELECT spotify_id, file_path FROM downloaded_tracks WHERE file_path LIKE ?",
                                    (norm_old + "%",)
                                )
                                for row in cur.fetchall():
                                    orig_fp = row["file_path"]
                                    rel = os.path.relpath(orig_fp, norm_old)
                                    updated_fp = normalize_path(os.path.join(norm_new, rel))
                                    conn.execute("UPDATE downloaded_tracks SET file_path = ? WHERE spotify_id = ?", (updated_fp, row["spotify_id"]))

                                cur2 = conn.execute(
                                    "SELECT id, file_path FROM saved_playlist_tracks WHERE playlist_id = ? AND file_path LIKE ?",
                                    (playlist_id, norm_old + "%")
                                )
                                for row in cur2.fetchall():
                                    orig_fp = row["file_path"]
                                    rel = os.path.relpath(orig_fp, norm_old)
                                    updated_fp = normalize_path(os.path.join(norm_new, rel))
                                    conn.execute("UPDATE saved_playlist_tracks SET file_path = ? WHERE id = ?", (updated_fp, row["id"]))
                        except Exception as e:
                            logger.debug(f"Could not rename folder on disk: {e}")

                logger.info(f"Updated saved playlist '{playlist_id}' -> Name: '{new_name}'")
                return True
        except Exception as e:
            logger.error(f"Failed to update playlist {playlist_id}: {e}")
            return False

    def rename_collection(self, old_name: str, new_name: str, collection_type: str = "playlist") -> bool:
        """
        Renames a playlist or collection in the downloaded tracks archive and saved playlists.
        Also renames the underlying storage folder if it exists on disk.
        """
        if not old_name or not new_name or old_name.strip() == new_name.strip():
            return False
        clean_old = old_name.strip()
        clean_new = new_name.strip()

        try:
            with self.connection() as conn:
                with conn:
                    # 1. Update downloaded_tracks collection_name
                    conn.execute("""
                        UPDATE downloaded_tracks
                        SET collection_name = ?
                        WHERE LOWER(collection_name) = LOWER(?)
                    """, (clean_new, clean_old))

                    # 2. Update saved_playlists if a matching playlist exists
                    conn.execute("""
                        UPDATE saved_playlists
                        SET name = ?, updated_at = CURRENT_TIMESTAMP
                        WHERE LOWER(name) = LOWER(?)
                    """, (clean_new, clean_old))

                # 3. Rename disk directory if present
                old_safe = sanitize_filename(clean_old, max_length=50)
                new_safe = sanitize_filename(clean_new, max_length=50)
                output_dir = config.get("download.output_dir", "") or str(get_default_download_dir())
                old_dir = os.path.join(output_dir, old_safe)
                new_dir = os.path.join(output_dir, new_safe)
                if os.path.isdir(old_dir) and not os.path.exists(new_dir):
                    try:
                        os.rename(old_dir, new_dir)
                        norm_old = normalize_path(old_dir)
                        norm_new = normalize_path(new_dir)
                        with conn:
                            cur = conn.execute(
                                "SELECT spotify_id, file_path FROM downloaded_tracks WHERE file_path LIKE ?",
                                (norm_old + "%",)
                            )
                            for row in cur.fetchall():
                                orig_fp = row["file_path"]
                                rel = os.path.relpath(orig_fp, norm_old)
                                updated_fp = normalize_path(os.path.join(norm_new, rel))
                                conn.execute("UPDATE downloaded_tracks SET file_path = ? WHERE spotify_id = ?", (updated_fp, row["spotify_id"]))

                            cur_saved = conn.execute(
                                "SELECT id, file_path FROM saved_playlist_tracks WHERE file_path LIKE ?",
                                (norm_old + "%",)
                            )
                            for row in cur_saved.fetchall():
                                orig_fp = row["file_path"]
                                rel = os.path.relpath(orig_fp, norm_old)
                                updated_fp = normalize_path(os.path.join(norm_new, rel))
                                conn.execute("UPDATE saved_playlist_tracks SET file_path = ? WHERE id = ?", (updated_fp, row["id"]))
                    except Exception as e:
                        logger.debug(f"Could not rename collection directory on disk: {e}")

                # 4. Cover cache migration
                covers_dir = str(get_covers_dir())
                for prefix in ("", "playlist_", "album_"):
                    old_c = os.path.join(covers_dir, f"{prefix}{old_safe}.jpg")
                    new_c = os.path.join(covers_dir, f"{prefix}{new_safe}.jpg")
                    if os.path.isfile(old_c) and not os.path.isfile(new_c):
                        try:
                            shutil.copy2(old_c, new_c)
                        except Exception:
                            pass

                logger.info(f"Renamed collection '{clean_old}' to '{clean_new}'.")
                return True
        except Exception as e:
            logger.error(f"Failed to rename collection '{clean_old}' to '{clean_new}': {e}")
            return False

    def update_saved_playlist_track(
        self,
        playlist_id: str,
        spotify_id: str,
        title: Optional[str] = None,
        artist: Optional[str] = None,
        album: Optional[str] = None
    ) -> bool:
        """Updates title, artist, and album for a specific track in a saved playlist."""
        if not playlist_id or not spotify_id:
            return False
        try:
            with self.connection() as conn:
                with conn:
                    r = conn.execute(
                        "SELECT title, artist, album FROM saved_playlist_tracks WHERE playlist_id = ? AND spotify_id = ?",
                        (playlist_id, spotify_id)
                    ).fetchone()
                    if not r:
                        return False
                    new_title = title.strip() if title is not None else r["title"]
                    new_artist = artist.strip() if artist is not None else r["artist"]
                    new_album = album.strip() if album is not None else (r["album"] or "")

                    conn.execute("""
                        UPDATE saved_playlist_tracks
                        SET title = ?, artist = ?, album = ?
                        WHERE playlist_id = ? AND spotify_id = ?
                    """, (new_title, new_artist, new_album, playlist_id, spotify_id))

                    conn.execute("""
                        UPDATE downloaded_tracks
                        SET title = ?, artist = ?, album = ?
                        WHERE spotify_id = ?
                    """, (new_title, new_artist, new_album, spotify_id))
                return True
        except Exception as e:
            logger.debug(f"Failed to update track {spotify_id}: {e}")
            return False

    def mark_saved_track_downloaded(
        self,
        spotify_id: str,
        file_path: str,
        quality_badge: str = "",
        source_type: str = "",
        genre: str = ""
    ):
        """Marks a track as downloaded across all saved playlists when download succeeds."""
        if not spotify_id:
            return
        if not quality_badge or not source_type:
            qb_inf, st_inf = self.infer_badge_from_file(file_path)
            quality_badge = quality_badge or qb_inf
            source_type = source_type or st_inf

        norm_fp = normalize_path(file_path)
        ext = os.path.splitext(norm_fp)[1].lower()
        if ext == ".opus":
            quality_badge = "YTM Opus"
            source_type = "YouTube Music"
        elif ext == ".m4a" and source_type not in ("YouTube", "YouTube Music"):
            quality_badge = "YTM M4A"
            source_type = "YouTube Music"
        try:
            with self.connection() as conn:
                # If genre wasn't provided, try querying it from downloaded_tracks
                if not genre:
                    r = conn.execute("SELECT genre FROM downloaded_tracks WHERE spotify_id = ? LIMIT 1", (spotify_id,)).fetchone()
                    if r and r["genre"]:
                        genre = r["genre"]

                with conn:
                    conn.execute("""
                        UPDATE saved_playlist_tracks
                        SET status = 'downloaded',
                            file_path = ?,
                            quality_badge = CASE WHEN ? != '' THEN ? ELSE quality_badge END,
                            source_type = CASE WHEN ? != '' THEN ? ELSE source_type END,
                            genre = CASE WHEN ? != '' THEN ? ELSE genre END
                        WHERE spotify_id = ?
                    """, (norm_fp, quality_badge, quality_badge, source_type, source_type, genre, genre, spotify_id))
        except Exception as e:
            logger.debug(f"Failed to mark track {spotify_id} downloaded in saved playlists: {e}")

    def mark_saved_tracks_queued(self, playlist_id: str, spotify_ids: List[str]):
        """Marks specific tracks as 'queued' when sent to the download manager."""
        if not spotify_ids:
            return
        try:
            with self.connection() as conn:
                with conn:
                    placeholders = ",".join("?" for _ in spotify_ids)
                    conn.execute(f"""
                        UPDATE saved_playlist_tracks
                        SET status = 'queued'
                        WHERE playlist_id = ? AND spotify_id IN ({placeholders}) AND status = 'pending'
                    """, (playlist_id, *spotify_ids))
        except Exception as e:
            logger.debug(f"Failed to mark tracks queued: {e}")

    def update_saved_track_status_by_spotify_id(self, spotify_id: str, new_status: str):
        """Updates the status of a specific track across all saved playlists (if not already downloaded)."""
        if not spotify_id:
            return
        try:
            with self.connection() as conn:
                with conn:
                    conn.execute("""
                        UPDATE saved_playlist_tracks
                        SET status = ?
                        WHERE spotify_id = ? AND status != 'downloaded'
                    """, (new_status, spotify_id))
        except Exception as e:
            logger.debug(f"Failed to update status for {spotify_id}: {e}")

    def revert_queued_tracks_to_pending(self, playlist_id: Optional[str] = None) -> int:
        """
        Reverts any tracks marked 'queued' or 'stopped' back to 'pending'.
        Prevents batch downloads from being permanently locked out when stopped or restarted.
        """
        try:
            with self.connection() as conn:
                with conn:
                    if playlist_id:
                        cur = conn.execute("""
                            UPDATE saved_playlist_tracks
                            SET status = 'pending'
                            WHERE playlist_id = ? AND status IN ('queued', 'stopped')
                        """, (playlist_id,))
                    else:
                        cur = conn.execute("""
                            UPDATE saved_playlist_tracks
                            SET status = 'pending'
                            WHERE status IN ('queued', 'stopped')
                        """)
                    reverted = cur.rowcount
                    if reverted > 0:
                        logger.info(f"Reverted {reverted} queued/stopped track(s) back to pending.")
                    return reverted
        except Exception as e:
            logger.debug(f"Failed to revert queued tracks to pending: {e}")
            return 0

    def retag_all_library_genres(
        self,
        root_dir: str = "",
        progress_callback: Optional[Callable[[int, int, str], None]] = None
    ) -> Dict[str, int]:
        """
        Scans all downloaded audio files in the library, checks for missing genre tags,
        resolves multi-source genres via GenreResolver, and embeds tags directly into
        FLAC, MP3, M4A, Opus, and Ogg containers. Also updates SQLite archive records.
        """
        from core.tagger import AudioTagger
        from core.genre import get_genre_resolver

        if not root_dir:
            root_dir = config.get("download.output_dir", "") or str(get_default_download_dir())
            if not os.path.isabs(root_dir):
                root_dir = os.path.normpath(os.path.join(str(get_default_download_dir()), root_dir))

        stats = {
            "scanned": 0,
            "missing_genres_found": 0,
            "retagged": 0,
            "already_tagged": 0,
            "errors": 0
        }

        if not os.path.isdir(root_dir):
            return stats

        tagger = AudioTagger()
        genre_resolver = get_genre_resolver()

        audio_files = []
        for root, dirs, files in os.walk(root_dir):
            if os.path.basename(root).lower() in ("lyrics", "cache", "logs", "bin"):
                continue
            for fname in files:
                ext = os.path.splitext(fname)[1].lower()
                if ext in (".flac", ".opus", ".mp3", ".m4a", ".ogg"):
                    audio_files.append(os.path.join(root, fname))

        total_files = len(audio_files)
        logger.info(f"Starting Genre Retagger across {total_files} audio files in: {root_dir}")

        for idx, fpath in enumerate(audio_files, 1):
            stats["scanned"] += 1
            bname = os.path.basename(fpath)
            if progress_callback:
                progress_callback(idx, total_files, f"Checking {bname}")

            ext = os.path.splitext(fpath)[1].lower()
            has_genre = False
            try:
                if ext == ".flac":
                    from mutagen.flac import FLAC
                    aud = FLAC(fpath)
                    g = aud.get("GENRE") or aud.get("genre")
                    if g and any(x.strip() for x in g):
                        has_genre = True
                elif ext in (".opus", ".ogg"):
                    try:
                        from mutagen.oggopus import OggOpus
                        aud = OggOpus(fpath)
                    except Exception:
                        from mutagen.oggvorbis import OggVorbis
                        aud = OggVorbis(fpath)
                    g = aud.get("GENRE") or aud.get("genre")
                    if g and any(x.strip() for x in g):
                        has_genre = True
                elif ext == ".mp3":
                    from mutagen.mp3 import MP3
                    aud = MP3(fpath)
                    for k in aud.keys():
                        if k.startswith("TCON"):
                            t = aud[k]
                            if t and any(str(x).strip() for x in getattr(t, "text", [])):
                                has_genre = True
                                break
                elif ext == ".m4a":
                    from mutagen.mp4 import MP4
                    aud = MP4(fpath)
                    g = aud.get("\xa9gen")
                    if g and any(str(x).strip() for x in g):
                        has_genre = True
            except Exception:
                pass

            if has_genre:
                stats["already_tagged"] += 1
                continue

            stats["missing_genres_found"] += 1

            # Resolve artist and title
            meta = self.get_track_by_path(fpath)
            artist = ""
            title = ""
            album = ""
            if meta:
                artist = meta.get("artist", "")
                title = meta.get("title", "")
                album = meta.get("album", "")
            else:
                raw_name = os.path.splitext(bname)[0]
                import re
                m_num = re.match(r"^(\d{1,3})[\s.\-_]+(.*)$", raw_name)
                if m_num:
                    raw_name = m_num.group(2).strip()
                if " - " in raw_name:
                    artist, title = raw_name.split(" - ", 1)
                else:
                    title = raw_name
                album = os.path.basename(os.path.dirname(fpath))

            if progress_callback:
                progress_callback(idx, total_files, f"Resolving genres for {bname}")

            resolved_genres = genre_resolver.resolve(artist, title, album)
            if not resolved_genres:
                resolved_genres = genre_resolver.resolve(artist, "", album)

            if not resolved_genres:
                resolved_genres = ["Pop"]

            try:
                ok = tagger.tag_genre_only(fpath, resolved_genres)
                if ok:
                    stats["retagged"] += 1
                    genre_str = "; ".join(resolved_genres)
                    self.update_track_genre(file_path=fpath, genre=genre_str)
                else:
                    stats["errors"] += 1
            except Exception as e_retag:
                logger.error(f"Failed to retag {fpath}: {e_retag}")
                stats["errors"] += 1

        logger.info(f"Library Genre Retag completed: {stats}")
        return stats

    def normalize_all_library_tracks(
        self,
        root_dir: str = "",
        target_lufs: float = -9.0,
        max_workers: int = 8,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None
    ) -> Dict[str, int]:
        """
        Scans all downloaded audio files in the library and boosts/balances their loudness
        to `target_lufs` (default -9.0 LUFS) using EBU R128 measurement and lookahead peak limiting
        while preserving 100% of embedded cover artwork, lyrics, genres, and metadata tags.
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from core.utils import normalize_audio_loudness

        if not root_dir:
            root_dir = config.get("download.output_dir", "") or str(get_default_download_dir())
            if not os.path.isabs(root_dir):
                root_dir = os.path.normpath(os.path.join(str(get_default_download_dir()), root_dir))

        stats = {
            "scanned": 0,
            "boosted": 0,
            "attenuated": 0,
            "already_balanced": 0,
            "errors": 0
        }

        if not os.path.isdir(root_dir):
            return stats

        audio_files: List[str] = []
        for root, _dirs, files in os.walk(root_dir):
            if os.path.basename(root).lower() in ("lyrics", "cache", "logs", "bin"):
                continue
            for fname in files:
                ext = os.path.splitext(fname)[1].lower()
                if ext in (".flac", ".opus", ".mp3", ".m4a", ".ogg") and not fname.endswith(".part") and ".norm_tmp" not in fname:
                    audio_files.append(os.path.join(root, fname))

        total_files = len(audio_files)
        if total_files == 0:
            return stats

        logger.info(f"Starting Library Volume Boost & Balance ({target_lufs:.1f} LUFS) across {total_files} tracks in: {root_dir}")

        def _process_one(fpath: str) -> Tuple[str, Optional[Tuple[float, float]]]:
            if cancel_check and cancel_check():
                return fpath, None
            res = normalize_audio_loudness(fpath, target_lufs=target_lufs)
            return fpath, res

        completed_idx = 0
        with ThreadPoolExecutor(max_workers=max(1, max_workers)) as pool:
            futures = {pool.submit(_process_one, fp): fp for fp in audio_files}
            for fut in as_completed(futures):
                if cancel_check and cancel_check():
                    break
                completed_idx += 1
                stats["scanned"] += 1
                fp = futures[fut]
                bname = os.path.basename(fp)
                try:
                    _, result = fut.result()
                    if result is None:
                        stats["errors"] += 1
                        status_txt = f"Skipped {bname}"
                    else:
                        orig_lufs, gain_db = result
                        if abs(gain_db) < 0.05:
                            stats["already_balanced"] += 1
                            status_txt = f"Balanced: {bname}"
                        elif gain_db > 0:
                            stats["boosted"] += 1
                            status_txt = f"Boosted {bname} ({gain_db:+.1f} dB)"
                        else:
                            stats["attenuated"] += 1
                            status_txt = f"Balanced {bname} ({gain_db:+.1f} dB)"
                except Exception as e:
                    logger.debug(f"Volume normalization worker error on {fp}: {e}")
                    stats["errors"] += 1
                    status_txt = f"Error on {bname}"

                if progress_callback:
                    progress_callback(completed_idx, total_files, status_txt)

        logger.info(f"Library Volume Boost & Balance completed: {stats}")
        return stats

    def retag_all_library_replaygain(
        self,
        root_dir: str = "",
        progress_callback: Optional[Callable[[int, int, str], None]] = None
    ) -> Dict[str, int]:
        """
        Calculates EBU R128 ReplayGain 2.0 tags and embeds them across all audio files in the library.
        """
        from core.tagger import AudioTagger
        from core.utils import calculate_replaygain

        if not root_dir:
            root_dir = config.get("download.output_dir", "") or str(get_default_download_dir())
            if not os.path.isabs(root_dir):
                root_dir = os.path.normpath(os.path.join(str(get_default_download_dir()), root_dir))

        stats = {"scanned": 0, "calculated": 0, "errors": 0}
        if not os.path.isdir(root_dir):
            return stats

        tagger = AudioTagger()
        audio_files: List[str] = []
        for root, _dirs, files in os.walk(root_dir):
            if os.path.basename(root).lower() in ("lyrics", "cache", "logs", "bin"):
                continue
            for fname in files:
                ext = os.path.splitext(fname)[1].lower()
                if ext in (".flac", ".opus", ".mp3", ".m4a", ".ogg") and not fname.endswith(".part"):
                    audio_files.append(os.path.join(root, fname))

        total_files = len(audio_files)
        for idx, fpath in enumerate(audio_files, 1):
            stats["scanned"] += 1
            bname = os.path.basename(fpath)
            if progress_callback:
                progress_callback(idx, total_files, f"Analyzing {bname}")
            try:
                rg = calculate_replaygain(fpath)
                if rg and tagger.tag_replaygain(fpath, rg[0], rg[1]):
                    stats["calculated"] += 1
                else:
                    stats["errors"] += 1
            except Exception:
                stats["errors"] += 1

        return stats

    # -------------------------------------------------------------------------
    # Smart Duplicate & Acoustic Fingerprint Merger + Batch Spectrum Scanner
    # -------------------------------------------------------------------------
    @staticmethod
    def _quality_rank(file_path: str, quality_badge: str = "", size_bytes: int = 0) -> Tuple[int, int]:
        ext = os.path.splitext(file_path)[1].lower()
        badge_up = (quality_badge or "").upper()
        if ext == ".flac":
            tier = 100 if "24" in badge_up else 90
        elif ext == ".wav":
            tier = 85
        elif ext == ".mp3":
            tier = 75 if "320" in badge_up else 65
        elif ext == ".opus":
            tier = 70
        elif ext == ".m4a":
            tier = 68
        else:
            tier = 50
        return tier, size_bytes

    def find_library_duplicates(
        self,
        root_dir: str = "",
        use_acoustic_fingerprint: bool = True,
        progress_callback: Optional[Callable[[int, int, str], None]] = None
    ) -> List[Dict[str, Any]]:
        """
        Detects duplicate songs across the library (Single vs Album releases, multiple playlist folders,
        or multiple format downloads) using:
        1. ISRC code matching
        2. Canonical normalized Artist + Title + Duration matching
        3. Acoustic Envelope Fingerprinting (64-bit energy/ZCR signature)
        Returns a list of duplicate group dictionaries with a ranked 'master' file and 'duplicates' list.
        """
        from core.utils import compute_acoustic_fingerprint, fingerprint_similarity, normalize_special_unicode, phonetic_skeleton

        if not root_dir:
            root_dir = config.get("download.output_dir", "") or str(get_default_download_dir())
            if not os.path.isabs(root_dir):
                root_dir = os.path.normpath(os.path.join(str(get_default_download_dir()), root_dir))

        db_rows = self.get_all_tracks()
        path_to_meta: Dict[str, Dict[str, Any]] = {}
        for r in db_rows:
            fp = normalize_path(r.get("file_path", ""))
            if fp and os.path.isfile(fp):
                entry = path_to_meta.setdefault(fp, {
                    "file_path": fp,
                    "title": r.get("title", ""),
                    "artist": r.get("artist", ""),
                    "album": r.get("album", ""),
                    "isrc": (r.get("isrc") or "").strip().upper(),
                    "duration_ms": int(r.get("duration_ms") or 0),
                    "quality_badge": r.get("quality_badge", ""),
                    "spotify_ids": [],
                })
                if r.get("spotify_id") and r["spotify_id"] not in entry["spotify_ids"]:
                    entry["spotify_ids"].append(r["spotify_id"])

        # Also scan disk for any audio files in root_dir not yet in path_to_meta
        if os.path.isdir(root_dir):
            for root, _dirs, files in os.walk(root_dir):
                if os.path.basename(root).lower() in ("lyrics", "cache", "logs", "bin", "eq_preview", "spectrograms"):
                    continue
                for fname in files:
                    ext = os.path.splitext(fname)[1].lower()
                    if ext in (".flac", ".mp3", ".opus", ".m4a", ".ogg") and not fname.endswith(".part") and ".norm_tmp" not in fname:
                        fp = normalize_path(os.path.join(root, fname))
                        if fp not in path_to_meta and os.path.isfile(fp):
                            stem = os.path.splitext(fname)[0]
                            stem = TRACK_PREFIX_PATTERN.sub("", stem).strip()
                            artist_g, title_g = (stem.split(" - ", 1) if " - " in stem else ("Unknown Artist", stem))
                            qb_inf, _ = self.infer_badge_from_file(fp)
                            dur_ms = 0
                            try:
                                import mutagen
                                m = mutagen.File(fp)
                                if m and m.info:
                                    dur_ms = int(float(getattr(m.info, "length", 0.0) or 0.0) * 1000)
                            except Exception:
                                pass
                            path_to_meta[fp] = {
                                "file_path": fp,
                                "title": title_g.strip(),
                                "artist": artist_g.strip(),
                                "album": os.path.basename(root),
                                "isrc": "",
                                "duration_ms": dur_ms,
                                "quality_badge": qb_inf,
                                "spotify_ids": [],
                            }

        all_entries = list(path_to_meta.values())
        total = len(all_entries)
        if total < 2:
            return []

        for idx, ent in enumerate(all_entries, 1):
            fp = ent["file_path"]
            try:
                st = os.stat(fp)
                ent["size_bytes"] = st.st_size
                ent["inode"] = (st.st_dev, st.st_ino) if st.st_ino else None
            except Exception:
                ent["size_bytes"] = 0
                ent["inode"] = None

            clean_t = re.sub(r'[\(\[\{].*?[\)\]\}]', '', normalize_special_unicode(ent["title"])).strip().lower()
            clean_a = normalize_special_unicode(ent["artist"]).split(",")[0].strip().lower()
            ent["norm_key"] = f"{phonetic_skeleton(clean_a) or clean_a}::{phonetic_skeleton(clean_t) or clean_t}"

        # Union-Find clustering across all_entries
        parent = list(range(total))
        reasons: Dict[int, str] = {}

        def find(i: int) -> int:
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        def union(i: int, j: int, reason: str):
            ri, rj = find(i), find(j)
            if ri != rj:
                parent[rj] = ri
                reasons[ri] = reason

        # Pass 1: ISRC exact match
        isrc_map: Dict[str, int] = {}
        for i, ent in enumerate(all_entries):
            isrc = ent.get("isrc", "")
            if isrc and len(isrc) >= 8:
                if isrc in isrc_map:
                    union(isrc_map[isrc], i, f"ISRC Match ({isrc})")
                else:
                    isrc_map[isrc] = i

        # Pass 2: Normalized Artist + Title + Duration (within ±4.5s)
        key_map: Dict[str, List[int]] = {}
        for i, ent in enumerate(all_entries):
            nk = ent["norm_key"]
            if nk and nk != "::":
                for prev_i in key_map.get(nk, []):
                    d1 = ent.get("duration_ms") or 0
                    d2 = all_entries[prev_i].get("duration_ms") or 0
                    if d1 == 0 or d2 == 0 or abs(d1 - d2) <= 4500:
                        union(prev_i, i, "Same Artist & Title")
                key_map.setdefault(nk, []).append(i)

        # Pass 3: Acoustic Fingerprint for same-title or close-duration tracks
        if use_acoustic_fingerprint:
            title_buckets: Dict[str, List[int]] = {}
            for i, ent in enumerate(all_entries):
                t_part = ent["norm_key"].split("::")[-1]
                if len(t_part) >= 3:
                    title_buckets.setdefault(t_part, []).append(i)

            candidates_for_fp = [idxs for idxs in title_buckets.values() if len(idxs) > 1]
            done_fp = 0
            for idxs in candidates_for_fp:
                # Only compute fingerprints if not all already in same cluster
                roots = {find(x) for x in idxs}
                if len(roots) <= 1:
                    continue
                for x in idxs:
                    if "fingerprint" not in all_entries[x]:
                        done_fp += 1
                        if progress_callback:
                            progress_callback(done_fp, len(all_entries), f"Fingerprinting {os.path.basename(all_entries[x]['file_path'])}")
                        all_entries[x]["fingerprint"] = compute_acoustic_fingerprint(all_entries[x]["file_path"]) or ""
                for a_idx in range(len(idxs)):
                    for b_idx in range(a_idx + 1, len(idxs)):
                        ia, ib = idxs[a_idx], idxs[b_idx]
                        if find(ia) == find(ib):
                            continue
                        fp_a = all_entries[ia].get("fingerprint", "")
                        fp_b = all_entries[ib].get("fingerprint", "")
                        sim = fingerprint_similarity(fp_a, fp_b)
                        if sim >= 0.86:
                            union(ia, ib, f"Acoustic Fingerprint ({int(sim * 100)}% Match)")

        clusters: Dict[int, List[Dict[str, Any]]] = {}
        for i, ent in enumerate(all_entries):
            r = find(i)
            clusters.setdefault(r, []).append(ent)

        duplicate_groups: List[Dict[str, Any]] = []
        for root_idx, members in clusters.items():
            if len(members) < 2:
                continue
            # Sort members by quality rank descending so best file is master
            members_sorted = sorted(
                members,
                key=lambda m: self._quality_rank(m["file_path"], m.get("quality_badge", ""), m.get("size_bytes", 0)),
                reverse=True
            )
            master = members_sorted[0]
            dups = members_sorted[1:]
            master_inode = master.get("inode")
            reclaimable = 0
            for d in dups:
                is_hl = bool(master_inode and d.get("inode") == master_inode and master_inode[1] != 0)
                d["is_hardlinked"] = is_hl
                if not is_hl:
                    reclaimable += d.get("size_bytes", 0)

            duplicate_groups.append({
                "key": master["norm_key"],
                "title": master["title"],
                "artist": master["artist"],
                "match_reason": reasons.get(root_idx, "Metadata + Duration Match"),
                "master": master,
                "duplicates": dups,
                "reclaimable_bytes": reclaimable,
            })

        duplicate_groups.sort(key=lambda g: g["reclaimable_bytes"], reverse=True)
        return duplicate_groups

    def merge_library_duplicates(
        self,
        duplicate_groups: List[Dict[str, Any]],
        mode: str = "hardlink"
    ) -> Dict[str, Any]:
        """
        Consolidates duplicate audio files across the library while keeping all SQLite archive
        records and .m3u8 playlists 100% intact.
        Modes:
        - 'hardlink': Replaces duplicate files of the same format with NTFS hard links to the master file
                      (zero disk space used by duplicates, files stay in both folders), or re-links DB records
                      if formats differ.
        - 'merge': Deletes redundant duplicate files, re-links all DB records (downloaded_tracks &
                   saved_playlist_tracks) to the master file, and regenerates all .m3u8 playlists.
        """
        stats = {
            "groups_processed": 0,
            "files_merged": 0,
            "hardlinked": 0,
            "reclaimed_bytes": 0,
            "errors": 0,
        }
        if not duplicate_groups:
            return stats

        for grp in duplicate_groups:
            master = grp.get("master") or {}
            master_fp = normalize_path(master.get("file_path", ""))
            master_badge = master.get("quality_badge", "")
            if not master_fp or not os.path.isfile(master_fp):
                continue

            master_ext = os.path.splitext(master_fp)[1].lower()
            grp_touched = False

            for dup in grp.get("duplicates", []):
                dup_fp = normalize_path(dup.get("file_path", ""))
                if not dup_fp or dup_fp.lower() == master_fp.lower() or not os.path.isfile(dup_fp):
                    continue
                if dup.get("is_hardlinked"):
                    continue

                dup_size = dup.get("size_bytes") or os.path.getsize(dup_fp)
                dup_ext = os.path.splitext(dup_fp)[1].lower()

                try:
                    if mode == "hardlink" and dup_ext == master_ext:
                        # Replace dup_fp with an atomic NTFS hard link to master_fp
                        tmp_bak = f"{dup_fp}.hl_bak"
                        os.replace(dup_fp, tmp_bak)
                        try:
                            os.link(master_fp, dup_fp)
                            os.remove(tmp_bak)
                            stats["hardlinked"] += 1
                            stats["files_merged"] += 1
                            stats["reclaimed_bytes"] += dup_size
                            grp_touched = True
                            continue
                        except Exception:
                            # Rollback if cross-volume or filesystem doesn't support hardlinks; fall through to DB merge
                            if os.path.exists(tmp_bak) and not os.path.exists(dup_fp):
                                os.replace(tmp_bak, dup_fp)

                    # Clean Merge: re-point all DB references from dup_fp -> master_fp and delete dup_fp
                    with self.connection() as conn:
                        with conn:
                            conn.execute(
                                "UPDATE downloaded_tracks SET file_path = ?, quality_badge = CASE WHEN ? != '' THEN ? ELSE quality_badge END WHERE file_path = ? COLLATE NOCASE",
                                (master_fp, master_badge, master_badge, dup_fp)
                            )
                            conn.execute(
                                "UPDATE saved_playlist_tracks SET file_path = ?, quality_badge = CASE WHEN ? != '' THEN ? ELSE quality_badge END WHERE file_path = ? COLLATE NOCASE",
                                (master_fp, master_badge, master_badge, dup_fp)
                            )
                            for sid in dup.get("spotify_ids", []):
                                conn.execute(
                                    "UPDATE downloaded_tracks SET file_path = ? WHERE spotify_id = ?",
                                    (master_fp, sid)
                                )
                                conn.execute(
                                    "UPDATE saved_playlist_tracks SET file_path = ?, status = 'downloaded' WHERE spotify_id = ?",
                                    (master_fp, sid)
                                )
                    try:
                        os.remove(dup_fp)
                        stats["files_merged"] += 1
                        stats["reclaimed_bytes"] += dup_size
                        grp_touched = True
                    except Exception as e_rm:
                        logger.debug(f"Could not delete merged duplicate {dup_fp}: {e_rm}")
                        stats["errors"] += 1
                except Exception as e:
                    logger.warning(f"Error merging duplicate {dup_fp} -> {master_fp}: {e}")
                    stats["errors"] += 1

            if grp_touched:
                stats["groups_processed"] += 1

        # Refresh all .m3u8 playlist files so every playlist points to the consolidated paths
        try:
            self.sync_all_playlist_m3u8_files()
        except Exception:
            pass

        return stats

    def scan_library_spectrum(
        self,
        root_dir: str = "",
        max_workers: int = 6,
        progress_callback: Optional[Callable[[int, int, str], None]] = None
    ) -> List[Dict[str, Any]]:
        """
        Batch-scans downloaded tracks in the library using ultrasonic spectrum analysis
        to identify upscaled / fake-bitrate transcodes (< 16.8 kHz cutoff).
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from core.utils import inspect_audio_spectrum

        if not root_dir:
            root_dir = config.get("download.output_dir", "") or str(get_default_download_dir())
            if not os.path.isabs(root_dir):
                root_dir = os.path.normpath(os.path.join(str(get_default_download_dir()), root_dir))

        audio_files: List[str] = []
        if os.path.isdir(root_dir):
            for root, _dirs, files in os.walk(root_dir):
                if os.path.basename(root).lower() in ("lyrics", "cache", "logs", "bin", "eq_preview", "spectrograms"):
                    continue
                for fname in files:
                    ext = os.path.splitext(fname)[1].lower()
                    if ext in (".flac", ".mp3", ".opus", ".m4a", ".ogg") and not fname.endswith(".part"):
                        audio_files.append(os.path.join(root, fname))

        total = len(audio_files)
        results: List[Dict[str, Any]] = []
        if total == 0:
            return results

        completed = 0
        with ThreadPoolExecutor(max_workers=max(1, max_workers)) as pool:
            futs = {pool.submit(inspect_audio_spectrum, fp, False): fp for fp in audio_files}
            for fut in as_completed(futs):
                completed += 1
                fp = futs[fut]
                bname = os.path.basename(fp)
                if progress_callback:
                    progress_callback(completed, total, f"Inspecting {bname}")
                try:
                    res = fut.result()
                    if res:
                        meta = self.get_track_by_path(fp) or {}
                        res["title"] = meta.get("title") or os.path.splitext(bname)[0]
                        res["artist"] = meta.get("artist") or ""
                        res["spotify_id"] = meta.get("spotify_id") or ""
                        results.append(res)
                except Exception:
                    pass

        results.sort(key=lambda r: (0 if r.get("verdict") == "upscaled" else (1 if r.get("verdict") == "good" else 2), r.get("cutoff_khz", 20.0)))
        return results



