import os
import sys
import unittest
from types import SimpleNamespace

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtCore import QTimer

# Single QApplication instance for the test process
app = QApplication.instance() or QApplication(sys.argv)

import requests
from unittest.mock import patch, MagicMock, Mock

from core.archive import ArchiveManager
from core.queue_manager import DownloadQueueManager
from core.resolver import CascadingAudioEngine
from gui.bridge import EngineSignalBridge
from gui.main_window import MainWindow
from gui.views.queue_view import QueueView
from gui.views.playlists_view import PlaylistsView
from gui.views.completed_view import CompletedView
from gui.views.settings_view import SettingsView


class TestGUI(unittest.TestCase):
    def setUp(self):
        # Mock SpotifyClient across core and GUI views to prevent network calls and rate limits
        self.patchers = [
            patch("core.spotify_client.SpotifyClient"),
            patch("gui.views.queue_view.SpotifyClient"),
            patch("gui.views.playlists_view.SpotifyClient"),
            patch("gui.views.settings_view.SpotifyClient"),
            patch("gui.views.reliability_view.ReliabilityView.refresh"),
            patch("gui.views.reliability_view.ReliabilityView.refresh_queue"),
            patch.object(requests.Session, "request", return_value=MagicMock(status_code=200, text="{}")),
            patch.object(requests.Session, "send", return_value=MagicMock(status_code=200, text="{}")),
        ]
        for p in self.patchers:
            p.start()

        self.window = MainWindow()

    def tearDown(self):
        self.window.close()
        for p in reversed(self.patchers):
            p.stop()

    def test_main_window_components(self):
        self.assertIsNotNone(self.window.queue_view)
        self.assertIsNotNone(self.window.playlists_view)
        self.assertIsNotNone(self.window.completed_view)
        self.assertIsNotNone(self.window.settings_view)
        self.assertIsNotNone(self.window.reliability_view)

    def test_playlists_view_controls(self):
        pv = self.window.playlists_view
        # Verify open_folder_btn and batch download controls exist
        self.assertTrue(hasattr(pv, "open_folder_btn"))
        self.assertTrue(hasattr(pv, "download_batch_btn"))
        self.assertTrue(hasattr(pv, "download_selected_btn"))
        self.assertTrue(hasattr(pv, "pause_btn"))
        self.assertTrue(hasattr(pv, "stop_btn"))
        self.assertTrue(hasattr(pv, "reset_btn"))
        self.assertTrue(hasattr(pv, "export_songs_btn"))
        self.assertTrue(hasattr(pv, "batch_spinbox"))

    def test_playlist_startup_timer_is_owned_by_view(self):
        timer = self.window.playlists_view._startup_sync_timer
        self.assertIs(timer.parent(), self.window.playlists_view)
        self.assertTrue(timer.isSingleShot())

    def test_navigation_switch(self):
        self.window.switchTo(self.window.playlists_view)
        self.assertEqual(self.window.stackedWidget.currentWidget(), self.window.playlists_view)

        self.window.switchTo(self.window.completed_view)
        self.assertEqual(self.window.stackedWidget.currentWidget(), self.window.completed_view)

        self.window.switchTo(self.window.settings_view)
        self.assertEqual(self.window.stackedWidget.currentWidget(), self.window.settings_view)

        self.window.switchTo(self.window.queue_view)
        self.assertEqual(self.window.stackedWidget.currentWidget(), self.window.queue_view)

    def test_recovery_tools_button_opens_workspace(self):
        with patch.object(self.window.reliability_view, "refresh") as refresh:
            self.window._show_reliability()
        refresh.assert_called_once()
        self.assertEqual(self.window.stackedWidget.currentWidget(), self.window.reliability_view)

    def test_source_review_bridge_waits_for_explicit_decision(self):
        track = SimpleNamespace(id="track-id")
        summary = {"requested_title": "Song", "requested_artist": "Artist", "requested_duration": 180,
                   "title": "Song live", "artist": "Artist", "reasons": ["Version differs"]}
        decide = Mock()
        self.window.bridge.sig_source_review_required.emit(track, summary, decide)
        dialog = self.window._source_review_dialogs[track.id]
        timer = dialog.findChild(QTimer)
        self.assertTrue(timer.isActive())
        decide.assert_not_called()
        self.assertEqual(dialog.defaultButton(), dialog.button(QMessageBox.StandardButton.No))
        dialog.button(QMessageBox.StandardButton.Yes).click()
        self.assertFalse(timer.isActive())
        decide.assert_called_once_with(True)
        self.assertNotIn(track.id, self.window._source_review_dialogs)

    def test_closing_source_review_rejects_match(self):
        track = SimpleNamespace(id="track-id")
        decide = Mock()
        self.window.bridge.sig_source_review_required.emit(track, {"requested_duration": 0}, decide)
        self.window._source_review_dialogs[track.id].reject()
        decide.assert_called_once_with(False)


if __name__ == "__main__":
    unittest.main()
