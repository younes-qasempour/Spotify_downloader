import logging
import os
from typing import Optional, Any, Dict

from PyQt6.QtCore import Qt, QPoint, QRect, QTimer, pyqtSignal, QSize, QEvent
from PyQt6.QtGui import (
    QColor, QFont, QIcon, QImage, QPainter, QPainterPath, QPixmap, QPen
)
from PyQt6.QtWidgets import (
    QWidget, QFrame, QVBoxLayout, QHBoxLayout, QBoxLayout, QLabel,
    QPushButton, QSlider, QSizePolicy, QSizeGrip
)

from core.config import config

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
    True OS-Level Floating Mini-Player / PiP Window modeled after the Spotify Miniplayer.
    Floats freely on top of games, browsers, and desktop apps.
    Fully resizable from ultra-compact micro-bar (200x52) to large high-res album studio (850x850).
    Features:
      - Multi-direction edge/corner resizing + bottom-right sleek grip handle
      - Adaptive 3-tier layout (Compact Bar, Standard Studio, Large Cover Art)
      - Always-on-top toggle (pinned/unpinned)
      - Frameless sleek dark glassmorphic Spotify design
      - Dynamically scaled album artwork with smooth anti-aliased rounded corners
      - Real-time text eliding for track title & artist
      - LIVE glowing synchronized karaoke lyrics line
      - Interactive seek bar and duration counter
      - Previous, Play/Pause, Next controls
      - Volume slider & mute
      - Restore main Flacify window button
      - Size memory across sessions
    """

    RESIZE_BORDER = 8

    def __init__(self, web_studio_view: Optional[Any] = None, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.web_studio_view = web_studio_view
        self.main_window: Optional[QWidget] = None
        self._is_pinned = True
        self._drag_pos = QPoint()
        self._current_cover_key = ""
        self._cached_qimage: Optional[QImage] = None
        self._is_seeking = False
        self._last_title = ""
        self._last_artist = ""
        self._last_lyric = ""
        self._active_mode = "standard"

        # Edge resizing state
        self._resizing = False
        self._resize_edge = None
        self._press_pos = QPoint()
        self._start_geom = QRect()

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
        self.setMouseTracking(True)
        self.setMinimumSize(200, 52)
        self.setMaximumSize(850, 850)

        # Restore user's preferred mini player size or default to 380x168
        saved_w = int(config.get("gui.mini_player_w", 380))
        saved_h = int(config.get("gui.mini_player_h", 168))
        self.resize(max(200, min(850, saved_w)), max(52, min(850, saved_h)))

    def _init_ui(self):
        self.root_layout = QVBoxLayout(self)
        self.root_layout.setContentsMargins(0, 0, 0, 0)
        self.root_layout.setSpacing(0)

        # Main styled card container
        self.card = QFrame(self)
        self.card.setObjectName("mini_card")
        self.card.setMouseTracking(True)
        self.card.installEventFilter(self)
        self.card.setStyleSheet("""
            QFrame#mini_card {
                background-color: #121216;
                border: 1px solid #282834;
                border-radius: 14px;
            }
        """)

        self.card_layout = QVBoxLayout(self.card)
        self.card_layout.setContentsMargins(12, 10, 12, 12)
        self.card_layout.setSpacing(6)

        # -------------------------------------------------------------
        # 1. Header Bar: Brand + Controls (Pin, Restore, Close)
        # -------------------------------------------------------------
        self.header_widget = QWidget(self.card)
        self.header_widget.setMouseTracking(True)
        self.header_layout = QHBoxLayout(self.header_widget)
        self.header_layout.setContentsMargins(0, 0, 0, 0)
        self.header_layout.setSpacing(6)

        # Glowing dot + title
        self.dot = QLabel("●", self.header_widget)
        self.dot.setStyleSheet("color: #1ed760; font-size: 10px; margin-right: 2px;")
        self.header_layout.addWidget(self.dot)

        self.brand_lbl = QLabel("FLACIFY MINI", self.header_widget)
        self.brand_lbl.setStyleSheet("""
            color: #94a3b8;
            font-size: 10px;
            font-weight: 700;
            letter-spacing: 1px;
            font-family: 'Segoe UI', system-ui, sans-serif;
        """)
        self.header_layout.addWidget(self.brand_lbl)
        self.header_layout.addStretch(1)

        # Pin / Always on Top button
        self.btn_pin = QPushButton("📌", self.header_widget)
        self.btn_pin.setToolTip("Always on Top (Keep pinned over games & apps)")
        self.btn_pin.setFixedSize(22, 22)
        self.btn_pin.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_pin.setStyleSheet(self._get_pin_style(True))
        self.btn_pin.clicked.connect(self._toggle_pinned)
        self.header_layout.addWidget(self.btn_pin)

        # Restore / Focus Main Window button
        self.btn_restore = QPushButton("⤢", self.header_widget)
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
        self.header_layout.addWidget(self.btn_restore)

        # Close button
        self.btn_close = QPushButton("✕", self.header_widget)
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
        self.header_layout.addWidget(self.btn_close)

        self.card_layout.addWidget(self.header_widget)

        # -------------------------------------------------------------
        # 2. Track Info & Cover Area
        # -------------------------------------------------------------
        self.mid_row = QWidget(self.card)
        self.mid_row.setMouseTracking(True)
        self.mid_layout = QBoxLayout(QBoxLayout.Direction.LeftToRight, self.mid_row)
        self.mid_layout.setContentsMargins(0, 0, 0, 0)
        self.mid_layout.setSpacing(10)

        # Cover Art Thumbnail / Large Display
        self.lbl_cover = QLabel(self.mid_row)
        self.lbl_cover.setFixedSize(60, 60)
        self.lbl_cover.setStyleSheet("""
            background-color: #1a1a22;
            border-radius: 8px;
            border: 1px solid #282834;
        """)
        self.lbl_cover.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.mid_layout.addWidget(self.lbl_cover)

        # Details Column
        self.info_col = QWidget(self.mid_row)
        self.info_col.setMouseTracking(True)
        self.info_layout = QVBoxLayout(self.info_col)
        self.info_layout.setContentsMargins(0, 0, 0, 0)
        self.info_layout.setSpacing(2)

        self.lbl_title = QLabel("Ready to Play", self.info_col)
        self.lbl_title.setStyleSheet("""
            color: #ffffff;
            font-size: 13px;
            font-weight: 700;
            font-family: 'Segoe UI', system-ui, sans-serif;
        """)
        self.info_layout.addWidget(self.lbl_title)

        self.lbl_artist = QLabel("Select any song in Flacify", self.info_col)
        self.lbl_artist.setStyleSheet("""
            color: #94a3b8;
            font-size: 11px;
            font-family: 'Segoe UI', system-ui, sans-serif;
        """)
        self.info_layout.addWidget(self.lbl_artist)

        # Live Synchronized Lyrics ticker
        self.lbl_lyrics = QLabel("♫ Synchronized Karaoke Studio ♫", self.info_col)
        self.lbl_lyrics.setStyleSheet("""
            color: #1ed760;
            font-size: 11px;
            font-weight: 600;
            font-family: 'Segoe UI', system-ui, sans-serif;
        """)
        self.info_layout.addWidget(self.lbl_lyrics)

        self.mid_layout.addWidget(self.info_col, 1)
        self.card_layout.addWidget(self.mid_row)

        # -------------------------------------------------------------
        # 3. Interactive Seek & Progress Bar
        # -------------------------------------------------------------
        self.progress_row = QWidget(self.card)
        self.progress_row.setMouseTracking(True)
        self.progress_layout = QHBoxLayout(self.progress_row)
        self.progress_layout.setContentsMargins(0, 0, 0, 0)
        self.progress_layout.setSpacing(6)

        self.lbl_cur_time = QLabel("0:00", self.progress_row)
        self.lbl_cur_time.setStyleSheet("color: #71717a; font-size: 10px; font-family: monospace;")
        self.progress_layout.addWidget(self.lbl_cur_time)

        self.seek_slider = FloatingSeekSlider(self.progress_row)
        self.seek_slider.sig_seek_requested.connect(self._on_seek_requested)
        self.progress_layout.addWidget(self.seek_slider, 1)

        self.lbl_dur_time = QLabel("0:00", self.progress_row)
        self.lbl_dur_time.setStyleSheet("color: #71717a; font-size: 10px; font-family: monospace;")
        self.progress_layout.addWidget(self.lbl_dur_time)

        self.card_layout.addWidget(self.progress_row)

        # -------------------------------------------------------------
        # 4. Transport Controls & Volume
        # -------------------------------------------------------------
        self.ctrl_row = QWidget(self.card)
        self.ctrl_row.setMouseTracking(True)
        self.ctrl_layout = QHBoxLayout(self.ctrl_row)
        self.ctrl_layout.setContentsMargins(0, 0, 0, 0)
        self.ctrl_layout.setSpacing(8)

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
        self.ctrl_layout.addWidget(self.btn_prev)

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
        self.ctrl_layout.addWidget(self.btn_play)

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
        self.ctrl_layout.addWidget(self.btn_next)

        self.ctrl_stretch = self.ctrl_layout.addStretch(1)

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
        self.ctrl_layout.addWidget(self.btn_vol)

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
        self.ctrl_layout.addWidget(self.vol_slider)

        self.card_layout.addWidget(self.ctrl_row)
        self.root_layout.addWidget(self.card)

        # Bottom-right resize grip indicator
        self.size_grip = QSizeGrip(self)
        self.size_grip.setFixedSize(14, 14)
        self.size_grip.setStyleSheet("background: transparent;")

        self._render_cover()
        self._update_responsive_layout(self.width(), self.height())

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

    # -----------------------------------------------------------------
    # Cover Artwork Rendering
    # -----------------------------------------------------------------
    def _render_cover(self):
        w = max(32, self.lbl_cover.width())
        h = max(32, self.lbl_cover.height())
        radius = 8 if w >= 50 else 6

        if self._cached_qimage and not self._cached_qimage.isNull():
            scaled = self._cached_qimage.scaled(
                w, h,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation
            )
            pix = QPixmap(w, h)
            pix.fill(Qt.GlobalColor.transparent)
            p = QPainter(pix)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            clip_path = QPainterPath()
            clip_path.addRoundedRect(0, 0, w, h, radius, radius)
            p.setClipPath(clip_path)
            p.drawImage(0, 0, scaled)
            p.end()
            self.lbl_cover.setPixmap(pix)
        else:
            pix = QPixmap(w, h)
            pix.fill(QColor("#1a1a22"))
            p = QPainter(pix)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            clip_path = QPainterPath()
            clip_path.addRoundedRect(0, 0, w, h, radius, radius)
            p.setClipPath(clip_path)
            p.fillPath(clip_path, QColor("#1a1a22"))
            p.setPen(QColor("#1ed760"))
            font = p.font()
            font.setPointSize(max(10, int(w * 0.28)))
            p.setFont(font)
            p.drawText(pix.rect(), Qt.AlignmentFlag.AlignCenter, "♫")
            p.end()
            self.lbl_cover.setPixmap(pix)

    def _set_default_cover(self):
        self._cached_qimage = None
        self._render_cover()

    # -----------------------------------------------------------------
    # Responsive Spotify-Style Layout Adaptation
    # -----------------------------------------------------------------
    def resize(self, *args):
        super().resize(*args)
        if hasattr(self, "card") and hasattr(self, "header_widget"):
            self._update_responsive_layout(self.width(), self.height())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Position size grip at bottom-right
        self.size_grip.move(
            self.width() - self.size_grip.width() - 2,
            self.height() - self.size_grip.height() - 2
        )
        self._update_responsive_layout(self.width(), self.height())

    def _update_responsive_layout(self, w: int, h: int):
        # 3 distinct modes:
        # 1. Compact: h < 110 (mini single-bar strip)
        # 2. Large: h >= 240 and w >= 260 (large artwork album view)
        # 3. Standard: 110 <= h < 240 (classic card)
        target_mode = "compact" if h < 110 else ("large" if (h >= 240 and w >= 260) else "standard")
        if target_mode != self._active_mode:
            self._switch_mode(target_mode)

        # Dynamic cover size
        if self._active_mode == "compact":
            cov_size = 38
        elif self._active_mode == "large":
            cov_size = max(80, min(w - 60, h - 180, 260))
        else:
            cov_size = 58

        if self.lbl_cover.width() != cov_size:
            self.lbl_cover.setFixedSize(cov_size, cov_size)
            self._render_cover()

        # Update text eliding with available width
        self._reapply_elided_text()

    def _switch_mode(self, mode: str):
        self._active_mode = mode

        if mode == "compact":
            # Micro-bar layout: Single horizontal row
            self.header_widget.hide()
            self.lbl_lyrics.hide()
            self.progress_row.hide()
            self.ctrl_row.hide()

            self.mid_layout.setDirection(QBoxLayout.Direction.LeftToRight)
            self.mid_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)
            self.info_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

            # Insert controls into mid_layout
            self.mid_layout.addWidget(self.btn_prev)
            self.mid_layout.addWidget(self.btn_play)
            self.mid_layout.addWidget(self.btn_next)
            self.mid_layout.addWidget(self.btn_pin)
            self.mid_layout.addWidget(self.btn_close)

            self.btn_prev.setVisible(self.width() >= 260)
            self.btn_next.setVisible(self.width() >= 260)
            self.btn_pin.setVisible(self.width() >= 300)

            self.lbl_title.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            self.lbl_artist.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            self.card_layout.setContentsMargins(8, 4, 8, 4)
            self.card_layout.setSpacing(2)

        elif mode == "standard":
            # Classic Standard card layout
            self.header_widget.show()
            self.lbl_lyrics.show()
            self.progress_row.show()
            self.ctrl_row.show()
            self.btn_prev.show()
            self.btn_next.show()
            self.btn_pin.show()
            self.btn_vol.show()
            self.vol_slider.show()

            self.header_layout.addWidget(self.btn_pin)
            self.header_layout.addWidget(self.btn_restore)
            self.header_layout.addWidget(self.btn_close)

            self.ctrl_layout.insertWidget(0, self.btn_prev)
            self.ctrl_layout.insertWidget(1, self.btn_play)
            self.ctrl_layout.insertWidget(2, self.btn_next)

            self.mid_layout.setDirection(QBoxLayout.Direction.LeftToRight)
            self.mid_layout.setAlignment(self.lbl_cover, Qt.AlignmentFlag.AlignVCenter)

            self.lbl_title.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            self.lbl_artist.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            self.lbl_lyrics.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

            self.card_layout.setContentsMargins(12, 10, 12, 12)
            self.card_layout.setSpacing(6)

        elif mode == "large":
            # Expanded Large Album Art layout
            self.header_widget.show()
            self.lbl_lyrics.show()
            self.progress_row.show()
            self.ctrl_row.show()
            self.btn_prev.show()
            self.btn_next.show()
            self.btn_pin.show()
            self.btn_vol.show()
            self.vol_slider.show()

            self.header_layout.addWidget(self.btn_pin)
            self.header_layout.addWidget(self.btn_restore)
            self.header_layout.addWidget(self.btn_close)

            self.ctrl_layout.insertWidget(0, self.btn_prev)
            self.ctrl_layout.insertWidget(1, self.btn_play)
            self.ctrl_layout.insertWidget(2, self.btn_next)

            self.mid_layout.setDirection(QBoxLayout.Direction.TopToBottom)
            self.mid_layout.setAlignment(self.lbl_cover, Qt.AlignmentFlag.AlignHCenter)

            self.lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.lbl_artist.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.lbl_lyrics.setAlignment(Qt.AlignmentFlag.AlignCenter)

            self.card_layout.setContentsMargins(14, 12, 14, 14)
            self.card_layout.setSpacing(8)

    def _reapply_elided_text(self):
        w = self.width()
        if self._active_mode == "compact":
            max_w = max(60, w - 150)
        elif self._active_mode == "large":
            max_w = max(100, w - 40)
        else:
            max_w = max(270, w - 90)

        if self._last_title:
            fm = self.lbl_title.fontMetrics()
            self.lbl_title.setText(fm.elidedText(self._last_title, Qt.TextElideMode.ElideRight, max_w))

        if self._last_artist:
            fm = self.lbl_artist.fontMetrics()
            self.lbl_artist.setText(fm.elidedText(self._last_artist, Qt.TextElideMode.ElideRight, max_w))

        if self._last_lyric and self._active_mode != "compact":
            fm = self.lbl_lyrics.fontMetrics()
            self.lbl_lyrics.setText(fm.elidedText(self._last_lyric, Qt.TextElideMode.ElideRight, max_w))

    # -----------------------------------------------------------------
    # Multi-Direction Edge/Corner Hit-Testing & Frameless Resizing
    # -----------------------------------------------------------------
    def _determine_edge(self, global_pos: QPoint):
        local_pos = self.mapFromGlobal(global_pos)
        w = self.width()
        h = self.height()
        b = self.RESIZE_BORDER

        left = local_pos.x() <= b
        right = local_pos.x() >= w - b
        top = local_pos.y() <= b
        bottom = local_pos.y() >= h - b

        if left or right or top or bottom:
            return (left, right, top, bottom)
        return None

    def _apply_cursor_for_edge(self, edge):
        if not edge:
            self.setCursor(Qt.CursorShape.ArrowCursor)
            return
        left, right, top, bottom = edge
        if (left and top) or (right and bottom):
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        elif (right and top) or (left and bottom):
            self.setCursor(Qt.CursorShape.SizeBDiagCursor)
        elif left or right:
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        elif top or bottom:
            self.setCursor(Qt.CursorShape.SizeVerCursor)

    def _handle_resize_drag(self, g_pos: QPoint):
        dx = g_pos.x() - self._press_pos.x()
        dy = g_pos.y() - self._press_pos.y()
        left, right, top, bottom = self._resize_edge
        geom = QRect(self._start_geom)

        min_w, min_h = self.minimumWidth(), self.minimumHeight()
        max_w, max_h = self.maximumWidth(), self.maximumHeight()

        if left:
            new_w = max(min_w, min(max_w, geom.width() - dx))
            new_x = geom.right() - new_w + 1
            geom.setLeft(new_x)
            geom.setWidth(new_w)
        elif right:
            new_w = max(min_w, min(max_w, geom.width() + dx))
            geom.setWidth(new_w)

        if top:
            new_h = max(min_h, min(max_h, geom.height() - dy))
            new_y = geom.bottom() - new_h + 1
            geom.setTop(new_y)
            geom.setHeight(new_h)
        elif bottom:
            new_h = max(min_h, min(max_h, geom.height() + dy))
            geom.setHeight(new_h)

        self.setGeometry(geom)

    def eventFilter(self, obj, event):
        # Intercept events on self.card to allow resizing near edges or dragging inside
        if obj == self.card:
            if event.type() == QEvent.Type.MouseMove:
                g_pos = event.globalPosition().toPoint()
                if self._resizing and self._resize_edge:
                    self._handle_resize_drag(g_pos)
                    return True
                elif not self._resizing and event.buttons() == Qt.MouseButton.LeftButton and hasattr(self, "_drag_pos"):
                    self.move(g_pos - self._drag_pos)
                    return True
                else:
                    edge = self._determine_edge(g_pos)
                    self._apply_cursor_for_edge(edge)
            elif event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                g_pos = event.globalPosition().toPoint()
                edge = self._determine_edge(g_pos)
                if edge:
                    self._resizing = True
                    self._resize_edge = edge
                    self._press_pos = g_pos
                    self._start_geom = self.geometry()
                    return True
                else:
                    self._resizing = False
                    self._drag_pos = g_pos - self.frameGeometry().topLeft()
            elif event.type() == QEvent.Type.MouseButtonRelease:
                self._resizing = False
                self._resize_edge = None

        return super().eventFilter(obj, event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            g_pos = event.globalPosition().toPoint()
            edge = self._determine_edge(g_pos)
            if edge:
                self._resizing = True
                self._resize_edge = edge
                self._press_pos = g_pos
                self._start_geom = self.geometry()
            else:
                self._resizing = False
                self._drag_pos = g_pos - self.frameGeometry().topLeft()
            event.accept()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        g_pos = event.globalPosition().toPoint()
        if self._resizing and self._resize_edge:
            self._handle_resize_drag(g_pos)
            event.accept()
            return
        elif event.buttons() == Qt.MouseButton.LeftButton and hasattr(self, "_drag_pos"):
            self.move(g_pos - self._drag_pos)
            event.accept()
            return
        else:
            edge = self._determine_edge(g_pos)
            self._apply_cursor_for_edge(edge)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._resizing = False
        self._resize_edge = None
        super().mouseReleaseEvent(event)

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
        # Persist preferred size across sessions
        try:
            config.set("gui.mini_player_w", self.width())
            config.set("gui.mini_player_h", self.height())
        except Exception:
            pass
        self.sync_timer.stop()
        self.hide()

    def closeEvent(self, event):
        try:
            config.set("gui.mini_player_w", self.width())
            config.set("gui.mini_player_h", self.height())
        except Exception:
            pass
        super().closeEvent(event)

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
        self._last_title = title
        self._last_artist = artist

        self.lbl_title.setToolTip(title)
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
        self._last_lyric = lyric
        if lyric:
            self.lbl_lyrics.setStyleSheet("color: #1ed760; font-size: 11px; font-weight: 600;")
            self.lbl_lyrics.setToolTip(lyric)
        else:
            self.lbl_lyrics.setStyleSheet("color: #64748b; font-size: 11px;")
            self.lbl_lyrics.setToolTip("")

        # 6. Volume Slider
        vol = int(data.get("volume", 100))
        if not self.vol_slider.isSliderDown():
            self.vol_slider.setValue(vol)
            self.btn_vol.setText("🔇" if vol == 0 else "🔊")

        # Apply responsive eliding
        self._reapply_elided_text()

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
                    self._cached_qimage = qimg
                    self._render_cover()
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
