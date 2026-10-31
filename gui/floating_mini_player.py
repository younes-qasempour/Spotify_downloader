import logging
import os
from typing import Optional, Any, Dict

from PyQt6.QtCore import Qt, QPoint, QTimer, pyqtSignal, QSize
from PyQt6.QtGui import (
    QColor, QFont, QIcon, QImage, QPainter, QPainterPath, QPixmap, QPen
)
from PyQt6.QtWidgets import (
    QWidget, QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QSlider, QSizePolicy
)

logger = logging.getLogger("gui.floating_mini_player")


def format_ms(ms: int) -> str:
    """Format milliseconds to M:SS."""
    if not ms or ms < 0:
        return "0:00"
    total_sec = int(ms // 1000)
    minutes = total_sec // 60
    seconds = total_sec % 60
    return f"{minutes}:{seconds:02d}"


class FloatingSeekSlider(QSlider):
    """Custom seek slider with instant click-to-seek and smooth drag feedback."""

    sig_seek_requested = pyqtSignal(int)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.is_scrubbing = False
        self.setRange(0, 1000)
        self.setValue(0)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("""
            QSlider::groove:horizontal {
                height: 4px;
                background: #27272a;
                border-radius: 2px;
            }
            QSlider::sub-page:horizontal {
                background: #1ed760;
                border-radius: 2px;
            }
            QSlider::handle:horizontal {
                background: #ffffff;
                width: 10px;
                height: 10px;
                margin: -3px 0;
                border-radius: 5px;
            }
            QSlider::handle:horizontal:hover {
                background: #1ed760;
                transform: scale(1.2);
            }
        """)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.is_scrubbing = True
            pos_ratio = max(0.0, min(1.0, event.position().x() / max(1, self.width())))
            val = int(pos_ratio * self.maximum())
            self.setValue(val)
            self.sig_seek_requested.emit(val)
            event.accept()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.is_scrubbing = False
            self.sig_seek_requested.emit(self.value())
            event.accept()
        super().mouseReleaseEvent(event)


class FloatingMiniPlayerWindow(QWidget):
    """
    True OS-Level Floating Mini-Player / PiP Window.
    Floats freely on top of games, browsers, and desktop apps.
    Features:
      - Always-on-top toggle (pinned/unpinned)
      - Frameless sleek dark glassmorphic Spotify design
      - Album artwork with smooth rounded corners
      - Track title & artist
      - LIVE glowing synchronized karaoke lyrics line
      - Interactive seek bar and duration counter
      - Previous, Play/Pause, Next controls
      - Volume slider & mute
      - Restore main Flacify window button
    """

    def __init__(self, web_studio_view: Optional[Any] = None, parent: Optional[QWidget] = None):
        # Top-level window outside main app
        super().__init__(parent)
        self.web_studio_view = web_studio_view
        self.main_window: Optional[QWidget] = None
        self._is_pinned = True
        self._drag_pos = QPoint()
        self._current_cover_key = ""
        self._cached_pixmap: Optional[QPixmap] = None
        self._is_seeking = False
        self._last_title = ""
        self._last_artist = ""

        self._init_window_flags()
        self._init_ui()

        # Polling sync timer when visible
        self.sync_timer = QTimer(self)
        self.sync_timer.setInterval(250)
        self.sync_timer.timeout.connect(self.request_state_sync)

    def set_main_window(self, win: QWidget):
        self.main_window = win

    def _init_window_flags(self):
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setWindowTitle("Flacify Mini Player")
        self.setFixedSize(390, 168)

    def _init_ui(self):
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # Main styled card container
        self.card = QFrame(self)
        self.card.setObjectName("mini_card")
        self.card.setStyleSheet("""
            QFrame#mini_card {
                background-color: #121216;
                border: 1px solid #282834;
                border-radius: 14px;
            }
        """)
        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(12, 10, 12, 12)
        card_layout.setSpacing(8)

        # -------------------------------------------------------------
        # 1. Header Bar: Brand + Controls (Pin, Restore, Close)
        # -------------------------------------------------------------
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(6)

        # Glowing dot + title
        dot = QLabel("●", self.card)
        dot.setStyleSheet("color: #1ed760; font-size: 10px; margin-right: 2px;")
        header.addWidget(dot)

        brand_lbl = QLabel("FLACIFY MINI", self.card)
        brand_lbl.setStyleSheet("""
            color: #94a3b8;
            font-size: 10px;
            font-weight: 700;
            letter-spacing: 1px;
            font-family: 'Segoe UI', system-ui, sans-serif;
        """)
        header.addWidget(brand_lbl)
        header.addStretch(1)

        # Pin / Always on Top button
        self.btn_pin = QPushButton("📌", self.card)
        self.btn_pin.setToolTip("Always on Top (Keep pinned over games & apps)")
        self.btn_pin.setFixedSize(22, 22)
        self.btn_pin.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_pin.setStyleSheet(self._get_pin_style(True))
        self.btn_pin.clicked.connect(self._toggle_pinned)
        header.addWidget(self.btn_pin)

        # Restore / Focus Main Window button
        self.btn_restore = QPushButton("⤢", self.card)
        self.btn_restore.setToolTip("Restore & Bring Flacify Studio to Front")
        self.btn_restore.setFixedSize(22, 22)
        self.btn_restore.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_restore.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: none;
                color: #94a3b8;
                font-size: 14px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background: #282834;
                color: #ffffff;
            }
        """)
        self.btn_restore.clicked.connect(self._restore_main_window)
        header.addWidget(self.btn_restore)

        # Close button
        self.btn_close = QPushButton("✕", self.card)
        self.btn_close.setToolTip("Close Mini-Player")
        self.btn_close.setFixedSize(22, 22)
        self.btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_close.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: none;
                color: #94a3b8;
                font-size: 11px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background: #e11d48;
                color: #ffffff;
            }
        """)
        self.btn_close.clicked.connect(self.hide_mini_player)
        header.addWidget(self.btn_close)

        card_layout.addLayout(header)

        # -------------------------------------------------------------
        # 2. Track Info & Live Lyrics Row
        # -------------------------------------------------------------
        mid_row = QHBoxLayout()
        mid_row.setContentsMargins(0, 0, 0, 0)
        mid_row.setSpacing(10)

        # Cover Art Thumbnail
        self.lbl_cover = QLabel(self.card)
        self.lbl_cover.setFixedSize(60, 60)
        self.lbl_cover.setStyleSheet("""
            background-color: #1a1a22;
            border-radius: 8px;
            border: 1px solid #282834;
        """)
        self.lbl_cover.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._set_default_cover()
        mid_row.addWidget(self.lbl_cover)

        # Details Column
        info_col = QVBoxLayout()
        info_col.setContentsMargins(0, 0, 0, 0)
        info_col.setSpacing(2)

        self.lbl_title = QLabel("Ready to Play", self.card)
        self.lbl_title.setStyleSheet("""
            color: #ffffff;
            font-size: 13px;
            font-weight: 700;
            font-family: 'Segoe UI', system-ui, sans-serif;
        """)
        info_col.addWidget(self.lbl_title)

        self.lbl_artist = QLabel("Select any song in Flacify", self.card)
        self.lbl_artist.setStyleSheet("""
            color: #94a3b8;
            font-size: 11px;
            font-family: 'Segoe UI', system-ui, sans-serif;
        """)
        info_col.addWidget(self.lbl_artist)

        # Live Synchronized Lyrics ticker
        self.lbl_lyrics = QLabel("♫ Synchronized Karaoke Studio ♫", self.card)
        self.lbl_lyrics.setStyleSheet("""
            color: #1ed760;
            font-size: 11px;
            font-weight: 600;
            font-family: 'Segoe UI', system-ui, sans-serif;
        """)
        info_col.addWidget(self.lbl_lyrics)

        mid_row.addLayout(info_col, 1)
        card_layout.addLayout(mid_row)

        # -------------------------------------------------------------
        # 3. Interactive Seek & Progress Bar
        # -------------------------------------------------------------
        progress_row = QHBoxLayout()
        progress_row.setContentsMargins(0, 0, 0, 0)
        progress_row.setSpacing(6)

        self.lbl_cur_time = QLabel("0:00", self.card)
        self.lbl_cur_time.setStyleSheet("color: #71717a; font-size: 10px; font-family: monospace;")
        progress_row.addWidget(self.lbl_cur_time)

        self.seek_slider = FloatingSeekSlider(self.card)
        self.seek_slider.sig_seek_requested.connect(self._on_seek_requested)
        progress_row.addWidget(self.seek_slider, 1)

        self.lbl_dur_time = QLabel("0:00", self.card)
        self.lbl_dur_time.setStyleSheet("color: #71717a; font-size: 10px; font-family: monospace;")
        progress_row.addWidget(self.lbl_dur_time)

        card_layout.addLayout(progress_row)

        # -------------------------------------------------------------
        # 4. Transport Controls & Volume
        # -------------------------------------------------------------
        ctrl_row = QHBoxLayout()
        ctrl_row.setContentsMargins(0, 0, 0, 0)
        ctrl_row.setSpacing(8)

        # Previous
        self.btn_prev = QPushButton("⏮", self.card)
        self.btn_prev.setFixedSize(26, 26)
        self.btn_prev.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_prev.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: none;
                color: #cbd5e1;
                font-size: 13px;
                border-radius: 13px;
            }
            QPushButton:hover {
                background: #282834;
                color: #ffffff;
            }
        """)
        self.btn_prev.clicked.connect(self._on_prev_clicked)
        ctrl_row.addWidget(self.btn_prev)

        # Play / Pause (Circular emerald)
        self.btn_play = QPushButton("▶", self.card)
        self.btn_play.setFixedSize(30, 30)
        self.btn_play.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_play.setStyleSheet("""
            QPushButton {
                background-color: #1ed760;
                color: #000000;
                border: none;
                border-radius: 15px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #22e668;
                transform: scale(1.06);
            }
        """)
        self.btn_play.clicked.connect(self._on_play_pause_clicked)
        ctrl_row.addWidget(self.btn_play)

        # Next
        self.btn_next = QPushButton("⏭", self.card)
        self.btn_next.setFixedSize(26, 26)
        self.btn_next.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_next.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: none;
                color: #cbd5e1;
                font-size: 13px;
                border-radius: 13px;
            }
            QPushButton:hover {
                background: #282834;
                color: #ffffff;
            }
        """)
        self.btn_next.clicked.connect(self._on_next_clicked)
        ctrl_row.addWidget(self.btn_next)

        ctrl_row.addStretch(1)

        # Volume icon / mute toggle
        self.btn_vol = QPushButton("🔊", self.card)
        self.btn_vol.setFixedSize(22, 22)
        self.btn_vol.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_vol.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: none;
                color: #94a3b8;
                font-size: 11px;
            }
            QPushButton:hover {
                color: #ffffff;
            }
        """)
        self.btn_vol.clicked.connect(self._on_mute_clicked)
        ctrl_row.addWidget(self.btn_vol)

        # Compact Volume slider
        self.vol_slider = QSlider(Qt.Orientation.Horizontal, self.card)
        self.vol_slider.setRange(0, 100)
        self.vol_slider.setValue(100)
        self.vol_slider.setFixedWidth(64)
        self.vol_slider.setCursor(Qt.CursorShape.PointingHandCursor)
        self.vol_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                height: 3px;
                background: #27272a;
                border-radius: 1px;
            }
            QSlider::sub-page:horizontal {
                background: #94a3b8;
                border-radius: 1px;
            }
            QSlider::handle:horizontal {
                background: #ffffff;
                width: 8px;
                height: 8px;
                margin: -2.5px 0;
                border-radius: 4px;
            }
        """)
        self.vol_slider.valueChanged.connect(self._on_vol_changed)
        ctrl_row.addWidget(self.vol_slider)

        card_layout.addLayout(ctrl_row)
        root_layout.addWidget(self.card)

    def _get_pin_style(self, active: bool) -> str:
        if active:
            return """
                QPushButton {
                    background: rgba(30, 215, 96, 0.18);
                    border: 1px solid #1ed760;
                    color: #1ed760;
                    font-size: 11px;
                    border-radius: 4px;
                }
                QPushButton:hover {
                    background: rgba(30, 215, 96, 0.3);
                }
            """
        return """
            QPushButton {
                background: transparent;
                border: none;
                color: #64748b;
                font-size: 11px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background: #282834;
                color: #ffffff;
            }
        """

    def _set_default_cover(self):
        pix = QPixmap(60, 60)
        pix.fill(QColor("#1a1a22"))
        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QColor("#1ed760"))
        font = p.font()
        font.setPointSize(16)
        p.setFont(font)
        p.drawText(pix.rect(), Qt.AlignmentFlag.AlignCenter, "♫")
        p.end()
        self.lbl_cover.setPixmap(pix)

    # -----------------------------------------------------------------
    # Mouse Dragging Across Desktops & Multi-Monitors
    # -----------------------------------------------------------------
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton and hasattr(self, "_drag_pos"):
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()
        super().mouseMoveEvent(event)

    # -----------------------------------------------------------------
    # Visibility and Always-On-Top Control
    # -----------------------------------------------------------------
    def toggle_visibility(self):
        if self.isVisible():
            self.hide_mini_player()
        else:
            self.show_mini_player()

    def show_mini_player(self):
        # Position nicely at bottom-right of screen if first time
        if self.x() == 0 and self.y() == 0:
            screen = self.screen() or (self.main_window.screen() if self.main_window else None)
            if screen:
                geom = screen.availableGeometry()
                self.move(geom.right() - self.width() - 30, geom.bottom() - self.height() - 40)
        self.show()
        self.raise_()
        self.activateWindow()
        self.sync_timer.start()
        self.request_state_sync()

    def hide_mini_player(self):
        self.sync_timer.stop()
        self.hide()

    def _toggle_pinned(self):
        self._is_pinned = not self._is_pinned
        pos = self.pos()
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, self._is_pinned)
        self.btn_pin.setStyleSheet(self._get_pin_style(self._is_pinned))
        self.show()
        self.move(pos)

    def _restore_main_window(self):
        if self.main_window:
            self.main_window.showNormal()
            self.main_window.activateWindow()
            self.main_window.raise_()

    # -----------------------------------------------------------------
    # State Synchronization via JavaScript Bridge
    # -----------------------------------------------------------------
    def request_state_sync(self):
        if not self.isVisible():
            return
        if self.web_studio_view and getattr(self.web_studio_view, "webview", None):
            wv = self.web_studio_view.webview
            if hasattr(wv, "page"):
                wv.page().runJavaScript(
                    "if (typeof window.getMiniPlayerState === 'function') window.getMiniPlayerState();",
                    self.update_state
                )

    def update_state(self, data: Optional[Dict[str, Any]]):
        if not isinstance(data, dict):
            return

        # 1. Track Info
        title = data.get("title") or "No Track Playing"
        artist = data.get("artist") or "Select a song in Flacify"
        if title != self._last_title:
            self._last_title = title
            # Truncate with ellipsis if needed
            fm = self.lbl_title.fontMetrics()
            elided = fm.elidedText(title, Qt.TextElideMode.ElideRight, 270)
            self.lbl_title.setText(elided)
            self.lbl_title.setToolTip(title)

        if artist != self._last_artist:
            self._last_artist = artist
            fm = self.lbl_artist.fontMetrics()
            elided = fm.elidedText(artist, Qt.TextElideMode.ElideRight, 270)
            self.lbl_artist.setText(elided)
            self.lbl_artist.setToolTip(artist)

        # 2. Cover Art
        cover_key = str(data.get("cover_key") or "")
        if cover_key != self._current_cover_key:
            self._current_cover_key = cover_key
            self._load_cover_image(cover_key)

        # 3. Play / Pause Button State
        is_playing = bool(data.get("is_playing", False))
        self.btn_play.setText("⏸" if is_playing else "▶")

        # 4. Progress Bar and Times
        pos_ms = int(data.get("position_ms", 0))
        dur_ms = int(data.get("duration_ms", 0))
        if not self.seek_slider.is_scrubbing:
            self.seek_slider.setMaximum(max(dur_ms, 1))
            self.seek_slider.setValue(pos_ms)
            self.lbl_cur_time.setText(format_ms(pos_ms))
            self.lbl_dur_time.setText(format_ms(dur_ms))

        # 5. Live Synchronized Karaoke Lyric
        lyric = str(data.get("lyric") or "").strip()
        if lyric:
            fm = self.lbl_lyrics.fontMetrics()
            elided_lyric = fm.elidedText(lyric, Qt.TextElideMode.ElideRight, 270)
            self.lbl_lyrics.setText(elided_lyric)
            self.lbl_lyrics.setStyleSheet("color: #1ed760; font-size: 11px; font-weight: 600;")
            self.lbl_lyrics.setToolTip(lyric)
        else:
            self.lbl_lyrics.setText("♫ Flacify High-Fidelity Audio ♫")
            self.lbl_lyrics.setStyleSheet("color: #64748b; font-size: 11px;")
            self.lbl_lyrics.setToolTip("")

        # 6. Volume Slider
        vol = int(data.get("volume", 100))
        if not self.vol_slider.isSliderDown():
            self.vol_slider.setValue(vol)
            self.btn_vol.setText("🔇" if vol == 0 else "🔊")

    def _load_cover_image(self, cover_key: str):
        if not cover_key or not self.web_studio_view or not getattr(self.web_studio_view, "web_server", None):
            self._set_default_cover()
            return

        try:
            state = self.web_studio_view.web_server.state
            data, mime = state.get_cover_bytes(cover_key)
            if data:
                qimg = QImage.fromData(data)
                if not qimg.isNull():
                    scaled = qimg.scaled(
                        60, 60,
                        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                        Qt.TransformationMode.SmoothTransformation
                    )
                    rounded = QPixmap(60, 60)
                    rounded.fill(Qt.GlobalColor.transparent)
                    p = QPainter(rounded)
                    p.setRenderHint(QPainter.RenderHint.Antialiasing)
                    clip_path = QPainterPath()
                    clip_path.addRoundedRect(0, 0, 60, 60, 8, 8)
                    p.setClipPath(clip_path)
                    p.drawImage(0, 0, scaled)
                    p.end()
                    self.lbl_cover.setPixmap(rounded)
                    return
        except Exception as e:
            logger.debug(f"Cover loading exception: {e}")

        self._set_default_cover()

    # -----------------------------------------------------------------
    # User Transport Control Callbacks
    # -----------------------------------------------------------------
    def _on_play_pause_clicked(self):
        if self.web_studio_view and getattr(self.web_studio_view, "webview", None):
            self.web_studio_view.webview.page().runJavaScript(
                "if (typeof window.triggerMediaPlayPause === 'function') window.triggerMediaPlayPause();"
            )

    def _on_prev_clicked(self):
        if self.web_studio_view and getattr(self.web_studio_view, "webview", None):
            self.web_studio_view.webview.page().runJavaScript(
                "if (typeof window.triggerMediaPrev === 'function') window.triggerMediaPrev();"
            )

    def _on_next_clicked(self):
        if self.web_studio_view and getattr(self.web_studio_view, "webview", None):
            self.web_studio_view.webview.page().runJavaScript(
                "if (typeof window.triggerMediaNext === 'function') window.triggerMediaNext();"
            )

    def _on_seek_requested(self, ms: int):
        if self.web_studio_view and getattr(self.web_studio_view, "webview", None):
            self.web_studio_view.webview.page().runJavaScript(
                f"if (typeof window.triggerMediaSeekTo === 'function') window.triggerMediaSeekTo({ms});"
            )

    def _on_vol_changed(self, val: int):
        self.btn_vol.setText("🔇" if val == 0 else "🔊")
        if self.web_studio_view and getattr(self.web_studio_view, "webview", None):
            self.web_studio_view.webview.page().runJavaScript(
                f"if (typeof window.triggerMediaSetVolume === 'function') window.triggerMediaSetVolume({val});"
            )

    def _on_mute_clicked(self):
        if self.web_studio_view and getattr(self.web_studio_view, "webview", None):
            self.web_studio_view.webview.page().runJavaScript(
                "if (typeof window.triggerMediaMute === 'function') window.triggerMediaMute();"
            )

