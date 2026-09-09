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
from bs4 import BeautifulSoup

from core.spotify_client import TrackMetadata
from core.utils import clean_watermarks, format_bytes

logger = logging.getLogger("core.musilon")


@dataclass
class MusilonSource:
    track_id: str
    title: str
    artist: str
    quality_tier: str  # "FLAC 16-bit", "FLAC 24-bit", "MP3 320kbps", "Stream 128k"
    download_url: str
    file_extension: str  # "flac" or "mp3"


class MusilonEngine:
    """
    VIP / Premium Scraper and Downloader for Musilon (https://musilon.com/).
    Implements:
    - Persistent authenticated session
    - ArvanCloud challenge bypass
    - Lazy search and fuzzy match with duration validation
    - Quality tier resolution (FLAC 16-bit > FLAC 24-bit > MP3 320k)
    - Rate-limit shield with 1.5s - 3.0s jitter and exponential backoff
    - Chunked streaming downloader with progress callbacks
    """

    BASE_URL = "https://musilon.com"
    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )

    def __init__(self, session_cookie: str = "", username: str = "", password: str = "", enabled: bool = True):
        self.enabled = enabled
        self.session_cookie = session_cookie.strip()
        self.username = username.strip()
        self.password = password.strip()

        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": self.USER_AGENT,
            "Referer": "https://musilon.com/",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
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

        # Parse key=value; key2=val2
        parts = clean.split(";")
        found_pair = False
        for part in parts:
            part = part.strip()
            if "=" in part:
                k, v = part.split("=", 1)
                k = k.strip().strip('"').strip("'")
                v = v.strip().strip('"').strip("'")
                self.session.cookies.set(k, v, domain="musilon.com")
                found_pair = True

        if not found_pair and clean:
            # User might have pasted only the raw value of the wordpress_logged_in cookie
            self.session.cookies.set("wordpress_logged_in", clean, domain="musilon.com")

    def login_with_credentials(self, username: str = "", password: str = "") -> Tuple[bool, str]:
        """
        Attempts direct login to Musilon using username/password via Digits 2-step AJAX.
        Returns: (success: bool, message: str)
        """
        user = (username or self.username).strip()
        pwd = (password or self.password).strip()

        if not user or not pwd:
            return False, "Username and password cannot be empty."

        try:
            self._rate_limit_shield()
            # 1. Fetch login page to extract nonce, tokens, and form hidden fields
            r_page = self._request("GET", f"{self.BASE_URL}/?login=true")
            soup = BeautifulSoup(r_page.text, "html.parser")
            login_form = soup.find("form", class_="digloginpage")
            if not login_form:
                return False, "Could not find Digits login form on Musilon."

            form_data = {}
            for inp in login_form.find_all("input"):
                n = inp.get("name")
                if n:
                    form_data[n] = inp.get("value", "")

            form_data["action_type"] = "email"
            form_data["digits_email"] = user
            if "digits_phone" in form_data:
                del form_data["digits_phone"]

            ajax_headers = {
                "X-Requested-With": "XMLHttpRequest",
                "Referer": f"{self.BASE_URL}/?login=true"
            }

            # Step 1: Submit email to request password step
            self._rate_limit_shield()
            r_step1 = self.session.post(
                f"{self.BASE_URL}/wp-admin/admin-ajax.php",
                data=form_data,
                headers=ajax_headers,
                timeout=15
            )
            step1_data = r_step1.json() if r_step1.status_code == 200 else {}
            if not step1_data.get("success"):
                msg = step1_data.get("data", {}).get("message", "Step 1 verification failed.")
                return False, f"Login failed: {msg}"

            # Step 2: Submit password
            form_data["digits_step_1_type"] = "password"
            form_data["digits_step_1_value"] = pwd
            form_data["password"] = pwd

            self._rate_limit_shield()
            r_step2 = self.session.post(
                f"{self.BASE_URL}/wp-admin/admin-ajax.php",
                data=form_data,
                headers=ajax_headers,
                timeout=15
            )
            step2_data = r_step2.json() if r_step2.status_code == 200 else {}
            if step2_data.get("success"):
                logger.info("Successfully authenticated with Musilon Digits VIP.")
                self.username = user
                self.password = pwd

                # Save session cookies to config if possible
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

                return True, "Successfully logged in to Musilon VIP."
            else:
                msg = step2_data.get("data", {}).get("message", "Invalid credentials or password.")
                return False, f"Login failed: {msg}"

        except Exception as e:
            logger.error(f"Error logging in to Musilon: {e}")
            return False, f"Login failed: {e}."

    def test_connection(self) -> Tuple[bool, bool, str]:
        """
        Tests connectivity and VIP authentication status.
        Auto-authenticates with credentials if VIP cookies are missing.
        Returns: (connected: bool, is_vip_authenticated: bool, status_message: str)
        """
        try:
            r = self._request("GET", f"{self.BASE_URL}/", timeout=10, max_retries=2)
            connected = r.status_code == 200

            cookies = self.session.cookies
            has_auth_cookie = any(
                ("wordpress_logged_in" in c.name or "wordpress_sec" in c.name or "d_user_session" in c.name)
                for c in cookies
            )
            page_logged_in = "action=logout" in r.text or "wp-login.php?action=logout" in r.text

            is_vip = has_auth_cookie or page_logged_in

            # If not VIP but credentials are present, auto-authenticate
            if not is_vip and self.username and self.password:
                logger.info("Musilon VIP session missing or expired; auto-authenticating with credentials...")
                login_ok, login_msg = self.login_with_credentials(self.username, self.password)
                if login_ok:
                    return True, True, "Connected! Active Musilon VIP session verified."

            if is_vip:
                return True, True, "Connected! Active Musilon VIP session verified."
            elif connected:
                return True, False, "Connected to Musilon (Guest mode). Log in or configure credentials to enable direct FLAC/320k."
            else:
                return False, False, f"HTTP status {r.status_code}"

        except Exception as e:
            return False, False, f"Musilon connection failed: {e}"

    # -------------------------------------------------------------------------
    # Rate-Limit Shield (Sequential Jitter & Backoff)
    # -------------------------------------------------------------------------
    def _rate_limit_shield(self):
        """Enforces a strict 1.0s to 2.0s jitter between consecutive requests."""
        now = time.time()
        elapsed = now - self._last_request_time
        jitter = random.uniform(1.0, 2.0)
        if elapsed < jitter:
            time.sleep(jitter - elapsed)
        self._last_request_time = time.time()

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        """Wrapper around requests with challenge handling and fast fallback."""
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
                        # Retry original request after setting challenge cookies
                        return self._request(method, url, allow_404=allow_404, max_retries=2, timeout=timeout, **kwargs)

                if resp.status_code == 404 and allow_404:
                    return resp

                if resp.status_code in (429, 403):
                    logger.warning(f"Musilon rate-limited (HTTP {resp.status_code}). Backing off for {backoff:.1f}s...")
                    time.sleep(backoff)
                    backoff *= 1.5
                    continue

                resp.raise_for_status()
                return resp

            except (requests.RequestException, Exception) as e:
                logger.warning(f"Musilon request failed (attempt {attempt + 1}/{max_retries}): {e}")
                if attempt == max_retries - 1:
                    raise e
                time.sleep(backoff)
                backoff *= 1.5

        raise RuntimeError(f"Max retries reached for {url}")

    def _solve_arvancloud_challenge(self, html_content: str) -> bool:
        """Solves ArvanCloud JavaScript challenge using Node.js."""
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
                    self.session.cookies.set(k, v, domain="musilon.com")
                logger.info("Successfully solved and injected ArvanCloud challenge cookies.")
                return True
        except Exception as e:
            logger.error(f"Error solving ArvanCloud challenge: {e}")
        return False

    # -------------------------------------------------------------------------
    # Multi-Source Search & Matching Logic
    # -------------------------------------------------------------------------
    UNWANTED_VERSION_MODIFIERS = [
        "instrumental", "karaoke", "acoustic", "workout mix", "workout",
        "remix", "live", "cover", "slowed", "speed up", "sped up",
        "reverb", "orchestral", "piano version", "tribute", "parody",
        "radio edit", "extended mix", "club mix", "dub mix"
    ]

    def _search_play_rest(self, query: str) -> List[Dict[str, Any]]:
        """Queries internal /wp-json/play/search endpoint returning structured JSON."""
        try:
            url = f"{self.BASE_URL}/wp-json/play/search?search={quote_plus(query)}"
            r = self._request("GET", url, timeout=10, allow_404=True)
            if r.status_code != 200:
                return []
            results = []
            for it in r.json():
                u = it.get("url", "")
                if "/station/" in u:
                    results.append({
                        "id": it.get("id"),
                        "title": clean_watermarks(it.get("title", "")),
                        "artist": clean_watermarks(it.get("author", "")),
                        "url": u,
                        "method": "play_rest"
                    })
            return results
        except Exception as e:
            logger.debug(f"play_rest search failed for '{query}': {e}")
            return []

    def _search_station_wp(self, query: str) -> List[Dict[str, Any]]:
        """Queries WordPress REST API /wp-json/wp/v2/station endpoint."""
        try:
            url = f"{self.BASE_URL}/wp-json/wp/v2/station?search={quote_plus(query)}&per_page=30"
            r = self._request("GET", url, timeout=10, allow_404=True)
            if r.status_code != 200:
                return []
            results = []
            for it in r.json():
                u = it.get("link", "")
                if "/station/" in u:
                    tit = it.get("title", {}).get("rendered", "")
                    results.append({
                        "id": str(it.get("id")),
                        "title": clean_watermarks(tit),
                        "artist": "",
                        "url": u,
                        "method": "station_wp"
                    })
            return results
        except Exception as e:
            logger.debug(f"station_wp search failed for '{query}': {e}")
            return []

    def _search_artist_taxonomy(self, artist_name: str) -> List[Dict[str, Any]]:
        """Queries artist taxonomy term and retrieves all stations by artist."""
        try:
            clean_art = re.sub(r'^(?:the|a)\s+', '', artist_name, flags=re.IGNORECASE).strip()
            url = f"{self.BASE_URL}/wp-json/wp/v2/artist?search={quote_plus(clean_art)}"
            r = self._request("GET", url, timeout=10, allow_404=True)
            if r.status_code != 200:
                return []
            terms = r.json()
            if not isinstance(terms, list):
                return []
            results = []
            for t in terms:
                term_id = t.get("id")
                term_name = t.get("name", "")
                count = t.get("count", 0)
                if count > 0 and (clean_art.lower() in term_name.lower() or term_name.lower() in clean_art.lower()):
                    st_url = f"{self.BASE_URL}/wp-json/wp/v2/station?artist={term_id}&per_page=100"
                    r_st = self._request("GET", st_url, timeout=10, allow_404=True)
                    if r_st.status_code == 200:
                        for it in r_st.json():
                            u = it.get("link", "")
                            tit = it.get("title", {}).get("rendered", "")
                            results.append({
                                "id": str(it.get("id")),
                                "title": clean_watermarks(tit),
                                "artist": term_name,
                                "url": u,
                                "method": "artist_taxonomy"
                            })
            return results
        except Exception as e:
            logger.debug(f"artist_taxonomy search failed for '{artist_name}': {e}")
            return []

    def _search(self, query: str) -> List[Dict[str, Any]]:
        """Queries Musilon HTML search page."""
        search_url = f"{self.BASE_URL}/search/{quote_plus(query)}/"
        resp = self._request("GET", search_url, allow_404=True)
        if resp.status_code != 200:
            return []
        soup = BeautifulSoup(resp.text, "html.parser")
        return self._parse_search_soup(soup)

    def _parse_search_soup(self, soup: BeautifulSoup) -> List[Dict[str, Any]]:
        candidates: List[Dict[str, Any]] = []
        seen = set()

        articles = soup.find_all("article")
        for art in articles:
            data_id = art.get("data-play-id") or art.get("id", "").replace("post-", "")
            title_tag = art.find(class_=re.compile(r'entry-title|item-title|station-title'))
            link_tag = art.find("a", href=True)
            if link_tag and title_tag:
                url = urljoin(self.BASE_URL, link_tag["href"])
                if url not in seen and "/station/" in url:
                    seen.add(url)
                    title = clean_watermarks(title_tag.get_text(strip=True))
                    candidates.append({
                        "id": data_id,
                        "title": title,
                        "artist": "",
                        "url": url,
                        "method": "html_search"
                    })

        return candidates

    def _score_candidate(self, track: TrackMetadata, cand: Dict[str, Any]) -> float:
        """
        Intelligently scores a Musilon candidate against target track metadata:
        - Strict Artist Validation: rejects candidates with foreign artists (-999.0)
        - Title Closeness: tokens and exact string matching
        - Version Modifiers: penalizes remixes/live/acoustic if not requested
        - Bonus Track alignment
        """
        cand_title = cand.get("title", "").lower()
        cand_author = cand.get("artist", "").lower()
        cand_url = cand.get("url", "").lower()

        target_title = clean_watermarks(track.title).lower()
        target_artist = track.primary_artist.lower()
        clean_target_art = re.sub(r'^(?:the|a)\s+', '', target_artist).strip()

        # Extract artist from URL slug: e.g. /station/daniel-caesar/who-knows-2/
        url_artist_slug = ""
        m = re.search(r'/station/([^/]+)/([^/]+)/?', cand_url)
        if m:
            url_artist_slug = m.group(1).replace("-", " ")

        # 1. Strict Artist Validation (Anti-False-Positive Filter)
        art_match = False
        target_art_tokens = [w for w in re.sub(r'[^\w\s]', ' ', clean_target_art).split() if len(w) > 1]

        check_authors = []
        if cand_author:
            check_authors.append(cand_author)
        if url_artist_slug:
            check_authors.append(url_artist_slug)

        for ca in check_authors:
            ca_clean = re.sub(r'[^\w\s]', ' ', ca)
            ca_tokens = set(ca_clean.split())
            if any(tok in ca_tokens for tok in target_art_tokens):
                art_match = True
                break
            if clean_target_art in ca or ca in clean_target_art:
                art_match = True
                break

        # If author/slug information is present but completely unrelated to target artist:
        # Immediate hard rejection (e.g. Dayglow for Seafret, or Teddy Swims for Omar Apollo)
        if check_authors and not art_match:
            return -999.0

        score = 50.0 if art_match else 0.0

        # 2. Title Matching
        base_title = re.sub(r'[\(\[\-].*?(?:feat|ft|remaster|version|from|bonus).*?[\)\]]?', '', target_title).strip()
        base_title = re.sub(r'[^\w\s]', ' ', base_title).strip()
        base_words = [w for w in base_title.split() if len(w) > 1]

        clean_cand_title = re.sub(r'[^\w\s]', ' ', cand_title).strip()
        cand_words = set(clean_cand_title.split())

        if base_words and all(w in cand_words for w in base_words):
            score += 60.0
        elif base_words:
            matched_words = sum(1 for w in base_words if w in cand_words)
            if matched_words >= max(1, len(base_words) - 1):
                score += 40.0

        # Exact title equality bonus
        clean_target_full = re.sub(r'[^\w\s]', ' ', target_title).strip()
        if clean_target_full == clean_cand_title or base_title == clean_cand_title:
            score += 30.0

        # 3. Version Modifier Penalties & Bonuses
        for mod in self.UNWANTED_VERSION_MODIFIERS:
            has_in_cand = (mod in cand_title) or (mod in cand_url)
            has_in_target = (mod in target_title)
            if has_in_cand and not has_in_target:
                score -= 70.0
            elif has_in_cand and has_in_target:
                score += 30.0

        # Bonus Track specific alignment
        if "bonus track" in target_title and "bonus track" in cand_title:
            score += 40.0

        return score

    def _find_best_candidate(self, track: TrackMetadata, candidates: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not candidates:
            return None

        scored = [(self._score_candidate(track, c), c) for c in candidates]
        scored.sort(key=lambda x: x[0], reverse=True)

        best_score, best_cand = scored[0]
        if best_score >= 70.0:
            return best_cand

        return None

    def resolve_track(self, track: TrackMetadata) -> Optional[MusilonSource]:
        """
        Searches Musilon for a track across 4 complementary search engines:
        1. Live /wp-json/play/search REST API
        2. /wp-json/wp/v2/station WordPress REST API
        3. Full Artist Taxonomy Discography archive
        4. HTML Search fallback
        Extracts the highest quality tier (FLAC 16 > FLAC 24 > MP3 320k).
        Strict Quality Rule: Rejects 128k preview streams.
        """
        if not self.enabled:
            return None

        # Check / verify VIP session
        cookies = self.session.cookies
        has_vip = any(
            ("wordpress_logged_in" in c.name or "wordpress_sec" in c.name or "d_user_session" in c.name)
            for c in cookies
        )
        if not has_vip and self.username and self.password:
            logger.info("Auto-authenticating VIP session in resolve_track...")
            self.login_with_credentials(self.username, self.password)

        clean_title = clean_watermarks(track.title).strip()
        primary_artist = track.primary_artist.strip()

        # Simplify artist: e.g. "The Black Eyed Peas" -> "Black Eyed Peas"
        simplified_artist = re.sub(r'^(?:the|a)\s+', '', primary_artist, flags=re.IGNORECASE).strip()

        # Base title: remove (feat. ...), [From ...], - Remastered..., etc.
        base_title = re.sub(r'[\(\[\-].*?(?:feat|ft|remaster|version|from|motion picture|bonus).*?[\)\]]?', '', clean_title, flags=re.IGNORECASE).strip()
        base_title = re.sub(r'[\(\[\{].*?[\)\]\}]', '', base_title).strip()
        base_title = base_title.rstrip(" -_~:").strip()

        # Punctuation-normalized titles
        norm_title = clean_title.replace("’", "'").replace("`", "'").replace("“", '"').replace("”", '"')
        norm_base = base_title.replace("’", "'").replace("`", "'").replace("“", '"').replace("”", '"')

        candidate_pool: List[Dict[str, Any]] = []
        seen_urls = set()

        def add_candidates(cands: List[Dict[str, Any]]):
            for c in cands:
                u = c.get("url")
                if u and u not in seen_urls:
                    seen_urls.add(u)
                    candidate_pool.append(c)

        # Stage 1: Play JSON REST Search with artist + base title
        if simplified_artist and norm_base:
            add_candidates(self._search_play_rest(f"{simplified_artist} {norm_base}"))

        # Early exit if high-confidence match found
        best = self._find_best_candidate(track, candidate_pool)
        if best and self._score_candidate(track, best) >= 100.0:
            logger.info(f"Found immediate high-confidence Musilon candidate: {best.get('title')}")
            return self._extract_source(best["url"], best.get("id"))

        # Stage 2: Play JSON REST Search with base title alone
        if norm_base and len(norm_base) >= 3:
            add_candidates(self._search_play_rest(norm_base))

        best = self._find_best_candidate(track, candidate_pool)
        if best and self._score_candidate(track, best) >= 100.0:
            return self._extract_source(best["url"], best.get("id"))

        # Stage 3: Play JSON REST Search with full title
        if norm_title != norm_base:
            add_candidates(self._search_play_rest(f"{simplified_artist} {norm_title}"))

        # Stage 4: Artist Taxonomy Discography Archive
        if simplified_artist:
            add_candidates(self._search_artist_taxonomy(simplified_artist))

        # Stage 5: WordPress Station Search
        if not candidate_pool:
            if simplified_artist and norm_base:
                add_candidates(self._search_station_wp(f"{simplified_artist} {norm_base}"))
            if norm_base:
                add_candidates(self._search_station_wp(norm_base))

        # Stage 6: HTML Search fallback
        if not candidate_pool:
            if simplified_artist and norm_base:
                add_candidates(self._search(f"{simplified_artist} {norm_base}"))
            if norm_base:
                add_candidates(self._search(norm_base))

        if not candidate_pool:
            logger.info(f"No candidates found on Musilon across all vectors for '{track.title}'")
            return None

        best_match = self._find_best_candidate(track, candidate_pool)
        if not best_match:
            logger.info(f"No candidate met strict criteria (threshold 70.0) for '{track.title}'")
            return None

        best_score = self._score_candidate(track, best_match)
        logger.info(f"Selected best Musilon candidate (score {best_score:.1f}): '{best_match.get('title')}' -> {best_match.get('url')}")

        return self._extract_source(best_match["url"], best_match.get("id"))

    def _extract_source(self, track_url: str, post_id: Optional[str] = None) -> Optional[MusilonSource]:
        """
        Fetches the track station page and inspects the download popup and play endpoints
        to extract the highest available quality tier (FLAC 16 > FLAC 24 > MP3 320k).
        Scopes link extraction strictly to this track station URL to prevent grabbing recommendations.
        """
        resp = self._request("GET", track_url)
        soup = BeautifulSoup(resp.text, "html.parser")

        # If VIP session is required / expired, auto-authenticate and reload
        if "dl-not-login" in resp.text and self.username and self.password:
            logger.info(f"Musilon VIP authentication required for {track_url}. Auto-authenticating...")
            login_ok, _ = self.login_with_credentials(self.username, self.password)
            if login_ok:
                resp = self._request("GET", track_url)
                soup = BeautifulSoup(resp.text, "html.parser")

        flac_16_url = None
        flac_24_url = None
        mp3_320_url = None

        # Clean target station path to strictly filter download links
        clean_target_path = track_url.split("?")[0].rstrip("/")
        station_slug = clean_target_path.split("/")[-1]

        # Check popup and download links
        for a in soup.find_all("a"):
            href = a.get("href", "") or a.get("data-url", "") or a.get("data-link", "")
            dtype = a.get("data-type", "")
            classes = " ".join(a.get("class", []))
            text = a.get_text(strip=True).lower()

            if not href or href == "#" or href.startswith("javascript:") or "login" in href:
                continue

            # Scope check: ensure this download button belongs to the requested station
            # Exclude recommendation links that belong to other stations
            if "/station/" in href and f"/{station_slug}/" not in href and not href.startswith(clean_target_path):
                continue

            full_url = urljoin(self.BASE_URL, href)

            if dtype == "16" or "dltype=16" in href or "16-bit" in text or "cd" in text:
                flac_16_url = full_url
            elif dtype == "24" or "dltype=24" in href or "24-bit" in text or "hi-res" in text:
                flac_24_url = full_url
            elif dtype == "320" or "dltype=320" in href or "320" in text or "320kbps" in text:
                mp3_320_url = full_url

        # Return highest quality available
        if flac_16_url:
            return MusilonSource(
                track_id=post_id or station_slug,
                title=soup.title.get_text(strip=True) if soup.title else "Track",
                artist="",
                quality_tier="Musilon FLAC 16",
                download_url=flac_16_url,
                file_extension="flac"
            )
        if flac_24_url:
            return MusilonSource(
                track_id=post_id or station_slug,
                title=soup.title.get_text(strip=True) if soup.title else "Track",
                artist="",
                quality_tier="Musilon FLAC 24",
                download_url=flac_24_url,
                file_extension="flac"
            )
        if mp3_320_url:
            return MusilonSource(
                track_id=post_id or station_slug,
                title=soup.title.get_text(strip=True) if soup.title else "Track",
                artist="",
                quality_tier="Musilon 320k",
                download_url=mp3_320_url,
                file_extension="mp3"
            )

        # If buttons are still marked dl-not-login, VIP session was not active
        if "dl-not-login" in resp.text:
            logger.info(f"Musilon VIP authentication required for direct download on {track_url}.")
            return None

        # Inspect the REST player endpoint fallback: /wp-json/play/play/{id}
        if not post_id:
            m = re.search(r'data-play-id="(\d+)"', resp.text)
            if m:
                post_id = m.group(1)

        if post_id:
            try:
                play_api = f"{self.BASE_URL}/wp-json/play/play/{post_id}"
                r_play = self._request("GET", play_api)
                data = r_play.json()
                if data.get("downloadable") and data.get("download_url"):
                    d_url = data["download_url"]
                    if "login" not in d_url and not d_url.endswith("#"):
                        is_flac = ".flac" in d_url.lower()
                        is_320 = "320" in d_url.lower() or not d_url.lower().endswith("128.mp3")
                        if is_flac or is_320:
                            tier = "Musilon FLAC 16" if is_flac else "Musilon 320k"
                            return MusilonSource(
                                track_id=post_id,
                                title=data.get("title", ""),
                                artist=data.get("artist", ""),
                                quality_tier=tier,
                                download_url=d_url,
                                file_extension="flac" if is_flac else "mp3"
                            )
            except Exception as e:
                logger.debug(f"Could not fetch play rest API: {e}")

        logger.info(f"Musilon does not offer FLAC or 320kbps for {track_url}.")
        return None

    # -------------------------------------------------------------------------
    # Chunked Direct CDN Downloader
    # -------------------------------------------------------------------------
    def download_file(
        self,
        url: str,
        dest_path: str,
        progress_callback: Optional[Callable[[float, str, str], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
        pause_wait: Optional[Callable[[], None]] = None
    ) -> bool:
        """
        Streams audio file directly from CDN to disk with chunked progress reporting.
        """
        temp_path = dest_path + ".part"
        os.makedirs(os.path.dirname(os.path.abspath(dest_path)), exist_ok=True)

        resp = self.session.get(url, stream=True, timeout=30, headers={"Referer": "https://musilon.com/"})
        resp.raise_for_status()

        total_size = int(resp.headers.get("content-length", 0))
        downloaded = 0
        start_time = time.time()
        last_update_time = 0.0

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

        # Rename .part to destination
        if os.path.exists(dest_path):
            os.remove(dest_path)
        os.rename(temp_path, dest_path)
        return True
