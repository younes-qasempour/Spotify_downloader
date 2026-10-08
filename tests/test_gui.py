import os
import sys
import unittest

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from PyQt6.QtWidgets import QApplication

# Single QApplication instance for the test process
app = QApplication.instance() or QApplication(sys.argv)

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
        self.window = MainWindow()

    def tearDown(self):
        self.window.close()

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
        self.assertTrue(hasattr(pv, "batch_spinbox"))

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
