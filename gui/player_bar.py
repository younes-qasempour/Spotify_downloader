import os
import re
import random
import logging
from typing import Optional, List, Tuple, Any

from PyQt6.QtCore import Qt, QUrl, QTime, QByteArray, QPoint, QTimer
from PyQt6.QtGui import QImage, QPixmap, QPainter, QPainterPath, QIcon, QKeySequence, QShortcut
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QFrame, QApplication
)
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput, QMediaDevices, QAudioDevice
from qfluentwidgets import (
    ToolButton, Slider, FluentIcon, CaptionLabel, StrongBodyLabel,
    BodyLabel, IconWidget, RoundMenu, Action
)

from core.spotify_client import TrackMetadata
from core.archive import resolve_collection_cover
from gui.queue_delegate import extract_embedded_cover, ThumbnailCache
from gui.styles import TEXT_MUTED, TEXT_PRIMARY, BG_CARD, SPOTIFY_EMERALD

logger = logging.getLogger("gui.player_bar")


# -----------------------------------------------------------------------------
# Crisp Vector SVG Icons (viewBox 0 0 24 24)
# -----------------------------------------------------------------------------
SVG_PREV = '<svg viewBox="0 0 24 24"><path fill="currentColor" d="M6 6h2.2v12H6zm3.3 6L18 18V6z"/></svg>'
SVG_NEXT = '<svg viewBox="0 0 24 24"><path fill="currentColor" d="M6 18l8.7-6L6 6v12zm9.8-12v12H18V6z"/></svg>'
SVG_REWIND_10 = (
    '<svg viewBox="0 0 24 24">'
    '<path fill="currentColor" d="M12.5 3a9 9 0 0 0-6.36 2.64L4 3.5V9h5.5L7.22 6.72A7 7 0 1 1 5.5 12h-2a9 9 0 1 0 9-9z"/>'
    '<text x="12.5" y="15.5" font-size="7.5" font-family="Segoe UI, sans-serif" font-weight="bold" fill="currentColor" text-anchor="middle">10</text>'
    '</svg>'
)
SVG_FORWARD_10 = (
    '<svg viewBox="0 0 24 24">'
    '<path fill="currentColor" d="M11.5 3a9 9 0 0 1 6.36 2.64L20 3.5V9h-5.5L16.78 6.72A7 7 0 1 0 18.5 12h2a9 9 0 1 1-9-9z"/>'
    '<text x="11.5" y="15.5" font-size="7.5" font-family="Segoe UI, sans-serif" font-weight="bold" fill="currentColor" text-anchor="middle">10</text>'
    '</svg>'
)
SVG_SHUFFLE = (
    '<svg viewBox="0 0 24 24">'
    '<path fill="currentColor" d="M10.59 9.17L5.41 4 4 5.41l5.17 5.17 1.42-1.41zM14.5 4l2.04 2.04L4 18.59 5.41 20 17.96 7.46 20 9.5V4h-5.5zm.33 9.41l-1.41 1.41 3.13 3.13L14.5 20H20v-5.5l-2.04 2.04-3.13-3.13z"/>'
    '</svg>'
)
SVG_REPEAT = (
    '<svg viewBox="0 0 24 24">'
    '<path fill="currentColor" d="M7 7h10v3l4-4-4-4v3H5v6h2V7zm10 10H7v-3l-4 4 4 4v-3h12v-6h-2v4z"/>'
    '</svg>'
)
SVG_REPEAT_ONE = (
    '<svg viewBox="0 0 24 24">'
    '<path fill="currentColor" d="M7 7h10v3l4-4-4-4v3H5v6h2V7zm10 10H7v-3l-4 4 4 4v-3h12v-6h-2v4z"/>'
    '<text x="12" y="14.5" font-size="6.5" font-family="Segoe UI, sans-serif" font-weight="bold" fill="currentColor" text-anchor="middle">1</text>'
    '</svg>'
)


def make_svg_icon(svg_str: str, color: str = "#E0E0E0", disabled_color: str = "#555555", size: int = 24) -> QIcon:
    """Renders an SVG string into a crisp, multi-state QIcon."""
    def _render(c: str) -> QPixmap:
        raw = svg_str.replace("currentColor", c)
        renderer = QSvgRenderer(QByteArray(raw.encode("utf-8")))
        pix = QPixmap(size, size)
        pix.fill(Qt.GlobalColor.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        renderer.render(p)
        p.end()
        return pix

    icon = QIcon()
    icon.addPixmap(_render(color), QIcon.Mode.Normal, QIcon.State.Off)
    icon.addPixmap(_render(color), QIcon.Mode.Normal, QIcon.State.On)
    icon.addPixmap(_render(disabled_color), QIcon.Mode.Disabled, QIcon.State.Off)
    icon.addPixmap(_render(disabled_color), QIcon.Mode.Disabled, QIcon.State.On)
    return icon


class PlayerSeekSlider(Slider):
    """
    Enhanced seek slider with instant click-to-seek and smooth drag responsiveness.
    Explicitly emits sliderPressed and sliderReleased on mouse events so background
    player tick updates never overwrite or fight user drag and click scrubbing.
    """

    def mousePressEvent(self, e):
        super().mousePressEvent(e)
        self.sliderPressed.emit()

    def mouseReleaseEvent(self, e):
        super().mouseReleaseEvent(e)
        self.sliderReleased.emit()


class MiniPlayerBar(QFrame):
    """
    Windows 11 Fluent In-App Mini-Player Dock.
    Features:
    - Integrated native audio decoding via PyQt6.QtMultimedia (FLAC, MP3, Opus, M4A, OGG).
    - True executive transport controls: Shuffle, Previous Track (|◀), Rewind 10s (↺10), Play/Pause, Forward 10s (↻10), Next Track (▶|), Repeat (Off/All/One).
    - Instant click-to-seek and drag-responsive seek slider with millisecond precision.
    - Synchronized live karaoke lyrics banner with upcoming line preview.
    - Interactive album cover artwork with click-to-reveal in Windows Explorer.
    - Safe global shortcuts (Space for Play/Pause, Left/Right for 5s seek, Ctrl+Left/Right for tracks).
    - Smart volume memory and instant mute/unmute.
    """

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("mini_player_bar")
        self.setFixedHeight(88)

        self.current_file_path: Optional[str] = None
        self.current_track: Optional[TrackMetadata] = None
        self.current_quality_badge: str = ""
        self.playlist: List[Any] = []
        self.current_index: int = -1
        self.lyrics_timeline: List[Tuple[int, str]] = []
        self.last_lyric_idx: int = -1
        self._user_seeking: bool = False
        self._saved_vol: float = 0.85

        # Playback Modes
        self.shuffle_enabled: bool = False
        self.repeat_mode: str = "off"  # "off", "all", "one"
        self._shuffle_history: List[int] = []
        self._unplayed_indices: List[int] = []

        # Audio Device Tracking & Dynamic Migration
        self.media_devices = QMediaDevices(self)
        self._current_device_id: Optional[bytes] = None
        self._selected_device_id: Optional[bytes] = None  # None indicates "auto" (follow Windows default)
        self._current_device_name: str = "System Default"

        # Initialize QtMultimedia Player and AudioOutput
        self.audio_output = QAudioOutput(self)
        self.audio_output.setVolume(self._saved_vol)
        default_dev = self.media_devices.defaultAudioOutput()
        if not default_dev.isNull():
            self._current_device_id = bytes(default_dev.id())
            self._current_device_name = default_dev.description()
            self.audio_output.setDevice(default_dev)

        self.media_devices.audioOutputsChanged.connect(self._on_audio_outputs_changed)

        # 1000ms Watchdog to detect Windows default audio device changes
        self._device_watchdog = QTimer(self)
        self._device_watchdog.setInterval(1000)
        self._device_watchdog.timeout.connect(self._check_audio_device_watchdog)
        self._device_watchdog.start()

        self.player = QMediaPlayer(self)
        self.player.setAudioOutput(self.audio_output)
        self.player.positionChanged.connect(self._on_player_position_changed)
        self.player.durationChanged.connect(self._on_player_duration_changed)
        self.player.playbackStateChanged.connect(self._on_playback_state_changed)
        self.player.mediaStatusChanged.connect(self._on_media_status_changed)

        # Connect to thumbnail loader
        self.thumb_cache = ThumbnailCache()
        self.thumb_cache.emitter.sig_loaded.connect(self._on_thumbnail_loaded)

        self._init_ui()
        self.setVisible(False)  # Hidden until track is played

    def _init_ui(self):
        self.setStyleSheet("""
            QFrame#mini_player_bar {
                background-color: #1a1a1a;
                border-top: 1px solid rgba(255, 255, 255, 0.10);
            }
        """)

        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(18, 6, 18, 6)
        main_layout.setSpacing(16)

        # -------------------------------------------------------------
        # Left Section: Thumbnail, Title, Artist, Quality Badge
        # -------------------------------------------------------------
        left_layout = QHBoxLayout()
        left_layout.setSpacing(12)
        left_layout.setContentsMargins(0, 0, 0, 0)

        self.cover_label = QLabel(self)
        self.cover_label.setFixedSize(52, 52)
        self.cover_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cover_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cover_label.setToolTip("Click to show file in Windows Explorer")
        self.cover_label.setStyleSheet("""
            QLabel {
                background-color: #262626;
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 6px;
            }
            QLabel:hover {
                border: 1px solid #1ED760;
            }
        """)
        self.cover_label.mousePressEvent = lambda e: self._open_in_explorer() if e.button() == Qt.MouseButton.LeftButton else None
        left_layout.addWidget(self.cover_label)

        info_layout = QVBoxLayout()
        info_layout.setSpacing(2)
        info_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        self.title_label = StrongBodyLabel("No track playing", self)
        self.title_label.setStyleSheet("color: #FFFFFF; font-size: 13px; font-weight: 600;")
        self.title_label.setMinimumWidth(160)
        self.title_label.setMaximumWidth(340)

        meta_row = QHBoxLayout()
        meta_row.setSpacing(6)
        meta_row.setContentsMargins(0, 0, 0, 0)

        self.artist_label = CaptionLabel("Ready", self)
        self.artist_label.setTextColor(TEXT_MUTED, TEXT_MUTED)
        self.artist_label.setMaximumWidth(220)

        self.badge_label = QLabel(self)
        self.badge_label.setStyleSheet("""
            QLabel {
                background-color: rgba(29, 185, 84, 0.18);
                color: #1ED760;
                font-size: 10px;
                font-weight: 700;
                padding: 1px 6px;
                border-radius: 3px;
                border: 1px solid rgba(29, 185, 84, 0.35);
            }
        """)
        self.badge_label.setVisible(False)

        meta_row.addWidget(self.artist_label)
        meta_row.addWidget(self.badge_label)
        meta_row.addStretch(1)

        info_layout.addWidget(self.title_label)
        info_layout.addLayout(meta_row)
        left_layout.addLayout(info_layout)

        main_layout.addLayout(left_layout, 0)

        # -------------------------------------------------------------
        # Center Section: Karaoke Banner + Controls + Seek Slider
        # -------------------------------------------------------------
        center_layout = QVBoxLayout()
        center_layout.setSpacing(2)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # 1. Live Karaoke Banner (Active line & Next line)
        karaoke_container = QHBoxLayout()
        karaoke_container.setSpacing(8)
        karaoke_container.setContentsMargins(0, 0, 0, 0)
        karaoke_container.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.active_lyric_label = QLabel("♪ Flacify High-Fidelity Audio ♪", self)
        self.active_lyric_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.active_lyric_label.setStyleSheet("""
            QLabel {
                color: #1ED760;
                font-size: 12px;
                font-weight: 600;
                background: transparent;
            }
        """)

        self.next_lyric_label = QLabel("", self)
        self.next_lyric_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.next_lyric_label.setStyleSheet("""
            QLabel {
                color: #777777;
                font-size: 11px;
                font-style: italic;
                background: transparent;
            }
        """)
        self.next_lyric_label.setVisible(False)

        karaoke_container.addWidget(self.active_lyric_label)
        karaoke_container.addWidget(self.next_lyric_label)
        center_layout.addLayout(karaoke_container)

        # 2. Controls Row: Shuffle, Previous (|◀), Rewind 10s (↺10), Play/Pause, Forward 10s (↻10), Next (▶|), Repeat
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_row.setContentsMargins(0, 0, 0, 0)
        btn_row.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Shuffle button
        self.shuffle_btn = ToolButton(make_svg_icon(SVG_SHUFFLE, color="#888888"), self)
        self.shuffle_btn.setToolTip("Shuffle: Off (Click to enable)")
        self.shuffle_btn.setFixedSize(28, 28)
        self.shuffle_btn.clicked.connect(self._toggle_shuffle)

        # Previous Track (|◀)
        self.prev_btn = ToolButton(make_svg_icon(SVG_PREV, color="#E0E0E0"), self)
        self.prev_btn.setToolTip("Previous Track")
        self.prev_btn.setFixedSize(30, 30)
        self.prev_btn.clicked.connect(self.play_previous)

        # Rewind 10 seconds (↺10)
        self.rewind_btn = ToolButton(make_svg_icon(SVG_REWIND_10, color="#CCCCCC"), self)
        self.rewind_btn.setToolTip("Rewind 10 seconds")
        self.rewind_btn.setFixedSize(26, 26)
        self.rewind_btn.clicked.connect(lambda: self._seek_relative(-10000))

        # Play / Pause
        self.play_btn = ToolButton(FluentIcon.PLAY, self)
        self.play_btn.setToolTip("Play / Pause (Space)")
        self.play_btn.setFixedSize(36, 36)
        self.play_btn.clicked.connect(self._toggle_play_pause)

        # Forward 10 seconds (↻10)
        self.forward_btn = ToolButton(make_svg_icon(SVG_FORWARD_10, color="#CCCCCC"), self)
        self.forward_btn.setToolTip("Forward 10 seconds")
        self.forward_btn.setFixedSize(26, 26)
        self.forward_btn.clicked.connect(lambda: self._seek_relative(10000))

        # Next Track (▶|)
        self.next_btn = ToolButton(make_svg_icon(SVG_NEXT, color="#E0E0E0"), self)
        self.next_btn.setToolTip("Next Track")
        self.next_btn.setFixedSize(30, 30)
        self.next_btn.clicked.connect(self.play_next)

        # Repeat button (Off -> All -> One)
        self.repeat_btn = ToolButton(make_svg_icon(SVG_REPEAT, color="#888888"), self)
        self.repeat_btn.setToolTip("Repeat: Off (Click to enable Repeat All)")
        self.repeat_btn.setFixedSize(28, 28)
        self.repeat_btn.clicked.connect(self._toggle_repeat)

        btn_row.addWidget(self.shuffle_btn)
        btn_row.addWidget(self.prev_btn)
        btn_row.addWidget(self.rewind_btn)
        btn_row.addWidget(self.play_btn)
        btn_row.addWidget(self.forward_btn)
        btn_row.addWidget(self.next_btn)
        btn_row.addWidget(self.repeat_btn)
        center_layout.addLayout(btn_row)

        # 3. Seek Slider Row with Time Labels on both sides
        seek_row = QHBoxLayout()
        seek_row.setSpacing(8)
        seek_row.setContentsMargins(0, 0, 0, 0)

        self.curr_time_label = CaptionLabel("00:00", self)
        self.curr_time_label.setTextColor(TEXT_MUTED, TEXT_MUTED)
        self.curr_time_label.setFixedWidth(38)
        self.curr_time_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.seek_slider = PlayerSeekSlider(Qt.Orientation.Horizontal, self)
        self.seek_slider.setRange(0, 1000)
        self.seek_slider.setValue(0)
        self.seek_slider.sliderPressed.connect(self._on_seek_started)
        self.seek_slider.sliderReleased.connect(self._on_seek_finished)
        self.seek_slider.sliderMoved.connect(self._on_slider_moved)
        self.seek_slider.clicked.connect(self._on_slider_clicked)
        self.seek_slider.valueChanged.connect(self._on_slider_value_changed)

        self.total_time_label = CaptionLabel("00:00", self)
        self.total_time_label.setTextColor(TEXT_MUTED, TEXT_MUTED)
        self.total_time_label.setFixedWidth(38)
        self.total_time_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        seek_row.addWidget(self.curr_time_label)
        seek_row.addWidget(self.seek_slider, 1)
        seek_row.addWidget(self.total_time_label)

        center_layout.addLayout(seek_row)
        main_layout.addLayout(center_layout, 1)

        # -------------------------------------------------------------
        # Right Section: Volume & File Actions
        # -------------------------------------------------------------
        right_layout = QHBoxLayout()
        right_layout.setSpacing(8)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        self.device_btn = ToolButton(FluentIcon.HEADPHONE, self)
        self.device_btn.setFixedSize(28, 28)
        self.device_btn.clicked.connect(self._show_device_menu)
        self._update_device_btn_tooltip()

        self.volume_btn = ToolButton(FluentIcon.VOLUME, self)
        self.volume_btn.setToolTip("Mute / Unmute")
        self.volume_btn.setFixedSize(28, 28)
        self.volume_btn.clicked.connect(self._toggle_mute)

        self.volume_slider = Slider(Qt.Orientation.Horizontal, self)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(int(self._saved_vol * 100))
        self.volume_slider.setFixedWidth(75)
        self.volume_slider.setToolTip(f"Volume: {int(self._saved_vol * 100)}%")
        self.volume_slider.valueChanged.connect(self._on_volume_changed)

        self.folder_btn = ToolButton(FluentIcon.FOLDER, self)
        self.folder_btn.setToolTip("Show in Explorer")
        self.folder_btn.setFixedSize(28, 28)
        self.folder_btn.clicked.connect(self._open_in_explorer)

        self.close_btn = ToolButton(FluentIcon.CLOSE, self)
        self.close_btn.setToolTip("Stop & Close Player")
        self.close_btn.setFixedSize(28, 28)
        self.close_btn.clicked.connect(self.stop_and_hide)

        right_layout.addWidget(self.device_btn)
        right_layout.addWidget(self.volume_btn)
        right_layout.addWidget(self.volume_slider)
        right_layout.addWidget(self.folder_btn)
        right_layout.addWidget(self.close_btn)

        main_layout.addLayout(right_layout, 0)

        # -------------------------------------------------------------
        # Safe Keyboard Shortcuts (Scoped to Player Dock to avoid hijacking text input)
        # -------------------------------------------------------------
        self._space_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Space), self)
        self._space_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._space_shortcut.activated.connect(self._toggle_play_pause)

        self._left_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Left), self)
        self._left_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._left_shortcut.activated.connect(lambda: self._seek_relative(-5000))

        self._right_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Right), self)
        self._right_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._right_shortcut.activated.connect(lambda: self._seek_relative(5000))

    # -------------------------------------------------------------
    # Playlist & Navigation Engine
    # -------------------------------------------------------------
    def set_playlist(self, playlist: List[Any], current_index: int = -1):
        """Sets the active playlist for Previous/Next song navigation."""
        self.playlist = list(playlist)
        self.current_index = current_index
        self._shuffle_history.clear()
        if self.shuffle_enabled:
            self._unplayed_indices = [i for i in range(len(self.playlist)) if i != current_index]
            random.shuffle(self._unplayed_indices)
        else:
            self._unplayed_indices.clear()
        self._update_nav_state()

    def _update_nav_state(self):
        has_items = len(self.playlist) > 0
        self.prev_btn.setEnabled(has_items)
        self.next_btn.setEnabled(has_items)
        self.shuffle_btn.setEnabled(len(self.playlist) > 1)
        self.repeat_btn.setEnabled(has_items)

        # Dynamic context tooltips with next/previous track names
        if has_items:
            # Previous tooltip
            if self.shuffle_enabled and self._shuffle_history:
                prev_item = self.playlist[self._shuffle_history[-1]]
                self.prev_btn.setToolTip(f"Previous: {self._get_item_title(prev_item)}")
            elif self.current_index > 0:
                prev_item = self.playlist[self.current_index - 1]
                self.prev_btn.setToolTip(f"Previous: {self._get_item_title(prev_item)}")
            elif len(self.playlist) > 1:
                prev_item = self.playlist[-1]
                self.prev_btn.setToolTip(f"Previous: {self._get_item_title(prev_item)}")
            else:
                self.prev_btn.setToolTip("Restart Track")

            # Next tooltip
            if self.shuffle_enabled and self._unplayed_indices:
                next_item = self.playlist[self._unplayed_indices[0]]
                self.next_btn.setToolTip(f"Next: {self._get_item_title(next_item)}")
            elif self.current_index + 1 < len(self.playlist):
                next_item = self.playlist[self.current_index + 1]
                self.next_btn.setToolTip(f"Next: {self._get_item_title(next_item)}")
            elif len(self.playlist) > 1:
                next_item = self.playlist[0]
                self.next_btn.setToolTip(f"Next: {self._get_item_title(next_item)}")
            else:
                self.next_btn.setToolTip("Next Track")
        else:
            self.prev_btn.setToolTip("Previous Track")
            self.next_btn.setToolTip("Next Track")

    def _toggle_shuffle(self):
        self.shuffle_enabled = not self.shuffle_enabled
        if self.shuffle_enabled:
            self.shuffle_btn.setIcon(make_svg_icon(SVG_SHUFFLE, color="#1ED760"))
            self.shuffle_btn.setToolTip("Shuffle: On (Click to disable)")
            self._unplayed_indices = [i for i in range(len(self.playlist)) if i != self.current_index]
            random.shuffle(self._unplayed_indices)
        else:
            self.shuffle_btn.setIcon(make_svg_icon(SVG_SHUFFLE, color="#888888"))
            self.shuffle_btn.setToolTip("Shuffle: Off (Click to enable)")
            self._unplayed_indices.clear()
            self._shuffle_history.clear()
        self._update_nav_state()

    def _toggle_repeat(self):
        # Cycle: off -> all -> one -> off
        if self.repeat_mode == "off":
            self.repeat_mode = "all"
            self.repeat_btn.setIcon(make_svg_icon(SVG_REPEAT, color="#1ED760"))
            self.repeat_btn.setToolTip("Repeat: All Tracks (Click for Repeat One)")
        elif self.repeat_mode == "all":
            self.repeat_mode = "one"
            self.repeat_btn.setIcon(make_svg_icon(SVG_REPEAT_ONE, color="#1ED760"))
            self.repeat_btn.setToolTip("Repeat: Current Track (Click to disable)")
        else:
            self.repeat_mode = "off"
            self.repeat_btn.setIcon(make_svg_icon(SVG_REPEAT, color="#888888"))
            self.repeat_btn.setToolTip("Repeat: Off (Click to enable Repeat All)")

    def play_index(self, index: int):
        if not self.playlist or index < 0 or index >= len(self.playlist):
            return
        self.current_index = index
        self._play_item(self.playlist[index])
        self._update_nav_state()

    def play_next(self, loop: bool = True):
        """Advances to the next track in the active playlist or shuffled pool."""
        if not self.playlist:
            return

        # If shuffle is enabled
        if self.shuffle_enabled and len(self.playlist) > 1:
            if not self._unplayed_indices:
                if self.repeat_mode == "off" and not loop:
                    self.player.stop()
                    return
                self._unplayed_indices = [i for i in range(len(self.playlist)) if i != self.current_index]
                random.shuffle(self._unplayed_indices)

            if self._unplayed_indices:
                next_idx = self._unplayed_indices.pop(0)
                if self.current_index >= 0:
                    self._shuffle_history.append(self.current_index)
                self.play_index(next_idx)
                return

        # Sequential playback
        next_idx = self.current_index + 1
        if next_idx < len(self.playlist):
            self.play_index(next_idx)
        elif len(self.playlist) > 1:
            if self.repeat_mode == "all" or loop:
                self.play_index(0)
            else:
                self.player.stop()
        elif len(self.playlist) == 1 and (self.repeat_mode == "all" or self.repeat_mode == "one"):
            self.player.setPosition(0)
            self.player.play()

    def play_previous(self):
        """Plays the previous track in the playlist, or restarts current if played > 3 seconds."""
        if not self.playlist:
            if self.player.position() > 3000:
                self.player.setPosition(0)
            return

        if self.player.position() > 3000:
            self.player.setPosition(0)
            return

        # If shuffle is active and history exists
        if self.shuffle_enabled and self._shuffle_history:
            prev_idx = self._shuffle_history.pop()
            self.play_index(prev_idx)
            return

        # Sequential playback
        prev_idx = self.current_index - 1
        if prev_idx >= 0:
            self.play_index(prev_idx)
        elif len(self.playlist) > 1:
            self.play_index(len(self.playlist) - 1)
        else:
            self.player.setPosition(0)

    def _play_item(self, item: Any):
        if not item:
            return
        fpath = ""
        track = None
        badge = ""
        if isinstance(item, (tuple, list)):
            fpath = item[0] if len(item) > 0 else ""
            track = item[1] if len(item) > 1 else None
            badge = item[2] if len(item) > 2 else ""
        elif isinstance(item, dict):
            fpath = item.get("file_path", "")
            track = item.get("track", None)
            badge = item.get("quality_badge", "")
        else:
            fpath = getattr(item, "output_path", "")
            track = getattr(item, "track", None)
            badge = getattr(item, "quality_badge", "")

        if fpath and os.path.isfile(fpath):
            self.play_track(fpath, track, badge, playlist=self.playlist, index=self.current_index)
        else:
            logger.warning(f"Audio file does not exist: {fpath}")
            if len(self.playlist) > 1:
                self.play_next()

    def _get_item_title(self, item: Any) -> str:
        if not item:
            return "Track"
        if isinstance(item, (tuple, list)):
            track = item[1] if len(item) > 1 else None
            fpath = item[0] if len(item) > 0 else ""
        elif isinstance(item, dict):
            track = item.get("track")
            fpath = item.get("file_path", "")
        else:
            track = getattr(item, "track", None)
            fpath = getattr(item, "output_path", "")
        if track and getattr(track, "title", None):
            artist = getattr(track, "artist_str", "")
            return f"{track.title} ({artist})" if artist else track.title
        if fpath:
            return os.path.splitext(os.path.basename(fpath))[0]
        return "Track"

    def _on_media_status_changed(self, status: QMediaPlayer.MediaStatus):
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            if self.repeat_mode == "one":
                self.player.setPosition(0)
                self.player.play()
            elif self.playlist and len(self.playlist) > 0:
                self.play_next(loop=(self.repeat_mode == "all"))

    # -------------------------------------------------------------
    # Playback & Lyrics Engine
    # -------------------------------------------------------------
    def play_track(
        self,
        file_path: str,
        track: Optional[TrackMetadata] = None,
        quality_badge: str = "",
        playlist: Optional[List[Any]] = None,
        index: int = -1
    ):
        """Loads and begins audio playback of a local music file."""
        if not file_path or not os.path.isfile(file_path):
            logger.warning(f"Audio file does not exist: {file_path}")
            return

        if playlist is not None:
            self.playlist = list(playlist)
            if index >= 0:
                self.current_index = index
            else:
                self.current_index = next(
                    (
                        i for i, it in enumerate(self.playlist)
                        if getattr(it, "output_path", "") == file_path
                        or getattr(it, "file_path", "") == file_path
                        or (isinstance(it, (tuple, list)) and len(it) > 0 and it[0] == file_path)
                    ),
                    -1
                )
            self._shuffle_history.clear()
            if self.shuffle_enabled:
                self._unplayed_indices = [i for i in range(len(self.playlist)) if i != self.current_index]
                random.shuffle(self._unplayed_indices)
            else:
                self._unplayed_indices.clear()
            self._update_nav_state()

        self.current_file_path = file_path
        self.current_track = track
        self.current_quality_badge = quality_badge

        # Title & Artist display
        title = track.title if track else os.path.splitext(os.path.basename(file_path))[0]
        artist = track.artist_str if track else "Local Audio"
        self.title_label.setText(title)
        self.title_label.setToolTip(f"{title} — {artist}")
        self.artist_label.setText(artist)

        # Quality Badge
        if quality_badge:
            self.badge_label.setText(quality_badge.upper())
            self.badge_label.setVisible(True)
        else:
            self.badge_label.setVisible(False)

        # Load cover artwork
        self._load_cover(file_path, track)

        # Parse synchronized LRC lyrics
        self._load_lyrics(file_path, track)

        # Set media source and play
        self.player.setSource(QUrl.fromLocalFile(file_path))
        self.player.play()

        self.setVisible(True)

    def _on_thumbnail_loaded(self, key: str):
        if not self.isVisible():
            return
        current_cover = getattr(self.current_track, "local_cover", "") or (self.current_track.cover_url if self.current_track else "")
        if key == current_cover or key == self.current_file_path:
            pix = self.thumb_cache.get(key)
            if pix and not pix.isNull():
                self._set_cover_pixmap(pix)

    def _load_cover(self, file_path: str, track: Optional[TrackMetadata]):
        for child in self.cover_label.findChildren(QWidget):
            child.deleteLater()

        # 1. High-priority: Extract embedded cover directly from audio tags (<2ms)
        try:
            art_bytes = extract_embedded_cover(file_path)
            if art_bytes:
                img = QImage()
                if img.loadFromData(art_bytes) and not img.isNull():
                    self._set_cover_pixmap(img)
                    return
        except Exception as e:
            logger.debug(f"Could not extract embedded cover: {e}")

        # 2. Check collection cover in app cache or music folder
        try:
            folder = os.path.dirname(file_path) if file_path else ""
            if folder:
                cached_collection = resolve_collection_cover(folder)
                if cached_collection and os.path.isfile(cached_collection):
                    img = QImage(cached_collection)
                    if not img.isNull():
                        self._set_cover_pixmap(img)
                        return

                for cand in ["cover.jpg", "cover.png", "folder.jpg", "artwork.jpg"]:
                    cand_p = os.path.join(folder, cand)
                    if os.path.isfile(cand_p):
                        img = QImage(cand_p)
                        if not img.isNull():
                            self._set_cover_pixmap(img)
                            return
        except Exception as e:
            logger.debug(f"Could not check folder artwork: {e}")

        # 3. Check track cover URL or local cover via async ThumbnailCache
        thumb_key = ""
        if track:
            thumb_key = getattr(track, "local_cover", "") or track.cover_url or ""

        if thumb_key:
            pix = self.thumb_cache.get(thumb_key)
            if pix and not pix.isNull():
                self._set_cover_pixmap(pix)
                return
            else:
                self.thumb_cache.load_async(thumb_key)

        # 4. Fallback: Sleek music note icon placeholder
        self.cover_label.clear()
        icon_w = IconWidget(FluentIcon.MUSIC, self.cover_label)
        icon_w.setFixedSize(28, 28)
        icon_w.move(11, 11)
        icon_w.show()

    def _set_cover_pixmap(self, img_or_pix: Any):
        for child in self.cover_label.findChildren(QWidget):
            child.deleteLater()
        if isinstance(img_or_pix, QPixmap):
            img = img_or_pix.toImage()
        else:
            img = img_or_pix

        scaled = img.scaled(52, 52, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
        rounded = QPixmap(52, 52)
        rounded.fill(Qt.GlobalColor.transparent)
        p = QPainter(rounded)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(0, 0, 52, 52, 6, 6)
        p.setClipPath(path)
        p.drawPixmap(0, 0, QPixmap.fromImage(scaled))
        p.end()
        self.cover_label.setPixmap(rounded)

    def _load_lyrics(self, file_path: str, track: Optional[TrackMetadata]):
        """Parses companion .lrc file for live CRLF/LF synchronized line timestamps."""
        self.lyrics_timeline.clear()
        self.last_lyric_idx = -1

        base, _ = os.path.splitext(file_path)
        candidates = [
            f"{base}.lrc",
            os.path.join(os.path.dirname(file_path), "lyrics", f"{os.path.basename(base)}.lrc")
        ]

        lrc_text = ""
        for cand in candidates:
            if os.path.isfile(cand):
                try:
                    with open(cand, "r", encoding="utf-8", errors="replace") as f:
                        lrc_text = f.read()
                    break
                except Exception:
                    pass

        if not lrc_text:
            title_text = track.title if track else os.path.splitext(os.path.basename(file_path))[0]
            artist_text = track.artist_str if track else ""
            if artist_text:
                self.active_lyric_label.setText(f"♪ {title_text} — {artist_text} ♪")
            else:
                self.active_lyric_label.setText(f"♪ {title_text} ♪")
            self.next_lyric_label.setText("")
            self.next_lyric_label.setVisible(False)
            return

        # Parse CRLF and LF lines: [mm:ss.xx] Lyric text
        pattern = re.compile(r'\[(\d{1,2}):(\d{2})(?:\.(\d{2,3}))?\](.*)')
        parsed_entries: List[Tuple[int, str]] = []

        for line in lrc_text.splitlines():
            line = line.strip()
            m = pattern.match(line)
            if m:
                mins = int(m.group(1))
                secs = int(m.group(2))
                ms_str = m.group(3) or "0"
                ms = int(ms_str.ljust(3, "0")[:3])
                total_ms = (mins * 60 + secs) * 1000 + ms
                lyric_text = m.group(4).strip()
                if lyric_text:
                    parsed_entries.append((total_ms, lyric_text))

        parsed_entries.sort(key=lambda x: x[0])
        self.lyrics_timeline = parsed_entries

        if self.lyrics_timeline:
            self.active_lyric_label.setText(self.lyrics_timeline[0][1])
            if len(self.lyrics_timeline) > 1:
                self.next_lyric_label.setText(f"  →  {self.lyrics_timeline[1][1]}")
                self.next_lyric_label.setVisible(True)
            else:
                self.next_lyric_label.setText("")
                self.next_lyric_label.setVisible(False)
        else:
            self.active_lyric_label.setText("♪ Synchronized Karaoke Lyrics ♪")
            self.next_lyric_label.setText("")
            self.next_lyric_label.setVisible(False)

    # -------------------------------------------------------------
    # Position & State Handlers
    # -------------------------------------------------------------
    def _on_player_position_changed(self, pos_ms: int):
        dur_ms = self.player.duration()
        if not self._user_seeking and dur_ms > 0:
            val = int(pos_ms / dur_ms * 1000)
            self.seek_slider.setValue(val)
            if hasattr(self.seek_slider, "_adjustHandlePos"):
                self.seek_slider._adjustHandlePos()

        # Update time labels
        if not self._user_seeking:
            self.curr_time_label.setText(self._format_ms(pos_ms))
        if dur_ms > 0:
            self.total_time_label.setText(self._format_ms(dur_ms))

        # Update live synchronized karaoke lyric
        if self.lyrics_timeline:
            idx = -1
            for i, (ts, text) in enumerate(self.lyrics_timeline):
                if ts <= pos_ms:
                    idx = i
                else:
                    break

            if idx != -1 and idx != self.last_lyric_idx:
                self.last_lyric_idx = idx
                self.active_lyric_label.setText(self.lyrics_timeline[idx][1])
                if idx + 1 < len(self.lyrics_timeline):
                    self.next_lyric_label.setText(f"  →  {self.lyrics_timeline[idx + 1][1]}")
                    self.next_lyric_label.setVisible(True)
                else:
                    self.next_lyric_label.setText("")
                    self.next_lyric_label.setVisible(False)

    def _on_player_duration_changed(self, dur_ms: int):
        self.total_time_label.setText(self._format_ms(dur_ms))
        self.curr_time_label.setText(self._format_ms(self.player.position()))

    def _on_playback_state_changed(self, state: QMediaPlayer.PlaybackState):
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self.play_btn.setIcon(FluentIcon.PAUSE)
            self.play_btn.setToolTip("Pause (Space)")
        else:
            self.play_btn.setIcon(FluentIcon.PLAY)
            self.play_btn.setToolTip("Play (Space)")

    def _toggle_play_pause(self):
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def _seek_relative(self, delta_ms: int):
        dur = self.player.duration()
        if dur > 0:
            new_pos = max(0, min(dur, self.player.position() + delta_ms))
            self.player.setPosition(new_pos)
            self.curr_time_label.setText(self._format_ms(new_pos))
            val = int(new_pos / dur * 1000)
            self.seek_slider.setValue(val)
            if hasattr(self.seek_slider, "_adjustHandlePos"):
                self.seek_slider._adjustHandlePos()

    def _on_seek_started(self):
        self._user_seeking = True

    def _on_seek_finished(self):
        self._user_seeking = False
        dur_ms = self.player.duration()
        if dur_ms > 0:
            target_pos = int(self.seek_slider.value() / 1000.0 * dur_ms)
            self.player.setPosition(target_pos)
            self.curr_time_label.setText(self._format_ms(target_pos))

    def _on_slider_moved(self, val: int):
        self._user_seeking = True
        dur_ms = self.player.duration()
        if dur_ms > 0:
            pos_ms = int(val / 1000.0 * dur_ms)
            self.curr_time_label.setText(self._format_ms(pos_ms))

    def _on_slider_clicked(self, val: int):
        dur_ms = self.player.duration()
        if dur_ms > 0:
            target_pos = int(val / 1000.0 * dur_ms)
            self.player.setPosition(target_pos)
            self.curr_time_label.setText(self._format_ms(target_pos))

    def _on_slider_value_changed(self, val: int):
        if hasattr(self.seek_slider, "_adjustHandlePos"):
            self.seek_slider._adjustHandlePos()
        if self._user_seeking:
            dur_ms = self.player.duration()
            if dur_ms > 0:
                pos_ms = int(val / 1000.0 * dur_ms)
                self.curr_time_label.setText(self._format_ms(pos_ms))

    def _on_volume_changed(self, val: int):
        vol_float = val / 100.0
        self.audio_output.setVolume(vol_float)
        self.volume_slider.setToolTip(f"Volume: {val}%")
        if val > 0:
            self._saved_vol = vol_float
            self.volume_btn.setIcon(FluentIcon.VOLUME)
            self.volume_btn.setToolTip("Mute")
        else:
            self.volume_btn.setIcon(FluentIcon.MUTE)
            self.volume_btn.setToolTip("Unmute")

    def _toggle_mute(self):
        if self.audio_output.volume() > 0.001:
            self._saved_vol = self.audio_output.volume()
            self.volume_slider.setValue(0)
        else:
            restore_vol = getattr(self, "_saved_vol", 0.85) or 0.85
            if restore_vol < 0.05:
                restore_vol = 0.85
            self.volume_slider.setValue(int(restore_vol * 100))

    def _open_in_explorer(self):
        if self.current_file_path and os.path.isfile(self.current_file_path):
            import subprocess
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
            subprocess.Popen(
                ["explorer", f"/select,{os.path.normpath(self.current_file_path)}"],
                creationflags=flags
            )
        elif self.current_file_path and os.path.isdir(os.path.dirname(self.current_file_path)):
            import subprocess
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
            subprocess.Popen(
                ["explorer", os.path.normpath(os.path.dirname(self.current_file_path))],
                creationflags=flags
            )

    def stop_and_hide(self):
        self.player.stop()
        self.setVisible(False)

    # -------------------------------------------------------------
    # Audio Output Device Engine & Dynamic Migration
    # -------------------------------------------------------------
    def _check_audio_device_watchdog(self):
        """Periodically checks if Windows default audio endpoint changed while in auto mode."""
        if self._selected_device_id is not None:
            return
        default_dev = self.media_devices.defaultAudioOutput()
        if default_dev.isNull():
            return
        cur_id = bytes(default_dev.id())
        if cur_id != self._current_device_id:
            logger.info(f"Windows default audio device changed: {default_dev.description()}")
            self._switch_audio_device(default_dev, is_auto=True)

    def _on_audio_outputs_changed(self):
        """Fired by Qt when audio endpoints are connected or disconnected."""
        logger.info("Windows audio outputs topology change detected")
        if self._selected_device_id is None:
            default_dev = self.media_devices.defaultAudioOutput()
            if not default_dev.isNull() and bytes(default_dev.id()) != self._current_device_id:
                self._switch_audio_device(default_dev, is_auto=True)
        else:
            # Check if user-selected device is still present
            all_devs = self.media_devices.audioOutputs()
            matching = [d for d in all_devs if bytes(d.id()) == self._selected_device_id]
            if not matching:
                logger.info("Selected audio device disconnected; reverting to system default")
                self._selected_device_id = None
                self._switch_audio_device(self.media_devices.defaultAudioOutput(), is_auto=True)
        self._update_device_btn_tooltip()

    def _switch_audio_device(self, new_device: QAudioDevice, is_auto: bool = True):
        """
        Dynamically migrates playback to new audio device endpoint without interrupting playback.
        Preserves track position and active playing state.
        """
        if new_device.isNull():
            return

        new_id = bytes(new_device.id())
        self._current_device_id = new_id
        self._current_device_name = new_device.description()
        if is_auto:
            self._selected_device_id = None
        else:
            self._selected_device_id = new_id

        was_playing = (self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState)
        pos = self.player.position()

        try:
            self.audio_output.setDevice(new_device)
            logger.info(f"Audio output migrated to: {new_device.description()} (auto={is_auto})")
        except Exception as e:
            logger.warning(f"Failed to switch audio output device: {e}")

        if was_playing:
            if self.player.playbackState() != QMediaPlayer.PlaybackState.PlayingState:
                self.player.setPosition(pos)
                self.player.play()

        self._update_device_btn_tooltip()

    def _update_device_btn_tooltip(self):
        if not hasattr(self, "device_btn"):
            return
        mode_str = "Auto: System Default" if self._selected_device_id is None else "Manual"
        self.device_btn.setToolTip(
            f"Audio Output: {self._current_device_name} ({mode_str})\n"
            "Click to switch output device"
        )

    def _show_device_menu(self):
        """Displays popup menu with system default and available audio devices."""
        menu = RoundMenu(parent=self)

        is_auto = (self._selected_device_id is None)
        auto_prefix = "✓ " if is_auto else "   "
        act_auto = Action(f"{auto_prefix}System Default (Auto-Switch)", self)
        act_auto.triggered.connect(lambda: self._switch_audio_device(self.media_devices.defaultAudioOutput(), is_auto=True))
        menu.addAction(act_auto)
        menu.addSeparator()

        all_devs = self.media_devices.audioOutputs()
        for dev in all_devs:
            dev_id = bytes(dev.id())
            desc = dev.description()
            is_active = (self._selected_device_id == dev_id) or (is_auto and dev_id == self._current_device_id)
            prefix = "✓ " if is_active else "   "
            act = Action(f"{prefix}{desc}", self)
            act.triggered.connect(lambda checked=False, d=dev: self._switch_audio_device(d, is_auto=False))
            menu.addAction(act)

        pos = self.device_btn.mapToGlobal(QPoint(0, -menu.sizeHint().height() - 5))
        menu.exec(pos)

    # -------------------------------------------------------------
    # Public Playback Transport Interface
    # -------------------------------------------------------------
    def toggle_play_pause(self):
        """Toggles playback between play and pause."""
        self._toggle_play_pause()

    def seek_relative(self, delta_ms: int):
        """Seeks forward or backward by delta_ms milliseconds."""
        self._seek_relative(delta_ms)

    def toggle_mute(self):
        """Toggles audio mute state."""
        self._toggle_mute()

    def adjust_volume(self, delta_percent: int):
        """Adjusts playback volume by delta_percent (+/- 1-100)."""
        curr = self.volume_slider.value()
        new_val = max(0, min(100, curr + delta_percent))
        self.volume_slider.setValue(new_val)

    def toggle_shuffle(self):
        """Toggles shuffle mode."""
        self._toggle_shuffle()

    def toggle_repeat(self):
        """Cycles repeat mode."""
        self._toggle_repeat()

    @staticmethod
    def _format_ms(ms: int) -> str:
        secs = max(0, ms // 1000)
        mins = secs // 60
        rem_secs = secs % 60
        return f"{mins:02d}:{rem_secs:02d}"
