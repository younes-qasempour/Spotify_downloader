import os
import time
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
from core.archive import ArchiveManager
from core.utils import sanitize_filename, is_valid_audio_file
from core.config import config

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
        max_concurrent_downloads: int = 2
    ):
        self.engine = audio_engine or CascadingAudioEngine()
        self.archive = archive_manager or ArchiveManager()
        self.max_workers = max_concurrent_downloads

        self._queue: queue.Queue[QueueItem] = queue.Queue()
        self._items: Dict[str, QueueItem] = {}  # track_id -> QueueItem
        self._lock = threading.RLock()
        self._paused = threading.Event()
        self._paused.set()  # Not paused by default
        self._running = False
        self._worker_threads: List[threading.Thread] = []

        # Musilon bottleneck lock to ensure strict sequential requests
        self._musilon_lock = threading.Lock()

        # Decoupled Event Callbacks
        self.on_track_enqueued: Optional[Callable[[QueueItem], None]] = None
        self.on_track_source_resolved: Optional[Callable[[str, str, str], None]] = None
        self.on_track_progress: Optional[Callable[[str, float, str, str], None]] = None
        self.on_track_status_changed: Optional[Callable[[str, str], None]] = None
        self.on_track_completed: Optional[Callable[[str, str], None]] = None
        self.on_track_failed: Optional[Callable[[str, str], None]] = None

    def start(self):
        with self._lock:
            if self._running:
                return
            self._running = True
            self._paused.set()

            # Start worker threads
            num_workers = max(1, config.get("download.concurrency", self.max_workers))
            for i in range(num_workers):
                t = threading.Thread(target=self._worker_loop, name=f"DownloadWorker-{i}", daemon=True)
                t.start()
                self._worker_threads.append(t)
            logger.info(f"Started DownloadQueueManager with {num_workers} workers.")

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

            # Ensure worker threads are alive
            self._worker_threads = [t for t in self._worker_threads if t.is_alive()]
            num_workers = max(1, config.get("download.concurrency", self.max_workers))
            while len(self._worker_threads) < num_workers:
                idx = len(self._worker_threads)
                t = threading.Thread(target=self._worker_loop, name=f"DownloadWorker-{idx}", daemon=True)
                t.start()
                self._worker_threads.append(t)

            logger.info(f"Started DownloadQueueManager: {pending_count} tracks enqueued for download across {len(self._worker_threads)} workers.")
            return pending_count

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
        """Finds all items in 'Failed' status, resets them, and re-queues them."""
        with self._lock:
            failed_items = [it for it in self._items.values() if it.status == "Failed"]
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
        - Unpauses and terminates worker threads cleanly
        """
        with self._lock:
            while not self._queue.empty():
                try:
                    it = self._queue.get_nowait()
                    if it.status == "Queued":
                        it.status = "Stopped"
                        if self.on_track_status_changed:
                            self.on_track_status_changed(it.track.id, "Stopped")
                    self._queue.task_done()
                except queue.Empty:
                    break

            for it in self._items.values():
                if it.status in ("Downloading", "Resolving", "Paused", "Queued"):
                    it.cancelled = True
                    it.status = "Stopped"
                    if self.on_track_status_changed:
                        self.on_track_status_changed(it.track.id, "Stopped")

            self._running = False
            self._paused.set()  # Unblock workers so they cleanly exit
        logger.info("Download queue stopped.")

    def enqueue(self, tracks: List[TrackMetadata]):
        with self._lock:
            for t in tracks:
                if t.id in self._items:
                    # If already completed or actively in queue, skip duplicate
                    existing = self._items[t.id]
                    if existing.status in ("Queued", "Downloading", "Resolving"):
                        continue

                item = QueueItem(track=t, status="Queued")
                self._items[t.id] = item
                self._queue.put(item)
                if self.on_track_enqueued:
                    self.on_track_enqueued(item)
        logger.info(f"Enqueued {len(tracks)} tracks. Total queue size: {self._queue.qsize()}")

    def cancel_track(self, track_id: str):
        with self._lock:
            if track_id in self._items:
                item = self._items[track_id]
                item.cancelled = True
                item.status = "Cancelled"
                if self.on_track_status_changed:
                    self.on_track_status_changed(track_id, "Cancelled")
        logger.info(f"Cancelled track {track_id}")

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

            try:
                item = self._queue.get(timeout=1.0)
            except queue.Empty:
                continue

            if not self._running:
                break

            if item.cancelled:
                self._queue.task_done()
                continue

            self._process_item(item)
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
            subfolder = getattr(track, "target_folder", "")
            norm_base = os.path.normpath(base_output_dir)
            if subfolder and os.path.basename(norm_base).lower() != subfolder.lower():
                output_dir = os.path.join(base_output_dir, subfolder)
            else:
                output_dir = base_output_dir
            naming_tmpl = config.get("download.naming_template", "{artist} - {title}")

            # Save collection (playlist / album) cover art to dedicated app cache directory
            coll_cover_url = getattr(track, "collection_cover_url", "")
            coll_type = getattr(track, "collection_type", "track")
            coll_name = getattr(track, "collection_name", "")
            if coll_cover_url and coll_type in ("playlist", "album") and coll_name:
                try:
                    cache_dir = config.get("download.cache_dir", "")
                    if not cache_dir:
                        cache_dir = os.path.normpath(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cache"))
                    covers_dir = os.path.join(cache_dir, "covers")
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
                try:
                    base_name = naming_tmpl.format(
                        artist=artist_clean,
                        title=title_clean,
                        album=sanitize_filename(track.album, max_length=40),
                        track_num=f"{track.track_number:02d}",
                        track_number=f"{track.track_number:02d}",
                        track=f"{track.track_number:02d}"
                    )
                except Exception:
                    base_name = f"{artist_clean} - {title_clean}"
                base_name = sanitize_filename(base_name, max_length=120)
                target_dest = os.path.normpath(os.path.join(output_dir, f"{base_name}{file_ext}"))

                if os.path.abspath(src_file) == os.path.abspath(target_dest):
                    # Same exact file in the destination folder
                    item.output_path = src_file
                    item.quality_badge = archived.get("quality_badge", "FLAC 16")
                    item.source_type = archived.get("source_type", "Musilon")
                    item.progress_percent = 100.0
                    self._update_status(item, "Completed")
                    if self.on_track_source_resolved:
                        self.on_track_source_resolved(track_id, item.source_type, item.quality_badge)
                    if self.on_track_progress:
                        self.on_track_progress(track_id, 100.0, "Archived", "00:00")
                    if self.on_track_completed:
                        self.on_track_completed(track_id, src_file)
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

                        item.output_path = target_dest
                        item.quality_badge = archived.get("quality_badge", "FLAC 16")
                        item.source_type = "Local Archive"
                        item.progress_percent = 100.0
                        self._update_status(item, "Completed")
                        if self.on_track_source_resolved:
                            self.on_track_source_resolved(track_id, item.source_type, item.quality_badge)
                        if self.on_track_progress:
                            self.on_track_progress(track_id, 100.0, "Copied", "00:00")
                        if self.on_track_completed:
                            self.on_track_completed(track_id, target_dest)
                        self.archive.add_track(track, target_dest, item.quality_badge, "Local Archive")
                        logger.info(f"Copied archived track '{track.title}' to {target_dest}")
                        return
                    except Exception as copy_err:
                        logger.warning(f"Failed to copy archived file ({copy_err}). Falling back to fresh download.")

            if item.cancelled or not self._running:
                self._update_status(item, "Stopped")
                return

            # 2. Resolving Phase
            self._paused.wait()
            if item.cancelled or not self._running:
                self._update_status(item, "Stopped")
                return

            self._update_status(item, "Resolving")
            
            # Lazy resolution with rate-limiting bottleneck for Musilon
            with self._musilon_lock:
                if item.cancelled or not self._running:
                    self._update_status(item, "Stopped")
                    return
                self._paused.wait()
                resolved = self.engine.resolve_source(track)

            if item.cancelled or not self._running:
                self._update_status(item, "Stopped")
                return

            if not resolved:
                raise RuntimeError("No matching audio source found across Musilon or YouTube Music.")

            item.source_type = resolved.source_type
            item.quality_badge = resolved.quality_badge
            if self.on_track_source_resolved:
                self.on_track_source_resolved(track_id, resolved.source_type, resolved.quality_badge)

            if item.cancelled or not self._running:
                self._update_status(item, "Stopped")
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

            def cancel_check() -> bool:
                return item.cancelled or not self._running

            def pause_wait():
                self._paused.wait()

            # Download & Tag
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

            if item.cancelled or not self._running:
                self._update_status(item, "Stopped")
                return

            item.output_path = file_path or ""
            self._update_status(item, "Completed")

            # Record in Archive
            if file_path and os.path.isfile(file_path):
                self.archive.add_track(track, file_path, item.quality_badge, item.source_type)

            if self.on_track_completed:
                self.on_track_completed(track_id, item.output_path)

        except Exception as e:
            if item.cancelled or not self._running:
                self._update_status(item, "Stopped")
                return
            logger.error(f"Failed to process track '{track.title}': {e}")
            item.error_message = str(e)
            self._update_status(item, "Failed")
            if self.on_track_failed:
                self.on_track_failed(track_id, str(e))

    def _update_status(self, item: QueueItem, status: str):
        with self._lock:
            if not self._running and status not in ("Stopped", "Cancelled"):
                return
            item.status = status
            if self.on_track_status_changed:
                self.on_track_status_changed(item.track.id, status)
