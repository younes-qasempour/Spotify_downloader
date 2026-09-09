import os
import sqlite3
import threading
import logging
from typing import Optional, List, Dict, Any
from pathlib import Path

from core.spotify_client import TrackMetadata
from core.utils import extract_embedded_cover

logger = logging.getLogger("core.archive")


def resolve_collection_cover(folder_path: str, sample_file: str = "") -> str:
    """
    Checks if a collection folder has a cover image (cover.jpg, cover.png, etc.).
    If not, extracts embedded artwork from sample_file (or first audio file found in folder)
    and saves it to folder_path/cover.jpg so it can be displayed as the collection's thumbnail.
    Returns the path to the cover image if found/created, or empty string.
    """
    if not folder_path or not os.path.isdir(folder_path):
        return ""

    for ext in (".jpg", ".jpeg", ".png", ".webp"):
        candidate = os.path.join(folder_path, f"cover{ext}")
        if os.path.isfile(candidate):
            return candidate
        candidate_f = os.path.join(folder_path, f"folder{ext}")
        if os.path.isfile(candidate_f):
            return candidate_f

    # If no cover image exists, attempt extraction from sample_file or first audio file
    target_audio = sample_file if (sample_file and os.path.isfile(sample_file)) else None
    if not target_audio:
        try:
            for fname in os.listdir(folder_path):
                if os.path.splitext(fname)[1].lower() in (".flac", ".mp3", ".opus", ".m4a", ".ogg"):
                    target_audio = os.path.join(folder_path, fname)
                    break
        except Exception:
            pass

    if target_audio and os.path.isfile(target_audio):
        try:
            art_bytes = extract_embedded_cover(target_audio)
            if art_bytes and len(art_bytes) > 500:
                cover_out = os.path.join(folder_path, "cover.jpg")
                with open(cover_out, "wb") as f:
                    f.write(art_bytes)
                logger.info(f"Generated collection cover from audio track: {cover_out}")
                return cover_out
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
        """Initializes database tables, performance indexes, and schema migrations."""
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
                            track_number INTEGER DEFAULT 1,
                            disc_number INTEGER DEFAULT 1,
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

                    # Migrations for existing databases
                    try:
                        conn.execute("ALTER TABLE downloaded_tracks ADD COLUMN track_number INTEGER DEFAULT 1;")
                    except sqlite3.OperationalError:
                        pass
                    try:
                        conn.execute("ALTER TABLE downloaded_tracks ADD COLUMN disc_number INTEGER DEFAULT 1;")
                    except sqlite3.OperationalError:
                        pass

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
                            track_number, disc_number,
                            file_path, file_size, quality_badge, source_type,
                            collection_name, collection_type, downloaded_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    """, (
                        track.id,
                        track.isrc or "",
                        track.title,
                        track.artist_str,
                        track.album or "",
                        track.duration_ms,
                        getattr(track, "track_number", 1) or 1,
                        getattr(track, "disc_number", 1) or 1,
                        norm_path,
                        file_size,
                        quality_badge,
                        source_type,
                        getattr(track, "collection_name", ""),
                        getattr(track, "collection_type", "track")
                    ))
                logger.debug(f"Archived track '{track.title}' (track #{getattr(track, 'track_number', 1)}) -> {norm_path}")
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

    def get_library_stats(self) -> Dict[str, Any]:
        """Returns high-level statistics for the offline music library."""
        with self._db_lock:
            conn = self._get_connection()
            try:
                cur = conn.execute("""
                    SELECT 
                        COUNT(*) as total_tracks,
                        COUNT(DISTINCT CASE WHEN (collection_type = 'playlist' OR (collection_name IS NOT NULL AND collection_name != ''))
                                             AND (collection_type IS NULL OR collection_type != 'album')
                                             AND LOWER(collection_name) NOT IN (
                                                 SELECT DISTINCT LOWER(COALESCE(NULLIF(album, ''), collection_name))
                                                 FROM downloaded_tracks
                                                 WHERE collection_type = 'album'
                                             )
                                        THEN collection_name END) as total_playlists,
                        COUNT(DISTINCT CASE WHEN collection_type = 'album' OR (album IS NOT NULL AND TRIM(album) != '' AND LOWER(album) NOT IN ('spotify playlist', 'singles', 'unknown album', 'downloads') AND (collection_type IS NULL OR collection_type != 'playlist'))
                                        THEN COALESCE(NULLIF(album, ''), collection_name) END) as total_albums,
                        COALESCE(SUM(file_size), 0) as total_bytes
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
            finally:
                conn.close()

    def get_playlists(self, search_query: str = "") -> List[Dict[str, Any]]:
        """
        Aggregates downloaded tracks by collection / playlist folder.
        Returns a list of playlists with track counts, total size, folder paths, and sample tracks.
        Excludes albums (which strictly belong in get_albums).
        """
        with self._db_lock:
            conn = self._get_connection()
            try:
                cur = conn.execute("""
                    SELECT 
                        COALESCE(NULLIF(collection_name, ''), 'Singles') as name,
                        collection_type,
                        COUNT(*) as track_count,
                        COALESCE(SUM(file_size), 0) as total_size,
                        MIN(file_path) as sample_file,
                        MAX(downloaded_at) as latest_download
                    FROM downloaded_tracks
                    WHERE (collection_type IS NULL OR collection_type != 'album')
                      AND LOWER(COALESCE(NULLIF(collection_name, ''), 'Singles')) NOT IN (
                          SELECT DISTINCT LOWER(COALESCE(NULLIF(album, ''), collection_name))
                          FROM downloaded_tracks
                          WHERE collection_type = 'album'
                      )
                    GROUP BY name
                    ORDER BY latest_download DESC
                """)
                rows = cur.fetchall()
                results: List[Dict[str, Any]] = []
                q = search_query.strip().lower()

                for r in rows:
                    pl_name = r["name"]
                    if q and q not in pl_name.lower():
                        continue

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

                    cover_path = resolve_collection_cover(folder_path, sample_file)

                    results.append({
                        "name": pl_name,
                        "collection_type": r["collection_type"] or "playlist",
                        "track_count": r["track_count"],
                        "total_size_bytes": sz_bytes,
                        "size_str": sz_str,
                        "folder_path": folder_path,
                        "cover_path": cover_path,
                        "latest_download": r["latest_download"]
                    })
                return results
            except Exception as e:
                logger.error(f"Failed to aggregate playlists: {e}")
                return []
            finally:
                conn.close()

    def get_albums(self, search_query: str = "") -> List[Dict[str, Any]]:
        """
        Aggregates downloaded tracks by album.
        Only returns genuine albums (downloaded via album URL or with genuine album metadata,
        excluding playlist placeholders like 'Spotify Playlist').
        """
        with self._db_lock:
            conn = self._get_connection()
            try:
                cur = conn.execute("""
                    SELECT 
                        COALESCE(NULLIF(album, ''), collection_name) as name,
                        artist,
                        COUNT(*) as track_count,
                        COALESCE(SUM(file_size), 0) as total_size,
                        MIN(file_path) as sample_file,
                        MAX(downloaded_at) as latest_download
                    FROM downloaded_tracks
                    WHERE collection_type = 'album'
                       OR (album IS NOT NULL 
                           AND TRIM(album) != '' 
                           AND LOWER(album) NOT IN ('spotify playlist', 'singles', 'unknown album', 'downloads')
                           AND collection_type != 'playlist')
                    GROUP BY name, artist
                    ORDER BY track_count DESC, latest_download DESC
                """)
                rows = cur.fetchall()
                results: List[Dict[str, Any]] = []
                q = search_query.strip().lower()

                for r in rows:
                    alb_name = r["name"]
                    artist_name = r["artist"] or ""
                    if q and (q not in alb_name.lower() and q not in artist_name.lower()):
                        continue

                    sample_file = r["sample_file"] or ""
                    folder_path = os.path.dirname(sample_file) if sample_file else ""

                    sz_bytes = r["total_size"]
                    if sz_bytes >= 1024 * 1024 * 1024:
                        sz_str = f"{sz_bytes / (1024 ** 3):.2f} GB"
                    else:
                        sz_str = f"{sz_bytes / (1024 ** 2):.1f} MB"

                    cover_path = resolve_collection_cover(folder_path, sample_file)

                    results.append({
                        "name": alb_name,
                        "artist": artist_name,
                        "track_count": r["track_count"],
                        "total_size_bytes": sz_bytes,
                        "size_str": sz_str,
                        "folder_path": folder_path,
                        "cover_path": cover_path,
                        "latest_download": r["latest_download"]
                    })
                return results
            except Exception as e:
                logger.error(f"Failed to aggregate albums: {e}")
                return []
            finally:
                conn.close()

    def get_collection_tracks(self, collection_name: str, collection_type: str = "playlist") -> List[Dict[str, Any]]:
        """Retrieves all tracks belonging to a specific collection (playlist or album) ordered by track number."""
        with self._db_lock:
            conn = self._get_connection()
            try:
                if collection_type == "album":
                    cur = conn.execute("""
                        SELECT * FROM downloaded_tracks
                        WHERE LOWER(album) = LOWER(?) OR LOWER(collection_name) = LOWER(?)
                        ORDER BY track_number ASC, title ASC
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
                for row in cur.fetchall():
                    item = dict(row)
                    if os.path.isfile(item.get("file_path", "")):
                        results.append(item)
                return results
            except Exception as e:
                logger.error(f"Failed to fetch collection tracks for '{collection_name}': {e}")
                return []
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

        import hashlib
        for dirpath, _, filenames in os.walk(root_dir):
            folder_name = os.path.basename(dirpath)
            for fname in filenames:
                ext = os.path.splitext(fname)[1].lower()
                if ext not in audio_exts:
                    continue

                full_path = os.path.normpath(os.path.join(dirpath, fname))

                # Check if already indexed by path (case-insensitive on Windows)
                with self._db_lock:
                    conn = self._get_connection()
                    try:
                        cur = conn.execute("SELECT spotify_id FROM downloaded_tracks WHERE LOWER(file_path) = LOWER(?) LIMIT 1", (full_path,))
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
                track_num = 0
                disc_num = 1
                quality = "FLAC 16" if ext == ".flac" else ("320k" if ext == ".mp3" else "Opus")

                if " - " in title:
                    parts = title.split(" - ", 1)
                    artist = parts[0].strip()
                    title = parts[1].strip()

                # Check if already in database by (title, artist, collection)
                with self._db_lock:
                    conn = self._get_connection()
                    try:
                        cur = conn.execute("""
                            SELECT spotify_id FROM downloaded_tracks 
                            WHERE LOWER(title) = LOWER(?) AND LOWER(artist) = LOWER(?) 
                              AND (LOWER(collection_name) = LOWER(?) OR LOWER(album) = LOWER(?))
                            LIMIT 1
                        """, (title, artist, folder_name, folder_name))
                        if cur.fetchone():
                            conn.close()
                            continue
                    except Exception:
                        pass
                    finally:
                        conn.close()

                if mutagen:
                    try:
                        audio = mutagen.File(full_path)
                        if audio:
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

                # Check if this folder belongs to an album
                is_album = False
                with self._db_lock:
                    conn = self._get_connection()
                    try:
                        c_chk = conn.execute(
                            "SELECT 1 FROM downloaded_tracks WHERE collection_type = 'album' AND (LOWER(collection_name) = LOWER(?) OR LOWER(album) = LOWER(?)) LIMIT 1",
                            (folder_name, folder_name)
                        )
                        if c_chk.fetchone():
                            is_album = True
                    except Exception:
                        pass
                    finally:
                        conn.close()

                # If folder matches audio file's album metadata tag, identify as album
                if not is_album and album and folder_name.lower() == album.lower() and folder_name.lower() not in ("singles", "downloads"):
                    is_album = True

                if is_album:
                    c_type = "album"
                elif folder_name in ("Singles", "downloads"):
                    c_type = "track"
                    track_num = 0
                else:
                    c_type = "playlist"
                    track_num = 0

                # Deterministic synthetic ID derived from path hash
                path_hash = hashlib.sha256(full_path.lower().encode("utf-8")).hexdigest()[:16]
                synth_id = f"local_{path_hash}"
                fake_track = TrackMetadata(
                    id=synth_id,
                    title=title,
                    artists=[artist],
                    album=album,
                    release_date="",
                    duration_ms=0,
                    track_number=track_num,
                    disc_number=disc_num,
                    isrc=isrc,
                    collection_name=folder_name,
                    collection_type=c_type
                )

                if self.add_track(fake_track, full_path, quality, "Local File"):
                    indexed_count += 1

        if indexed_count > 0:
            logger.info(f"Scanned {root_dir} and indexed {indexed_count} existing tracks into Archive.")
        return indexed_count
