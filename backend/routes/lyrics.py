"""
Synchronized Karaoke Lyrics, LRCLIB fetching, export, and translation endpoints (/api/lyrics/*).
"""

import asyncio
import logging
import os
import re
from typing import Any, Dict, List, Literal, Optional, Tuple

from fastapi import APIRouter, Body, HTTPException, Query, Request
from pydantic import BaseModel, Field

from backend.state import BackendState
from backend.track_lookup import resolve_track_row_and_file
from core.spotify_client import TrackMetadata
from core.utils import extract_embedded_lyrics

logger = logging.getLogger("backend.routes.lyrics")

router = APIRouter(prefix="/api/lyrics", tags=["lyrics"])

_LRC_TAG_RE = re.compile(r"\[(\d{1,2}):(\d{2})(?:\.(\d{2,3}))?\]")
_LRC_LINE_PREFIX_RE = re.compile(r"^((?:\[\d{1,2}:\d{2}(?:\.\d{2,3})?\])+)(.*)$")


class TranslateLyricsRequest(BaseModel):
    lines: List[str] = Field(default_factory=list)
    target_lang: Literal["none", "en", "fa"] = "none"
    persist_preference: bool = True


class ExportLrcRequest(BaseModel):
    include_translation: bool = False
    target_lang: Optional[Literal["en", "fa"]] = None
    output_path: Optional[str] = None
    write_to_disk: bool = True


def _get_backend(request: Request) -> BackendState:
    return request.app.state.backend


def _resolve_track_and_file(
    backend: BackendState, track_id: str
) -> Tuple[Optional[str], Optional[Dict[str, Any]], Optional[TrackMetadata]]:
    return resolve_track_row_and_file(backend, track_id)


def _load_local_lyrics(file_path: str) -> Tuple[str, str]:
    base, _ = os.path.splitext(file_path)
    candidates = [
        f"{base}.lrc",
        os.path.join(os.path.dirname(file_path), "lyrics", f"{os.path.basename(base)}.lrc"),
    ]
    for cand in candidates:
        if os.path.isfile(cand):
            try:
                with open(cand, "r", encoding="utf-8", errors="replace") as fh:
                    text = fh.read()
                if text.strip():
                    return text, "lrc_file"
            except Exception:
                pass

    try:
        embedded = extract_embedded_lyrics(file_path)
        if embedded and embedded.strip():
            return embedded, "embedded"
    except Exception:
        pass

    return "", "none"


def _parse_lrc_timeline(raw_text: str) -> Tuple[List[Dict[str, Any]], bool]:
    if not raw_text or not raw_text.strip():
        return [], False

    synced_entries: List[Tuple[int, str]] = []
    plain_lines: List[str] = []

    for raw_line in raw_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        m = _LRC_LINE_PREFIX_RE.match(line)
        if m:
            tags_part = m.group(1)
            lyric_text = m.group(2).strip()
            if not lyric_text:
                continue
            for tm in _LRC_TAG_RE.finditer(tags_part):
                mins = int(tm.group(1))
                secs = int(tm.group(2))
                ms_str = tm.group(3) or "0"
                ms = int(ms_str.ljust(3, "0")[:3])
                total_ms = (mins * 60 + secs) * 1000 + ms
                synced_entries.append((total_ms, lyric_text))
        elif not line.startswith("["):
            plain_lines.append(line)

    if synced_entries:
        synced_entries.sort(key=lambda x: x[0])
        return (
            [{"timestamp_ms": ts, "text": txt} for ts, txt in synced_entries],
            True,
        )

    if plain_lines:
        return ([{"timestamp_ms": 0, "text": txt} for txt in plain_lines], False)

    return [], False


def _format_lrc_content(
    lines: List[Dict[str, Any]], translations: Optional[List[str]] = None
) -> str:
    has_trans = translations is not None and len(translations) == len(lines)
    out_lines: List[str] = []
    for idx, entry in enumerate(lines):
        ts_ms = max(0, int(entry.get("timestamp_ms", 0)))
        txt = str(entry.get("text", ""))
        mins = ts_ms // 60000
        secs = (ts_ms % 60000) // 1000
        centis = (ts_ms % 1000) // 10
        if has_trans and translations[idx] and translations[idx] != txt:
            out_lines.append(f"[{mins:02d}:{secs:02d}.{centis:02d}] {txt} / {translations[idx]}")
        else:
            out_lines.append(f"[{mins:02d}:{secs:02d}.{centis:02d}] {txt}")
    return "\n".join(out_lines) + "\n"


@router.post("/translate")
async def translate_lyrics_lines(request: Request, body: TranslateLyricsRequest):
    backend = _get_backend(request)
    if body.persist_preference:
        backend.config.set("ui.lyrics_translation_lang", body.target_lang)

    if body.target_lang == "none" or not body.lines:
        return {"target_lang": body.target_lang, "translated_lines": []}

    translated = await asyncio.to_thread(
        backend.lyrics_engine.translate_lyrics, body.lines, body.target_lang
    )
    return {"target_lang": body.target_lang, "translated_lines": translated}


@router.get("/{track_id}")
async def get_track_lyrics(
    request: Request,
    track_id: str,
    lang: Optional[str] = Query(default=None),
):
    backend = _get_backend(request)
    file_path, row, q_track = _resolve_track_and_file(backend, track_id)
    if row is None and q_track is None:
        raise HTTPException(status_code=404, detail=f"Track '{track_id}' not found.")

    raw_text = ""
    source = "none"
    if file_path:
        raw_text, source = _load_local_lyrics(file_path)

    lines, is_synced = _parse_lrc_timeline(raw_text)
    active_lang = (lang or "none").strip().lower()
    if active_lang not in ("en", "fa"):
        active_lang = "none"

    if active_lang in ("en", "fa") and lines:
        translated = await asyncio.to_thread(
            backend.lyrics_engine.translate_lyrics,
            [line["text"] for line in lines],
            active_lang,
        )
        if translated and len(translated) == len(lines):
            for idx, line in enumerate(lines):
                line["translated"] = translated[idx]

    return {
        "track_id": track_id,
        "has_lyrics": bool(lines),
        "is_synced": is_synced,
        "source": source,
        "raw_text": raw_text,
        "lines": lines,
        "translation_lang": active_lang,
    }


@router.post("/{track_id}/fetch")
async def fetch_track_lyrics_online(request: Request, track_id: str):
    backend = _get_backend(request)
    file_path, row, q_track = _resolve_track_and_file(backend, track_id)
    if not file_path or not os.path.isfile(file_path):
        raise HTTPException(
            status_code=404,
            detail=f"Audio file for track '{track_id}' not found on disk.",
        )

    if q_track is not None:
        t_meta = q_track
    elif row is not None:
        artists = [
            a.strip() for a in (row.get("artist") or "").split(",") if a.strip()
        ] or ["Unknown"]
        t_meta = TrackMetadata(
            id=row.get("spotify_id") or track_id,
            title=row.get("title") or os.path.splitext(os.path.basename(file_path))[0],
            artists=artists,
            album=row.get("album") or "",
            duration_ms=row.get("duration_ms") or 0,
        )
    else:
        raise HTTPException(status_code=404, detail=f"Track '{track_id}' not found.")

    lyr = await asyncio.to_thread(backend.lyrics_engine.fetch_lyrics, t_meta)
    if lyr and (lyr.synced_lyrics or lyr.plain_lyrics):
        await asyncio.to_thread(
            backend.tagger.tag_file,
            file_path,
            t_meta,
            lyrics_data=lyr,
            embed_art=False,
            embed_lyrics=True,
        )
        lrc_saved = False
        if lyr.synced_lyrics:
            base, _ = os.path.splitext(file_path)
            saved_p = backend.lyrics_engine.save_lrc_file(
                lyr.synced_lyrics, f"{base}.lrc"
            )
            lrc_saved = bool(saved_p)

        raw_text = lyr.synced_lyrics or lyr.plain_lyrics or ""
        lines, is_synced = _parse_lrc_timeline(raw_text)
        return {
            "found": True,
            "has_lyrics": bool(lines),
            "is_synced": is_synced,
            "source": "lrclib",
            "raw_text": raw_text,
            "lines": lines,
            "lrc_saved": lrc_saved,
        }

    return {
        "found": False,
        "has_lyrics": False,
        "is_synced": False,
        "source": "none",
        "raw_text": "",
        "lines": [],
        "message": "No lyrics found on LRCLIB for this track.",
    }


@router.post("/{track_id}/export-lrc")
async def export_track_lrc(
    request: Request,
    track_id: str,
    body: Optional[ExportLrcRequest] = Body(default=None),
):
    backend = _get_backend(request)
    file_path, row, q_track = _resolve_track_and_file(backend, track_id)
    if not file_path or not os.path.isfile(file_path):
        raise HTTPException(
            status_code=404,
            detail=f"Audio file for track '{track_id}' not found on disk.",
        )

    raw_text, _ = _load_local_lyrics(file_path)
    lines, _ = _parse_lrc_timeline(raw_text)
    if not lines:
        raise HTTPException(
            status_code=404, detail=f"No lyrics found for track '{track_id}'."
        )

    req = body or ExportLrcRequest()
    translations: Optional[List[str]] = None
    if req.include_translation and req.target_lang in ("en", "fa"):
        translations = await asyncio.to_thread(
            backend.lyrics_engine.translate_lyrics,
            [line["text"] for line in lines],
            req.target_lang,
        )

    content = _format_lrc_content(lines, translations=translations)
    saved_path: Optional[str] = None
    if req.write_to_disk:
        target_path = req.output_path or (os.path.splitext(file_path)[0] + ".lrc")
        os.makedirs(os.path.dirname(os.path.abspath(target_path)), exist_ok=True)
        with open(target_path, "w", encoding="utf-8") as fh:
            fh.write(content)
        saved_path = target_path

    return {"saved_path": saved_path, "content": content}
