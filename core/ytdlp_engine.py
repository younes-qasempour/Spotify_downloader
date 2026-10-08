import os
import re
import time
import shutil
import logging
import difflib
from dataclasses import dataclass, field
from typing import Optional, Callable, Dict, Any, List, Tuple
import yt_dlp

from core.spotify_client import TrackMetadata
from core.utils import clean_watermarks, format_bytes, ensure_ffmpeg
from core.config import config
from core.paths import get_app_data_dir, get_resource_path

logger = logging.getLogger("core.ytdlp")


@dataclass
class YtdlpSource:
    video_id: str
    title: str
    duration: int
    url: str
    audio_format: str  # "opus" or "m4a"
    candidate_urls: List[str] = field(default_factory=list)


class YtdlpEngine:
    """
    High-Precision YouTube / YouTube Music Audio Resolution & Download Engine using yt-dlp.
    Implements:
    - Advanced title normalization stripping featured artists, remasters, and soundtrack tags
    - Targeted multi-query generation (auto-generated Topic audio, official audio, clean search)
    - Anti-false-positive scoring with Levenshtein title similarity & word token matching
    - Strict version modifier validation (penalizing/rejecting unwanted mix, live, acoustic, cover)
    - Foreign Topic channel disqualification (preventing fake cover channels like Jaco-Topic from winning)
    - Early high-confidence stop for verified Topic/official audio master releases
    - Multi-candidate resilience with validated candidate fallbacks
    - Clean native audio extraction (Opus/M4A) via FFmpeg postprocessors
    - Real-time progress, speed, ETA, pause/resume, and cancellation hooks
    """

    DURATION_TOLERANCE_SEC = 25.0

    def __init__(self, output_dir: str = ""):
        self.output_dir = output_dir
        self.ffmpeg_path = ensure_ffmpeg()

    def _get_ydl_auth_opts(self) -> Dict[str, Any]:
        """Extracts cookiefile, proxy, and ffmpeg configurations for yt-dlp."""
        opts: Dict[str, Any] = {}
        # 1. Cookies file check
        cookie_file = config.get("download.cookies_file", "").strip()
        if not cookie_file or not os.path.isfile(cookie_file):
            root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            app_data_dir = str(get_app_data_dir())
            for cand in [
                os.path.join(app_data_dir, "cookies.txt"),
                os.path.join(app_data_dir, "youtube_cookies.txt"),
                str(get_resource_path("cookies.txt")),
                os.path.join(root_dir, "cookies.txt"),
                os.path.join(root_dir, "youtube_cookies.txt"),
                "cookies.txt",
                "youtube_cookies.txt"
            ]:
                if os.path.isfile(cand):
                    cookie_file = cand
                    break

        if cookie_file and os.path.isfile(cookie_file):
            opts["cookiefile"] = cookie_file
            logger.info(f"Using YouTube cookies file: {cookie_file}")

        # 2. Proxy check
        proxy = config.get("download.proxy", "").strip()
        if not proxy:
            for env_key in ("HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY", "https_proxy", "http_proxy", "all_proxy"):
                val = os.environ.get(env_key)
                if val:
                    proxy = val
                    break
        if proxy:
            opts["proxy"] = proxy
            logger.info(f"Using proxy for yt-dlp: {proxy}")

        if not self.ffmpeg_path:
            self.ffmpeg_path = ensure_ffmpeg()
        if self.ffmpeg_path:
            opts["ffmpeg_location"] = self.ffmpeg_path

        return opts

    @staticmethod
    def _normalize_text(text: str) -> str:
        """Lowercases, removes punctuation, and normalizes whitespace."""
        t = text.lower()
        t = re.sub(r'[^\w\s]', ' ', t)
        return re.sub(r'\s+', ' ', t).strip()

    @staticmethod
    def _clean_title_for_search(raw_title: str) -> Tuple[str, List[str], Dict[str, bool]]:
        """
        Parses a Spotify track title into:
        - core_title: the pure fundamental title of the song
        - featured_artists: list of featured artists extracted from title
        - flags: dictionary of version attributes (is_remaster, is_live, is_acoustic, is_remix, is_instrumental, is_radio_edit)
        """
        title = raw_title.strip()
        flags = {
            "is_remaster": False,
            "is_live": False,
            "is_acoustic": False,
            "is_remix": False,
            "is_instrumental": False,
            "is_radio_edit": False
        }

        lower_t = title.lower()
        if any(k in lower_t for k in ["remaster", "remastered", "anniversary"]):
            flags["is_remaster"] = True
        if any(k in lower_t for k in ["live", "in concert", "live at", "live from", "unplugged"]):
            flags["is_live"] = True
        if "acoustic" in lower_t:
            flags["is_acoustic"] = True
        if any(k in lower_t for k in ["remix", "club mix", "extended mix", "vip mix", "dub mix"]):
            flags["is_remix"] = True
        if any(k in lower_t for k in ["instrumental", "karaoke"]):
            flags["is_instrumental"] = True
        if "radio edit" in lower_t or "short edit" in lower_t:
            flags["is_radio_edit"] = True

        featured_artists: List[str] = []
        feat_patterns = [
            r'[\(\[]\s*(?:feat\.?|ft\.?|with|featuring)\s+([^\)\]]+)[\)\]]',
            r'[\-\–\—]\s*(?:feat\.?|ft\.?|with|featuring)\s+([^\-\–\—]+)$',
        ]
        for pat in feat_patterns:
            m = re.search(pat, title, flags=re.IGNORECASE)
            if m:
                raw_feats = m.group(1)
                feats = re.split(r'[,&]|\band\b', raw_feats)
                for f in feats:
                    clean_f = f.strip()
                    if clean_f and clean_f.lower() not in [x.lower() for x in featured_artists]:
                        featured_artists.append(clean_f)

        # Strip features from core title
        core = re.sub(r'[\(\[]\s*(?:feat\.?|ft\.?|with|featuring)\b[^\)\]]*[\)\]]', '', title, flags=re.IGNORECASE)
        core = re.sub(r'[\-\–\—]\s*(?:feat\.?|ft\.?|with|featuring)\b.*$', '', core, flags=re.IGNORECASE)

        # Strip remaster / anniversary tags
        core = re.sub(r'[\(\[]\s*(?:\d{4}\s+)?remaster(?:ed)?(?:\s+\d{4})?(?:\s+version)?\s*[\)\]]', '', core, flags=re.IGNORECASE)
        core = re.sub(r'[\-\–\—]\s*(?:\d{4}\s+)?remaster(?:ed)?(?:\s+\d{4})?(?:\s+version)?\s*$', '', core, flags=re.IGNORECASE)
        core = re.sub(r'[\(\[]\s*anniversary(?:\s+edition)?\s*[\)\]]', '', core, flags=re.IGNORECASE)
        core = re.sub(r'[\-\–\—]\s*anniversary(?:\s+edition)?\s*$', '', core, flags=re.IGNORECASE)

        # Strip soundtrack / movie / TV / series subtitles in parentheses/brackets
        core = re.sub(r'[\(\[]\s*(?:music\s+)?(?:from|featured in|soundtrack|theme|ost|score|original series)\b[^\)\]]*[\)\]]', '', core, flags=re.IGNORECASE)

        # Strip movie / soundtrack / edition / series trailing tags after separators
        for sep in [" - ", " – ", " — "]:
            if sep in core:
                parts = core.split(sep)
                if len(parts) >= 2:
                    p1 = parts[0].strip()
                    p2 = sep.join(parts[1:]).strip().lower()
                    soundtrack_keywords = [
                        "from ", "soundtrack", "motion picture", "version", "edition", "deluxe",
                        "series", "original score", "music from", "ost", "theme", "vol.", "vol ",
                        "spider-man", "netflix", "hbo", "anime", "original soundtrack"
                    ]
                    if any(k in p2 for k in soundtrack_keywords):
                        core = p1
                        break

        core = re.sub(r'\s+', ' ', core).strip()
        return core, featured_artists, flags

    def _score_candidate(
        self,
        cand: Dict[str, Any],
        all_artists: List[str],
        core_title: str,
        raw_title: str,
        flags: Dict[str, bool],
        target_dur: float
    ) -> Tuple[float, str]:
        """
        Calculates high-accuracy confidence score for a candidate video against target track metadata.
        Returns (score, debug_reason). Positive score indicates a valid candidate.
        """
        cand_title = cand.get("title", "")
        cand_lower = cand_title.lower()
        uploader = (cand.get("uploader") or cand.get("channel") or "").strip()
        uploader_lower = uploader.lower()
        cand_dur = cand.get("duration") or 0
        diff = abs(cand_dur - target_dur)

        # 1. Hard Disqualifications
        # Exclude duration mismatch > 25 seconds for standard tracks
        if diff > self.DURATION_TOLERANCE_SEC and target_dur < 600:
            return -999.0, f"Duration mismatch too high ({diff:.1f}s > {self.DURATION_TOLERANCE_SEC}s)"

        # Hard rejection for known cover / tribute / karaoke phrases
        cover_tribute_phrases = [
            "originally performed by", "in the style of", "as made famous by",
            "originally by", "made popular by", "tribute to", "vocal version",
            "piano version", "instrumental version", "backing track", "minus one",
            "guitar cover", "drum cover", "piano cover", "vocal cover", "bass cover",
            "cover by", "covered by", "how to play", "tutorial", "synthesizer cover"
        ]
        if any(p in cand_lower for p in cover_tribute_phrases):
            return -999.0, "Cover / tribute / karaoke marker detected"

        hard_unwanted = [
            "karaoke", "instrumental", "cover", "workout", "slowed", "reverb",
            "nightcore", "8d audio", "parody", "reaction", "歌ってみた", "踊ってみた",
            "カラオケ", "ニコカラ", "練習用", "オフボーカル", "off vocal", "off-vocal",
            "弾いてみた", "叩いてみた", "吹いてみた", "アレンジ", "耳コピ", "オルゴール", "カバー"
        ]
        for uw in hard_unwanted:
            if uw in cand_lower and uw not in core_title.lower() and uw not in raw_title.lower():
                return -999.0, f"Unwanted modifier: {uw}"

        # 2. Artist verification
        norm_artists = [self._normalize_text(a) for a in all_artists if a]
        cand_title_norm = self._normalize_text(cand_title)
        uploader_norm = self._normalize_text(uploader)
        desc = (cand.get("description") or "").strip()
        desc_norm = self._normalize_text(desc)

        artist_in_channel = any(a in uploader_norm for a in norm_artists)
        artist_in_title = any(a in cand_title_norm for a in norm_artists)
        artist_in_desc = any(a in desc_norm for a in norm_artists)
        is_topic_channel = "topic" in uploader_lower or "topic" in cand_lower
        is_various_artists = "various artists" in uploader_lower
        is_cjk_title = bool(re.search(r'[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uff66-\uff9f\uac00-\ud7af]', core_title))
        is_official_channel = (
            cand.get("channel_is_verified", False)
            or any(lbl in uploader_lower for lbl in (
                "official", "vevo", "records", "entertainment", "sony music",
                "universal music", "warner", "avex", "channel", "music video", "label"
            ))
        )
        is_official_delivery = (
            "provided to youtube by" in desc.lower()
            or "auto-generated by youtube" in desc.lower()
            or "auto-generated" in cand_lower
        )

        norm_core = self._normalize_text(core_title)
        norm_raw = self._normalize_text(raw_title)

        # Detect native artist prefix (e.g. "あいみょん - マリーゴールド", "菅田将暉 『さよならエレジー』")
        native_artist_prefix = ""
        for sep in [" - ", " – ", " — ", " : ", " 『", " 「", " / "]:
            if sep in cand_title:
                prefix = cand_title.split(sep, 1)[0].strip()
                remainder = cand_title.split(sep, 1)[1].strip()
                if norm_core in self._normalize_text(remainder):
                    native_artist_prefix = self._normalize_text(prefix)
                    break

        native_artist_match = bool(native_artist_prefix) and (
            native_artist_prefix in uploader_norm
            or uploader_norm in native_artist_prefix
            or is_official_channel
        )

        artist_verified = (
            artist_in_channel
            or artist_in_title
            or artist_in_desc
            or native_artist_match
            or (is_cjk_title and (is_official_channel or is_topic_channel or norm_core in cand_title_norm))
        )

        # Strict check: Candidate must mention artist in channel/title/desc or be verified native/official delivery
        if not (artist_verified or (is_topic_channel and is_various_artists)):
            return -999.0, "Artist not found in channel, title, or description"

        # Foreign Topic Channel Filter:
        # If candidate is a Topic channel, it MUST belong to the artist, be official, or be Various Artists
        # Prevents third-party cover artists (e.g. Jaco-Topic, Release-Topic) from masquerading as official
        if is_topic_channel and not (artist_in_channel or artist_in_desc or is_cjk_title) and not is_various_artists:
            return -999.0, "Foreign topic channel (unofficial cover)"

        # 3. Title Matching
        # Strip artist from candidate title if formatted like "Artist - Title"
        cand_title_clean = cand_title
        for sep in [" - ", " – ", " — ", " : ", " 『", " 「", " / "]:
            if sep in cand_title_clean:
                parts = cand_title_clean.split(sep, 1)
                p0_norm = self._normalize_text(parts[0])
                if any(a in p0_norm for a in norm_artists) or (native_artist_prefix and p0_norm == native_artist_prefix):
                    cand_title_clean = parts[1]
                    break

        # Strip standard publication tags
        cand_core = re.sub(r'[\(\[]\s*(?:official\s+)?(?:music\s+)?(?:audio|video|lyrics?|hd|4k|visualizer)\s*[\)\]]', '', cand_title_clean, flags=re.IGNORECASE)
        cand_core = re.sub(r'[\-\–\—]\s*(?:official\s+)?(?:music\s+)?(?:audio|video|lyrics?|hd|4k|visualizer)\s*$', '', cand_core, flags=re.IGNORECASE)
        cand_core = re.sub(r'[\(\[]\s*(?:\d{4}\s+)?remaster(?:ed)?(?:\s+\d{4})?\s*[\)\]]', '', cand_core, flags=re.IGNORECASE)
        cand_core = re.sub(r'[\-\–\—]\s*(?:\d{4}\s+)?remaster(?:ed)?(?:\s+\d{4})?\s*$', '', cand_core, flags=re.IGNORECASE)
        cand_core = re.sub(r'[\(\[『「].*?[\)\]』」]', '', cand_core).strip()

        norm_cand_core = self._normalize_text(cand_core)

        seq_sim = difflib.SequenceMatcher(None, norm_core, norm_cand_core).ratio()
        raw_seq_sim = difflib.SequenceMatcher(None, norm_raw, norm_cand_core).ratio()
        best_sim = max(seq_sim, raw_seq_sim)

        core_words = set(norm_core.split())
        cand_words = set(norm_cand_core.split())
        matched_words = core_words.intersection(cand_words)
        word_overlap = len(matched_words) / max(len(core_words), 1)

        missing_words = core_words - cand_words
        sig_missing = [w for w in missing_words if len(w) > 2]

        extra_words = cand_words - core_words
        artist_words = set(" ".join(norm_artists).split())
        if native_artist_prefix:
            artist_words.update(native_artist_prefix.split())
        stop_words = {"the", "a", "an", "and", "or", "of", "in", "on", "at", "to", "for", "with", "feat", "ft", "by"}
        sig_extra = [w for w in extra_words if w not in artist_words and w not in stop_words and len(w) > 2]

        # Base title score (max 50)
        if norm_core == norm_cand_core or norm_core in norm_cand_core or norm_raw in norm_cand_core:
            title_score = 50.0
        elif (is_official_delivery or is_topic_channel or is_official_channel) and (artist_in_desc or artist_in_channel or artist_in_title) and diff <= 3.0:
            # Multi-lingual official delivery match where title is English/Romaji (e.g. Sheena Ringo - Marunouchi Sadistic)
            title_score = 48.0
        else:
            title_score = (best_sim * 35.0) + (word_overlap * 15.0)

        # Penalize missing significant core words
        if sig_missing:
            title_score -= len(sig_missing) * 15.0

        # Penalize extra unexplained words (e.g. "Butch Vig Mix")
        if sig_extra:
            title_score -= len(sig_extra) * 8.0

        if title_score < 10.0:
            return -999.0, f"Title score too low ({title_score:.1f})"

        # 4. Version Modifiers Scoring
        version_penalty = 0.0
        cand_lower_raw = cand_title.lower()

        # Check mix / remix
        cand_has_mix = any(m in cand_lower_raw for m in ["mix", "remix", "dub", "edit"])
        if cand_has_mix and not flags["is_remix"] and not flags["is_radio_edit"]:
            version_penalty -= 35.0

        # Check live
        cand_has_live = any(l in cand_lower_raw for l in ["live", "concert", "tour", "unplugged", "live at", "live from"])
        if cand_has_live and not flags["is_live"]:
            version_penalty -= 40.0
        elif cand_has_live and flags["is_live"]:
            version_penalty += 20.0

        # Check acoustic
        cand_has_acoustic = "acoustic" in cand_lower_raw
        if cand_has_acoustic and not flags["is_acoustic"]:
            version_penalty -= 30.0
        elif cand_has_acoustic and flags["is_acoustic"]:
            version_penalty += 20.0

        # 5. Channel and Delivery Scoring
        channel_score = 0.0
        if is_topic_channel:
            if artist_in_channel:
                channel_score = 45.0  # Authentic artist Topic channel
            else:
                channel_score = 25.0  # Various Artists soundtrack topic
        elif artist_in_channel:
            channel_score = 35.0  # Official artist channel
        elif any(lbl in uploader_lower for lbl in ("vevo", "records", "entertainment", "sony music", "universal music", "warner")):
            channel_score = 30.0  # Official record label
        else:
            channel_score = 5.0   # Third party channel

        # Auto-generated official release bonus
        desc = cand.get("description", "") or ""
        if "provided to youtube by" in desc.lower() or "auto-generated by youtube" in desc.lower() or "auto-generated" in cand_lower:
            channel_score += 15.0

        # 6. Duration Proximity Scoring
        if diff <= 1.5:
            dur_score = 35.0 - (diff * 2.0)
        elif diff <= 3.0:
            dur_score = 30.0 - (diff * 2.5)
        elif diff <= 6.0:
            dur_score = 20.0 - (diff * 2.0)
        elif diff <= 12.0:
            dur_score = 10.0 - diff
        else:
            dur_score = -diff

        total_score = title_score + version_penalty + channel_score + dur_score
        reason = f"title={title_score:.1f}, ver={version_penalty:.1f}, chan={channel_score:.1f}, dur={dur_score:.1f}"
        return total_score, reason

    def resolve_track(
        self,
        track: TrackMetadata,
        cancel_check: Optional[Callable[[], bool]] = None
    ) -> Optional[YtdlpSource]:
        """
        Queries YouTube for matching audio tracks with high accuracy.
        Generates targeted queries, applies anti-false-positive scoring,
        and returns YtdlpSource with validated candidate URLs.
        Respects cancel_check to abort immediately if download is stopped.
        """
        if cancel_check and cancel_check():
            return None

        clean_raw_title = clean_watermarks(track.title).strip()
        core_title, feat_artists, flags = self._clean_title_for_search(clean_raw_title)
        artist = track.primary_artist.strip()
        clean_artist = re.sub(r'^(?:the|a)\s+', '', artist, flags=re.IGNORECASE).strip()

        all_artists: List[str] = list(track.artists or [artist])
        for fa in feat_artists:
            if fa not in all_artists:
                all_artists.append(fa)
        if clean_artist not in all_artists:
            all_artists.append(clean_artist)

        # Build clean prioritized search queries without negation or quoting pitfalls
        isrc = getattr(track, "isrc", "").strip()
        queries: List[str] = []
        if isrc:
            queries.append(f'ytsearch3:{isrc}')

        queries.extend([
            f'ytsearch5:{artist} - {core_title} auto-generated',
            f'ytsearch5:{artist} {core_title} Topic',
            f'ytsearch5:{artist} {core_title} official audio',
            f'ytsearch5:{artist} {core_title}',
        ])
        if feat_artists:
            queries.append(f'ytsearch5:{artist} {" ".join(feat_artists)} {core_title}')
        if clean_artist != artist:
            queries.append(f'ytsearch5:{clean_artist} {core_title}')

        is_cjk_title = bool(re.search(r'[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uff66-\uff9f\uac00-\ud7af]', core_title))
        if is_cjk_title:
            queries.append(f'ytsearch5:{core_title}')
            queries.append(f'ytsearch5:{core_title} {artist}')
            queries.append(f'ytsearch5:{core_title} Topic')

        # Deduplicate queries while preserving order
        dedup_queries: List[str] = []
        for q in queries:
            if q not in dedup_queries:
                dedup_queries.append(q)
        queries = dedup_queries

        node_path = shutil.which("node")
        ydl_opts: Dict[str, Any] = {
            "extract_flat": True,
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "remote_components": {"ejs:github"},
        }
        if node_path:
            ydl_opts["js_runtimes"] = {"node": {"path": node_path}}
        ydl_opts.update(self._get_ydl_auth_opts())

        candidates: Dict[str, Dict[str, Any]] = {}

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                for query in queries:
                    if cancel_check and cancel_check():
                        return None
                    try:
                        logger.info(f"Searching YouTube with query: '{query}'")
                        res = ydl.extract_info(query, download=False)
                        entries = res.get("entries", []) if res else []

                        for entry in entries:
                            if not entry:
                                continue
                            cand_id = entry.get("id")
                            if not cand_id or cand_id in candidates:
                                continue

                            cand_dur = entry.get("duration")
                            if cand_dur is None:
                                continue

                            score, reason = self._score_candidate(
                                cand=entry,
                                all_artists=all_artists,
                                core_title=core_title,
                                raw_title=clean_raw_title,
                                flags=flags,
                                target_dur=track.duration_sec
                            )

                            if score > 0:
                                candidates[cand_id] = {
                                    "id": cand_id,
                                    "title": entry.get("title", ""),
                                    "uploader": entry.get("uploader") or entry.get("channel") or "",
                                    "duration": int(cand_dur),
                                    "diff": abs(cand_dur - track.duration_sec),
                                    "score": score,
                                    "reason": reason
                                }

                        # Early high-confidence stop check:
                        # Stop if an authentic Topic/Official delivery with close duration and no version penalty is found
                        best_so_far = max(candidates.values(), key=lambda x: x["score"]) if candidates else None
                        if best_so_far and best_so_far["score"] >= 120.0 and best_so_far["diff"] <= 2.5:
                            logger.info(f"Found immediate high-confidence official YouTube candidate: '{best_so_far['title']}' (ID: {best_so_far['id']}, score: {best_so_far['score']:.1f})")
                            break

                    except Exception as e_query:
                        logger.warning(f"Error querying YouTube for '{query}': {e_query}")

        except Exception as e_session:
            logger.error(f"YouTubeDL session error: {e_session}")

        if not candidates:
            logger.warning(f"No YouTube candidate met tolerance for '{track.title}'")
            return None

        # Sort valid candidates by score descending
        sorted_candidates = sorted(candidates.values(), key=lambda x: x["score"], reverse=True)
        best = sorted_candidates[0]
        # Only include valid positive-scoring candidate URLs for multi-candidate retry fallback
        candidate_urls = [f"https://www.youtube.com/watch?v={c['id']}" for c in sorted_candidates if c["score"] > 0]

        logger.info(f"Found {len(sorted_candidates)} validated YouTube candidate(s). Best: '{best['title']}' (ID: {best['id']}, dur: {best['duration']}s, diff: {best['diff']:.1f}s, score: {best['score']:.1f}, reason: {best['reason']})")
        return YtdlpSource(
            video_id=best["id"],
            title=best["title"],
            duration=best["duration"],
            url=f"https://www.youtube.com/watch?v={best['id']}",
            audio_format="opus",
            candidate_urls=candidate_urls
        )

    def download_track(
        self,
        source: YtdlpSource,
        output_template_without_ext: str,
        progress_callback: Optional[Callable[[float, str, str], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
        pause_wait: Optional[Callable[[], None]] = None
    ) -> Optional[str]:
        """
        Downloads the best audio stream directly to disk without lossy re-encoding.
        Captures postprocessed files via postprocessor_hooks and falls back across candidate URLs.
        """
        urls_to_try = source.candidate_urls if source.candidate_urls else [source.url]

        def _clean_part_files():
            base_dir = os.path.dirname(output_template_without_ext)
            base_file = os.path.basename(output_template_without_ext)
            if os.path.isdir(base_dir):
                for fname in os.listdir(base_dir):
                    if fname.startswith(base_file) and fname.endswith(".part"):
                        try:
                            os.remove(os.path.join(base_dir, fname))
                        except Exception:
                            pass

        for url in urls_to_try:
            if cancel_check and cancel_check():
                _clean_part_files()
                return None
            downloaded_file: Optional[str] = None
            _clean_part_files()

            def ydl_hook(d: Dict[str, Any]):
                nonlocal downloaded_file
                if cancel_check and cancel_check():
                    raise yt_dlp.utils.DownloadCancelled("Download cancelled by user.")
                if pause_wait:
                    pause_wait()

                status = d.get("status")
                if status == "downloading":
                    total_bytes = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                    downloaded = d.get("downloaded_bytes") or 0
                    speed = d.get("speed") or 0
                    eta = d.get("eta") or 0

                    percent = (downloaded / total_bytes * 100.0) if total_bytes > 0 else 0.0
                    speed_str = f"{format_bytes(speed)}/s" if speed else "-- KB/s"
                    eta_str = f"{int(eta) // 60:02d}:{int(eta) % 60:02d}" if eta else "--:--"

                    if progress_callback:
                        progress_callback(percent, speed_str, eta_str)

                elif status == "finished":
                    fname = d.get("filename")
                    if fname and os.path.isfile(fname):
                        downloaded_file = fname
                    if progress_callback:
                        progress_callback(100.0, "-- KB/s", "00:00")

            def ydl_pp_hook(d: Dict[str, Any]):
                nonlocal downloaded_file
                if d.get("status") == "finished":
                    fpath = d.get("info_dict", {}).get("filepath") or d.get("filename")
                    if fpath and os.path.isfile(fpath):
                        downloaded_file = fpath

            outtmpl = output_template_without_ext + ".%(ext)s"
            node_path = shutil.which("node")

            if not self.ffmpeg_path:
                self.ffmpeg_path = ensure_ffmpeg()
            postprocessors = []
            if self.ffmpeg_path:
                postprocessors.append({
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "best",
                })

            ydl_opts: Dict[str, Any] = {
                "format": "bestaudio/best",
                "outtmpl": outtmpl,
                "quiet": True,
                "no_warnings": True,
                "noplaylist": True,
                "continuedl": False,
                "overwrites": True,
                "no_color": True,
                "progress_hooks": [ydl_hook],
                "postprocessor_hooks": [ydl_pp_hook],
                "remote_components": {"ejs:github"},
                "postprocessors": postprocessors,
            }

            if node_path:
                ydl_opts["js_runtimes"] = {"node": {"path": node_path}}

            if self.ffmpeg_path:
                ydl_opts["ffmpeg_location"] = self.ffmpeg_path
            ydl_opts.update(self._get_ydl_auth_opts())

            start_time = time.time() - 1.0
            try:
                logger.info(f"Attempting yt-dlp download from: {url}")
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([url])

                # Check for newly written or updated file
                new_file = None
                if downloaded_file and os.path.isfile(downloaded_file):
                    new_file = downloaded_file
                else:
                    for ext in ["opus", "m4a", "webm", "mp3", "flac", "ogg"]:
                        candidate = f"{output_template_without_ext}.{ext}"
                        if os.path.isfile(candidate) and os.path.getmtime(candidate) >= start_time:
                            new_file = candidate
                            break

                if not new_file:
                    for ext in ["opus", "m4a", "webm", "mp3", "flac", "ogg"]:
                        candidate = f"{output_template_without_ext}.{ext}"
                        if os.path.isfile(candidate):
                            new_file = candidate
                            break

                if new_file and os.path.isfile(new_file):
                    # Clean up any stale conflicting audio extensions with the same base name
                    new_ext = os.path.splitext(new_file)[1].lower()
                    for ext in [".opus", ".m4a", ".webm", ".mp3", ".flac", ".ogg"]:
                        if ext != new_ext:
                            stale_path = f"{output_template_without_ext}{ext}"
                            if os.path.isfile(stale_path):
                                try:
                                    os.remove(stale_path)
                                    logger.info(f"Removed stale duplicate audio file: {stale_path}")
                                except Exception:
                                    pass
                    return new_file

            except yt_dlp.utils.DownloadCancelled:
                logger.info("yt-dlp download cancelled.")
                _clean_part_files()
                return None
            except Exception as e:
                _clean_part_files()
                logger.warning(f"Download candidate {url} failed: {e}. Trying next candidate...")

        logger.error("All YouTube download candidates failed.")
        return None
