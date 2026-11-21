"""
Pure JSON serialization and secret-masking helpers for core models.
"""

import copy
from typing import Any, Dict

from core.config import SECRET_KEYS
from core.queue_manager import QueueItem
from core.spotify_client import TrackMetadata


def serialize_track(track: TrackMetadata) -> Dict[str, Any]:
    """Converts a TrackMetadata dataclass into a JSON-serializable dictionary."""
    return {
        "id": track.id,
        "title": track.title,
        "artists": list(track.artists) if track.artists else [],
        "artist_str": track.artist_str,
        "primary_artist": track.primary_artist,
        "album": track.album,
        "release_date": track.release_date,
        "duration_ms": track.duration_ms,
        "duration_sec": track.duration_sec,
        "track_number": track.track_number,
        "disc_number": track.disc_number,
        "isrc": track.isrc,
        "cover_url": track.cover_url,
        "collection_type": track.collection_type,
        "collection_name": track.collection_name,
        "collection_cover_url": track.collection_cover_url,
        "genres": list(track.genres) if track.genres else [],
        "genre_str": track.genre_str,
        "preferred_engine": track.preferred_engine,
    }


def serialize_queue_item(item: QueueItem) -> Dict[str, Any]:
    """Converts a DownloadQueueManager QueueItem into a JSON-serializable dictionary."""
    return {
        "track": serialize_track(item.track),
        "status": item.status,
        "source_type": item.source_type,
        "quality_badge": item.quality_badge,
        "progress_percent": item.progress_percent,
        "speed_str": item.speed_str,
        "eta_str": item.eta_str,
        "error_message": item.error_message,
        "output_path": item.output_path,
        "cancelled": item.cancelled,
        "preferred_engine": item.preferred_engine,
    }


def _mask_secret_str(value: str) -> str:
    return "******" if len(value) <= 8 else f"{value[:3]}***{value[-3:]}"


def _mask_dict_recursive(data: Dict[str, Any]) -> None:
    for key, val in data.items():
        if isinstance(val, dict):
            _mask_dict_recursive(val)
        elif isinstance(val, str) and key in SECRET_KEYS and val:
            data[key] = _mask_secret_str(val)


def mask_config_value(key_path: str, value: Any) -> Any:
    """Masks sensitive configuration values before broadcasting or serializing."""
    if isinstance(value, dict):
        masked = copy.deepcopy(value)
        _mask_dict_recursive(masked)
        return masked

    leaf_key = key_path.split(".")[-1] if key_path else ""
    if leaf_key in SECRET_KEYS and isinstance(value, str) and value:
        return _mask_secret_str(value)
    return value
