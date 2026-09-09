import os
import time
import queue
import threading
import logging
from dataclasses import dataclass, field
from typing import Optional, Dict, List, Callable, Any
from concurrent.futures import ThreadPoolExecutor

from core.spotify_client import TrackMetadata
from core.resolver import CascadingAudioEngine, ResolvedTrackSource
from core.config import config

logger = logging.getLogger("core.queue")


@dataclass
class QueueItem:
    track: TrackMetadata
    status: str = "Queued"  # "Queued", "Resolving", "Downloading", "Tagging", "Fetching Lyrics", "Completed", "Failed", "Cancelled"
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
    - Sequential Musilon rate-limit throttling
    - Multi-threaded fallback downloads
    - Real-time event and callback dispatching
    """

    def __init__(
        self,
        audio_engine: Optional[CascadingAudioEngine] = None,
        max_concurrent_downloads: int = 2
    ):
        self.engine = audio_engine or CascadingAudioEngine()
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

    def pause(self):
        self._paused.clear()
        logger.info("Download queue paused.")

    def resume(self):
        self._paused.set()
        logger.info("Download queue resumed.")

    def is_paused(self) -> bool:
        return not self._paused.is_set()

    def stop(self):
        with self._lock:
            self._running = False
            self._paused.set()
            # Drain queue
            while not self._queue.empty():
                try:
                    self._queue.get_nowait()
                    self._queue.task_done()
                except queue.Empty:
                    break
        logger.info("Download queue stopped.")

    def enqueue(self, tracks: List[TrackMetadata]):
        with self._lock:
            for t in tracks:
                if t.id in self._items:
                    # If already completed or in queue, skip duplicate
                    existing = self._items[t.id]
                    if existing.status in ("Queued", "Downloading", "Resolving"):
                        continue

                item = QueueItem(track=t)
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
            completed_ids = [tid for tid, it in self._items.items() if it.status in ("Completed", "Cancelled", "Failed")]
            for tid in completed_ids:
                del self._items[tid]
        logger.info("Cleared completed/failed items from tracker.")

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
            # 1. Resolving Phase
            self._update_status(item, "Resolving")
            
            # Lazy resolution with rate-limiting bottleneck for Musilon
            with self._musilon_lock:
                resolved = self.engine.resolve_source(track)

            if not resolved:
                raise RuntimeError("No matching audio source found across Musilon or YouTube Music.")

            item.source_type = resolved.source_type
            item.quality_badge = resolved.quality_badge
            if self.on_track_source_resolved:
                self.on_track_source_resolved(track_id, resolved.source_type, resolved.quality_badge)

            if item.cancelled:
                self._update_status(item, "Cancelled")
                return

            # 2. Download and Tagging Phase
            output_dir = config.get("download.output_dir", os.path.expanduser("~/Music/Spotify Downloads"))
            naming_tmpl = config.get("download.naming_template", "{artist} - {title}")
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
                return item.cancelled

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
                cancel_check=cancel_check
            )

            item.output_path = file_path or ""
            self._update_status(item, "Completed")
            if self.on_track_completed:
                self.on_track_completed(track_id, item.output_path)

        except Exception as e:
            logger.error(f"Failed to process track '{track.title}': {e}")
            item.error_message = str(e)
            self._update_status(item, "Failed")
            if self.on_track_failed:
                self.on_track_failed(track_id, str(e))

    def _update_status(self, item: QueueItem, status: str):
        item.status = status
        if self.on_track_status_changed:
            self.on_track_status_changed(item.track.id, status)
