"""
Queue & Download management REST endpoints (/api/queue/*).
"""

import asyncio
import logging
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from backend.serializers import serialize_queue_item
from backend.state import BackendState
from core.queue_manager import QueueItem
from core.spotify_client import SpotifyClient, TrackMetadata

logger = logging.getLogger("backend.routes.queue")

router = APIRouter(prefix="/api/queue", tags=["queue"])

_ACTIVE_STATUSES = {
    "resolving",
    "resolving (ytm fallback)",
    "downloading",
    "tagging",
    "fetching lyrics",
}
_QUEUED_STATUSES = {"queued", "paused"}
_FAILED_STATUSES = {"failed", "cancelled", "stopped"}


class EnqueueRequest(BaseModel):
    input: Optional[str] = None
    urls: Optional[List[str]] = None
    auto_start: bool = False
    preferred_engine: Optional[str] = None


class TrackIdsRequest(BaseModel):
    track_ids: List[str] = Field(default_factory=list)


class MusilonDecisionRequest(BaseModel):
    action: Literal["continue_youtube", "stop"]


def _get_backend(request: Request) -> BackendState:
    return request.app.state.backend


def _is_active_status(status: str) -> bool:
    s = status.strip().lower()
    return s in _ACTIVE_STATUSES or s.startswith("resolving")


def _compute_queue_stats(items: List[QueueItem]) -> Dict[str, Any]:
    total = len(items)
    active = sum(1 for it in items if _is_active_status(it.status))
    queued = sum(1 for it in items if it.status.strip().lower() in _QUEUED_STATUSES)
    completed = sum(1 for it in items if it.status.strip().lower() == "completed")
    failed = sum(1 for it in items if it.status.strip().lower() in _FAILED_STATUSES)
    overall_progress_percent = int((completed / total) * 100) if total > 0 else 0
    return {
        "total": total,
        "active": active,
        "queued": queued,
        "completed": completed,
        "failed": failed,
        "overall_progress_percent": overall_progress_percent,
    }


def _filter_queue_items(
    items: List[QueueItem], query: str = "", status: str = "all"
) -> List[QueueItem]:
    q = query.strip().lower()
    status_f = status.strip().lower()

    filtered: List[QueueItem] = []
    for it in items:
        if status_f and status_f != "all":
            s = it.status.strip().lower()
            if status_f in ("active", "downloading") and not _is_active_status(it.status):
                continue
            elif status_f in ("queued", "pending") and s not in _QUEUED_STATUSES:
                continue
            elif status_f == "completed" and s != "completed":
                continue
            elif status_f in ("failed", "stopped") and s not in _FAILED_STATUSES:
                continue

        if q:
            title = (it.track.title or "").lower()
            artist = (it.track.artist_str or "").lower()
            album = (it.track.album or "").lower()
            if q not in title and q not in artist and q not in album:
                continue

        filtered.append(it)
    return filtered


def _queue_state_payload(backend: BackendState) -> Dict[str, Any]:
    return {
        "paused": backend.queue_manager.is_paused(),
        "running": bool(getattr(backend.queue_manager, "_running", False)),
    }


def _resolve_and_enqueue_sync(
    backend: BackendState,
    raw_targets: List[str],
    auto_start: bool,
    preferred_engine: Optional[str],
) -> Dict[str, Any]:
    backend.spotify_client.update_credentials(
        client_id=backend.config.get("spotify.client_id", ""),
        client_secret=backend.config.get("spotify.client_secret", ""),
    )

    all_resolved_tracks: List[TrackMetadata] = []
    errors: List[str] = []
    saved_playlists_updated = False

    ytdlp_engine = getattr(backend.audio_engine, "ytdlp", None) or backend.ytdlp_engine
    if not ytdlp_engine:
        from core.ytdlp_engine import YtdlpEngine

        ytdlp_engine = YtdlpEngine(
            output_dir=backend.config.get("download.output_dir", "")
        )

    for target_url in raw_targets:
        parsed = SpotifyClient.parse_url(target_url)
        if parsed:
            entity_type, entity_id = parsed
            try:
                tracks = backend.spotify_client.resolve(target_url)
                if tracks and entity_type in ("playlist", "album"):
                    try:
                        pl_name = tracks[0].collection_name or (
                            "Spotify Playlist"
                            if entity_type == "playlist"
                            else "Spotify Album"
                        )
                        pl_cover = (
                            getattr(tracks[0], "collection_cover_url", "")
                            or tracks[0].cover_url
                            or ""
                        )
                        backend.archive_manager.save_playlist(
                            name=pl_name,
                            spotify_url=target_url,
                            cover_url=pl_cover,
                            tracks=tracks,
                            playlist_id=entity_id,
                        )
                        saved_playlists_updated = True
                    except Exception:
                        pass
                if tracks:
                    all_resolved_tracks.extend(tracks)
            except Exception as exc:
                errors.append(f"{target_url}: {exc}")
        else:
            try:
                tracks = ytdlp_engine.extract_from_url_or_search(target_url)
                if tracks and any(
                    getattr(t, "collection_type", "") == "playlist" for t in tracks
                ):
                    try:
                        pl_name = tracks[0].collection_name or "YouTube Playlist"
                        pl_cover = (
                            getattr(tracks[0], "collection_cover_url", "")
                            or tracks[0].cover_url
                            or ""
                        )
                        backend.archive_manager.save_playlist(
                            name=pl_name,
                            spotify_url=target_url
                            if target_url.startswith("http")
                            else "",
                            cover_url=pl_cover,
                            tracks=tracks,
                            playlist_id=target_url
                            if target_url.startswith("http")
                            else "",
                        )
                        saved_playlists_updated = True
                    except Exception:
                        pass
                if tracks:
                    all_resolved_tracks.extend(tracks)
            except Exception as exc:
                errors.append(f"{target_url}: {exc}")

    if preferred_engine:
        for track in all_resolved_tracks:
            track.preferred_engine = preferred_engine

    if not all_resolved_tracks and errors:
        raise HTTPException(status_code=502, detail="; ".join(errors))

    if all_resolved_tracks:
        backend.queue_manager.enqueue(all_resolved_tracks)
        if auto_start:
            backend.queue_manager.start_all()
        if saved_playlists_updated:
            backend.events.emit_threadsafe("playlists_updated", {})

    has_spotify = any(
        not getattr(t, "id", "").startswith("yt_") for t in all_resolved_tracks
    )
    truncated_guest_limit = bool(
        has_spotify
        and (
            getattr(backend.spotify_client, "last_was_truncated", False)
            or (
                not backend.spotify_client.has_credentials()
                and len(all_resolved_tracks) == 100
            )
        )
    )

    items_by_id = {it.track.id: it for it in backend.queue_manager.get_items()}
    seen_ids = set()
    serialized_items: List[Dict[str, Any]] = []
    for t in all_resolved_tracks:
        if t.id in seen_ids:
            continue
        seen_ids.add(t.id)
        item = items_by_id.get(t.id)
        if item is not None:
            serialized_items.append(serialize_queue_item(item))

    return {
        "enqueued_count": len(all_resolved_tracks),
        "items": serialized_items,
        "errors": errors,
        "truncated_guest_limit": truncated_guest_limit,
        "saved_playlists_updated": saved_playlists_updated,
        "started": bool(auto_start and all_resolved_tracks),
    }


@router.get("")
async def get_queue(
    request: Request,
    query: str = Query(default=""),
    status: str = Query(default="all"),
):
    backend = _get_backend(request)
    all_items = backend.queue_manager.get_items()
    filtered = _filter_queue_items(all_items, query=query, status=status)
    return {
        "items": [serialize_queue_item(it) for it in filtered],
        "stats": _compute_queue_stats(all_items),
        "paused": backend.queue_manager.is_paused(),
        "running": bool(getattr(backend.queue_manager, "_running", False)),
        "pending_prompts": backend.get_pending_musilon_prompts(),
    }


@router.post("/enqueue")
async def enqueue_tracks(request: Request, body: EnqueueRequest):
    raw_targets: List[str] = []
    if body.input:
        raw_targets.extend(
            line.strip() for line in body.input.splitlines() if line.strip()
        )
    if body.urls:
        raw_targets.extend(u.strip() for u in body.urls if u and u.strip())

    if not raw_targets:
        raise HTTPException(
            status_code=400,
            detail="Please provide at least one Spotify/YouTube link or search query.",
        )

    backend = _get_backend(request)
    return await asyncio.to_thread(
        _resolve_and_enqueue_sync,
        backend,
        raw_targets,
        body.auto_start,
        body.preferred_engine,
    )


@router.post("/start")
async def start_queue(request: Request):
    backend = _get_backend(request)
    started = backend.queue_manager.start_all()
    state_payload = _queue_state_payload(backend)
    backend.events.emit_threadsafe("queue_state_changed", state_payload)
    return {"started_count": started, **state_payload}


@router.post("/pause")
async def pause_queue(request: Request):
    backend = _get_backend(request)
    backend.queue_manager.pause()
    state_payload = _queue_state_payload(backend)
    backend.events.emit_threadsafe("queue_state_changed", state_payload)
    return state_payload


@router.post("/resume")
async def resume_queue(request: Request):
    backend = _get_backend(request)
    backend.queue_manager.resume()
    state_payload = _queue_state_payload(backend)
    backend.events.emit_threadsafe("queue_state_changed", state_payload)
    return state_payload


@router.post("/stop")
async def stop_queue(request: Request):
    backend = _get_backend(request)
    backend.queue_manager.stop()
    state_payload = _queue_state_payload(backend)
    backend.events.emit_threadsafe("queue_state_changed", state_payload)
    return {"stopped": True, **state_payload}


@router.post("/retry-failed")
async def retry_failed_queue(request: Request):
    backend = _get_backend(request)
    retried = backend.queue_manager.retry_failed()
    backend.events.emit_threadsafe("queue_state_changed", _queue_state_payload(backend))
    return {"retried_count": retried}


@router.post("/clear-completed")
async def clear_completed_queue(request: Request):
    backend = _get_backend(request)
    backend.queue_manager.clear_completed()
    backend.events.emit_threadsafe("queue_cleared", {"scope": "completed"})
    return {
        "cleared": True,
        "remaining_count": len(backend.queue_manager.get_items()),
    }


@router.post("/tracks/retry")
async def retry_tracks_batch(request: Request, body: TrackIdsRequest):
    backend = _get_backend(request)
    items_by_id = {it.track.id: it for it in backend.queue_manager.get_items()}
    retried_ids: List[str] = []
    for tid in body.track_ids:
        item = items_by_id.get(tid)
        if item and item.status in ("Failed", "Cancelled", "Stopped"):
            if backend.queue_manager.retry_track(tid):
                retried_ids.append(tid)
    return {"retried_ids": retried_ids, "retried_count": len(retried_ids)}


@router.post("/tracks/cancel")
async def cancel_tracks_batch(request: Request, body: TrackIdsRequest):
    backend = _get_backend(request)
    items_by_id = {it.track.id: it for it in backend.queue_manager.get_items()}
    cancellable = {
        "Queued",
        "Downloading",
        "Resolving",
        "Resolving (YTM Fallback)",
        "Paused",
    }
    cancelled_ids: List[str] = []
    for tid in body.track_ids:
        item = items_by_id.get(tid)
        if item and item.status in cancellable:
            backend.queue_manager.cancel_track(tid)
            cancelled_ids.append(tid)
    return {"cancelled_ids": cancelled_ids, "cancelled_count": len(cancelled_ids)}


@router.post("/tracks/remove")
async def remove_tracks_batch(request: Request, body: TrackIdsRequest):
    backend = _get_backend(request)
    existing = {it.track.id for it in backend.queue_manager.get_items()}
    existing_ids: List[str] = []
    seen = set()
    for tid in body.track_ids:
        if tid in existing and tid not in seen:
            seen.add(tid)
            existing_ids.append(tid)

    if existing_ids:
        backend.queue_manager.remove_tracks(existing_ids)
        backend.events.emit_threadsafe("tracks_removed", {"track_ids": existing_ids})
    return {"removed_ids": existing_ids, "removed_count": len(existing_ids)}


@router.post("/tracks/{track_id}/retry")
async def retry_single_track(request: Request, track_id: str):
    backend = _get_backend(request)
    if not backend.queue_manager.retry_track(track_id):
        raise HTTPException(
            status_code=404, detail=f"Track '{track_id}' not found in queue."
        )
    return {"retried": True, "track_id": track_id}


@router.post("/tracks/{track_id}/cancel")
async def cancel_single_track(request: Request, track_id: str):
    backend = _get_backend(request)
    existing = {it.track.id for it in backend.queue_manager.get_items()}
    if track_id not in existing:
        raise HTTPException(
            status_code=404, detail=f"Track '{track_id}' not found in queue."
        )
    backend.queue_manager.cancel_track(track_id)
    return {"cancelled": True, "track_id": track_id}


@router.delete("/tracks/{track_id}")
async def remove_single_track(request: Request, track_id: str):
    backend = _get_backend(request)
    existing = {it.track.id for it in backend.queue_manager.get_items()}
    if track_id not in existing:
        raise HTTPException(
            status_code=404, detail=f"Track '{track_id}' not found in queue."
        )
    backend.queue_manager.remove_track(track_id)
    backend.events.emit_threadsafe("tracks_removed", {"track_ids": [track_id]})
    return {"removed": True, "track_id": track_id}


@router.get("/prompts")
async def list_musilon_prompts(request: Request):
    backend = _get_backend(request)
    return {"prompts": backend.get_pending_musilon_prompts()}


@router.post("/prompts/{prompt_id}/resolve")
async def resolve_musilon_prompt_route(
    request: Request, prompt_id: str, body: MusilonDecisionRequest
):
    backend = _get_backend(request)
    ok = backend.resolve_musilon_prompt(prompt_id, body.action)
    if not ok:
        raise HTTPException(
            status_code=404,
            detail=f"Prompt '{prompt_id}' not found or already resolved.",
        )
    return {"resolved": True, "prompt_id": prompt_id, "action": body.action}
