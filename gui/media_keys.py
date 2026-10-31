"""
Media Key & Keyboard Transport Control System for Flacify.
Provides dual-layer keyboard and hardware controller integration:
1. Application-wide Qt Key Filter (GlobalMediaKeyFilter):
   Intercepts Space, Left/Right scrubbing, Up/Down volume, Ctrl+Left/Right track skips,
   and YouTube/Spotify hotkeys (J/K/L/M/N/P) everywhere in Flacify without stealing
   focus or interfering with text-input fields.
2. Windows Hardware Native Filter (WindowsMediaNativeFilter):
   Hooks Windows multimedia hotkeys and WM_APPCOMMAND messages so Bluetooth headsets,
   earbuds, and multimedia keyboards seamlessly control Flacify even in background.
"""

import sys
import logging
from typing import Optional, Dict

from PyQt6.QtCore import QObject, QEvent, Qt, QAbstractNativeEventFilter
from PyQt6.QtWidgets import (
    QApplication, QLineEdit, QTextEdit, QPlainTextEdit,
    QAbstractSpinBox, QComboBox
)

logger = logging.getLogger("gui.media_keys")

# Windows API Constants & Structures
if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    class MSG(ctypes.Structure):
        _fields_ = [
            ("hwnd", wintypes.HWND),
            ("message", wintypes.UINT),
            ("wParam", wintypes.WPARAM),
            ("lParam", wintypes.LPARAM),
            ("time", wintypes.DWORD),
            ("pt_x", wintypes.LONG),
            ("pt_y", wintypes.LONG),
        ]

    WM_HOTKEY = 0x0312
    WM_APPCOMMAND = 0x0319

    # AppCommand Codes (lParam high word)
    APPCOMMAND_MEDIA_NEXTTRACK = 11
    APPCOMMAND_MEDIA_PREVIOUSTRACK = 12
    APPCOMMAND_MEDIA_STOP = 13
    APPCOMMAND_MEDIA_PLAY_PAUSE = 14
    APPCOMMAND_MEDIA_PLAY = 46
    APPCOMMAND_MEDIA_PAUSE = 47

    # Windows Virtual Keys
    VK_MEDIA_NEXT_TRACK = 0xB0
    VK_MEDIA_PREV_TRACK = 0xB1
    VK_MEDIA_STOP = 0xB2
    VK_MEDIA_PLAY_PAUSE = 0xB3
    MOD_NOREPEAT = 0x4000

    HK_PLAY_PAUSE = 1001
    HK_NEXT = 1002
    HK_PREV = 1003
    HK_STOP = 1004


def is_text_input_widget(w: Optional[QObject]) -> bool:
    """Checks whether the given widget is an active text input."""
    if w is None:
        return False
    if isinstance(w, (QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox)):
        return True
    if isinstance(w, QComboBox) and w.isEditable():
        return True
    if hasattr(w, "inherits") and (w.inherits("QLineEdit") or w.inherits("QTextEdit") or w.inherits("QPlainTextEdit")):
        return True
    return False


def is_text_input_focused() -> bool:
    """Checks whether the currently focused widget is an active text input."""
    return is_text_input_widget(QApplication.focusWidget())


class GlobalMediaKeyFilter(QObject):
    """
    Application-wide event filter for media keys and player keyboard navigation.
    Handles playback controls seamlessly when Flacify is focused without hijacking
    text-editing fields.
    """

    def __init__(self, main_window):
        parent = main_window if isinstance(main_window, QObject) else None
        super().__init__(parent)
        self.main_window = main_window

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.KeyPress:
            key = event.key()
            modifiers = event.modifiers()
            has_ctrl = bool(modifiers & Qt.KeyboardModifier.ControlModifier)
            has_shift = bool(modifiers & Qt.KeyboardModifier.ShiftModifier)
            has_alt = bool(modifiers & Qt.KeyboardModifier.AltModifier)

            player_bar = getattr(self.main_window, "player_bar", None)

            # ---------------------------------------------------------
            # 1. Hardware Media Keys (ALWAYS handled regardless of focus)
            # ---------------------------------------------------------
            if key in (Qt.Key.Key_MediaPlay, Qt.Key.Key_MediaPause, Qt.Key.Key_MediaTogglePlayPause):
                if hasattr(self.main_window, "media_play_pause"):
                    self.main_window.media_play_pause()
                elif player_bar:
                    player_bar.toggle_play_pause()
                return True
            elif key == Qt.Key.Key_MediaNext:
                if hasattr(self.main_window, "media_next"):
                    self.main_window.media_next()
                elif player_bar:
                    player_bar.play_next()
                return True
            elif key == Qt.Key.Key_MediaPrevious:
                if hasattr(self.main_window, "media_prev"):
                    self.main_window.media_prev()
                elif player_bar:
                    player_bar.play_previous()
                return True
            elif key == Qt.Key.Key_MediaStop:
                if hasattr(self.main_window, "media_stop"):
                    self.main_window.media_stop()
                elif player_bar:
                    player_bar.player.stop()
                return True

            # ---------------------------------------------------------
            # 2. Check if a text input widget is focused or being typed into
            # ---------------------------------------------------------
            if is_text_input_widget(QApplication.focusWidget()) or is_text_input_widget(watched):
                return super().eventFilter(watched, event)

            player_bar = getattr(self.main_window, "player_bar", None)
            is_web = hasattr(self.main_window, "web_studio_view")

            # ---------------------------------------------------------
            # 3. In-App Keyboard Shortcuts (Active when not editing text)
            # ---------------------------------------------------------
            if key == Qt.Key.Key_Space:
                if is_web:
                    self.main_window.media_play_pause()
                elif player_bar and player_bar.isVisible():
                    player_bar.toggle_play_pause()
                return True

            elif key == Qt.Key.Key_Left:
                if has_ctrl:
                    if is_web: self.main_window.media_prev()
                    elif player_bar: player_bar.play_previous()
                elif has_shift:
                    if is_web: self.main_window.media_seek_relative(-10000)
                    elif player_bar: player_bar.seek_relative(-10000)
                else:
                    if is_web: self.main_window.media_seek_relative(-5000)
                    elif player_bar: player_bar.seek_relative(-5000)
                return True

            elif key == Qt.Key.Key_Right:
                if has_ctrl:
                    if is_web: self.main_window.media_next()
                    elif player_bar: player_bar.play_next()
                elif has_shift:
                    if is_web: self.main_window.media_seek_relative(10000)
                    elif player_bar: player_bar.seek_relative(10000)
                else:
                    if is_web: self.main_window.media_seek_relative(5000)
                    elif player_bar: player_bar.seek_relative(5000)
                return True

            elif key == Qt.Key.Key_Up:
                if is_web: self.main_window.media_adjust_volume(5)
                elif player_bar: player_bar.adjust_volume(5)
                return True

            elif key == Qt.Key.Key_Down:
                if is_web: self.main_window.media_adjust_volume(-5)
                elif player_bar: player_bar.adjust_volume(-5)
                return True

            elif not has_ctrl and not has_alt:
                if key == Qt.Key.Key_K:
                    player_bar.toggle_play_pause()
                    return True
                elif key == Qt.Key.Key_J:
                    player_bar.seek_relative(-10000)
                    return True
                elif key == Qt.Key.Key_L:
                    player_bar.seek_relative(10000)
                    return True
                elif key == Qt.Key.Key_N:
                    player_bar.play_next()
                    return True
                elif key == Qt.Key.Key_P:
                    player_bar.play_previous()
                    return True
                elif key == Qt.Key.Key_M:
                    player_bar.toggle_mute()
                    return True
                elif key == Qt.Key.Key_S:
                    player_bar.toggle_shuffle()
                    return True
                elif key == Qt.Key.Key_R:
                    player_bar.toggle_repeat()
                    return True

        return super().eventFilter(watched, event)


class WindowsMediaNativeFilter(QAbstractNativeEventFilter):
    """
    Native Windows Message Filter for system-wide media hotkeys and WM_APPCOMMAND events.
    Enables background and headset controls even when Flacify is minimized or unfocused.
    """

    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window

    def nativeEventFilter(self, eventType, message) -> tuple:
        if sys.platform == "win32" and eventType == b"windows_generic_MSG":
            try:
                msg = MSG.from_address(int(message))
                player_bar = getattr(self.main_window, "player_bar", None)

                # WM_HOTKEY
                if msg.message == WM_HOTKEY:
                    hk_id = msg.wParam
                    if player_bar and player_bar.isVisible():
                        if hk_id == HK_PLAY_PAUSE:
                            player_bar.toggle_play_pause()
                            return True, 0
                        elif hk_id == HK_NEXT:
                            player_bar.play_next()
                            return True, 0
                        elif hk_id == HK_PREV:
                            player_bar.play_previous()
                            return True, 0
                        elif hk_id == HK_STOP:
                            player_bar.player.stop()
                            return True, 0

                # WM_APPCOMMAND (Headset buttons, multimedia keyboard commands)
                elif msg.message == WM_APPCOMMAND:
                    cmd = (msg.lParam >> 16) & ~0xF000
                    if player_bar and player_bar.isVisible():
                        if cmd in (APPCOMMAND_MEDIA_PLAY_PAUSE, APPCOMMAND_MEDIA_PLAY, APPCOMMAND_MEDIA_PAUSE):
                            player_bar.toggle_play_pause()
                            return True, 1
                        elif cmd == APPCOMMAND_MEDIA_NEXTTRACK:
                            player_bar.play_next()
                            return True, 1
                        elif cmd == APPCOMMAND_MEDIA_PREVIOUSTRACK:
                            player_bar.play_previous()
                            return True, 1
                        elif cmd == APPCOMMAND_MEDIA_STOP:
                            player_bar.player.stop()
                            return True, 1
            except Exception as e:
                logger.debug(f"Error processing Windows media message: {e}")

        return False, 0


class MediaControllerManager:
    """Manages the lifecycle of application and native media filters and hotkeys."""

    def __init__(self, main_window):
        self.main_window = main_window
        self.key_filter: Optional[GlobalMediaKeyFilter] = None
        self.native_filter: Optional[WindowsMediaNativeFilter] = None
        self.registered_hotkeys: Dict[int, int] = {}

    def setup(self):
        """Installs global key filter and registers Windows media hotkeys."""
        app = QApplication.instance()
        if not app:
            return

        # Install application key filter
        self.key_filter = GlobalMediaKeyFilter(self.main_window)
        app.installEventFilter(self.key_filter)

        # On Windows, install native filter and register global media hotkeys
        if sys.platform == "win32":
            self.native_filter = WindowsMediaNativeFilter(self.main_window)
            app.installNativeEventFilter(self.native_filter)
            self._register_windows_hotkeys()

        logger.info("MediaControllerManager successfully initialized")

    def _register_windows_hotkeys(self):
        try:
            hwnd = int(self.main_window.winId())
            user32 = ctypes.windll.user32
            hotkeys = [
                (HK_PLAY_PAUSE, VK_MEDIA_PLAY_PAUSE),
                (HK_NEXT, VK_MEDIA_NEXT_TRACK),
                (HK_PREV, VK_MEDIA_PREV_TRACK),
                (HK_STOP, VK_MEDIA_STOP),
            ]
            for hk_id, vk in hotkeys:
                if user32.RegisterHotKey(hwnd, hk_id, MOD_NOREPEAT, vk):
                    self.registered_hotkeys[hk_id] = vk
                    logger.debug(f"Registered global hotkey {hk_id} (VK {hex(vk)})")
        except Exception as e:
            logger.debug(f"Failed to register Windows media hotkeys: {e}")

    def cleanup(self):
        """Cleanly unregisters Windows hotkeys and removes installed filters."""
        app = QApplication.instance()
        if app and self.key_filter:
            app.removeEventFilter(self.key_filter)
            self.key_filter = None

        if sys.platform == "win32":
            if app and self.native_filter:
                app.removeNativeEventFilter(self.native_filter)
                self.native_filter = None

            if self.registered_hotkeys:
                try:
                    hwnd = int(self.main_window.winId())
                    user32 = ctypes.windll.user32
                    for hk_id in self.registered_hotkeys:
                        user32.UnregisterHotKey(hwnd, hk_id)
                    self.registered_hotkeys.clear()
                    logger.debug("Unregistered all Windows global media hotkeys")
                except Exception as e:
                    logger.debug(f"Error unregistering hotkeys: {e}")
