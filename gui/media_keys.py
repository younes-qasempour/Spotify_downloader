"""
Media Key & Keyboard Transport Control System for Flacify.
Provides comprehensive keyboard, hardware controller, and taskbar integration:
1. Application-wide Qt Key Filter (GlobalMediaKeyFilter):
   Intercepts Space, Left/Right scrubbing, Up/Down volume, Ctrl+Left/Right track skips,
   and YouTube/Spotify hotkeys (J/K/L/M/N/P/S/R) everywhere in Flacify without stealing
   focus or interfering with text-input fields.
2. Windows Hardware Native Filter (WindowsMediaNativeFilter):
   Hooks Windows multimedia hotkeys and WM_APPCOMMAND messages so Bluetooth headsets,
   earbuds, and multimedia keyboards seamlessly control Flacify even in background.
3. Windows Taskbar Thumbnail Toolbar Integration (TaskbarThumbnailManager):
   Wires interactive Previous, Play/Pause, and Next buttons directly into the Windows
   taskbar thumbnail hover preview flyout.
"""

import sys
import logging
from typing import Optional, Dict, Any

from PyQt6.QtCore import QObject, QEvent, Qt, QAbstractNativeEventFilter, QTimer
from PyQt6.QtWidgets import (
    QApplication, QLineEdit, QTextEdit, QPlainTextEdit,
    QAbstractSpinBox, QComboBox, QWidget
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
    WM_COMMAND = 0x0111

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
    """Checks whether the given widget is an active text input or editing component."""
    if w is None:
        return False
    if isinstance(w, (QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox)):
        return True
    if isinstance(w, QComboBox) and w.isEditable():
        return True
    if hasattr(w, "inherits") and (w.inherits("QLineEdit") or w.inherits("QTextEdit") or w.inherits("QPlainTextEdit")):
        return True
    return False


def is_inside_web_view(w: Optional[QObject]) -> bool:
    """Checks whether the widget is a Chromium QWebEngineView or child thereof."""
    if w is None:
        return False
    curr = w
    while curr:
        cls_name = curr.metaObject().className() if hasattr(curr, "metaObject") else curr.__class__.__name__
        if "WebEngine" in cls_name or "RenderWidgetHost" in cls_name:
            return True
        curr = curr.parent() if hasattr(curr, "parent") else None
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
            # 2. Text Input & Web View Safeguard:
            # If the user is typing into any input or within the web view,
            # NEVER hijack typing keys, space, or navigation. Let Chromium/Qt handle it.
            # ---------------------------------------------------------
            focused_widget = QApplication.focusWidget()
            if is_text_input_widget(focused_widget) or is_text_input_widget(watched):
                return super().eventFilter(watched, event)

            if is_inside_web_view(focused_widget) or is_inside_web_view(watched):
                return super().eventFilter(watched, event)

            # ---------------------------------------------------------
            # 3. Native In-App Shortcuts (ONLY for non-web, non-text focus)
            # All letter keys (K, L, M, N, P, S, R, etc.) are strictly NOT bound
            # to guarantee that typing is never hijacked anywhere in Flacify.
            # ---------------------------------------------------------
            if key == Qt.Key.Key_Space:
                if hasattr(self.main_window, "media_play_pause"):
                    self.main_window.media_play_pause()
                elif player_bar:
                    player_bar.toggle_play_pause()
                return True

            elif key == Qt.Key.Key_Left:
                if has_ctrl:
                    if hasattr(self.main_window, "media_prev"):
                        self.main_window.media_prev()
                    elif player_bar:
                        player_bar.play_previous()
                elif has_shift:
                    if hasattr(self.main_window, "media_seek_relative"):
                        self.main_window.media_seek_relative(-10000)
                    elif player_bar:
                        player_bar.seek_relative(-10000)
                else:
                    if hasattr(self.main_window, "media_seek_relative"):
                        self.main_window.media_seek_relative(-5000)
                    elif player_bar:
                        player_bar.seek_relative(-5000)
                return True

            elif key == Qt.Key.Key_Right:
                if has_ctrl:
                    if hasattr(self.main_window, "media_next"):
                        self.main_window.media_next()
                    elif player_bar:
                        player_bar.play_next()
                elif has_shift:
                    if hasattr(self.main_window, "media_seek_relative"):
                        self.main_window.media_seek_relative(10000)
                    elif player_bar:
                        player_bar.seek_relative(10000)
                else:
                    if hasattr(self.main_window, "media_seek_relative"):
                        self.main_window.media_seek_relative(5000)
                    elif player_bar:
                        player_bar.seek_relative(5000)
                return True

            elif key == Qt.Key.Key_Up:
                if hasattr(self.main_window, "media_adjust_volume"):
                    self.main_window.media_adjust_volume(5)
                elif player_bar:
                    player_bar.adjust_volume(5)
                return True

            elif key == Qt.Key.Key_Down:
                if hasattr(self.main_window, "media_adjust_volume"):
                    self.main_window.media_adjust_volume(-5)
                elif player_bar:
                    player_bar.adjust_volume(-5)
                return True

        return super().eventFilter(watched, event)


class WindowsMediaNativeFilter(QAbstractNativeEventFilter):
    """
    Native Windows Message Filter for system-wide media hotkeys, WM_APPCOMMAND events,
    and Taskbar Thumbnail Toolbar clicks.
    Enables background, headset, and taskbar controls even when Flacify is minimized or unfocused.
    """

    def __init__(self, main_window, taskbar_manager=None):
        super().__init__()
        self.main_window = main_window
        self.taskbar_manager = taskbar_manager

    def nativeEventFilter(self, eventType, message) -> tuple:
        if sys.platform == "win32" and eventType == b"windows_generic_MSG":
            try:
                msg = MSG.from_address(int(message))

                # 1. WM_HOTKEY (Registered system-wide media keys)
                if msg.message == WM_HOTKEY:
                    hk_id = msg.wParam
                    if hk_id == HK_PLAY_PAUSE:
                        if hasattr(self.main_window, "media_play_pause"):
                            self.main_window.media_play_pause()
                        return True, 0
                    elif hk_id == HK_NEXT:
                        if hasattr(self.main_window, "media_next"):
                            self.main_window.media_next()
                        return True, 0
                    elif hk_id == HK_PREV:
                        if hasattr(self.main_window, "media_prev"):
                            self.main_window.media_prev()
                        return True, 0
                    elif hk_id == HK_STOP:
                        if hasattr(self.main_window, "media_stop"):
                            self.main_window.media_stop()
                        return True, 0

                # 2. WM_APPCOMMAND (Headset buttons, multimedia keyboard commands)
                elif msg.message == WM_APPCOMMAND:
                    cmd = (msg.lParam >> 16) & ~0xF000
                    if cmd in (APPCOMMAND_MEDIA_PLAY_PAUSE, APPCOMMAND_MEDIA_PLAY, APPCOMMAND_MEDIA_PAUSE):
                        if hasattr(self.main_window, "media_play_pause"):
                            self.main_window.media_play_pause()
                        return True, 1
                    elif cmd == APPCOMMAND_MEDIA_NEXTTRACK:
                        if hasattr(self.main_window, "media_next"):
                            self.main_window.media_next()
                        return True, 1
                    elif cmd == APPCOMMAND_MEDIA_PREVIOUSTRACK:
                        if hasattr(self.main_window, "media_prev"):
                            self.main_window.media_prev()
                        return True, 1
                    elif cmd == APPCOMMAND_MEDIA_STOP:
                        if hasattr(self.main_window, "media_stop"):
                            self.main_window.media_stop()
                        return True, 1

                # 3. WM_COMMAND (Taskbar Thumbnail Toolbar Buttons)
                elif msg.message == WM_COMMAND:
                    if self.taskbar_manager and self.taskbar_manager.handle_command(msg.wParam):
                        return True, 0

                # 4. Registered TaskbarButtonCreated Message
                elif self.taskbar_manager and self.taskbar_manager.wm_taskbar_created and msg.message == self.taskbar_manager.wm_taskbar_created:
                    self.taskbar_manager.init_buttons(msg.hwnd)
                    return True, 0

            except Exception as e:
                logger.debug(f"Error processing Windows media message: {e}")

        return False, 0


class MediaControllerManager:
    """Manages the lifecycle of application and native media filters, taskbar thumbnail toolbar, and hotkeys."""

    def __init__(self, main_window):
        self.main_window = main_window
        self.key_filter: Optional[GlobalMediaKeyFilter] = None
        self.native_filter: Optional[WindowsMediaNativeFilter] = None
        self.taskbar_manager: Optional[Any] = None
        self.registered_hotkeys: Dict[int, int] = {}
        self._sync_timer: Optional[QTimer] = None

    def setup(self):
        """Installs global key filter, taskbar thumbnail toolbar, and registers Windows media hotkeys."""
        app = QApplication.instance()
        if not app:
            return

        # Install application key filter
        self.key_filter = GlobalMediaKeyFilter(self.main_window)
        app.installEventFilter(self.key_filter)

        # On Windows, install native filter, taskbar thumbnail toolbar, and register global media hotkeys
        if sys.platform == "win32":
            try:
                from gui.taskbar_thumbnail import TaskbarThumbnailManager
                self.taskbar_manager = TaskbarThumbnailManager(self.main_window)
                self.taskbar_manager.setup()
            except Exception as e:
                logger.debug(f"TaskbarThumbnailManager init failed: {e}")
                self.taskbar_manager = None

            self.native_filter = WindowsMediaNativeFilter(self.main_window, self.taskbar_manager)
            app.installNativeEventFilter(self.native_filter)
            self._register_windows_hotkeys()

            # Schedule delayed initialization of thumbnail toolbar buttons once window is shown
            if self.taskbar_manager:
                QTimer.singleShot(800, self._delayed_init_taskbar)

            # Start playback state sync timer for taskbar buttons
            self._sync_timer = QTimer(self.main_window if isinstance(self.main_window, QWidget) else None)
            self._sync_timer.setInterval(1000)
            self._sync_timer.timeout.connect(self.sync_playback_state)
            self._sync_timer.start()

        logger.info("MediaControllerManager successfully initialized")

    def _delayed_init_taskbar(self):
        if self.taskbar_manager and self.main_window:
            try:
                hwnd = int(self.main_window.winId())
                if hwnd:
                    self.taskbar_manager.init_buttons(hwnd)
            except Exception as e:
                logger.debug(f"Delayed taskbar init: {e}")

    def set_playing(self, is_playing: bool):
        """Notifies the taskbar thumbnail manager of the latest playback state."""
        if self.taskbar_manager:
            self.taskbar_manager.update_playback_state(bool(is_playing))

    def sync_playback_state(self):
        """Queries the active player state and updates taskbar thumbnail buttons."""
        if not self.taskbar_manager:
            return

        # 1. Chromium WebStudioView
        if hasattr(self.main_window, "web_studio_view") and getattr(self.main_window.web_studio_view, "webview", None):
            wv = self.main_window.web_studio_view.webview
            if hasattr(wv, "page"):
                try:
                    wv.page().runJavaScript(
                        "(typeof window.getMiniPlayerState === 'function') ? (window.getMiniPlayerState().is_playing ? true : false) : false;",
                        self.set_playing
                    )
                except Exception:
                    pass
        # 2. Native PlayerBar fallback
        elif getattr(self.main_window, "player_bar", None):
            pb = self.main_window.player_bar
            is_playing = bool(hasattr(pb, "is_playing") and pb.is_playing)
            self.set_playing(is_playing)

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
        """Cleanly unregisters Windows hotkeys, stops timers, and removes installed filters."""
        if self._sync_timer:
            self._sync_timer.stop()
            self._sync_timer = None

        if self.taskbar_manager:
            self.taskbar_manager.cleanup()
            self.taskbar_manager = None

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
