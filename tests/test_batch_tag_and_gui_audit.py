import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock
import typing

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtWidgets import QApplication

from core.archive import ArchiveManager
from core.spotify_client import TrackMetadata
from core.tagger import AudioTagger
from gui.dialogs.library_repair_dialog import LibraryRepairDialog
from gui.main_window import MainWindow
from gui.queue_delegate import ThumbnailCache, TrackCardDelegate
from gui.web_api import FlacifyWebRequestHandler, WebBackendState


class TestBatchTagAndGuiAudit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([""])

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp_dir, "test_archive.db")
        self.archive = ArchiveManager(self.db_path)
        self.qm = MagicMock()
        self.state = WebBackendState(self.qm, self.archive)

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_main_window_type_hints_valid(self):
        """Verify MainWindow.play_audio_track type annotations do not throw NameError."""
        hints = typing.get_type_hints(MainWindow.play_audio_track)
        self.assertIn("file_path", hints)
        self.assertIn("track", hints)
        self.assertIn("quality_badge", hints)
        self.assertIn("playlist", hints)
        self.assertIn("index", hints)

    def test_queue_delegate_type_hints_valid(self):
        """Verify ThumbnailCache._on_internal_loaded type annotations evaluate without NameError."""
        hints = typing.get_type_hints(ThumbnailCache._on_internal_loaded)
        self.assertIn("key", hints)
        self.assertIn("img", hints)

    def test_batch_tag_handler_state_archive_reference(self):
        """Verify _handle_batch_tag accesses self.state.archive and does not crash on self.archive."""
        handler = object.__new__(FlacifyWebRequestHandler)
        handler.state = self.state
        handler._send_json_called = None

        def mock_send_json(data, status=200):
            handler._send_json_called = (data, status)
            return data

        handler._send_json = mock_send_json

        # 1. Test empty tracks list
        handler._handle_batch_tag({"action": "set_artist", "file_paths": []})
        self.assertIsNotNone(handler._send_json_called)
        self.assertFalse(handler._send_json_called[0]["ok"])
        self.assertEqual(handler._send_json_called[1], 400)

        # 2. Test empty new artist
        handler._handle_batch_tag({"action": "set_artist", "file_paths": ["fake.mp3"], "new_artist": ""})
        self.assertFalse(handler._send_json_called[0]["ok"])
        self.assertEqual(handler._send_json_called[1], 400)

        # 3. Test set_artist with real track file
        audio_path = os.path.join(self.tmp_dir, "test_song.mp3")
        with open(audio_path, "wb") as f:
            f.write(b"dummy audio content")

        meta = TrackMetadata(id="test_id", title="Test Title", artists=["Old Artist"], album="Test Album")
        added = self.archive.add_track(meta, audio_path, "320k", "youtube")
        self.assertTrue(added)

        handler._handle_batch_tag({
            "action": "set_artist",
            "file_paths": [audio_path],
            "new_artist": "New Artist Name"
        })
        self.assertIsNotNone(handler._send_json_called)
        res, status = handler._send_json_called
        self.assertTrue(res["ok"])
        self.assertEqual(res["processed"], 1)

        # Check archive record was updated
        track = self.archive.get_track_by_path(audio_path)
        self.assertIsNotNone(track)
        self.assertEqual(track.get("artist"), "New Artist Name")

    def test_batch_tag_set_album_and_renumber(self):
        """Verify _handle_batch_tag sets album and track numbering in archive."""
        handler = object.__new__(FlacifyWebRequestHandler)
        handler.state = self.state

        def mock_send_json(data, status=200):
            handler._send_json_called = (data, status)
            return data

        handler._send_json = mock_send_json

        f1 = os.path.join(self.tmp_dir, "song1.mp3")
        f2 = os.path.join(self.tmp_dir, "song2.mp3")
        with open(f1, "wb") as f: f.write(b"1")
        with open(f2, "wb") as f: f.write(b"2")

        m1 = TrackMetadata(id="id1", title="Track One", artists=["Artist"], album="Old Album")
        m2 = TrackMetadata(id="id2", title="Track Two", artists=["Artist"], album="Old Album")
        self.archive.add_track(m1, f1, "320k", "youtube")
        self.archive.add_track(m2, f2, "320k", "youtube")

        handler._handle_batch_tag({
            "action": "set_album",
            "file_paths": [f1, f2],
            "new_album": "Mastered Album 2026",
            "renumber": True,
        })
        res, status = handler._send_json_called
        self.assertTrue(res["ok"])
        self.assertEqual(res["processed"], 2)

        t1 = self.archive.get_track_by_path(f1)
        t2 = self.archive.get_track_by_path(f2)
        self.assertIsNotNone(t1)
        self.assertIsNotNone(t2)
        self.assertEqual(t1.get("album"), "Mastered Album 2026")
        self.assertEqual(t1.get("track_number"), 1)
        self.assertEqual(t2.get("album"), "Mastered Album 2026")
        self.assertEqual(t2.get("track_number"), 2)

    def test_batch_tag_set_genre(self):
        """Verify _handle_batch_tag updates genre across database records."""
        handler = object.__new__(FlacifyWebRequestHandler)
        handler.state = self.state

        def mock_send_json(data, status=200):
            handler._send_json_called = (data, status)
            return data

        handler._send_json = mock_send_json

        f1 = os.path.join(self.tmp_dir, "song_genre.mp3")
        with open(f1, "wb") as f: f.write(b"g")
        m = TrackMetadata(id="id_g", title="Synth Track", artists=["Artist"], album="Album")
        self.archive.add_track(m, f1, "320k", "youtube")

        handler._handle_batch_tag({
            "action": "set_genre",
            "file_paths": [f1],
            "genre": "Synthwave",
        })
        res, status = handler._send_json_called
        self.assertTrue(res["ok"])
        self.assertEqual(res["processed"], 1)

        t = self.archive.get_track_by_path(f1)
        self.assertIsNotNone(t)
        self.assertEqual(t.get("genre"), "Synthwave")

    def test_batch_tag_diagnostics_total_failed_counts(self):
        handler = object.__new__(FlacifyWebRequestHandler)
        handler.state = self.state

        def mock_send_json(data, status=200):
            handler._send_json_called = (data, status)
            return data

        handler._send_json = mock_send_json

        real_audio = os.path.join(self.tmp_dir, "real_song.mp3")
        with open(real_audio, "wb") as f:
            f.write(b"audio data")
        missing_audio = os.path.join(self.tmp_dir, "missing_song.mp3")

        handler._handle_batch_tag({
            "action": "set_artist",
            "file_paths": [real_audio, missing_audio],
            "new_artist": "Audited Artist"
        })
        res, status = handler._send_json_called
        self.assertTrue(res["ok"])
        self.assertEqual(res["total"], 2)
        self.assertEqual(res["processed"], 1)
        self.assertEqual(res["failed"], 1)

    def test_library_repair_dialog_search_and_state_filtering(self):
        mock_rm = MagicMock()
        mock_rm.list_history.return_value = [
            {"id": "id-1", "file_path": "/music/classic_rock.mp3", "action": "retag", "state": "applied", "original_hash": "hash_a", "repaired_hash": "hash_b"},
            {"id": "id-2", "file_path": "/music/jazz_night.flac", "action": "duplicate", "state": "undone", "original_hash": "hash_c", "repaired_hash": "hash_d"},
            {"id": "id-3", "file_path": "/music/ambient.opus", "action": "retag", "state": "aborted", "original_hash": "hash_e", "repaired_hash": ""},
        ]
        dlg = LibraryRepairDialog(repair_manager=mock_rm)
        self.addCleanup(dlg.deleteLater)

        # Initial state: 3 entries
        self.assertEqual(len(dlg.history_entries), 3)

        # Search by file path substring
        dlg.search_input.setText("classic")
        visible_cards = [dlg.list_lay.itemAt(i).widget() for i in range(dlg.list_lay.count()) if dlg.list_lay.itemAt(i).widget()]
        self.assertEqual(len(visible_cards), 1)

        # Search by action
        dlg.search_input.setText("duplicate")
        visible_cards = [dlg.list_lay.itemAt(i).widget() for i in range(dlg.list_lay.count()) if dlg.list_lay.itemAt(i).widget()]
        self.assertEqual(len(visible_cards), 1)

        # Search by hash
        dlg.search_input.setText("hash_e")
        visible_cards = [dlg.list_lay.itemAt(i).widget() for i in range(dlg.list_lay.count()) if dlg.list_lay.itemAt(i).widget()]
        self.assertEqual(len(visible_cards), 1)

        # Search nonexistent
        dlg.search_input.setText("nomatch")
        visible_cards = [dlg.list_lay.itemAt(i).widget() for i in range(dlg.list_lay.count()) if dlg.list_lay.itemAt(i).widget()]
        self.assertEqual(len(visible_cards), 1)
        self.assertIn("No matching", visible_cards[0].text())

        # Reset search, test state filter
        dlg.search_input.setText("")
        dlg.state_filter.setCurrentText("Applied")
        visible_cards = [dlg.list_lay.itemAt(i).widget() for i in range(dlg.list_lay.count()) if dlg.list_lay.itemAt(i).widget()]
        self.assertEqual(len(visible_cards), 1)

        dlg.state_filter.setCurrentText("Undone")
        visible_cards = [dlg.list_lay.itemAt(i).widget() for i in range(dlg.list_lay.count()) if dlg.list_lay.itemAt(i).widget()]
        self.assertEqual(len(visible_cards), 1)

        dlg.state_filter.setCurrentText("Aborted")
        visible_cards = [dlg.list_lay.itemAt(i).widget() for i in range(dlg.list_lay.count()) if dlg.list_lay.itemAt(i).widget()]
        self.assertEqual(len(visible_cards), 1)

        dlg.state_filter.setCurrentText("All States")
        visible_cards = [dlg.list_lay.itemAt(i).widget() for i in range(dlg.list_lay.count()) if dlg.list_lay.itemAt(i).widget()]
        self.assertEqual(len(visible_cards), 3)

    def test_library_repair_dialog_undo_and_batch_undo(self):
        mock_rm = MagicMock()
        mock_rm.list_history.return_value = [
            {"id": "id-1", "file_path": "/music/song1.mp3", "action": "retag", "state": "applied"},
            {"id": "id-2", "file_path": "/music/song2.mp3", "action": "duplicate", "state": "applied"},
        ]
        dlg = LibraryRepairDialog(repair_manager=mock_rm)
        self.addCleanup(dlg.deleteLater)

        # Single undo
        dlg._trigger_undo("id-1")
        if dlg._last_undo_thread:
            dlg._last_undo_thread.join(timeout=5)
        QApplication.instance().processEvents()
        mock_rm.undo.assert_called_with("id-1")

        # Batch undo all applied
        mock_rm.undo.reset_mock()
        dlg._trigger_undo_all()
        if dlg._last_undo_thread:
            dlg._last_undo_thread.join(timeout=5)
        QApplication.instance().processEvents()
        self.assertEqual(mock_rm.undo.call_count, 2)
        mock_rm.undo.assert_any_call("id-1")
        mock_rm.undo.assert_any_call("id-2")

    def test_mini_player_bar_close_stops_watchdog(self):
        from gui.player_bar import MiniPlayerBar
        bar = MiniPlayerBar()
        self.addCleanup(bar.deleteLater)
        self.assertTrue(hasattr(bar, "_device_watchdog"))
        self.assertTrue(bar._device_watchdog.isActive())
        bar.close()
        self.assertFalse(bar._device_watchdog.isActive())


if __name__ == "__main__":
    unittest.main()
