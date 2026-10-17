import os
import re
import sys
import time
import math
import asyncio
import logging
import threading
from dataclasses import dataclass
from typing import Optional, List, Dict, Any, Callable, Tuple, AsyncGenerator
from pathlib import Path
from difflib import SequenceMatcher

from telethon import TelegramClient, utils, events
from telethon.network import MTProtoSender
from telethon.tl.alltlobjects import LAYER
from telethon.tl.functions import InvokeWithLayerRequest
from telethon.tl.functions.auth import ExportAuthorizationRequest, ImportAuthorizationRequest
from telethon.tl.functions.upload import GetFileRequest
from telethon.tl.custom.message import Message
from telethon.tl.types import (
    MessageMediaDocument,
    DocumentAttributeAudio,
    DocumentAttributeFilename,
)
from telethon.errors import (
    SessionPasswordNeededError,
    PhoneCodeInvalidError,
    PhoneCodeExpiredError,
    PasswordHashInvalidError,
    FloodWaitError,
    RPCError,
)

from core.exceptions import FlacifyError
from core.spotify_client import TrackMetadata
from core.utils import sanitize_filename, is_valid_audio_file, format_bytes
from core.paths import get_cache_dir
from core.config import config

logger = logging.getLogger("core.melobot")

# Official standard client credentials (bundled default)
DEFAULT_TELEGRAM_API_ID = 2040
DEFAULT_TELEGRAM_API_HASH = "b18441a1ff607e10a989891a5462e627"


class MeloBotError(FlacifyError):
    """Base exception for MeloBot errors."""
    pass


class MeloBotAuthError(MeloBotError):
    """Raised when Telegram authentication fails or user is not logged in."""
    pass


class MeloBotRateLimitError(MeloBotError):
    """Raised when Telegram or MeloBot rate limits or flood-waits."""
    pass


class MeloBotTrackNotFoundError(MeloBotError):
    """Raised when a track cannot be resolved across all vectors in MeloBot."""
    pass


class MeloBotDownloadError(MeloBotError):
    """Raised when stream downloading from MeloBot fails or produces invalid audio."""
    pass


@dataclass
class MeloBotSource:
    track_id: str
    title: str
    artist: str
    quality_tier: str  # e.g. "MeloBot FLAC", "MeloBot 320k", "MeloBot Audio"
    message_id: int
    chat_id: Any
    file_extension: str  # "flac", "mp3", "m4a", "ogg"
    file_size: int = 0
    duration: int = 0
    mime_type: str = "audio/mpeg"


class DownloadSender:
    """Dedicated parallel MTProto chunk download sender."""

    def __init__(
        self,
        client: TelegramClient,
        sender: MTProtoSender,
        file_location: Any,
        offset: int,
        limit: int,
        stride: int,
        count: int
    ):
        self.client = client
        self.sender = sender
        self.request = GetFileRequest(file_location, offset=offset, limit=limit)
        self.stride = stride
        self.remaining = count

    async def next(self) -> Optional[bytes]:
        if self.remaining <= 0:
            return None
        res = await self.client._call(self.sender, self.request)
        self.remaining -= 1
        self.request.offset += self.stride
        return getattr(res, "bytes", b"")

    async def disconnect(self):
        try:
            await self.sender.disconnect()
        except Exception:
            pass


class ParallelTransferrer:
    """
    High-Performance Multi-Connection Parallel Chunk Transferrer for Telethon.
    Divides files into 512KB parts and downloads across multiple concurrent MTProto connections,
    saturating network bandwidth and bypassing single-connection round-trip latency bottlenecks.
    """

    def __init__(self, client: TelegramClient, dc_id: Optional[int] = None):
        self.client = client
        self.loop = client.loop
        self.dc_id = dc_id or client.session.dc_id
        self.auth_key = None if (dc_id and client.session.dc_id != dc_id) else getattr(client.session, "auth_key", None)
        self.senders: List[DownloadSender] = []

    async def _create_sender(self) -> MTProtoSender:
        dc = await self.client._get_dc(self.dc_id)
        sender = MTProtoSender(self.auth_key, loggers=self.client._log)
        await sender.connect(self.client._connection(
            dc.ip_address,
            dc.port,
            dc.id,
            loggers=self.client._log,
            proxy=self.client._proxy
        ))
        if not self.auth_key:
            auth = await self.client(ExportAuthorizationRequest(self.dc_id))
            self.client._init_request.query = ImportAuthorizationRequest(id=auth.id, bytes=auth.bytes)
            req = InvokeWithLayerRequest(LAYER, self.client._init_request)
            await sender.send(req)
            self.auth_key = sender.auth_key
        return sender

    async def init_download(
        self,
        file_location: Any,
        file_size: int,
        connection_count: int = 4,
        part_size: int = 512 * 1024
    ):
        part_count = math.ceil(file_size / part_size)
        connections = min(connection_count, max(1, part_count))
        stride = connections * part_size

        minimum, remainder = divmod(part_count, connections)

        def get_parts():
            nonlocal remainder
            if remainder > 0:
                remainder -= 1
                return minimum + 1
            return minimum

        # Cross-DC export authorization happens on the first sender
        first_sender = await self._create_sender()
        self.senders = [
            DownloadSender(self.client, first_sender, file_location, 0, part_size, stride, get_parts())
        ]
        if connections > 1:
            async def _make_sender(idx):
                s = await self._create_sender()
                return DownloadSender(self.client, s, file_location, idx * part_size, part_size, stride, get_parts())

            other_senders = await asyncio.gather(*[_make_sender(i) for i in range(1, connections)])
            self.senders.extend(other_senders)

    async def download(self, file_size: int, part_size: int = 512 * 1024) -> AsyncGenerator[bytes, None]:
        part_count = math.ceil(file_size / part_size)
        part = 0
        try:
            while part < part_count:
                tasks = [self.loop.create_task(s.next()) for s in self.senders]
                for task in tasks:
                    chunk = await task
                    if not chunk:
                        break
                    yield chunk
                    part += 1
        finally:
            await self.cleanup()

    async def cleanup(self):
        if self.senders:
            await asyncio.gather(*[s.disconnect() for s in self.senders], return_exceptions=True)
            self.senders = []


class MeloBotEngine:
    """
    High-Performance MeloBot (@melobot) Telegram Downloader Engine.
    Coordinates:
    - Thread-safe background Telethon MTProto user client with dedicated asyncio loop
    - Seamless GUI-driven phone number + verification code authentication
    - Multi-vector catalog querying (Spotify track link > Artist - Title > Clean Title Artist)
    - Automated intelligent inline keyboard button clicker prioritizing highest quality (FLAC > 320k)
    - Chunked media download with cancellation check, pause synchronization, and speed/ETA telemetry
    - Audio file validity & magic bytes verification
    """

    def __init__(
        self,
        api_id: Optional[int] = None,
        api_hash: Optional[str] = None,
        bot_username: str = "melobot",
        session_name: str = "telegram_session"
    ):
        self.api_id = api_id or int(config.get("telegram.api_id", DEFAULT_TELEGRAM_API_ID) or DEFAULT_TELEGRAM_API_ID)
        self.api_hash = api_hash or str(config.get("telegram.api_hash", DEFAULT_TELEGRAM_API_HASH) or DEFAULT_TELEGRAM_API_HASH)
        self.bot_username = bot_username or str(config.get("telegram.bot_username", "melobot"))
        self.session_name = session_name or str(config.get("telegram.session_name", "telegram_session"))

        self._session_path = str(get_cache_dir() / self.session_name)
        self._lock = threading.RLock()
        self._chat_lock = threading.RLock()
        self._client: Optional[TelegramClient] = None
        self._client_connected = False
        self._login_phone_code_hash: Optional[str] = None
        self._login_phone: Optional[str] = None

        # Dedicated background asyncio thread & loop
        self._loop = asyncio.new_event_loop()
        self._loop_thread = threading.Thread(target=self._run_event_loop, daemon=True, name="TelethonLoopThread")
        self._loop_thread.start()

    def _run_event_loop(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _run_async(self, coro, timeout: Optional[float] = None) -> Any:
        """Executes an async coroutine inside the dedicated background thread safely."""
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        try:
            return future.result(timeout=timeout)
        except (Exception, asyncio.CancelledError):
            future.cancel()
            raise

    @property
    def enabled(self) -> bool:
        """Checks if Telegram/MeloBot is enabled in settings."""
        source_engine = config.get("source_engine", "musilon")
        tg_enabled = config.get("telegram.enabled", False)
        return tg_enabled or (source_engine == "melobot")

    # =========================================================================
    # Client Lifecycle & Authentication
    # =========================================================================

    def _ensure_client(self) -> TelegramClient:
        with self._lock:
            if self._client is None:
                self._client = TelegramClient(
                    session=self._session_path,
                    api_id=self.api_id,
                    api_hash=self.api_hash,
                    loop=self._loop
                )
            return self._client

    async def _async_connect(self) -> bool:
        client = self._ensure_client()
        if not client.is_connected():
            await client.connect()
        self._client_connected = client.is_connected()
        return self._client_connected

    def connect(self) -> bool:
        try:
            return self._run_async(self._async_connect(), timeout=15.0)
        except Exception as e:
            logger.error(f"Failed to connect TelegramClient: {e}")
            return False

    async def _async_is_authorized(self) -> bool:
        await self._async_connect()
        return await self._client.is_user_authorized()

    def is_authorized(self) -> bool:
        """Returns True if the user account is actively signed in."""
        try:
            return bool(self._run_async(self._async_is_authorized(), timeout=10.0))
        except Exception as e:
            logger.debug(f"is_authorized check failed: {e}")
            return False

    async def _async_get_me(self) -> Optional[Dict[str, Any]]:
        if not await self._async_is_authorized():
            return None
        me = await self._client.get_me()
        if not me:
            return None
        return {
            "id": getattr(me, "id", 0),
            "first_name": getattr(me, "first_name", "") or "",
            "last_name": getattr(me, "last_name", "") or "",
            "username": getattr(me, "username", "") or "",
            "phone": getattr(me, "phone", "") or "",
            "is_premium": getattr(me, "premium", False),
        }

    def get_me(self) -> Optional[Dict[str, Any]]:
        """Returns current logged-in user profile info or None if not signed in."""
        try:
            return self._run_async(self._async_get_me(), timeout=10.0)
        except Exception as e:
            logger.debug(f"get_me failed: {e}")
            return None

    async def _async_send_code(self, phone: str) -> Dict[str, Any]:
        await self._async_connect()
        clean_phone = phone.strip().replace(" ", "").replace("-", "")
        if not clean_phone.startswith("+"):
            clean_phone = "+" + clean_phone
        res = await self._client.send_code_request(clean_phone)
        self._login_phone = clean_phone
        self._login_phone_code_hash = res.phone_code_hash
        return {
            "success": True,
            "phone": clean_phone,
            "phone_code_hash": res.phone_code_hash,
            "timeout": getattr(res, "timeout", 60),
        }

    def send_code(self, phone: str) -> Dict[str, Any]:
        """Requests a verification code from Telegram sent via SMS or official app."""
        try:
            return self._run_async(self._async_send_code(phone), timeout=25.0)
        except FloodWaitError as fe:
            logger.warning(f"Telegram flood wait during send_code: {fe.seconds}s")
            return {"success": False, "error": f"Rate limited by Telegram. Please wait {fe.seconds} seconds."}
        except RPCError as re_err:
            logger.error(f"RPCError during send_code: {re_err}")
            return {"success": False, "error": str(re_err)}
        except Exception as e:
            logger.error(f"Unexpected error in send_code: {e}")
            return {"success": False, "error": str(e)}

    async def _async_sign_in(
        self,
        code: str,
        password: Optional[str] = None,
        phone_code_hash: Optional[str] = None,
        phone: Optional[str] = None
    ) -> Dict[str, Any]:
        target_phone = phone or self._login_phone or config.get("telegram.phone", "")
        target_hash = phone_code_hash or self._login_phone_code_hash
        if not target_phone or not target_hash:
            return {"success": False, "error": "No pending phone code request. Please click 'Send Code' first."}

        clean_code = code.strip().replace(" ", "")
        try:
            user = await self._client.sign_in(
                phone=target_phone,
                code=clean_code,
                phone_code_hash=target_hash
            )
            # Save phone to config
            config.set("telegram.phone", target_phone)
            config.set("telegram.enabled", True)
            config.save()

            me_info = await self._async_get_me()
            return {"success": True, "user": me_info}
        except SessionPasswordNeededError:
            if not password:
                return {
                    "success": False,
                    "needs_password": True,
                    "error": "Two-Factor Authentication (2FA) password is required."
                }
            user = await self._client.sign_in(password=password.strip())
            config.set("telegram.phone", target_phone)
            config.set("telegram.enabled", True)
            config.save()
            me_info = await self._async_get_me()
            return {"success": True, "user": me_info}
        except PhoneCodeInvalidError:
            return {"success": False, "error": "The verification code you entered is invalid."}
        except PhoneCodeExpiredError:
            return {"success": False, "error": "The verification code has expired. Please request a new code."}
        except PasswordHashInvalidError:
            return {"success": False, "error": "The 2FA password you entered is incorrect."}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def sign_in(
        self,
        code: str,
        password: Optional[str] = None,
        phone_code_hash: Optional[str] = None,
        phone: Optional[str] = None
    ) -> Dict[str, Any]:
        """Completes sign-in with the verification code (and optional 2FA password)."""
        try:
            return self._run_async(self._async_sign_in(code, password, phone_code_hash, phone), timeout=30.0)
        except Exception as e:
            logger.error(f"Unexpected error in sign_in: {e}")
            return {"success": False, "error": str(e)}

    async def _async_log_out(self) -> bool:
        if self._client and self._client.is_connected():
            try:
                await self._client.log_out()
            except Exception as e:
                logger.debug(f"Log out note: {e}")
            try:
                await self._client.disconnect()
            except Exception:
                pass
        self._client = None
        self._client_connected = False
        config.set("telegram.enabled", False)
        config.set("telegram.phone", "")
        config.save()

        # Remove session file if exists
        sess_file = Path(f"{self._session_path}.session")
        if sess_file.exists():
            try:
                sess_file.unlink()
            except Exception:
                pass
        return True

    def log_out(self) -> bool:
        """Logs out from Telegram and resets credentials."""
        try:
            return bool(self._run_async(self._async_log_out(), timeout=15.0))
        except Exception as e:
            logger.error(f"log_out failed: {e}")
            return False

    # =========================================================================
    # Track Resolution & Multi-Vector Query Ladder
    # =========================================================================

    def resolve_track(
        self,
        track: TrackMetadata,
        cancel_check: Optional[Callable[[], bool]] = None
    ) -> Optional[MeloBotSource]:
        """
        Cascading multi-vector resolver for MeloBot.
        Guarded by self._chat_lock to guarantee sequential, 1-song-at-a-time Telegram bot conversation.
        """
        if cancel_check and cancel_check():
            return None

        if not self.is_authorized():
            logger.warning("MeloBot resolution skipped: Telegram user account is not logged in.")
            return None

        with self._chat_lock:
            if cancel_check and cancel_check():
                return None

            clean_artists = [sanitize_filename(a, max_length=80).strip() for a in (track.artists or [track.primary_artist])]
            clean_artists = [a for a in clean_artists if a]
            clean_title = sanitize_filename(track.title, max_length=150).strip()
            # Strip common extra tags like '(Remastered)', '[Explicit]', '(feat. ...)', '(2nd version, 1877)', etc.
            clean_title_no_parentheses = re.sub(
                r'[\(\[]\s*(?:\d+(?:st|nd|rd|th)?\s+version(?:\s*,\s*\d{4})?|\d{4}\s+version|version\s*,\s*\d{4}|ed\.?\s+[^\)\]]+|edition\b[^\)\]]*|die\s+verurteilten|shawshank|soundtrack|ost|[^\)\]]*)\s*[\)\]]',
                '',
                clean_title,
                flags=re.IGNORECASE
            ).strip()
            clean_title_no_parentheses = re.sub(r'\s+', ' ', clean_title_no_parentheses).strip()

            all_artist_text = (track.title + " " + " ".join(track.artists or [track.primary_artist])).lower()
            is_classical = any(k in all_artist_text for k in (
                "symphony", "concerto", "sonata", "scherzo", "allegro", "adagio", "andante",
                "presto", "moderato", "largo", "vivace", "overture", "nozze", "figaro",
                "requiem", "canzonetta", "duettino", "aria", "cavatina", "philharmoniker",
                "philharmonic", "sinfonia", "orchestra", "orchester", "mozart", "bruckner",
                "beethoven", "bach", "brahms", "chopin", "tchaikovsky", "dvorak", "dvořák",
                "vivaldi", "schubert", "mahler", "wagner", "handel", "haydn", "shostakovich"
            )) or bool(re.search(r'\b(?:op|wab|bwv|hob|k|rv)\.?\s*\d+\b', all_artist_text))

            search_vectors: List[Tuple[str, str]] = []

            if is_classical:
                parts = [re.sub(r'[\(\[].*?[\)\]]', '', p).strip() for p in re.split(r'[:\-–—]|\.{2,}|\…', clean_title_no_parentheses) if p.strip()]
                if len(parts) >= 2:
                    work = parts[0]
                    work_clean = re.sub(r',?\s*\b(?:WAB|Op\.?|K\.?|BWV|Hob\.?|D\.?|RV|S\.)\s*\d+[a-zA-Z]?\b', '', work, flags=re.IGNORECASE).strip()
                    work_short = re.sub(r'\s+in\s+[A-G](?:\s+(?:flat|sharp))?(?:\s+(?:major|minor))?', '', work_clean, flags=re.IGNORECASE).strip()

                    mvt = parts[1]
                    mvt_clean = re.sub(r'\.{2,}', ' ', mvt).strip()
                    m = re.search(r'\b(?:I{1,3}|IV|V|VI|VII|VIII|IX|X|\d+)?\.?\s*(Scherzo|Allegro|Adagio|Andante|Presto|Moderato|Largo|Vivace|Grave|Maestoso|Canzonetta|Duettino|Aria|Cavatina|Overture)\b[^\.\-–—]*', mvt_clean, re.IGNORECASE)
                    mvt_word = m.group(0).strip() if m else mvt_clean.split('.')[0].strip()

                    if clean_artists and mvt_word:
                        search_vectors.append(("Classical Movement & Artist", f"{clean_artists[0]} {mvt_word}"))
                        search_vectors.append(("Classical Work & Movement", f"{clean_artists[0]} {work_short} {mvt_word}"))
                        for co_art in clean_artists[1:3]:
                            search_vectors.append((f"Co-Artist ({co_art}) - Movement", f"{co_art} {mvt_word}"))
                    if mvt_word:
                        search_vectors.append(("Classical Movement Query", mvt_word))
                    if clean_artists and clean_title_no_parentheses:
                        search_vectors.append(("Clean Title & Artist", f"{clean_artists[0]} {clean_title_no_parentheses[:60]}"))
            else:
                primary_clean = clean_title_no_parentheses or clean_title

                # Vector 1: Primary Artist - Clean Title (Optimal indexing in MeloBot for instant 1st-try resolution)
                if clean_artists and primary_clean:
                    search_vectors.append(("Primary Artist - Clean Title", f"{clean_artists[0]} - {primary_clean}"))

                # Vector 2: Additional Co-Artists - Clean Title
                for additional_artist in clean_artists[1:3]:
                    if primary_clean:
                        search_vectors.append((f"Co-Artist ({additional_artist}) - Clean Title", f"{additional_artist} - {primary_clean}"))

                # Vector 3: Clean Title Alone (Wide candidate pool from MeloBot)
                if primary_clean:
                    search_vectors.append(("Clean Title Query", primary_clean))

                # Vector 4: Full Title with Parentheses & Tags (if distinct from clean title)
                if clean_title_no_parentheses and clean_title_no_parentheses != clean_title and clean_artists:
                    search_vectors.append(("Full Title & Artist", f"{clean_artists[0]} - {clean_title}"))

                # Vector 5: Full Title Alone (Final fallback vector)
                if clean_title and clean_title != primary_clean:
                    search_vectors.append(("Full Title Query", clean_title))

            for vector_name, query_str in search_vectors:
                if cancel_check and cancel_check():
                    return None

                logger.info(f"MeloBot querying Vector '{vector_name}' for '{track.title}': {query_str}")
                try:
                    src = self._run_async(
                        self._async_query_melobot(track=track, query=query_str, cancel_check=cancel_check),
                        timeout=130.0
                    )
                    if src:
                        logger.info(f"Resolved '{track.title}' via MeloBot ({src.quality_tier}) using '{vector_name}'")
                        return src
                except Exception as e:
                    logger.warning(f"MeloBot query failed on vector '{vector_name}': {e}")

                # Humanized brief pause between vectors
                time.sleep(0.4)

            logger.info(f"MeloBot search exhausted all {len(search_vectors)} vectors for '{track.title}'. Not found.")
            return None

    async def _async_query_melobot(
        self,
        track: TrackMetadata,
        query: str,
        cancel_check: Optional[Callable[[], bool]] = None
    ) -> Optional[MeloBotSource]:
        """
        Sends a query message to @melobot, inspects the response for audio files
        or interactive keyboard buttons, handles candidate selection & quality picking,
        and returns a MeloBotSource.
        Uses Telethon event push updates with gentle fallback polling to completely prevent
        flood waits (FloodWaitError). Retries button clicks (up to 3 times) and waits up to
        120s for audio delivery to maximize MeloBot download success.
        """
        client = self._ensure_client()
        bot_entity = await client.get_input_entity(self.bot_username)

        # Queue for incoming bot push events
        event_queue: asyncio.Queue[Message] = asyncio.Queue()

        async def _bot_msg_handler(event):
            if not getattr(event, "out", False):
                await event_queue.put(event.message)

        client.add_event_handler(_bot_msg_handler, events.NewMessage(chats=bot_entity))
        client.add_event_handler(_bot_msg_handler, events.MessageEdited(chats=bot_entity))

        # Track message IDs with clicked buttons to guarantee controlled button clicks
        clicked_msg_ids = set()
        audio_msg: Optional[Message] = None

        # Interactive state tracking for multi-click retry & extended wait
        last_clicked_msg: Optional[Message] = None
        last_clicked_is_quality: bool = False
        click_attempts: int = 0
        last_click_time: float = 0.0

        try:
            # Send query message to the bot
            sent_msg = await client.send_message(bot_entity, query)
            last_id = sent_msg.id

            vector_start = time.time()
            stage_start = time.time()
            stage_timeout = 20.0  # 20s to get initial candidate / quality menu
            max_vector_time = 130.0  # Total time allowed for this vector

            while time.time() - vector_start < max_vector_time:
                if cancel_check and cancel_check():
                    return None

                # Check if we need to re-click the button (user requested 2-3 click retries)
                now = time.time()
                if last_clicked_msg and click_attempts < 3:
                    retry_delay = 14.0 if last_clicked_is_quality else 6.0
                    if (now - last_click_time) >= retry_delay:
                        logger.info(
                            f"MeloBot {'audio' if last_clicked_is_quality else 'quality menu'} response pending; "
                            f"re-clicking {'quality' if last_clicked_is_quality else 'candidate'} button (attempt {click_attempts + 1}/3)..."
                        )
                        await self._handle_bot_keyboard(last_clicked_msg, track, bot_entity)
                        click_attempts += 1
                        last_click_time = time.time()

                remaining_stage = stage_timeout - (time.time() - stage_start)
                if remaining_stage <= 0:
                    logger.info(f"MeloBot stage timeout ({stage_timeout:.1f}s) reached for vector query '{query}'.")
                    break

                # Await incoming push update or do a safe rate-limited poll every 1.5s
                wait_slice = min(1.5, max(0.1, remaining_stage))
                incoming_msg: Optional[Message] = None
                try:
                    incoming_msg = await asyncio.wait_for(event_queue.get(), timeout=wait_slice)
                except asyncio.TimeoutError:
                    # Gentle fallback poll: only 1 request per 1.5s, strictly safe from flood wait
                    try:
                        poll_msgs = await client.get_messages(bot_entity, min_id=last_id, limit=4)
                        for pm in reversed(poll_msgs):
                            if not getattr(pm, "out", False) and pm.id not in clicked_msg_ids:
                                incoming_msg = pm
                                break
                    except Exception as e_poll:
                        logger.debug(f"MeloBot fallback poll error: {e_poll}")

                if not incoming_msg or incoming_msg.id <= sent_msg.id:
                    continue

                msg = incoming_msg
                last_id = max(last_id, msg.id)

                # 1. Direct audio file received
                if self._is_audio_message(msg):
                    target_dur = track.duration_sec
                    doc = getattr(msg.media, "document", None) if getattr(msg, "media", None) else None
                    dur = 0
                    if doc:
                        for attr in getattr(doc, "attributes", []):
                            if isinstance(attr, DocumentAttributeAudio):
                                dur = getattr(attr, "duration", 0) or 0

                    all_artist_text = (track.title + " " + " ".join(track.artists or [track.primary_artist])).lower()
                    is_classical = any(k in all_artist_text for k in (
                        "symphony", "concerto", "sonata", "scherzo", "allegro", "adagio", "andante",
                        "presto", "moderato", "largo", "vivace", "overture", "nozze", "figaro",
                        "requiem", "canzonetta", "duettino", "aria", "cavatina"
                    )) or bool(re.search(r'\b(?:op|wab|bwv|hob|k|rv)\.?\s*\d+\b', all_artist_text))
                    max_dur_tol = max(45.0, target_dur * 0.15) if is_classical else 25.0

                    if dur > 0 and target_dur > 0 and abs(dur - target_dur) > max_dur_tol:
                        logger.warning(
                            f"MeloBot delivered audio with duration mismatch ({dur}s vs target {target_dur:.1f}s, "
                            f"diff={abs(dur - target_dur):.1f}s > {max_dur_tol:.1f}s). Discarding mismatch audio."
                        )
                        continue

                    audio_msg = msg
                    break

                # 2. Interactive keyboard received (Candidate Picker or Quality Selector)
                if getattr(msg, "buttons", None) and msg.id not in clicked_msg_ids:
                    is_qual = self._is_quality_menu(msg)
                    clicked = await self._handle_bot_keyboard(msg, track, bot_entity)
                    if clicked:
                        clicked_msg_ids.add(msg.id)
                        last_clicked_msg = msg
                        last_clicked_is_quality = is_qual
                        click_attempts = 1
                        last_click_time = time.time()
                        stage_start = time.time()
                        if is_qual:
                            # Quality clicked! MeloBot will transcode and upload the audio file (10MB-40MB).
                            # Allow up to 120 seconds for full upload.
                            stage_timeout = 120.0
                            max_vector_time = max(max_vector_time, time.time() - vector_start + 120.0)
                        else:
                            # Candidate clicked! Quality menu will arrive within 18 seconds.
                            stage_timeout = 18.0
                        continue
                    else:
                        logger.info(f"MeloBot keyboard options for '{track.title}' did not satisfy candidate/quality criteria. Ending vector early.")
                        return None

                # 3. Text-only message indicating no results found
                elif (msg.text or "").strip() and not getattr(msg, "media", None):
                    txt_lower = msg.text.lower()
                    if any(w in txt_lower for w in ("یافت نشد", "پیدا نشد", "موردی یافت نشد", "not found")):
                        logger.info(f"MeloBot reported no results for '{query}'. Ending vector early.")
                        return None

        finally:
            client.remove_event_handler(_bot_msg_handler, events.NewMessage(chats=bot_entity))
            client.remove_event_handler(_bot_msg_handler, events.MessageEdited(chats=bot_entity))

        if not audio_msg:
            return None

        # Build MeloBotSource from audio message
        return self._extract_source_from_message(audio_msg, track)

    def _is_audio_message(self, msg: Message) -> bool:
        """Returns True if the message contains playable audio (music, podcast, audio document)."""
        if not msg:
            return False
        if getattr(msg, "audio", None):
            return True
        if getattr(msg, "media", None) and isinstance(msg.media, MessageMediaDocument):
            doc = msg.media.document
            if doc:
                mime = getattr(doc, "mime_type", "").lower()
                if mime.startswith("audio/") or mime in ("application/ogg", "application/x-flac"):
                    return True
                # Check file name extension
                for attr in getattr(doc, "attributes", []):
                    if isinstance(attr, (DocumentAttributeAudio, DocumentAttributeFilename)):
                        if isinstance(attr, DocumentAttributeAudio):
                            return True
                        fname = getattr(attr, "file_name", "").lower()
                        if any(fname.endswith(ext) for ext in (".mp3", ".flac", ".m4a", ".ogg", ".wav", ".aac")):
                            return True
        return False

    def _is_quality_menu(self, msg: Message) -> bool:
        """Returns True if the message keyboard contains quality selection buttons (FLAC, 320k, 128k)."""
        if not getattr(msg, "buttons", None):
            return False
        for row in msg.buttons:
            for btn in row:
                t = (getattr(btn, "text", "") or "").strip().lower()
                for fa_d, en_d in (('۰', '0'), ('۱', '1'), ('۲', '2'), ('۳', '3'), ('۴', '4'), ('۵', '5'), ('۶', '6'), ('۷', '7'), ('۸', '8'), ('۹', '9')):
                    t = t.replace(fa_d, en_d)
                if any(k in t for k in ("کیفیت عالی", "کیفیت 320", "320 kbps", "320k", "کیفیت flac", "flac", "کیفیت معمولی", "کیفیت 128")):
                    return True
        return False

    async def _handle_bot_keyboard(self, msg: Message, track: TrackMetadata, bot_entity: Any) -> bool:
        """
        Intelligently identifies whether the keyboard is a Quality Menu or Candidate Menu
        and clicks the optimal button:
        - If Quality Menu: Picks FLAC > 320k (کیفیت عالی) > 128k (کیفیت معمولی)
        - If Candidate Menu: Scores candidate songs against track title/artist, avoids navigation & artists
        """
        if not getattr(msg, "buttons", None):
            return False

        buttons: List[Tuple[int, int, str, Any]] = []
        for r_idx, row in enumerate(msg.buttons):
            for c_idx, btn in enumerate(row):
                text = (getattr(btn, "text", "") or "").strip()
                buttons.append((r_idx, c_idx, text, btn))

        if not buttons:
            return False

        # Helper to classify genuine quality selection buttons
        def _get_quality_tier(btn_text: str) -> Optional[str]:
            t = btn_text.strip()
            # Candidate buttons or lengthy strings are never quality buttons
            if any(t.startswith(icon) for icon in ('🎵', '📀', '🗣', '👤', '🎬', '🎧', '⬅️', '➡️')):
                return None
            if len(t) > 40:
                return None
            t_clean = t.lower()
            for fa_d, en_d in (('۰', '0'), ('۱', '1'), ('۲', '2'), ('۳', '3'), ('۴', '4'), ('۵', '5'), ('۶', '6'), ('۷', '7'), ('۸', '8'), ('۹', '9')):
                t_clean = t_clean.replace(fa_d, en_d)

            # 1. FLAC / Lossless
            if any(k in t_clean for k in ("کیفیت flac", "flac", "lossless", "hi-res")):
                return "flac"
            # 2. 320 kbps / High Quality
            if any(k in t_clean for k in ("کیفیت عالی", "کیفیت 320", "320 kbps", "320k")) or t_clean in ("320", "عالی", "high quality"):
                return "320"
            # 3. 128 kbps / Standard Quality
            if any(k in t_clean for k in ("کیفیت معمولی", "کیفیت 128", "128 kbps", "128k")) or t_clean in ("128", "معمولی", "standard quality"):
                return "128"
            return None

        # Check if keyboard contains genuine quality selection buttons
        has_quality_buttons = any(_get_quality_tier(txt) is not None for _, _, txt, _ in buttons)

        # Check if keyboard belongs to an Album Tracklist Menu
        is_album_menu = False
        msg_text = (getattr(msg, "text", "") or "").lower()
        if "آلبوم" in msg_text or any("دانلود همه" in txt for _, _, txt, _ in buttons):
            is_album_menu = True

        # Check if this keyboard contains song/album search candidate buttons
        has_candidate_buttons = not has_quality_buttons and (any(
            any(txt.startswith(icon) for icon in ('🎵', '📀', '👤', '🎬', '🎧')) or
            (txt.startswith('🗣') and not any(k in txt for k in ("خوانندهها", "خواننده ها", "خواننده")))
            for _, _, txt, _ in buttons
        ) or is_album_menu)

        # --- A. Quality Selection Processing (When quality menu is presented) ---
        if has_quality_buttons:
            # 1. FLAC / Lossless
            for r, c, txt, btn in buttons:
                if _get_quality_tier(txt) == "flac":
                    logger.info(f"MeloBot clicking FLAC Lossless quality button: '{txt}'")
                    try:
                        await btn.click()
                    except Exception:
                        await self._client.send_message(bot_entity, txt)
                    return True

            # 2. 320 kbps / High Quality / کیفیت عالی (Includes VIP)
            for r, c, txt, btn in buttons:
                if _get_quality_tier(txt) == "320":
                    logger.info(f"MeloBot clicking High Quality (320k / VIP) button: '{txt}'")
                    try:
                        await btn.click()
                    except Exception:
                        await self._client.send_message(bot_entity, txt)
                    return True

            # 3. Standard Quality (128 kbps) - only if explicitly allowed or user preferred 128k
            pref_q = str(config.get("telegram.preferred_quality", config.get("download.preferred_quality", "320"))).strip().lower()
            allow_128k = config.get("download.allow_128k", False) or pref_q in ("128", "standard", "low")

            if allow_128k:
                for r, c, txt, btn in buttons:
                    if _get_quality_tier(txt) == "128":
                        logger.info(f"MeloBot clicking Standard Quality (128k) button: '{txt}'")
                        try:
                            await btn.click()
                        except Exception:
                            await self._client.send_message(bot_entity, txt)
                        return True
            else:
                logger.info(f"MeloBot only offered 128k standard quality ('کیفیت معمولی'). Rejecting to satisfy FLAC/320k priority.")
                return False

            return False

        # --- B. Candidate Menu Processing (When search results or albums are presented) ---
        if has_candidate_buttons:
            best_score = -1.0
            best_btn: Optional[Tuple[int, int, str, Any]] = None

            for r, c, txt, btn in buttons:
                score = self._score_candidate(txt, track, is_album_menu=is_album_menu)
                if score > best_score and score >= 40.0:
                    best_score = score
                    best_btn = (r, c, txt, btn)

            if best_btn:
                r, c, txt, btn = best_btn
                logger.info(f"MeloBot clicking perfect search candidate (score={best_score:.1f}, is_album={is_album_menu}): '{txt}'")
                try:
                    await btn.click()
                except Exception:
                    await self._client.send_message(bot_entity, txt)
                return True

            return False

        return False

    def _clean_track_str(self, text: str) -> str:
        text = text.replace("'", "").replace("’", "").replace("`", "")
        text = text.replace("-", " ")
        text = re.sub(r'x\s+[\d\.]+[kmKM]?', '', text)
        text = re.sub(r'^[🎵📀🎧🎬\s]+', '', text)
        text = re.sub(r'[^\w\s]', ' ', text)
        return ' '.join(text.lower().split())

    def _score_candidate(self, button_text: str, track: TrackMetadata, is_album_menu: bool = False) -> float:
        excluded = (
            '⬅️', '➡️', 'صفحه اصلی', '🗣', 'نتیجه در لیست نیست', 'خرید اشتراک',
            'هدیه با موزیک', 'دانلود همه', 'بیشتر...', 'مشابه', 'متن آهنگ',
            'جستجوی پیشرفته', '❌ لغو', 'لینک اشتراک'
        )
        for ex in excluded:
            if ex in button_text:
                return -1.0

        btn_clean = self._clean_track_str(button_text)
        t_clean = self._clean_track_str(track.title)

        btn_words = set(btn_clean.split())
        t_words = [w for w in t_clean.split() if len(w) > 1]
        if not t_words:
            return -1.0

        def _match_token(w: str, bw: str) -> bool:
            if w == bw:
                return True
            if (w + 's' == bw) or (bw + 's' == w):
                return True
            if abs(len(w) - len(bw)) <= 1 and SequenceMatcher(None, w, bw).ratio() >= 0.82:
                return True
            return False

        # 1. Artist Verification:
        # In album tracklists, buttons contain only track titles because artist is in album header.
        best_artist_ratio = 1.0 if is_album_menu else 0.0
        if not is_album_menu:
            all_artists = track.artists if getattr(track, "artists", None) else [track.primary_artist]
            matched_any_artist = False

            for artist_name in all_artists:
                a_clean = self._clean_track_str(artist_name)
                a_words = [w for w in a_clean.split() if len(w) > 1]
                if not a_words:
                    continue

                # Check direct concatenation (e.g. mohammad + reza -> mohammadreza)
                a_concat = "".join(a_words)
                if a_concat in btn_words or a_concat in btn_clean.replace(" ", ""):
                    best_artist_ratio = 1.0
                    matched_any_artist = True
                    break

                matched_indices = []
                for i, w in enumerate(a_words):
                    if any(_match_token(w, bw) for bw in btn_words):
                        matched_indices.append(i)
                    elif any(len(w) >= 4 and len(bw) >= 4 and (w in bw or bw in w) for bw in btn_words):
                        matched_indices.append(i)
                    elif any(len(w) >= 3 and len(bw) >= 5 and (bw.startswith(w) or bw.endswith(w)) for bw in btn_words):
                        matched_indices.append(i)

                matched = len(matched_indices)
                ratio = matched / len(a_words)
                if ratio > best_artist_ratio:
                    best_artist_ratio = ratio

                if len(a_words) == 1 and matched >= 1:
                    matched_any_artist = True
                elif len(a_words) == 2 and (matched == 2 or (1 in matched_indices)):
                    matched_any_artist = True
                elif len(a_words) >= 3 and (ratio >= 0.5 or (matched >= 2 and (len(a_words) - 1) in matched_indices)):
                    matched_any_artist = True

            if not matched_any_artist:
                return -1.0  # Disqualified: None of the track artists match

        # 2. Strict Version & Descriptors Verification:
        descriptors = (
            # Live / Concert
            'live', 'لایو', 'زنده', 'کنسرت', 'concert', 'unplugged',
            # Acoustic & Orchestral
            'acoustic', 'آکوستیک', 'orchestral', 'ارکسترال', 'symphony', 'سمفونی',
            # Remix, DJ, Mix
            'remix', 'ریمیکس', 'میکس', 'mix', 'vip mix', 'club', 'dubstep',
            'dj', 'دی جی', 'دی‌جی', 'podcast', 'پادکست',
            # Vocal / Instrumental
            'acapella', 'آکاپلا', 'instrumental', 'بی کلام', 'بیکلام', 'karaoke',
            # Audio modifications / Pitch / Speed / AI
            'sped up', 'speed up', 'slowed', 'reverb', 'nightcore',
            '8d', 'bass boosted', 'bass boost',
            'ai', 'هوش مصنوعی',
            # Other variants
            'mashup', 'medley', 'parody', 'cover', 'کاور', 'tribute', 'deli', 'دلی'
        )

        def _has_descriptor(desc: str, text: str) -> bool:
            pattern = rf'(?<![a-zA-Z0-9\u0600-\u06FF]){re.escape(desc)}(?![a-zA-Z0-9\u0600-\u06FF])'
            return bool(re.search(pattern, text, re.IGNORECASE))

        for d in descriptors:
            in_btn = _has_descriptor(d, btn_clean)
            in_track = _has_descriptor(d, t_clean)
            if in_btn and not in_track:
                return -1.0  # Extraneous version not wanted by user
            if in_track and not in_btn:
                return -1.0  # Track requested this version, but button does not have it

        # 3. Title Word Match Ratio (Calculated against full title and core title without parentheses)
        clean_core_title = re.sub(
            r'[\(\[]\s*(?:\d+(?:st|nd|rd|th)?\s+version(?:\s*,\s*\d{4})?|\d{4}\s+version|version\s*,\s*\d{4}|ed\.?\s+[^\)\]]+|edition\b[^\)\]]*|die\s+verurteilten|shawshank|soundtrack|ost|[^\)\]]*)\s*[\)\]]',
            '',
            track.title,
            flags=re.IGNORECASE
        ).strip()
        core_clean = self._clean_track_str(clean_core_title)
        core_words = [w for w in core_clean.split() if len(w) > 1]

        matched_full = sum(1 for w in t_words if any(_match_token(w, bw) for bw in btn_words))
        full_ratio = matched_full / len(t_words) if t_words else 0.0

        matched_core = sum(1 for w in core_words if any(_match_token(w, bw) for bw in btn_words))
        core_ratio = matched_core / len(core_words) if core_words else 0.0

        title_ratio = max(full_ratio, core_ratio)
        min_title_threshold = 0.5 if len(core_words or t_words) >= 3 else 0.8

        # Check segmented matching for classical, soundtrack, or multi-part titles (e.g. Work: Aria)
        best_segment_ratio = 0.0
        for part in re.split(r'[:\-–—]|\.{2,}|\…', track.title):
            p_clean = re.sub(r'[\(\[].*?[\)\]]', '', part).strip()
            p_clean = self._clean_track_str(p_clean)
            sw = [w for w in p_clean.split() if len(w) > 1]
            if len(sw) >= 2:
                m_seg = sum(1 for w in sw if any(_match_token(w, bw) for bw in btn_words))
                r_seg = m_seg / len(sw)
                if r_seg > best_segment_ratio:
                    best_segment_ratio = r_seg

        min_segment_threshold = 0.45 if any(k in track.title.lower() for k in ("symphony", "concerto", "sonata", "scherzo", "allegro", "adagio", "andante", "presto", "moderato", "largo", "vivace", "overture", "nozze", "figaro", "requiem", "canzonetta", "duettino", "aria", "cavatina")) else 0.65
        if title_ratio < min_title_threshold and best_segment_ratio < min_segment_threshold:
            return -1.0

        effective_title_ratio = max(title_ratio, best_segment_ratio)

        # 4. SequenceMatcher Similarity
        sim_title = max(
            SequenceMatcher(None, t_clean, btn_clean).ratio(),
            SequenceMatcher(None, core_clean, btn_clean).ratio() if core_clean else 0.0
        )
        base_score = max(sim_title * 100.0, best_segment_ratio * 60.0)

        # 5. Icon/Release Priority: Single track (🎵) or Album title track (📀)
        if button_text.startswith('🎵'):
            base_score += 15.0
        elif button_text.startswith('📀'):
            base_score += 12.0

        # In album tracklists, prefer vocal / saaz va avaz / tasnif over instrumental
        if is_album_menu:
            if 'saaz va avaz' in btn_clean or 'ساز و آواز' in btn_clean or 'tasnif' in btn_clean or 'تصنیف' in btn_clean:
                base_score += 15.0
            elif 'ham navazi' in btn_clean or 'همنوازی' in btn_clean:
                base_score -= 20.0

        # 6. Bonuses for title and artist ratios
        base_score += best_artist_ratio * 25.0
        base_score += effective_title_ratio * 25.0

        return base_score

    def _extract_source_from_message(self, msg: Message, track: TrackMetadata) -> MeloBotSource:
        """Parses audio metadata from the message and builds a MeloBotSource."""
        doc = getattr(msg.media, "document", None) if getattr(msg, "media", None) else None
        file_size = getattr(doc, "size", 0) if doc else 0
        mime = getattr(doc, "mime_type", "audio/mpeg").lower() if doc else "audio/mpeg"
        duration = 0
        file_name = ""

        if doc:
            for attr in getattr(doc, "attributes", []):
                if isinstance(attr, DocumentAttributeAudio):
                    duration = getattr(attr, "duration", 0) or 0
                elif isinstance(attr, DocumentAttributeFilename):
                    file_name = getattr(attr, "file_name", "") or ""

        # Determine extension
        ext = "mp3"
        if "flac" in mime or file_name.lower().endswith(".flac"):
            ext = "flac"
        elif "ogg" in mime or file_name.lower().endswith(".ogg") or file_name.lower().endswith(".opus"):
            ext = "ogg"
        elif "m4a" in mime or file_name.lower().endswith(".m4a"):
            ext = "m4a"

        # Determine quality badge
        if ext == "flac":
            badge = "MeloBot FLAC"
        elif ext == "mp3":
            if duration > 0:
                bitrate_kbps = (file_size * 8) / (duration * 1000)
                badge = "MeloBot 320k" if bitrate_kbps >= 220 else "MeloBot 128k"
            elif file_size > 6 * 1024 * 1024:
                badge = "MeloBot 320k"
            else:
                badge = "MeloBot 128k"
        else:
            badge = f"MeloBot {ext.upper()}"

        return MeloBotSource(
            track_id=track.id,
            title=track.title,
            artist=track.primary_artist,
            quality_tier=badge,
            message_id=msg.id,
            chat_id=msg.chat_id,
            file_extension=ext,
            file_size=file_size,
            duration=duration,
            mime_type=mime
        )

    # =========================================================================
    # Download & Streaming
    # =========================================================================

    def download_track(
        self,
        source: MeloBotSource,
        dest_path: str,
        progress_callback: Optional[Callable[[float, str, str], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
        pause_wait: Optional[Callable[[], None]] = None
    ) -> bool:
        """
        Downloads the resolved audio file directly from Telegram servers into dest_path.
        Guarded by self._chat_lock to ensure atomic, sequential media downloading.
        """
        if cancel_check and cancel_check():
            return False

        with self._chat_lock:
            if cancel_check and cancel_check():
                return False

            try:
                return bool(
                    self._run_async(
                        self._async_download_track(
                            source=source,
                            dest_path=dest_path,
                            progress_callback=progress_callback,
                            cancel_check=cancel_check,
                            pause_wait=pause_wait
                        ),
                        timeout=300.0
                    )
                )
            except Exception as e:
                logger.error(f"MeloBot download failed for '{source.title}': {e}", exc_info=True)
                if os.path.exists(dest_path):
                    try:
                        os.remove(dest_path)
                    except Exception:
                        pass
                raise MeloBotDownloadError(f"MeloBot download failed: {e}")

    async def _async_download_track(
        self,
        source: MeloBotSource,
        dest_path: str,
        progress_callback: Optional[Callable[[float, str, str], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
        pause_wait: Optional[Callable[[], None]] = None
    ) -> bool:
        client = self._ensure_client()
        temp_dest = f"{dest_path}.part"
        os.makedirs(os.path.dirname(os.path.abspath(dest_path)), exist_ok=True)

        msg = await client.get_messages(source.chat_id, ids=source.message_id)
        if not msg or not msg.media:
            raise MeloBotDownloadError(f"Telegram media message {source.message_id} was deleted or unavailable.")

        last_time = [time.time()]
        last_bytes = [0]
        total_size = source.file_size or getattr(getattr(msg.media, "document", None), "size", 0) or 1

        def telethon_progress(received_bytes: int, total: int):
            if cancel_check and cancel_check():
                raise asyncio.CancelledError("Download cancelled by user.")

            if pause_wait:
                pause_wait()

            now = time.time()
            elapsed = now - last_time[0]
            if elapsed >= 0.3:
                speed_bps = (received_bytes - last_bytes[0]) / elapsed if elapsed > 0 else 0
                speed_str = f"{format_bytes(speed_bps)}/s" if speed_bps > 0 else "0 KB/s"
                remaining = max(0, total - received_bytes)
                eta_sec = int(remaining / speed_bps) if speed_bps > 0 else 0
                eta_str = f"{eta_sec // 60:02d}:{eta_sec % 60:02d}"
                percent = min(99.0, (received_bytes / max(1, total)) * 100.0)

                last_time[0] = now
                last_bytes[0] = received_bytes

                if progress_callback:
                    progress_callback(percent, speed_str, eta_str)

        try:
            downloaded_file = await client.download_media(
                msg,
                file=temp_dest,
                progress_callback=telethon_progress
            )
        except asyncio.CancelledError:
            if os.path.exists(temp_dest):
                try:
                    os.remove(temp_dest)
                except Exception:
                    pass
            return False
        except Exception as e_dl:
            if os.path.exists(temp_dest):
                try:
                    os.remove(temp_dest)
                except Exception:
                    pass
            raise MeloBotDownloadError(f"Telethon download error: {e_dl}")

        if not os.path.isfile(temp_dest) or os.path.getsize(temp_dest) < 1024:
            if os.path.exists(temp_dest):
                try:
                    os.remove(temp_dest)
                except Exception:
                    pass
            raise MeloBotDownloadError("MeloBot downloaded file is empty or corrupted.")

        # Audio file validation
        is_valid, reason = is_valid_audio_file(temp_dest)
        if not is_valid:
            if os.path.exists(temp_dest):
                try:
                    os.remove(temp_dest)
                except Exception:
                    pass
            raise MeloBotDownloadError(f"MeloBot downloaded file failed audio integrity check: {reason}")

        # Atomically rename .part to final destination
        if os.path.exists(dest_path):
            try:
                os.remove(dest_path)
            except Exception:
                pass
        os.rename(temp_dest, dest_path)

        if progress_callback:
            progress_callback(100.0, "Complete", "00:00")

        logger.info(f"Successfully downloaded MeloBot track to: {dest_path}")
        return True
