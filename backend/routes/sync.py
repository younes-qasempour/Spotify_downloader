"""
Android & Mobile Wi-Fi Sync, Pairing QR Code, Resumable Lossless Transfer & Remote Share API (/api/sync/*).
"""

import asyncio
import io
import logging
import os
import re
import secrets
import time
from typing import Any, Dict, List, Literal, Optional
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from backend.mdns import (
    detect_reachable_lan_ips,
    get_device_name,
    get_or_create_pair_token,
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

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost", "testclient"})
_URL_RE = re.compile(r"https?://[^\s<>\"']+")


class ShareSpotifyUrlRequest(BaseModel):
    url: str = Field(..., min_length=1)
    auto_download: bool = True
    preferred_engine: Optional[Literal["auto", "melobot", "musilon", "youtube"]] = None


def is_loopback_host(host: Optional[str]) -> bool:
    return (host or "").strip().lower() in _LOOPBACK_HOSTS


def _get_backend(request: Request) -> BackendState:
    return request.app.state.backend


def _resolve_port(request: Request) -> int:
    if request.url.port:
        return int(request.url.port)
    try:
        return int(os.getenv("FLACIFY_PORT", "8765") or "8765")
    except ValueError:
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

    archive = backend.archive_manager
    library_stats = archive.get_library_stats()
    try:
        saved_playlists_count = len(archive.get_saved_playlists())
    except Exception:
        saved_playlists_count = 0

    payload: Dict[str, Any] = {
        "lan_enabled": lan_enabled,
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


def _has_companion_lrc(file_path: str) -> bool:
    stem_no_ext = os.path.splitext(file_path)[0]
    if os.path.isfile(stem_no_ext + ".lrc"):
        return True
    parent = os.path.dirname(file_path)
    base = os.path.splitext(os.path.basename(file_path))[0]
    return os.path.isfile(os.path.join(parent, "lyrics", base + ".lrc"))


@router.get("/info")
async def get_sync_info(request: Request):
    backend = _get_backend(request)
    client_host = request.client.host if request.client else ""
    return _build_sync_info(
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

    return Response(
        content=buf.getvalue(),
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
    cfg = backend.config
    new_token = secrets.token_urlsafe(24)
    cfg.set("mobile.pair_token", new_token)
    if hasattr(cfg, "save") and callable(cfg.save):
        cfg.save()

    return _build_sync_info(request, backend, include_secret=True)


@router.get("/manifest")
async def get_sync_manifest(
    request: Request,
    playlist_id: Optional[str] = Query(default=None),
    include_tracks: bool = Query(default=True),
):
    backend = _get_backend(request)
    archive = backend.archive_manager

    raw_canonical = archive.get_all_tracks()
    fp_to_canonical_row: Dict[str, Dict[str, Any]] = {}
    fp_to_canonical_id: Dict[str, str] = {}
    sid_to_canonical_id: Dict[str, str] = {}

    for row in raw_canonical:
        sid = str(row.get("spotify_id") or "").strip()
        raw_fp = str(row.get("file_path") or "").strip()
        norm_fp = normalize_path(raw_fp) if raw_fp else ""
        if not sid or not norm_fp or not os.path.isfile(norm_fp):
            continue
        fp_key = os.path.normcase(norm_fp)
        fp_to_canonical_row[fp_key] = row
        fp_to_canonical_id[fp_key] = sid
        sid_to_canonical_id[sid] = sid

    fp_to_aliases: Dict[str, List[str]] = {k: [] for k in fp_to_canonical_id}
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
    referenced_canonical_ids = set()

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
                "tracks": pl_tracks,
            }
        )

    unique_tracks_payload: List[Dict[str, Any]] = []
    total_bytes = 0

    for fp_key, row in fp_to_canonical_row.items():
        canon_id = fp_to_canonical_id[fp_key]
        if playlist_id and canon_id not in referenced_canonical_ids:
            continue

        norm_fp = normalize_path(row["file_path"])
        try:
            st = os.stat(norm_fp)
            file_size = int(st.st_size)
            mtime_ms = int(st.st_mtime * 1000)
        except OSError:
            continue

        total_bytes += file_size
        if not include_tracks:
            continue

        bname = os.path.basename(norm_fp)
        ext = os.path.splitext(bname)[1].lower()
        q_badge = row.get("quality_badge") or ""
        s_type = row.get("source_type") or ""
        if not q_badge:
            q_inf, s_inf = archive.infer_badge_from_file(norm_fp)
            q_badge = q_inf or "FLAC 16"
            s_type = s_type or s_inf or "Musilon"

        unique_tracks_payload.append(
            {
                "id": canon_id,
                "alias_ids": fp_to_aliases.get(fp_key, []),
                "title": row.get("title") or os.path.splitext(bname)[0],
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
                "has_lrc": _has_companion_lrc(norm_fp),
            }
        )

    total_unique = (
        len(referenced_canonical_ids) if playlist_id and not include_tracks else (
            len(unique_tracks_payload) if include_tracks else len(fp_to_canonical_id)
        )
    )

    return {
        "server_version": __version__,
        "device_name": get_device_name(backend.config),
        "generated_at": int(time.time() * 1000),
        "total_unique_tracks": total_unique,
        "total_bytes": total_bytes,
        "playlists": playlists_payload,
        "tracks": unique_tracks_payload,
    }


def _file_transfer_headers(file_path: str, file_size: int, mtime_ms: int, track_id: str) -> Dict[str, str]:
    encoded_name = quote(os.path.basename(file_path), safe="")
    return {
        "Accept-Ranges": "bytes",
        "Content-Length": str(file_size),
        "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_name}",
        "X-File-Size": str(file_size),
        "X-File-Mtime-Ms": str(mtime_ms),
        "X-Track-Id": track_id,
    }


@router.head("/tracks/{track_id}/file")
async def head_sync_track_file(request: Request, track_id: str):
    backend = _get_backend(request)
    file_path, _row, _qt = resolve_track_row_and_file(backend, track_id)
    if not file_path or not os.path.isfile(file_path):
        raise HTTPException(
            status_code=404, detail=f"Audio file for track '{track_id}' not found."
        )

    st = os.stat(file_path)
    return Response(
        status_code=200,
        media_type=_audio_media_type(file_path),
        headers=_file_transfer_headers(file_path, int(st.st_size), int(st.st_mtime * 1000), track_id),
    )


@router.get("/tracks/{track_id}/file")
async def download_sync_track_file(request: Request, track_id: str):
    backend = _get_backend(request)
    file_path, _row, _qt = resolve_track_row_and_file(backend, track_id)
    if not file_path or not os.path.isfile(file_path):
        raise HTTPException(
            status_code=404, detail=f"Audio file for track '{track_id}' not found."
        )

    st = os.stat(file_path)
    file_size = int(st.st_size)
    mtime_ms = int(st.st_mtime * 1000)
    media_type = _audio_media_type(file_path)
    base_headers = _file_transfer_headers(file_path, file_size, mtime_ms, track_id)

    range_header = request.headers.get("range")
    if range_header:
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
    match = _URL_RE.search(raw_text or "")
    if not match:
        return ""
    return match.group(0).rstrip(".,;!>\"')")


@router.post("/share")
async def share_url_from_mobile(request: Request, body: ShareSpotifyUrlRequest):
    extracted = _extract_shared_url(body.url)
    if not extracted:
        raise HTTPException(
            status_code=400,
            detail="No valid Spotify or audio URL found in shared text.",
        )

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
