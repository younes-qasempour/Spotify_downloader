import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from core.queue_manager import DownloadQueueManager, QueueItem
from core.reliability_store import ReliabilityStore
from core.resolver import CascadingAudioEngine, ResolvedTrackSource
from core.spotify_client import TrackMetadata
from core import staging_recovery


class FinalQueueIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = ReliabilityStore(self.root / "queue.sqlite3")
        self.enterContext(patch("core.queue_manager.ReliabilityStore", return_value=self.store))
        self.values = {"download.output_dir": self.temp.name, "musilon.safe_mode": False}
        cfg = self.enterContext(patch("core.queue_manager.config"))
        cfg.get.side_effect = lambda key, default=None: self.values.get(key, default)
        self.engine = MagicMock()
        self.engine._publish_lock = threading.Lock()
        self.archive = MagicMock()
        self.archive.find_track.return_value = None
        self.archive.add_track.return_value = True
        self.manager = DownloadQueueManager(self.engine, self.archive, 1)
        self.manager._running = True
        self.track = TrackMetadata(id="test-track", title="Song", artists=["Artist"], album="Album")
        self.manager.enqueue([self.track])
        self.item = self.manager.get_items()[0]

    def test_bulk_removal_is_persisted(self):
        self.manager.remove_tracks([self.track.id])
        self.assertEqual(self.store.load_queue(), [])

    def test_recovered_jobs_require_explicit_retry(self):
        second = TrackMetadata(id="second", title="Second", artists=["Artist"], album="Album")
        fresh = TrackMetadata(id="fresh", title="Fresh", artists=["Artist"], album="Album")
        self.manager.enqueue([second])
        recovered = DownloadQueueManager(self.engine, self.archive, 1)
        self.assertEqual({item.status for item in recovered.get_items()}, {"Stopped"})
        with patch.object(recovered, "get_effective_concurrency", return_value=0):
            recovered.enqueue([self.track, fresh])
            recovered.start_all()
            items = {item.track.id: item for item in recovered.get_items()}
            self.assertEqual(items[self.track.id].status, "Stopped")
            self.assertEqual(items[second.id].status, "Stopped")
            self.assertEqual(items[fresh.id].status, "Queued")
            self.assertEqual([item.track.id for item in recovered._queue.queue], [fresh.id])
            self.assertTrue(recovered.retry_track(self.track.id))
            self.assertEqual(items[second.id].status, "Stopped")
            self.assertEqual({item.track.id for item in recovered._queue.queue}, {fresh.id, self.track.id})
            self.assertEqual(recovered.retry_failed(), 1)
            self.assertEqual({item.track.id for item in recovered._queue.queue}, {fresh.id, self.track.id, second.id})

    def test_uncertain_match_without_review_callback_is_not_approved(self):
        resolved = ResolvedTrackSource("YouTube", "Opus", SimpleNamespace(title="Different Live"), "opus")
        self.assertFalse(self.manager._review_source(self.item, resolved, lambda: False))
        self.assertIn("approval", self.item.error_message.lower())

    def test_completion_waits_for_archive_even_if_engine_sends_completed(self):
        output = self.root / "audio.opus"
        output.write_bytes(b"audio")
        self.engine.resolve_source.return_value = ResolvedTrackSource(
            "YouTube", "Opus", SimpleNamespace(title="Song", artist="Artist"), "opus")
        self.values["download.review_uncertain_matches"] = False
        statuses = []
        self.manager.on_track_status_changed = lambda tid, status: statuses.append(status)

        def download(**kwargs):
            kwargs["status_callback"]("Completed")
            self.assertNotIn("Completed", statuses)
            self.assertEqual(len(self.store.load_queue()), 1)
            return str(output)

        def register(*args, **kwargs):
            self.assertNotIn("Completed", statuses)
            self.assertEqual(len(self.store.load_queue()), 1)
            return True

        self.engine.download_and_tag.side_effect = download
        self.archive.add_track.side_effect = register
        self.manager._process_item(self.item)
        self.assertEqual(self.item.status, "Completed")
        self.assertEqual(self.store.load_queue(), [])

    def test_archive_registration_failure_keeps_job_recoverable(self):
        output = self.root / "audio.opus"
        output.write_bytes(b"audio")
        self.engine.resolve_source.return_value = ResolvedTrackSource(
            "YouTube", "Opus", SimpleNamespace(title="Song", artist="Artist"), "opus")
        self.values["download.review_uncertain_matches"] = False
        self.engine.download_and_tag.return_value = str(output)
        self.archive.add_track.return_value = False
        self.manager.on_track_completed = MagicMock()
        self.manager._process_item(self.item)
        self.assertEqual(self.item.status, "Failed")
        self.assertEqual(len(self.store.load_queue()), 1)
        self.manager.on_track_completed.assert_not_called()

    def test_cancel_during_archive_lookup_never_completes(self):
        output = self.root / "archived.opus"
        output.write_bytes(b"audio")
        def find_track(**kwargs):
            self.manager.cancel_track(self.track.id)
            return {"file_path": str(output), "quality_badge": "Opus", "source_type": "Local"}
        self.archive.find_track.side_effect = find_track
        self.manager.on_track_completed = MagicMock()
        with patch("core.queue_manager.is_valid_audio_file", return_value=(True, "ok")):
            self.manager._process_item(self.item)
        self.assertEqual(self.item.status, "Cancelled")
        self.manager.on_track_completed.assert_not_called()
        self.archive.mark_saved_track_downloaded.assert_not_called()

    def test_archive_copy_revalidates_after_album_tagging(self):
        source = self.root / "original.opus"
        source.write_bytes(b"original")
        destination = self.root / "copy.opus"
        self.track.collection_type = "album"
        self.track.track_number = 1

        def corrupt(**kwargs):
            Path(kwargs["file_path"]).write_bytes(b"corrupt")
            return True

        self.engine.tagger.tag_file.side_effect = corrupt
        with patch("core.queue_manager.is_valid_audio_file", return_value=(False, "corrupt")):
            with self.assertRaisesRegex(Exception, "corrupt"):
                self.manager._copy_archived_track(str(source), str(destination), self.track, lambda: False)
        self.assertFalse(destination.exists())
        self.assertEqual(source.read_bytes(), b"original")

    def test_cancel_during_archive_tagging_never_publishes_copy(self):
        source = self.root / "original.opus"
        source.write_bytes(b"original")
        destination = self.root / "copy.opus"
        self.track.collection_type = "album"
        self.track.track_number = 1
        self.engine.tagger.tag_file.side_effect = lambda **kwargs: self.manager.cancel_track(self.track.id) or True
        with patch("core.queue_manager.is_valid_audio_file", return_value=(True, "ok")):
            result = self.manager._copy_archived_track(
                str(source), str(destination), self.track, lambda: self.item.cancelled
            )
        self.assertIsNone(result)
        self.assertFalse(destination.exists())
        self.assertEqual(source.read_bytes(), b"original")
        self.assertEqual(self.item.status, "Cancelled")

    def test_manual_recovery_registers_before_completing_queue_entry(self):
        output = self.root / "recovered.opus"
        output.write_bytes(b"audio")
        self.archive.infer_badge_from_file.return_value = ("Opus", None)
        def register(*args, **kwargs):
            self.assertNotEqual(self.item.status, "Completed")
            self.assertEqual(len(self.store.load_queue()), 1)
            return True
        self.archive.add_track.side_effect = register
        with patch("core.queue_manager.is_valid_audio_file", return_value=(True, "ok")):
            self.assertTrue(self.manager.complete_recovered_track(self.track.id, str(output)))
        self.assertEqual(self.item.status, "Completed")
        self.assertEqual(self.store.load_queue(), [])
        self.archive.mark_saved_track_downloaded.assert_called_once()


class FinalPublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.track = TrackMetadata(id="test-track", title="Song", artists=["Artist"], album="Album")
        self.resolved = ResolvedTrackSource("YouTube", "Opus", None, "opus")
        self.enterContext(patch("core.resolver.is_valid_audio_file", return_value=(True, "ok")))
        self.enterContext(patch("core.staging_recovery.utils.is_valid_audio_file", return_value=(True, "ok")))

    def engine(self, audio=b"audio", lyrics=None, lyrics_location="nested"):
        engine = object.__new__(CascadingAudioEngine)
        engine._publish_lock = threading.Lock()
        def stage(track, resolved, directory, *args):
            path = Path(directory) / "Song.opus"
            path.write_bytes(audio)
            if lyrics is not None:
                lyrics_dir = path.parent / "lyrics" if lyrics_location == "nested" else path.parent
                lyrics_dir.mkdir(exist_ok=True)
                (lyrics_dir / "Song.lrc").write_bytes(lyrics)
            return str(path)
        engine._download_and_tag = stage
        return engine

    def test_publication_callbacks_do_not_hold_publication_lock(self):
        engine = self.engine()
        seen = []
        def status(value):
            if value == "Publishing output":
                acquired = engine._publish_lock.acquire(blocking=False)
                seen.append(acquired)
                if acquired:
                    engine._publish_lock.release()
        engine.download_and_tag(self.track, self.resolved, str(self.root), status_callback=status)
        self.assertEqual(seen, [True])

    def test_cancel_while_waiting_for_publication_does_not_publish(self):
        engine = self.engine()
        publishing = threading.Event()
        cancelled = threading.Event()
        results, errors = [], []

        def run():
            try:
                results.append(engine.download_and_tag(
                    self.track, self.resolved, str(self.root), cancel_check=cancelled.is_set,
                    status_callback=lambda status: publishing.set() if status == "Publishing output" else None,
                ))
            except Exception as exc:
                errors.append(exc)

        with engine._publish_lock:
            thread = threading.Thread(target=run, daemon=True)
            thread.start()
            try:
                self.assertTrue(publishing.wait(3))
                cancelled.set()
            finally:
                cancelled.set()
        thread.join(timeout=5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(results, [None])
        self.assertEqual(list(self.root.iterdir()), [])

    def test_existing_lyrics_are_not_overwritten(self):
        (self.root / "lyrics").mkdir()
        (self.root / "lyrics" / "Song.lrc").write_bytes(b"existing")
        result = self.engine(lyrics=b"new").download_and_tag(self.track, self.resolved, str(self.root))
        self.assertEqual((self.root / "lyrics" / "Song.lrc").read_bytes(), b"existing")
        self.assertEqual(Path(result).stem, "Song (1)")
        self.assertEqual((self.root / "lyrics" / "Song (1).lrc").read_bytes(), b"new")
        self.assertEqual(staging_recovery.scan_abandoned_staging(self.root), [])

    def test_same_folder_lyrics_stay_next_to_published_audio(self):
        with patch("core.resolver.config.get", side_effect=lambda key, default=None:
                   "same_folder" if key == "download.lyrics_mode" else default):
            result = self.engine(lyrics=b"lyrics", lyrics_location="adjacent").download_and_tag(
                self.track, self.resolved, str(self.root)
            )
        self.assertEqual(Path(result).with_suffix(".lrc").read_bytes(), b"lyrics")

    def test_independent_publishers_cannot_overwrite_each_other(self):
        barrier = threading.Barrier(2)
        original = staging_recovery._publish_ready
        def simultaneous_publication(path, owner):
            barrier.wait(timeout=3)
            return original(path, owner)
        outputs, errors = [], []
        def publish(audio):
            try:
                outputs.append(self.engine(audio).download_and_tag(self.track, self.resolved, str(self.root)))
            except Exception as exc:
                errors.append(exc)
        with patch("core.staging_recovery._publish_ready", side_effect=simultaneous_publication):
            threads = [threading.Thread(target=publish, args=(value,)) for value in (b"one", b"two")]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=5)
        self.assertFalse(errors)
        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(len(set(outputs)), 2)
        self.assertEqual({Path(path).read_bytes() for path in outputs}, {b"one", b"two"})

    def test_partial_publication_preserves_ready_stage_for_explicit_recovery(self):
        original = staging_recovery._publish
        def fail_lyrics(source, destination, expected):
            if destination.suffix == ".lrc":
                raise OSError("lyrics publication interrupted")
            return original(source, destination, expected)

        with patch("core.staging_recovery._publish", side_effect=fail_lyrics):
            with self.assertRaisesRegex(OSError, "interrupted"):
                self.engine(lyrics=b"new").download_and_tag(self.track, self.resolved, str(self.root))
        stages = staging_recovery.scan_abandoned_staging(self.root)
        self.assertEqual(len(stages), 1)
        self.assertEqual(stages[0]["state"], "ready")
        self.assertTrue(stages[0]["publication_interrupted"])
        self.assertEqual((self.root / "Song.opus").read_bytes(), b"audio")
        result = Path(staging_recovery.recover_staging(stages[0]["directory"]))
        self.assertEqual(result.name, "Song (1).opus")
        self.assertEqual(result.read_bytes(), b"audio")
        self.assertEqual((self.root / "lyrics" / "Song (1).lrc").read_bytes(), b"new")
        self.assertEqual(staging_recovery.scan_abandoned_staging(self.root), [])

    def test_process_crash_during_normal_publication_leaves_recoverable_stage(self):
        script = """
import os, sys, threading
from pathlib import Path
from core import resolver, staging_recovery
from core.spotify_client import TrackMetadata
resolver.is_valid_audio_file = lambda path: (True, 'ok')
staging_recovery.utils.is_valid_audio_file = lambda path: (True, 'ok')
engine = object.__new__(resolver.CascadingAudioEngine)
engine._publish_lock = threading.Lock()
def stage(track, source, directory, *args):
    audio = Path(directory) / 'Song.opus'
    audio.write_bytes(b'audio')
    (audio.parent / 'lyrics').mkdir()
    (audio.parent / 'lyrics' / 'Song.lrc').write_bytes(b'lyrics')
    return str(audio)
engine._download_and_tag = stage
link = os.link
def crash(source, destination):
    link(source, destination)
    os._exit(42)
staging_recovery.os.link = crash
track = TrackMetadata(id='test-track', title='Song', artists=['Artist'], album='Album')
engine.download_and_tag(track, resolver.ResolvedTrackSource('YouTube', 'Opus', None, 'opus'), sys.argv[1])
"""
        process = subprocess.run([sys.executable, "-B", "-c", script, str(self.root)],
                                 cwd=Path(__file__).resolve().parents[1], capture_output=True, timeout=30)
        self.assertEqual(process.returncode, 42, process.stderr)
        stages = staging_recovery.scan_abandoned_staging(self.root)
        self.assertEqual(len(stages), 1)
        self.assertEqual(stages[0]["state"], "ready")
        self.assertTrue(stages[0]["publication_interrupted"])
        self.assertEqual((self.root / "Song.opus").read_bytes(), b"audio")
        result = Path(staging_recovery.recover_staging(stages[0]["directory"]))
        self.assertEqual(result.read_bytes(), b"audio")
        self.assertEqual((self.root / "lyrics" / (result.stem + ".lrc")).read_bytes(), b"lyrics")


if __name__ == "__main__":
    unittest.main()