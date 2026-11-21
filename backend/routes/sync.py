"""
Android & Mobile Wi-Fi Sync, Pairing QR Code, Resumable Lossless Transfer & Remote Share API (/api/sync/*).
"""

import asyncio
import gzip
import io
import json
import logging
import os
import re
import secrets
import stat
import time
from typing import Any, Dict, List, Literal, Optional, Set, Tuple
from urllib.parse import quote, urlparse

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field
import requests

from backend.mdns import (
    detect_reachable_lan_ips,
    get_device_name,
    get_or_create_pair_token,
    is_loopback_host,
)
from backend.routes.media import (
    _audio_media_type,
    _file_chunk_iterator,
    _parse_byte_range,
)
from backend.routes.queue import _resolve_and_enqueue_sync
from backend.state import BackendState
from backend.track_lookup import resolve_track_row_and_file
from core import __version__
from core.archive import normalize_path
from core.spotify_client import SpotifyClient

logger = logging.getLogger("backend.routes.sync")

router = APIRouter(prefix="/api/sync", tags=["sync"])

_URL_RE = re.compile(r"https?://[^\s<>\"']+")
_SPOTIFY_URI_RE = re.compile(
    r"spotify:(?:user:[^:\s]+:)?(?:track|album|playlist|artist|collection)(?::[a-zA-Z0-9]+)?",
    re.IGNORECASE,
)
_SHORT_LINK_HOSTS = frozenset({"spotify.link", "spotify.app.link", "spoti.fi"})


class ShareSpotifyUrlRequest(BaseModel):
    url: str = Field(..., min_length=1)
    auto_download: bool = True
    preferred_engine: Optional[Literal["auto", "melobot", "musilon", "youtube"]] = None


def _get_backend(request: Request) -> BackendState:
    return request.app.state.backend


def _resolve_port(request: Request) -> int:
    env_port = (os.getenv("FLACIFY_PORT") or "").strip()
    if env_port:
        try:
            port_val = int(env_port)
            if 1 <= port_val <= 65535:
                return port_val
        except ValueError:
            pass
    if request.url.port:
        return int(request.url.port)
    return 8765


def _build_sync_info(request: Request, backend: BackendState, *, include_secret: bool) -> Dict[str, Any]:
    cfg = backend.config
    lan_enabled = bool(cfg.get("mobile.lan_enabled", True))
    device_name = get_device_name(cfg)
    ips = detect_reachable_lan_ips()
    port = _resolve_port(request)
    urls = [f"http://{ip}:{port}" for ip in ips]
    primary_ip = ips[0] if ips else "127.0.0.1"
    primary_url = urls[0] if urls else f"http://127.0.0.1:{port}"
    bind_host = os.getenv("FLACIFY_BIND_HOST", "").strip()
    restart_required = bool(lan_enabled and bind_host and is_loopback_host(bind_host))

    archive = backend.archive_manager
    library_stats = archive.get_library_stats()
    try:
        saved_playlists_count = len(archive.get_saved_playlists())
    except Exception:
        saved_playlists_count = 0

    payload: Dict[str, Any] = {
        "lan_enabled": lan_enabled,
        "bind_host": bind_host,
        "restart_required": restart_required,
        "device_name": device_name,
        "port": port,
        "server_version": __version__,
        "ips": ips,
        "urls": urls,
        "primary_url": primary_url,
        "library_stats": library_stats,
        "saved_playlists_count": saved_playlists_count,
        "paired": True,
    }

    if include_secret:
        token = get_or_create_pair_token(cfg)
        pair_uri = (
            f"flacify://pair?host={quote(primary_ip, safe='')}"
            f"&port={port}"
            f"&token={quote(token, safe='')}"
            f"&name={quote(device_name, safe='')}"
            f"&urls={quote(','.join(urls), safe='')}"
        )
        payload["pair_token"] = token
        payload["pair_uri"] = pair_uri
        payload["qr_svg_url"] = "/api/sync/pairing-qr"

    return payload


def _build_pairing_qr_svg_sync(request: Request, backend: BackendState) -> bytes:
    info = _build_sync_info(request, backend, include_secret=True)
    pair_uri = info["pair_uri"]

    try:
        import qrcode
        import qrcode.image.svg
    except ImportError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"QR code library unavailable on host: {exc}",
        )

    qr = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=8,
        border=2,
    )
    qr.add_data(pair_uri)
    qr.make(fit=True)
    img = qr.make_image(image_factory=qrcode.image.svg.SvgPathImage)
    buf = io.BytesIO()
    img.save(buf)
    return buf.getvalue()


def _regenerate_pair_token_sync(request: Request, backend: BackendState) -> Dict[str, Any]:
    cfg = backend.config
    new_token = secrets.token_urlsafe(24)
    cfg.set("mobile.pair_token", new_token)
    if hasattr(cfg, "save") and callable(cfg.save):
        cfg.save()
    return _build_sync_info(request, backend, include_secret=True)


@router.get("/info")
async def get_sync_info(request: Request):
    backend = _get_backend(request)
    client_host = request.client.host if request.client else ""
    return await asyncio.to_thread(
        _build_sync_info,
        request,
        backend,
        include_secret=is_loopback_host(client_host),
    )


@router.get("/pairing-qr")
async def get_pairing_qr(request: Request):
    client_host = request.client.host if request.client else ""
    if not is_loopback_host(client_host):
        raise HTTPException(
            status_code=403,
            detail="Pairing QR code is only available locally on the host PC.",
        )

    backend = _get_backend(request)
    svg_bytes = await asyncio.to_thread(_build_pairing_qr_svg_sync, request, backend)

    return Response(
        content=svg_bytes,
        media_type="image/svg+xml",
        headers={"Cache-Control": "no-store"},
    )


@router.post("/token/regenerate")
async def regenerate_pair_token(request: Request):
    client_host = request.client.host if request.client else ""
    if not is_loopback_host(client_host):
        raise HTTPException(
            status_code=403,
            detail="Pair token regeneration is only allowed locally on the host PC.",
        )

    backend = _get_backend(request)
    return await asyncio.to_thread(_regenerate_pair_token_sync, request, backend)


def _client_accepts_gzip(request: Request) -> bool:
    accept_enc = request.headers.get("accept-encoding") or ""
    for part in accept_enc.split(","):
        tokens = [seg.strip().lower() for seg in part.split(";") if seg.strip()]
        if not tokens:
            continue
        coding = tokens[0]
        if coding not in ("gzip", "*"):
            continue
        q_val = 1.0
        for param in tokens[1:]:
            if param.startswith("q="):
                try:
                    q_val = float(param[2:].strip())
                except ValueError:
                    q_val = 0.0
        if q_val > 0.0:
            return True
    return False


def _build_sync_manifest_sync(
    backend: BackendState,
    playlist_id: Optional[str],
    include_tracks: bool,
) -> Dict[str, Any]:
    archive = backend.archive_manager

    raw_canonical = archive.get_all_tracks()
    dir_entries_cache: Dict[
        str, Optional[Tuple[Dict[str, Tuple[int, int]], Set[str]]]
    ] = {}

    def _scan_dir_cached(
        dir_path: str,
    ) -> Optional[Tuple[Dict[str, Tuple[int, int]], Set[str]]]:
        dir_key = os.path.normcase(dir_path)
        if dir_key in dir_entries_cache:
            return dir_entries_cache[dir_key]

        files_map: Dict[str, Tuple[int, int]] = {}
        lrc_stems: Set[str] = set()
        try:
            with os.scandir(dir_path) as entries:
                for entry in entries:
                    try:
                        if entry.is_symlink():
                            st = entry.stat(follow_symlinks=True)
                            if not stat.S_ISREG(st.st_mode):
                                continue
                        elif entry.is_file(follow_symlinks=False):
                            st = entry.stat(follow_symlinks=False)
                        else:
                            continue
                    except OSError:
                        continue
                    files_map[os.path.normcase(entry.name)] = (
                        int(st.st_size),
                        int(st.st_mtime * 1000),
                    )
                    if entry.name.lower().endswith(".lrc"):
                        lrc_stems.add(
                            os.path.normcase(os.path.splitext(entry.name)[0])
                        )
        except OSError:
            dir_entries_cache[dir_key] = None
            return None

        try:
            with os.scandir(os.path.join(dir_path, "lyrics")) as lrc_entries:
                for entry in lrc_entries:
                    if entry.name.lower().endswith(".lrc"):
                        try:
                            if entry.is_file(follow_symlinks=True):
                                lrc_stems.add(
                                    os.path.normcase(os.path.splitext(entry.name)[0])
                                )
                        except OSError:
                            pass
        except OSError:
            pass

        result = (files_map, lrc_stems)
        dir_entries_cache[dir_key] = result
        return result

    fp_to_canonical_row: Dict[str, Dict[str, Any]] = {}
    fp_to_canonical_id: Dict[str, str] = {}
    fp_to_stat: Dict[str, Tuple[str, int, int]] = {}
    fp_to_aliases: Dict[str, List[str]] = {}
    sid_to_canonical_id: Dict[str, str] = {}

    for row in raw_canonical:
        sid = str(row.get("spotify_id") or "").strip()
        raw_fp = str(row.get("file_path") or "").strip()
        norm_fp = normalize_path(raw_fp) if raw_fp else ""
        if not sid or not norm_fp:
            continue

        dir_data = _scan_dir_cached(os.path.dirname(norm_fp))
        if dir_data is not None:
            stat_pair = dir_data[0].get(os.path.normcase(os.path.basename(norm_fp)))
            if stat_pair is None:
                continue
            file_size, mtime_ms = stat_pair
        else:
            try:
                st = os.stat(norm_fp)
            except OSError:
                continue
            if not stat.S_ISREG(st.st_mode):
                continue
            file_size, mtime_ms = int(st.st_size), int(st.st_mtime * 1000)

        fp_key = os.path.normcase(norm_fp)
        existing_canon = fp_to_canonical_id.get(fp_key)
        if existing_canon:
            sid_to_canonical_id.setdefault(sid, existing_canon)
            if sid != existing_canon and sid not in fp_to_aliases[fp_key]:
                fp_to_aliases[fp_key].append(sid)
            continue

        fp_to_canonical_row[fp_key] = row
        fp_to_canonical_id[fp_key] = sid
        fp_to_stat[fp_key] = (norm_fp, file_size, mtime_ms)
        fp_to_aliases[fp_key] = []
        sid_to_canonical_id[sid] = sid

    try:
        with archive.connection() as conn:
            for sql in (
                "SELECT spotify_id, file_path FROM downloaded_tracks WHERE file_path IS NOT NULL AND file_path != ''",
                "SELECT spotify_id, file_path FROM saved_playlist_tracks WHERE file_path IS NOT NULL AND file_path != ''",
            ):
                for row_sid, row_fp in conn.execute(sql).fetchall():
                    if not row_sid or not row_fp:
                        continue
                    fk = os.path.normcase(normalize_path(row_fp))
                    canon_id = fp_to_canonical_id.get(fk)
                    if not canon_id:
                        continue
                    sid_to_canonical_id.setdefault(row_sid, canon_id)
                    if row_sid != canon_id and row_sid not in fp_to_aliases[fk]:
                        fp_to_aliases[fk].append(row_sid)
    except Exception as exc:
        logger.debug(f"Manifest alias resolution notice: {exc}")

    valid_canonical_ids = set(fp_to_canonical_id.values())

    if playlist_id:
        target_pl = archive.get_saved_playlist(playlist_id)
        if not target_pl:
            raise HTTPException(
                status_code=404, detail=f"Saved playlist '{playlist_id}' not found."
            )
        pl_list = [target_pl]
    else:
        pl_list = archive.get_saved_playlists()

    playlists_payload: List[Dict[str, Any]] = []
    referenced_canonical_ids: Set[str] = set()

    for pl in pl_list:
        pl_id = pl["id"]
        sp_rows = archive.get_saved_playlist_tracks(pl_id)
        pl_tracks: List[Dict[str, Any]] = []
        downloaded_count = 0

        for sp in sp_rows:
            sp_id = str(sp.get("spotify_id") or "")
            sp_fp = str(sp.get("file_path") or "").strip()
            canon_id = sid_to_canonical_id.get(sp_id)
            if not canon_id and sp_fp:
                canon_id = fp_to_canonical_id.get(os.path.normcase(normalize_path(sp_fp)))

            is_downloaded = bool(canon_id and canon_id in valid_canonical_ids)
            if is_downloaded and canon_id:
                referenced_canonical_ids.add(canon_id)
                downloaded_count += 1

            pl_tracks.append(
                {
                    "spotify_id": sp_id,
                    "canonical_id": canon_id if is_downloaded else sp_id,
                    "title": sp.get("title") or "",
                    "artist": sp.get("artist") or "",
                    "album": sp.get("album") or "",
                    "duration_ms": int(sp.get("duration_ms") or 0),
                    "downloaded": is_downloaded,
                }
            )

        playlists_payload.append(
            {
                "id": pl_id,
                "name": pl.get("name") or "Playlist",
                "total_tracks": len(pl_tracks),
                "downloaded_tracks": downloaded_count,
                "cover_url": f"/api/media/cover/collection?playlist_id={quote(pl_id, safe='')}",
                "remote_cover_url": pl.get("cover_url") or "",
                "tracks": pl_tracks,
            }
        )

    unique_tracks_payload: List[Dict[str, Any]] = []
    total_bytes = 0
    matched_unique_count = 0

    for fp_key, row in fp_to_canonical_row.items():
        canon_id = fp_to_canonical_id[fp_key]
        if playlist_id and canon_id not in referenced_canonical_ids:
            continue

        norm_fp, file_size, mtime_ms = fp_to_stat[fp_key]
        matched_unique_count += 1
        total_bytes += file_size
        if not include_tracks:
            continue

        bname = os.path.basename(norm_fp)
        stem, ext_raw = os.path.splitext(bname)
        ext = ext_raw.lower()
        q_badge = row.get("quality_badge") or ""
        s_type = row.get("source_type") or ""
        if not q_badge:
            q_inf, s_inf = archive.infer_badge_from_file(norm_fp)
            q_badge = q_inf or "FLAC 16"
            s_type = s_type or s_inf or "Musilon"

        parent_dir = os.path.dirname(norm_fp)
        parent_data = _scan_dir_cached(parent_dir)
        if parent_data is not None:
            has_lrc = os.path.normcase(stem) in parent_data[1]
        else:
            has_lrc = os.path.isfile(os.path.splitext(norm_fp)[0] + ".lrc") or os.path.isfile(
                os.path.join(parent_dir, "lyrics", stem + ".lrc")
            )

        unique_tracks_payload.append(
            {
                "id": canon_id,
                "alias_ids": fp_to_aliases.get(fp_key, []),
                "title": row.get("title") or stem,
                "artist": row.get("artist") or "Unknown Artist",
                "album": row.get("album") or "",
                "duration_ms": int(row.get("duration_ms") or 0),
                "track_number": int(row.get("track_number") or 1),
                "disc_number": int(row.get("disc_number") or 1),
                "genre": row.get("genre") or "",
                "quality_badge": q_badge,
                "source_type": s_type,
                "filename": bname,
                "ext": ext,
                "file_size": file_size,
                "mtime_ms": mtime_ms,
                "file_url": f"/api/sync/tracks/{quote(canon_id, safe='')}/file",
                "stream_url": f"/api/media/audio/{quote(canon_id, safe='')}",
                "cover_url": f"/api/media/cover/track/{quote(canon_id, safe='')}",
                "lyrics_url": f"/api/lyrics/{quote(canon_id, safe='')}",
                "has_lrc": has_lrc,
            }
        )

    return {
        "server_version": __version__,
        "device_name": get_device_name(backend.config),
        "generated_at": int(time.time() * 1000),
        "total_unique_tracks": matched_unique_count,
        "total_bytes": total_bytes,
        "playlists": playlists_payload,
        "tracks": unique_tracks_payload,
    }


def _build_manifest_payload_bytes_sync(
    backend: BackendState,
    playlist_id: Optional[str],
    include_tracks: bool,
    compress_gzip: bool,
) -> bytes:
    manifest = _build_sync_manifest_sync(backend, playlist_id, include_tracks)
    raw_bytes = json.dumps(manifest, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if compress_gzip:
        return gzip.compress(raw_bytes, compresslevel=5)
    return raw_bytes


@router.get("/manifest")
async def get_sync_manifest(
    request: Request,
    playlist_id: Optional[str] = Query(default=None),
    include_tracks: bool = Query(default=True),
):
    backend = _get_backend(request)
    use_gzip = _client_accepts_gzip(request)
    payload_bytes = await asyncio.to_thread(
        _build_manifest_payload_bytes_sync,
        backend,
        playlist_id,
        include_tracks,
        use_gzip,
    )
    headers = {"Vary": "Accept-Encoding"}
    if use_gzip:
        headers["Content-Encoding"] = "gzip"
    return Response(
        content=payload_bytes,
        media_type="application/json",
        headers=headers,
    )


def _ascii_safe_filename(file_path: str) -> str:
    cleaned = []
    for ch in os.path.basename(file_path or ""):
        code = ord(ch)
        if ch in ('"', "\\", "\r", "\n") or code < 32 or code >= 127:
            cleaned.append("_")
        else:
            cleaned.append(ch)
    result = "".join(cleaned).strip().strip(".")
    return result or "track"


def _file_transfer_headers(file_path: str, file_size: int, mtime_ms: int, track_id: str) -> Dict[str, str]:
    ascii_name = _ascii_safe_filename(file_path)
    encoded_name = quote(os.path.basename(file_path), safe="")
    etag = f'"{file_size:x}-{mtime_ms:x}"'
    return {
        "Accept-Ranges": "bytes",
        "Content-Length": str(file_size),
        "Content-Disposition": f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{encoded_name}',
        "ETag": etag,
        "X-File-Size": str(file_size),
        "X-File-Mtime-Ms": str(mtime_ms),
        "X-Track-Id": track_id,
    }


def _resolve_and_stat_track_file(backend: BackendState, track_id: str) -> Tuple[str, int, int]:
    file_path, _row, _qt = resolve_track_row_and_file(backend, track_id)
    if not file_path:
        raise HTTPException(
            status_code=404, detail=f"Audio file for track '{track_id}' not found."
        )
    try:
        st = os.stat(file_path)
    except OSError:
        raise HTTPException(
            status_code=404, detail=f"Audio file for track '{track_id}' not found."
        )
    if not stat.S_ISREG(st.st_mode):
        raise HTTPException(
            status_code=404, detail=f"Audio file for track '{track_id}' not found."
        )
    return file_path, int(st.st_size), int(st.st_mtime * 1000)


@router.head("/tracks/{track_id}/file")
async def head_sync_track_file(request: Request, track_id: str):
    backend = _get_backend(request)
    file_path, file_size, mtime_ms = await asyncio.to_thread(
        _resolve_and_stat_track_file, backend, track_id
    )
    return Response(
        status_code=200,
        media_type=_audio_media_type(file_path),
        headers=_file_transfer_headers(file_path, file_size, mtime_ms, track_id),
    )


@router.get("/tracks/{track_id}/file")
async def download_sync_track_file(request: Request, track_id: str):
    backend = _get_backend(request)
    file_path, file_size, mtime_ms = await asyncio.to_thread(
        _resolve_and_stat_track_file, backend, track_id
    )
    media_type = _audio_media_type(file_path)
    base_headers = _file_transfer_headers(file_path, file_size, mtime_ms, track_id)

    range_header = request.headers.get("range")
    if_range = (request.headers.get("if-range") or "").strip()
    etag = base_headers["ETag"]
    if range_header and (not if_range or if_range == etag):
        parsed = _parse_byte_range(range_header, file_size)
        if parsed is None:
            return Response(
                status_code=416,
                headers={
                    "Content-Range": f"bytes */{file_size}",
                    "Accept-Ranges": "bytes",
                },
            )
        start, end = parsed
        content_len = end - start + 1
        range_headers = dict(base_headers)
        range_headers["Content-Range"] = f"bytes {start}-{end}/{file_size}"
        range_headers["Content-Length"] = str(content_len)
        return StreamingResponse(
            _file_chunk_iterator(file_path, start, content_len, chunk_size=262144),
            status_code=206,
            media_type=media_type,
            headers=range_headers,
        )

    return StreamingResponse(
        _file_chunk_iterator(file_path, 0, file_size, chunk_size=262144),
        status_code=200,
        media_type=media_type,
        headers=base_headers,
    )


def _extract_shared_url(raw_text: str) -> str:
    text = raw_text or ""
    match = _URL_RE.search(text)
    if match:
        return match.group(0).rstrip(".,;!>\"')")
    uri_match = _SPOTIFY_URI_RE.search(text)
    if uri_match:
        return uri_match.group(0).rstrip(".,;!>\"')")
    return ""


def _unwrap_spotify_short_link(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme.lower() not in ("http", "https"):
        return url
    host = (parsed.hostname or "").lower()
    if host not in _SHORT_LINK_HOSTS:
        return url

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
    }
    try:
        resp = requests.head(url, allow_redirects=True, timeout=6, headers=headers)
        try:
            final_url = str(resp.url or url)
            status = int(getattr(resp, "status_code", 200) or 200)
        finally:
            resp.close()

        final_host = (urlparse(final_url).hostname or "").lower()
        if status >= 400 or final_host in _SHORT_LINK_HOSTS:
            resp2 = requests.get(
                url, allow_redirects=True, stream=True, timeout=6, headers=headers
            )
            try:
                if resp2.url:
                    final_url = str(resp2.url)
            finally:
                resp2.close()

        if urlparse(final_url).scheme.lower() in ("http", "https"):
            return final_url
    except Exception as exc:
        logger.debug(f"Could not unwrap Spotify short link '{url}': {exc}")
    return url


@router.post("/share")
async def share_url_from_mobile(request: Request, body: ShareSpotifyUrlRequest):
    extracted = _extract_shared_url(body.url)
    if not extracted:
        raise HTTPException(
            status_code=400,
            detail="No valid Spotify or audio URL found in shared text.",
        )

    extracted = await asyncio.to_thread(_unwrap_spotify_short_link, extracted)
    backend = _get_backend(request)
    parsed = SpotifyClient.parse_url(extracted)
    entity_type = parsed[0] if parsed else "url"

    result = await asyncio.to_thread(
        _resolve_and_enqueue_sync,
        backend,
        [extracted],
        body.auto_download,
        body.preferred_engine,
    )

    return {
        "accepted": True,
        "extracted_url": extracted,
        "entity_type": entity_type,
        "queued_count": result["enqueued_count"],
        "saved_playlists_updated": result["saved_playlists_updated"],
        "started": result["started"],
        "tracks": result["items"],
        "errors": result["errors"],
    }
