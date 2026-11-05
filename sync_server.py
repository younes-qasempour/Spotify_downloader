import os
import re
import json
import socket
import hashlib
import time
import logging
import subprocess
from pathlib import Path
from typing import List, Optional, Dict, Any, Callable
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Header, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from zeroconf import ServiceInfo, Zeroconf
import uvicorn
from PyQt6.QtCore import QThread, pyqtSignal

logger = logging.getLogger("sync_server")


# ============================================================================
# Pydantic Data Models (Shared Schema with Android Flutter App)
# ============================================================================

class TrackManifestItem(BaseModel):
    track_id: str                   # Unique ID (MD5 of relative filename or Spotify ID)
    filename: str                   # Relative path inside music folder
    title: str
    artist: str
    album: str
    duration_ms: int = 0
    file_size: int
    file_hash: str                  # Fast partial SHA-256 for rapid delta detection
    has_lyrics: bool = False
    lyrics_lrc: Optional[str] = None
    cover_hash: Optional[str] = None
    updated_at: int                 # Unix timestamp in seconds


class ManifestResponse(BaseModel):
    device_name: str
    total_tracks: int
    tracks: List[TrackManifestItem]


class SyncPlaylistTrack(BaseModel):
    spotify_id: str
    title: str
    artist: str
    album: Optional[str] = ""
    duration_ms: Optional[int] = 0
    track_number: Optional[int] = 1
    cover_url: Optional[str] = ""


class SyncPlaylistItem(BaseModel):
    id: str
    name: str
    spotify_url: Optional[str] = ""
    cover_url: Optional[str] = ""
    total_tracks: int = 0
    updated_at: int                 # Unix timestamp in seconds
    tracks: List[SyncPlaylistTrack] = []


class PlaylistSyncRequest(BaseModel):
    playlists: List[SyncPlaylistItem]


class PlaylistSyncResponse(BaseModel):
    device_name: str
    playlists: List[SyncPlaylistItem]
    synced_count: int


# ============================================================================
# Utilities: Fast Hash, Network IP & Tag Extraction
# ============================================================================

def compute_fast_file_hash(filepath: Path) -> str:
    """Computes SHA-256 of the first and last 64KB + file size for fast LAN indexing."""
    try:
        size = filepath.stat().st_size
        hasher = hashlib.sha256()
        hasher.update(str(size).encode('utf-8'))
        with open(filepath, 'rb') as f:
            hasher.update(f.read(65536))
            if size > 65536:
                f.seek(max(0, size - 65536))
                hasher.update(f.read(65536))
        return hasher.hexdigest()
    except Exception as e:
        logger.debug(f"Error hashing file {filepath}: {e}")
        return ""


def get_lan_info() -> Dict[str, Any]:
    """
    Intelligently identifies the real LAN / Wi-Fi IP and network adapter,
    filtering out VPN tunnels (Windscribe, WireGuard, OpenVPN, PPP, TAP, TUN)
    and virtual machine adapters (VMware, VirtualBox, vEthernet).
    """
    adapters = []
    try:
        out = subprocess.check_output(['ipconfig', '/all'], text=True, errors='ignore')
        current_adapter = {}
        for line in out.splitlines():
            line_stripped = line.strip()
            if not line.startswith(' ') and line_stripped.endswith(':'):
                if current_adapter.get('name') and current_adapter.get('ips'):
                    adapters.append(current_adapter)
                current_adapter = {'name': line_stripped[:-1], 'ips': [], 'gateway': False, 'desc': ''}
            elif 'Description' in line:
                current_adapter['desc'] = line.split(':', 1)[-1].strip()
            elif 'IPv4 Address' in line or 'IPv4-Adresse' in line:
                m = re.search(r'([0-9]+\.[0-9]+\.[0-9]+\.[0-9]+)', line)
                if m:
                    ip = m.group(1)
                    if not ip.startswith('127.') and not ip.startswith('169.254.'):
                        current_adapter['ips'].append(ip)
            elif 'Default Gateway' in line or 'Standardgateway' in line:
                m = re.search(r'([0-9]+\.[0-9]+\.[0-9]+\.[0-9]+)', line)
                if m and m.group(1) != '0.0.0.0':
                    current_adapter['gateway'] = True

        if current_adapter.get('name') and current_adapter.get('ips'):
            adapters.append(current_adapter)

        ignore = ['vpn', 'ppp', 'windscribe', 'tun', 'tap', 'wireguard', 'tailscale', 'zerotier', 'vmware', 'virtual', 'hyper-v', 'loopback', 'vethernet']

        # Priority 1: Wi-Fi or Ethernet with default gateway and not a VPN
        for a in adapters:
            nd = (a['name'] + ' ' + a.get('desc', '')).lower()
            if not any(k in nd for k in ignore) and a.get('gateway') and ('wi-fi' in nd or 'wireless' in nd or 'ethernet' in nd):
                return {'ip': a['ips'][0], 'adapter': a['name']}

        # Priority 2: Any non-VPN adapter with a valid gateway
        for a in adapters:
            nd = (a['name'] + ' ' + a.get('desc', '')).lower()
            if not any(k in nd for k in ignore) and a.get('gateway') and a['ips']:
                return {'ip': a['ips'][0], 'adapter': a['name']}

        # Priority 3: Any non-VPN adapter with an IP
        for a in adapters:
            nd = (a['name'] + ' ' + a.get('desc', '')).lower()
            if not any(k in nd for k in ignore) and a['ips']:
                return {'ip': a['ips'][0], 'adapter': a['name']}
    except Exception as e:
        logger.debug(f"Error enumerating LAN adapters: {e}")

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('10.255.255.255', 1))
        ip = s.getsockname()[0]
        s.close()
        return {'ip': ip, 'adapter': 'Default Adapter'}
    except Exception:
        try:
            ip = socket.gethostbyname(socket.gethostname())
            return {'ip': ip, 'adapter': 'Local Hostname'}
        except Exception:
            return {'ip': '127.0.0.1', 'adapter': 'Localhost'}


def get_local_ip() -> str:
    """Returns local LAN IP address accessible by other devices on the same Wi-Fi."""
    return get_lan_info()['ip']


def extract_audio_tags_and_cover(file_path: Path) -> Dict[str, Any]:
    """Reads embedded ID3 / FLAC metadata and cover hash using Mutagen if available."""
    info = {
        "title": file_path.stem,
        "artist": "Unknown Artist",
        "album": "Synced Music",
        "duration_ms": 0,
        "cover_hash": None,
    }

    # Split "Artist - Title" filename convention as initial default
    stem_parts = file_path.stem.split(' - ', 1)
    if len(stem_parts) > 1:
        info["artist"] = stem_parts[0].strip()
        info["title"] = stem_parts[1].strip()

    try:
        ext = file_path.suffix.lower()
        if ext == ".flac":
            from mutagen.flac import FLAC
            audio = FLAC(str(file_path))
            if audio.tags:
                if "title" in audio.tags and audio.tags["title"]:
                    info["title"] = str(audio.tags["title"][0])
                if "artist" in audio.tags and audio.tags["artist"]:
                    info["artist"] = str(audio.tags["artist"][0])
                if "album" in audio.tags and audio.tags["album"]:
                    info["album"] = str(audio.tags["album"][0])
            if audio.info:
                info["duration_ms"] = int(audio.info.length * 1000)
            if audio.pictures:
                info["cover_hash"] = hashlib.md5(audio.pictures[0].data[:16384]).hexdigest()

        elif ext == ".mp3":
            from mutagen.mp3 import MP3
            audio = MP3(str(file_path))
            if audio.info:
                info["duration_ms"] = int(audio.info.length * 1000)
            if audio.tags:
                title_tag = audio.tags.get("TIT2")
                if title_tag:
                    info["title"] = str(title_tag.text[0])
                artist_tag = audio.tags.get("TPE1")
                if artist_tag:
                    info["artist"] = str(artist_tag.text[0])
                album_tag = audio.tags.get("TALB")
                if album_tag:
                    info["album"] = str(album_tag.text[0])
                for tag_name, tag in audio.tags.items():
                    if tag_name.startswith("APIC"):
                        info["cover_hash"] = hashlib.md5(tag.data[:16384]).hexdigest()
                        break

        elif ext in (".m4a", ".mp4"):
            from mutagen.mp4 import MP4
            audio = MP4(str(file_path))
            if audio.info:
                info["duration_ms"] = int(audio.info.length * 1000)
            if audio.tags:
                if "\xa9nam" in audio.tags:
                    info["title"] = str(audio.tags["\xa9nam"][0])
                if "\xa9ART" in audio.tags:
                    info["artist"] = str(audio.tags["\xa9ART"][0])
                if "\xa9alb" in audio.tags:
                    info["album"] = str(audio.tags["\xa9alb"][0])
                if "covr" in audio.tags and audio.tags["covr"]:
                    info["cover_hash"] = hashlib.md5(audio.tags["covr"][0][:16384]).hexdigest()
    except Exception as e:
        logger.debug(f"Could not read Mutagen tags from {file_path}: {e}")

    return info


# ============================================================================
# FastAPI Wi-Fi Sync Server Application
# ============================================================================

def create_sync_app(
    music_dir: Path,
    auth_token: str,
    archive_manager: Optional[Any] = None,
    on_sync_event: Optional[Callable[[str], None]] = None,
    on_progress_event: Optional[Callable[[str, str, float], None]] = None,
    on_client_connected: Optional[Callable[[str], None]] = None,
) -> FastAPI:
    app = FastAPI(title="Flacify Local Wi-Fi Sync Server", version="1.0.0")
    music_dir.mkdir(parents=True, exist_ok=True)

    active_transfers: Dict[str, Dict[str, Any]] = {}
    manifest_cache: Dict[str, Any] = {
        "timestamp": 0.0,
        "items": [],
        "by_id": {},
    }

    def verify_token(provided_token: str):
        if auth_token:
            if not provided_token or provided_token.strip() != auth_token.strip():
                raise HTTPException(status_code=401, detail="Invalid sync token")

    def build_manifest(force: bool = False) -> List[TrackManifestItem]:
        now = time.time()
        if not force and manifest_cache["items"] and (now - manifest_cache["timestamp"] < 30.0):
            return manifest_cache["items"]

        items: List[TrackManifestItem] = []
        by_id_map: Dict[str, Path] = {}
        supported_exts = {'.flac', '.mp3', '.m4a', '.opus', '.ogg', '.wav'}

        # Map from archive database if available
        archive_map = {}
        if archive_manager:
            try:
                for row in archive_manager.get_all_tracks():
                    fp = row.get("file_path", "")
                    if fp:
                        norm = os.path.normpath(fp).lower()
                        archive_map[norm] = row
            except Exception as e:
                logger.debug(f"Error querying archive for manifest: {e}")

        for path in music_dir.rglob('*'):
            if path.suffix.lower() in supported_exts and path.is_file():
                try:
                    stat = path.stat()
                    rel_name = str(path.relative_to(music_dir)).replace('\\', '/')
                    file_hash = compute_fast_file_hash(path)
                    track_id = hashlib.md5(rel_name.lower().encode('utf-8')).hexdigest()
                    by_id_map[track_id] = path

                    # Check for sidecar .lrc file
                    lrc_path = path.with_suffix('.lrc')
                    lyrics_content = None
                    if lrc_path.exists():
                        try:
                            lyrics_content = lrc_path.read_text(encoding='utf-8', errors='ignore')
                        except Exception:
                            lyrics_content = None

                    norm_key = os.path.normpath(str(path)).lower()
                    arch_row = archive_map.get(norm_key)

                    if arch_row:
                        title = arch_row.get("title") or path.stem
                        artist = arch_row.get("artist") or "Unknown Artist"
                        album = arch_row.get("album") or "Synced Library"
                        duration_ms = arch_row.get("duration_ms") or 0
                        cover_hash = arch_row.get("spotify_id") or None
                    else:
                        tags = extract_audio_tags_and_cover(path)
                        title = tags["title"]
                        artist = tags["artist"]
                        album = tags["album"]
                        duration_ms = tags["duration_ms"]
                        cover_hash = tags["cover_hash"]

                    items.append(TrackManifestItem(
                        track_id=track_id,
                        filename=rel_name,
                        title=title,
                        artist=artist,
                        album=album,
                        duration_ms=duration_ms,
                        file_size=stat.st_size,
                        file_hash=file_hash,
                        has_lyrics=lyrics_content is not None,
                        lyrics_lrc=lyrics_content,
                        cover_hash=cover_hash,
                        updated_at=int(stat.st_mtime),
                    ))
                except Exception as err:
                    logger.debug(f"Error indexing file {path}: {err}")

        manifest_cache["items"] = items
        manifest_cache["by_id"] = by_id_map
        manifest_cache["timestamp"] = now
        return items

    @app.get("/api/ping")
    def ping(request: Request):
        client_host = request.client.host if request.client else "unknown"
        if on_client_connected:
            on_client_connected(client_host)
        return {
            "status": "online",
            "hostname": socket.gethostname(),
            "version": "1.0",
            "client_ip": client_host
        }

    @app.get("/api/manifest", response_model=ManifestResponse)
    def get_manifest(
        request: Request,
        x_sync_token: str = Header(default=""),
        token: str = Query(default=""),
        refresh: bool = Query(default=False)
    ):
        verify_token(x_sync_token or token)
        client_host = request.client.host if request.client else "unknown"
        if on_client_connected:
            on_client_connected(client_host)
        tracks = build_manifest(force=refresh)
        if on_sync_event:
            on_sync_event(f"Manifest requested by {client_host} ({len(tracks)} tracks indexed)")
        return ManifestResponse(
            device_name=socket.gethostname(),
            total_tracks=len(tracks),
            tracks=tracks
        )

    @app.get("/api/tracks/{track_id}/download")
    def download_track(
        track_id: str,
        request: Request,
        x_sync_token: str = Header(default=""),
        token: str = Query(default="")
    ):
        verify_token(x_sync_token or token)
        client_host = request.client.host if request.client else "unknown"
        if not manifest_cache["items"]:
            build_manifest()

        target_path = manifest_cache["by_id"].get(track_id)
        if not target_path or not target_path.exists():
            build_manifest(force=True)
            target_path = manifest_cache["by_id"].get(track_id)

        if target_path and target_path.exists():
            if on_sync_event:
                on_sync_event(f"Sending to phone ({client_host}): {target_path.name}")
            if on_progress_event:
                on_progress_event(target_path.name, "download", 1.0)
            return FileResponse(
                path=target_path,
                filename=target_path.name,
                media_type="application/octet-stream"
            )
        raise HTTPException(status_code=404, detail="Track not found")

    @app.post("/api/tracks/upload")
    async def upload_track(
        request: Request,
        rel_filename: str = Form(...),
        lyrics_lrc: Optional[str] = Form(None),
        file: UploadFile = File(...),
        x_sync_token: str = Header(default="")
    ):
        verify_token(x_sync_token)
        client_host = request.client.host if request.client else "unknown"
        if on_client_connected:
            on_client_connected(client_host)

        # Sanitize path to avoid traversal attacks
        safe_name = Path(rel_filename).name
        dest_path = music_dir / safe_name

        total_read = 0
        with open(dest_path, "wb") as buffer:
            while chunk := await file.read(1024 * 256):
                buffer.write(chunk)
                total_read += len(chunk)

        if lyrics_lrc:
            lrc_path = dest_path.with_suffix('.lrc')
            lrc_path.write_text(lyrics_lrc, encoding='utf-8')

        if on_sync_event:
            on_sync_event(f"Received from phone: {safe_name} ({total_read // 1024} KB)")
        if on_progress_event:
            on_progress_event(safe_name, "upload", 1.0)

        # Automatically index uploaded file into SQLite ArchiveManager if available
        if archive_manager:
            try:
                archive_manager.scan_and_index_directory(str(music_dir))
            except Exception as e_idx:
                logger.debug(f"Could not auto-index uploaded track: {e_idx}")

        return {"status": "uploaded", "filename": safe_name, "bytes_written": total_read}

    @app.get("/api/playlists")
    def get_playlists(x_sync_token: str = Header(default="")):
        verify_token(x_sync_token)
        result: List[SyncPlaylistItem] = []
        if not archive_manager:
            return {"device_name": socket.gethostname(), "playlists": []}

        try:
            saved_playlists = archive_manager.get_saved_playlists()
            for pl in saved_playlists:
                pl_id = pl.get("id", "")
                raw_tracks = archive_manager.get_saved_playlist_tracks(pl_id)
                sync_tracks = []
                for t in raw_tracks:
                    sync_tracks.append(SyncPlaylistTrack(
                        spotify_id=t.get("spotify_id") or "",
                        title=t.get("title") or "Unknown Track",
                        artist=t.get("artist") or "Unknown Artist",
                        album=t.get("album") or "",
                        duration_ms=t.get("duration_ms") or 0,
                        track_number=t.get("track_number") or 1,
                        cover_url=t.get("cover_url") or "",
                    ))

                # Convert updated_at string/timestamp to unix seconds
                up_at = pl.get("updated_at")
                up_secs = int(time.time())
                if isinstance(up_at, (int, float)):
                    up_secs = int(up_at)
                elif isinstance(up_at, str) and up_at:
                    try:
                        import datetime
                        dt = datetime.datetime.fromisoformat(up_at.replace("Z", "+00:00"))
                        up_secs = int(dt.timestamp())
                    except Exception:
                        pass

                result.append(SyncPlaylistItem(
                    id=pl_id,
                    name=pl.get("name") or "Playlist",
                    spotify_url=pl.get("spotify_url") or "",
                    cover_url=pl.get("cover_url") or "",
                    total_tracks=len(sync_tracks),
                    updated_at=up_secs,
                    tracks=sync_tracks
                ))
        except Exception as e:
            logger.error(f"Error fetching playlists for sync: {e}")

        return {"device_name": socket.gethostname(), "playlists": result}

    @app.post("/api/playlists/sync", response_model=PlaylistSyncResponse)
    def sync_playlists(
        payload: PlaylistSyncRequest,
        x_sync_token: str = Header(default="")
    ):
        verify_token(x_sync_token)
        if not archive_manager:
            return PlaylistSyncResponse(
                device_name=socket.gethostname(),
                playlists=payload.playlists,
                synced_count=0
            )

        updated_count = 0
        from core.spotify_client import TrackMetadata

        local_playlists_map = {p["id"]: p for p in archive_manager.get_saved_playlists()}

        for remote_pl in payload.playlists:
            local = local_playlists_map.get(remote_pl.id)
            should_apply_remote = False

            if local is None:
                # Playlist exists on phone but not on PC
                should_apply_remote = True
            else:
                # Last-Write-Wins (LWW) comparison
                local_up = local.get("updated_at")
                local_secs = 0
                if isinstance(local_up, (int, float)):
                    local_secs = int(local_up)
                elif isinstance(local_up, str) and local_up:
                    try:
                        import datetime
                        dt = datetime.datetime.fromisoformat(local_up.replace("Z", "+00:00"))
                        local_secs = int(dt.timestamp())
                    except Exception:
                        pass

                if remote_pl.updated_at > local_secs:
                    should_apply_remote = True

            if should_apply_remote:
                tracks_to_save: List[TrackMetadata] = []
                for trk in remote_pl.tracks:
                    tracks_to_save.append(TrackMetadata(
                        id=trk.spotify_id,
                        title=trk.title,
                        artists=[trk.artist] if trk.artist else ["Unknown Artist"],
                        album=trk.album or "",
                        duration_ms=trk.duration_ms or 0,
                        track_number=trk.track_number or 1,
                        cover_url=trk.cover_url or "",
                        collection_type="playlist",
                        collection_name=remote_pl.name
                    ))

                archive_manager.save_playlist(
                    name=remote_pl.name,
                    spotify_url=remote_pl.spotify_url or "",
                    cover_url=remote_pl.cover_url or "",
                    tracks=tracks_to_save,
                    playlist_id=remote_pl.id
                )
                updated_count += 1
                if on_sync_event:
                    on_sync_event(f"Playlist synced from phone (LWW Win): {remote_pl.name}")

        # Return latest merged state from PC
        refreshed = get_playlists(x_sync_token=auth_token)
        return PlaylistSyncResponse(
            device_name=socket.gethostname(),
            playlists=refreshed.get("playlists", []),
            synced_count=updated_count
        )

    return app


# ============================================================================
# PyQt6 Background Worker Thread with mDNS Discovery
# ============================================================================

class WifiSyncServerThread(QThread):
    status_changed = pyqtSignal(str)
    server_started = pyqtSignal(str, int, str)        # ip, port, token
    server_stopped = pyqtSignal()
    progress_updated = pyqtSignal(str, str, float)     # item, direction, progress (0.0 - 1.0)
    device_connected = pyqtSignal(str)                 # client ip

    def __init__(
        self,
        music_dir: str,
        port: int = 8765,
        token: str = "flacify-lan-sync",
        archive_manager: Optional[Any] = None
    ):
        super().__init__()
        self.music_dir = Path(music_dir)
        self.port = port
        self.token = token
        self.archive_manager = archive_manager
        self.zeroconf: Optional[Zeroconf] = None
        self.service_info: Optional[ServiceInfo] = None
        self._server: Optional[uvicorn.Server] = None
        self.ip: str = "127.0.0.1"

    def register_mdns(self, ip: str):
        try:
            # Bind specifically to the Wi-Fi LAN IP so multicast traffic doesn't route into VPN
            self.zeroconf = Zeroconf(interfaces=[ip])
            hostname = socket.gethostname()
            self.service_info = ServiceInfo(
                type_="_musicsync._tcp.local.",
                name=f"{hostname}._musicsync._tcp.local.",
                addresses=[socket.inet_aton(ip)],
                port=self.port,
                properties={"version": "1.0", "device": hostname, "token": self.token},
                server=f"{hostname}.local.",
            )
            self.zeroconf.register_service(self.service_info)
            logger.info(f"mDNS registered: _musicsync._tcp.local. on {ip}:{self.port}")
        except Exception as e:
            try:
                self.zeroconf = Zeroconf()
                hostname = socket.gethostname()
                self.service_info = ServiceInfo(
                    type_="_musicsync._tcp.local.",
                    name=f"{hostname}._musicsync._tcp.local.",
                    addresses=[socket.inet_aton(ip)],
                    port=self.port,
                    properties={"version": "1.0", "device": hostname, "token": self.token},
                    server=f"{hostname}.local.",
                )
                self.zeroconf.register_service(self.service_info)
                logger.info(f"mDNS registered (fallback): _musicsync._tcp.local. on {ip}:{self.port}")
            except Exception as e2:
                logger.warning(f"Could not register mDNS service: {e2}")
                self.status_changed.emit(f"mDNS Notice: {e2}")

    def run(self):
        self.ip = get_local_ip()
        self.register_mdns(self.ip)

        app = create_sync_app(
            music_dir=self.music_dir,
            auth_token=self.token,
            archive_manager=self.archive_manager,
            on_sync_event=lambda msg: self.status_changed.emit(msg),
            on_progress_event=lambda item, direction, p: self.progress_updated.emit(item, direction, p),
            on_client_connected=lambda client: self.device_connected.emit(client),
        )

        config = uvicorn.Config(
            app=app,
            host="0.0.0.0",
            port=self.port,
            log_level="warning",
            access_log=False
        )
        self._server = uvicorn.Server(config)
        self.server_started.emit(self.ip, self.port, self.token)
        self.status_changed.emit(f"Wi-Fi Sync active on {self.ip}:{self.port}")
        logger.info(f"Sync Server listening on 0.0.0.0:{self.port} (LAN: {self.ip})")

        try:
            self._server.run()
        finally:
            self.server_stopped.emit()

    def stop(self):
        if self._server:
            self._server.should_exit = True
        if self.zeroconf and self.service_info:
            try:
                self.zeroconf.unregister_service(self.service_info)
                self.zeroconf.close()
            except Exception as e:
                logger.debug(f"Error unregistering mDNS: {e}")
            self.zeroconf = None
            self.service_info = None
        self.status_changed.emit("Sync Server stopped")
