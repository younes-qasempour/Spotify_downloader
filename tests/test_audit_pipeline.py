import os
import asyncio
import tempfile
import threading
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, PropertyMock, patch

from core.queue_manager import DownloadQueueManager, QueueItem
from core.reliability_store import ReliabilityStore
from core.resolver import CascadingAudioEngine, ResolvedTrackSource
from core.spotify_client import TrackMetadata
from core.utils import is_valid_audio_file, sanitize_filename


class TestQueueAudit(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = ReliabilityStore(Path(self.temp.name) / "queue.sqlite3")
        self.enterContext(patch("core.queue_manager.ReliabilityStore", return_value=self.store))
        self.values = {
            "download.output_dir": self.temp.name,
            "download.normalize_volume": False,
            "source_engine": "musilon",
            "telegram.enabled": False,
            "musilon.enabled": True,
        }
        cfg = self.enterContext(patch("core.queue_manager.config"))
        cfg.get.side_effect = lambda key, default=None: self.values.get(key, default)
        self.engine = MagicMock()
        self.archive = MagicMock()
        self.archive.find_track.return_value = None
        self.qm = DownloadQueueManager(self.engine, self.archive, 1)
        self.addCleanup(self.stop_workers)
        self.track = TrackMetadata(id="audit", title="Song", artists=["Artist"], album="Album")
        self.engine.resolve_source.return_value = ResolvedTrackSource(
            "YouTube", "YouTube Opus", SimpleNamespace(title="Different Song", artist="Artist"), "opus")

    def stop_workers(self):
        self.qm.stop()
        for worker in self.qm._worker_threads:
            worker.join(timeout=2)

    def test_missing_output_is_not_completed(self):
        self.qm._running = True
        self.engine.download_and_tag.return_value = None
        item = QueueItem(self.track)
        self.qm.on_track_completed = MagicMock()
        self.qm.on_source_review_required = MagicMock(side_effect=lambda trk, summary, decide: decide(True))
        self.qm._process_item(item)
        self.qm.on_source_review_required.assert_called_once()
        self.engine.download_and_tag.assert_called_once()
        self.assertEqual(item.status, "Failed")
        self.assertIn("did not produce", item.error_message)
        self.qm.on_track_completed.assert_not_called()
        self.archive.mark_saved_track_downloaded.assert_not_called()

    def test_stop_cancels_all_processing_states(self):
        for state in ("Downloading (YTM)", "Tagging Metadata", "Fetching Lyrics", "Balancing Volume", "VIP Cooldown (5s)"):
            with self.subTest(state=state):
                item = QueueItem(self.track, status=state)
                self.qm._items = {self.track.id: item}
                self.qm._running = True
                self.qm.stop()
                self.assertTrue(item.cancelled)
                self.assertEqual(item.status, "Stopped")

    def test_cancelling_a_paused_item_releases_its_worker(self):
        item = QueueItem(self.track, status="Paused")
        self.qm._items[self.track.id] = item
        self.qm._running = True
        self.qm.pause()
        worker = threading.Thread(target=self.qm._process_item, args=(item,), daemon=True)
        worker.start()
        try:
            self.qm.cancel_track(self.track.id)
            worker.join(timeout=0.75)
            self.assertFalse(worker.is_alive())
            self.assertEqual(item.status, "Cancelled")
        finally:
            self.qm.stop()
            worker.join(timeout=2)

    def test_retry_does_not_reactivate_an_inflight_cancelled_item(self):
        entered = threading.Event()
        release = threading.Event()

        def processing(item):
            entered.set()
            release.wait(timeout=3)

        self.qm._process_item = processing
        self.qm.enqueue([self.track])
        self.qm.start()
        try:
            self.assertTrue(entered.wait(timeout=2))
            self.qm.cancel_track(self.track.id)
            self.assertFalse(self.qm.retry_track(self.track.id))
            self.assertTrue(self.qm.get_items()[0].cancelled)
            self.assertEqual(self.qm.start_all(), 0)
        finally:
            release.set()

    def test_resolution_error_does_not_escape_fallback_handler(self):
        from core.melobot import MeloBotError

        self.qm._running = True
        self.engine.resolve_source.side_effect = MeloBotError("Provider unavailable")
        self.engine.ytdlp.resolve_track.return_value = None
        item = QueueItem(self.track)
        self.qm.on_track_failed = MagicMock()
        self.qm._process_item(item)
        self.assertEqual(item.status, "Failed")
        self.assertIn("fallback", item.error_message.lower())
        self.qm.on_track_failed.assert_called_once_with(self.track.id, item.error_message)

    def test_failed_archive_copy_preserves_existing_destination(self):
        self.values["download.save_in_subfolders"] = True
        self.track.collection_type = "playlist"
        self.track.collection_name = "Mix"
        source = Path(self.temp.name) / "original.opus"
        source.write_bytes(b"original music")
        destination = Path(self.temp.name) / "Mix" / "Artist - Song.opus"
        destination.parent.mkdir()
        destination.write_bytes(b"other music")
        self.archive.find_track.return_value = {"file_path": str(source)}
        self.engine.download_and_tag.return_value = None
        self.qm._running = True
        self.qm.on_source_review_required = MagicMock(side_effect=lambda trk, summary, decide: decide(True))
        item = QueueItem(self.track)

        def interrupted_copy(src, dest):
            Path(dest).write_bytes(b"partial copy")
            raise OSError("disk full")

        with patch("core.queue_manager.is_valid_audio_file", return_value=(True, "")), \
                patch("core.queue_manager.shutil.copy2", side_effect=interrupted_copy) as copy:
            self.qm._process_item(item)
        copy.assert_called_once()
        self.qm.on_source_review_required.assert_called_once()
        self.engine.download_and_tag.assert_called_once()
        self.assertEqual(item.status, "Failed")
        self.assertEqual(destination.read_bytes(), b"other music")
        self.assertEqual(list(destination.parent.iterdir()), [destination])

    def test_shutdown_closes_providers_only_after_workers_exit(self):
        entered = threading.Event()
        cleaned = threading.Event()

        def processing(item):
            entered.set()
            while not item.cancelled:
                cleaned.wait(timeout=0.01)
            cleaned.set()

        self.qm._process_item = processing
        self.engine.close.side_effect = lambda: self.assertTrue(cleaned.is_set())
        self.qm.enqueue([self.track])
        self.qm.start()
        self.assertTrue(entered.wait(timeout=2))
        self.qm.shutdown()
        self.qm.shutdown()
        self.engine.close.assert_called_once()
        self.assertTrue(all(not worker.is_alive() for worker in self.qm._worker_threads))

    def test_stale_completed_queue_entry_is_not_processed_again(self):
        processed = []

        def processing(item):
            processed.append(item.track.id)
            item.status = "Completed"

        self.qm._process_item = processing
        self.qm.enqueue([self.track])
        self.qm._queue.put(self.qm.get_items()[0])
        self.qm.start()
        self.qm._queue.join()
        self.assertEqual(processed, [self.track.id])


class TestResolverAudit(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name)
        self.values = {
            "download.normalize_volume": False,
            "download.target_format": "original",
            "download.save_in_subfolders": False,
            "download.lyrics_mode": "same_folder",
        }
        cfg = self.enterContext(patch("core.resolver.config"))
        cfg.get.side_effect = lambda key, default=None: self.values.get(key, default)
        self.enterContext(patch("core.output_preview.config", cfg))
        self.engine = CascadingAudioEngine(*(MagicMock() for _ in range(5)))
        self.engine.lyrics.fetch_lyrics.return_value = None
        self.engine.tagger.tag_file.return_value = True
        self.enterContext(patch("core.resolver.is_valid_audio_file", return_value=(True, "")))
        self.track = TrackMetadata(id="audit", title="Song", artists=["Artist"], album="Album")
        self.resolved = ResolvedTrackSource("YouTube", "YouTube Opus", MagicMock(), "opus")

    def download(self, **kwargs):
        return self.engine.download_and_tag(self.track, self.resolved, str(self.output), embed_art=False, **kwargs)

    def test_failed_download_preserves_existing_destination(self):
        existing = self.output / "Artist - Song.opus"
        existing.write_bytes(b"existing music")

        def fail(**kwargs):
            Path(kwargs["output_template_without_ext"] + ".opus").write_bytes(b"partial")
            raise OSError("network interrupted")

        self.engine.ytdlp.download_track.side_effect = fail
        with self.assertRaises(OSError):
            self.download()
        self.assertEqual(existing.read_bytes(), b"existing music")
        self.assertEqual(list(self.output.iterdir()), [existing])

    def test_cancelled_tagging_leaves_no_audio_or_lyrics(self):
        cancelled = threading.Event()

        def transfer(**kwargs):
            dest = Path(kwargs["output_template_without_ext"] + ".opus")
            dest.write_bytes(b"audio")
            dest.with_suffix(".lrc").write_text("[00:01]lyrics", encoding="utf-8")
            return str(dest)

        self.engine.ytdlp.download_track.side_effect = transfer
        self.engine.tagger.tag_file.side_effect = lambda **kw: cancelled.set() or True
        self.assertIsNone(self.download(cancel_check=cancelled.is_set))
        self.assertEqual(list(self.output.iterdir()), [])

    def test_collection_folder_cannot_escape_output(self):
        self.values["download.save_in_subfolders"] = True
        self.enterContext(patch.object(TrackMetadata, "target_folder", new_callable=PropertyMock, return_value="..\\outside"))

        def transfer(**kwargs):
            dest = Path(kwargs["output_template_without_ext"] + ".wav")
            self.assertTrue(dest.resolve().is_relative_to(self.output.resolve()))
            with wave.open(str(dest), "wb") as audio:
                audio.setparams((1, 2, 44100, 0, "NONE", "not compressed"))
                audio.writeframes(b"\x00\x01" * 100000)
            return str(dest)

        self.engine.ytdlp.download_track.side_effect = transfer
        with patch("core.resolver.is_valid_audio_file", wraps=is_valid_audio_file):
            output = Path(self.download())
        self.assertTrue(output.is_file())
        self.assertTrue(output.resolve().is_relative_to(self.output.resolve()))
        self.assertEqual(output.parent, self.output / sanitize_filename("..\\outside"))
        self.assertEqual(is_valid_audio_file(str(output)), (True, "wav"))

    def test_tagging_failure_is_not_reported_as_success(self):
        def transfer(**kwargs):
            dest = Path(kwargs["output_template_without_ext"] + ".opus")
            dest.write_bytes(b"audio")
            return str(dest)

        self.engine.ytdlp.download_track.side_effect = transfer
        self.engine.tagger.tag_file.return_value = False
        with self.assertRaisesRegex(Exception, "[Tt]ag"):
            self.download()
        self.assertEqual(list(self.output.iterdir()), [])

    def test_processing_cancellation_cleans_staged_files(self):
        from core.utils import AudioProcessingCancelled

        for step in ("remux", "transcode", "normalize"):
            with self.subTest(step=step):
                cancelled = threading.Event()
                self.values["download.target_format"] = "mp3" if step == "transcode" else "original"
                self.values["download.normalize_volume"] = step == "normalize"

                def transfer(**kwargs):
                    extension = ".webm" if step == "remux" else ".opus"
                    dest = Path(kwargs["output_template_without_ext"] + extension)
                    dest.write_bytes(b"audio")
                    return str(dest)

                def cancel(*args, **kwargs):
                    self.assertIsNotNone(kwargs.get("cancel_check"))
                    cancelled.set()
                    raise AudioProcessingCancelled("cancelled")

                self.engine.ytdlp.download_track.side_effect = transfer
                target = {
                    "remux": "core.resolver.run_ffmpeg",
                    "transcode": "core.resolver.transcode_audio",
                    "normalize": "core.utils.normalize_audio_loudness",
                }[step]
                with patch(target, side_effect=cancel) as processing, \
                        patch("core.utils.ensure_ffmpeg", return_value="ffmpeg"):
                    self.assertIsNone(self.download(cancel_check=cancelled.is_set))
                    processing.assert_called_once()
                self.assertEqual(list(self.output.iterdir()), [])


class TestSpotifyLifecycleAudit(unittest.TestCase):
    def test_close_releases_each_owned_session_once(self):
        from core.spotify_client import SpotifyClient

        client = SpotifyClient.__new__(SpotifyClient)
        client._session = MagicMock()
        shared_session = MagicMock()
        client._sp = MagicMock(_session=shared_session)
        client._oauth = MagicMock(_session=shared_session)
        client.close()
        client._session.close.assert_called_once()
        shared_session.close.assert_called_once()


class TestTelegramLifecycleAudit(unittest.TestCase):
    def make_engine(self):
        from core.melobot import MeloBotEngine

        engine = MeloBotEngine(api_id=123, api_hash="test-only")

        def cleanup():
            if hasattr(engine, "close"):
                engine.close()
            elif not engine._loop.is_closed():
                engine._loop.call_soon_threadsafe(engine._loop.stop)
                engine._loop_thread.join(timeout=2)
                engine._loop.close()

        self.addCleanup(cleanup)
        return engine

    def test_close_stops_and_closes_event_loop_without_logging_out(self):
        from unittest.mock import AsyncMock

        engine = self.make_engine()
        engine._client = MagicMock()
        engine._client.disconnect = AsyncMock()
        engine.close()
        self.assertFalse(engine._loop_thread.is_alive())
        self.assertTrue(engine._loop.is_closed())
        engine._client.disconnect.assert_awaited_once()
        engine._client.log_out.assert_not_called()

    def test_timeout_waits_for_coroutine_file_cleanup(self):
        engine = self.make_engine()
        cleaned = threading.Event()

        async def pending_download():
            try:
                await asyncio.sleep(100)
            finally:
                await asyncio.sleep(0.02)
                cleaned.set()

        with self.assertRaises(TimeoutError):
            engine._run_async(pending_download(), timeout=0.01)
        self.assertTrue(cleaned.is_set())


if __name__ == "__main__":
    unittest.main()