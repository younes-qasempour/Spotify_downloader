import os
import unittest
from unittest.mock import MagicMock, patch

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt

# Ensure QApplication exists for GUI tests
app = QApplication.instance()
if not app:
    app = QApplication([])

from gui.floating_mini_player import FloatingMiniPlayerWindow, format_ms
from gui.web_api import WebBackendState, FlacifyWebServer


class TestFloatingMiniPlayer(unittest.TestCase):
    """Test suite for the OS-Level Floating Mini-Player / PiP Window."""

    def setUp(self):
        self.mock_web_studio = MagicMock()
        self.mini_player = FloatingMiniPlayerWindow(web_studio_view=self.mock_web_studio)

    def tearDown(self):
        self.mini_player.close()

    def test_format_ms(self):
        self.assertEqual(format_ms(0), "0:00")
        self.assertEqual(format_ms(65000), "1:05")
        self.assertEqual(format_ms(245000), "4:05")
        self.assertEqual(format_ms(-500), "0:00")

    def test_window_flags_and_attributes(self):
        flags = self.mini_player.windowFlags()
        self.assertTrue(bool(flags & Qt.WindowType.FramelessWindowHint))
        self.assertTrue(bool(flags & Qt.WindowType.WindowStaysOnTopHint))
        self.assertEqual(self.mini_player.windowTitle(), "Flacify Mini Player")

    def test_toggle_visibility(self):
        self.assertFalse(self.mini_player.isVisible())
        self.mini_player.toggle_visibility()
        self.assertTrue(self.mini_player.isVisible())
        self.mini_player.toggle_visibility()
        self.assertFalse(self.mini_player.isVisible())

    def test_toggle_pinned(self):
        self.assertTrue(self.mini_player._is_pinned)
        self.mini_player._toggle_pinned()
        self.assertFalse(self.mini_player._is_pinned)
        flags = self.mini_player.windowFlags()
        self.assertFalse(bool(flags & Qt.WindowType.WindowStaysOnTopHint))

        self.mini_player._toggle_pinned()
        self.assertTrue(self.mini_player._is_pinned)
        flags = self.mini_player.windowFlags()
        self.assertTrue(bool(flags & Qt.WindowType.WindowStaysOnTopHint))

    def test_update_state(self):
        sample_state = {
            "hasTrack": True,
            "title": "Stay with Me",
            "artist": "Miki Matsubara",
            "album": "Pocket Park",
            "cover_key": "",
            "is_playing": True,
            "position_ms": 75000,
            "duration_ms": 300000,
            "lyric": "真夜中のドアをたたき",
            "volume": 85,
        }
        self.mini_player.update_state(sample_state)

        self.assertIn("Stay with Me", self.mini_player.lbl_title.toolTip())
        self.assertIn("Miki Matsubara", self.mini_player.lbl_artist.toolTip())
        self.assertEqual(self.mini_player.btn_play.text(), "⏸")
        self.assertEqual(self.mini_player.lbl_cur_time.text(), "1:15")
        self.assertEqual(self.mini_player.lbl_dur_time.text(), "5:00")
        self.assertEqual(self.mini_player.seek_slider.value(), 75000)
        self.assertEqual(self.mini_player.lbl_lyrics.text(), "真夜中のドアをたたき")
        self.assertEqual(self.mini_player.vol_slider.value(), 85)

    def test_backend_toggle_callback(self):
        qm = MagicMock()
        am = MagicMock()
        mock_cb = MagicMock()

        state = WebBackendState(
            queue_manager=qm,
            archive_manager=am,
            mini_player_toggle_cb=mock_cb
        )
        self.assertEqual(state.mini_player_toggle_cb, mock_cb)

        # Call toggle
        state.mini_player_toggle_cb()
        mock_cb.assert_called_once()

    def test_resizing_and_adaptive_modes(self):
        # Minimum size check (ultra compact)
        self.assertEqual(self.mini_player.minimumWidth(), 200)
        self.assertEqual(self.mini_player.minimumHeight(), 52)

        # 1. Compact Bar Mode (h < 110)
        self.mini_player.resize(220, 60)
        self.assertEqual(self.mini_player._active_mode, "compact")
        self.assertTrue(self.mini_player.header_widget.isHidden())
        self.assertTrue(self.mini_player.lbl_lyrics.isHidden())
        self.assertTrue(self.mini_player.ctrl_row.isHidden())

        # 2. Standard Studio Mode (110 <= h < 240)
        self.mini_player.resize(380, 168)
        self.assertEqual(self.mini_player._active_mode, "standard")
        self.assertFalse(self.mini_player.header_widget.isHidden())
        self.assertFalse(self.mini_player.lbl_lyrics.isHidden())
        self.assertFalse(self.mini_player.ctrl_row.isHidden())

        # 3. Large Album Art Mode (h >= 240 and w >= 260)
        self.mini_player.resize(450, 400)
        self.assertEqual(self.mini_player._active_mode, "large")
        self.assertFalse(self.mini_player.header_widget.isHidden())
        self.assertFalse(self.mini_player.lbl_cover.isHidden())
        self.assertGreaterEqual(self.mini_player.lbl_cover.width(), 80)


if __name__ == "__main__":
    unittest.main()

