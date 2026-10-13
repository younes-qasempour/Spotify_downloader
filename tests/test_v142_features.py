import os
import sys
import unittest
from unittest.mock import MagicMock

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from PyQt6.QtWidgets import QApplication, QLineEdit, QWidget
from PyQt6.QtCore import Qt, QEvent
from PyQt6.QtGui import QKeyEvent

# Single QApplication instance
app = QApplication.instance() or QApplication(sys.argv)

from gui.player_bar import MiniPlayerBar
from gui.media_keys import GlobalMediaKeyFilter, MediaControllerManager, is_text_input_focused


class TestV142Features(unittest.TestCase):
    def setUp(self):
        self.player_bar = MiniPlayerBar()
        self.player_bar.setVisible(True)

        class MockMainWindow(QWidget):
            def __init__(self, bar):
                super().__init__()
                self.player_bar = bar
                self._win_id = 12345
            def winId(self):
                return self._win_id

        self.mock_main_window = MockMainWindow(self.player_bar)
        self.key_filter = GlobalMediaKeyFilter(self.mock_main_window)

    def tearDown(self):
        if hasattr(self.player_bar, "_device_watchdog"):
            self.player_bar._device_watchdog.stop()
        self.player_bar.close()

    def test_audio_device_initialization_and_button(self):
        """Verifies QMediaDevices tracking and device button integration."""
        self.assertTrue(hasattr(self.player_bar, "media_devices"))
        self.assertTrue(hasattr(self.player_bar, "device_btn"))
        self.assertIsNotNone(self.player_bar.device_btn)
        self.assertTrue(hasattr(self.player_bar, "_device_watchdog"))
        self.assertTrue(self.player_bar._device_watchdog.isActive())

        # Check tooltip exists
        tip = self.player_bar.device_btn.toolTip()
        self.assertIn("Audio Output:", tip)

    def test_audio_device_switching(self):
        """Verifies _switch_audio_device correctly switches and updates state."""
        default_dev = self.player_bar.media_devices.defaultAudioOutput()
        if not default_dev.isNull():
            self.player_bar._switch_audio_device(default_dev, is_auto=True)
            self.assertIsNone(self.player_bar._selected_device_id)
            self.assertIn("Auto: System Default", self.player_bar.device_btn.toolTip())

            # Manual selection mode
            self.player_bar._switch_audio_device(default_dev, is_auto=False)
            self.assertEqual(self.player_bar._selected_device_id, bytes(default_dev.id()))
            self.assertIn("Manual", self.player_bar.device_btn.toolTip())

    def test_public_playback_transport_methods(self):
        """Verifies public transport control helpers."""
        # Volume adjust
        self.player_bar.volume_slider.setValue(50)
        self.player_bar.adjust_volume(10)
        self.assertEqual(self.player_bar.volume_slider.value(), 60)
        self.player_bar.adjust_volume(-20)
        self.assertEqual(self.player_bar.volume_slider.value(), 40)

        # Mute toggle
        self.player_bar.toggle_mute()
        self.assertEqual(self.player_bar.volume_slider.value(), 0)
        self.player_bar.toggle_mute()
        self.assertGreater(self.player_bar.volume_slider.value(), 0)

        # Shuffle & Repeat toggles
        initial_shuffle = self.player_bar.shuffle_enabled
        self.player_bar.toggle_shuffle()
        self.assertNotEqual(self.player_bar.shuffle_enabled, initial_shuffle)

        self.player_bar.toggle_repeat()
        self.assertIn(self.player_bar.repeat_mode, ["all", "one", "off"])

    def test_keyboard_filter_space_play_pause(self):
        """Verifies Space toggles play/pause when not editing text."""
        toggle_mock = MagicMock()
        self.player_bar.toggle_play_pause = toggle_mock

        dummy_widget = QWidget()
        dummy_widget.show()
        dummy_widget.setFocus()

        # Send space key event
        event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Space, Qt.KeyboardModifier.NoModifier)
        handled = self.key_filter.eventFilter(dummy_widget, event)
        self.assertTrue(handled)
        toggle_mock.assert_called_once()

    def test_keyboard_filter_does_not_hijack_text_input(self):
        """Verifies Space and regular keys are preserved when QLineEdit is focused."""
        toggle_mock = MagicMock()
        self.player_bar.toggle_play_pause = toggle_mock

        line_edit = QLineEdit()
        line_edit.show()

        # Send space key event while text edit is targeted
        event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Space, Qt.KeyboardModifier.NoModifier)
        handled = self.key_filter.eventFilter(line_edit, event)
        self.assertFalse(handled)
        toggle_mock.assert_not_called()

        line_edit.close()

    def test_keyboard_filter_hardware_media_keys(self):
        """Verifies hardware media keys trigger even if text input is active."""
        toggle_mock = MagicMock()
        next_mock = MagicMock()
        prev_mock = MagicMock()
        self.player_bar.toggle_play_pause = toggle_mock
        self.player_bar.play_next = next_mock
        self.player_bar.play_previous = prev_mock

        line_edit = QLineEdit()
        line_edit.show()
        line_edit.setFocus()

        # MediaPlayPause
        ev_play = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_MediaTogglePlayPause, Qt.KeyboardModifier.NoModifier)
        self.assertTrue(self.key_filter.eventFilter(line_edit, ev_play))
        toggle_mock.assert_called_once()

        # MediaNext
        ev_next = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_MediaNext, Qt.KeyboardModifier.NoModifier)
        self.assertTrue(self.key_filter.eventFilter(line_edit, ev_next))
        next_mock.assert_called_once()

        # MediaPrevious
        ev_prev = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_MediaPrevious, Qt.KeyboardModifier.NoModifier)
        self.assertTrue(self.key_filter.eventFilter(line_edit, ev_prev))
        prev_mock.assert_called_once()

        line_edit.close()

    def test_media_controller_manager_lifecycle(self):
        """Verifies setup and cleanup of MediaControllerManager."""
        manager = MediaControllerManager(self.mock_main_window)
        manager.setup()
        self.assertIsNotNone(manager.key_filter)
        manager.cleanup()
        self.assertIsNone(manager.key_filter)


if __name__ == "__main__":
    unittest.main()
