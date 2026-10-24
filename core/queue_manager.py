import os
import time
import random
import queue
import shutil
import threading
import logging
from dataclasses import dataclass, field
from typing import Optional, Dict, List, Callable, Any
from concurrent.futures import ThreadPoolExecutor
import requests

from core.spotify_client import TrackMetadata
from core.resolver import CascadingAudioEngine, ResolvedTrackSource
from core.musilon import MusilonRateLimitExceededError, MusilonVipError, MusilonDownloadError, MusilonError
from core.melobot import MeloBotDownloadError, MeloBotError
from core.archive import ArchiveManager
from core.utils import sanitize_filename, is_valid_audio_file
from core.config import config
from core.paths import get_covers_dir
from core.exceptions import AudioSourceNotFoundError

logger = logging.getLogger("core.queue")


@dataclass
class QueueItem:
    track: TrackMetadata
    status: str = "Queued"  # "Queued", "Resolving", "Downloading", "Paused", "Tagging", "Fetching Lyrics", "Completed", "Failed", "Cancelled"
    source_type: str = ""
    quality_badge: str = ""
    progress_percent: float = 0.0
    speed_str: str = ""
    eta_str: str = ""
    error_message: str = ""
    output_path: str = ""
    cancelled: bool = False
    preferred_engine: Optional[str] = None


class DownloadQueueManager:
    """
    Thread-safe Producer-Consumer Queue Manager (Zero Qt Dependencies).
    Coordinates:
    - Lazy track resolution
    - Archive deduplication & instant local reuse
    - Active pause / resume synchronization
    - Failed songs bulk retry
    - Sequential Musilon rate-limit throttling
    - Multi-threaded fallback downloads
    - Real-time event and callback dispatching
    """

    def __init__(
        self,
        audio_engine: Optional[CascadingAudioEngine] = None,
        archive_manager: Optional[ArchiveManager] = None,
        max_concurrent_downloads: Optional[int] = None
    ):
        self.engine = audio_engine or CascadingAudioEngine()
        self.archive = archive_manager or ArchiveManager()
        self.max_workers = max_concurrent_downloads if max_concurrent_downloads is not None else int(config.get("download.concurrency", 5))

        self._queue: queue.Queue[QueueItem] = queue.Queue()
        self._items: Dict[str, QueueItem] = {}  # track_id -> QueueItem
        self._lock = threading.RLock()
        self._paused = threading.Event()
        self._paused.set()  # Not paused by default
        self._running = False
        self._worker_threads: List[threading.Thread] = []

        # Musilon stream semaphore to protect CDN bandwidth from rate limits while allowing parallel search
        mus_streams = max(1, int(config.get("musilon.stream_concurrency", 1)))
        self._musilon_stream_lock = threading.Semaphore(mus_streams)

        # Dedicated single-thread semaphore for Telegram MeloBot bot queries & downloads
        self._telegram_stream_lock = threading.Semaphore(1)

        # Decoupled Event Callbacks
        self.on_track_enqueued: Optional[Callable[[QueueItem], None]] = None
        self.on_tracks_enqueued: Optional[Callable[[List[QueueItem]], None]] = None
        self.on_track_source_resolved: Optional[Callable[[str, str, str], None]] = None
        self.on_track_progress: Optional[Callable[[str, float, str, str], None]] = None
        self.on_track_status_changed: Optional[Callable[[str, str], None]] = None
        self.on_track_completed: Optional[Callable[[str, str], None]] = None
        self.on_track_failed: Optional[Callable[[str, str], None]] = None
        self.on_musilon_limit_reached: Optional[Callable[[TrackMetadata, QueueItem, Callable[[str], None]], None]] = None

        self._allow_yt_on_limit = False
        self._limit_lock = threading.Lock()

    def get_effective_concurrency(self) -> int:
        """
        Returns effective concurrency. If MeloBot Telegram engine is active,
        strictly enforces 1 concurrent song at a time to prevent Telegram chat collisions.
        """
        source = str(config.get("source_engine", "musilon")).strip().lower()
        use_melobot = (source == "melobot" or (config.get("telegram.enabled", False) and not config.get("musilon.enabled", True)))
        if use_melobot:
            return 1
        return max(1, min(10, self.max_workers))

    def start(self):
        with self._lock:
            self._paused.set()
            if not self._running:
                self._running = True

            # Ensure worker threads are alive up to effective concurrency
            self._worker_threads = [t for t in self._worker_threads if t.is_alive()]
            num_workers = self.get_effective_concurrency()
            while len(self._worker_threads) < num_workers:
                idx = len(self._worker_threads)
                t = threading.Thread(target=self._worker_loop, name=f"DownloadWorker-{idx}", daemon=True)
                t.start()
                self._worker_threads.append(t)
            logger.info(f"Started DownloadQueueManager with {len(self._worker_threads)} workers (effective concurrency: {num_workers}).")

    def start_all(self) -> int:
        """
        User-triggered action to start downloading queued / stopped / paused items.
        Re-queues any non-completed tracks if not in processing queue and starts workers.
        """
        with self._lock:
            # Drain queue to avoid stale duplicate entries
            while not self._queue.empty():
                try:
                    self._queue.get_nowait()
                    self._queue.task_done()
                except queue.Empty:
                    break

            pending_count = 0
            for item in self._items.values():
                if item.status in ("Queued", "Stopped", "Paused", "Failed"):
                    item.status = "Queued"
                    item.cancelled = False
                    self._queue.put(item)
                    pending_count += 1
                    if self.on_track_status_changed:
                        self.on_track_status_changed(item.track.id, "Queued")

            self._running = True
            self._paused.set()

            # Ensure worker threads match effective concurrency
            self._worker_threads = [t for t in self._worker_threads if t.is_alive()]
            num_workers = self.get_effective_concurrency()
            while len(self._worker_threads) < num_workers:
                idx = len(self._worker_threads)
                t = threading.Thread(target=self._worker_loop, name=f"DownloadWorker-{idx}", daemon=True)
                t.start()
                self._worker_threads.append(t)

            logger.info(f"Started DownloadQueueManager: {pending_count} tracks enqueued for download across {len(self._worker_threads)} workers (effective limit: {num_workers}).")
            return pending_count

    def update_concurrency(self, new_concurrency: Optional[int] = None):
        """Dynamically scales the worker pool up or down to the effective concurrency."""
        with self._lock:
            if new_concurrency is not None:
                self.max_workers = max(1, min(10, new_concurrency))
            target_workers = self.get_effective_concurrency()

            if self._running:
                self._worker_threads = [t for t in self._worker_threads if t.is_alive()]
                while len(self._worker_threads) < target_workers:
                    idx = len(self._worker_threads)
                    t = threading.Thread(target=self._worker_loop, name=f"DownloadWorker-{idx}", daemon=True)
                    t.start()
                    self._worker_threads.append(t)
            logger.info(f"DownloadQueueManager concurrency set to {target_workers} (base setting: {self.max_workers}, active workers: {len(self._worker_threads)})")

    def pause(self):
        with self._lock:
            self._paused.clear()
            for it in self._items.values():
                if it.status in ("Downloading", "Resolving"):
                    it.status = "Paused"
                    if self.on_track_status_changed:
                        self.on_track_status_changed(it.track.id, "Paused")
        logger.info("Download queue paused.")

    def resume(self):
        with self._lock:
            self._paused.set()
            for it in self._items.values():
                if it.status == "Paused":
                    it.status = "Downloading"
                    if self.on_track_status_changed:
                        self.on_track_status_changed(it.track.id, "Downloading")
        logger.info("Download queue resumed.")

    def is_paused(self) -> bool:
        return not self._paused.is_set()

    def retry_failed(self) -> int:
        """Finds all items in 'Failed' or 'Stopped' status, resets them, and re-queues them."""
        with self._lock:
            failed_items = [it for it in self._items.values() if it.status in ("Failed", "Stopped")]
            for item in failed_items:
                item.status = "Queued"
                item.progress_percent = 0.0
                item.error_message = ""
                item.cancelled = False
                item.speed_str = ""
                item.eta_str = ""
                self._queue.put(item)
                if self.on_track_status_changed:
                    self.on_track_status_changed(item.track.id, "Queued")
            if failed_items:
                self.start_all()
            logger.info(f"Re-queued {len(failed_items)} failed tracks for download.")
            return len(failed_items)

    def retry_track(self, track_id: str) -> bool:
        """Retries a specific track by id."""
        with self._lock:
            if track_id in self._items:
                item = self._items[track_id]
                item.status = "Queued"
                item.progress_percent = 0.0
                item.error_message = ""
                item.cancelled = False
                item.speed_str = ""
                item.eta_str = ""
                self._queue.put(item)
                if self.on_track_status_changed:
                    self.on_track_status_changed(track_id, "Queued")
                self.start_all()
                return True
        return False

    def stop(self):
        """
        Stops active downloads immediately:
        - Drains pending items from queue and marks them 'Stopped'
        - Marks active in-flight items with cancelled = True and 'Stopped'
        - Reverts queued tracks back to pending in saved playlists
        - Unpauses and terminates worker threads cleanly
        """
        with self._lock:
            while not self._queue.empty():
                try:
                    it = self._queue.get_nowait()
                    it.cancelled = True
                    if it.status == "Queued":
                        it.status = "Stopped"
                        if self.on_track_status_changed:
                            self.on_track_status_changed(it.track.id, "Stopped")
                    self._queue.task_done()
                except queue.Empty:
                    break

            for it in self._items.values():
                if it.status in ("Downloading", "Resolving", "Paused", "Queued", "Stopped"):
                    it.cancelled = True
                    if it.status != "Stopped":
                        it.status = "Stopped"
                        if self.on_track_status_changed:
                            self.on_track_status_changed(it.track.id, "Stopped")

            self._running = False
            self._allow_yt_on_limit = False
            self._paused.set()  # Unblock workers so they cleanly exit

            # Revert any queued or stopped tracks in SQLite back to pending so they can be re-downloaded
            try:
                self.archive.revert_queued_tracks_to_pending()
            except Exception as e_rev:
                logger.debug(f"Could not revert queued tracks on stop: {e_rev}")

            try:
                self.archive.checkpoint_wal()
            except Exception:
                pass

        logger.info("Download queue stopped.")

    def enqueue(self, tracks: List[TrackMetadata]):
        with self._lock:
            enqueued_items: List[QueueItem] = []
            for t in tracks:
                if t.id in self._items:
                    existing = self._items[t.id]
                    if existing.status in ("Queued", "Downloading", "Resolving"):
                        continue
                    # Re-queue previously stopped/cancelled/failed items without adding duplicates
                    existing.status = "Queued"
                    existing.cancelled = False
                    existing.progress_percent = 0.0
                    existing.error_message = ""
                    existing.speed_str = ""
                    existing.eta_str = ""
                    existing.preferred_engine = getattr(t, "preferred_engine", None)
                    self._queue.put(existing)
                    enqueued_items.append(existing)
                    if self.on_track_status_changed:
                        self.on_track_status_changed(t.id, "Queued")
                    continue

                item = QueueItem(track=t, status="Queued", preferred_engine=getattr(t, "preferred_engine", None))
                self._items[t.id] = item
                self._queue.put(item)
                enqueued_items.append(item)
                if self.on_track_enqueued and not self.on_tracks_enqueued:
                    self.on_track_enqueued(item)

            if enqueued_items and self.on_tracks_enqueued:
                self.on_tracks_enqueued(enqueued_items)

        logger.info(f"Enqueued {len(tracks)} tracks. Total queue size: {self._queue.qsize()}")

    def cancel_track(self, track_id: str):
        with self._lock:
            if track_id in self._items:
                item = self._items[track_id]
                item.cancelled = True
                item.status = "Cancelled"
                if self.on_track_status_changed:
                    self.on_track_status_changed(track_id, "Cancelled")
            try:
                self.archive.update_saved_track_status_by_spotify_id(track_id, "pending")
            except Exception as e_arc:
                logger.debug(f"Could not update archive status on cancel: {e_arc}")
        logger.info(f"Cancelled track {track_id}")

    def remove_track(self, track_id: str):
        """Cancels track if running and removes it completely from queue tracking."""
        with self._lock:
            if track_id in self._items:
                self._items[track_id].cancelled = True
                del self._items[track_id]
        logger.info(f"Removed track {track_id} from queue manager.")

    def remove_tracks(self, track_ids: List[str]):
        """Bulk removal of tracks from queue manager."""
        with self._lock:
            for tid in track_ids:
                if tid in self._items:
                    self._items[tid].cancelled = True
                    del self._items[tid]
        logger.info(f"Removed {len(track_ids)} tracks from queue manager.")

    def clear_completed(self):
        with self._lock:
            completed_ids = [tid for tid, it in self._items.items() if it.status == "Completed"]
            for tid in completed_ids:
                del self._items[tid]
        logger.info(f"Cleared {len(completed_ids)} completed items from tracker.")

    def get_items(self) -> List[QueueItem]:
        with self._lock:
            return list(self._items.values())

    def _worker_loop(self):
        while self._running:
            self._paused.wait()  # Block while paused

            # Check if active workers exceed effective concurrency limit (e.g. scaled down for Telegram single-song mode)
            with self._lock:
                effective_limit = self.get_effective_concurrency()
                alive_workers = [t for t in self._worker_threads if t.is_alive()]
                if len(alive_workers) > effective_limit:
                    current_t = threading.current_thread()
                    if current_t in self._worker_threads:
                        self._worker_threads.remove(current_t)
                    logger.debug(f"Worker {current_t.name} gracefully exiting to respect effective concurrency of {effective_limit}.")
                    return

            try:
                item = self._queue.get(timeout=1.0)
            except queue.Empty:
                continue

            if not self._running:
                break

            if item.cancelled:
                self._queue.task_done()
                continue

            try:
                self._process_item(item)
            except Exception as e_proc:
                logger.error(f"Unexpected error in _process_item for '{item.track.title}': {e_proc}", exc_info=True)
            finally:
                self._queue.task_done()

    def _process_item(self, item: QueueItem):
        track = item.track
        track_id = track.id

        try:
            # 0. Wait if queue is paused
            self._paused.wait()
            if item.cancelled:
                self._update_status(item, "Cancelled")
                return

            # Compute target destination folder
            base_output_dir = config.get("download.output_dir", os.path.expanduser("~/Music/Spotify Downloads"))
            save_in_subfolders = config.get("download.save_in_subfolders", False)
            subfolder = getattr(track, "target_folder", "") if save_in_subfolders else ""
            norm_base = os.path.normpath(base_output_dir)
            if subfolder and os.path.basename(norm_base).lower() != subfolder.lower():
                output_dir = os.path.join(base_output_dir, subfolder)
            else:
                output_dir = base_output_dir
            is_album = (getattr(track, "collection_type", "track") == "album")
            if is_album and getattr(track, "track_number", 0) > 0:
                naming_tmpl = config.get("download.album_naming_template", "{track_num}. {artist} - {title}")
            else:
                naming_tmpl = config.get("download.naming_template", "{artist} - {title}")

            # Save collection (playlist / album) cover art to dedicated app cache directory
            coll_cover_url = getattr(track, "collection_cover_url", "")
            coll_type = getattr(track, "collection_type", "track")
            coll_name = getattr(track, "collection_name", "")
            if coll_cover_url and coll_type in ("playlist", "album") and coll_name:
                try:
                    cache_dir = config.get("download.cache_dir", "")
                    covers_dir = os.path.join(cache_dir, "covers") if cache_dir else str(get_covers_dir())
                    os.makedirs(covers_dir, exist_ok=True)
                    safe_coll = sanitize_filename(coll_name, max_length=50)
                    cover_target = os.path.join(covers_dir, f"{coll_type}_{safe_coll}.jpg")

                    if not os.path.isfile(cover_target):
                        r_cov = requests.get(coll_cover_url, timeout=8)
                        if r_cov.status_code == 200 and len(r_cov.content) > 500:
                            with open(cover_target, "wb") as f_cov:
                                f_cov.write(r_cov.content)
                            logger.info(f"Saved authentic collection cover art to app cache: {cover_target}")
                except Exception as e_cov:
                    logger.debug(f"Could not save collection cover art to cache: {e_cov}")

            # 1. Archive Deduplication Check (Instant Local Reuse)
            # If the user explicitly requested a specific engine or a re-download, bypass archive reuse
            skip_archive = bool(getattr(track, "preferred_engine", None) or getattr(item, "preferred_engine", None))
            archived = None
            if not skip_archive:
                archived = self.archive.find_track(
                    spotify_id=track.id,
                    isrc=track.isrc,
                    title=track.title,
                    artist=track.primary_artist
                )

            # Ensure archived file is a genuine playable audio file before reusing
            if archived and os.path.isfile(archived.get("file_path", "")):
                src_file = os.path.normpath(archived["file_path"])
                is_valid, _ = is_valid_audio_file(src_file)
                if not is_valid:
                    logger.warning(f"Archived file '{src_file}' failed integrity check; redownloading freshly.")
                    archived = None

            if archived and os.path.isfile(archived.get("file_path", "")):
                src_file = os.path.normpath(archived["file_path"])
                file_ext = os.path.splitext(src_file)[1]
                artist_clean = sanitize_filename(track.primary_artist, max_length=40)
                title_clean = sanitize_filename(track.title, max_length=40)
                track_num_str = f"{track.track_number:02d}"
                disc_num_str = f"{getattr(track, 'disc_number', 1) or 1:02d}"
                try:
                    base_name = naming_tmpl.format(
                        artist=artist_clean,
                        title=title_clean,
                        album=sanitize_filename(track.album, max_length=40),
                        track_num=track_num_str,
                        track_number=track_num_str,
                        track=track_num_str,
                        disc_num=disc_num_str,
                        disc_number=disc_num_str
                    )
                except Exception:
                    if is_album and getattr(track, "track_number", 0) > 0:
                        base_name = f"{track_num_str}. {artist_clean} - {title_clean}"
                    else:
                        base_name = f"{artist_clean} - {title_clean}"
                base_name = sanitize_filename(base_name, max_length=120)
                target_dest = os.path.normpath(os.path.join(output_dir, f"{base_name}{file_ext}"))

                save_in_subfolders = config.get("download.save_in_subfolders", False)
                if not save_in_subfolders or os.path.abspath(src_file) == os.path.abspath(target_dest):
                    # Same exact file in the destination folder
                    item.output_path = src_file
                    item.quality_badge = archived.get("quality_badge") or self.archive.infer_badge_from_file(src_file)[0] or "FLAC 16"
                    item.source_type = archived.get("source_type") or self.archive.infer_badge_from_file(src_file)[1] or "Musilon"
                    item.progress_percent = 100.0
                    self._update_status(item, "Completed")
                    if self.on_track_source_resolved:
                        self.on_track_source_resolved(track_id, item.source_type, item.quality_badge)
                    if self.on_track_progress:
                        self.on_track_progress(track_id, 100.0, "Archived", "00:00")
                    if self.on_track_completed:
                        self.on_track_completed(track_id, src_file)
                    self.archive.mark_saved_track_downloaded(track.id, src_file, item.quality_badge, item.source_type)
                    logger.info(f"Reused existing archive file for '{track.title}': {src_file}")
                    return
                else:
                    # File exists in another folder (e.g. from Singles or another playlist)
                    try:
                        os.makedirs(os.path.dirname(target_dest), exist_ok=True)
                        shutil.copy2(src_file, target_dest)
                        lyrics_mode = config.get("download.lyrics_mode", "embedded_only")
                        if lyrics_mode != "embedded_only":
                            src_lrc = os.path.splitext(src_file)[0] + ".lrc"
                            if lyrics_mode == "separate_folder":
                                lrc_dir = os.path.join(output_dir, "lyrics")
                                os.makedirs(lrc_dir, exist_ok=True)
                                target_lrc = os.path.join(lrc_dir, f"{base_name}.lrc")
                            else:
                                target_lrc = os.path.splitext(target_dest)[0] + ".lrc"
                            if os.path.isfile(src_lrc):
                                shutil.copy2(src_lrc, target_lrc)

                        # Retag copied file if it was copied into an album, ensuring proper track numbers
                        if is_album and getattr(track, "track_number", 0) > 0:
                            try:
                                from core.tagger import AudioTagger
                                AudioTagger().tag_file(
                                    file_path=target_dest,
                                    track=track,
                                    embed_lyrics=config.get("download.embed_lyrics", True),
                                    embed_art=config.get("download.embed_cover_art", True)
                                )
                            except Exception as e_tag:
                                logger.debug(f"Retagging archived track for album failed: {e_tag}")

                        item.output_path = target_dest
                        item.quality_badge = archived.get("quality_badge") or self.archive.infer_badge_from_file(target_dest)[0] or "FLAC 16"
                        item.source_type = "Local Archive"
                        item.progress_percent = 100.0
                        self._update_status(item, "Completed")
                        if self.on_track_source_resolved:
                            self.on_track_source_resolved(track_id, item.source_type, item.quality_badge)
                        if self.on_track_progress:
                            self.on_track_progress(track_id, 100.0, "Copied", "00:00")
                        if self.on_track_completed:
                            self.on_track_completed(track_id, target_dest)
                        self.archive.add_track(track, target_dest, item.quality_badge, "Local Archive", genre=archived.get("genre", ""))
                        self.archive.mark_saved_track_downloaded(track.id, target_dest, item.quality_badge, item.source_type)
                        logger.info(f"Copied archived track '{track.title}' to {target_dest}")
                        return
                    except Exception as copy_err:
                        logger.warning(f"Failed to copy archived file ({copy_err}). Falling back to fresh download.")

            if item.cancelled or not self._running:
                self._update_status(item, "Stopped")
                return

            def cancel_check() -> bool:
                return item.cancelled or not self._running

            def pause_wait():
                self._paused.wait()

            # 2. Resolving Phase
            self._paused.wait()
            if cancel_check():
                self._update_status(item, "Stopped")
                self.archive.update_saved_track_status_by_spotify_id(track_id, "pending")
                return

            self._update_status(item, "Resolving")
            
            # If Musilon daily limit was reached and user elected to continue with YouTube,
            # bypass Musilon search entirely for subsequent tracks in the queue.
            skip_mus = False
            with self._limit_lock:
                skip_mus = self._allow_yt_on_limit

            self._paused.wait()
            if cancel_check():
                self._update_status(item, "Stopped")
                self.archive.update_saved_track_status_by_spotify_id(track_id, "pending")
                return

            pref_eng = getattr(track, "preferred_engine", None) or getattr(item, "preferred_engine", None)
            source_engine = str(config.get("source_engine", "musilon")).strip().lower()
            is_melobot_mode = (pref_eng == "melobot" or source_engine == "melobot" or (config.get("telegram.enabled", False) and not config.get("musilon.enabled", True)))
            if is_melobot_mode:
                skip_mus = True

            if pref_eng == "melobot" or (not pref_eng and is_melobot_mode):
                with self._telegram_stream_lock:
                    resolved = self.engine.resolve_source(track, skip_musilon=skip_mus, cancel_check=cancel_check, preferred_engine=pref_eng)
            else:
                resolved = self.engine.resolve_source(track, skip_musilon=skip_mus, cancel_check=cancel_check, preferred_engine=pref_eng)

            if cancel_check():
                self._update_status(item, "Stopped")
                self.archive.update_saved_track_status_by_spotify_id(track_id, "pending")
                return

            if not resolved:
                raise AudioSourceNotFoundError("No matching audio source found across MeloBot, Musilon, or YouTube Music.")

            item.source_type = resolved.source_type
            item.quality_badge = resolved.quality_badge
            if self.on_track_source_resolved:
                self.on_track_source_resolved(track_id, resolved.source_type, resolved.quality_badge)

            if cancel_check():
                self._update_status(item, "Stopped")
                self.archive.update_saved_track_status_by_spotify_id(track_id, "pending")
                return

            self._paused.wait()

            # 3. Download and Tagging Phase
            save_lrc = config.get("download.save_lrc", True)
            embed_lyrics = config.get("download.embed_lyrics", True)
            embed_art = config.get("download.embed_cover_art", True)

            def progress_cb(percent: float, speed_str: str, eta_str: str):
                item.progress_percent = percent
                item.speed_str = speed_str
                item.eta_str = eta_str
                if self.on_track_progress:
                    self.on_track_progress(track_id, percent, speed_str, eta_str)

            def status_cb(status_str: str):
                self._update_status(item, status_str)

            # Download & Tag with controlled stream Semaphore and post-download cooldown
            is_musilon = (resolved.source_type == "Musilon")
            is_melobot = (resolved.source_type == "MeloBot")
            if is_musilon:
                with self._musilon_stream_lock:
                    if cancel_check():
                        self._update_status(item, "Stopped")
                        self.archive.update_saved_track_status_by_spotify_id(track_id, "pending")
                        return

                    file_path = self.engine.download_and_tag(
                        track=track,
                        resolved=resolved,
                        output_dir=output_dir,
                        naming_template=naming_tmpl,
                        save_lrc=save_lrc,
                        embed_lyrics=embed_lyrics,
                        embed_art=embed_art,
                        progress_callback=progress_cb,
                        status_callback=status_cb,
                        cancel_check=cancel_check,
                        pause_wait=pause_wait
                    )

                # Post-download VIP cooldown is decoupled from stream lock so next download can begin
                if file_path and os.path.isfile(file_path) and config.get("musilon.safe_mode", True) and not cancel_check():
                    min_cd = max(0, int(config.get("musilon.cooldown_min_sec", 15)))
                    max_cd = max(min_cd, int(config.get("musilon.cooldown_max_sec", 35)))
                    cooldown_secs = random.randint(min_cd, max_cd) if max_cd > 0 else 0
                    if cooldown_secs > 0:
                        logger.info(f"Musilon Safe Mode: cooling down for {cooldown_secs}s to evade rate limits...")
                        for remaining in range(cooldown_secs, 0, -1):
                            if cancel_check():
                                break
                            self._paused.wait()
                            status_cb(f"VIP Cooldown ({remaining}s)")
                            for _ in range(10):
                                if cancel_check():
                                    break
                                time.sleep(0.1)
            elif is_melobot:
                with self._telegram_stream_lock:
                    if cancel_check():
                        self._update_status(item, "Stopped")
                        self.archive.update_saved_track_status_by_spotify_id(track_id, "pending")
                        return

                    file_path = self.engine.download_and_tag(
                        track=track,
                        resolved=resolved,
                        output_dir=output_dir,
                        naming_template=naming_tmpl,
                        save_lrc=save_lrc,
                        embed_lyrics=embed_lyrics,
                        embed_art=embed_art,
                        progress_callback=progress_cb,
                        status_callback=status_cb,
                        cancel_check=cancel_check,
                        pause_wait=pause_wait
                    )

                # Polite pause between bot requests
                delay_sec = max(0.0, float(config.get("telegram.safe_delay_sec", 0.5)))
                if delay_sec > 0 and not cancel_check():
                    time.sleep(delay_sec)
            else:
                file_path = self.engine.download_and_tag(
                    track=track,
                    resolved=resolved,
                    output_dir=output_dir,
                    naming_template=naming_tmpl,
                    save_lrc=save_lrc,
                    embed_lyrics=embed_lyrics,
                    embed_art=embed_art,
                    progress_callback=progress_cb,
                    status_callback=status_cb,
                    cancel_check=cancel_check,
                    pause_wait=pause_wait
                )

            if cancel_check():
                self._update_status(item, "Stopped")
                self.archive.update_saved_track_status_by_spotify_id(track_id, "pending")
                return

            if file_path and os.path.isfile(file_path):
                act_ext = os.path.splitext(file_path)[1].lstrip(".").lower()
                # Strict sanity check: Opus or M4A files from YouTube Music must never be marked as Musilon
                if act_ext == "opus" or (resolved and resolved.source_type in ("YouTube Music", "YouTube")):
                    item.source_type = "YouTube Music" if resolved and resolved.source_type != "YouTube" else "YouTube"
                    item.quality_badge = "YTM Opus" if act_ext == "opus" else ("YTM M4A" if act_ext == "m4a" else item.quality_badge)
                    if self.on_track_source_resolved:
                        self.on_track_source_resolved(track_id, item.source_type, item.quality_badge)
                elif resolved:
                    if resolved.quality_badge and resolved.quality_badge != item.quality_badge:
                        item.quality_badge = resolved.quality_badge
                    if resolved.source_type and resolved.source_type != item.source_type:
                        item.source_type = resolved.source_type
                    if self.on_track_source_resolved:
                        self.on_track_source_resolved(track_id, item.source_type, item.quality_badge)
            elif resolved:
                if resolved.quality_badge and resolved.quality_badge != item.quality_badge:
                    item.quality_badge = resolved.quality_badge
                if resolved.source_type and resolved.source_type != item.source_type:
                    item.source_type = resolved.source_type
                if self.on_track_source_resolved:
                    self.on_track_source_resolved(track_id, item.source_type, item.quality_badge)

            item.output_path = file_path or ""
            self._update_status(item, "Completed")

            # Record in Archive
            if file_path and os.path.isfile(file_path):
                self.archive.add_track(track, file_path, item.quality_badge, item.source_type, genre=track.genre_str)
                self.archive.mark_saved_track_downloaded(track.id, file_path, item.quality_badge, item.source_type)
                if config.get("download.generate_m3u8", True) and getattr(track, "collection_type", "track") in ("playlist", "album"):
                    try:
                        coll_name = getattr(track, "collection_name", "")
                        if coll_name:
                            threading.Thread(
                                target=self.archive.export_collection_m3u8,
                                args=(coll_name,),
                                daemon=True,
                                name="M3U8Generator"
                            ).start()
                    except Exception as e_m3u8:
                        logger.debug(f"m3u8 playlist file generation note: {e_m3u8}")

            if self.on_track_completed:
                self.on_track_completed(track_id, item.output_path)

        except (MeloBotDownloadError, MeloBotError) as e_melo:
            if cancel_check():
                self._update_status(item, "Stopped")
                self.archive.update_saved_track_status_by_spotify_id(track_id, "pending")
                return
            logger.warning(f"MeloBot issue for '{track.title}': {e_melo}. Checking fallback...")
            allow_fallback = config.get("download.allow_fallback", True)
            if allow_fallback and not cancel_check():
                self._fallback_to_youtube(
                    item=item,
                    track=track,
                    output_dir=output_dir,
                    naming_tmpl=naming_tmpl,
                    save_lrc=save_lrc,
                    embed_lyrics=embed_lyrics,
                    embed_art=embed_art,
                    progress_cb=progress_cb,
                    status_cb=status_cb,
                    cancel_check=cancel_check,
                    pause_wait=pause_wait
                )
            else:
                self._update_status(item, "Failed")
                item.error_message = str(e_melo)
                self.archive.update_saved_track_status_by_spotify_id(track_id, "pending")
                if self.on_track_failed:
                    self.on_track_failed(track_id, str(e_melo))

        except (MusilonRateLimitExceededError, MusilonVipError, MusilonDownloadError, MusilonError) as e_musilon:
            if cancel_check():
                self._update_status(item, "Stopped")
                self.archive.update_saved_track_status_by_spotify_id(track_id, "pending")
                return

            pref_eng = getattr(track, "preferred_engine", None) or getattr(item, "preferred_engine", None)
            source_engine = str(config.get("source_engine", "musilon")).strip().lower()
            is_melobot_user = (pref_eng == "melobot" or source_engine == "melobot" or getattr(item, "source_type", "") == "MeloBot" or (config.get("telegram.enabled", False) and not config.get("musilon.enabled", True)))

            if is_melobot_user:
                logger.info(f"Musilon error ignored during MeloBot session for '{track.title}': {e_musilon}. Suppressing popup and falling back to YouTube Music...")
                allow_fallback = config.get("download.allow_fallback", True)
                if allow_fallback and not cancel_check():
                    self._fallback_to_youtube(
                        item=item,
                        track=track,
                        output_dir=output_dir,
                        naming_tmpl=naming_tmpl,
                        save_lrc=save_lrc,
                        embed_lyrics=embed_lyrics,
                        embed_art=embed_art,
                        progress_cb=progress_cb,
                        status_cb=status_cb,
                        cancel_check=cancel_check,
                        pause_wait=pause_wait
                    )
                else:
                    self._update_status(item, "Failed")
                    item.error_message = str(e_musilon)
                    self.archive.update_saved_track_status_by_spotify_id(track_id, "pending")
                    if self.on_track_failed:
                        self.on_track_failed(track_id, str(e_musilon))
                return

            logger.warning(f"Musilon issue encountered for '{track.title}': {e_musilon}. Prompting user or checking session preference...")

            use_yt = False
            with self._limit_lock:
                if self._allow_yt_on_limit:
                    use_yt = True
                else:
                    self.pause()
                    self._update_status(item, "Musilon Issue")

                    if isinstance(e_musilon, MusilonRateLimitExceededError):
                        reason_str = f"Download rate limit or daily VIP quota reached ({e_musilon})."
                    elif isinstance(e_musilon, MusilonVipError):
                        reason_str = f"VIP authentication or subscription required ({e_musilon})."
                    else:
                        reason_str = f"Musilon stream download failed ({e_musilon})."

                    decision_event = threading.Event()
                    decision_action = ["stop"]

                    def on_decision(action: str):
                        decision_action[0] = action
                        decision_event.set()

                    if self.on_musilon_limit_reached:
                        try:
                            import inspect
                            sig = inspect.signature(self.on_musilon_limit_reached)
                            if len(sig.parameters) >= 4:
                                self.on_musilon_limit_reached(track, item, reason_str, on_decision)
                            else:
                                self.on_musilon_limit_reached(track, item, on_decision)
                        except Exception as e_hook:
                            logger.error(f"Error invoking on_musilon_limit_reached: {e_hook}")
                            decision_event.set()
                    else:
                        decision_event.set()

                    while not decision_event.wait(timeout=0.25):
                        if cancel_check():
                            decision_action[0] = "stop"
                            break

                    if decision_action[0] == "continue_youtube" and not cancel_check():
                        self._allow_yt_on_limit = True
                        self.resume()
                        use_yt = True
                    else:
                        self.stop()
                        self._update_status(item, "Stopped")
                        self.archive.update_saved_track_status_by_spotify_id(track_id, "pending")
                        return

            if use_yt and not cancel_check():
                self._fallback_to_youtube(
                    item=item,
                    track=track,
                    output_dir=output_dir,
                    naming_tmpl=naming_tmpl,
                    save_lrc=save_lrc,
                    embed_lyrics=embed_lyrics,
                    embed_art=embed_art,
                    progress_cb=progress_cb,
                    status_cb=status_cb,
                    cancel_check=cancel_check,
                    pause_wait=pause_wait
                )

        except Exception as e:
            if item.cancelled or not self._running:
                self._update_status(item, "Stopped")
                self.archive.update_saved_track_status_by_spotify_id(track_id, "pending")
                return
            logger.error(f"Failed to process track '{track.title}': {e}")
            item.error_message = str(e)
            self._update_status(item, "Failed")
            self.archive.update_saved_track_status_by_spotify_id(track_id, "pending")
            if self.on_track_failed:
                self.on_track_failed(track_id, str(e))

    def _fallback_to_youtube(
        self,
        item: QueueItem,
        track: TrackMetadata,
        output_dir: str,
        naming_tmpl: str,
        save_lrc: bool,
        embed_lyrics: bool,
        embed_art: bool,
        progress_cb: Callable,
        status_cb: Callable,
        cancel_check: Callable[[], bool],
        pause_wait: Callable[[], None]
    ):
        if cancel_check():
            self._update_status(item, "Stopped")
            self.archive.update_saved_track_status_by_spotify_id(track.id, "pending")
            return

        self._update_status(item, "Resolving (YTM Fallback)")
        yt_src = self.engine.ytdlp.resolve_track(track, cancel_check=cancel_check)
        if cancel_check():
            self._update_status(item, "Stopped")
            self.archive.update_saved_track_status_by_spotify_id(track.id, "pending")
            return

        if not yt_src:
            raise AudioSourceNotFoundError(f"YouTube Music fallback could not find audio for '{track.title}'.")

        act_ext = yt_src.audio_format or "opus"
        badge = "YTM M4A" if act_ext.lower() == "m4a" else "YTM Opus"
        resolved_yt = ResolvedTrackSource(
            source_type="YouTube Music",
            quality_badge=badge,
            source_obj=yt_src,
            file_extension=act_ext
        )
        item.source_type = resolved_yt.source_type
        item.quality_badge = resolved_yt.quality_badge
        if self.on_track_source_resolved:
            self.on_track_source_resolved(track.id, resolved_yt.source_type, resolved_yt.quality_badge)

        file_path = self.engine.download_and_tag(
            track=track,
            resolved=resolved_yt,
            output_dir=output_dir,
            naming_template=naming_tmpl,
            save_lrc=save_lrc,
            embed_lyrics=embed_lyrics,
            embed_art=embed_art,
            progress_callback=progress_cb,
            status_callback=status_cb,
            cancel_check=cancel_check,
            pause_wait=pause_wait
        )
        if cancel_check():
            self._update_status(item, "Stopped")
            self.archive.update_saved_track_status_by_spotify_id(track.id, "pending")
            return

        if file_path and os.path.isfile(file_path):
            act_ext = os.path.splitext(file_path)[1].lstrip(".").lower()
            item.source_type = "YouTube Music"
            item.quality_badge = "YTM Opus" if act_ext == "opus" else ("YTM M4A" if act_ext == "m4a" else item.quality_badge)
            if self.on_track_source_resolved:
                self.on_track_source_resolved(track.id, item.source_type, item.quality_badge)

        item.output_path = file_path or ""
        self._update_status(item, "Completed")
        if file_path and os.path.isfile(file_path):
            self.archive.add_track(track, file_path, item.quality_badge, item.source_type, genre=track.genre_str)
            self.archive.mark_saved_track_downloaded(track.id, file_path, item.quality_badge, item.source_type)
        if self.on_track_completed:
            self.on_track_completed(track.id, item.output_path)

    def _update_status(self, item: QueueItem, status: str):
        with self._lock:
            if not self._running and status not in ("Stopped", "Cancelled"):
                return
            item.status = status
            if self.on_track_status_changed:
                self.on_track_status_changed(item.track.id, status)
