"""Non-sensitive source-match summaries for interactive approval."""
import re
import math
from difflib import SequenceMatcher


VERSION_WORDS = {"live", "remix", "acoustic", "instrumental", "cover", "karaoke", "slowed", "sped", "remaster"}
_INFLECTIONS = {
    "remastered": "remaster",
    "remixes": "remix",
    "covers": "cover",
}


def _extract_versions(normalized_text: str) -> set[str]:
    tokens = [_INFLECTIONS.get(word, word) for word in str(normalized_text).split()]
    return VERSION_WORDS.intersection(tokens)


def _normalized(text: str) -> str:
    return " ".join(re.findall(r"\w+", str(text).casefold()))


def source_review_summary(track, resolved) -> dict:
    source = resolved.source_obj
    title = str(getattr(source, "title", "") or "")
    artist = str(getattr(source, "artist", "") or getattr(source, "uploader", "") or "")
    duration = getattr(source, "duration_sec", None)
    if duration is None:
        duration = getattr(source, "duration", None)
    try:
        if duration is None and getattr(source, "duration_ms", None) is not None:
            duration = float(source.duration_ms) / 1000.0
        duration = float(duration) if duration is not None else None
        if duration is not None and (not math.isfinite(duration) or duration <= 0):
            duration = None
    except (TypeError, ValueError):
        duration = None
    expected_title = _normalized(track.title)
    candidate_title = _normalized(title)
    expected_versions = _extract_versions(expected_title)
    candidate_versions = _extract_versions(candidate_title)
    reasons = []
    if not title:
        reasons.append("The provider did not supply a candidate title.")
    elif SequenceMatcher(None, expected_title, candidate_title).ratio() < 0.88:
        matched = False
        prefixes = [
            _normalized(getattr(track, "primary_artist", "") or track.artist_str) + " ",
            _normalized(track.artist_str) + " ",
        ]
        for prefix in prefixes:
            if prefix.strip() and candidate_title.startswith(prefix):
                stripped = candidate_title[len(prefix):]
                if SequenceMatcher(None, expected_title, stripped).ratio() >= 0.88:
                    matched = True
                    break
        if not matched:
            reasons.append("Candidate title differs from the requested recording.")
    if artist and SequenceMatcher(None, _normalized(track.artist_str), _normalized(artist)).ratio() < 0.8:
        reasons.append("Candidate artist differs from the requested artist.")
    if expected_versions != candidate_versions:
        reasons.append("Recording-version markers differ (for example live, remix, or acoustic).")
    expected_duration = track.duration_sec
    if duration is not None and expected_duration > 0 and abs(duration - expected_duration) > max(5, expected_duration * 0.04):
        reasons.append("Candidate duration differs by more than the matching tolerance.")
    return {
        "requested_title": track.title,
        "requested_artist": track.artist_str,
        "requested_duration": expected_duration,
        "title": title or "Not supplied",
        "artist": artist or "Not supplied",
        "duration": duration,
        "version": ", ".join(sorted(candidate_versions)) or "No version marker supplied",
        "quality": resolved.quality_badge,
        "provider": resolved.source_type,
        "reasons": reasons,
        "uncertain": bool(reasons),
    }


def diagnostic_hint(message: str, stage: str = "") -> str:
    text = message.casefold()
    if any(word in text for word in ("429", "quota", "rate limit", "budget")):
        return "Wait for the provider cooldown or daily quota reset; avoid repeatedly retrying the batch."
    if any(word in text for word in ("unauthorized", "cookie", "authentication", "session expired", "vip")):
        return "Reconnect this provider in Settings, then retry the stopped or failed item."
    if any(word in text for word in ("permission", "disk", "space", "access denied")):
        return "Check free disk space and output-folder permissions, then retry."
    if any(word in text for word in ("timeout", "connection", "network", "proxy")):
        return "Check the network and proxy settings, allow the provider cooldown to finish, then retry."
    if "ffmpeg" in text or stage in {"Conversion", "Normalization"}:
        return "Check FFmpeg availability and the selected audio format; retry with the native format if necessary."
    if "source" in text or "match" in text:
        return "Review the requested recording and source provider, then retry or choose another provider."
    return "Inspect the error and settings, then retry this item. Previously completed files remain untouched."


def processing_stage(status: str) -> str:
    text = status.casefold()
    for marker, stage in (
        ("approval", "Source review"), ("resolv", "Source matching"),
        ("download", "Transfer"), ("transcod", "Conversion"), ("remux", "Conversion"),
        ("lyrics", "Lyrics"), ("tag", "Tagging"), ("balanc", "Normalization"),
        ("normaliz", "Normalization"), ("cooldown", "Provider cooldown"),
        ("publish", "Publication"), ("verif", "Verification"),
    ):
        if marker in text:
            return stage
    return status