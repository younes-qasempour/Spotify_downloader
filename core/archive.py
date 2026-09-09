import os
import sqlite3
import threading
import logging
from typing import Optional, List, Dict, Any
from pathlib import Path

from core.spotify_client import TrackMetadata

logger = logging.getLogger("core.archive")


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
        if getattr(self, "_initialized", False):
            return
        self._initialized = True

        if db_path:
            self.db_path = Path(db_path)
        else:
            # Default to archive.db in the project root directory
            self.db_path = Path(__file__).resolve().parent.parent / "archive.db"

        self._db_lock = threading.Lock()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=15.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        """Initializes database tables and performance indexes."""
        with self._db_lock:
            conn = self._get_connection()
            try:
                with conn:
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS downloaded_tracks (
                            spotify_id TEXT PRIMARY KEY,
                            isrc TEXT,
                            title TEXT NOT NULL,
                            artist TEXT NOT NULL,
                            album TEXT,
                            duration_ms INTEGER,
                            file_path TEXT NOT NULL,
                            file_size INTEGER DEFAULT 0,
                            quality_badge TEXT DEFAULT 'FLAC',
                            source_type TEXT DEFAULT 'Musilon',
                            collection_name TEXT,
                            collection_type TEXT,
                            downloaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        );
                    """)
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_artist_title ON downloaded_tracks (artist, title);")
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_isrc ON downloaded_tracks (isrc);")
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_downloaded_at ON downloaded_tracks (downloaded_at DESC);")
                logger.info(f"Initialized Archive database at: {self.db_path}")
            except Exception as e:
                logger.error(f"Failed to initialize Archive database: {e}")
            finally:
                conn.close()

    def add_track(
        self,
        track: TrackMetadata,
        file_path: str,
        quality_badge: str,
        source_type: str,
        file_size: int = 0
    ) -> bool:
        """Records or updates a successfully downloaded track in the archive."""
        if not file_path or not os.path.isfile(file_path):
            return False

        norm_path = os.path.normpath(os.path.abspath(file_path))
        if file_size <= 0:
            try:
                file_size = os.path.getsize(norm_path)
            except Exception:
                file_size = 0

        with self._db_lock:
            conn = self._get_connection()
            try:
                with conn:
                    conn.execute("""
                        INSERT OR REPLACE INTO downloaded_tracks (
                            spotify_id, isrc, title, artist, album, duration_ms,
                            file_path, file_size, quality_badge, source_type,
                            collection_name, collection_type, downloaded_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    """, (
                        track.id,
                        track.isrc or "",
                        track.title,
                        track.artist_str,
                        track.album or "",
                        track.duration_ms,
                        norm_path,
                        file_size,
                        quality_badge,
                        source_type,
                        getattr(track, "collection_name", ""),
                        getattr(track, "collection_type", "track")
                    ))
                logger.debug(f"Archived track '{track.title}' -> {norm_path}")
                return True
            except Exception as e:
                logger.error(f"Failed to record track in archive: {e}")
                return False
            finally:
                conn.close()

    def find_track(
        self,
        spotify_id: str = "",
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
        with self._db_lock:
            conn = self._get_connection()
            try:
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
                if file_path and os.path.isfile(file_path):
                    return data
                else:
                    # File was deleted from disk; remove stale record
                    logger.info(f"Archived file deleted from disk: {file_path}. Cleaning record.")
                    with conn:
                        conn.execute("DELETE FROM downloaded_tracks WHERE spotify_id = ?", (data["spotify_id"],))
                    return None

            except Exception as e:
                logger.error(f"Error querying archive: {e}")
                return None
            finally:
                conn.close()

    def get_all_tracks(self, search_query: str = "") -> List[Dict[str, Any]]:
        """Retrieves all archived tracks, optionally filtered by title, artist, or album."""
        with self._db_lock:
            conn = self._get_connection()
            try:
                if search_query:
                    q = f"%{search_query.strip().lower()}%"
                    cur = conn.execute("""
                        SELECT * FROM downloaded_tracks
                        WHERE LOWER(title) LIKE ? OR LOWER(artist) LIKE ? OR LOWER(album) LIKE ? OR LOWER(collection_name) LIKE ?
                        ORDER BY downloaded_at DESC
                    """, (q, q, q, q))
                else:
                    cur = conn.execute("SELECT * FROM downloaded_tracks ORDER BY downloaded_at DESC")

                results: List[Dict[str, Any]] = []
                stale_ids: List[str] = []

                for row in cur.fetchall():
                    item = dict(row)
                    # Verify file exists on disk
                    if os.path.isfile(item.get("file_path", "")):
                        results.append(item)
                    else:
                        stale_ids.append(item["spotify_id"])

                # Clean stale records in background
                if stale_ids:
                    with conn:
                        conn.executemany("DELETE FROM downloaded_tracks WHERE spotify_id = ?", [(i,) for i in stale_ids])

                return results
            except Exception as e:
                logger.error(f"Failed to fetch archive tracks: {e}")
                return []
            finally:
                conn.close()

    def get_track_count(self) -> int:
        """Returns total valid tracks stored in archive."""
        with self._db_lock:
            conn = self._get_connection()
            try:
                cur = conn.execute("SELECT COUNT(*) FROM downloaded_tracks")
                return cur.fetchone()[0]
            except Exception:
                return 0
            finally:
                conn.close()

    def delete_track(self, spotify_id: str) -> bool:
        """Deletes a track from the archive record."""
        with self._db_lock:
            conn = self._get_connection()
            try:
                with conn:
                    conn.execute("DELETE FROM downloaded_tracks WHERE spotify_id = ?", (spotify_id,))
                return True
            except Exception as e:
                logger.error(f"Failed to delete track {spotify_id} from archive: {e}")
                return False
            finally:
                conn.close()

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
            from mutagen.easyid3 import EasyID3
            from mutagen.flac import FLAC
            from mutagen.mp4 import MP4
            from mutagen.oggopus import OggOpus
        except ImportError:
            mutagen = None

        for dirpath, _, filenames in os.walk(root_dir):
            folder_name = os.path.basename(dirpath)
            for fname in filenames:
                ext = os.path.splitext(fname)[1].lower()
                if ext not in audio_exts:
                    continue

                full_path = os.path.normpath(os.path.join(dirpath, fname))

                # Check if already indexed
                with self._db_lock:
                    conn = self._get_connection()
                    try:
                        cur = conn.execute("SELECT spotify_id FROM downloaded_tracks WHERE file_path = ? LIMIT 1", (full_path,))
                        if cur.fetchone():
                            conn.close()
                            continue
                    except Exception:
                        pass
                    finally:
                        conn.close()

                # Extract basic tags
                title = os.path.splitext(fname)[0]
                artist = "Unknown Artist"
                album = folder_name
                isrc = ""
                quality = "FLAC 16" if ext == ".flac" else ("320k" if ext == ".mp3" else "Opus")

                if " - " in title:
                    parts = title.split(" - ", 1)
                    artist = parts[0].strip()
                    title = parts[1].strip()

                if mutagen:
                    try:
                        audio = mutagen.File(full_path)
                        if audio:
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

                # Derive synthetic ID from artist and title hash
                synth_id = f"local_{abs(hash(artist + title))}"
                fake_track = TrackMetadata(
                    id=synth_id,
                    title=title,
                    artists=[artist],
                    album=album,
                    release_date="",
                    duration_ms=0,
                    isrc=isrc,
                    collection_name=folder_name,
                    collection_type="playlist" if folder_name not in ("Singles", "downloads") else "track"
                )

                if self.add_track(fake_track, full_path, quality, "Local File"):
                    indexed_count += 1

        if indexed_count > 0:
            logger.info(f"Scanned {root_dir} and indexed {indexed_count} existing tracks into Archive.")
        return indexed_count
