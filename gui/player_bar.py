import os
import re
import logging
from typing import Optional, List, Tuple

from PyQt6.QtCore import Qt, QUrl, QTime
from PyQt6.QtGui import QImage, QPixmap, QPainter, QPainterPath
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QFrame, QApplication
)
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from qfluentwidgets import (
    ToolButton, Slider, FluentIcon, CaptionLabel, StrongBodyLabel,
    BodyLabel, IconWidget, RoundMenu, Action
)

from core.spotify_client import TrackMetadata
from core.archive import resolve_collection_cover
from gui.queue_delegate import extract_embedded_cover, ThumbnailCache
from gui.styles import TEXT_MUTED, TEXT_PRIMARY, BG_CARD, SPOTIFY_EMERALD

logger = logging.getLogger("gui.player_bar")


class MiniPlayerBar(QFrame):
    """
    Windows 11 Fluent In-App Mini-Player Dock.
    Features:
    - Integrated native audio decoding via PyQt6.QtMultimedia (FLAC, MP3, Opus, M4A, OGG).
    - Live CRLF synchronized karaoke lyrics banner with active line highlighting and next-line preview.
    - Album artwork thumbnail, track title, artist name, and audio quality badge.
    - Interactive seek slider with smooth time updates and volume controls.
    - 'Show in Explorer' quick action and collapsible dock.
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
        self.lyrics_timeline: List[Tuple[int, str]] = []  # List of (timestamp_ms, text)
        self.last_lyric_idx: int = -1
        self._user_seeking: bool = False

        # Initialize QtMultimedia Player and AudioOutput
        self.audio_output = QAudioOutput(self)
        self.audio_output.setVolume(0.85)

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
        self.cover_label.setStyleSheet("""
            QLabel {
                background-color: #262626;
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 6px;
            }
        """)
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
        # Center Section: Live Karaoke Banner + Next/Prev Controls + Seek Slider
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

        karaoke_container.addWidget(self.active_lyric_label)
        karaoke_container.addWidget(self.next_lyric_label)
        center_layout.addLayout(karaoke_container)

        # 2. Controls Row: Rewind, Previous, Play/Pause, Next, Forward
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_row.setContentsMargins(0, 0, 0, 0)
        btn_row.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.rewind_btn = ToolButton(FluentIcon.PAGE_LEFT, self)
        self.rewind_btn.setToolTip("Rewind 10 seconds")
        self.rewind_btn.setFixedSize(26, 26)
        self.rewind_btn.clicked.connect(lambda: self._seek_relative(-10000))

        self.prev_btn = ToolButton(FluentIcon.SKIP_BACK, self)
        self.prev_btn.setToolTip("Previous Track")
        self.prev_btn.setFixedSize(28, 28)
        self.prev_btn.clicked.connect(self.play_previous)

        self.play_btn = ToolButton(FluentIcon.PLAY, self)
        self.play_btn.setToolTip("Play / Pause")
        self.play_btn.setFixedSize(32, 32)
        self.play_btn.clicked.connect(self._toggle_play_pause)

        self.next_btn = ToolButton(FluentIcon.SKIP_FORWARD, self)
        self.next_btn.setToolTip("Next Track")
        self.next_btn.setFixedSize(28, 28)
        self.next_btn.clicked.connect(self.play_next)

        self.forward_btn = ToolButton(FluentIcon.PAGE_RIGHT, self)
        self.forward_btn.setToolTip("Forward 10 seconds")
        self.forward_btn.setFixedSize(26, 26)
        self.forward_btn.clicked.connect(lambda: self._seek_relative(10000))

        btn_row.addWidget(self.rewind_btn)
        btn_row.addWidget(self.prev_btn)
        btn_row.addWidget(self.play_btn)
        btn_row.addWidget(self.next_btn)
        btn_row.addWidget(self.forward_btn)
        center_layout.addLayout(btn_row)

        # 3. Seek Slider Row with Time Labels on both sides
        seek_row = QHBoxLayout()
        seek_row.setSpacing(8)
        seek_row.setContentsMargins(0, 0, 0, 0)

        self.curr_time_label = CaptionLabel("00:00", self)
        self.curr_time_label.setTextColor(TEXT_MUTED, TEXT_MUTED)
        self.curr_time_label.setFixedWidth(38)
        self.curr_time_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.seek_slider = Slider(Qt.Orientation.Horizontal, self)
        self.seek_slider.setRange(0, 1000)
        self.seek_slider.setValue(0)
        self.seek_slider.sliderPressed.connect(self._on_seek_started)
        self.seek_slider.sliderReleased.connect(self._on_seek_finished)
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

        self.volume_btn = ToolButton(FluentIcon.VOLUME, self)
        self.volume_btn.setToolTip("Mute / Unmute")
        self.volume_btn.setFixedSize(28, 28)
        self.volume_btn.clicked.connect(self._toggle_mute)

        self.volume_slider = Slider(Qt.Orientation.Horizontal, self)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(85)
        self.volume_slider.setFixedWidth(75)
        self.volume_slider.valueChanged.connect(self._on_volume_changed)

        self.folder_btn = ToolButton(FluentIcon.FOLDER, self)
        self.folder_btn.setToolTip("Show in Explorer")
        self.folder_btn.setFixedSize(28, 28)
        self.folder_btn.clicked.connect(self._open_in_explorer)

        self.close_btn = ToolButton(FluentIcon.CLOSE, self)
        self.close_btn.setToolTip("Stop & Close Player")
        self.close_btn.setFixedSize(28, 28)
        self.close_btn.clicked.connect(self.stop_and_hide)

        right_layout.addWidget(self.volume_btn)
        right_layout.addWidget(self.volume_slider)
        right_layout.addWidget(self.folder_btn)
        right_layout.addWidget(self.close_btn)

        main_layout.addLayout(right_layout, 0)

    # -------------------------------------------------------------
    # Playlist & Navigation Engine
    # -------------------------------------------------------------
    def set_playlist(self, playlist: List[Any], current_index: int = -1):
        """Sets the active playlist for Previous/Next song navigation."""
        self.playlist = list(playlist)
        self.current_index = current_index
        self._update_nav_state()

    def _update_nav_state(self):
        has_items = len(self.playlist) > 0
        self.prev_btn.setEnabled(has_items)
        self.next_btn.setEnabled(has_items)

    def play_index(self, index: int):
        if not self.playlist or index < 0 or index >= len(self.playlist):
            return
        self.current_index = index
        self._play_item(self.playlist[index])
        self._update_nav_state()

    def play_next(self):
        """Advances to the next track in the active playlist."""
        if not self.playlist:
            return
        next_idx = self.current_index + 1
        if next_idx < len(self.playlist):
            self.play_index(next_idx)
        elif len(self.playlist) > 1:
            # Loop back to first song
            self.play_index(0)

    def play_previous(self):
        """Plays the previous track in the playlist, or restarts current if played > 3 seconds."""
        if not self.playlist:
            if self.player.position() > 3000:
                self.player.setPosition(0)
            return
        if self.player.position() > 3000:
            self.player.setPosition(0)
            return
        prev_idx = self.current_index - 1
        if prev_idx >= 0:
            self.play_index(prev_idx)
        elif len(self.playlist) > 1:
            self.play_index(len(self.playlist) - 1)

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

    def _on_media_status_changed(self, status: QMediaPlayer.MediaStatus):
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            if self.playlist and len(self.playlist) > 0:
                self.play_next()

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
                    (i for i, it in enumerate(self.playlist) if getattr(it, "output_path", "") == file_path or getattr(it, "file_path", "") == file_path),
                    -1
                )
            self._update_nav_state()

        self.current_file_path = file_path
        self.current_track = track
        self.current_quality_badge = quality_badge

        # Title & Artist display
        title = track.title if track else os.path.splitext(os.path.basename(file_path))[0]
        artist = track.artist_str if track else "Local Audio"
        self.title_label.setText(title)
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
                for child in self.cover_label.findChildren(QWidget):
                    child.deleteLater()
                self.cover_label.setPixmap(pix)

    def _load_cover(self, file_path: str, track: Optional[TrackMetadata]):
        # Clean any existing child icon widgets
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
                self.cover_label.setPixmap(pix)
                return
            else:
                self.thumb_cache.load_async(thumb_key)

        # 4. Fallback: Sleek music note icon placeholder
        self.cover_label.clear()
        icon_w = IconWidget(FluentIcon.MUSIC, self.cover_label)
        icon_w.setFixedSize(28, 28)
        icon_w.move(11, 11)
        icon_w.show()

    def _set_cover_pixmap(self, img: QImage):
        for child in self.cover_label.findChildren(QWidget):
            child.deleteLater()
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
            self.active_lyric_label.setText(f"♪ {track.title if track else 'Playing Audio'} ♪")
            self.next_lyric_label.setText("")
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
            self.next_lyric_label.setText(self.lyrics_timeline[1][1] if len(self.lyrics_timeline) > 1 else "")
        else:
            self.active_lyric_label.setText("♪ Synchronized Karaoke Lyrics ♪")
            self.next_lyric_label.setText("")

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
                else:
                    self.next_lyric_label.setText("")

    def _on_player_duration_changed(self, dur_ms: int):
        self.total_time_label.setText(self._format_ms(dur_ms))
        self.curr_time_label.setText(self._format_ms(self.player.position()))

    def _on_playback_state_changed(self, state: QMediaPlayer.PlaybackState):
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self.play_btn.setIcon(FluentIcon.PAUSE)
        else:
            self.play_btn.setIcon(FluentIcon.PLAY)

    def _toggle_play_pause(self):
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def _seek_relative(self, delta_ms: int):
        new_pos = max(0, min(self.player.duration(), self.player.position() + delta_ms))
        self.player.setPosition(new_pos)

    def _on_seek_started(self):
        self._user_seeking = True

    def _on_seek_finished(self):
        self._user_seeking = False
        dur_ms = self.player.duration()
        if dur_ms > 0:
            target_pos = int(self.seek_slider.value() / 1000.0 * dur_ms)
            self.player.setPosition(target_pos)

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
        if val == 0:
            self.volume_btn.setIcon(FluentIcon.MUTE)
        else:
            self.volume_btn.setIcon(FluentIcon.VOLUME)

    def _toggle_mute(self):
        if self.audio_output.volume() > 0:
            self._saved_vol = self.audio_output.volume()
            self.audio_output.setVolume(0.0)
            self.volume_slider.setValue(0)
            self.volume_btn.setIcon(FluentIcon.MUTE)
        else:
            restore_vol = getattr(self, "_saved_vol", 0.85) or 0.85
            self.audio_output.setVolume(restore_vol)
            self.volume_slider.setValue(int(restore_vol * 100))
            self.volume_btn.setIcon(FluentIcon.VOLUME)

    def _open_in_explorer(self):
        if self.current_file_path and os.path.isfile(self.current_file_path):
            import subprocess
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
            subprocess.Popen(
                ["explorer", f"/select,{os.path.normpath(self.current_file_path)}"],
                creationflags=flags
            )

    def stop_and_hide(self):
        self.player.stop()
        self.setVisible(False)

    @staticmethod
    def _format_ms(ms: int) -> str:
        secs = max(0, ms // 1000)
        mins = secs // 60
        rem_secs = secs % 60
        return f"{mins:02d}:{rem_secs:02d}"
