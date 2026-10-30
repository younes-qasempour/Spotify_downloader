import collections
import hashlib
import json
import logging
import mimetypes
import os
import re
import subprocess
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import requests

from core.archive import ArchiveManager, resolve_collection_cover
from core.config import config
from core.lyrics import LyricsData, LyricsEngine
from core.paths import get_cache_dir
from core.queue_manager import DownloadQueueManager, QueueItem
from core.spotify_client import SpotifyClient, TrackMetadata
from core.tagger import AudioTagger
from core.utils import (
    EQ_FREQUENCIES,
    EQ_PRESETS,
    apply_equalizer_to_file,
    ensure_ffmpeg,
    extract_embedded_cover,
    extract_embedded_lyrics,
    format_bytes,
    format_duration,
    inspect_audio_spectrum,
)

logger = logging.getLogger("gui.web_api")


def get_cached_transcode(file_path: str) -> Optional[str]:
    """Transcodes unsupported audio containers (like .m4a / AAC) to MP3 for Chromium playback."""
    ffmpeg = ensure_ffmpeg()
    if not ffmpeg or not os.path.isfile(ffmpeg):
        return None
    cache_dir = os.path.join(get_cache_dir(), "web_audio_cache")
    os.makedirs(cache_dir, exist_ok=True)
    try:
        st = os.stat(file_path)
        key = hashlib.md5(f"{file_path}_{st.st_mtime}_{st.st_size}".encode("utf-8")).hexdigest()
    except OSError:
        key = hashlib.md5(file_path.encode("utf-8")).hexdigest()

    out_mp3 = os.path.join(cache_dir, f"{key}.mp3")
    if os.path.isfile(out_mp3) and os.path.getsize(out_mp3) > 1000:
        return out_mp3

    cmd = [
        ffmpeg, "-y", "-i", file_path,
        "-vn", "-acodec", "libmp3lame", "-b:a", "320k",
        out_mp3
    ]
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=flags)
    if res.returncode == 0 and os.path.isfile(out_mp3):
        return out_mp3
    return None


class WebBackendState:
    """Shared state and thread-safe caches for the Flacify Web Desktop Studio API."""

    def __init__(
        self,
        queue_manager: DownloadQueueManager,
        archive_manager: ArchiveManager,
        folder_picker_cb: Optional[Callable[[str], str]] = None,
        on_track_play_cb: Optional[Callable[[str, str, str], None]] = None,
    ):
        self.qm = queue_manager
        self.archive = archive_manager
        self.folder_picker_cb = folder_picker_cb
        self.on_track_play_cb = on_track_play_cb

        self.cover_cache: collections.OrderedDict[str, Tuple[bytes, str]] = collections.OrderedDict()
        self.cover_lock = threading.Lock()
        self.MAX_COVER_CACHE = 400

        self.resolving_lock = threading.Lock()
        self.is_resolving = False
        self.resolving_message = ""
        self.last_resolve_result: Dict[str, Any] = {}

        # Cached library snapshot for ultra-fast UI rendering
        self.lib_lock = threading.Lock()
        self.lib_cache: Optional[Dict[str, Any]] = None
        self.lib_cache_time: float = 0.0

        # Spectrum batch scan state
        self.spectrum_scan_lock = threading.Lock()
        self.spectrum_scanning = False
        self.spectrum_progress = 0
        self.spectrum_total = 0
        self.spectrum_results: List[Dict[str, Any]] = []

    def invalidate_library_cache(self):
        with self.lib_lock:
            self.lib_cache = None
            self.lib_cache_time = 0.0

    def get_cover_bytes(self, key: str) -> Tuple[Optional[bytes], str]:
        if not key:
            return None, "image/jpeg"
        with self.cover_lock:
            if key in self.cover_cache:
                self.cover_cache.move_to_end(key)
                return self.cover_cache[key]

        data: Optional[bytes] = None
        mime = "image/jpeg"

        try:
            if os.path.isfile(key):
                ext = os.path.splitext(key)[1].lower()
                if ext in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
                    with open(key, "rb") as f:
                        data = f.read()
                    mime = "image/png" if ext == ".png" else ("image/webp" if ext == ".webp" else "image/jpeg")
                else:
                    data = extract_embedded_cover(key)
                    if not data:
                        folder = os.path.dirname(key)
                        coll_cov = resolve_collection_cover(folder)
                        if coll_cov and os.path.isfile(coll_cov):
                            with open(coll_cov, "rb") as f:
                                data = f.read()
                        else:
                            for cand in ("cover.jpg", "cover.png", "folder.jpg", "artwork.jpg"):
                                cp = os.path.join(folder, cand)
                                if os.path.isfile(cp):
                                    with open(cp, "rb") as f:
                                        data = f.read()
                                    break
            elif os.path.isdir(key):
                coll_cov = resolve_collection_cover(key)
                if coll_cov and os.path.isfile(coll_cov):
                    with open(coll_cov, "rb") as f:
                        data = f.read()
                else:
                    for cand in ("cover.jpg", "cover.png", "folder.jpg", "artwork.jpg"):
                        cp = os.path.join(key, cand)
                        if os.path.isfile(cp):
                            with open(cp, "rb") as f:
                                data = f.read()
                            break
                    if not data:
                        # Extract cover from first audio file in directory
                        for fn in os.listdir(key):
                            if fn.lower().endswith((".mp3", ".flac", ".m4a", ".opus", ".ogg")):
                                fp = os.path.join(key, fn)
                                data = extract_embedded_cover(fp)
                                if data:
                                    break
            elif key.startswith("http://") or key.startswith("https://"):
                resp = requests.get(key, timeout=8)
                if resp.status_code == 200:
                    data = resp.content
                    ct = resp.headers.get("Content-Type", "")
                    if "png" in ct:
                        mime = "image/png"
        except Exception as e:
            logger.debug(f"Cover fetch error for {key}: {e}")

        if data:
            if data[:8] == b"\x89PNG\r\n\x1a\n":
                mime = "image/png"
            with self.cover_lock:
                self.cover_cache[key] = (data, mime)
                self.cover_cache.move_to_end(key)
                while len(self.cover_cache) > self.MAX_COVER_CACHE:
                    self.cover_cache.popitem(last=False)
            return data, mime
        return None, "image/jpeg"

    def build_library_snapshot(self, force_refresh: bool = False) -> Dict[str, Any]:
        with self.lib_lock:
            if not force_refresh and self.lib_cache is not None and (time.time() - self.lib_cache_time) < 12.0:
                return self.lib_cache

        base_dir = config.get("download.output_dir", "")
        archive_records = self.archive.get_all_tracks()

        # Fetch true playlist memberships from saved_playlists and saved_playlist_tracks
        saved_pls = self.archive.get_saved_playlists()
        track_collections_map: Dict[str, Set[str]] = collections.defaultdict(set)
        try:
            with self.archive.connection() as conn:
                cur = conn.execute("""
                    SELECT s.spotify_id, p.name 
                    FROM saved_playlist_tracks s
                    JOIN saved_playlists p ON s.playlist_id = p.id
                    WHERE s.spotify_id IS NOT NULL AND s.spotify_id != ''
                """)
                for sid, pname in cur.fetchall():
                    if pname:
                        track_collections_map[sid].add(pname.strip())
        except Exception as e_mem:
            logger.debug(f"Could not load playlist track memberships: {e_mem}")

        # Index archive records by normalized file path
        arch_by_path: Dict[str, Dict[str, Any]] = {}
        for rec in archive_records:
            fp = rec.get("file_path") or ""
            if fp:
                arch_by_path[os.path.normcase(os.path.normpath(fp))] = rec

        audio_exts = {".mp3", ".flac", ".m4a", ".opus", ".ogg", ".wav"}
        discovered_files: Dict[str, Dict[str, Any]] = {}

        # 1. Include existing archive records whose files exist on disk
        for norm_p, rec in arch_by_path.items():
            fp = rec.get("file_path", "")
            if fp and os.path.isfile(fp):
                discovered_files[norm_p] = rec

        # 2. Scan download directory for any audio files
        if base_dir and os.path.isdir(base_dir):
            norm_base = os.path.normpath(base_dir)
            for root, dirs, files in os.walk(norm_base):
                # Skip internal playlists m3u8 folder
                if os.path.basename(root).lower() in ("playlists", ".git", "__pycache__"):
                    continue
                for fn in files:
                    ext = os.path.splitext(fn)[1].lower()
                    if ext not in audio_exts:
                        continue
                    fp = os.path.join(root, fn)
                    norm_p = os.path.normcase(os.path.normpath(fp))
                    if norm_p not in discovered_files:
                        rel_dir = os.path.relpath(root, norm_base)
                        coll_name = "" if rel_dir in (".", "") else rel_dir.split(os.sep)[0]
                        stem = os.path.splitext(fn)[0]
                        if " - " in stem:
                            parts = stem.split(" - ", 1)
                            artist_guess, title_guess = parts[0].strip(), parts[1].strip()
                        else:
                            artist_guess, title_guess = "Unknown Artist", stem.strip()
                        discovered_files[norm_p] = {
                            "spotify_id": f"local_{ abs(hash(norm_p)) }",
                            "title": title_guess,
                            "artist": artist_guess,
                            "album": coll_name or "Singles",
                            "duration_ms": 0,
                            "file_path": fp,
                            "quality_badge": "FLAC" if ext == ".flac" else ("YTM Opus" if ext == ".opus" else "320k MP3"),
                            "source_type": "Local Disk",
                            "collection_name": coll_name,
                            "collection_type": "playlist" if coll_name else "single",
                            "genre": "",
                        }

        tracks_out: List[Dict[str, Any]] = []
        playlists_map: Dict[str, Dict[str, Any]] = {}
        albums_map: Dict[str, Dict[str, Any]] = {}
        genres_counter = collections.Counter()
        total_bytes = 0

        # Seed playlists_map with all saved playlists so track counts and covers are 100% accurate
        for pl in saved_pls:
            p_name = pl["name"].strip()
            cov_key = resolve_collection_cover(p_name) or pl.get("local_cover") or pl.get("cover_url") or ""
            playlists_map[p_name] = {
                "name": p_name,
                "type": "playlist",
                "artist": "Spotify Playlist",
                "folder_path": "",
                "cover_key": cov_key,
                "track_count": 0,
                "total_bytes": 0,
                "genres": collections.Counter(),
                "latest_mtime": 0.0,
            }

        norm_base = os.path.normcase(os.path.normpath(base_dir)) if base_dir else ""

        for norm_p, rec in discovered_files.items():
            fp = rec.get("file_path", "")
            try:
                st = os.stat(fp)
                fsize = st.st_size
                mtime = st.st_mtime
            except OSError:
                continue

            total_bytes += fsize
            folder = os.path.dirname(fp)
            norm_folder = os.path.normcase(os.path.normpath(folder))

            coll_name = (rec.get("collection_name") or "").strip()
            coll_type = (rec.get("collection_type") or "playlist").strip().lower()
            if not coll_name and norm_base and norm_folder != norm_base and norm_folder.startswith(norm_base):
                rel = os.path.relpath(folder, base_dir)
                if rel and rel != ".":
                    coll_name = rel.split(os.sep)[0]

            sid = rec.get("spotify_id") or ""
            coll_set = set(track_collections_map.get(sid, set()))
            if coll_name and coll_name.lower() not in ("singles", "downloads", "music", "."):
                coll_set.add(coll_name)

            genre_raw = (rec.get("genre") or "").strip()
            primary_genre = ""
            if genre_raw:
                for g in re.split(r"[;,/|]", genre_raw):
                    g_clean = g.strip().title()
                    if g_clean and len(g_clean) > 1 and g_clean.lower() not in ("unknown", "other", "music", "audio"):
                        genres_counter[g_clean] += 1
                        if not primary_genre:
                            primary_genre = g_clean

            dur_ms = int(rec.get("duration_ms") or 0)
            qual = (rec.get("quality_badge") or rec.get("quality") or "").strip()
            src = (rec.get("source_type") or rec.get("source") or "").strip()
            if qual:
                badge = qual
            elif src.lower() == "melobot":
                badge = "MeloBot 320k"
            else:
                ext = os.path.splitext(fp)[1].lower()
                badge = "FLAC" if ext == ".flac" else ("YTM Opus" if ext == ".opus" else "320k MP3")

            title = rec.get("title") or os.path.splitext(os.path.basename(fp))[0]
            artist = rec.get("artist") or "Unknown Artist"
            album = rec.get("album") or coll_name or "Singles"

            track_obj = {
                "id": sid or norm_p,
                "title": title,
                "artist": artist,
                "album": album,
                "genre": primary_genre,
                "genres_all": genre_raw,
                "duration_ms": dur_ms,
                "duration_str": format_duration(dur_ms) if dur_ms > 0 else "--:--",
                "file_path": fp,
                "cover_key": fp,
                "quality_badge": badge,
                "source": src,
                "collection_name": coll_name or (sorted(list(coll_set))[0] if coll_set else "Singles"),
                "collections": sorted(list(coll_set)),
                "collection_type": coll_type,
                "folder_path": folder,
                "size_bytes": fsize,
                "mtime": mtime,
            }
            tracks_out.append(track_obj)

            # Group into Playlists or Albums
            if coll_type == "album" and album and album.lower() not in ("singles", "downloads", "."):
                if album not in albums_map:
                    cov_cand = resolve_collection_cover(album, fp) or fp
                    albums_map[album] = {
                        "name": album,
                        "type": "album",
                        "artist": artist,
                        "folder_path": folder,
                        "cover_key": cov_cand,
                        "track_count": 0,
                        "total_bytes": 0,
                        "genres": collections.Counter(),
                        "latest_mtime": 0.0,
                    }
                a_entry = albums_map[album]
                a_entry["track_count"] += 1
                a_entry["total_bytes"] += fsize
                if mtime > a_entry["latest_mtime"]:
                    a_entry["latest_mtime"] = mtime
                if primary_genre:
                    a_entry["genres"][primary_genre] += 1

            # Group into all matching playlists
            for c_name in coll_set:
                if c_name not in playlists_map:
                    cov_cand = resolve_collection_cover(c_name, fp) or fp
                    playlists_map[c_name] = {
                        "name": c_name,
                        "type": "playlist",
                        "artist": "Playlist",
                        "folder_path": folder,
                        "cover_key": cov_cand,
                        "track_count": 0,
                        "total_bytes": 0,
                        "genres": collections.Counter(),
                        "latest_mtime": 0.0,
                    }
                p_entry = playlists_map[c_name]
                p_entry["track_count"] += 1
                p_entry["total_bytes"] += fsize
                if not p_entry.get("folder_path"):
                    p_entry["folder_path"] = folder
                if mtime > p_entry["latest_mtime"]:
                    p_entry["latest_mtime"] = mtime
                if primary_genre:
                    p_entry["genres"][primary_genre] += 1

        # Format playlists and albums lists
        playlists_out = []
        for name, info in sorted(playlists_map.items(), key=lambda kv: kv[0].lower()):
            if info["track_count"] == 0:
                continue
            top_genres = [g for g, _ in info["genres"].most_common(2)]
            playlists_out.append({
                "name": info["name"],
                "type": "playlist",
                "subtitle": f"{info['track_count']} songs • {format_bytes(info['total_bytes'])}",
                "genre_summary": ", ".join(top_genres) if top_genres else "Mixed",
                "folder_path": info["folder_path"],
                "cover_key": info["cover_key"],
                "track_count": info["track_count"],
                "total_bytes": info["total_bytes"],
                "size_str": format_bytes(info["total_bytes"]),
            })

        albums_out = []
        for name, info in sorted(albums_map.items(), key=lambda kv: kv[0].lower()):
            if info["track_count"] == 0:
                continue
            top_genres = [g for g, _ in info["genres"].most_common(2)]
            albums_out.append({
                "name": info["name"],
                "type": "album",
                "artist": info["artist"],
                "subtitle": f"{info['artist']} • {info['track_count']} songs",
                "genre_summary": ", ".join(top_genres) if top_genres else "Album",
                "folder_path": info["folder_path"],
                "cover_key": info["cover_key"],
                "track_count": info["track_count"],
                "total_bytes": info["total_bytes"],
                "size_str": format_bytes(info["total_bytes"]),
            })

        # Sort tracks by title by default
        tracks_out.sort(key=lambda t: (t["title"] or "").lower())

        # Select top genres (at most 20) by frequency across user's library, sorted alphabetically for UI
        top_genres = [g for g, _ in genres_counter.most_common(20)]
        top_genres_sorted = sorted(top_genres, key=lambda s: s.lower())

        snapshot = {
            "tracks": tracks_out,
            "playlists": playlists_out,
            "albums": albums_out,
            "genres": top_genres_sorted,
            "stats": {
                "total_tracks": len(tracks_out),
                "total_bytes": total_bytes,
                "total_size_str": format_bytes(total_bytes),
                "playlists_count": len(playlists_out),
                "albums_count": len(albums_out),
            },
        }
        with self.lib_lock:
            self.lib_cache = snapshot
            self.lib_cache_time = time.time()
        return snapshot


class FlacifyWebRequestHandler(BaseHTTPRequestHandler):
    """HTTP Request Handler with Byte-Range Audio Streaming and JSON REST API."""

    state: WebBackendState = None  # Bound at server creation
    web_root: str = ""

    def log_message(self, format: str, *args: Any):
        # Silence noisy per-request HTTP logs in console
        pass

    def _send_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Range")
        self.send_header("Access-Control-Expose-Headers", "Content-Range, Content-Length, Accept-Ranges")

    def _send_json(self, payload: Any, status: int = 200):
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self._send_cors_headers()
        self.end_headers()
        self.wfile.write(raw)

    def _read_json_body(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return {}

    def do_OPTIONS(self):
        self.send_response(204)
        self._send_cors_headers()
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        qs = urllib.parse.parse_qs(parsed.query)

        try:
            if path == "/api/state":
                return self._handle_get_state()
            elif path == "/api/library":
                force = qs.get("refresh", ["0"])[0] == "1"
                return self._send_json(self.state.build_library_snapshot(force_refresh=force))
            elif path == "/api/saved_playlists":
                return self._handle_get_saved_playlists()
            elif path == "/api/saved_playlists/tracks":
                pid = qs.get("id", [""])[0]
                return self._handle_get_saved_playlist_tracks(pid)
            elif path == "/api/lyrics":
                fp = qs.get("path", [""])[0]
                title = qs.get("title", [""])[0]
                artist = qs.get("artist", [""])[0]
                return self._handle_get_lyrics(fp, title, artist)
            elif path == "/api/settings":
                return self._handle_get_settings()
            elif path == "/api/eq":
                return self._handle_get_eq()
            elif path == "/api/tools/spectrum/status":
                return self._handle_get_spectrum_status()
            elif path == "/api/cover":
                key = qs.get("key", [""])[0]
                return self._handle_get_cover(key)
            elif path == "/api/audio":
                fp = qs.get("path", [""])[0]
                trans = qs.get("transcode", ["0"])[0] == "1"
                return self._handle_stream_audio(fp, transcode=trans)
            else:
                return self._handle_static_file(path)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        except Exception as e:
            logger.error(f"GET {path} error: {e}", exc_info=True)
            try:
                self._send_json({"ok": False, "error": str(e)}, status=500)
            except Exception:
                pass

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        body = self._read_json_body()

        try:
            if path == "/api/queue/add":
                return self._handle_queue_add(body)
            elif path == "/api/queue/action":
                return self._handle_queue_action(body)
            elif path == "/api/library/rescan":
                return self._handle_library_rescan()
            elif path == "/api/library/delete":
                return self._handle_library_delete(body)
            elif path == "/api/library/rename_collection":
                return self._handle_rename_collection(body)
            elif path == "/api/library/export_m3u8":
                return self._handle_export_m3u8(body)
            elif path == "/api/saved_playlists/action":
                return self._handle_saved_playlists_action(body)
            elif path == "/api/lyrics/fetch":
                return self._handle_lyrics_fetch(body)
            elif path == "/api/lyrics/translate":
                return self._handle_lyrics_translate(body)
            elif path == "/api/lyrics/save":
                return self._handle_lyrics_save(body)
            elif path == "/api/eq/save":
                return self._handle_eq_save(body)
            elif path == "/api/eq/apply_file":
                return self._handle_eq_apply_file(body)
            elif path == "/api/tools/spectrum/inspect":
                return self._handle_spectrum_inspect(body)
            elif path == "/api/tools/spectrum/batch":
                return self._handle_spectrum_batch(body)
            elif path == "/api/tools/duplicates/scan":
                return self._handle_duplicates_scan(body)
            elif path == "/api/tools/duplicates/merge":
                return self._handle_duplicates_merge(body)
            elif path == "/api/settings":
                return self._handle_save_settings(body)
            elif path == "/api/shell/open":
                return self._handle_shell_open(body)
            elif path == "/api/dialog/folder":
                return self._handle_folder_dialog(body)
            elif path == "/api/player/notify":
                return self._handle_player_notify(body)
            else:
                return self._send_json({"ok": False, "error": f"Unknown endpoint {path}"}, status=404)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        except Exception as e:
            logger.error(f"POST {path} error: {e}", exc_info=True)
            try:
                self._send_json({"ok": False, "error": str(e)}, status=500)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Handlers: State & Queue
    # ------------------------------------------------------------------
    def _handle_get_state(self):
        qm = self.state.qm
        items_raw = qm.get_items() if hasattr(qm, "get_items") else qm.get_all_items()
        queue_out = []
        counts = {"all": len(items_raw), "downloading": 0, "queued": 0, "completed": 0, "failed": 0}
        total_speed_bps = 0.0

        for it in items_raw:
            st = it.status
            if st in ("Downloading", "Resolving"):
                counts["downloading"] += 1
            elif st in ("Queued", "Paused", "Stopped"):
                counts["queued"] += 1
            elif st == "Completed":
                counts["completed"] += 1
            elif st == "Failed":
                counts["failed"] += 1

            # Parse speed string if downloading
            if st == "Downloading" and it.speed_str:
                m = re.search(r"([\d.]+)\s*(KB|MB|GB)/s", it.speed_str, re.IGNORECASE)
                if m:
                    val = float(m.group(1))
                    unit = m.group(2).upper()
                    mult = 1024 if unit == "KB" else (1024 * 1024 if unit == "MB" else 1024 ** 3)
                    total_speed_bps += val * mult

            queue_out.append({
                "item_id": getattr(it, "item_id", None) or it.track.id,
                "title": it.track.title,
                "artist": it.track.artist_str,
                "album": it.track.album,
                "duration_ms": it.track.duration_ms,
                "duration_str": format_duration(it.track.duration_ms),
                "cover_key": it.output_path if (it.output_path and os.path.isfile(it.output_path)) else (it.track.cover_url or ""),
                "status": it.status,
                "progress": round(float(it.progress_percent or 0.0), 1),
                "speed_str": it.speed_str or "",
                "eta_str": it.eta_str or "",
                "quality_badge": it.quality_badge or "",
                "output_path": it.output_path or "",
                "error_message": it.error_message or "",
                "collection_name": getattr(it.track, "collection_name", "") or "",
            })

        with self.state.resolving_lock:
            is_res = self.state.is_resolving
            res_msg = self.state.resolving_message
            last_res = dict(self.state.last_resolve_result)

        watched = self.state.archive.get_watched_playlists()
        is_paused = qm.is_paused() if callable(getattr(qm, "is_paused", None)) else False
        self._send_json({
            "ok": True,
            "queue": queue_out,
            "counts": counts,
            "is_paused": bool(is_paused),
            "total_speed_str": f"{format_bytes(int(total_speed_bps))}/s" if total_speed_bps > 0 else "0 B/s",
            "is_resolving": is_res,
            "resolving_message": res_msg,
            "last_resolve": last_res,
            "watched_playlists_count": len(watched),
        })

    def _handle_queue_add(self, body: Dict[str, Any]):
        url = (body.get("url") or "").strip()
        save_to_playlists = bool(body.get("save_playlist", False))
        if not url:
            return self._send_json({"ok": False, "error": "Please enter a Spotify URL or search query."}, status=400)

        with self.state.resolving_lock:
            if self.state.is_resolving:
                return self._send_json({"ok": False, "error": "Already resolving a URL. Please wait..."})
            self.state.is_resolving = True
            self.state.resolving_message = f"Resolving Spotify metadata for {url[:48]}..."
            self.state.last_resolve_result = {}

        def worker():
            try:
                sp = SpotifyClient(
                    client_id=config.get("spotify.client_id", ""),
                    client_secret=config.get("spotify.client_secret", ""),
                )

                def prog_cb(msg: str):
                    with self.state.resolving_lock:
                        self.state.resolving_message = msg

                tracks = sp.resolve(url, progress_callback=prog_cb)
                if not tracks:
                    with self.state.resolving_lock:
                        self.state.is_resolving = False
                        self.state.resolving_message = ""
                        self.state.last_resolve_result = {"ok": False, "message": "No tracks found for that URL."}
                    return

                if save_to_playlists:
                    coll_name = getattr(tracks[0], "collection_name", "") or "Saved Playlist"
                    coll_cover = getattr(tracks[0], "collection_cover_url", "") or tracks[0].cover_url or ""
                    self.state.archive.save_playlist(coll_name, url, coll_cover, tracks)
                    with self.state.resolving_lock:
                        self.state.is_resolving = False
                        self.state.resolving_message = ""
                        self.state.last_resolve_result = {
                            "ok": True,
                            "message": f"Saved '{coll_name}' ({len(tracks)} tracks) to Playlists.",
                            "count": len(tracks),
                        }
                    return

                self.state.qm.enqueue(tracks)
                self.state.qm.start_all()
                added = len(tracks)
                with self.state.resolving_lock:
                    self.state.is_resolving = False
                    self.state.resolving_message = ""
                    self.state.last_resolve_result = {
                        "ok": True,
                        "message": f"Queued {added} track(s) for download",
                        "count": added,
                    }
                self.state.invalidate_library_cache()
            except Exception as e:
                logger.error(f"URL resolution failed: {e}")
                with self.state.resolving_lock:
                    self.state.is_resolving = False
                    self.state.resolving_message = ""
                    self.state.last_resolve_result = {"ok": False, "message": f"Resolution failed: {e}"}

        threading.Thread(target=worker, daemon=True, name="WebURLResolver").start()
        self._send_json({"ok": True, "message": "Started resolving URL..."})

    def _handle_queue_action(self, body: Dict[str, Any]):
        action = (body.get("action") or "").strip()
        item_id = (body.get("item_id") or "").strip()
        qm = self.state.qm

        if action == "pause":
            qm.pause()
        elif action == "resume":
            qm.resume()
        elif action == "retry_failed":
            qm.retry_failed()
        elif action == "clear_completed":
            qm.clear_completed()
        elif action == "stop_all":
            qm.stop()
        elif action == "remove" and item_id:
            qm.remove_track(item_id)
        elif action == "retry_item" and item_id:
            qm.retry_track(item_id)
        else:
            return self._send_json({"ok": False, "error": f"Unknown action '{action}'"}, status=400)

        self.state.invalidate_library_cache()
        self._send_json({"ok": True})

    # ------------------------------------------------------------------
    # Handlers: Library & Collections
    # ------------------------------------------------------------------
    def _handle_library_rescan(self):
        base_dir = config.get("download.output_dir", "")
        if base_dir and os.path.isdir(base_dir):
            self.state.archive.scan_and_index_directory(base_dir)
        self.state.invalidate_library_cache()
        snap = self.state.build_library_snapshot(force_refresh=True)
        self._send_json({"ok": True, "stats": snap["stats"]})

    def _handle_library_delete(self, body: Dict[str, Any]):
        fp = (body.get("file_path") or "").strip()
        delete_disk = bool(body.get("delete_from_disk", True))
        if not fp:
            return self._send_json({"ok": False, "error": "Missing file_path"}, status=400)

        tr = self.state.archive.get_track_by_path(fp)
        if tr and tr.get("spotify_id"):
            self.state.archive.remove_downloaded_track(tr["spotify_id"])

        if delete_disk and os.path.isfile(fp):
            try:
                os.remove(fp)
                lrc = os.path.splitext(fp)[0] + ".lrc"
                if os.path.isfile(lrc):
                    os.remove(lrc)
            except Exception as e:
                logger.warning(f"Could not delete file {fp}: {e}")

        self.state.invalidate_library_cache()
        self._send_json({"ok": True})

    def _handle_rename_collection(self, body: Dict[str, Any]):
        old_name = (body.get("old_name") or "").strip()
        new_name = (body.get("new_name") or "").strip()
        coll_type = (body.get("collection_type") or "playlist").strip()
        if not old_name or not new_name:
            return self._send_json({"ok": False, "error": "Both old_name and new_name are required"}, status=400)

        ok = self.state.archive.rename_collection(old_name, new_name, coll_type)
        self.state.invalidate_library_cache()
        self._send_json({"ok": ok})

    def _handle_export_m3u8(self, body: Dict[str, Any]):
        coll_name = (body.get("collection_name") or "Library").strip()
        folder_path = (body.get("folder_path") or config.get("download.output_dir", "")).strip()
        snap = self.state.build_library_snapshot()
        tracks = [
            t for t in snap["tracks"]
            if not coll_name or coll_name == "All Songs" or t["collection_name"].lower() == coll_name.lower() or coll_name in t.get("collections", [])
        ]
        if not tracks:
            return self._send_json({"ok": False, "error": "No tracks to export"}, status=400)

        playlists_dir = os.path.join(config.get("download.output_dir", folder_path), "Playlists")
        os.makedirs(playlists_dir, exist_ok=True)
        safe_name = re.sub(r'[<>:"/\\|?*]', "_", coll_name)
        m3u_path = os.path.join(playlists_dir, f"{safe_name}.m3u8")

        lines = ["#EXTM3U", f"#PLAYLIST:{coll_name}"]
        for t in tracks:
            dur_s = max(1, int((t.get("duration_ms") or 0) // 1000))
            lines.append(f"#EXTINF:{dur_s},{t['artist']} - {t['title']}")
            lines.append(t["file_path"])

        with open(m3u_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

        self._send_json({"ok": True, "m3u_path": m3u_path, "count": len(tracks)})

    # ------------------------------------------------------------------
    # Handlers: Saved & Watched Playlists
    # ------------------------------------------------------------------
    def _handle_get_saved_playlists(self):
        pls = self.state.archive.get_saved_playlists()
        for p in pls:
            if not p.get("local_cover"):
                p["local_cover"] = resolve_collection_cover(p["name"]) or p.get("cover_url") or ""
        self._send_json({"ok": True, "playlists": pls})

    def _handle_get_saved_playlist_tracks(self, playlist_id: str):
        if not playlist_id:
            return self._send_json({"ok": False, "error": "Missing playlist id"}, status=400)
        pl = self.state.archive.get_saved_playlist(playlist_id)
        if pl and not pl.get("local_cover"):
            pl["local_cover"] = resolve_collection_cover(pl["name"]) or pl.get("cover_url") or ""
        tracks = self.state.archive.get_saved_playlist_tracks(playlist_id)
        out_tracks = []
        for idx, tr in enumerate(tracks, 1):
            fp = tr.get("file_path") or tr.get("local_path") or ""
            is_dl = (tr.get("status") == "downloaded") and bool(fp) and os.path.isfile(fp)
            if not is_dl and fp and os.path.isfile(fp):
                is_dl = True
            dur_ms = int(tr.get("duration_ms") or 0)
            qb = tr.get("quality_badge") or tr.get("quality") or ""
            if not qb and is_dl and fp:
                qb, _ = ArchiveManager.infer_badge_from_file(fp)
            cov = resolve_collection_cover(tr.get("album") or "") or tr.get("cover_url") or ""
            out_tracks.append({
                "index": idx,
                "spotify_id": tr.get("spotify_id", ""),
                "title": tr.get("title", ""),
                "artist": tr.get("artist", ""),
                "album": tr.get("album", ""),
                "duration_ms": dur_ms,
                "duration_str": format_duration(dur_ms) if dur_ms > 0 else "--:--",
                "cover_url": tr.get("cover_url", ""),
                "cover_key": fp if (fp and os.path.isfile(fp)) else (tr.get("cover_url") or cov),
                "genre": tr.get("genre", ""),
                "is_downloaded": is_dl,
                "status": "downloaded" if is_dl else (tr.get("status") or "pending"),
                "file_path": fp if is_dl else "",
                "local_path": fp if is_dl else "",
                "quality_badge": qb or ("Downloaded" if is_dl else "Missing"),
                "quality": qb,
            })
        self._send_json({"ok": True, "playlist": pl, "tracks": out_tracks})

    def _handle_saved_playlists_action(self, body: Dict[str, Any]):
        action = (body.get("action") or "").strip()
        pid = (body.get("playlist_id") or "").strip()

        if action == "toggle_watch" and pid:
            enabled = bool(body.get("auto_sync", False))
            self.state.archive.set_playlist_auto_sync(pid, enabled)
            return self._send_json({"ok": True, "auto_sync": enabled})

        elif action == "delete" and pid:
            self.state.archive.delete_saved_playlist(pid)
            self.state.invalidate_library_cache()
            return self._send_json({"ok": True})

        elif action == "rename" and pid:
            new_name = (body.get("name") or "").strip()
            if new_name:
                self.state.archive.update_saved_playlist(pid, name=new_name)
            self.state.invalidate_library_cache()
            return self._send_json({"ok": True})

        elif action in ("download_missing", "download_all", "download_selected") and pid:
            pl = self.state.archive.get_saved_playlist(pid)
            rows = self.state.archive.get_saved_playlist_tracks(pid)
            selected_ids = set(body.get("spotify_ids") or [])
            to_queue: List[TrackMetadata] = []

            for r in rows:
                fp = r.get("file_path") or r.get("local_path") or ""
                is_dl = (r.get("status") == "downloaded") and bool(fp) and os.path.isfile(fp)
                if not is_dl and fp and os.path.isfile(fp):
                    is_dl = True
                if action == "download_missing" and is_dl:
                    continue
                if action == "download_selected" and r.get("spotify_id") not in selected_ids:
                    continue
                meta_json = r.get("metadata_json")
                if meta_json:
                    try:
                        d = json.loads(meta_json)
                        tm = TrackMetadata(**{k: v for k, v in d.items() if k in TrackMetadata.__dataclass_fields__})
                        if pl and pl.get("name"):
                            tm.collection_name = pl["name"]
                            tm.collection_type = "playlist"
                        to_queue.append(tm)
                        continue
                    except Exception:
                        pass
                tm = TrackMetadata(
                    id=r.get("spotify_id", ""),
                    title=r.get("title", "Unknown"),
                    artists=[a.strip() for a in (r.get("artist") or "Unknown").split(",") if a.strip()],
                    album=r.get("album", ""),
                    duration_ms=int(r.get("duration_ms") or 0),
                    cover_url=r.get("cover_url", ""),
                    collection_name=pl["name"] if pl else "Saved Playlist",
                    collection_type="playlist",
                )
                to_queue.append(tm)

            if to_queue:
                self.state.qm.enqueue(to_queue)
                self.state.qm.start_all()
            return self._send_json({"ok": True, "queued": len(to_queue)})

        elif action == "sync" and pid:
            pl = self.state.archive.get_saved_playlist(pid)
            source_url = (pl.get("spotify_url") if pl else "") or (pl.get("source_url") if pl else "")
            if not pl or not source_url:
                return self._send_json({"ok": False, "error": "Playlist has no Spotify source URL"}, status=400)

            auto_queue = bool(body.get("queue_new", True))

            def sync_worker():
                try:
                    with self.state.resolving_lock:
                        self.state.is_resolving = True
                        self.state.resolving_message = f"Syncing '{pl['name']}' with Spotify..."
                    sp = SpotifyClient(
                        client_id=config.get("spotify.client_id", ""),
                        client_secret=config.get("spotify.client_secret", ""),
                    )
                    fresh = sp.resolve(source_url)
                    if fresh:
                        res = self.state.archive.sync_saved_playlist(pid, fresh)
                        new_tracks = res.get("delta_tracks", [])
                        if auto_queue and new_tracks:
                            for t in new_tracks:
                                t.collection_name = pl["name"]
                                t.collection_type = "playlist"
                            self.state.qm.enqueue(new_tracks)
                            self.state.qm.start_all()
                        with self.state.resolving_lock:
                            self.state.is_resolving = False
                            self.state.resolving_message = ""
                            self.state.last_resolve_result = {
                                "ok": True,
                                "message": f"Synced '{pl['name']}': +{res.get('added', 0)} new tracks",
                            }
                        self.state.invalidate_library_cache()
                    else:
                        with self.state.resolving_lock:
                            self.state.is_resolving = False
                            self.state.resolving_message = ""
                except Exception as e:
                    with self.state.resolving_lock:
                        self.state.is_resolving = False
                        self.state.resolving_message = ""
                        self.state.last_resolve_result = {"ok": False, "message": f"Sync error: {e}"}

            threading.Thread(target=sync_worker, daemon=True, name="WebPlaylistSync").start()
            return self._send_json({"ok": True, "message": f"Syncing '{pl['name']}' in background..."})

        return self._send_json({"ok": False, "error": f"Unknown playlist action '{action}'"}, status=400)

        return self._send_json({"ok": False, "error": f"Unknown playlist action '{action}'"}, status=400)

    # ------------------------------------------------------------------
    # Handlers: Synchronized Karaoke Lyrics & Bilingual Translation
    # ------------------------------------------------------------------
    def _parse_lrc_text(self, lrc_text: str, duration_ms: int = 180000) -> Tuple[bool, List[Dict[str, Any]]]:
        pattern = re.compile(r"\[(\d{1,2}):(\d{2})(?:\.(\d{2,3}))?\](.*)")
        parsed_entries: List[Tuple[int, str]] = []
        plain_lines: List[str] = []

        for line in (lrc_text or "").splitlines():
            line = line.strip()
            if not line:
                continue
            m = pattern.match(line)
            if m:
                mins = int(m.group(1))
                secs = int(m.group(2))
                ms_str = m.group(3) or "0"
                ms = int(ms_str.ljust(3, "0")[:3])
                total_ms = (mins * 60 + secs) * 1000 + ms
                txt = m.group(4).strip()
                if txt:
                    parsed_entries.append((total_ms, txt))
            elif not line.startswith("["):
                plain_lines.append(line)

        if parsed_entries:
            parsed_entries.sort(key=lambda x: x[0])
            return True, [{"time_ms": ts, "text": txt} for ts, txt in parsed_entries]
        elif plain_lines:
            step = max(2500, (duration_ms or 180000) // max(1, len(plain_lines) + 1))
            return False, [{"time_ms": i * step, "text": txt} for i, txt in enumerate(plain_lines)]
        return False, []

    def _handle_get_lyrics(self, file_path: str, title: str = "", artist: str = ""):
        lrc_text = ""
        if file_path and os.path.isfile(file_path):
            base, _ = os.path.splitext(file_path)
            candidates = [
                f"{base}.lrc",
                os.path.join(os.path.dirname(file_path), "lyrics", f"{os.path.basename(base)}.lrc"),
            ]
            for cand in candidates:
                if os.path.isfile(cand):
                    try:
                        with open(cand, "r", encoding="utf-8", errors="replace") as f:
                            lrc_text = f.read()
                        break
                    except Exception:
                        pass
            if not lrc_text:
                try:
                    lrc_text = extract_embedded_lyrics(file_path) or ""
                except Exception:
                    lrc_text = ""

        synced, lines = self._parse_lrc_text(lrc_text)
        self._send_json({
            "ok": True,
            "has_lyrics": len(lines) > 0,
            "synced": synced,
            "lines": lines,
            "raw_text": lrc_text,
            "preferred_trans_lang": config.get("ui.lyrics_translation_lang", "none"),
        })

    def _handle_lyrics_fetch(self, body: Dict[str, Any]):
        fp = (body.get("file_path") or "").strip()
        title = (body.get("title") or "").strip()
        artist = (body.get("artist") or "").strip()
        album = (body.get("album") or "").strip()
        duration_ms = int(body.get("duration_ms") or 180000)

        if not title and fp:
            title = os.path.splitext(os.path.basename(fp))[0]

        tm = TrackMetadata(
            id="lyrics_lookup",
            title=title or "Unknown",
            artists=[artist] if artist else ["Unknown"],
            album=album,
            duration_ms=duration_ms,
        )
        eng = LyricsEngine()
        ldata = eng.fetch_lyrics(tm)
        if not ldata or (not ldata.synced_lyrics and not ldata.plain_lyrics):
            return self._send_json({"ok": False, "error": "No lyrics found on LRCLIB for this track."})

        raw_lrc = ldata.synced_lyrics or ldata.plain_lyrics or ""
        if fp and os.path.isfile(fp):
            try:
                lrc_p = os.path.splitext(fp)[0] + ".lrc"
                with open(lrc_p, "w", encoding="utf-8") as f:
                    f.write(raw_lrc)
                AudioTagger()._embed_lyrics_only(fp, ldata)
            except Exception as e:
                logger.debug(f"Could not save fetched lyrics to {fp}: {e}")

        synced, lines = self._parse_lrc_text(raw_lrc, duration_ms=duration_ms)
        self._send_json({
            "ok": True,
            "has_lyrics": len(lines) > 0,
            "synced": synced,
            "lines": lines,
            "raw_text": raw_lrc,
        })

    def _handle_lyrics_translate(self, body: Dict[str, Any]):
        lines = body.get("lines") or []
        lang = (body.get("target_lang") or "en").strip().lower()
        config.set("ui.lyrics_translation_lang", lang)
        if lang not in ("en", "fa") or not lines:
            return self._send_json({"ok": True, "target_lang": "none", "translated": []})

        eng = LyricsEngine()
        translated = eng.translate_lyrics([str(x) for x in lines], target_lang=lang)
        self._send_json({
            "ok": True,
            "target_lang": lang,
            "translated": translated,
        })

    def _handle_lyrics_save(self, body: Dict[str, Any]):
        fp = (body.get("file_path") or "").strip()
        raw_text = body.get("raw_text") or ""
        if not fp or not raw_text:
            return self._send_json({"ok": False, "error": "Missing file_path or lyrics text"}, status=400)
        lrc_p = os.path.splitext(fp)[0] + ".lrc"
        with open(lrc_p, "w", encoding="utf-8") as f:
            f.write(raw_text)
        self._send_json({"ok": True, "lrc_path": lrc_p})

    # ------------------------------------------------------------------
    # Handlers: 10-Band Equalizer & Audio Studio Tools
    # ------------------------------------------------------------------
    def _handle_get_eq(self):
        self._send_json({
            "ok": True,
            "enabled": bool(config.get("ui.eq_enabled", False)),
            "preset": str(config.get("ui.eq_preset", "Flat (Default)")),
            "bands": list(config.get("ui.eq_bands", [0.0] * 10) or [0.0] * 10),
            "preamp": float(config.get("ui.eq_preamp", 0.0) or 0.0),
            "bass_boost": float(config.get("ui.eq_bass_boost", 0.0) or 0.0),
            "frequencies": EQ_FREQUENCIES,
            "presets": EQ_PRESETS,
        })

    def _handle_eq_save(self, body: Dict[str, Any]):
        if "enabled" in body:
            config.set("ui.eq_enabled", bool(body["enabled"]))
        if "preset" in body:
            config.set("ui.eq_preset", str(body["preset"]))
        if "bands" in body and isinstance(body["bands"], list) and len(body["bands"]) == 10:
            config.set("ui.eq_bands", [float(x) for x in body["bands"]])
        if "preamp" in body:
            config.set("ui.eq_preamp", float(body["preamp"]))
        if "bass_boost" in body:
            config.set("ui.eq_bass_boost", float(body["bass_boost"]))
        self._send_json({"ok": True})

    def _handle_eq_apply_file(self, body: Dict[str, Any]):
        fp = (body.get("file_path") or "").strip()
        if not fp or not os.path.isfile(fp):
            return self._send_json({"ok": False, "error": "Audio file not found on disk"}, status=400)
        bands = [float(x) for x in (body.get("bands") or config.get("ui.eq_bands", [0.0] * 10))]
        preamp = float(body.get("preamp", config.get("ui.eq_preamp", 0.0)))
        bass = float(body.get("bass_boost", config.get("ui.eq_bass_boost", 0.0)))
        ok = apply_equalizer_to_file(fp, bands, preamp_db=preamp, bass_boost_db=bass)
        self._send_json({"ok": ok, "message": "Equalizer curve permanently mastered into audio file." if ok else "Failed to apply EQ to file."})

    def _handle_spectrum_inspect(self, body: Dict[str, Any]):
        fp = (body.get("file_path") or "").strip()
        if not fp or not os.path.isfile(fp):
            return self._send_json({"ok": False, "error": "File does not exist"}, status=400)
        res = inspect_audio_spectrum(fp, generate_spectrogram=True)
        if not res:
            return self._send_json({"ok": False, "error": "Could not analyze audio spectrum"}, status=500)
        self._send_json({"ok": True, "result": res})

    def _handle_spectrum_batch(self, body: Dict[str, Any]):
        limit = int(body.get("limit") or 60)
        snap = self.state.build_library_snapshot()
        tracks = snap["tracks"][:limit]

        with self.state.spectrum_scan_lock:
            if self.state.spectrum_scanning:
                return self._send_json({"ok": True, "message": "Scan already running"})
            self.state.spectrum_scanning = True
            self.state.spectrum_progress = 0
            self.state.spectrum_total = len(tracks)
            self.state.spectrum_results = []

        def worker():
            try:
                for idx, t in enumerate(tracks, 1):
                    fp = t["file_path"]
                    res = inspect_audio_spectrum(fp, generate_spectrogram=False)
                    if res:
                        res["title"] = t["title"]
                        res["artist"] = t["artist"]
                        res["quality_badge"] = t["quality_badge"]
                        with self.state.spectrum_scan_lock:
                            self.state.spectrum_results.append(res)
                    with self.state.spectrum_scan_lock:
                        self.state.spectrum_progress = idx
            finally:
                with self.state.spectrum_scan_lock:
                    self.state.spectrum_scanning = False

        threading.Thread(target=worker, daemon=True, name="WebSpectrumScanner").start()
        self._send_json({"ok": True, "total": len(tracks)})

    def _handle_get_spectrum_status(self):
        with self.state.spectrum_scan_lock:
            self._send_json({
                "ok": True,
                "scanning": self.state.spectrum_scanning,
                "progress": self.state.spectrum_progress,
                "total": self.state.spectrum_total,
                "results": list(self.state.spectrum_results),
            })

    def _handle_duplicates_scan(self, body: Dict[str, Any]):
        use_fp = bool(body.get("use_acoustic_fingerprint", False))
        base_dir = config.get("download.output_dir", "")
        groups = self.state.archive.find_library_duplicates(root_dir=base_dir, use_acoustic_fingerprint=use_fp)
        total_reclaimable = sum(int(g.get("reclaimable_bytes") or 0) for g in groups)
        for g in groups:
            g["reclaimable_str"] = format_bytes(int(g.get("reclaimable_bytes") or 0))
            if "primary" in g and "size_bytes" in g["primary"]:
                g["primary"]["size_str"] = format_bytes(int(g["primary"]["size_bytes"]))
            for d in g.get("duplicates", []):
                if "size_bytes" in d:
                    d["size_str"] = format_bytes(int(d["size_bytes"]))
        self._send_json({
            "ok": True,
            "groups": groups,
            "total_groups": len(groups),
            "total_reclaimable_bytes": total_reclaimable,
            "total_reclaimable_str": format_bytes(total_reclaimable),
        })

    def _handle_duplicates_merge(self, body: Dict[str, Any]):
        mode = (body.get("mode") or "hardlink").strip()
        use_fp = bool(body.get("use_acoustic_fingerprint", False))
        base_dir = config.get("download.output_dir", "")
        groups = self.state.archive.find_library_duplicates(root_dir=base_dir, use_acoustic_fingerprint=use_fp)
        stats = self.state.archive.merge_library_duplicates(groups, mode=mode)
        stats["bytes_saved_str"] = format_bytes(int(stats.get("bytes_saved") or 0))
        self.state.invalidate_library_cache()
        self._send_json({"ok": True, "stats": stats})

    # ------------------------------------------------------------------
    # Handlers: Settings & OS Integration
    # ------------------------------------------------------------------
    def _handle_get_settings(self):
        self._send_json({
            "ok": True,
            "settings": {
                "output_dir": config.get("download.output_dir", ""),
                "save_in_subfolders": bool(config.get("download.save_in_subfolders", True)),
                "concurrency": int(config.get("download.concurrency", 5)),
                "preferred_source": config.get("download.preferred_source", "melobot"),
                "prefer_high_quality": bool(config.get("download.prefer_high_quality", True)),
                "normalize_audio": bool(config.get("download.normalize_audio", True)),
                "embed_lyrics": bool(config.get("download.embed_lyrics", True)),
                "auto_sync_enabled": bool(config.get("playlists.auto_sync_enabled", True)),
                "auto_sync_interval_min": int(config.get("playlists.auto_sync_interval_min", 30)),
                "spotify_client_id": config.get("spotify.client_id", ""),
                "spotify_client_secret": config.get("spotify.client_secret", ""),
                "musilon_enabled": bool(config.get("musilon.enabled", True)),
            },
        })

    def _handle_save_settings(self, body: Dict[str, Any]):
        s = body.get("settings") or body
        mapping = {
            "output_dir": "download.output_dir",
            "save_in_subfolders": "download.save_in_subfolders",
            "concurrency": "download.concurrency",
            "preferred_source": "download.preferred_source",
            "prefer_high_quality": "download.prefer_high_quality",
            "normalize_audio": "download.normalize_audio",
            "embed_lyrics": "download.embed_lyrics",
            "auto_sync_enabled": "playlists.auto_sync_enabled",
            "auto_sync_interval_min": "playlists.auto_sync_interval_min",
            "spotify_client_id": "spotify.client_id",
            "spotify_client_secret": "spotify.client_secret",
            "musilon_enabled": "musilon.enabled",
        }
        for key, cfg_path in mapping.items():
            if key in s:
                config.set(cfg_path, s[key])
        self.state.invalidate_library_cache()
        self._send_json({"ok": True})

    def _handle_shell_open(self, body: Dict[str, Any]):
        target = (body.get("path") or config.get("download.output_dir", "")).strip()
        if not target:
            return self._send_json({"ok": False, "error": "Empty path"}, status=400)
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        if os.path.isfile(target):
            subprocess.Popen(["explorer", f"/select,{os.path.normpath(target)}"], creationflags=flags)
        elif os.path.isdir(target):
            subprocess.Popen(["explorer", os.path.normpath(target)], creationflags=flags)
        self._send_json({"ok": True})

    def _handle_folder_dialog(self, body: Dict[str, Any]):
        current = (body.get("current") or config.get("download.output_dir", "")).strip()
        if callable(self.state.folder_picker_cb):
            chosen = self.state.folder_picker_cb(current)
            if chosen:
                config.set("download.output_dir", chosen)
                self.state.invalidate_library_cache()
                return self._send_json({"ok": True, "path": chosen})
        self._send_json({"ok": False, "path": ""})

    def _handle_player_notify(self, body: Dict[str, Any]):
        if callable(self.state.on_track_play_cb):
            try:
                self.state.on_track_play_cb(
                    body.get("file_path", ""),
                    body.get("title", ""),
                    body.get("artist", ""),
                )
            except Exception:
                pass
        self._send_json({"ok": True})

    # ------------------------------------------------------------------
    # Handlers: Cover Art & Byte-Range Audio Streaming
    # ------------------------------------------------------------------
    def _handle_get_cover(self, key: str):
        data, mime = self.state.get_cover_bytes(key)
        if not data:
            self.send_response(404)
            self._send_cors_headers()
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "public, max-age=86400")
        self._send_cors_headers()
        self.end_headers()
        self.wfile.write(data)

    def _handle_stream_audio(self, file_path: str, transcode: bool = False):
        if not file_path or not os.path.isfile(file_path):
            self.send_response(404)
            self._send_cors_headers()
            self.end_headers()
            return

        ext = os.path.splitext(file_path)[1].lower()
        if ext in (".m4a", ".aac", ".alac") or transcode:
            transcoded_p = get_cached_transcode(file_path)
            if transcoded_p and os.path.isfile(transcoded_p):
                file_path = transcoded_p
                ext = ".mp3"

        mime_map = {
            ".mp3": "audio/mpeg",
            ".flac": "audio/flac",
            ".opus": "audio/ogg",
            ".ogg": "audio/ogg",
            ".m4a": "audio/mp4",
            ".wav": "audio/wav",
        }
        content_type = mime_map.get(ext, "audio/mpeg")
        file_size = os.path.getsize(file_path)

        range_header = self.headers.get("Range")
        start = 0
        end = file_size - 1
        status = 200

        if range_header and range_header.startswith("bytes="):
            status = 206
            parts = range_header.replace("bytes=", "").split("-")
            if parts[0]:
                start = int(parts[0])
            if len(parts) > 1 and parts[1]:
                end = min(file_size - 1, int(parts[1]))

        if start >= file_size or start > end:
            self.send_response(416)
            self.send_header("Content-Range", f"bytes */{file_size}")
            self._send_cors_headers()
            self.end_headers()
            return

        chunk_len = end - start + 1
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(chunk_len))
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
        self._send_cors_headers()
        self.end_headers()

        with open(file_path, "rb") as f:
            f.seek(start)
            remaining = chunk_len
            while remaining > 0:
                buf = f.read(min(65536, remaining))
                if not buf:
                    break
                self.wfile.write(buf)
                remaining -= len(buf)

    def _handle_static_file(self, url_path: str):
        if url_path in ("/", ""):
            url_path = "/index.html"
        rel = url_path.lstrip("/").replace("/", os.sep)
        full_p = os.path.normpath(os.path.join(self.web_root, rel))
        if not full_p.startswith(os.path.normpath(self.web_root)) or not os.path.isfile(full_p):
            full_p = os.path.join(self.web_root, "index.html")
            if not os.path.isfile(full_p):
                self.send_response(404)
                self.end_headers()
                return

        mime, _ = mimetypes.guess_type(full_p)
        if full_p.endswith(".js"):
            mime = "application/javascript; charset=utf-8"
        elif full_p.endswith(".css"):
            mime = "text/css; charset=utf-8"
        elif full_p.endswith(".html"):
            mime = "text/html; charset=utf-8"
        elif full_p.endswith(".svg"):
            mime = "image/svg+xml"

        with open(full_p, "rb") as f:
            content = f.read()

        self.send_response(200)
        self.send_header("Content-Type", mime or "application/octet-stream")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-cache")
        self._send_cors_headers()
        self.end_headers()
        self.wfile.write(content)


class FlacifyWebServer:
    """Manages the embedded background ThreadingHTTPServer for the Spotify Desktop Web UI."""

    def __init__(
        self,
        queue_manager: DownloadQueueManager,
        archive_manager: ArchiveManager,
        web_root: str,
        folder_picker_cb: Optional[Callable[[str], str]] = None,
        on_track_play_cb: Optional[Callable[[str, str, str], None]] = None,
    ):
        self.state = WebBackendState(
            queue_manager=queue_manager,
            archive_manager=archive_manager,
            folder_picker_cb=folder_picker_cb,
            on_track_play_cb=on_track_play_cb,
        )
        self.web_root = os.path.abspath(web_root)
        self.port = 0
        self.httpd: Optional[ThreadingHTTPServer] = None
        self.thread: Optional[threading.Thread] = None

    def start(self) -> str:
        if self.httpd is not None:
            return f"http://127.0.0.1:{self.port}"

        handler_cls = type(
            "BoundFlacifyWebRequestHandler",
            (FlacifyWebRequestHandler,),
            {"state": self.state, "web_root": self.web_root},
        )
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(
            target=self.httpd.serve_forever,
            daemon=True,
            name="FlacifyWebServerThread",
        )
        self.thread.start()
        logger.info(f"Flacify Web Studio Server listening at http://127.0.0.1:{self.port}")
        return f"http://127.0.0.1:{self.port}"

    def stop(self):
        if self.httpd:
            try:
                self.httpd.shutdown()
                self.httpd.server_close()
            except Exception:
                pass
            self.httpd = None
