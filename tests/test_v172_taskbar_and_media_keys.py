import os
import sys
import unittest
from unittest.mock import MagicMock, patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PyQt6.QtWidgets import QApplication, QLineEdit, QWidget
from PyQt6.QtCore import Qt, QEvent
from PyQt6.QtGui import QKeyEvent

# Single QApplication instance
app = QApplication.instance() or QApplication(sys.argv)

from gui.media_keys import (
    GlobalMediaKeyFilter, WindowsMediaNativeFilter, MediaControllerManager,
    HK_PLAY_PAUSE, HK_NEXT, HK_PREV, HK_STOP,
    APPCOMMAND_MEDIA_PLAY_PAUSE, APPCOMMAND_MEDIA_NEXTTRACK,
    APPCOMMAND_MEDIA_PREVIOUSTRACK, APPCOMMAND_MEDIA_STOP,
    WM_HOTKEY, WM_APPCOMMAND, WM_COMMAND
)
from gui.taskbar_thumbnail import (
    TaskbarThumbnailManager, THBN_CLICKED,
    THB_PREV_ID, THB_PLAY_PAUSE_ID, THB_NEXT_ID
)


class MockMainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.media_play_pause = MagicMock()
        self.media_next = MagicMock()
        self.media_prev = MagicMock()
        self.media_stop = MagicMock()
        self.media_adjust_volume = MagicMock()
        self.media_seek_relative = MagicMock()
        self.media_toggle_mute = MagicMock()
        self.media_toggle_shuffle = MagicMock()
        self.media_toggle_repeat = MagicMock()
        self.player_bar = None

    def winId(self):
        return 99999


class TestTaskbarAndMediaKeys(unittest.TestCase):
    def setUp(self):
        self.mock_window = MockMainWindow()
        self.key_filter = GlobalMediaKeyFilter(self.mock_window)
        self.taskbar_mgr = TaskbarThumbnailManager(self.mock_window)

    def tearDown(self):
        self.taskbar_mgr.cleanup()
        self.mock_window.close()

    def test_taskbar_thumbnail_commands(self):
        """Verifies Taskbar thumbnail buttons dispatch to mock_window."""
        self.assertEqual(THBN_CLICKED, 0x1800)
        self.assertEqual(THB_PREV_ID, 1)
        self.assertEqual(THB_PLAY_PAUSE_ID, 2)
        self.assertEqual(THB_NEXT_ID, 3)

        # Prev button click (HIWORD=THBN_CLICKED, LOWORD=1)
        wparam_prev = (THBN_CLICKED << 16) | THB_PREV_ID
        handled = self.taskbar_mgr.handle_command(wparam_prev)
        self.assertTrue(handled)
        self.mock_window.media_prev.assert_called_once()

        # Play/Pause button click
        wparam_pp = (THBN_CLICKED << 16) | THB_PLAY_PAUSE_ID
        handled = self.taskbar_mgr.handle_command(wparam_pp)
        self.assertTrue(handled)
        self.mock_window.media_play_pause.assert_called_once()

        # Next button click
        wparam_next = (THBN_CLICKED << 16) | THB_NEXT_ID
        handled = self.taskbar_mgr.handle_command(wparam_next)
        self.assertTrue(handled)
        self.mock_window.media_next.assert_called_once()

        # Unrelated notification
        wparam_other = (0x0200 << 16) | THB_PLAY_PAUSE_ID
        self.assertFalse(self.taskbar_mgr.handle_command(wparam_other))

    def test_taskbar_thumbnail_playback_state_update(self):
        """Verifies update_playback_state toggles internal flag safely."""
        self.taskbar_mgr.update_playback_state(True)
        self.assertTrue(self.taskbar_mgr._is_playing)

        self.taskbar_mgr.update_playback_state(False)
        self.assertFalse(self.taskbar_mgr._is_playing)

    def test_global_keyboard_shortcuts_dispatch(self):
        """Verifies space and modifier-arrow transport hotkeys trigger media_*()."""
        dummy = QWidget()
        dummy.show()

        # 1. Space -> play_pause
        ev_space = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Space, Qt.KeyboardModifier.NoModifier)
        self.assertTrue(self.key_filter.eventFilter(dummy, ev_space))
        self.mock_window.media_play_pause.assert_called_once()

        # 2. Ctrl + Right -> media_next
        ev_ctrl_r = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Right, Qt.KeyboardModifier.ControlModifier)
        self.assertTrue(self.key_filter.eventFilter(dummy, ev_ctrl_r))
        self.mock_window.media_next.assert_called_once()

        # 3. Ctrl + Left -> media_prev
        ev_ctrl_l = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Left, Qt.KeyboardModifier.ControlModifier)
        self.assertTrue(self.key_filter.eventFilter(dummy, ev_ctrl_l))
        self.mock_window.media_prev.assert_called_once()

        # 4. Shift + Right -> seek_relative(10000)
        ev_shift_r = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Right, Qt.KeyboardModifier.ShiftModifier)
        self.assertTrue(self.key_filter.eventFilter(dummy, ev_shift_r))
        self.mock_window.media_seek_relative.assert_called_with(10000)

        # 5. Left -> seek_relative(-5000)
        ev_l = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Left, Qt.KeyboardModifier.NoModifier)
        self.assertTrue(self.key_filter.eventFilter(dummy, ev_l))
        self.mock_window.media_seek_relative.assert_called_with(-5000)

        # 6. Up / Down volume
        ev_up = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Up, Qt.KeyboardModifier.NoModifier)
        self.assertTrue(self.key_filter.eventFilter(dummy, ev_up))
        self.mock_window.media_adjust_volume.assert_called_with(5)

        ev_dn = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Down, Qt.KeyboardModifier.NoModifier)
        self.assertTrue(self.key_filter.eventFilter(dummy, ev_dn))
        self.mock_window.media_adjust_volume.assert_called_with(-5)

        # 7. Letter Keys (K, J, L, N, P, M, S, R) must NEVER be intercepted by the global filter
        for letter_key in [Qt.Key.Key_K, Qt.Key.Key_J, Qt.Key.Key_L, Qt.Key.Key_N, Qt.Key.Key_P, Qt.Key.Key_M, Qt.Key.Key_S, Qt.Key.Key_R]:
            ev_letter = QKeyEvent(QEvent.Type.KeyPress, letter_key, Qt.KeyboardModifier.NoModifier)
            handled = self.key_filter.eventFilter(dummy, ev_letter)
            self.assertFalse(handled, f"Key {letter_key} should NOT be intercepted by GlobalMediaKeyFilter")

        dummy.close()

    def test_text_input_and_web_safeguard(self):
        """Verifies text field typing and web view typing are never intercepted."""
        line_edit = QLineEdit()
        line_edit.show()

        ev_space = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Space, Qt.KeyboardModifier.NoModifier)
        handled = self.key_filter.eventFilter(line_edit, ev_space)
        self.assertFalse(handled)
        self.mock_window.media_play_pause.assert_not_called()

        ev_k = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_K, Qt.KeyboardModifier.NoModifier)
        handled = self.key_filter.eventFilter(line_edit, ev_k)
        self.assertFalse(handled)

        ev_l = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_L, Qt.KeyboardModifier.NoModifier)
        handled = self.key_filter.eventFilter(line_edit, ev_l)
        self.assertFalse(handled)

        line_edit.close()

    def test_native_filter_without_player_bar_visible(self):
        """Verifies Windows native filter triggers mock_window directly even when player_bar is hidden."""
        if sys.platform != "win32":
            return

        import ctypes
        from gui.media_keys import MSG

        native_filter = WindowsMediaNativeFilter(self.mock_window, self.taskbar_mgr)

        # 1. Simulate WM_HOTKEY for Play/Pause
        msg_hk = MSG(
            hwnd=self.mock_window.winId(),
            message=WM_HOTKEY,
            wParam=HK_PLAY_PAUSE,
            lParam=0,
            time=0, pt_x=0, pt_y=0
        )
        msg_ptr = ctypes.addressof(msg_hk)
        handled, ret = native_filter.nativeEventFilter(b"windows_generic_MSG", msg_ptr)
        self.assertTrue(handled)
        self.mock_window.media_play_pause.assert_called_once()

        # 2. Simulate WM_APPCOMMAND for Next Track
        msg_appcmd = MSG(
            hwnd=self.mock_window.winId(),
            message=WM_APPCOMMAND,
            wParam=0,
            lParam=APPCOMMAND_MEDIA_NEXTTRACK << 16,
            time=0, pt_x=0, pt_y=0
        )
        msg_ptr = ctypes.addressof(msg_appcmd)
        handled, ret = native_filter.nativeEventFilter(b"windows_generic_MSG", msg_ptr)
        self.assertTrue(handled)
        self.mock_window.media_next.assert_called_once()

        # 3. Simulate WM_COMMAND with THBN_CLICKED for Prev Track
        msg_cmd = MSG(
            hwnd=self.mock_window.winId(),
            message=WM_COMMAND,
            wParam=(THBN_CLICKED << 16) | THB_PREV_ID,
            lParam=0,
            time=0, pt_x=0, pt_y=0
        )
        msg_ptr = ctypes.addressof(msg_cmd)
        handled, ret = native_filter.nativeEventFilter(b"windows_generic_MSG", msg_ptr)
        self.assertTrue(handled)
        self.mock_window.media_prev.assert_called_once()


if __name__ == "__main__":
    unittest.main()
