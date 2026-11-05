"""
Windows Taskbar Thumbnail Toolbar Integration for Flacify.
Provides native interactive playback controls (⏮ Prev, ▶/⏸ Play/Pause, ⏭ Next)
in the Windows taskbar hover preview flyout via ITaskbarList3 (ThumbBarAddButtons).
"""

import sys
import logging
from typing import Optional, Dict

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QImage, QPainter, QColor

logger = logging.getLogger("gui.taskbar_thumbnail")

# Windows API Constants & Structures
if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes, Structure, byref, c_void_p, c_ulong, c_wchar, c_uint, WINFUNCTYPE, c_int, POINTER

    WM_COMMAND = 0x0111
    THBN_CLICKED = 0x1800

    THB_BITMAP = 0x0001
    THB_ICON = 0x0002
    THB_TOOLTIP = 0x0004
    THB_FLAGS = 0x0008

    THBF_ENABLED = 0x0000
    THBF_DISABLED = 0x0001
    THBF_DISMISSONCLICK = 0x0002
    THBF_NOBACKGROUND = 0x0004
    THBF_HIDDEN = 0x0008
    THBF_NONINTERACTIVE = 0x0010

    THB_PREV_ID = 1
    THB_PLAY_PAUSE_ID = 2
    THB_NEXT_ID = 3

    class GUID(Structure):
        _fields_ = [
            ("Data1", c_ulong),
            ("Data2", wintypes.WORD),
            ("Data3", wintypes.WORD),
            ("Data4", wintypes.BYTE * 8),
        ]

    CLSID_TaskbarList = GUID(
        0x56FDF344, 0xFD6D, 0x11D0,
        (wintypes.BYTE * 8)(0x95, 0x8A, 0x00, 0x60, 0x97, 0xC9, 0xA0, 0x90)
    )
    IID_ITaskbarList3 = GUID(
        0xEA1AFB91, 0x9E28, 0x4B86,
        (wintypes.BYTE * 8)(0x90, 0xE9, 0x9E, 0x9F, 0x8A, 0x5E, 0xEF, 0xAF)
    )

    class THUMBBUTTON(Structure):
        _fields_ = [
            ("dwMask", wintypes.DWORD),
            ("iId", wintypes.UINT),
            ("iBitmap", wintypes.UINT),
            ("hIcon", wintypes.HICON),
            ("szTip", c_wchar * 260),
            ("dwFlags", wintypes.DWORD),
        ]

    class BITMAPINFOHEADER(Structure):
        _fields_ = [
            ("biSize", wintypes.DWORD),
            ("biWidth", wintypes.LONG),
            ("biHeight", wintypes.LONG),
            ("biPlanes", wintypes.WORD),
            ("biBitCount", wintypes.WORD),
            ("biCompression", wintypes.DWORD),
            ("biSizeImage", wintypes.DWORD),
            ("biXPelsPerMeter", wintypes.LONG),
            ("biYPelsPerMeter", wintypes.LONG),
            ("biClrUsed", wintypes.DWORD),
            ("biClrImportant", wintypes.DWORD),
        ]

    class BITMAPINFO(Structure):
        _fields_ = [
            ("bmiHeader", BITMAPINFOHEADER),
            ("bmiColors", wintypes.DWORD * 3),
        ]

    class ICONINFO(Structure):
        _fields_ = [
            ("fIcon", wintypes.BOOL),
            ("xHotspot", wintypes.DWORD),
            ("yHotspot", wintypes.DWORD),
            ("hbmMask", wintypes.HBITMAP),
            ("hbmColor", wintypes.HBITMAP),
        ]


def _create_glyph_hicon(glyph: str) -> int:
    """Renders a crisp Unicode glyph into a native Windows 32-bit ARGB HICON."""
    if sys.platform != "win32":
        return 0

    img = QImage(24, 24, QImage.Format.Format_ARGB32)
    img.fill(QColor(0, 0, 0, 0))
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(QColor(255, 255, 255))
    font = p.font()
    font.setFamily("Segoe UI Symbol")
    font.setPointSize(11)
    font.setBold(True)
    p.setFont(font)
    p.drawText(img.rect(), Qt.AlignmentFlag.AlignCenter, glyph)
    p.end()

    w, h = img.width(), img.height()
    gdi32 = ctypes.windll.gdi32
    user32 = ctypes.windll.user32

    bmi = BITMAPINFO()
    bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.bmiHeader.biWidth = w
    bmi.bmiHeader.biHeight = -h
    bmi.bmiHeader.biPlanes = 1
    bmi.bmiHeader.biBitCount = 32
    bmi.bmiHeader.biCompression = 0

    bits = c_void_p()
    hdc = user32.GetDC(None)
    hbm_color = gdi32.CreateDIBSection(hdc, byref(bmi), 0, byref(bits), None, 0)
    user32.ReleaseDC(None, hdc)
    if not hbm_color or not bits.value:
        return 0

    ctypes.memmove(bits.value, int(img.constBits()), w * h * 4)
    hbm_mask = gdi32.CreateBitmap(w, h, 1, 1, None)

    ii = ICONINFO(True, 0, 0, hbm_mask, hbm_color)
    hicon = user32.CreateIconIndirect(byref(ii))
    gdi32.DeleteObject(hbm_color)
    gdi32.DeleteObject(hbm_mask)
    return hicon


class TaskbarThumbnailManager:
    """
    Manages the Windows Taskbar Thumbnail Toolbar for Flacify.
    Displays Previous, Play/Pause, and Next buttons when the user hovers over
    the Flacify icon in the Windows taskbar preview window.
    """

    def __init__(self, main_window):
        self.main_window = main_window
        self.taskbar: Optional[c_void_p] = None
        self._thumb_add = None
        self._thumb_update = None
        self._buttons_added = False
        self._is_playing = False
        self._icons: Dict[str, int] = {}
        self.wm_taskbar_created: int = 0

    def setup(self):
        """Initializes COM and registers taskbar window message listeners."""
        if sys.platform != "win32":
            return

        try:
            user32 = ctypes.windll.user32
            self.wm_taskbar_created = user32.RegisterWindowMessageW("TaskbarButtonCreated")

            ole32 = ctypes.oledll.ole32
            ole32.CoInitialize(None)
            self.taskbar = c_void_p()
            hr = ole32.CoCreateInstance(
                byref(CLSID_TaskbarList),
                None,
                1,  # CLSCTX_INPROC_SERVER
                byref(IID_ITaskbarList3),
                byref(self.taskbar),
            )
            if hr == 0 and self.taskbar.value:
                vtable = ctypes.cast(self.taskbar, POINTER(POINTER(c_void_p))).contents
                # Index 3: HrInit
                WINFUNCTYPE(c_int, c_void_p)(vtable[3])(self.taskbar)
                # Index 15: ThumbBarAddButtons
                self._thumb_add = WINFUNCTYPE(c_int, c_void_p, wintypes.HWND, wintypes.UINT, POINTER(THUMBBUTTON))(vtable[15])
                # Index 16: ThumbBarUpdateButtons
                self._thumb_update = WINFUNCTYPE(c_int, c_void_p, wintypes.HWND, wintypes.UINT, POINTER(THUMBBUTTON))(vtable[16])
                logger.info("ITaskbarList3 initialized for Taskbar Thumbnail Toolbar")
            else:
                logger.debug(f"CoCreateInstance for ITaskbarList3 returned {hex(hr & 0xFFFFFFFF)}")
        except Exception as e:
            logger.debug(f"Could not setup Windows taskbar thumbnail toolbar: {e}")

    def _get_icon(self, name: str) -> int:
        """Returns or creates a cached HICON handle for the requested glyph."""
        if name not in self._icons or not self._icons[name]:
            glyphs = {
                "prev": "⏮",
                "play": "▶",
                "pause": "⏸",
                "next": "⏭",
            }
            glyph = glyphs.get(name, "▶")
            self._icons[name] = _create_glyph_hicon(glyph)
        return self._icons.get(name, 0)

    def init_buttons(self, hwnd: int, reset: bool = False) -> bool:
        """
        Adds the thumbnail toolbar buttons to the taskbar button preview.
        Can only be called once per window lifecycle.
        """
        if sys.platform != "win32" or not self.taskbar or not self._thumb_add or not hwnd:
            return False
        if reset:
            self._buttons_added = False
        if self._buttons_added:
            return True

        try:
            buttons = (THUMBBUTTON * 3)()

            # Button 1: Previous Track
            buttons[0].dwMask = THB_ICON | THB_FLAGS | THB_TOOLTIP
            buttons[0].iId = THB_PREV_ID
            buttons[0].hIcon = self._get_icon("prev")
            buttons[0].szTip = "Previous Track"
            buttons[0].dwFlags = THBF_ENABLED

            # Button 2: Play / Pause
            buttons[1].dwMask = THB_ICON | THB_FLAGS | THB_TOOLTIP
            buttons[1].iId = THB_PLAY_PAUSE_ID
            buttons[1].hIcon = self._get_icon("pause" if self._is_playing else "play")
            buttons[1].szTip = "Pause" if self._is_playing else "Play"
            buttons[1].dwFlags = THBF_ENABLED

            # Button 3: Next Track
            buttons[2].dwMask = THB_ICON | THB_FLAGS | THB_TOOLTIP
            buttons[2].iId = THB_NEXT_ID
            buttons[2].hIcon = self._get_icon("next")
            buttons[2].szTip = "Next Track"
            buttons[2].dwFlags = THBF_ENABLED

            hr = self._thumb_add(self.taskbar, hwnd, 3, buttons)
            if hr == 0:
                self._buttons_added = True
                logger.info("Taskbar Thumbnail Toolbar buttons attached successfully")
                return True
            else:
                logger.debug(f"ThumbBarAddButtons returned {hex(hr & 0xFFFFFFFF)}")
                return False
        except Exception as e:
            logger.debug(f"Error initializing taskbar thumbnail buttons: {e}")
            return False

    def update_playback_state(self, is_playing: bool):
        """Updates the Play/Pause button icon and tooltip when playback state changes."""
        self._is_playing = is_playing
        if sys.platform != "win32" or not self.taskbar or not self._thumb_update:
            return

        hwnd = int(self.main_window.winId()) if self.main_window else 0
        if not hwnd:
            return

        # If buttons have not been successfully added yet, try adding them
        if not self._buttons_added:
            self.init_buttons(hwnd)
            return

        try:
            btn = THUMBBUTTON()
            btn.dwMask = THB_ICON | THB_FLAGS | THB_TOOLTIP
            btn.iId = THB_PLAY_PAUSE_ID
            btn.hIcon = self._get_icon("pause" if is_playing else "play")
            btn.szTip = "Pause" if is_playing else "Play"
            btn.dwFlags = THBF_ENABLED

            arr = (THUMBBUTTON * 1)(btn)
            hr = self._thumb_update(self.taskbar, hwnd, 1, arr)
            if hr != 0:
                logger.debug(f"ThumbBarUpdateButtons returned {hex(hr & 0xFFFFFFFF)}")
        except Exception as e:
            logger.debug(f"Error updating taskbar thumbnail button state: {e}")

    def handle_command(self, wparam: int) -> bool:
        """
        Handles WM_COMMAND messages when a thumbnail button is clicked.
        Returns True if the command was processed.
        """
        if sys.platform != "win32":
            return False

        notification = (wparam >> 16) & 0xFFFF
        button_id = wparam & 0xFFFF

        if notification == THBN_CLICKED:
            if button_id == THB_PREV_ID:
                if hasattr(self.main_window, "media_prev"):
                    self.main_window.media_prev()
                return True
            elif button_id == THB_PLAY_PAUSE_ID:
                if hasattr(self.main_window, "media_play_pause"):
                    self.main_window.media_play_pause()
                return True
            elif button_id == THB_NEXT_ID:
                if hasattr(self.main_window, "media_next"):
                    self.main_window.media_next()
                return True

        return False

    def cleanup(self):
        """Destroys cached HICON handles and releases taskbar interface."""
        if sys.platform == "win32":
            user32 = ctypes.windll.user32
            for icon in self._icons.values():
                if icon:
                    try:
                        user32.DestroyIcon(icon)
                    except Exception:
                        pass
            self._icons.clear()
            if self.taskbar and getattr(self.taskbar, "value", None):
                try:
                    vtable = ctypes.cast(self.taskbar, POINTER(POINTER(c_void_p))).contents
                    WINFUNCTYPE(c_ulong, c_void_p)(vtable[2])(self.taskbar)
                except Exception:
                    pass
            self.taskbar = None
            self._thumb_add = None
            self._thumb_update = None
            self._buttons_added = False

