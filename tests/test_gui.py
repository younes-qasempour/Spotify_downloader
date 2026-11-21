import os
import sys
import unittest

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from PyQt6.QtWidgets import QApplication

# Single QApplication instance for the test process
app = QApplication.instance() or QApplication(sys.argv)

import requests
from unittest.mock import patch, MagicMock

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
            patch.object(requests.Session, "request", return_value=MagicMock(status_code=200, text="{}")),
            patch.object(requests.Session, "send", return_value=MagicMock(status_code=200, text="{}")),
        ]
        for p in self.patchers:
            p.start()

        self.window = MainWindow()

    def tearDown(self):
        if getattr(self.window, "tray_icon", None) is not None:
            self.window.tray_icon.hide()
            self.window.tray_icon.deleteLater()
        self.window.close()
        self.window.deleteLater()
        QApplication.instance().processEvents()
        QApplication.instance().processEvents()
        for p in reversed(self.patchers):
            p.stop()

    def test_main_window_components(self):
        self.assertIsNotNone(self.window.queue_view)
        self.assertIsNotNone(self.window.playlists_view)
        self.assertIsNotNone(self.window.completed_view)
        self.assertIsNotNone(self.window.settings_view)

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

    def test_detail_watch_btn_preserves_icon_padding(self):
        pv = self.window.playlists_view
        pv.current_playlist_data = {
            "id": "pl_test",
            "name": "Test Playlist",
            "auto_sync": False,
        }

        pv._update_detail_watch_btn()
        self.assertTrue(pv.detail_watch_btn.property("hasIcon"))
        self.assertEqual(pv.detail_watch_btn.text(), "Auto-Sync: Off")
        self.assertIn("padding: 5px 12px 6px 36px;", pv.detail_watch_btn.styleSheet())
        self.assertNotIn("#1DB954", pv.detail_watch_btn.styleSheet())

        pv.current_playlist_data["auto_sync"] = True
        pv._update_detail_watch_btn()
        self.assertEqual(pv.detail_watch_btn.text(), "Auto-Sync: ON")
        self.assertIn("padding: 5px 12px 6px 36px;", pv.detail_watch_btn.styleSheet())
        self.assertNotIn("padding: 4px 6px", pv.detail_watch_btn.styleSheet())
        self.assertIn("#1DB954", pv.detail_watch_btn.styleSheet())

        pv.current_playlist_data["auto_sync"] = False
        pv._update_detail_watch_btn()
        self.assertEqual(pv.detail_watch_btn.text(), "Auto-Sync: Off")
        self.assertIn("padding: 5px 12px 6px 36px;", pv.detail_watch_btn.styleSheet())
        self.assertNotIn("#1DB954", pv.detail_watch_btn.styleSheet())

    def test_navigation_switch(self):
        self.window.switchTo(self.window.playlists_view)
        self.assertEqual(self.window.stackedWidget.currentWidget(), self.window.playlists_view)

        self.window.switchTo(self.window.completed_view)
        self.assertEqual(self.window.stackedWidget.currentWidget(), self.window.completed_view)

        self.window.switchTo(self.window.settings_view)
        self.assertEqual(self.window.stackedWidget.currentWidget(), self.window.settings_view)

        self.window.switchTo(self.window.queue_view)
        self.assertEqual(self.window.stackedWidget.currentWidget(), self.window.queue_view)


if __name__ == "__main__":
    unittest.main()
