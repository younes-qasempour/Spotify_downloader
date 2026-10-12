from typing import Protocol, TypedDict, Literal, Optional, List, Dict, Any, Callable, runtime_checkable
from dataclasses import dataclass

QualityTier = Literal[
    "Musilon FLAC 24",
    "Musilon FLAC 16",
    "Musilon 320k",
    "Musilon Standard",
    "YTM Opus",
    "YTM M4A",
    "YouTube Opus",
    "YouTube M4A",
    "Local Archive",
    "Audio"
]

DownloadStatus = Literal[
    "Queued",
    "Resolving",
    "Downloading",
    "Paused",
    "Tagging",
    "Fetching Lyrics",
    "Completed",
    "Failed",
    "Cancelled",
    "Stopped",
    "Musilon Limit Reached"
]

CollectionType = Literal["track", "album", "playlist", "artist"]

LyricsMode = Literal["embedded_only", "same_folder", "separate_folder"]

TargetAudioFormat = Literal["original", "alac", "mp3_320", "flac", "opus"]


@runtime_checkable
class DownloadProgressCallback(Protocol):
    def __call__(self, percent: float, speed_str: str, eta_str: str) -> None: ...


@runtime_checkable
class StatusCallback(Protocol):
    def __call__(self, status: str) -> None: ...


@runtime_checkable
class CancelCheckCallback(Protocol):
    def __call__(self) -> bool: ...


@runtime_checkable
class PauseWaitCallback(Protocol):
    def __call__(self) -> None: ...


class ArchivedTrackRecord(TypedDict, total=False):
    spotify_id: str
    isrc: str
    title: str
    artist: str
    album: str
    duration_ms: int
    track_number: int
    disc_number: int
    file_path: str
    file_size: int
    quality_badge: str
    source_type: str
    collection_name: str
    collection_type: str
    genre: str
    downloaded_at: str


class SavedPlaylistRecord(TypedDict, total=False):
    id: str
    name: str
    spotify_url: str
    cover_url: str
    total_tracks: int
    downloaded_tracks: int
    created_at: str
    updated_at: str
