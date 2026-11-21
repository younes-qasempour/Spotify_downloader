"""
Saved Playlists & Auto-Sync management REST endpoints (/api/playlists/*).
"""

import asyncio
import logging
import os
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Body, HTTPException, Query, Request
from pydantic import BaseModel, Field

from backend.state import BackendState
from core.spotify_client import SpotifyClient, TrackMetadata

logger = logging.getLogger("backend.routes.playlists")

router = APIRouter(prefix="/api/playlists", tags=["playlists"])


class SavePlaylistRequest(BaseModel):
    url: str


class UpdatePlaylistRequest(BaseModel):
    name: Optional[str] = None
    spotify_url: Optional[str] = None
    cover_url: Optional[str] = None
    local_cover_path: Optional[str] = None


class AutoSyncToggleRequest(BaseModel):
    enabled: bool


class AutoSyncScheduleRequest(BaseModel):
    on_startup: Optional[bool] = None
    interval_hours: Optional[int] = Field(default=None, ge=0, le=168)
    auto_download_synced_tracks: Optional[bool] = None


class SyncPlaylistRequest(BaseModel):
    auto_download: bool = True


class DownloadBatchRequest(BaseModel):
    batch_size: int = Field(default=50, ge=1, le=5000)


class DownloadSelectedRequest(BaseModel):
    track_ids: List[str] = Field(default_factory=list)
    preferred_engine: Optional[Literal["auto", "melobot", "musilon", "youtube"]] = None
    redownload: bool = False


class UpdatePlaylistTrackRequest(BaseModel):
    title: Optional[str] = None
    artist: Optional[str] = None
    album: Optional[str] = None


def _get_backend(request: Request) -> BackendState:
    return request.app.state.backend


def _require_playlist(backend: BackendState, playlist_id: str) -> Dict[str, Any]:
    pl = backend.archive_manager.get_saved_playlist(playlist_id)
    if not pl:
        raise HTTPException(
            status_code=404, detail=f"Saved playlist '{playlist_id}' not found."
        )
    return pl


def _spotify_status_snapshot(backend: BackendState) -> Dict[str, Any]:
    cid = str(backend.config.get("spotify.client_id", "") or "").strip()
    sec = str(backend.config.get("spotify.client_secret", "") or "").strip()
    has_credentials = bool(cid and sec)
    has_user_auth = bool(backend.spotify_client.has_user_auth(allow_network=False))
    user_name = getattr(backend.spotify_client, "_cached_user_name", None) or ""
    if has_user_auth:
        mode = "connected"
    elif has_credentials:
        mode = "keys_only"
    else:
        mode = "guest"
    return {
        "mode": mode,
        "has_credentials": has_credentials,
        "has_user_auth": has_user_auth,
        "user_name": user_name,
    }


def _auto_sync_schedule_snapshot(backend: BackendState) -> Dict[str, Any]:
    return {
        "on_startup": bool(backend.config.get("playlists.auto_sync_on_startup", True)),
        "interval_hours": int(
            backend.config.get("playlists.auto_sync_interval_hours", 6) or 0
        ),
        "auto_download_synced_tracks": bool(
            backend.config.get("playlists.auto_download_synced_tracks", True)
        ),
    }


def _sort_playlist_tracks(
    rows: List[Dict[str, Any]], sort_by: str
) -> List[Dict[str, Any]]:
    mode = (sort_by or "default").strip().lower()
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
    if mode == "title":
        return sorted(rows, key=lambda r: (r.get("title") or "").strip().lower())
    if mode == "artist":
        return sorted(rows, key=lambda r: (r.get("artist") or "").strip().lower())
    if mode == "duration_asc":
        return sorted(rows, key=lambda r: r.get("duration_ms") or 0)
    if mode == "duration_desc":
        return sorted(rows, key=lambda r: r.get("duration_ms") or 0, reverse=True)
    return rows


def _format_playlist_track_row(row: Dict[str, Any]) -> Dict[str, Any]:
    formatted = dict(row)
    raw_status = (row.get("status") or "pending").strip().lower()
    if raw_status == "downloaded":
        status_pill = "Completed"
    elif raw_status == "queued":
        status_pill = "Queued"
    else:
        status_pill = "Pending"

    file_path = row.get("file_path") or ""
    genre_raw = row.get("genre") or ""
    artist_raw = row.get("artist") or ""

    formatted["status_pill"] = status_pill
    formatted["genres"] = [g.strip() for g in genre_raw.split(";") if g.strip()]
    formatted["artists"] = [a.strip() for a in artist_raw.split(",") if a.strip()]
    formatted["file_exists"] = bool(file_path and os.path.isfile(file_path))
    return formatted


def _row_to_track_metadata(
    row: Dict[str, Any],
    pl_data: Dict[str, Any],
    preferred_engine: Optional[str] = None,
) -> TrackMetadata:
    genre_raw = row.get("genre") or ""
    track_genres = [g.strip() for g in genre_raw.split(";") if g.strip()]
    artists = [a.strip() for a in (row.get("artist") or "").split(",") if a.strip()]
    return TrackMetadata(
        id=row["spotify_id"],
        title=row["title"],
        artists=artists or ["Unknown Artist"],
        album=row.get("album", "") or "",
        duration_ms=row.get("duration_ms", 0) or 0,
        track_number=row.get("track_number", 1) or 1,
        disc_number=row.get("disc_number", 1) or 1,
        isrc=row.get("isrc", "") or "",
        cover_url=row.get("cover_url", "") or "",
        collection_name=pl_data.get("name", "Playlist") if pl_data else "Playlist",
        collection_type="playlist",
        collection_cover_url=(pl_data.get("cover_url", "") or "") if pl_data else "",
        genres=track_genres,
        preferred_engine=preferred_engine,
    )


def _save_playlist_sync(backend: BackendState, url: str) -> Dict[str, Any]:
    parsed = SpotifyClient.parse_url(url)
    if not parsed:
        raise HTTPException(
            status_code=400,
            detail="The provided link is not a recognized Spotify URL.",
        )

    entity_type, entity_id = parsed
    if entity_type not in ("playlist", "album", "collection"):
        raise HTTPException(
            status_code=400,
            detail="Please provide a Spotify Playlist, Album, or Liked Songs link to save tracks to offline storage.",
        )

    backend.spotify_client.update_credentials(
        client_id=backend.config.get("spotify.client_id", ""),
        client_secret=backend.config.get("spotify.client_secret", ""),
    )

    try:
        tracks = backend.spotify_client.resolve(url)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Error resolving Spotify metadata: {exc}",
        ) from exc

    if not tracks:
        raise HTTPException(
            status_code=422,
            detail="No tracks could be found in the provided Spotify link.",
        )

    pl_name = (tracks[0].collection_name if tracks else "") or (
        "Liked Songs" if entity_type == "collection" else "Spotify Playlist"
    )
    pl_cover = (tracks[0].collection_cover_url if tracks else "") or (
        tracks[0].cover_url if tracks else ""
    )
    pl_id = entity_id if entity_type != "collection" else "collection_tracks"

    saved_info = backend.archive_manager.save_playlist(
        name=pl_name,
        spotify_url=url,
        cover_url=pl_cover,
        tracks=tracks,
        playlist_id=pl_id,
    )
    is_guest = getattr(backend.spotify_client, "last_resolution_mode", "api") == "guest"
    was_truncated = getattr(backend.spotify_client, "last_was_truncated", False) or (
        is_guest and len(tracks) == 100
    )
    api_error = getattr(backend.spotify_client, "last_api_error", "")
    owner_name = getattr(backend.spotify_client, "last_owner_name", "")
    auth_user = backend.spotify_client.get_current_user_name()

    backend.events.emit_threadsafe("playlists_updated", {})
    return {
        "playlist": saved_info,
        "was_truncated": bool(was_truncated),
        "is_guest": bool(is_guest),
        "api_error": api_error,
        "owner_name": owner_name,
        "auth_user": auth_user,
    }


def _sync_single_playlist_sync(
    backend: BackendState, playlist_id: str, auto_download: bool
) -> Dict[str, Any]:
    target_pl = _require_playlist(backend, playlist_id)
    pl_url = (target_pl.get("spotify_url") or "").strip()
    if not pl_url:
        raise HTTPException(
            status_code=400,
            detail="No source link recorded for this saved playlist.",
        )

    def on_progress(cur: int, tot: int) -> None:
        backend.events.emit_threadsafe(
            "playlist_sync_progress",
            {"playlist_id": playlist_id, "current": cur, "total": tot},
        )

    try:
        if SpotifyClient.parse_url(pl_url):
            backend.spotify_client.update_credentials(
                client_id=backend.config.get("spotify.client_id", ""),
                client_secret=backend.config.get("spotify.client_secret", ""),
            )
            tracks = backend.spotify_client.resolve(pl_url, progress_callback=on_progress)
        else:
            ytdlp_engine = (
                getattr(backend.audio_engine, "ytdlp", None) or backend.ytdlp_engine
            )
            if not ytdlp_engine:
                from core.ytdlp_engine import YtdlpEngine

                ytdlp_engine = YtdlpEngine(
                    output_dir=backend.config.get("download.output_dir", "")
                )
            tracks = ytdlp_engine.extract_from_url_or_search(pl_url)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail=f"Error syncing playlist tracks: {exc}"
        ) from exc

    if not tracks:
        raise HTTPException(
            status_code=502,
            detail="Could not retrieve songs from online source.",
        )

    res = backend.archive_manager.sync_saved_playlist(playlist_id, tracks)
    added = res.get("added", 0)
    removed = res.get("removed", 0)
    total = res.get("total", 0)
    delta_tracks = res.get("delta_tracks", [])

    queued_count = 0
    if delta_tracks and auto_download:
        backend.archive_manager.mark_saved_tracks_queued(
            playlist_id, [t.id for t in delta_tracks]
        )
        backend.queue_manager.enqueue(delta_tracks)
        backend.queue_manager.start_all()
        queued_count = len(delta_tracks)

    fresh_pl = backend.archive_manager.get_saved_playlist(playlist_id) or target_pl
    pl_name = fresh_pl.get("name", "Playlist")
    liked_songs_tip = bool(
        "liked" in pl_name.lower()
        and "collection" not in pl_url.lower()
        and not delta_tracks
    )

    backend.events.emit_threadsafe(
        "playlist_synced",
        {
            "playlist_id": playlist_id,
            "added": added,
            "removed": removed,
            "total": total,
            "queued_count": queued_count,
        },
    )
    backend.events.emit_threadsafe("playlists_updated", {})

    return {
        "playlist": fresh_pl,
        "added": added,
        "removed": removed,
        "total": total,
        "queued_count": queued_count,
        "liked_songs_tip": liked_songs_tip,
    }


def _sync_all_playlists_sync(backend: BackendState) -> Dict[str, Any]:
    playlists = backend.archive_manager.get_saved_playlists()
    eligible = [p for p in playlists if p.get("spotify_url")]
    if not eligible:
        return {
            "checked_count": 0,
            "total_added": 0,
            "total_removed": 0,
            "errors": [],
        }

    ytdlp_engine = getattr(backend.audio_engine, "ytdlp", None) or backend.ytdlp_engine
    total_added = 0
    total_removed = 0
    errors: List[str] = []

    for pl in eligible:
        pl_id = pl["id"]
        pl_url = pl["spotify_url"]
        try:
            if SpotifyClient.parse_url(pl_url):
                backend.spotify_client.update_credentials(
                    client_id=backend.config.get("spotify.client_id", ""),
                    client_secret=backend.config.get("spotify.client_secret", ""),
                )
                tracks = backend.spotify_client.resolve(pl_url)
            else:
                if not ytdlp_engine:
                    from core.ytdlp_engine import YtdlpEngine

                    ytdlp_engine = YtdlpEngine(
                        output_dir=backend.config.get("download.output_dir", "")
                    )
                tracks = ytdlp_engine.extract_from_url_or_search(pl_url)
            if tracks:
                res = backend.archive_manager.sync_saved_playlist(pl_id, tracks)
                total_added += res.get("added", 0)
                total_removed += res.get("removed", 0)
        except Exception as exc:
            logger.debug(f"Sync error on playlist {pl_id}: {exc}")
            errors.append(f"{pl_id}: {exc}")

    backend.events.emit_threadsafe("playlists_updated", {})
    return {
        "checked_count": len(eligible),
        "total_added": total_added,
        "total_removed": total_removed,
        "errors": errors,
    }


@router.get("")
async def list_playlists(request: Request, search: str = Query(default="")):
    backend = _get_backend(request)
    all_playlists = backend.archive_manager.get_saved_playlists()

    tot_tracks = sum(p.get("total_tracks", 0) for p in all_playlists)
    tot_down = sum(p.get("downloaded_count", 0) for p in all_playlists)
    tot_pend = max(0, tot_tracks - tot_down)

    q = search.strip().lower()
    filtered = (
        [p for p in all_playlists if q in (p.get("name") or "").lower()]
        if q
        else all_playlists
    )

    return {
        "playlists": filtered,
        "summary": {
            "total_playlists": len(all_playlists),
            "total_tracks": tot_tracks,
            "downloaded_count": tot_down,
            "pending_count": tot_pend,
        },
        "auto_sync_schedule": _auto_sync_schedule_snapshot(backend),
        "spotify_status": _spotify_status_snapshot(backend),
    }


@router.post("")
async def save_playlist(request: Request, body: SavePlaylistRequest):
    url = body.url.strip()
    if not url:
        raise HTTPException(
            status_code=400, detail="Please paste a valid Spotify playlist URL."
        )
    backend = _get_backend(request)
    return await asyncio.to_thread(_save_playlist_sync, backend, url)


@router.post("/sync-all")
async def sync_all_playlists(request: Request):
    backend = _get_backend(request)
    return await asyncio.to_thread(_sync_all_playlists_sync, backend)


@router.get("/auto-sync/schedule")
async def get_auto_sync_schedule(request: Request):
    backend = _get_backend(request)
    return _auto_sync_schedule_snapshot(backend)


@router.put("/auto-sync/schedule")
async def update_auto_sync_schedule(
    request: Request, body: AutoSyncScheduleRequest
):
    backend = _get_backend(request)
    if body.on_startup is not None:
        backend.config.set("playlists.auto_sync_on_startup", body.on_startup)
    if body.interval_hours is not None:
        backend.config.set("playlists.auto_sync_interval_hours", body.interval_hours)
    if body.auto_download_synced_tracks is not None:
        backend.config.set(
            "playlists.auto_download_synced_tracks", body.auto_download_synced_tracks
        )
    backend.reschedule_auto_sync()
    return _auto_sync_schedule_snapshot(backend)


@router.post("/auto-sync/run")
async def run_watched_auto_sync_now(request: Request):
    backend = _get_backend(request)
    return await asyncio.to_thread(backend.run_watched_playlists_sync_sync, False)


@router.get("/{playlist_id}")
async def get_playlist_detail(
    request: Request,
    playlist_id: str,
    search: str = Query(default=""),
    status: str = Query(default="all"),
    genre: str = Query(default=""),
    sort: str = Query(default="default"),
    reconcile: bool = Query(default=True),
):
    backend = _get_backend(request)
    pl_data = _require_playlist(backend, playlist_id)

    if reconcile:
        try:
            backend.archive_manager.reconcile_playlist_files(playlist_id)
            fresh = backend.archive_manager.get_saved_playlist(playlist_id)
            if fresh:
                pl_data = fresh
        except Exception as exc:
            logger.debug(f"File reconciliation skipped for {playlist_id}: {exc}")

    all_tracks = backend.archive_manager.get_saved_playlist_tracks(playlist_id)
    genres_set = set()
    for t in all_tracks:
        for g in (t.get("genre") or "").split(";"):
            clean_g = g.strip()
            if clean_g:
                genres_set.add(clean_g)

    norm_status = status.strip().lower()
    status_filter: Optional[str] = (
        None if norm_status in ("", "all") else norm_status
    )
    genre_filter = (
        "" if genre.strip().lower() in ("", "all genres") else genre.strip()
    )

    rows = backend.archive_manager.get_saved_playlist_tracks(
        playlist_id,
        status=status_filter,
        search_query=search.strip(),
        genre_filter=genre_filter,
    )
    rows = _sort_playlist_tracks(rows, sort)
    formatted_tracks = [_format_playlist_track_row(r) for r in rows]

    return {
        "playlist": pl_data,
        "tracks": formatted_tracks,
        "available_genres": sorted(genres_set),
    }


@router.patch("/{playlist_id}")
async def update_playlist(
    request: Request, playlist_id: str, body: UpdatePlaylistRequest
):
    backend = _get_backend(request)
    _require_playlist(backend, playlist_id)

    new_cover = body.cover_url
    local_cover = body.local_cover_path
    if new_cover and os.path.isfile(new_cover) and not local_cover:
        local_cover = new_cover
        new_cover = ""

    ok = backend.archive_manager.update_saved_playlist(
        playlist_id=playlist_id,
        name=body.name,
        cover_url=new_cover,
        spotify_url=body.spotify_url,
        local_cover_path=local_cover,
    )
    if not ok:
        raise HTTPException(
            status_code=500, detail=f"Failed to update playlist '{playlist_id}'."
        )

    fresh = backend.archive_manager.get_saved_playlist(playlist_id)
    backend.events.emit_threadsafe("playlists_updated", {})
    return {"updated": True, "playlist": fresh}


@router.delete("/{playlist_id}")
async def delete_playlist(request: Request, playlist_id: str):
    backend = _get_backend(request)
    _require_playlist(backend, playlist_id)
    ok = backend.archive_manager.delete_saved_playlist(playlist_id)
    if not ok:
        raise HTTPException(
            status_code=500, detail=f"Failed to delete playlist '{playlist_id}'."
        )
    backend.events.emit_threadsafe("playlists_updated", {})
    return {"deleted": True, "playlist_id": playlist_id}


@router.put("/{playlist_id}/auto-sync")
async def toggle_playlist_auto_sync(
    request: Request, playlist_id: str, body: AutoSyncToggleRequest
):
    backend = _get_backend(request)
    _require_playlist(backend, playlist_id)
    backend.archive_manager.set_playlist_auto_sync(playlist_id, body.enabled)
    fresh = backend.archive_manager.get_saved_playlist(playlist_id)
    backend.events.emit_threadsafe("playlists_updated", {})
    return {"playlist": fresh, "auto_sync": body.enabled}


@router.post("/{playlist_id}/sync")
async def sync_single_playlist(
    request: Request,
    playlist_id: str,
    body: Optional[SyncPlaylistRequest] = Body(default=None),
):
    backend = _get_backend(request)
    auto_download = body.auto_download if body is not None else True
    return await asyncio.to_thread(
        _sync_single_playlist_sync, backend, playlist_id, auto_download
    )


@router.post("/{playlist_id}/download-batch")
async def download_playlist_batch(
    request: Request, playlist_id: str, body: DownloadBatchRequest
):
    backend = _get_backend(request)
    pl_data = _require_playlist(backend, playlist_id)

    pending_rows = backend.archive_manager.get_saved_playlist_tracks(
        playlist_id, status="pending", limit=body.batch_size
    )
    if not pending_rows:
        return {
            "queued_count": 0,
            "requested_batch_size": body.batch_size,
            "track_ids": [],
            "playlist": pl_data,
        }

    tracks = [_row_to_track_metadata(r, pl_data) for r in pending_rows]
    track_ids = [t.id for t in tracks]

    backend.archive_manager.mark_saved_tracks_queued(playlist_id, track_ids)
    backend.queue_manager.enqueue(tracks)
    backend.queue_manager.start()

    fresh = backend.archive_manager.get_saved_playlist(playlist_id) or pl_data
    backend.events.emit_threadsafe("playlists_updated", {})
    return {
        "queued_count": len(tracks),
        "requested_batch_size": body.batch_size,
        "track_ids": track_ids,
        "playlist": fresh,
    }


@router.post("/{playlist_id}/download-selected")
async def download_selected_playlist_tracks(
    request: Request, playlist_id: str, body: DownloadSelectedRequest
):
    backend = _get_backend(request)
    pl_data = _require_playlist(backend, playlist_id)

    if not body.track_ids:
        raise HTTPException(
            status_code=400, detail="Please select at least one track ID to download."
        )

    rows = backend.archive_manager.get_saved_playlist_tracks(playlist_id)
    rows_by_id = {r["spotify_id"]: r for r in rows}

    tracks_to_queue: List[TrackMetadata] = []
    queued_ids: List[str] = []
    seen = set()

    for tid in body.track_ids:
        if tid in seen:
            continue
        seen.add(tid)
        row = rows_by_id.get(tid)
        if not row:
            continue

        if body.redownload:
            file_to_del = row.get("file_path") or ""
            if not file_to_del:
                archived = backend.archive_manager.find_track(spotify_id=tid)
                if archived:
                    file_to_del = archived.get("file_path", "")
            if file_to_del and os.path.exists(file_to_del):
                try:
                    os.remove(file_to_del)
                except Exception as exc:
                    logger.warning(f"Failed to delete old file {file_to_del}: {exc}")
            backend.archive_manager.remove_downloaded_track(tid, playlist_id=playlist_id)
        elif row.get("status") == "downloaded":
            continue

        pref_engine = body.preferred_engine or ("auto" if body.redownload else None)
        tracks_to_queue.append(_row_to_track_metadata(row, pl_data, preferred_engine=pref_engine))
        queued_ids.append(tid)

    if tracks_to_queue:
        backend.archive_manager.mark_saved_tracks_queued(playlist_id, queued_ids)
        backend.queue_manager.enqueue(tracks_to_queue)
        backend.queue_manager.start_all()
        backend.events.emit_threadsafe("playlists_updated", {})

    fresh = backend.archive_manager.get_saved_playlist(playlist_id) or pl_data
    return {
        "queued_count": len(tracks_to_queue),
        "track_ids": queued_ids,
        "playlist": fresh,
    }


@router.post("/{playlist_id}/reset-queued")
async def reset_queued_playlist_tracks(request: Request, playlist_id: str):
    backend = _get_backend(request)
    _require_playlist(backend, playlist_id)
    reverted = backend.archive_manager.revert_queued_tracks_to_pending(playlist_id)
    fresh = backend.archive_manager.get_saved_playlist(playlist_id)
    backend.events.emit_threadsafe("playlists_updated", {})
    return {"reverted_count": reverted, "playlist": fresh}


@router.patch("/{playlist_id}/tracks/{track_id}")
async def update_playlist_track(
    request: Request,
    playlist_id: str,
    track_id: str,
    body: UpdatePlaylistTrackRequest,
):
    backend = _get_backend(request)
    _require_playlist(backend, playlist_id)
    ok = backend.archive_manager.update_saved_playlist_track(
        playlist_id,
        track_id,
        title=body.title,
        artist=body.artist,
        album=body.album,
    )
    if not ok:
        raise HTTPException(
            status_code=404,
            detail=f"Track '{track_id}' not found in playlist '{playlist_id}'.",
        )
    backend.events.emit_threadsafe("playlists_updated", {})
    return {"updated": True, "playlist_id": playlist_id, "track_id": track_id}


@router.post("/{playlist_id}/tracks/{track_id}/reset")
async def reset_playlist_track_status(
    request: Request, playlist_id: str, track_id: str
):
    backend = _get_backend(request)
    _require_playlist(backend, playlist_id)
    rows = backend.archive_manager.get_saved_playlist_tracks(playlist_id)
    if not any(r["spotify_id"] == track_id for r in rows):
        raise HTTPException(
            status_code=404,
            detail=f"Track '{track_id}' not found in playlist '{playlist_id}'.",
        )
    backend.archive_manager.update_saved_track_status(playlist_id, track_id, "pending")
    backend.events.emit_threadsafe("playlists_updated", {})
    return {"reset": True, "playlist_id": playlist_id, "track_id": track_id}


@router.post("/{playlist_id}/tracks/{track_id}/cancel")
async def cancel_playlist_track(
    request: Request, playlist_id: str, track_id: str
):
    backend = _get_backend(request)
    _require_playlist(backend, playlist_id)
    backend.queue_manager.cancel_track(track_id)
    backend.archive_manager.update_saved_track_status(playlist_id, track_id, "pending")
    backend.events.emit_threadsafe("playlists_updated", {})
    return {"cancelled": True, "playlist_id": playlist_id, "track_id": track_id}


@router.delete("/{playlist_id}/tracks/{track_id}/file")
async def delete_playlist_track_file(
    request: Request, playlist_id: str, track_id: str
):
    backend = _get_backend(request)
    _require_playlist(backend, playlist_id)
    rows = backend.archive_manager.get_saved_playlist_tracks(playlist_id)
    row = next((r for r in rows if r["spotify_id"] == track_id), None)
    if not row:
        raise HTTPException(
            status_code=404,
            detail=f"Track '{track_id}' not found in playlist '{playlist_id}'.",
        )

    file_to_del = row.get("file_path") or ""
    if not file_to_del:
        archived = backend.archive_manager.find_track(spotify_id=track_id)
        if archived:
            file_to_del = archived.get("file_path", "")

    file_removed = False
    if file_to_del and os.path.exists(file_to_del):
        try:
            os.remove(file_to_del)
            file_removed = True
        except Exception as exc:
            logger.warning(f"Failed to delete file {file_to_del}: {exc}")

    backend.archive_manager.remove_downloaded_track(track_id, playlist_id=playlist_id)
    fresh = backend.archive_manager.get_saved_playlist(playlist_id)
    backend.events.emit_threadsafe("playlists_updated", {})
    backend.events.emit_threadsafe("library_updated", {})
    return {"deleted": True, "file_removed": file_removed, "playlist": fresh}
