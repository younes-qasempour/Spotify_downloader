"""
Unified track & file lookup across downloaded_tracks, saved_playlist_tracks, and active queue.
Handles smart-deduplicated saved playlist tracks whose spotify_id differs from the master
record's spotify_id in downloaded_tracks.
"""

import os
from typing import Any, Dict, Optional, Tuple

from backend.state import BackendState
from core.spotify_client import TrackMetadata


def _lookup_saved_playlist_row(backend: BackendState, track_id: str) -> Optional[Dict[str, Any]]:
    archive = backend.archive_manager
    try:
        with archive.connection() as conn:
            cur = conn.execute(
                """
                SELECT * FROM saved_playlist_tracks
                WHERE spotify_id = ?
                ORDER BY
                    CASE WHEN file_path IS NOT NULL AND file_path != '' THEN 0 ELSE 1 END,
                    id DESC
                LIMIT 1
                """,
                (track_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None
    except Exception:
        return None


def _merge_saved_with_archive(
    archive: Any, saved_row: Dict[str, Any], file_path: str
) -> Dict[str, Any]:
    merged: Dict[str, Any] = dict(saved_row)
    canonical = archive.get_track_by_path(file_path) if file_path else None
    if canonical:
        for k, v in canonical.items():
            if k in ("spotify_id", "cover_url"):
                merged.setdefault(k, v)
            elif not merged.get(k) and v:
                merged[k] = v
        # Keep the requested track's own identity & playlist cover URL while sharing physical path
        merged["file_path"] = canonical.get("file_path") or file_path
        if saved_row.get("cover_url"):
            merged["cover_url"] = saved_row["cover_url"]
        if saved_row.get("spotify_id"):
            merged["spotify_id"] = saved_row["spotify_id"]
    else:
        merged["file_path"] = file_path
    return merged


def resolve_track_row_and_file(
    backend: BackendState, track_id: str
) -> Tuple[Optional[str], Optional[Dict[str, Any]], Optional[TrackMetadata]]:
    """
    Resolves (file_path_on_disk, db_row_dict, active_queue_track) for any track_id across:
    1. Master `downloaded_tracks` (by spotify_id)
    2. `saved_playlist_tracks` (by spotify_id -> file_path or ISRC/title+artist fallback)
    3. Active download queue items
    """
    archive = backend.archive_manager

    # 1. Master archive lookup by spotify_id
    master_row = archive.find_track(spotify_id=track_id)
    if master_row:
        fp = master_row.get("file_path") or ""
        if fp and os.path.isfile(fp):
            return fp, master_row, None

    # 2. Saved playlist track lookup (handles deduplicated editions pointing to shared file_path)
    saved_row = _lookup_saved_playlist_row(backend, track_id)
    if saved_row:
        sp_fp = saved_row.get("file_path") or ""
        if sp_fp and os.path.isfile(sp_fp):
            return sp_fp, _merge_saved_with_archive(archive, saved_row, sp_fp), None

        # Secondary dedup match via ISRC / normalized title + artist when file_path was blank
        matched = archive.find_track(
            isrc=saved_row.get("isrc") or "",
            title=saved_row.get("title") or "",
            artist=saved_row.get("artist") or "",
        )
        if matched:
            m_fp = matched.get("file_path") or ""
            if m_fp and os.path.isfile(m_fp):
                return m_fp, _merge_saved_with_archive(archive, saved_row, m_fp), None

    # 3. Active or recently finished queue items
    queue_track: Optional[TrackMetadata] = None
    for it in backend.queue_manager.get_items():
        if it.track.id == track_id:
            queue_track = it.track
            if it.output_path and os.path.isfile(it.output_path):
                q_row = {
                    "spotify_id": it.track.id,
                    "title": it.track.title,
                    "artist": it.track.artist_str,
                    "album": it.track.album,
                    "duration_ms": it.track.duration_ms,
                    "track_number": it.track.track_number,
                    "disc_number": it.track.disc_number,
                    "isrc": it.track.isrc,
                    "cover_url": it.track.cover_url,
                    "collection_name": it.track.collection_name,
                    "collection_type": it.track.collection_type,
                    "genre": "; ".join(it.track.genres or []),
                    "file_path": it.output_path,
                }
                return it.output_path, q_row, it.track
            break

    return None, (master_row or saved_row), queue_track
