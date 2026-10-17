import unittest
import tempfile
import os
from core.spotify_client import TrackMetadata
from core.queue_manager import DownloadQueueManager, QueueItem
from core.archive import ArchiveManager


class MockAudioEngine:
    def __init__(self):
        pass


class TestQueueManager(unittest.TestCase):
    def setUp(self):
        from core.config import config
        self._orig_source = config.get("source_engine", "musilon")
        self._orig_tg = config.get("telegram.enabled", False)
        self._orig_mus = config.get("musilon.enabled", True)
        config.set("source_engine", "musilon")
        config.set("telegram.enabled", False)
        config.set("musilon.enabled", True)

        self.tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp_db.close()
        ArchiveManager._instance = None
        self.archive = ArchiveManager(db_path=self.tmp_db.name)
        self.engine = MockAudioEngine()
        self.qm = DownloadQueueManager(audio_engine=self.engine, archive_manager=self.archive)

    def tearDown(self):
        self.qm.stop()
        ArchiveManager._instance = None
        if os.path.exists(self.tmp_db.name):
            try:
                os.remove(self.tmp_db.name)
            except Exception:
                pass
        from core.config import config
        config.set("source_engine", self._orig_source)
        config.set("telegram.enabled", self._orig_tg)
        config.set("musilon.enabled", self._orig_mus)

    def test_enqueue_and_get_items(self):
        tracks = [
            TrackMetadata(
                id=f"test_id_{i}",
                title=f"Test Song {i}",
                artists=["Test Artist"],
                album="Test Album",
                duration_ms=180000
            )
            for i in range(3)
        ]
        self.qm.enqueue(tracks)
        items = self.qm.get_items()
        self.assertEqual(len(items), 3)
        self.assertEqual(items[0].track.title, "Test Song 0")
        self.assertEqual(items[0].status, "Queued")

    def test_pause_and_resume(self):
        self.qm.pause()
        self.assertTrue(self.qm.is_paused())
        self.qm.resume()
        self.assertFalse(self.qm.is_paused())

    def test_clear_queue(self):
        track = TrackMetadata(
            id="test_clear",
            title="Clear Song",
            artists=["Artist"],
            album="Album"
        )
        self.qm.enqueue([track])
        self.assertEqual(len(self.qm.get_items()), 1)
        self.qm.clear_completed()
        # Item is Queued so clear_completed should not remove it
        self.assertEqual(len(self.qm.get_items()), 1)

    def test_concurrency_scaling(self):
        self.assertEqual(self.qm.max_workers, 5)
        self.qm.update_concurrency(7)
        self.assertEqual(self.qm.max_workers, 7)
        self.qm.update_concurrency(3)
        self.assertEqual(self.qm.max_workers, 3)

    def test_concurrent_worker_spawn(self):
        self.qm.start()
        self.assertEqual(len(self.qm._worker_threads), self.qm.max_workers)
        self.qm.update_concurrency(8)
        self.assertEqual(len(self.qm._worker_threads), 8)
        self.qm.stop()

    def test_opus_file_in_archive_always_ytm(self):
        # Create a dummy .opus file
        tmp_opus = tempfile.NamedTemporaryFile(suffix=".opus", delete=False)
        tmp_opus.write(b"OggS" + b"\x00" * 100)
        tmp_opus.close()
        try:
            track = TrackMetadata(id="t_opus", title="Opus Song", artists=["Artist"], album="Album")
            # Attempt to add with incorrect Musilon badge
            self.archive.add_track(track, tmp_opus.name, quality_badge="Musilon 320k", source_type="Musilon")
            row = self.archive.get_all_tracks()[0]
            self.assertEqual(row["quality_badge"], "YTM Opus")
            self.assertEqual(row["source_type"], "YouTube Music")
        finally:
            if os.path.exists(tmp_opus.name):
                os.remove(tmp_opus.name)

    def test_musilon_issue_prompts_user_on_vip_error(self):
        from core.musilon import MusilonVipError, MusilonSource
        from core.resolver import ResolvedTrackSource
        self.qm._running = True
        track = TrackMetadata(id="t_vip", title="VIP Song", artists=["Artist"], album="Album")
        resolved = ResolvedTrackSource(
            source_type="Musilon",
            quality_badge="Musilon 320k",
            source_obj=MusilonSource("id", "VIP Song", "Artist", "Musilon 320k", "http://dl", "ogg"),
            file_extension="ogg"
        )
        self.engine.resolve_source = lambda trk, **kw: resolved
        def raise_vip(**kw):
            raise MusilonVipError("HTTP 401 Session Expired")
        self.engine.download_and_tag = raise_vip

        prompt_called = []
        def on_limit(trk, itm, rsn, cb):
            prompt_called.append((trk.title, rsn))
            cb("stop")

        self.qm.on_musilon_limit_reached = on_limit
        item = QueueItem(track=track)
        self.qm._process_item(item)

        self.assertEqual(len(prompt_called), 1)
        self.assertEqual(prompt_called[0][0], "VIP Song")
        self.assertIn("VIP", prompt_called[0][1])
        self.assertEqual(item.status, "Stopped")


if __name__ == "__main__":
    unittest.main()

