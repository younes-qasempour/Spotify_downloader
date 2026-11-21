"""
Headless backend engine container mirroring gui/main_window.py core initialization
and signal bindings without any Qt dependencies.
"""

import asyncio
import logging
import os
import threading
import uuid
from typing import Any, Callable, Dict, List, Optional

from backend.mdns import FlacifyMdnsBroadcaster, get_device_name
from backend.serializers import (
    mask_config_value,
    serialize_queue_item,
    serialize_track,
)
from backend.ws import EventHub
from core.archive import ArchiveManager
from core.config import ConfigManager, config
from core.lyrics import LyricsEngine
from core.melobot import MeloBotEngine
from core.musilon import MusilonEngine
from core.queue_manager import DownloadQueueManager, QueueItem
from core.resolver import CascadingAudioEngine
from core.spotify_client import SpotifyClient, TrackMetadata
from core.tagger import AudioTagger
from core.ytdlp_engine import YtdlpEngine

logger = logging.getLogger("backend.state")


class BackendState:
    """
    Holds initialized core engines, binds thread-safe callbacks to EventHub,
    and manages application startup/shutdown lifecycle and interactive prompts.
    """

    def __init__(
        self,
        *,
        archive_manager: Optional[ArchiveManager] = None,
        musilon_engine: Optional[MusilonEngine] = None,
        melobot_engine: Optional[MeloBotEngine] = None,
        ytdlp_engine: Optional[YtdlpEngine] = None,
        lyrics_engine: Optional[LyricsEngine] = None,
        tagger: Optional[AudioTagger] = None,
        audio_engine: Optional[CascadingAudioEngine] = None,
        queue_manager: Optional[DownloadQueueManager] = None,
        spotify_client: Optional[SpotifyClient] = None,
        config_manager: Optional[ConfigManager] = None,
        event_hub: Optional[EventHub] = None,
        run_startup_scan: bool = True,
        run_mdns: Optional[bool] = None,
        run_auto_sync_scheduler: bool = True,
    ) -> None:
        self.config = config_manager or config
        self.events = event_hub or EventHub()
        self.run_startup_scan = run_startup_scan
        self.run_mdns = run_startup_scan if run_mdns is None else bool(run_mdns)
        self.run_auto_sync_scheduler = run_auto_sync_scheduler
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._watched_sync_lock = threading.Lock()
        self._watched_sync_running = False
        self._auto_sync_task: Optional[asyncio.Task] = None
        self._auto_sync_wakeup: Optional[asyncio.Event] = None

        self.archive_manager = archive_manager or ArchiveManager()
        try:
            self.archive_manager.checkpoint_wal()
        except Exception as exc:
            logger.debug(f"Could not checkpoint WAL on init: {exc}")

        self.musilon_engine = musilon_engine or MusilonEngine(
            session_cookie=self.config.get("musilon.session_cookie", ""),
            username=self.config.get("musilon.username", ""),
            password=self.config.get("musilon.password", ""),
            enabled=self.config.get("musilon.enabled", True),
        )
        self.melobot_engine = melobot_engine or MeloBotEngine()
        self.ytdlp_engine = ytdlp_engine or YtdlpEngine(
            output_dir=self.config.get("download.output_dir", "")
        )
        self.lyrics_engine = lyrics_engine or LyricsEngine()
        self.tagger = tagger or AudioTagger()

        self.audio_engine = audio_engine or CascadingAudioEngine(
            musilon_engine=self.musilon_engine,
            melobot_engine=self.melobot_engine,
            ytdlp_engine=self.ytdlp_engine,
            lyrics_engine=self.lyrics_engine,
            tagger=self.tagger,
        )

        self.queue_manager = queue_manager or DownloadQueueManager(
            audio_engine=self.audio_engine,
            archive_manager=self.archive_manager,
            max_concurrent_downloads=self.config.get("download.concurrency", 5),
        )

        self.spotify_client = spotify_client or SpotifyClient(
            client_id=self.config.get("spotify.client_id", ""),
            client_secret=self.config.get("spotify.client_secret", ""),
        )

        self._prompts_lock = threading.Lock()
        self._pending_prompts: Dict[str, Dict[str, Any]] = {}
        self._telegram_auth_lock = threading.Lock()
        self._telegram_phone_hashes: Dict[str, str] = {}
        self._tools_lock = threading.Lock()
        self._last_duplicate_groups: List[Dict[str, Any]] = []
        self._tool_cancel_events: Dict[str, threading.Event] = {}
        self._mdns = FlacifyMdnsBroadcaster()
        self._bind_callbacks()

    def _bind_callbacks(self) -> None:
        qm = self.queue_manager
        qm.on_track_enqueued = self._on_track_enqueued
        qm.on_tracks_enqueued = self._on_tracks_enqueued
        qm.on_track_source_resolved = self._on_track_source_resolved
        qm.on_track_progress = self._on_track_progress
        qm.on_track_status_changed = self._on_track_status_changed
        qm.on_track_completed = self._on_track_completed
        qm.on_track_failed = self._on_track_failed
        qm.on_musilon_limit_reached = self._handle_musilon_limit_reached

        self.config.add_listener(self._on_config_changed)

    def _on_track_enqueued(self, item: QueueItem) -> None:
        self.events.emit_threadsafe(
            "track_enqueued", {"item": serialize_queue_item(item)}
        )

    def _on_tracks_enqueued(self, items: List[QueueItem]) -> None:
        self.events.emit_threadsafe(
            "tracks_enqueued",
            {"items": [serialize_queue_item(it) for it in items]},
        )

    def _on_track_source_resolved(
        self, track_id: str, source_type: str, quality_badge: str
    ) -> None:
        self.events.emit_threadsafe(
            "source_resolved",
            {
                "track_id": track_id,
                "source_type": source_type,
                "quality_badge": quality_badge,
            },
        )

    def _on_track_progress(
        self, track_id: str, percent: float, speed_str: str, eta_str: str
    ) -> None:
        self.events.emit_threadsafe(
            "track_progress",
            {
                "track_id": track_id,
                "percent": percent,
                "speed": speed_str,
                "eta": eta_str,
            },
        )

    def _on_track_status_changed(self, track_id: str, status: str) -> None:
        self.events.emit_threadsafe(
            "status_changed", {"track_id": track_id, "status": status}
        )

    def _on_track_completed(self, track_id: str, path: str) -> None:
        matched_item: Optional[QueueItem] = None
        for it in self.queue_manager.get_items():
            if it.track.id == track_id:
                matched_item = it
                break
        self.events.emit_threadsafe(
            "track_completed",
            {
                "track_id": track_id,
                "output_path": path,
                "item": serialize_queue_item(matched_item) if matched_item else None,
            },
        )

    def _on_track_failed(self, track_id: str, err: str) -> None:
        self.events.emit_threadsafe(
            "track_failed", {"track_id": track_id, "error": err}
        )

    def _on_config_changed(self, key_path: str, new_value: Any) -> None:
        self.events.emit_threadsafe(
            "config_changed",
            {"key": key_path, "value": mask_config_value(key_path, new_value)},
        )

    def _handle_musilon_limit_reached(
        self,
        track: TrackMetadata,
        item: QueueItem,
        reason_or_cb: Any,
        decision_callback: Optional[Callable[[str], None]] = None,
    ) -> None:
        """
        Mirrors MainWindow._show_musilon_limit_dialog: suppresses prompts when MeloBot
        is active and otherwise emits a prompt event awaiting client resolution.
        """
        if decision_callback is None and callable(reason_or_cb):
            decision_callback = reason_or_cb
            reason = "Musilon download rate limit or daily VIP quota reached."
        else:
            reason = str(reason_or_cb or "Musilon stream download rejected.")

        source_engine = str(self.config.get("source_engine", "musilon")).strip().lower()
        pref_eng = getattr(track, "preferred_engine", None) or getattr(
            item, "preferred_engine", None
        )
        item_source = getattr(item, "source_type", "")
        if (
            source_engine == "melobot"
            or pref_eng == "melobot"
            or item_source == "MeloBot"
            or (
                self.config.get("telegram.enabled", False)
                and not self.config.get("musilon.enabled", True)
            )
        ):
            logger.info(
                "MeloBot active; suppressing Musilon limit dialog and continuing via YouTube fallback."
            )
            if decision_callback:
                decision_callback("continue_youtube")
            return

        lower_reason = reason.lower()
        is_quota = any(w in lower_reason for w in ("limit", "quota", "429", "budget"))
        is_vip = any(
            w in lower_reason
            for w in ("vip", "auth", "401", "402", "403", "credential", "subscription", "session")
        )

        if is_quota:
            category = "quota"
            title = "Musilon Download Limit Reached"
            description = (
                "Musilon has reached its download rate limit or daily VIP quota while downloading:"
            )
            action_prompt = (
                "Would you like to continue downloading from YouTube Music, or stop the downloading process?"
            )
        elif is_vip:
            category = "vip"
            title = "Musilon VIP / Account Issue"
            description = (
                "Musilon encountered an account or VIP subscription issue while downloading:"
            )
            action_prompt = (
                "Would you like to continue downloading from YouTube Music, or stop to fix your VIP credentials in Settings?"
            )
        else:
            category = "error"
            title = "Musilon Download Failed"
            description = "Musilon failed or rejected the download stream for:"
            action_prompt = (
                "Would you like to continue downloading from YouTube Music, or stop the downloading process?"
            )

        prompt_id = uuid.uuid4().hex
        prompt_info: Dict[str, Any] = {
            "prompt_id": prompt_id,
            "track": serialize_track(track),
            "reason": reason,
            "category": category,
            "title": title,
            "description": description,
            "action_prompt": action_prompt,
        }

        with self._prompts_lock:
            self._pending_prompts[prompt_id] = {
                "info": prompt_info,
                "callback": decision_callback,
            }

        self.events.emit_threadsafe("musilon_limit_reached", prompt_info)

    def resolve_musilon_prompt(self, prompt_id: str, action: str) -> bool:
        """Resolves a pending Musilon limit prompt with 'continue_youtube' or 'stop'."""
        if action not in ("continue_youtube", "stop"):
            return False

        with self._prompts_lock:
            entry = self._pending_prompts.pop(prompt_id, None)

        if entry is None:
            return False

        callback = entry.get("callback")
        if callable(callback):
            try:
                callback(action)
            except Exception as exc:
                logger.error(f"Error executing Musilon decision callback: {exc}")

        self.events.emit_threadsafe(
            "musilon_limit_resolved", {"prompt_id": prompt_id, "action": action}
        )
        return True

    def get_pending_musilon_prompts(self) -> List[Dict[str, Any]]:
        """Returns active unresolved Musilon limit prompts."""
        with self._prompts_lock:
            return [entry["info"] for entry in self._pending_prompts.values()]

    def set_telegram_phone_hash(self, phone: str, phone_code_hash: str) -> None:
        """Caches the Telegram OTP phone_code_hash between send-code and verify steps."""
        key = phone.strip()
        with self._telegram_auth_lock:
            self._telegram_phone_hashes[key] = phone_code_hash

    def get_telegram_phone_hash(self, phone: str) -> Optional[str]:
        """Retrieves the cached Telegram OTP phone_code_hash for a phone number."""
        key = phone.strip()
        with self._telegram_auth_lock:
            return self._telegram_phone_hashes.get(key)

    def clear_telegram_phone_hash(self, phone: str) -> None:
        """Clears a cached Telegram OTP phone_code_hash after successful sign-in."""
        key = phone.strip()
        with self._telegram_auth_lock:
            self._telegram_phone_hashes.pop(key, None)

    def set_last_duplicate_groups(self, groups: List[Dict[str, Any]]) -> None:
        """Stores the most recent duplicate scan results for subsequent merge calls."""
        with self._tools_lock:
            self._last_duplicate_groups = list(groups)

    def get_last_duplicate_groups(self) -> List[Dict[str, Any]]:
        """Returns a shallow copy of the most recently scanned duplicate groups."""
        with self._tools_lock:
            return list(self._last_duplicate_groups)

    def register_tool_cancel_event(self, tool_name: str) -> threading.Event:
        """Registers and returns a fresh cancellation event for a long-running tool."""
        ev = threading.Event()
        with self._tools_lock:
            old = self._tool_cancel_events.get(tool_name)
            if old is not None:
                old.set()
            self._tool_cancel_events[tool_name] = ev
        return ev

    def clear_tool_cancel_event(
        self, tool_name: str, event: Optional[threading.Event] = None
    ) -> None:
        """Unregisters a tool cancellation event when the job finishes."""
        with self._tools_lock:
            cur = self._tool_cancel_events.get(tool_name)
            if cur is not None and (event is None or cur is event):
                self._tool_cancel_events.pop(tool_name, None)

    def cancel_tool(self, tool_name: str) -> bool:
        """Signals cancellation to an active long-running tool by name."""
        with self._tools_lock:
            ev = self._tool_cancel_events.get(tool_name)
            if ev is None:
                return False
            ev.set()
            return True

    def refresh_mdns(self) -> None:
        """Starts or stops mDNS advertising based on `mobile.lan_enabled`."""
        try:
            if not self.run_mdns:
                return
            if bool(self.config.get("mobile.lan_enabled", True)):
                from core import __version__

                port = int(os.getenv("FLACIFY_PORT", "8765") or "8765")
                threading.Thread(
                    target=self._mdns.start,
                    args=(port, get_device_name(self.config), __version__),
                    daemon=True,
                    name="BackendMdnsAdvertiser",
                ).start()
            else:
                self._mdns.stop()
        except Exception as exc:
            logger.debug(f"Could not refresh mDNS broadcaster: {exc}")

    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        """Binds the running asyncio loop and launches startup scan, mDNS & Auto-Sync scheduler."""
        self._loop = loop
        self.events.set_loop(loop)
        if self.run_startup_scan:
            output_dir = self.config.get("download.output_dir", "downloads")
            if output_dir and os.path.exists(output_dir):
                threading.Thread(
                    target=self._scan_and_index_startup,
                    args=(output_dir,),
                    daemon=True,
                    name="BackendStartupScanner",
                ).start()
        if self.run_mdns:
            self.refresh_mdns()
        if self.run_auto_sync_scheduler:
            self._auto_sync_wakeup = asyncio.Event()
            self._auto_sync_task = loop.create_task(self._auto_sync_loop())

    def reschedule_auto_sync(self) -> None:
        """Wakes the background Auto-Sync scheduler loop so updated intervals apply immediately."""
        loop = self._loop
        wakeup = self._auto_sync_wakeup
        if (
            loop is not None
            and not loop.is_closed()
            and loop.is_running()
            and wakeup is not None
        ):
            try:
                loop.call_soon_threadsafe(wakeup.set)
            except RuntimeError:
                pass

    async def _auto_sync_loop(self) -> None:
        """Background scheduled runner mirroring PlaylistsView._auto_sync_timer & startup check."""
        try:
            if bool(self.config.get("playlists.auto_sync_on_startup", True)):
                await asyncio.sleep(5.0)
                await asyncio.to_thread(self.run_watched_playlists_sync_sync, True)

            while True:
                hrs = int(self.config.get("playlists.auto_sync_interval_hours", 6) or 0)
                if self._auto_sync_wakeup is None:
                    self._auto_sync_wakeup = asyncio.Event()
                self._auto_sync_wakeup.clear()
                if hrs <= 0:
                    await self._auto_sync_wakeup.wait()
                    continue
                try:
                    await asyncio.wait_for(
                        self._auto_sync_wakeup.wait(), timeout=hrs * 3600.0
                    )
                    continue
                except asyncio.TimeoutError:
                    await asyncio.to_thread(self.run_watched_playlists_sync_sync, False)
        except asyncio.CancelledError:
            return

    def run_watched_playlists_sync_sync(self, is_startup: bool = False) -> Dict[str, Any]:
        """Checks all pinned ('Watched') playlists for newly added songs and queues deltas."""
        with self._watched_sync_lock:
            if self._watched_sync_running:
                return {
                    "already_running": True,
                    "checked_count": 0,
                    "total_added": 0,
                    "queued_count": 0,
                    "errors": [],
                }
            self._watched_sync_running = True

        try:
            watched = self.archive_manager.get_watched_playlists()
            if not watched:
                return {
                    "already_running": False,
                    "checked_count": 0,
                    "total_added": 0,
                    "queued_count": 0,
                    "errors": [],
                }

            total_added = 0
            all_delta_tracks: List[TrackMetadata] = []
            errors: List[str] = []
            ytdlp_engine = getattr(self.audio_engine, "ytdlp", None) or self.ytdlp_engine

            for pl in watched:
                pl_id = pl["id"]
                pl_url = pl.get("spotify_url", "")
                if not pl_url:
                    continue
                try:
                    if SpotifyClient.parse_url(pl_url):
                        self.spotify_client.update_credentials(
                            client_id=self.config.get("spotify.client_id", ""),
                            client_secret=self.config.get("spotify.client_secret", ""),
                        )
                        tracks = self.spotify_client.resolve(pl_url)
                    else:
                        if not ytdlp_engine:
                            from core.ytdlp_engine import YtdlpEngine

                            ytdlp_engine = YtdlpEngine(
                                output_dir=self.config.get("download.output_dir", "")
                            )
                        tracks = ytdlp_engine.extract_from_url_or_search(pl_url)

                    if tracks:
                        res = self.archive_manager.sync_saved_playlist(pl_id, tracks)
                        added = res.get("added", 0)
                        deltas = res.get("delta_tracks", [])
                        if added > 0 and deltas:
                            total_added += added
                            if bool(
                                self.config.get(
                                    "playlists.auto_download_synced_tracks", True
                                )
                            ):
                                self.archive_manager.mark_saved_tracks_queued(
                                    pl_id, [t.id for t in deltas]
                                )
                                all_delta_tracks.extend(deltas)
                except Exception as exc:
                    logger.debug(f"Auto-Sync error on watched playlist {pl_id}: {exc}")
                    errors.append(f"{pl_id}: {exc}")

            if all_delta_tracks:
                self.queue_manager.enqueue(all_delta_tracks)
                self.queue_manager.start_all()

            if total_added > 0:
                self.events.emit_threadsafe("playlists_updated", {})
                self.events.emit_threadsafe(
                    "watched_playlists_synced",
                    {
                        "checked_count": len(watched),
                        "total_added": total_added,
                        "queued_count": len(all_delta_tracks),
                        "is_startup": is_startup,
                        "errors": errors,
                    },
                )

            return {
                "already_running": False,
                "checked_count": len(watched),
                "total_added": total_added,
                "queued_count": len(all_delta_tracks),
                "errors": errors,
            }
        finally:
            with self._watched_sync_lock:
                self._watched_sync_running = False

    def _scan_and_index_startup(self, output_dir: str) -> None:
        try:
            indexed = self.archive_manager.scan_and_index_directory(output_dir)
            if indexed > 0:
                logger.info(f"Startup scan indexed {indexed} tracks into download archive.")
                self.events.emit_threadsafe("library_updated", {"indexed": indexed})
        except Exception as exc:
            logger.warning(f"Error during startup archive directory scan: {exc}")

    def shutdown(self) -> None:
        """Cleanly stops workers, scheduler, unblocks prompts, flushes caches, and checkpoints SQLite."""
        if self._auto_sync_task is not None and not self._auto_sync_task.done():
            self._auto_sync_task.cancel()
        self._auto_sync_task = None
        self._auto_sync_wakeup = None
        self._loop = None

        try:
            self.config.remove_listener(self._on_config_changed)
        except Exception:
            pass

        with self._tools_lock:
            for ev in self._tool_cancel_events.values():
                ev.set()
            self._tool_cancel_events.clear()

        with self._prompts_lock:
            pending = list(self._pending_prompts.values())
            self._pending_prompts.clear()

        for entry in pending:
            cb = entry.get("callback")
            if callable(cb):
                try:
                    cb("stop")
                except Exception:
                    pass

        try:
            self._mdns.stop()
        except Exception as exc:
            logger.debug(f"Error stopping mDNS broadcaster on shutdown: {exc}")

        try:
            self.queue_manager.stop()
        except Exception as exc:
            logger.debug(f"Error stopping queue manager on shutdown: {exc}")

        try:
            from core.genre import get_genre_resolver

            get_genre_resolver().save_cache()
        except Exception as exc:
            logger.debug(f"Error saving genre cache on shutdown: {exc}")

        try:
            self.archive_manager.checkpoint_wal()
        except Exception as exc:
            logger.debug(f"Error checkpointing WAL on shutdown: {exc}")

        self.events.set_loop(None)
