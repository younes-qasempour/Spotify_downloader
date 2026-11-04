import unittest
import os
import json
import tempfile
import shutil
from unittest.mock import MagicMock, patch

from core.queue_manager import DownloadQueueManager, QueueItem
from core.archive import ArchiveManager
from core.spotify_client import TrackMetadata
from gui.web_api import FlacifyWebRequestHandler, WebBackendState


class DummyWFile:
    def __init__(self):
        self.data = bytearray()

    def write(self, b):
        self.data.extend(b)


class TestDownloaderSavedConsistency(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "test_archive.db")
        self.archive = ArchiveManager(self.db_path)
        self.qm = DownloadQueueManager(archive_manager=self.archive)
        self.qm.start_workers = MagicMock()
        self.file_picker_mock = MagicMock(return_value="C:/Music/Covers/album.png")

        self.state = WebBackendState(
            queue_manager=self.qm,
            archive_manager=self.archive,
            file_picker_cb=self.file_picker_mock,
        )

    def tearDown(self):
        self.qm.stop()
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _call_post(self, path, body):
        handler = object.__new__(FlacifyWebRequestHandler)
        handler.state = self.state
        handler.web_root = os.path.abspath("gui/web_ui")
        handler.path = path
        handler.command = "POST"
        handler.headers = {"Host": "127.0.0.1"}
        handler.wfile = DummyWFile()

        def send_response(code, message=None):
            handler.status_code = code

        def send_header(keyword, value):
            pass

        def end_headers():
            pass

        handler.send_response = send_response
        handler.send_header = send_header
        handler.end_headers = end_headers

        if path == "/api/dialog/file":
            handler._handle_file_dialog(body)
        elif path == "/api/saved_playlists/action":
            handler._handle_saved_playlists_action(body)
        elif path == "/api/queue/action":
            handler._handle_queue_action(body)
        elif path == "/api/queue/add":
            handler._handle_queue_add(body)

        raw = bytes(handler.wfile.data)
        if b"\r\n\r\n" in raw:
            raw_body = raw.split(b"\r\n\r\n", 1)[1]
        else:
            raw_body = raw
        return json.loads(raw_body.decode("utf-8"))

    def test_queue_manager_clear_all_resets_archive(self):
        pid = "test_pl_1"
        tm1 = TrackMetadata(id="sp_1", title="Track 1", artists=["Artist 1"], album="Album 1", duration_ms=180000)
        tm2 = TrackMetadata(id="sp_2", title="Track 2", artists=["Artist 2"], album="Album 2", duration_ms=200000)
        tracks = [tm1, tm2]

        self.archive.save_playlist(name="Test Playlist", spotify_url="https://open.spotify.com/playlist/test", cover_url="", tracks=tracks, playlist_id=pid)
        self.archive.mark_saved_tracks_queued(pid, ["sp_1", "sp_2"])

        item1 = QueueItem(track=tm1, status="Queued")
        item2 = QueueItem(track=tm2, status="Downloading")
        self.qm._items = {"sp_1": item1, "sp_2": item2}

        self.qm.clear_all()
        self.assertEqual(len(self.qm.get_items()), 0)

        updated_tracks = self.archive.get_saved_playlist_tracks(pid)
        for t in updated_tracks:
            self.assertEqual(t["status"], "pending", f"Expected track {t['spotify_id']} status to be pending, got {t['status']}")

    def test_remove_track_resets_archive_to_pending(self):
        pid = "test_pl_2"
        tm = TrackMetadata(id="sp_active", title="Active Track", artists=["Artist"], album="Album", duration_ms=180000)
        self.archive.save_playlist(name="Test Playlist 2", spotify_url="https://open.spotify.com/playlist/test2", cover_url="", tracks=[tm], playlist_id=pid)
        self.archive.mark_saved_tracks_queued(pid, ["sp_active"])

        item = QueueItem(track=tm, status="Downloading")
        self.qm._items = {"sp_active": item}

        self.qm.remove_track("sp_active")
        self.assertEqual(len(self.qm.get_items()), 0)

        updated_tracks = self.archive.get_saved_playlist_tracks(pid)
        self.assertEqual(updated_tracks[0]["status"], "pending")

    def test_remove_completed_track_leaves_archive_untouched(self):
        pid = "test_pl_3"
        tm = TrackMetadata(id="sp_done", title="Done Track", artists=["Artist"], album="Album", duration_ms=180000)
        self.archive.save_playlist(name="Test Playlist 3", spotify_url="https://open.spotify.com/playlist/test3", cover_url="", tracks=[tm], playlist_id=pid)
        self.archive.mark_saved_track_downloaded(spotify_id="sp_done", file_path="C:/music/done.mp3", quality_badge="320K")

        item = QueueItem(track=tm, status="Completed")
        self.qm._items = {"sp_done": item}

        self.qm.remove_track("sp_done")
        self.assertEqual(len(self.qm.get_items()), 0)

        updated_tracks = self.archive.get_saved_playlist_tracks(pid)
        self.assertEqual(updated_tracks[0]["status"], "downloaded")
        self.assertEqual(os.path.normpath(updated_tracks[0]["file_path"]), os.path.normpath("C:/music/done.mp3"))

    def test_web_api_file_dialog_endpoint(self):
        data = self._call_post("/api/dialog/file", {
            "title": "Select Artwork",
            "filter": "Images (*.png *.jpg)"
        })

        self.assertTrue(data.get("ok"))
        self.assertEqual(data.get("path"), "C:/Music/Covers/album.png")
        self.file_picker_mock.assert_called_once_with("Select Artwork", "Images (*.png *.jpg)")

    def test_saved_playlist_cancel_track(self):
        pid = "test_cancel_pl"
        tm = TrackMetadata(id="sp_cancelling", title="Cancelling Track", artists=["Artist"], album="Album", duration_ms=180000)
        self.archive.save_playlist(name="Cancel Pl", spotify_url="https://open.spotify.com/playlist/cancel", cover_url="", tracks=[tm], playlist_id=pid)
        self.archive.mark_saved_tracks_queued(pid, ["sp_cancelling"])

        data = self._call_post("/api/saved_playlists/action", {
            "action": "cancel_track",
            "playlist_id": pid,
            "spotify_id": "sp_cancelling"
        })

        self.assertTrue(data.get("ok"))
        saved_tracks = self.archive.get_saved_playlist_tracks(pid)
        self.assertEqual(saved_tracks[0]["status"], "pending")

    def test_web_api_queue_action_clear_all(self):
        tm = TrackMetadata(id="sp_1", title="Track 1", artists=["Artist 1"], album="Album 1")
        item1 = QueueItem(track=tm, status="Queued")
        self.qm._items = {"sp_1": item1}

        data = self._call_post("/api/queue/action", {"action": "clear_all"})
        self.assertTrue(data.get("ok"))
        self.assertEqual(len(self.qm.get_items()), 0)


if __name__ == "__main__":
    unittest.main()
