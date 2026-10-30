import os
import logging
from dataclasses import dataclass
from typing import Optional
import requests

from core.spotify_client import TrackMetadata
from core.utils import clean_watermarks

logger = logging.getLogger("core.lyrics")


@dataclass
class LyricsData:
    synced_lyrics: Optional[str] = None
    plain_lyrics: Optional[str] = None
    instrumental: bool = False

    def get(self, key: str, default=None):
        if key in ("synced", "synced_lyrics"):
            return self.synced_lyrics if self.synced_lyrics is not None else default
        if key in ("plain", "plain_lyrics"):
            return self.plain_lyrics if self.plain_lyrics is not None else default
        return getattr(self, key, default)


class LyricsEngine:
    """
    LRCLIB REST API integration (https://lrclib.net/api/get).
    Provides:
    - Synchronized lyrics ([mm:ss.xx] timestamped format)
    - Unsynchronized plain text lyrics for ID3/Vorbis embedding
    - Companion .lrc file exporter
    """

    API_URL = "https://lrclib.net/api/get"
    SEARCH_URL = "https://lrclib.net/api/search"
    USER_AGENT = "Flacify/1.6.2 (https://github.com/younes-qasempour/Spotify_downloader)"

    def __init__(self, session: Optional[requests.Session] = None):
        self.session = session or requests.Session()
        self.session.headers.update({
            "User-Agent": self.USER_AGENT,
            "Accept": "application/json",
        })
        try:
            from core.config import config
            proxy = config.get("download.proxy", "").strip()
            if proxy:
                self.session.proxies = {"http": proxy, "https": proxy}
        except Exception:
            pass

    def fetch_lyrics(self, track: TrackMetadata) -> Optional[LyricsData]:
        """
        Queries LRCLIB for lyrics using title, artist, album, and duration.
        If exact match is not found or is flagged instrumental without lyrics,
        falls back to searching LRCLIB with fuzzy title/bilingual variants.
        """
        import re
        clean_title = clean_watermarks(track.title)
        clean_album = clean_watermarks(track.album)
        params = {
            "track_name": clean_title,
            "artist_name": track.primary_artist,
            "album_name": clean_album,
            "duration": int(track.duration_sec),
        }

        try:
            resp = self.session.get(self.API_URL, params=params, timeout=10)
            if resp.status_code == 404:
                # Retry without album name
                params.pop("album_name", None)
                resp = self.session.get(self.API_URL, params=params, timeout=10)

            if resp.status_code == 200:
                data = resp.json()
                synced = data.get("syncedLyrics")
                plain = data.get("plainLyrics")
                instrumental = bool(data.get("instrumental", False))

                if synced or plain:
                    logger.info(f"Lyrics found via exact get for '{track.title}' (synced={bool(synced)})")
                    return LyricsData(
                        synced_lyrics=synced,
                        plain_lyrics=plain,
                        instrumental=instrumental
                    )
                elif instrumental:
                    logger.info(f"Track '{track.title}' is confirmed instrumental via exact LRCLIB match")
                    return LyricsData(
                        synced_lyrics="[00:00.00] ♪ Instrumental ♪",
                        plain_lyrics="[Instrumental]",
                        instrumental=True
                    )
            else:
                logger.info(f"Exact lyrics get missed on LRCLIB for '{track.title}' (status {resp.status_code})")

        except Exception as e:
            logger.warning(f"Error in exact lyrics fetch for '{track.title}': {e}")

        # Search fallback across fuzzy queries & bilingual variants
        return self._search_lyrics(track, clean_title)

    def _search_lyrics(self, track: TrackMetadata, clean_title: str) -> Optional[LyricsData]:
        import re
        target_dur = track.duration_sec
        feat_clean = re.sub(r'[\(\[]\s*(?:feat\.?|ft\.?|with|prod\.?|featuring)\b[^\]\)]*[\)\]]', '', clean_title, flags=re.IGNORECASE).strip()
        queries = [f"{feat_clean} {track.primary_artist}".strip()]
        if clean_title != feat_clean:
            queries.append(f"{clean_title} {track.primary_artist}".strip())

        # Bilingual / split parts (e.g. "オトノケ - Otonoke", "青のすみか - Where Our Blue Is")
        for sep in (" - ", " / ", " | ", " : "):
            for src_t in (feat_clean, clean_title):
                if sep in src_t:
                    for part in src_t.split(sep):
                        p_c = part.strip()
                        if len(p_c) >= 2:
                            q_cand = f"{p_c} {track.primary_artist}".strip()
                            if q_cand not in queries:
                                queries.append(q_cand)
                            if p_c not in queries:
                                queries.append(p_c)

        if feat_clean not in queries:
            queries.append(feat_clean)

        instrumental_match = False

        for q in queries:
            try:
                r = self.session.get(self.SEARCH_URL, params={"q": q}, timeout=8)
                if r.status_code == 200:
                    results = r.json()
                    # Filter items with lyrics
                    valid_with_lyrics = [c for c in results if (c.get("syncedLyrics") or c.get("plainLyrics"))]

                    # Filter candidates within duration window (±15s or missing duration)
                    candidates = []
                    for c in valid_with_lyrics:
                        c_dur = c.get("duration")
                        diff = abs(c_dur - target_dur) if (c_dur and target_dur > 0) else 0.0
                        if target_dur <= 0 or diff <= 15.0 or c_dur is None:
                            candidates.append((diff, 0 if c.get("syncedLyrics") else 1, c))

                    if candidates:
                        # Best is synced first, then closest duration
                        candidates.sort(key=lambda x: (x[1], x[0]))
                        best = candidates[0][2]
                        diff = candidates[0][0]
                        logger.info(f"LRCLIB search fallback found lyrics for '{track.title}' (diff={diff:.1f}s, query='{q}')")
                        return LyricsData(
                            synced_lyrics=best.get("syncedLyrics"),
                            plain_lyrics=best.get("plainLyrics"),
                            instrumental=False
                        )

                    # Check if search indicated instrumental
                    if not instrumental_match:
                        for c in results:
                            if c.get("instrumental", False):
                                c_dur = c.get("duration")
                                diff = abs(c_dur - target_dur) if (c_dur and target_dur > 0) else 0.0
                                if target_dur <= 0 or diff <= 15.0 or c_dur is None:
                                    instrumental_match = True
                                    break
            except Exception as e_search:
                logger.debug(f"LRCLIB search query '{q}' error: {e_search}")

        if instrumental_match:
            logger.info(f"LRCLIB search fallback determined '{track.title}' is instrumental")
            return LyricsData(
                synced_lyrics="[00:00.00] ♪ Instrumental ♪",
                plain_lyrics="[Instrumental]",
                instrumental=True
            )

        return None

    def save_companion_lrc(
        self,
        audio_file_path: str,
        lyrics_data: LyricsData,
        target_dir: Optional[str] = None
    ) -> Optional[str]:
        """
        Saves companion .lrc file.
        If target_dir is specified (e.g. lyrics/ subfolder), saves it there;
        otherwise saves in the same folder as the audio file.
        """
        if not lyrics_data or not lyrics_data.synced_lyrics:
            return None

        base_name = os.path.splitext(os.path.basename(audio_file_path))[0]
        if target_dir:
            os.makedirs(target_dir, exist_ok=True)
            lrc_path = os.path.join(target_dir, f"{base_name}.lrc")
        else:
            parent_dir = os.path.dirname(audio_file_path)
            lrc_path = os.path.join(parent_dir, f"{base_name}.lrc")

        try:
            with open(lrc_path, "w", encoding="utf-8", newline="") as f:
                f.write(lyrics_data.synced_lyrics)
            logger.info(f"Saved companion .lrc to {lrc_path}")
            return lrc_path
        except Exception as e:
            logger.error(f"Failed to write .lrc file {lrc_path}: {e}")
            return None

    def save_lrc_file(self, synced_lyrics: str, lrc_path: str) -> Optional[str]:
        """Writes raw synchronized LRC text directly to the specified lrc_path."""
        if not synced_lyrics or not lrc_path:
            return None
        try:
            os.makedirs(os.path.dirname(os.path.abspath(lrc_path)), exist_ok=True)
            with open(lrc_path, "w", encoding="utf-8", newline="") as f:
                f.write(synced_lyrics)
            return lrc_path
        except Exception as e:
            logger.error(f"Failed to write .lrc file {lrc_path}: {e}")
            return None

    def translate_lyrics(self, lines: list[str], target_lang: str = "en") -> list[str]:
        """
        Translates a list of lyric lines into the target language ('en' for English, 'fa' for Persian).
        Uses persistent local disk caching in <cache_dir>/lyrics_translations/ and multi-parameter
        Google Translate Chrome Dictionary API requests with per-line fallback.
        """
        import hashlib
        import json
        import re
        from core.paths import get_cache_dir

        lang = (target_lang or "").strip().lower()
        if lang in ("english", "en-us", "en-gb"):
            lang = "en"
        elif lang in ("persian", "farsi", "fa-ir", "فارسی"):
            lang = "fa"

        if not lines or lang not in ("en", "fa"):
            return list(lines)

        cache_dir = os.path.join(str(get_cache_dir()), "lyrics_translations")
        os.makedirs(cache_dir, exist_ok=True)

        # Clean up any legacy v1 cache files that may contain invalid responses
        try:
            for fname in os.listdir(cache_dir):
                if fname.startswith("trans_") and not fname.startswith("trans_v2_"):
                    try:
                        os.remove(os.path.join(cache_dir, fname))
                    except Exception:
                        pass
        except Exception:
            pass

        payload_hash = hashlib.sha1(
            (f"v2||{lang}||" + "\n".join(lines)).encode("utf-8", errors="replace")
        ).hexdigest()[:20]
        cache_file = os.path.join(cache_dir, f"trans_v2_{lang}_{payload_hash}.json")

        if os.path.isfile(cache_file):
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    cached = json.load(f)
                if (
                    isinstance(cached, list)
                    and len(cached) == len(lines)
                    and not any("PLEASE SELECT TWO DISTINCT" in str(x).upper() for x in cached)
                ):
                    return [str(x) for x in cached]
            except Exception:
                pass

        # Identify unique translatable lines (skip empty, instrumental markers, or lines already in target script)
        unique_lines: list[str] = []
        seen_set: set[str] = set()
        for raw_line in lines:
            cleaned = (raw_line or "").strip()
            if not cleaned:
                continue
            stripped_notes = cleaned.strip("♪♫ \t-—•*")
            if not stripped_notes or stripped_notes.lower() in ("[instrumental]", "instrumental"):
                continue
            # If translating to Persian and line is already predominantly Persian/Arabic script, skip network call
            if lang == "fa" and re.search(r'[\u0600-\u06FF]', stripped_notes) and not re.search(r'[A-Za-z\u3040-\u30FF\u4E00-\u9FFF]', stripped_notes):
                continue
            if cleaned not in seen_set:
                seen_set.add(cleaned)
                unique_lines.append(cleaned)

        if not unique_lines:
            return list(lines)

        translation_map: dict[str, str] = {}

        # Translate in batches of 30 unique lines via multi-q POST
        batch_size = 30
        for start_i in range(0, len(unique_lines), batch_size):
            batch = unique_lines[start_i: start_i + batch_size]
            translated_batch = self._translate_batch_gtx(batch, lang, expected_count=len(batch))
            if translated_batch and len(translated_batch) == len(batch):
                for orig_l, trans_l in zip(batch, translated_batch):
                    translation_map[orig_l] = self._sanitize_translated_line(orig_l, trans_l)
            else:
                for orig_l in batch:
                    single_res = self._translate_single_line(orig_l, lang)
                    translation_map[orig_l] = self._sanitize_translated_line(orig_l, single_res)

        result_lines: list[str] = []
        for raw_line in lines:
            cleaned = (raw_line or "").strip()
            result_lines.append(translation_map.get(cleaned, raw_line))

        try:
            if any(r != o for r, o in zip(result_lines, lines)):
                with open(cache_file, "w", encoding="utf-8") as f:
                    json.dump(result_lines, f, ensure_ascii=False, indent=2)
        except Exception as e_cache:
            logger.debug(f"Could not write lyrics translation cache: {e_cache}")

        return result_lines

    @staticmethod
    def _sanitize_translated_line(orig_line: str, trans_line: Optional[str]) -> str:
        if not trans_line or not isinstance(trans_line, str):
            return orig_line
        cleaned = trans_line.strip()
        upper = cleaned.upper()
        if (
            not cleaned
            or "PLEASE SELECT TWO DISTINCT" in upper
            or "MYMEMORY WARNING" in upper
            or "QUERY LENGTH LIMIT" in upper
            or "INVALID LANGUAGE PAIR" in upper
        ):
            return orig_line
        return cleaned

    def _translate_batch_gtx(self, batch_lines: list[str] | str, target_lang: str, expected_count: int = 1) -> Optional[list[str]]:
        """
        Translates a list of lyric lines in a single HTTP request using Google's
        clients5 dict-chrome-ex multi-q endpoint, guaranteeing 1-to-1 line alignment.
        """
        if isinstance(batch_lines, str):
            lines_list = [l for l in batch_lines.split("\n")]
        else:
            lines_list = list(batch_lines)

        if not lines_list:
            return []

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
        }

        # Primary: clients5.google.com multi-q POST (returns 1-to-1 array per 'q' item)
        try:
            url = "https://clients5.google.com/translate_a/t"
            params = {
                "client": "dict-chrome-ex",
                "sl": "auto",
                "tl": target_lang,
            }
            form_data = [("q", line) for line in lines_list]
            resp = self.session.post(url, params=params, data=form_data, headers=headers, timeout=12)
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list) and len(data) == len(lines_list):
                    out: list[str] = []
                    for orig_l, item in zip(lines_list, data):
                        if isinstance(item, list) and item:
                            tr_text = str(item[0] or "").strip()
                            src_lang = str(item[1] or "").strip().lower() if len(item) > 1 else ""
                            if src_lang == target_lang:
                                out.append(orig_l)
                            else:
                                out.append(tr_text or orig_l)
                        elif isinstance(item, str):
                            out.append(item.strip() or orig_l)
                        else:
                            out.append(orig_l)
                    if len(out) == expected_count:
                        return out
        except Exception as e:
            logger.debug(f"clients5 batch translation error ({target_lang}): {e}")

        # Secondary: translate.googleapis.com with explicit indexed delimiter
        try:
            delim = " ||| "
            joined = delim.join(lines_list)
            url2 = "https://translate.googleapis.com/translate_a/single"
            params2 = {
                "client": "gtx",
                "sl": "auto",
                "tl": target_lang,
                "dt": "t",
                "q": joined,
            }
            resp2 = self.session.get(url2, params=params2, headers=headers, timeout=10)
            if resp2.status_code == 200:
                data2 = resp2.json()
                if isinstance(data2, list) and data2 and isinstance(data2[0], list):
                    full_tr = "".join(
                        str(seg[0]) for seg in data2[0] if isinstance(seg, list) and seg and seg[0] is not None
                    )
                    parts = [p.strip() for p in full_tr.split("|||")]
                    if len(parts) == expected_count:
                        return parts
        except Exception as e2:
            logger.debug(f"googleapis fallback translation error ({target_lang}): {e2}")

        return None

    def _translate_single_line(self, text: str, target_lang: str) -> str:
        """Translates a single lyric line via clients5/GTX."""
        res = self._translate_batch_gtx([text], target_lang, expected_count=1)
        if res and res[0]:
            return self._sanitize_translated_line(text, res[0])
        return text

