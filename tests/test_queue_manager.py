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


if __name__ == "__main__":
    unittest.main()
