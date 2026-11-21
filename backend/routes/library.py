"""
Downloaded Library, Collections, Rescan & Track Management REST endpoints (/api/library/*).
"""

import asyncio
import logging
import os
from typing import Any, Dict, List, Literal
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from backend.state import BackendState
from core.archive import ArchiveManager
from core.spotify_client import TrackMetadata

logger = logging.getLogger("backend.routes.library")

router = APIRouter(prefix="/api/library", tags=["library"])


class RenameCollectionRequest(BaseModel):
    old_name: str
    new_name: str
    collection_type: Literal["playlist", "album"] = "playlist"


class RedownloadTrackRequest(BaseModel):
    preferred_engine: Literal["auto", "melobot", "musilon", "youtube"] = "auto"


def _get_backend(request: Request) -> BackendState:
    return request.app.state.backend


def _sort_library_tracks(
    rows: List[Dict[str, Any]], sort_by: str
) -> List[Dict[str, Any]]:
    mode = (sort_by or "title").strip().lower()
    if mode == "track_number":
        return sorted(
            rows,
            key=lambda r: (
                r.get("disc_number", 1) or 1,
                r.get("track_number")
                if (r.get("track_number") is not None and r.get("track_number") > 0)
                else 9999,
                (r.get("title") or "").strip().lower(),
            ),
        )
    if mode == "artist":
        return sorted(rows, key=lambda r: (r.get("artist") or "").strip().lower())
    if mode == "duration_asc":
        return sorted(rows, key=lambda r: r.get("duration_ms") or 0)
    if mode == "duration_desc":
        return sorted(rows, key=lambda r: r.get("duration_ms") or 0, reverse=True)
    if mode == "recent":
        return sorted(
            rows, key=lambda r: r.get("downloaded_at") or "", reverse=True
        )
    if mode == "genre":
        return sorted(
            rows,
            key=lambda r: (
                0 if (r.get("genre") or "").strip() else 1,
                (r.get("genre") or "").strip().lower(),
                (r.get("artist") or "").strip().lower(),
                (r.get("title") or "").strip().lower(),
            ),
        )
    return sorted(rows, key=lambda r: (r.get("title") or "").strip().lower())


def _sort_collections(
    items: List[Dict[str, Any]], sort_by: str, is_album: bool = False
) -> List[Dict[str, Any]]:
    mode = (sort_by or "title").strip().lower()
    if mode == "genre":
        if is_album:
            return sorted(
                items,
                key=lambda a: (
                    0 if a.get("genre") else 1,
                    (a.get("genre") or "").strip().lower(),
                    (a.get("artist") or "").strip().lower(),
                    a["name"].strip().lower(),
                ),
            )
        return sorted(
            items,
            key=lambda p: (
                0 if p.get("genre") else 1,
                (p.get("genre") or "").strip().lower(),
                p["name"].strip().lower(),
            ),
        )
    if mode == "artist" and is_album:
        return sorted(items, key=lambda a: (a.get("artist") or "").strip().lower())
    if mode == "track_count":
        return sorted(
            items, key=lambda x: x.get("track_count") or 0, reverse=True
        )
    if mode in ("size_asc", "duration_asc"):
        return sorted(items, key=lambda x: x.get("total_size_bytes") or 0)
    if mode in ("size_desc", "duration_desc"):
        return sorted(
            items, key=lambda x: x.get("total_size_bytes") or 0, reverse=True
        )
    if mode == "recent":
        return sorted(
            items, key=lambda x: x.get("latest_download") or "", reverse=True
        )
    return sorted(items, key=lambda x: x["name"].strip().lower())


def _format_library_track(
    row: Dict[str, Any], archive: ArchiveManager
) -> Dict[str, Any]:
    formatted = dict(row)
    spotify_id = row.get("spotify_id") or ""
    file_path = row.get("file_path") or ""
    q_badge = row.get("quality_badge") or ""
    s_type = row.get("source_type") or ""

    if not q_badge and file_path:
        q_inf, s_inf = archive.infer_badge_from_file(file_path)
        q_badge = q_inf or "FLAC 16"
        s_type = s_type or s_inf or "Musilon"
    elif not q_badge:
        q_badge = "FLAC 16"
        s_type = s_type or "Musilon"

    artist_raw = row.get("artist") or ""
    genre_raw = row.get("genre") or ""

    formatted["quality_badge"] = q_badge
    formatted["source_type"] = s_type
    formatted["artists"] = [a.strip() for a in artist_raw.split(",") if a.strip()]
    formatted["genres"] = [g.strip() for g in genre_raw.split(";") if g.strip()]
    formatted["file_exists"] = bool(file_path and os.path.isfile(file_path))
    formatted["audio_url"] = f"/api/media/audio/{spotify_id}"
    formatted["cover_url_local"] = f"/api/media/cover/track/{spotify_id}"
    return formatted


@router.get("/stats")
async def get_library_stats(request: Request):
    backend = _get_backend(request)
    stats = backend.archive_manager.get_library_stats()
    return {
        **stats,
        "available_genres": backend.archive_manager.get_all_genres(),
    }


@router.get("/tracks")
async def list_library_tracks(
    request: Request,
    search: str = Query(default=""),
    genre: str = Query(default=""),
    sort: str = Query(default="title"),
):
    backend = _get_backend(request)
    archive = backend.archive_manager
    genre_filter = "" if genre.strip().lower() in ("", "all genres") else genre.strip()
    rows = archive.get_all_tracks(search.strip(), genre_filter=genre_filter)
    rows = _sort_library_tracks(rows, sort)
    formatted = [_format_library_track(r, archive) for r in rows]
    return {
        "tracks": formatted,
        "total": len(formatted),
        "stats": archive.get_library_stats(),
        "available_genres": archive.get_all_genres(),
    }


@router.get("/playlists")
async def list_library_playlists(
    request: Request,
    search: str = Query(default=""),
    genre: str = Query(default=""),
    sort: str = Query(default="title"),
):
    backend = _get_backend(request)
    genre_filter = "" if genre.strip().lower() in ("", "all genres") else genre.strip()
    items = backend.archive_manager.get_playlists(
        search.strip(), genre_filter=genre_filter
    )
    items = _sort_collections(items, sort, is_album=False)
    for it in items:
        it["cover_url_local"] = (
            f"/api/media/cover/collection?name={quote(it['name'], safe='')}"
        )
    return {"playlists": items, "total": len(items)}


@router.get("/albums")
async def list_library_albums(
    request: Request,
    search: str = Query(default=""),
    genre: str = Query(default=""),
    sort: str = Query(default="title"),
):
    backend = _get_backend(request)
    genre_filter = "" if genre.strip().lower() in ("", "all genres") else genre.strip()
    items = backend.archive_manager.get_albums(
        search.strip(), genre_filter=genre_filter
    )
    items = _sort_collections(items, sort, is_album=True)
    for it in items:
        it["cover_url_local"] = (
            f"/api/media/cover/collection?name={quote(it['name'], safe='')}"
        )
    return {"albums": items, "total": len(items)}


@router.get("/collections/tracks")
async def list_collection_tracks(
    request: Request,
    name: str = Query(...),
    type: Literal["playlist", "album"] = Query(default="playlist"),
    search: str = Query(default=""),
    genre: str = Query(default=""),
    sort: str = Query(default=""),
):
    backend = _get_backend(request)
    archive = backend.archive_manager
    genre_filter = "" if genre.strip().lower() in ("", "all genres") else genre.strip()
    rows = archive.get_collection_tracks(name, type, genre_filter=genre_filter)

    q = search.strip().lower()
    if q:
        rows = [
            r
            for r in rows
            if q in (r.get("title") or "").lower()
            or q in (r.get("artist") or "").lower()
            or q in (r.get("album") or "").lower()
        ]

    effective_sort = sort.strip() or ("track_number" if type == "album" else "title")
    rows = _sort_library_tracks(rows, effective_sort)
    formatted = [_format_library_track(r, archive) for r in rows]
    return {
        "name": name,
        "collection_type": type,
        "tracks": formatted,
        "total": len(formatted),
    }


@router.patch("/collections/rename")
async def rename_library_collection(
    request: Request, body: RenameCollectionRequest
):
    old_name = body.old_name.strip()
    new_name = body.new_name.strip()
    if not old_name or not new_name or old_name == new_name:
        raise HTTPException(
            status_code=400,
            detail="Both old_name and new_name must be non-empty and distinct.",
        )

    backend = _get_backend(request)
    ok = backend.archive_manager.rename_collection(
        old_name, new_name, collection_type=body.collection_type
    )
    if not ok:
        raise HTTPException(
            status_code=404,
            detail=f"Could not rename collection '{old_name}'.",
        )

    backend.events.emit_threadsafe("library_updated", {})
    backend.events.emit_threadsafe("playlists_updated", {})
    return {
        "renamed": True,
        "old_name": old_name,
        "new_name": new_name,
        "collection_type": body.collection_type,
    }


@router.post("/rescan")
async def rescan_library_directory(request: Request):
    backend = _get_backend(request)
    out_dir = backend.config.get("download.output_dir", "downloads")
    if not out_dir or not os.path.isdir(out_dir):
        raise HTTPException(
            status_code=400,
            detail=f"Download directory does not exist: {out_dir}",
        )

    indexed = await asyncio.to_thread(
        backend.archive_manager.scan_and_index_directory, out_dir
    )
    backend.events.emit_threadsafe("library_updated", {"indexed": indexed})
    return {
        "indexed": indexed,
        "directory": out_dir,
        "stats": backend.archive_manager.get_library_stats(),
    }


@router.get("/tracks/{track_id}")
async def get_library_track(request: Request, track_id: str):
    backend = _get_backend(request)
    row = backend.archive_manager.find_track(spotify_id=track_id)
    if not row:
        raise HTTPException(
            status_code=404, detail=f"Track '{track_id}' not found in library."
        )
    return {"track": _format_library_track(row, backend.archive_manager)}


@router.delete("/tracks/{track_id}")
async def delete_library_track(
    request: Request,
    track_id: str,
    delete_file: bool = Query(default=False),
):
    backend = _get_backend(request)
    row = backend.archive_manager.find_track(spotify_id=track_id)
    if not row:
        raise HTTPException(
            status_code=404, detail=f"Track '{track_id}' not found in library."
        )

    file_removed = False
    file_path = row.get("file_path") or ""
    if delete_file and file_path and os.path.exists(file_path):
        try:
            os.remove(file_path)
            file_removed = True
        except Exception as exc:
            logger.warning(f"Failed to delete file {file_path}: {exc}")

    backend.archive_manager.remove_downloaded_track(track_id)
    if file_removed or (delete_file and file_path and not os.path.exists(file_path)):
        backend.archive_manager.remove_downloaded_tracks_by_path(file_path)
    backend.events.emit_threadsafe("library_updated", {})
    backend.events.emit_threadsafe("playlists_updated", {})
    return {
        "deleted": True,
        "track_id": track_id,
        "file_removed": file_removed,
    }


@router.post("/tracks/{track_id}/redownload")
async def redownload_library_track(
    request: Request, track_id: str, body: RedownloadTrackRequest
):
    backend = _get_backend(request)
    row = backend.archive_manager.find_track(spotify_id=track_id)
    if not row:
        raise HTTPException(
            status_code=404, detail=f"Track '{track_id}' not found in library."
        )

    file_path = row.get("file_path") or ""
    if file_path and os.path.exists(file_path):
        try:
            os.remove(file_path)
        except Exception as exc:
            logger.warning(f"Failed to delete old file {file_path}: {exc}")

    backend.archive_manager.remove_downloaded_track(track_id)

    artists = [
        a.strip() for a in (row.get("artist") or "").split(",") if a.strip()
    ] or ["Unknown Artist"]
    genres = [
        g.strip() for g in (row.get("genre") or "").split(";") if g.strip()
    ]
    track = TrackMetadata(
        id=row.get("spotify_id") or track_id,
        title=row.get("title") or "Unknown Track",
        artists=artists,
        album=row.get("album") or "",
        duration_ms=row.get("duration_ms") or 0,
        track_number=row.get("track_number") or 1,
        disc_number=row.get("disc_number") or 1,
        isrc=row.get("isrc") or "",
        collection_name=row.get("collection_name") or "Singles",
        collection_type=row.get("collection_type") or "track",
        genres=genres,
        preferred_engine=body.preferred_engine,
    )

    backend.queue_manager.enqueue([track])
    backend.queue_manager.start_all()
    backend.events.emit_threadsafe("library_updated", {})
    backend.events.emit_threadsafe("playlists_updated", {})
    return {
        "queued": True,
        "track_id": track_id,
        "preferred_engine": body.preferred_engine,
    }
