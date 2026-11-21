"""
Audio streaming (HTTP Byte-Range) and cover artwork endpoints (/api/media/*).
"""

import mimetypes
import os
import re
from typing import Any, Dict, Iterator, Optional, Tuple

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response, StreamingResponse

from backend.state import BackendState
from core.archive import resolve_collection_cover
from core.utils import extract_embedded_cover

router = APIRouter(prefix="/api/media", tags=["media"])

_AUDIO_MIME_TYPES = {
    ".flac": "audio/flac",
    ".mp3": "audio/mpeg",
    ".opus": "audio/ogg",
    ".ogg": "audio/ogg",
    ".m4a": "audio/mp4",
    ".mp4": "audio/mp4",
    ".wav": "audio/wav",
    ".aac": "audio/aac",
}

_RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$")


def _get_backend(request: Request) -> BackendState:
    return request.app.state.backend


def _resolve_track_file(
    backend: BackendState, track_id: str
) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    row = backend.archive_manager.find_track(spotify_id=track_id)
    if row and row.get("file_path") and os.path.isfile(row["file_path"]):
        return row["file_path"], row

    for it in backend.queue_manager.get_items():
        if it.track.id == track_id and it.output_path and os.path.isfile(it.output_path):
            return it.output_path, {
                "spotify_id": it.track.id,
                "title": it.track.title,
                "artist": it.track.artist_str,
                "album": it.track.album,
                "collection_name": it.track.collection_name,
                "file_path": it.output_path,
            }
    return None, row


def _audio_media_type(file_path: str) -> str:
    ext = os.path.splitext(file_path)[1].lower()
    if ext in _AUDIO_MIME_TYPES:
        return _AUDIO_MIME_TYPES[ext]
    guessed, _ = mimetypes.guess_type(file_path)
    return guessed or "application/octet-stream"


def _detect_image_mime(data: bytes) -> str:
    if data.startswith(b"\x89PNG"):
        return "image/png"
    if data.startswith(b"\xff\xd8"):
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data.startswith(b"GIF8"):
        return "image/gif"
    return "image/jpeg"


def _parse_byte_range(range_header: str, file_size: int) -> Optional[Tuple[int, int]]:
    if file_size <= 0:
        return None
    m = _RANGE_RE.match(range_header.strip())
    if not m:
        return None

    start_s, end_s = m.group(1), m.group(2)
    if not start_s and not end_s:
        return None

    if not start_s:
        suffix_len = int(end_s)
        if suffix_len <= 0:
            return None
        start = max(0, file_size - suffix_len)
        end = file_size - 1
        return start, end

    start = int(start_s)
    if start >= file_size:
        return None

    if not end_s:
        end = file_size - 1
    else:
        end = min(int(end_s), file_size - 1)
        if end < start:
            return None

    return start, end


def _file_chunk_iterator(
    file_path: str, start: int, length: int, chunk_size: int = 65536
) -> Iterator[bytes]:
    with open(file_path, "rb") as fh:
        fh.seek(start)
        remaining = length
        while remaining > 0:
            chunk = fh.read(min(chunk_size, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


@router.head("/audio/{track_id}")
async def head_audio_stream(request: Request, track_id: str):
    backend = _get_backend(request)
    file_path, _ = _resolve_track_file(backend, track_id)
    if not file_path or not os.path.isfile(file_path):
        raise HTTPException(
            status_code=404, detail=f"Audio file for track '{track_id}' not found."
        )

    file_size = os.path.getsize(file_path)
    media_type = _audio_media_type(file_path)
    return Response(
        status_code=200,
        media_type=media_type,
        headers={
            "Accept-Ranges": "bytes",
            "Content-Length": str(file_size),
        },
    )


@router.get("/audio/{track_id}")
async def stream_audio(request: Request, track_id: str):
    backend = _get_backend(request)
    file_path, _ = _resolve_track_file(backend, track_id)
    if not file_path or not os.path.isfile(file_path):
        raise HTTPException(
            status_code=404, detail=f"Audio file for track '{track_id}' not found."
        )

    file_size = os.path.getsize(file_path)
    media_type = _audio_media_type(file_path)
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
        return StreamingResponse(
            _file_chunk_iterator(file_path, start, content_len),
            status_code=206,
            media_type=media_type,
            headers={
                "Content-Range": f"bytes {start}-{end}/{file_size}",
                "Accept-Ranges": "bytes",
                "Content-Length": str(content_len),
            },
        )

    return StreamingResponse(
        _file_chunk_iterator(file_path, 0, file_size),
        status_code=200,
        media_type=media_type,
        headers={
            "Accept-Ranges": "bytes",
            "Content-Length": str(file_size),
        },
    )


@router.get("/cover/track/{track_id}")
async def get_track_cover(request: Request, track_id: str):
    backend = _get_backend(request)
    file_path, row = _resolve_track_file(backend, track_id)
    if not file_path or not os.path.isfile(file_path):
        raise HTTPException(
            status_code=404, detail=f"Cover art for track '{track_id}' not found."
        )

    art_bytes = extract_embedded_cover(file_path)
    if art_bytes:
        return Response(
            content=art_bytes,
            media_type=_detect_image_mime(art_bytes),
            headers={"Cache-Control": "public, max-age=3600"},
        )

    coll_name = (row.get("collection_name") if row else "") or os.path.dirname(file_path)
    cached_cover = resolve_collection_cover(coll_name, file_path)
    if cached_cover and os.path.isfile(cached_cover):
        return FileResponse(
            cached_cover,
            headers={"Cache-Control": "public, max-age=3600"},
        )

    folder = os.path.dirname(file_path)
    if folder and os.path.isdir(folder):
        for cand in ("cover.jpg", "cover.png", "folder.jpg", "artwork.jpg"):
            cand_path = os.path.join(folder, cand)
            if os.path.isfile(cand_path):
                return FileResponse(
                    cand_path,
                    headers={"Cache-Control": "public, max-age=3600"},
                )

    raise HTTPException(
        status_code=404, detail=f"Cover art for track '{track_id}' not found."
    )


@router.get("/cover/collection")
async def get_collection_cover(
    request: Request,
    name: str = Query(default=""),
    playlist_id: Optional[str] = Query(default=None),
):
    backend = _get_backend(request)

    if playlist_id:
        pl = backend.archive_manager.get_saved_playlist(playlist_id)
        if pl:
            local_cover = pl.get("local_cover") or ""
            if local_cover and os.path.isfile(local_cover):
                return FileResponse(
                    local_cover,
                    headers={"Cache-Control": "public, max-age=3600"},
                )
            if not name:
                name = pl.get("name") or ""

    if name.strip():
        cover_path = resolve_collection_cover(name.strip())
        if cover_path and os.path.isfile(cover_path):
            return FileResponse(
                cover_path,
                headers={"Cache-Control": "public, max-age=3600"},
            )

    raise HTTPException(status_code=404, detail="Collection cover art not found.")
