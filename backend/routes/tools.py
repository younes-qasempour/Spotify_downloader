"""
Audio Tools, Analysis, Equalizer, Maintenance & Exporters REST endpoints (/api/tools/*).
"""

import asyncio
import logging
import os
import re
from typing import Any, Dict, List, Literal, Optional, Tuple

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from backend.state import BackendState
from backend.track_lookup import resolve_track_row_and_file
from core import paths as core_paths
from core import utils as core_utils
from core.exporter import ExportConfig, PlaylistExporter
from core.spotify_client import TrackMetadata
from core.utils import EQ_FREQUENCIES, EQ_PRESETS, sanitize_filename

logger = logging.getLogger("backend.routes.tools")

router = APIRouter(prefix="/api/tools", tags=["tools"])

_SAFE_SPECTROGRAM_RE = re.compile(r"^[A-Za-z0-9_.-]+\.png$")


class SpectrumInspectRequest(BaseModel):
    track_id: Optional[str] = None
    file_path: Optional[str] = None
    generate_spectrogram: bool = True


class SpectrumScanRequest(BaseModel):
    root_dir: Optional[str] = None
    max_workers: int = 6


class SpectrumUpgradeRequest(BaseModel):
    track_ids: List[str] = []
    file_paths: List[str] = []
    preferred_engine: Literal["auto", "melobot", "musilon", "youtube"] = "auto"


class DuplicateScanRequest(BaseModel):
    use_acoustic_fingerprint: bool = True
    root_dir: Optional[str] = None


class DuplicateMergeRequest(BaseModel):
    mode: Literal["hardlink", "merge"] = "hardlink"
    groups: Optional[List[Dict[str, Any]]] = None
    group_keys: Optional[List[str]] = None


class NormalizeTrackRequest(BaseModel):
    target_lufs: Optional[float] = None
    force: bool = True


class NormalizeLibraryRequest(BaseModel):
    target_lufs: Optional[float] = None
    max_workers: Optional[int] = None
    root_dir: Optional[str] = None


class LibraryToolRequest(BaseModel):
    root_dir: Optional[str] = None


class EqualizerConfigRequest(BaseModel):
    enabled: Optional[bool] = None
    preset: Optional[str] = None
    preamp: Optional[float] = None
    bass_boost: Optional[float] = None
    bands: Optional[List[float]] = None


class EqualizerBakeRequest(BaseModel):
    bands: Optional[List[float]] = None
    preamp_db: Optional[float] = None
    bass_boost_db: Optional[float] = None


class ExportSongsRequest(BaseModel):
    destination_dir: str
    playlist_name: Optional[str] = None
    playlist_id: Optional[str] = None
    collection_name: Optional[str] = None
    collection_type: Optional[Literal["playlist", "album"]] = None
    track_ids: Optional[List[str]] = None
    create_playlist_subfolder: bool = True
    target_format: Literal["original", "mp3", "flac", "opus", "alac"] = "original"
    generate_m3u8: bool = True
    skip_existing: bool = True


class ExportM3u8Request(BaseModel):
    dest_path: Optional[str] = None
    playlist_id: Optional[str] = None
    collection_name: Optional[str] = None
    collection_type: Optional[Literal["playlist", "album"]] = None
    playlist_name: Optional[str] = None
    track_ids: Optional[List[str]] = None
    path_mode: Literal["filename", "absolute", "relative", "android_prefix"] = "filename"
    android_prefix: str = "/storage/emulated/0/Music"


def _get_backend(request: Request) -> BackendState:
    return request.app.state.backend


def _emit_tool_progress(
    backend: BackendState, tool: str, current: int, total: int, message: str
) -> None:
    pct = round((current / total) * 100.0, 1) if total > 0 else 0.0
    backend.events.emit_threadsafe(
        "tool_progress",
        {
            "tool": tool,
            "current": current,
            "total": total,
            "percent": pct,
            "message": message,
        },
    )


def _get_root_dir(backend: BackendState, override: Optional[str] = None) -> str:
    if override is not None and override.strip():
        return override.strip()
    return str(backend.config.get("download.output_dir", "") or "")


def _spectrogram_cache_dir() -> str:
    return os.path.join(str(core_paths.get_cache_dir()), "spectrograms")


def _find_track_row(backend: BackendState, track_id: str) -> Optional[Dict[str, Any]]:
    _fp, row, _qt = resolve_track_row_and_file(backend, track_id)
    if row:
        return row
    for candidate in backend.archive_manager.get_all_tracks():
        if candidate.get("spotify_id") == track_id:
            return candidate
    return None


def _resolve_track_row_and_path(
    backend: BackendState, track_id: str
) -> Tuple[Dict[str, Any], str]:
    file_path, row, _qt = resolve_track_row_and_file(backend, track_id)
    if not row:
        raise HTTPException(
            status_code=404, detail=f"Track '{track_id}' not found in library."
        )
    if not file_path or not os.path.isfile(file_path):
        raise HTTPException(
            status_code=404,
            detail=f"Audio file missing on disk for track '{track_id}'.",
        )
    return row, file_path


def _row_to_track_metadata(
    row: Dict[str, Any], preferred_engine: str = "auto"
) -> TrackMetadata:
    artists = [
        a.strip() for a in (row.get("artist") or "").split(",") if a.strip()
    ] or ["Unknown Artist"]
    genres = [g.strip() for g in (row.get("genre") or "").split(";") if g.strip()]
    return TrackMetadata(
        id=row.get("spotify_id") or "",
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
        preferred_engine=preferred_engine,
    )


def _format_spectrum_result(
    res: Dict[str, Any],
    *,
    track_id: Optional[str] = None,
    row: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    out = dict(res)
    spec_path = out.get("spectrogram_path")
    out["spectrogram_url"] = (
        f"/api/tools/spectrum/spectrogram/{os.path.basename(spec_path)}"
        if spec_path
        else None
    )
    if track_id is not None:
        out["track_id"] = track_id
    elif row and row.get("spotify_id"):
        out["track_id"] = row.get("spotify_id")
    if row:
        out.setdefault("title", row.get("title") or "")
        out.setdefault("artist", row.get("artist") or "")
    return out


# ---------------------------------------------------------------------------
# Spectrum Audit
# ---------------------------------------------------------------------------
@router.post("/spectrum/inspect/{track_id}")
async def inspect_track_spectrum(
    request: Request,
    track_id: str,
    generate_spectrogram: bool = Query(default=True),
):
    backend = _get_backend(request)
    row, file_path = _resolve_track_row_and_path(backend, track_id)
    res = await asyncio.to_thread(
        core_utils.inspect_audio_spectrum,
        file_path,
        generate_spectrogram=generate_spectrogram,
    )
    if res is None:
        raise HTTPException(
            status_code=422,
            detail="Could not inspect audio spectrum (ensure FFmpeg is installed and file is valid).",
        )
    return _format_spectrum_result(res, track_id=track_id, row=row)


@router.post("/spectrum/inspect")
async def inspect_path_spectrum(request: Request, body: SpectrumInspectRequest):
    backend = _get_backend(request)
    row: Optional[Dict[str, Any]] = None
    resolved_track_id = body.track_id

    if body.track_id:
        row, file_path = _resolve_track_row_and_path(backend, body.track_id)
    elif body.file_path and body.file_path.strip():
        file_path = body.file_path.strip()
        if not os.path.isfile(file_path):
            raise HTTPException(
                status_code=404, detail=f"Audio file not found: {file_path}"
            )
        row = backend.archive_manager.get_track_by_path(file_path)
        if row:
            resolved_track_id = row.get("spotify_id")
    else:
        raise HTTPException(
            status_code=400, detail="Provide either track_id or file_path."
        )

    res = await asyncio.to_thread(
        core_utils.inspect_audio_spectrum,
        file_path,
        generate_spectrogram=body.generate_spectrogram,
    )
    if res is None:
        raise HTTPException(
            status_code=422,
            detail="Could not inspect audio spectrum (ensure FFmpeg is installed and file is valid).",
        )
    return _format_spectrum_result(res, track_id=resolved_track_id, row=row)


@router.get("/spectrum/spectrogram/{filename}")
async def get_spectrogram_image(filename: str):
    if ".." in filename or not _SAFE_SPECTROGRAM_RE.fullmatch(filename):
        raise HTTPException(status_code=400, detail="Invalid spectrogram filename.")

    base_real = os.path.realpath(_spectrogram_cache_dir())
    target_real = os.path.realpath(os.path.join(base_real, filename))
    try:
        common = os.path.commonpath([base_real, target_real])
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid spectrogram path.")

    if common != base_real:
        raise HTTPException(status_code=400, detail="Invalid spectrogram path.")
    if not os.path.isfile(target_real):
        raise HTTPException(status_code=404, detail="Spectrogram image not found.")

    return FileResponse(target_real, media_type="image/png")


@router.post("/spectrum/scan")
async def scan_library_spectrum(
    request: Request, body: Optional[SpectrumScanRequest] = None
):
    backend = _get_backend(request)
    req = body or SpectrumScanRequest()
    root_dir = _get_root_dir(backend, req.root_dir)
    max_workers = max(1, min(16, int(req.max_workers)))

    def _cb(cur: int, total: int, msg: str) -> None:
        _emit_tool_progress(backend, "spectrum_scan", cur, total, msg)

    results = await asyncio.to_thread(
        backend.archive_manager.scan_library_spectrum,
        root_dir=root_dir,
        max_workers=max_workers,
        progress_callback=_cb,
    )

    upscaled = sum(1 for r in results if r.get("verdict") == "upscaled")
    good = sum(1 for r in results if r.get("verdict") == "good")
    authentic = sum(1 for r in results if r.get("verdict") == "authentic")
    return {
        "results": results,
        "summary": {
            "total": len(results),
            "upscaled": upscaled,
            "good": good,
            "authentic": authentic,
        },
    }


@router.post("/spectrum/upgrade")
async def upgrade_spectrum_tracks(request: Request, body: SpectrumUpgradeRequest):
    if not body.track_ids and not body.file_paths:
        raise HTTPException(
            status_code=400,
            detail="Provide at least one track_id or file_path to upgrade.",
        )

    backend = _get_backend(request)
    archive = backend.archive_manager
    matched_rows: Dict[str, Dict[str, Any]] = {}
    not_found: List[str] = []

    for tid in body.track_ids:
        row = _find_track_row(backend, tid)
        if row and row.get("spotify_id"):
            matched_rows[row["spotify_id"]] = row
        else:
            not_found.append(tid)

    for fp in body.file_paths:
        row = archive.get_track_by_path(fp)
        if row and row.get("spotify_id"):
            matched_rows[row["spotify_id"]] = row
        else:
            not_found.append(fp)

    tracks_to_upgrade: List[TrackMetadata] = []
    queued_ids: List[str] = []
    for sid, row in matched_rows.items():
        fp = row.get("file_path") or ""
        if fp and os.path.exists(fp):
            try:
                os.remove(fp)
            except Exception as exc:
                logger.warning(f"Failed removing file {fp} before upgrade: {exc}")
        archive.remove_downloaded_track(sid)
        tracks_to_upgrade.append(
            _row_to_track_metadata(row, preferred_engine=body.preferred_engine)
        )
        queued_ids.append(sid)

    if tracks_to_upgrade:
        backend.queue_manager.enqueue(tracks_to_upgrade)
        backend.queue_manager.start_all()
        backend.events.emit_threadsafe("library_updated", {})
        backend.events.emit_threadsafe("playlists_updated", {})

    return {
        "queued_count": len(tracks_to_upgrade),
        "track_ids": queued_ids,
        "not_found": not_found,
    }


# ---------------------------------------------------------------------------
# Smart Duplicate & Fingerprint Merger
# ---------------------------------------------------------------------------
@router.post("/duplicates/scan")
async def scan_duplicates(
    request: Request, body: Optional[DuplicateScanRequest] = None
):
    backend = _get_backend(request)
    req = body or DuplicateScanRequest()
    root_dir = _get_root_dir(backend, req.root_dir)

    def _cb(cur: int, total: int, msg: str) -> None:
        _emit_tool_progress(backend, "duplicates_scan", cur, total, msg)

    groups = await asyncio.to_thread(
        backend.archive_manager.find_library_duplicates,
        root_dir=root_dir,
        use_acoustic_fingerprint=req.use_acoustic_fingerprint,
        progress_callback=_cb,
    )
    backend.set_last_duplicate_groups(groups)

    redundant_files = sum(len(g.get("duplicates", [])) for g in groups)
    reclaimable_bytes = sum(int(g.get("reclaimable_bytes", 0) or 0) for g in groups)
    return {
        "groups": groups,
        "summary": {
            "total_groups": len(groups),
            "redundant_files": redundant_files,
            "reclaimable_bytes": reclaimable_bytes,
        },
    }


@router.post("/duplicates/merge")
async def merge_duplicates(request: Request, body: DuplicateMergeRequest):
    backend = _get_backend(request)
    using_cache = body.groups is None
    groups = (
        list(body.groups)
        if body.groups is not None
        else backend.get_last_duplicate_groups()
    )

    key_filter = set(body.group_keys) if body.group_keys is not None else None
    if key_filter is not None:
        groups = [g for g in groups if g.get("key") in key_filter]

    if not groups:
        return {
            "mode": body.mode,
            "groups_processed": 0,
            "files_merged": 0,
            "hardlinked": 0,
            "reclaimed_bytes": 0,
            "errors": 0,
        }

    stats = await asyncio.to_thread(
        backend.archive_manager.merge_library_duplicates,
        groups,
        mode=body.mode,
    )

    if using_cache:
        if key_filter is not None:
            remaining = [
                g
                for g in backend.get_last_duplicate_groups()
                if g.get("key") not in key_filter
            ]
            backend.set_last_duplicate_groups(remaining)
        else:
            backend.set_last_duplicate_groups([])

    backend.events.emit_threadsafe("library_updated", {})
    backend.events.emit_threadsafe("playlists_updated", {})
    return {"mode": body.mode, **stats}


# ---------------------------------------------------------------------------
# Volume Normalization & ReplayGain 2.0
# ---------------------------------------------------------------------------
@router.post("/volume/normalize-track/{track_id}")
async def normalize_single_track(
    request: Request,
    track_id: str,
    body: Optional[NormalizeTrackRequest] = None,
):
    backend = _get_backend(request)
    _row, file_path = _resolve_track_row_and_path(backend, track_id)
    req = body or NormalizeTrackRequest()
    target_lufs = (
        float(req.target_lufs)
        if req.target_lufs is not None
        else float(backend.config.get("download.target_lufs", -9.0) or -9.0)
    )

    res = await asyncio.to_thread(
        core_utils.normalize_audio_loudness,
        file_path,
        target_lufs=target_lufs,
        force=req.force,
    )
    return {
        "success": res is not None,
        "track_id": track_id,
        "target_lufs": target_lufs,
        "measured_lufs": res[0] if res else None,
        "gain_db": res[1] if res else None,
    }


@router.post("/volume/normalize-library")
async def normalize_library(
    request: Request, body: Optional[NormalizeLibraryRequest] = None
):
    backend = _get_backend(request)
    req = body or NormalizeLibraryRequest()
    root_dir = _get_root_dir(backend, req.root_dir)
    target_lufs = (
        float(req.target_lufs)
        if req.target_lufs is not None
        else float(backend.config.get("download.target_lufs", -9.0) or -9.0)
    )
    workers = (
        max(1, min(16, int(req.max_workers)))
        if req.max_workers is not None
        else min(12, max(4, (os.cpu_count() or 4)))
    )

    cancel_event = backend.register_tool_cancel_event("normalize_library")

    def _cb(cur: int, total: int, msg: str) -> None:
        _emit_tool_progress(backend, "normalize_library", cur, total, msg)

    try:
        stats = await asyncio.to_thread(
            backend.archive_manager.normalize_all_library_tracks,
            root_dir=root_dir,
            target_lufs=target_lufs,
            max_workers=workers,
            progress_callback=_cb,
            cancel_check=cancel_event.is_set,
        )
    finally:
        was_cancelled = cancel_event.is_set()
        backend.clear_tool_cancel_event("normalize_library", cancel_event)

    return {"cancelled": was_cancelled, **stats}


@router.post("/replaygain/track/{track_id}")
async def tag_single_track_replaygain(request: Request, track_id: str):
    backend = _get_backend(request)
    _row, file_path = _resolve_track_row_and_path(backend, track_id)

    rg = await asyncio.to_thread(core_utils.calculate_replaygain, file_path)
    if not rg:
        return {
            "success": False,
            "track_id": track_id,
            "track_gain": None,
            "track_peak": None,
        }

    gain_str, peak_str = rg
    tagged = await asyncio.to_thread(
        backend.tagger.tag_replaygain, file_path, gain_str, peak_str
    )
    return {
        "success": bool(tagged),
        "track_id": track_id,
        "track_gain": gain_str,
        "track_peak": peak_str,
    }


@router.post("/replaygain/library")
async def tag_library_replaygain(
    request: Request, body: Optional[LibraryToolRequest] = None
):
    backend = _get_backend(request)
    req = body or LibraryToolRequest()
    root_dir = _get_root_dir(backend, req.root_dir)

    def _cb(cur: int, total: int, msg: str) -> None:
        _emit_tool_progress(backend, "replaygain_library", cur, total, msg)

    stats = await asyncio.to_thread(
        backend.archive_manager.retag_all_library_replaygain,
        root_dir=root_dir,
        progress_callback=_cb,
    )
    return stats


# ---------------------------------------------------------------------------
# Equalizer
# ---------------------------------------------------------------------------
def _eq_response(backend: BackendState) -> Dict[str, Any]:
    cfg = backend.config
    raw_bands = cfg.get("ui.eq_bands", [0.0] * 10)
    if not isinstance(raw_bands, list) or len(raw_bands) != 10:
        raw_bands = [0.0] * 10
    return {
        "frequencies": list(EQ_FREQUENCIES),
        "presets": EQ_PRESETS,
        "config": {
            "enabled": bool(cfg.get("ui.eq_enabled", False)),
            "preset": str(cfg.get("ui.eq_preset", "Flat (Default)") or "Flat (Default)"),
            "preamp": float(cfg.get("ui.eq_preamp", 0.0) or 0.0),
            "bass_boost": float(cfg.get("ui.eq_bass_boost", 0.0) or 0.0),
            "bands": [float(b) for b in raw_bands],
        },
    }


@router.get("/eq")
async def get_equalizer_settings(request: Request):
    backend = _get_backend(request)
    return _eq_response(backend)


@router.put("/eq")
async def update_equalizer_settings(request: Request, body: EqualizerConfigRequest):
    backend = _get_backend(request)
    cfg = backend.config

    preset_data = EQ_PRESETS.get(body.preset) if body.preset else None
    bands_to_save = body.bands
    preamp_to_save = body.preamp
    bass_to_save = body.bass_boost

    if preset_data is not None:
        if bands_to_save is None:
            bands_to_save = list(preset_data["bands"])
        if preamp_to_save is None:
            preamp_to_save = float(preset_data.get("preamp", 0.0))
        if bass_to_save is None:
            bass_to_save = float(preset_data.get("bass_boost", 0.0))

    if bands_to_save is not None:
        if len(bands_to_save) != 10:
            raise HTTPException(
                status_code=400,
                detail="Equalizer bands must contain exactly 10 values.",
            )
        clamped_bands = [round(max(-12.0, min(12.0, float(v))), 2) for v in bands_to_save]
        cfg.set("ui.eq_bands", clamped_bands)

    if body.enabled is not None:
        cfg.set("ui.eq_enabled", bool(body.enabled))
    if body.preset is not None:
        cfg.set("ui.eq_preset", body.preset)
    if preamp_to_save is not None:
        cfg.set("ui.eq_preamp", round(max(-12.0, min(12.0, float(preamp_to_save))), 2))
    if bass_to_save is not None:
        cfg.set("ui.eq_bass_boost", round(max(0.0, min(12.0, float(bass_to_save))), 2))

    if hasattr(cfg, "save") and callable(cfg.save):
        cfg.save()

    return _eq_response(backend)


@router.post("/eq/bake/{track_id}")
async def bake_equalizer_to_track(
    request: Request,
    track_id: str,
    body: Optional[EqualizerBakeRequest] = None,
):
    backend = _get_backend(request)
    _row, file_path = _resolve_track_row_and_path(backend, track_id)
    req = body or EqualizerBakeRequest()
    cfg = backend.config

    bands = req.bands if req.bands is not None else cfg.get("ui.eq_bands", [0.0] * 10)
    if not isinstance(bands, list) or len(bands) != 10:
        raise HTTPException(
            status_code=400,
            detail="Equalizer bands must contain exactly 10 values.",
        )

    clean_bands = [max(-12.0, min(12.0, float(v))) for v in bands]
    preamp = float(
        req.preamp_db if req.preamp_db is not None else (cfg.get("ui.eq_preamp", 0.0) or 0.0)
    )
    bass_boost = float(
        req.bass_boost_db
        if req.bass_boost_db is not None
        else (cfg.get("ui.eq_bass_boost", 0.0) or 0.0)
    )

    ok = await asyncio.to_thread(
        core_utils.apply_equalizer_to_file,
        file_path,
        clean_bands,
        preamp_db=preamp,
        bass_boost_db=bass_boost,
    )
    return {
        "success": bool(ok),
        "track_id": track_id,
        "file_path": file_path,
    }


# ---------------------------------------------------------------------------
# Library Maintenance
# ---------------------------------------------------------------------------
@router.post("/maintenance/clean")
async def clean_library(request: Request, body: Optional[LibraryToolRequest] = None):
    backend = _get_backend(request)
    req = body or LibraryToolRequest()
    root_dir = _get_root_dir(backend, req.root_dir)
    stats = await asyncio.to_thread(
        backend.archive_manager.purge_corrupt_and_cleanup_library,
        downloads_dir=root_dir or None,
    )
    backend.events.emit_threadsafe("library_updated", {})
    return stats


@router.post("/maintenance/repair")
async def repair_library(request: Request, body: Optional[LibraryToolRequest] = None):
    backend = _get_backend(request)
    req = body or LibraryToolRequest()
    root_dir = _get_root_dir(backend, req.root_dir)

    def _cb(cur: int, total: int, msg: str) -> None:
        _emit_tool_progress(backend, "repair_library", cur, total, msg)

    stats = await asyncio.to_thread(
        backend.archive_manager.repair_library,
        root_dir=root_dir,
        progress_callback=_cb,
    )
    backend.events.emit_threadsafe("library_updated", {})
    return stats


@router.post("/maintenance/retag-genres")
async def retag_library_genres(
    request: Request, body: Optional[LibraryToolRequest] = None
):
    backend = _get_backend(request)
    req = body or LibraryToolRequest()
    root_dir = _get_root_dir(backend, req.root_dir)

    def _cb(cur: int, total: int, msg: str) -> None:
        _emit_tool_progress(backend, "retag_genres", cur, total, msg)

    stats = await asyncio.to_thread(
        backend.archive_manager.retag_all_library_genres,
        root_dir=root_dir,
        progress_callback=_cb,
    )
    backend.events.emit_threadsafe("library_updated", {})
    return stats


# ---------------------------------------------------------------------------
# Export Songs & Export .m3u8 & Cancellation
# ---------------------------------------------------------------------------
def _resolve_export_source(
    backend: BackendState,
    *,
    playlist_id: Optional[str],
    collection_name: Optional[str],
    collection_type: Optional[str],
    track_ids: Optional[List[str]],
    explicit_name: Optional[str],
) -> Tuple[str, List[Dict[str, Any]]]:
    archive = backend.archive_manager
    default_name = (explicit_name or "").strip()

    if playlist_id:
        pl = archive.get_saved_playlist(playlist_id)
        if not pl:
            raise HTTPException(
                status_code=404, detail=f"Saved playlist '{playlist_id}' not found."
            )
        rows = archive.get_saved_playlist_tracks(playlist_id)
        playable = [
            r for r in rows if r.get("file_path") and os.path.isfile(r["file_path"])
        ]
        return default_name or pl.get("name") or "Exported Playlist", playable

    if collection_name:
        if collection_type:
            rows = archive.get_collection_tracks(
                collection_name, collection_type=collection_type
            )
        else:
            rows = archive.get_collection_tracks(
                collection_name, collection_type="playlist"
            )
            if not rows:
                rows = archive.get_collection_tracks(
                    collection_name, collection_type="album"
                )
        return default_name or collection_name, rows

    if track_ids:
        rows: List[Dict[str, Any]] = []
        for tid in track_ids:
            row = _find_track_row(backend, tid)
            if row:
                rows.append(row)
        return default_name or "Exported Tracks", rows

    raise HTTPException(
        status_code=400,
        detail="Provide playlist_id, collection_name, or track_ids.",
    )


@router.post("/export/songs")
async def export_songs(request: Request, body: ExportSongsRequest):
    dest_dir = body.destination_dir.strip()
    if not dest_dir:
        raise HTTPException(
            status_code=400, detail="Destination directory must be specified."
        )

    backend = _get_backend(request)
    name, tracks = _resolve_export_source(
        backend,
        playlist_id=body.playlist_id,
        collection_name=body.collection_name,
        collection_type=body.collection_type,
        track_ids=body.track_ids,
        explicit_name=body.playlist_name,
    )
    if not tracks:
        raise HTTPException(
            status_code=400, detail="No downloaded tracks available to export."
        )

    cfg = backend.config
    cfg.set("export.last_dir", os.path.normpath(dest_dir))
    cfg.set("export.last_subfolder", body.create_playlist_subfolder)
    cfg.set("export.last_format", body.target_format)
    cfg.set("export.last_m3u8", body.generate_m3u8)
    cfg.set("export.last_skip_existing", body.skip_existing)
    if hasattr(cfg, "save") and callable(cfg.save):
        cfg.save()

    exp_cfg = ExportConfig(
        destination_dir=os.path.normpath(dest_dir),
        create_playlist_subfolder=body.create_playlist_subfolder,
        target_format=body.target_format,
        generate_m3u8=body.generate_m3u8,
        skip_existing=body.skip_existing,
    )
    cancel_event = backend.register_tool_cancel_event("export_songs")

    def _cb(cur: int, total: int, msg: str) -> None:
        _emit_tool_progress(backend, "export_songs", cur, total, msg)

    try:
        res = await asyncio.to_thread(
            PlaylistExporter.export_tracks,
            name,
            tracks,
            exp_cfg,
            progress_callback=_cb,
            cancel_event=cancel_event,
        )
    finally:
        backend.clear_tool_cancel_event("export_songs", cancel_event)

    return {
        "total": res.total,
        "exported": res.exported,
        "skipped": res.skipped,
        "failed": res.failed,
        "export_dir": res.export_dir,
        "m3u8_path": res.m3u8_path,
        "errors": res.errors,
        "cancelled": res.cancelled,
    }


@router.post("/export/m3u8")
async def export_m3u8_playlist(request: Request, body: ExportM3u8Request):
    backend = _get_backend(request)
    archive = backend.archive_manager
    cfg = backend.config

    dest_path = body.dest_path.strip() if body.dest_path else None
    if dest_path and not dest_path.lower().endswith(".m3u8"):
        dest_path = f"{dest_path}.m3u8"

    cfg.set("export_m3u.path_mode", body.path_mode)
    cfg.set("export_m3u.android_prefix", body.android_prefix.strip())
    if dest_path:
        cfg.set("export_m3u.last_dir", os.path.dirname(os.path.abspath(dest_path)))
    if hasattr(cfg, "save") and callable(cfg.save):
        cfg.save()

    if body.playlist_id:
        pl = archive.get_saved_playlist(body.playlist_id)
        if not pl:
            raise HTTPException(
                status_code=404,
                detail=f"Saved playlist '{body.playlist_id}' not found.",
            )
        if not dest_path:
            output_dir = _get_root_dir(backend) or str(
                core_paths.get_default_download_dir()
            )
            safe_name = sanitize_filename(pl.get("name", "Playlist"), max_length=50)
            if bool(cfg.get("download.save_in_subfolders", False)):
                dest_path = os.path.join(output_dir, safe_name, f"{safe_name}.m3u8")
            else:
                dest_path = os.path.join(output_dir, "playlists", f"{safe_name}.m3u8")
        out_path = await asyncio.to_thread(
            archive.export_saved_playlist_m3u8,
            body.playlist_id,
            dest_path=dest_path,
            path_mode=body.path_mode,
            android_prefix=body.android_prefix.strip(),
        )
    else:
        name, tracks = _resolve_export_source(
            backend,
            playlist_id=None,
            collection_name=body.collection_name,
            collection_type=body.collection_type,
            track_ids=body.track_ids,
            explicit_name=body.playlist_name,
        )
        if not tracks:
            raise HTTPException(
                status_code=400, detail="No downloaded tracks available for M3U8 export."
            )
        if not dest_path:
            base_dir = _get_root_dir(backend) or str(
                core_paths.get_default_download_dir()
            )
            safe_name = sanitize_filename(name, max_length=60) or "Playlist"
            dest_path = os.path.join(base_dir, f"{safe_name}.m3u8")
        out_path = await asyncio.to_thread(
            archive.export_tracks_to_m3u8,
            name,
            tracks,
            dest_path,
            path_mode=body.path_mode,
            android_prefix=body.android_prefix.strip(),
        )

    if not out_path:
        raise HTTPException(
            status_code=422,
            detail="Could not generate .m3u8 playlist (no playable tracks found).",
        )

    return {
        "success": True,
        "m3u8_path": out_path,
        "path_mode": body.path_mode,
    }


@router.post("/cancel/{tool_name}")
async def cancel_running_tool(request: Request, tool_name: str):
    backend = _get_backend(request)
    cancelled = backend.cancel_tool(tool_name)
    return {"tool": tool_name, "cancelled": cancelled}
