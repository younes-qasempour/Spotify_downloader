import os
import re
import time
import json
import random
import logging
import subprocess
from dataclasses import dataclass
from typing import Optional, List, Dict, Any, Callable, Tuple
from urllib.parse import quote_plus, urljoin
import requests

from core.spotify_client import TrackMetadata
from core.utils import clean_watermarks, format_bytes, is_valid_audio_file, detect_audio_header

logger = logging.getLogger("core.musilon")


class MusilonVipError(Exception):
    """Raised when Musilon requires authentication or returns an unauthorized response."""
    pass


class MusilonRateLimitExceededError(MusilonVipError):
    """Raised when Musilon rejects a download due to rate limit or daily quota exceeded."""
    pass


class MusilonQualityUnavailableError(Exception):
    """Raised when the requested quality tier is not available for a specific track (HTTP 409)."""
    pass


@dataclass
class MusilonSource:
    track_id: str
    title: str
    artist: str
    quality_tier: str  # e.g. "Musilon FLAC 16", "Musilon FLAC 24", "Musilon 320k", "Musilon Standard"
    download_url: str
    file_extension: str  # "flac" or "ogg"
    station_url: str = ""
    isrc: str = ""
    quality_param: str = "lossless"  # "hires", "lossless", "high", "standard"


class MusilonEngine:
    """
    VIP / Premium Engine for Musilon (https://open.musilon.com / https://musilon.com).
    Supports:
    - Direct NextAuth credentials login & persistent session management
    - REST catalog search with smart anti-false-positive scoring & ISRC validation
    - Multi-tier quality resolution (FLAC 24-bit Hi-Res > FLAC 16-bit Lossless > OGG 320k > OGG 192k)
    - Automatic quality step-down fallback on 409 DOWNLOAD_QUALITY_UNAVAILABLE
    - Chunked streaming downloader with magic bytes verification & integrity validation
    - Rate-limit shield with sequential jitter and exponential backoff
    - Auto-reauthentication on session expiration
    """

    BASE_URL = "https://open.musilon.com"
    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    )

    UNWANTED_VERSION_MODIFIERS = [
        "instrumental", "karaoke", "acoustic", "workout mix", "workout",
        "remix", "live", "cover", "slowed", "speed up", "sped up",
        "reverb", "orchestral", "piano version", "tribute", "parody",
        "radio edit", "extended mix", "club mix", "dub mix"
    ]

    def __init__(self, session_cookie: str = "", username: str = "", password: str = "", enabled: bool = True):
        from core.config import config
        self.enabled = enabled
        self.session_cookie = (session_cookie or config.get("musilon.session_cookie", "")).strip()
        self.username = (username or config.get("musilon.username", "")).strip()
        self.password = (password or config.get("musilon.password", "")).strip()

        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": self.USER_AGENT,
            "Referer": f"{self.BASE_URL}/",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "fa-IR,fa;q=0.9,en-US;q=0.8,en;q=0.7",
            "sec-ch-ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
        })

        self._last_request_time = 0.0
        self._load_cookie_string(self.session_cookie)

    def set_credentials(self, session_cookie: str = "", username: str = "", password: str = "", enabled: bool = True):
        self.enabled = enabled
        self.session_cookie = session_cookie.strip()
        self.username = username.strip()
        self.password = password.strip()
        self._load_cookie_string(self.session_cookie)

    def _load_cookie_string(self, cookie_str: str):
        if not cookie_str:
            return

        clean = cookie_str.strip()
        if clean.lower().startswith("cookie:"):
            clean = clean[7:].strip()

        parts = clean.split(";")
        found_pair = False
        for part in parts:
            part = part.strip()
            if "=" in part:
                k, v = part.split("=", 1)
                k = k.strip().strip('"').strip("'")
                v = v.strip().strip('"').strip("'")
                self.session.cookies.set(k, v, domain="open.musilon.com")
                self.session.cookies.set(k, v, domain="musilon.com")
                found_pair = True

        if not found_pair and clean:
            # User might have pasted only the raw value of the next-auth session token
            self.session.cookies.set("__Secure-next-auth.session-token", clean, domain="open.musilon.com")
            self.session.cookies.set("next-auth.session-token", clean, domain="open.musilon.com")

    # -------------------------------------------------------------------------
    # Authentication & Session Verification
    # -------------------------------------------------------------------------
    def login_with_credentials(self, username: str = "", password: str = "") -> Tuple[bool, str]:
        """
        Attempts direct login to Musilon using NextAuth Directus Credentials flow.
        1. Queries /api/auth/csrf for CSRF token
        2. Submits credentials to /api/auth/callback/credentials
        3. Verifies session via /api/auth/session
        Returns: (success: bool, message: str)
        """
        user = (username or self.username).strip()
        pwd = (password or self.password).strip()

        if not user or not pwd:
            return False, "Username and password cannot be empty."

        try:
            self._rate_limit_shield()

            login_session = requests.Session()
            login_session.headers.update({
                "User-Agent": self.USER_AGENT,
                "Referer": f"{self.BASE_URL}/",
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "fa-IR,fa;q=0.9,en-US;q=0.8,en;q=0.7",
            })

            # Copy challenge cookies if present
            for c in self.session.cookies:
                if "__arcsjs" in c.name or "cf_" in c.name:
                    login_session.cookies.set(c.name, c.value, domain="open.musilon.com")
                    login_session.cookies.set(c.name, c.value, domain="musilon.com")

            # 1. Fetch CSRF token
            csrf_resp = login_session.get(f"{self.BASE_URL}/api/auth/csrf", timeout=12)
            if csrf_resp.status_code != 200:
                return False, f"Could not obtain CSRF token from Musilon (HTTP {csrf_resp.status_code})."

            csrf_token = csrf_resp.json().get("csrfToken", "")
            if not csrf_token:
                return False, "Musilon did not return a valid CSRF token."

            # 2. Submit credentials
            self._rate_limit_shield()
            data = {
                "csrfToken": csrf_token,
                "email": user,
                "password": pwd,
                "json": "true"
            }
            login_resp = login_session.post(
                f"{self.BASE_URL}/api/auth/callback/credentials",
                data=data,
                timeout=15
            )

            if login_resp.status_code not in (200, 302):
                err_msg = "Invalid username or password."
                try:
                    res_json = login_resp.json()
                    if "error" in res_json:
                        err_msg = res_json["error"]
                except Exception:
                    pass
                return False, f"Login failed: {err_msg}"

            # 3. Verify session
            sess_resp = login_session.get(f"{self.BASE_URL}/api/auth/session", timeout=10)
            user_info = sess_resp.json().get("user") if sess_resp.status_code == 200 else None

            if not user_info:
                return False, "Login failed: No active session created."

            display_name = user_info.get("display_name") or user_info.get("name") or user_info.get("first_name") or user

            # Transfer authenticated cookies to self.session
            for k, v in login_session.cookies.items():
                self.session.cookies.set(k, v, domain="open.musilon.com")
                self.session.cookies.set(k, v, domain="musilon.com")

            self.username = user
            self.password = pwd

            # Persist cookies to config
            try:
                from core.config import config
                cookie_dict = self.session.cookies.get_dict()
                cookie_str = "; ".join(f"{k}={v}" for k, v in cookie_dict.items())
                config.set("musilon.session_cookie", cookie_str)
                config.set("musilon.username", user)
                config.set("musilon.password", pwd)
                config.set("musilon.enabled", True)
            except Exception as e:
                logger.debug(f"Could not persist session cookies to config: {e}")

            logger.info(f"Successfully authenticated with Musilon account: {display_name} ({user})")
            return True, f"Successfully logged in as {display_name}."

        except Exception as e:
            logger.error(f"Error logging in to Musilon: {e}")
            return False, f"Login failed: {e}"

    def test_connection(self) -> Tuple[bool, bool, str]:
        """
        Tests connectivity and VIP authentication status with Musilon.
        Returns: (connected: bool, is_vip: bool, status_message: str)
        """
        try:
            r = self._request("GET", f"{self.BASE_URL}/api/auth/session", timeout=10, max_retries=2)
            connected = r.status_code == 200
            user_data = r.json().get("user") if connected else None
            is_authenticated = bool(user_data)

            # If not authenticated but credentials exist, attempt auto-login
            if not is_authenticated and self.username and self.password:
                logger.info("Musilon session unauthenticated; auto-authenticating with credentials...")
                login_ok, _ = self.login_with_credentials(self.username, self.password)
                if login_ok:
                    return self.test_connection()

            if is_authenticated:
                user_name = user_data.get("display_name") or user_data.get("name") or user_data.get("email") or "VIP User"
                
                # Check subscription status and download budget
                is_premium = True
                try:
                    r_sub = self._request("GET", f"{self.BASE_URL}/api/subscription/me", timeout=8)
                    if r_sub.status_code == 200:
                        is_premium = r_sub.json().get("data", {}).get("isPremium", True)
                except Exception:
                    pass

                budget_str = ""
                try:
                    r_budget = self._request("GET", f"{self.BASE_URL}/api/media/download-budget", timeout=8)
                    if r_budget.status_code == 200:
                        b_data = r_budget.json()
                        p_rem = b_data.get("premium", {}).get("remaining", 0)
                        p_lim = b_data.get("premium", {}).get("limit", 0)
                        s_rem = b_data.get("standard", {}).get("remaining", 0)
                        s_lim = b_data.get("standard", {}).get("limit", 0)
                        budget_str = f" | Daily Budget: {p_rem}/{p_lim} Lossless, {s_rem}/{s_lim} Standard"
                except Exception:
                    pass

                vip_text = "VIP Active" if is_premium else "Free Account"
                return True, is_premium, f"Connected! {vip_text} ({user_name}){budget_str}"

            elif connected:
                return True, False, "Connected to Musilon (Guest mode). Log in with account credentials in Settings to enable downloads."
            else:
                return False, False, f"Musilon returned HTTP {r.status_code}"

        except Exception as e:
            return False, False, f"Musilon connection failed: {e}"

    def ensure_vip_session(self, force: bool = False) -> bool:
        """
        Ensures the engine has a verified active VIP session.
        If force is True or session is inactive, re-authenticates with username/password.
        """
        if not self.username or not self.password:
            from core.config import config
            self.username = config.get("musilon.username", "")
            self.password = config.get("musilon.password", "")

        if not self.username or not self.password:
            logger.warning("Musilon credentials not configured; cannot auto-authenticate.")
            return False

        if force:
            logger.info("Forcing fresh Musilon VIP authentication with credentials...")
            ok, _ = self.login_with_credentials(self.username, self.password)
            return ok

        try:
            r = self._request("GET", f"{self.BASE_URL}/api/auth/session", timeout=8, max_retries=1)
            if r.status_code == 200:
                data = r.json()
                user = data.get("user") or {}
                if user and (user.get("email") or user.get("name") or user.get("display_name")) and not data.get("error"):
                    return True
        except Exception:
            pass

        logger.info("Musilon session inactive or expired; authenticating with credentials...")
        ok, _ = self.login_with_credentials(self.username, self.password)
        return ok

    def get_download_budget(self) -> Optional[Dict[str, Any]]:
        """
        Queries /api/media/download-budget to retrieve current daily download quota.
        Returns dict with 'premium' and 'standard' usage and limits, or None if unavailable.
        """
        try:
            r = self._request("GET", f"{self.BASE_URL}/api/media/download-budget", timeout=8)
            if r.status_code == 200:
                return r.json()
        except Exception as e:
            logger.debug(f"Could not retrieve download budget: {e}")
        return None

    def is_budget_exhausted(self, quality_tier: str = "lossless") -> bool:
        """
        Checks whether the daily download budget for the requested tier is exhausted.
        """
        budget = self.get_download_budget()
        if not budget:
            return False

        is_lossless = any(q in quality_tier.lower() for q in ("hires", "lossless", "flac"))
        if is_lossless:
            p_rem = budget.get("premium", {}).get("remaining", 1)
            return p_rem <= 0
        else:
            s_rem = budget.get("standard", {}).get("remaining", 1)
            return s_rem <= 0


    # -------------------------------------------------------------------------
    # Rate-Limit Shield (Sequential Jitter & Backoff)
    # -------------------------------------------------------------------------
    def _rate_limit_shield(self):
        """Enforces a strict 0.5s to 1.5s jitter between consecutive requests."""
        now = time.time()
        elapsed = now - self._last_request_time
        jitter = random.uniform(0.5, 1.2)
        if elapsed < jitter:
            time.sleep(jitter - elapsed)
        self._last_request_time = time.time()

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        """Wrapper around requests with challenge handling and fast backoff."""
        allow_404 = kwargs.pop("allow_404", False)
        max_retries = kwargs.pop("max_retries", 3)
        timeout = kwargs.pop("timeout", 15)
        backoff = 1.5

        for attempt in range(max_retries):
            self._rate_limit_shield()
            try:
                resp = self.session.request(method, url, timeout=timeout, **kwargs)

                # Check for ArvanCloud challenge
                if resp.status_code == 200 and "__arcsjs" in resp.text and "<script" in resp.text:
                    logger.info("ArvanCloud challenge detected. Solving challenge...")
                    if self._solve_arvancloud_challenge(resp.text):
                        return self._request(method, url, allow_404=allow_404, max_retries=2, timeout=timeout, **kwargs)

                if resp.status_code == 404 and allow_404:
                    return resp

                if resp.status_code in (429, 503):
                    logger.warning(f"Musilon rate-limited (HTTP {resp.status_code}). Backing off for {backoff:.1f}s...")
                    time.sleep(backoff)
                    backoff *= 1.5
                    continue

                return resp

            except (requests.RequestException, Exception) as e:
                logger.warning(f"Musilon request failed (attempt {attempt + 1}/{max_retries}): {e}")
                if attempt == max_retries - 1:
                    raise e
                time.sleep(backoff)
                backoff *= 1.5

        raise RuntimeError(f"Max retries reached for {url}")

    def _solve_arvancloud_challenge(self, html_content: str) -> bool:
        """Solves ArvanCloud JavaScript challenge using headless Node.js."""
        try:
            scripts = re.findall(r'<script[^>]*>(.*?)</script>', html_content, re.DOTALL)
            challenge_script = next((s for s in scripts if '__arcsjs' in s), None)
            if not challenge_script:
                return False

            node_code = f"""
            var exports = undefined; var module = undefined; var define = undefined;
            var window = this; var self = this;
            let cookies = {{}};
            let document = {{ addEventListener: (e, cb) => cb(), cookie: '' }};
            let location = {{ reload: () => {{}} }};
            Object.defineProperty(document, 'cookie', {{
                set: (val) => {{ 
                    let [k, v] = val.split(';')[0].split('='); 
                    cookies[k.trim()] = v ? v.trim() : ''; 
                }}
            }});
            function setTimeout(cb) {{ cb(); }}
            {challenge_script}
            console.log(JSON.stringify(cookies));
            """
            proc = subprocess.run(['node', '-e', node_code], capture_output=True, text=True, timeout=10)
            if proc.returncode == 0 and proc.stdout.strip():
                cookies = json.loads(proc.stdout.strip())
                for k, v in cookies.items():
                    self.session.cookies.set(k, v, domain="open.musilon.com")
                    self.session.cookies.set(k, v, domain="musilon.com")
                logger.info("Successfully solved and injected ArvanCloud challenge cookies.")
                return True
        except Exception as e:
            logger.error(f"Error solving ArvanCloud challenge: {e}")
        return False

    # -------------------------------------------------------------------------
    # Catalog Search & Context
    # -------------------------------------------------------------------------
    def _search_catalog(self, query: str) -> List[Dict[str, Any]]:
        """
        Queries Musilon REST catalog /api/search?q={query}.
        Returns structured track candidate objects.
        """
        if not query or not query.strip():
            return []

        try:
            url = f"{self.BASE_URL}/api/search?q={quote_plus(query.strip())}"
            resp = self._request("GET", url, timeout=12, allow_404=True)
            if resp.status_code != 200:
                return []

            data = resp.json()
            raw_tracks = list(data.get("tracks", []))

            # Include any tracks returned in the mixed/featured category
            for item in data.get("mixed", []):
                if isinstance(item, dict) and item.get("type") == "track":
                    raw_tracks.append(item)

            candidates: List[Dict[str, Any]] = []
            seen_ids = set()

            for t in raw_tracks:
                t_id = t.get("id", "")
                if not t_id or t_id in seen_ids:
                    continue
                seen_ids.add(t_id)

                artists = t.get("artistNames", [])
                if not artists and t.get("artistCredits"):
                    artists = [c.get("name") for c in t.get("artistCredits", []) if c.get("name")]

                candidates.append({
                    "id": t_id,
                    "title": clean_watermarks(t.get("name", "")),
                    "artist": ", ".join(artists) if artists else "",
                    "artists": artists,
                    "album": clean_watermarks(t.get("albumName", "")),
                    "isrc": (t.get("isrc") or "").strip(),
                    "lossless": t.get("lossless"),
                    "hires": t.get("hires"),
                    "popularity": t.get("popularity", 0.0),
                })

            return candidates

        except Exception as e:
            logger.debug(f"Musilon catalog search failed for '{query}': {e}")
            return []

    def _get_track_context(self, track_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieves detailed quality metadata for a track from /api/tracks/{id}/context.
        """
        if not track_id:
            return None
        try:
            url = f"{self.BASE_URL}/api/tracks/{track_id}/context"
            resp = self._request("GET", url, timeout=8, allow_404=True)
            if resp.status_code == 200:
                data = resp.json()
                return data.get("track")
        except Exception as e:
            logger.debug(f"Failed to fetch context for track {track_id}: {e}")
        return None

    # -------------------------------------------------------------------------
    # Scoring & Matching Logic
    # -------------------------------------------------------------------------
    def _score_candidate(self, track: TrackMetadata, cand: Dict[str, Any]) -> float:
        """
        Intelligently scores a Musilon candidate against target track metadata.
        - Exact ISRC match gives an automatic 999.0 score.
        - Strict Artist Validation: rejects foreign artists (-999.0).
        - Title Closeness: tokens and exact string matching.
        - Version Modifiers: penalizes unrequested remixes/live/acoustic/covers.
        """
        cand_isrc = (cand.get("isrc") or "").strip().upper()
        target_isrc = (track.isrc or "").strip().upper()

        # 1. Exact ISRC match = Instant 100% verified match
        if target_isrc and cand_isrc and target_isrc == cand_isrc:
            return 999.0

        cand_title = cand.get("title", "").lower()
        cand_author = cand.get("artist", "").lower()

        target_title = clean_watermarks(track.title).lower()
        target_artists = [track.primary_artist] + [a for a in (track.artists or []) if a != track.primary_artist]

        # 2. Artist Validation
        target_art_tokens = []
        for a in target_artists:
            clean_a = re.sub(r'^(?:the|a)\s+', '', a.lower(), flags=re.IGNORECASE).strip()
            target_art_tokens.extend([w for w in re.sub(r'[^\w\s]', ' ', clean_a).split() if len(w) > 1])

        cand_artists = [a.lower() for a in cand.get("artists", [])]
        if cand_author:
            cand_artists.append(cand_author)

        art_match = False
        for ca in cand_artists:
            ca_clean = re.sub(r'[^\w\s]', ' ', ca)
            ca_tokens = set(ca_clean.split())
            if any(tok in ca_tokens for tok in target_art_tokens):
                art_match = True
                break
            if any(clean_a in ca or ca in clean_a for clean_a in [re.sub(r'^(?:the|a)\s+', '', a.lower()).strip() for a in target_artists]):
                art_match = True
                break

        if cand_artists and not art_match:
            return -999.0

        score = 50.0 if art_match else 0.0

        # Exact artist match bonus
        if cand_author and art_match:
            author_clean = re.sub(r'\b(?:and|feat|ft|featuring|with|prod|the|a)\b', ' ', cand_author, flags=re.IGNORECASE)
            author_tokens = set(w for w in re.sub(r'[^\w\s]', ' ', author_clean).split() if len(w) > 1)
            target_set = set(target_art_tokens)
            if author_tokens and author_tokens.issubset(target_set):
                score += 35.0
            else:
                extra_tokens = author_tokens - target_set
                title_clean = re.sub(r'[^\w\s]', ' ', target_title)
                title_words = set(title_clean.split())
                unrequested_extra = [w for w in extra_tokens if w not in title_words]
                if unrequested_extra:
                    score -= 45.0

        # 3. Title Matching
        clean_feat_title = re.sub(r'[\(\[]\s*(?:feat\.?|ft\.?|with|prod\.?|featuring)\b[^\]\)]*[\)\]]', '', target_title, flags=re.IGNORECASE).strip()
        clean_feat_title = re.sub(r'[\-\–\—]\s*(?:feat\.?|ft\.?|with|prod\.?|featuring)\b.*$', '', clean_feat_title, flags=re.IGNORECASE).strip()
        base_title_clean = re.sub(r'[\(\[\{][^\)\]\}]*[\)\]\}]', '', clean_feat_title).strip()

        title_variants = [clean_feat_title, base_title_clean, target_title]
        for pm in re.finditer(r'[\(\[]([^\)\]]+)[\)\]]', clean_feat_title):
            sub = pm.group(1).strip()
            if sub and len(sub) > 2 and sub not in title_variants:
                title_variants.append(sub)

        for sep in (" - ", " / ", " | ", " : "):
            if sep in target_title:
                for part in target_title.split(sep):
                    p_str = part.strip()
                    if p_str and len(p_str) >= 2 and p_str not in title_variants:
                        title_variants.append(p_str)

        clean_cand_title = re.sub(r'[^\w\s]', ' ', cand_title).strip()
        cand_words = set(clean_cand_title.split())

        best_title_score = 0.0
        for variant in title_variants:
            v_score = 0.0
            clean_v = re.sub(r'[^\w\s]', ' ', variant).strip()
            v_words = [w for w in clean_v.split() if len(w) > 1]

            base_v = re.sub(r'[\(\[\-].*?(?:feat|ft|with|prod|remaster|version|from|bonus).*?[\)\]]?', '', variant).strip()
            base_v = re.sub(r'[^\w\s]', ' ', base_v).strip()
            base_v_words = [w for w in base_v.split() if len(w) > 1]

            if clean_v == clean_cand_title or base_v == clean_cand_title:
                v_score = 90.0
            elif v_words and all(w in cand_words for w in v_words):
                v_score = 70.0
            elif base_v_words and all(w in cand_words for w in base_v_words):
                v_score = 70.0
            elif cand_words and all(w in set(v_words) for w in cand_words):
                v_score = 65.0
            elif v_words:
                matched_words = sum(1 for w in v_words if w in cand_words)
                if matched_words >= max(1, len(v_words) - 1):
                    v_score = 45.0

            if v_score > best_title_score:
                best_title_score = v_score

        if best_title_score < 40.0:
            return -999.0

        score += best_title_score

        # 4. Version Modifier Penalties & Bonuses
        for mod in self.UNWANTED_VERSION_MODIFIERS:
            has_in_cand = (mod in cand_title) or (cand_author and mod in cand_author)
            has_in_target = (mod in target_title)
            if has_in_cand and not has_in_target:
                if mod in ("cover", "tribute", "karaoke", "like a version", "parody"):
                    score -= 90.0
                else:
                    score -= 70.0
            elif has_in_cand and has_in_target:
                score += 30.0

        if "bonus track" in target_title and "bonus track" in cand_title:
            score += 40.0

        return score

    # -------------------------------------------------------------------------
    # Track Resolution
    # -------------------------------------------------------------------------
    def resolve_track(
        self,
        track: TrackMetadata,
        cancel_check: Optional[Callable[[], bool]] = None
    ) -> Optional[MusilonSource]:
        """
        Searches Musilon catalog and resolves the best matching audio source.
        1. Multi-stage search across artist + title, base title, and full title.
        2. Evaluates ISRC precision match or intelligent scoring.
        3. Inspects quality options (FLAC 24-bit Hi-Res, FLAC 16-bit Lossless, OGG 320k).
        4. Constructs MusilonSource configured for direct streaming/download.
        """
        if not self.enabled:
            return None

        if cancel_check and cancel_check():
            return None

        # Verify or auto-authenticate session if credentials exist
        if self.username and self.password:
            self.ensure_vip_session()

        clean_title = clean_watermarks(track.title).strip()
        primary_artist = track.primary_artist.strip()

        simplified_artist = re.sub(r'^(?:the|a)\s+', '', primary_artist, flags=re.IGNORECASE).strip()
        clean_feat_title = re.sub(r'[\(\[]\s*(?:feat\.?|ft\.?|with|prod\.?|featuring)\b[^\]\)]*[\)\]]', '', clean_title, flags=re.IGNORECASE).strip()
        base_title = re.sub(r'[\(\[\-].*?(?:feat|ft|with|prod|remaster|version|from|motion picture|bonus).*?[\)\]]?', '', clean_feat_title, flags=re.IGNORECASE).strip()
        base_title = re.sub(r'[\(\[\{][^\)\]\}]*[\)\]\}]', '', base_title).rstrip(" -_~:").strip()

        candidate_pool: List[Dict[str, Any]] = []
        seen_ids = set()

        def add_candidates(cands: List[Dict[str, Any]]):
            for c in cands:
                cid = c.get("id")
                if cid and cid not in seen_ids:
                    seen_ids.add(cid)
                    candidate_pool.append(c)

        # Stage 1: Artist + Base Title
        if primary_artist and base_title:
            add_candidates(self._search_catalog(f"{primary_artist} {base_title}"))
        if simplified_artist and simplified_artist != primary_artist and base_title:
            add_candidates(self._search_catalog(f"{simplified_artist} {base_title}"))

        if cancel_check and cancel_check():
            return None

        # Quick check for exact ISRC match in Stage 1
        target_isrc = (track.isrc or "").strip().upper()
        if target_isrc:
            for c in candidate_pool:
                if (c.get("isrc") or "").strip().upper() == target_isrc:
                    logger.info(f"Instant exact ISRC match on Musilon for '{track.title}': {target_isrc}")
                    return self._create_source_from_candidate(c, track)

        # Stage 2: Base Title alone
        if not candidate_pool and base_title and len(base_title) >= 3:
            add_candidates(self._search_catalog(base_title))

        if cancel_check and cancel_check():
            return None

        # Stage 3: Full title + Artist
        if not candidate_pool and clean_title != base_title:
            add_candidates(self._search_catalog(f"{primary_artist} {clean_title}"))

        if cancel_check and cancel_check():
            return None

        if not candidate_pool:
            logger.info(f"No candidate tracks found on Musilon catalog for '{track.title}' by {primary_artist}")
            return None

        # Score candidates
        scored = [(self._score_candidate(track, c), c) for c in candidate_pool]
        scored.sort(key=lambda x: x[0], reverse=True)

        best_score, best_cand = scored[0]
        if best_score < 70.0:
            logger.info(f"Musilon candidate score {best_score:.1f} below threshold (70.0) for '{track.title}'")
            return None

        logger.info(f"Selected best Musilon candidate (score {best_score:.1f}): '{best_cand.get('title')}' by {best_cand.get('artist')}")
        return self._create_source_from_candidate(best_cand, track)

    def _create_source_from_candidate(self, cand: Dict[str, Any], track: TrackMetadata) -> Optional[MusilonSource]:
        """
        Builds a MusilonSource from a candidate dict, querying quality context if needed
        and picking initial quality based on user preferences.
        """
        isrc = (cand.get("isrc") or "").strip()
        cand_id = cand.get("id", "")

        has_lossless = cand.get("lossless")
        has_hires = cand.get("hires")

        # If quality attributes are not present in the search hit, fetch track context
        if (has_lossless is None or not isrc) and cand_id:
            ctx = self._get_track_context(cand_id)
            if ctx:
                has_lossless = ctx.get("lossless")
                has_hires = ctx.get("hires")
                if not isrc:
                    isrc = (ctx.get("isrc") or "").strip()

        if not isrc:
            logger.warning(f"Musilon candidate '{cand.get('title')}' has no ISRC identifier; cannot construct download ticket.")
            return None

        from core.config import config
        pref_q = str(config.get("download.preferred_quality", "320")).strip().lower()

        # Quality ladder:
        # User prefers "flac": hires (if available) -> lossless -> high (320k)
        # User prefers "320": high (320k) -> lossless (flac) -> hires (flac)
        if pref_q in ("flac", "lossless", "hires", "flac_16", "flac_24"):
            if has_hires:
                quality_param = "hires"
                tier_label = "Musilon FLAC 24"
                ext = "flac"
            else:
                quality_param = "lossless"
                tier_label = "Musilon FLAC 16"
                ext = "flac"
        else:
            quality_param = "high"
            tier_label = "Musilon 320k"
            ext = "ogg"

        dl_url = f"{self.BASE_URL}/api/media/download/{quote_plus(isrc)}?quality={quality_param}"

        return MusilonSource(
            track_id=cand_id,
            title=cand.get("title", track.title),
            artist=cand.get("artist", track.artist_str),
            quality_tier=tier_label,
            download_url=dl_url,
            file_extension=ext,
            station_url=f"{self.BASE_URL}/",
            isrc=isrc,
            quality_param=quality_param
        )

    # -------------------------------------------------------------------------
    # Chunked Streaming Downloader
    # -------------------------------------------------------------------------
    def download_file(
        self,
        url: str,
        dest_path: str,
        station_url: str = "",
        progress_callback: Optional[Callable[[float, str, str], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
        pause_wait: Optional[Callable[[], None]] = None
    ) -> bool:
        """
        Streams audio file directly from Musilon to disk with chunked progress reporting.
        Strictly verifies audio headers; raises MusilonQualityUnavailableError on 409,
        MusilonVipError on 401/403, and MusilonRateLimitExceededError on 429.
        """
        temp_path = dest_path + ".part"
        os.makedirs(os.path.dirname(os.path.abspath(dest_path)), exist_ok=True)

        download_headers = {
            "Referer": f"{self.BASE_URL}/",
            "Accept": "*/*",
            "Sec-Fetch-Dest": "audio",
            "Sec-Fetch-Mode": "no-cors",
            "Sec-Fetch-Site": "same-origin",
        }

        resp = self.session.get(url, stream=True, timeout=(20, 90), headers=download_headers, allow_redirects=True)

        # Handle 429 Too Many Requests immediately
        if resp.status_code == 429:
            raise MusilonRateLimitExceededError("Musilon download rate limit exceeded (HTTP 429 Too Many Requests).")

        content_type = resp.headers.get("content-type", "").lower()
        is_json_or_text = any(t in content_type for t in ("application/json", "text/html", "text/plain"))

        # Inspect non-200 responses or unexpected payload bodies for quota/budget exhaustion BEFORE raise_for_status()
        if resp.status_code != 200 or is_json_or_text:
            text_preview = ""
            try:
                text_preview = resp.text[:4000].lower() if hasattr(resp, "text") else ""
            except Exception:
                pass

            budget_indicators = [
                "download_budget_exhausted",
                "download_budget_unavailable",
                "budget_exhausted",
                "daily download budget",
                "budget",
                "quota",
                "rate limit",
                "daily limit",
                "too many requests",
                "limit reached",
                "سقف دانلود",
            ]
            if any(k in text_preview for k in budget_indicators):
                raise MusilonRateLimitExceededError(
                    f"Musilon download limit or daily quota reached (HTTP {resp.status_code})."
                )

        if resp.status_code == 409:
            raise MusilonQualityUnavailableError("Requested quality tier unavailable for this track.")

        if resp.status_code in (401, 403):
            # Check if 403 was caused by budget exhaustion before raising generic VIP error
            if self.is_budget_exhausted():
                raise MusilonRateLimitExceededError(f"Musilon daily download budget exhausted (HTTP {resp.status_code}).")
            raise MusilonVipError(f"Musilon authentication required or session expired (HTTP {resp.status_code}).")

        resp.raise_for_status()

        if is_json_or_text:
            logger.warning(f"Musilon returned non-audio content-type '{content_type}' for {url}")
            initial_text = resp.text[:4000].lower() if hasattr(resp, "text") else ""
            if "authentication" in initial_text or "unauthorized" in initial_text:
                raise MusilonVipError("Musilon session expired or authentication required.")
            raise MusilonVipError(f"Musilon returned non-audio response ({content_type}).")

        total_size = int(resp.headers.get("content-length", 0))
        downloaded = 0
        start_time = time.time()
        last_update_time = 0.0
        header_verified = False

        try:
            with open(temp_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=64 * 1024):
                    if cancel_check and cancel_check():
                        f.close()
                        if os.path.exists(temp_path):
                            os.remove(temp_path)
                        return False

                    if pause_wait:
                        pause_wait()

                    if chunk:
                        # Magic bytes verification on first chunk
                        if not header_verified:
                            fmt = detect_audio_header(chunk)
                            if not fmt:
                                text_chunk = chunk[:2000].decode("utf-8", errors="ignore").lower()
                                f.close()
                                if os.path.exists(temp_path):
                                    os.remove(temp_path)

                                if any(k in text_chunk for k in [
                                    "download_budget_exhausted", "download_budget_unavailable",
                                    "budget_exhausted", "budget", "quota", "rate limit",
                                    "daily limit", "too many requests", "limit reached", "سقف دانلود"
                                ]) or self.is_budget_exhausted():
                                    raise MusilonRateLimitExceededError("Musilon download limit or daily quota reached.")
                                if "authentication" in text_chunk or "unauthorized" in text_chunk:
                                    raise MusilonVipError("Musilon authentication required.")
                                raise ValueError(f"Unrecognized audio stream header: {chunk[:32]}")
                            header_verified = True

                        f.write(chunk)
                        downloaded += len(chunk)

                        now = time.time()
                        if progress_callback and (now - last_update_time > 0.15 or downloaded == total_size):
                            last_update_time = now
                            percent = (downloaded / total_size * 100.0) if total_size > 0 else 0.0
                            elapsed = now - start_time
                            speed_bps = downloaded / elapsed if elapsed > 0 else 0.0
                            speed_str = f"{format_bytes(speed_bps)}/s"

                            if total_size > downloaded and speed_bps > 0:
                                eta_sec = int((total_size - downloaded) / speed_bps)
                                eta_str = f"{eta_sec // 60:02d}:{eta_sec % 60:02d}"
                            else:
                                eta_str = "00:00"

                            progress_callback(percent, speed_str, eta_str)

            # Final file integrity verification
            is_valid, reason = is_valid_audio_file(temp_path)
            if not is_valid:
                logger.warning(f"Downloaded Musilon file failed integrity verification: {reason}")
                if os.path.exists(temp_path):
                    os.remove(temp_path)
                return False

            if os.path.exists(dest_path):
                os.remove(dest_path)
            os.rename(temp_path, dest_path)
            return True

        except Exception:
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception:
                    pass
            raise

    # -------------------------------------------------------------------------
    # Download with Retry & Quality Fallback
    # -------------------------------------------------------------------------
    def download_track_with_retry(
        self,
        track: TrackMetadata,
        source: MusilonSource,
        dest_path: str,
        progress_callback: Optional[Callable[[float, str, str], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
        pause_wait: Optional[Callable[[], None]] = None,
        max_retries: int = 5
    ) -> bool:
        """
        Downloads a track from Musilon with automatic quality tier fallback and VIP session renewal.
        1. If 409 (quality unavailable): steps down quality (hires -> lossless -> high -> standard).
        2. If 401/403 (session issue): renews VIP session with stored credentials and retries.
        """
        current_source = source
        quality_stepdown_chain = {
            "hires": "lossless",
            "lossless": "high",
            "high": "standard",
            "standard": None
        }

        tier_labels = {
            "hires": "Musilon FLAC 24",
            "lossless": "Musilon FLAC 16",
            "high": "Musilon 320k",
            "standard": "Musilon Standard"
        }

        tier_exts = {
            "hires": "flac",
            "lossless": "flac",
            "high": "ogg",
            "standard": "ogg"
        }

        for attempt in range(1, max_retries + 1):
            if cancel_check and cancel_check():
                return False

            # Update dest_path extension if quality stepdown changed the format
            base_dest = os.path.splitext(dest_path)[0]
            cur_dest = f"{base_dest}.{current_source.file_extension}"

            try:
                logger.info(f"Musilon download attempt {attempt}/{max_retries} for '{track.title}' ({current_source.quality_tier})...")
                success = self.download_file(
                    url=current_source.download_url,
                    dest_path=cur_dest,
                    station_url=current_source.station_url,
                    progress_callback=progress_callback,
                    cancel_check=cancel_check,
                    pause_wait=pause_wait
                )
                if cancel_check and cancel_check():
                    return False

                if success and os.path.isfile(cur_dest):
                    valid, reason = is_valid_audio_file(cur_dest)
                    if valid:
                        logger.info(f"Musilon download successfully completed and verified for '{track.title}'.")
                        return True
                    else:
                        logger.warning(f"Musilon file failed validation on attempt {attempt}: {reason}")

            except MusilonQualityUnavailableError:
                if cancel_check and cancel_check():
                    return False
                next_q = quality_stepdown_chain.get(current_source.quality_param)
                if next_q:
                    logger.info(f"Quality '{current_source.quality_param}' unavailable for '{track.title}'. Stepping down to '{next_q}'...")
                    next_ext = tier_exts[next_q]
                    next_tier = tier_labels[next_q]
                    next_url = f"{self.BASE_URL}/api/media/download/{quote_plus(current_source.isrc)}?quality={next_q}"
                    current_source = MusilonSource(
                        track_id=current_source.track_id,
                        title=current_source.title,
                        artist=current_source.artist,
                        quality_tier=next_tier,
                        download_url=next_url,
                        file_extension=next_ext,
                        station_url=current_source.station_url,
                        isrc=current_source.isrc,
                        quality_param=next_q
                    )
                    continue
                else:
                    logger.warning(f"All quality tiers exhausted for Musilon track '{track.title}'.")
                    break

            except MusilonRateLimitExceededError as e_limit:
                if cancel_check and cancel_check():
                    return False
                logger.warning(f"Musilon rate limit / daily quota exceeded for '{track.title}': {e_limit}")
                raise e_limit

            except MusilonVipError as e_vip:
                if cancel_check and cancel_check():
                    return False
                logger.warning(f"Musilon attempt {attempt}/{max_retries} encountered VIP issue: {e_vip}")
                if self.is_budget_exhausted(current_source.quality_tier):
                    logger.warning(f"Musilon daily budget confirmed exhausted for '{track.title}'. Raising limit error.")
                    raise MusilonRateLimitExceededError(f"Musilon download limit / daily quota reached for '{track.title}'.")

                if self.username and self.password:
                    logger.info("Renewing Musilon VIP session credentials...")
                    login_ok = self.ensure_vip_session(force=True)
                    if login_ok and not (cancel_check and cancel_check()):
                        time.sleep(random.uniform(0.5, 1.5))
                        continue

            except Exception as e:
                if cancel_check and cancel_check():
                    return False
                logger.warning(f"Musilon attempt {attempt}/{max_retries} error: {e}")
                if self.is_budget_exhausted(current_source.quality_tier):
                    logger.warning(f"Musilon daily budget confirmed exhausted for '{track.title}'. Raising limit error.")
                    raise MusilonRateLimitExceededError(f"Musilon download limit / daily quota reached for '{track.title}'.")

                if "401" in str(e) or "403" in str(e) or "unauthorized" in str(e).lower():
                    self.ensure_vip_session(force=True)
                    if not (cancel_check and cancel_check()):
                        time.sleep(random.uniform(0.5, 1.5))
                        continue

            if cancel_check and cancel_check():
                return False

            time.sleep(random.uniform(1.0, 2.0))

        logger.error(f"All {max_retries} Musilon download attempts exhausted for '{track.title}'.")
        return False
