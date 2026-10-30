import os
import threading
import logging
from typing import Optional, List, Tuple, Callable

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QImage, QPixmap, QPainter, QPainterPath
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QFileDialog, QApplication
)
from qfluentwidgets import (
    MessageBoxBase, SubtitleLabel, StrongBodyLabel, BodyLabel, CaptionLabel,
    PushButton, PrimaryPushButton, ToolButton, Slider, ComboBox, SwitchButton,
    SmoothScrollArea, CardWidget, FluentIcon, InfoBar, InfoBarPosition
)

from core.config import config
from core.utils import (
    EQ_FREQUENCIES, EQ_PRESETS, apply_equalizer_to_file, extract_embedded_cover
)
from gui.styles import TEXT_MUTED, TEXT_SECONDARY

logger = logging.getLogger("gui.dialogs.player_panels")


class LyricLineRow(QFrame):
    """Interactive clickable lyric line row inside the Karaoke Lyrics Drawer."""

    clicked_timestamp = pyqtSignal(int)

    def __init__(self, timestamp_ms: int, text: str, is_synced: bool = True, parent=None):
        super().__init__(parent)
        self.timestamp_ms = timestamp_ms
        self.lyric_text = text
        self.is_synced = is_synced
        self._is_active = False

        if is_synced and timestamp_ms >= 0:
            self.setCursor(Qt.CursorShape.PointingHandCursor)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 8, 14, 8)
        lay.setSpacing(12)

        mins = max(0, timestamp_ms // 60000)
        secs = max(0, (timestamp_ms % 60000) // 1000)
        ts_str = f"{mins:02d}:{secs:02d}" if (is_synced and timestamp_ms >= 0) else "  •  "

        self.time_lbl = CaptionLabel(ts_str, self)
        self.time_lbl.setFixedWidth(42)
        self.time_lbl.setStyleSheet("color: #666666; font-family: 'Consolas', monospace; font-size: 11px;")

        self.text_lbl = BodyLabel(text, self)
        self.text_lbl.setWordWrap(True)
        self.text_lbl.setStyleSheet("color: #AAAAAA; font-size: 14px; font-weight: 500; background: transparent;")

        lay.addWidget(self.time_lbl, 0, Qt.AlignmentFlag.AlignTop)
        lay.addWidget(self.text_lbl, 1)
        self.set_active(False, is_past=False)

    def set_active(self, active: bool, is_past: bool = False):
        self._is_active = active
        if active:
            self.setStyleSheet("""
                LyricLineRow {
                    background-color: rgba(29, 185, 84, 0.16);
                    border-left: 3px solid #1ED760;
                    border-radius: 6px;
                }
            """)
            self.time_lbl.setStyleSheet("color: #1ED760; font-family: 'Consolas', monospace; font-size: 11px; font-weight: bold; background: transparent;")
            self.text_lbl.setStyleSheet("color: #1ED760; font-size: 16px; font-weight: 700; background: transparent;")
        else:
            self.setStyleSheet("""
                LyricLineRow {
                    background-color: transparent;
                    border-left: 3px solid transparent;
                    border-radius: 6px;
                }
                LyricLineRow:hover {
                    background-color: rgba(255, 255, 255, 0.05);
                }
            """)
            color = "#707070" if is_past else "#CCCCCC"
            self.time_lbl.setStyleSheet("color: #555555; font-family: 'Consolas', monospace; font-size: 11px; background: transparent;")
            self.text_lbl.setStyleSheet(f"color: {color}; font-size: 14px; font-weight: 500; background: transparent;")

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.is_synced and self.timestamp_ms >= 0:
            self.clicked_timestamp.emit(self.timestamp_ms)
        super().mousePressEvent(event)


class KaraokeLyricsDrawer(MessageBoxBase):
    """
    Slide-up Synchronized Karaoke Lyrics Viewer synced in real-time to MiniPlayerBar.
    Supports click-to-seek on any line, live auto-scrolling, and one-click online lyrics fetching.
    """

    sig_lyrics_fetched = pyqtSignal(bool, str)

    def __init__(self, player_bar, parent=None):
        super().__init__(parent or player_bar)
        self.player_bar = player_bar
        self.line_widgets: List[LyricLineRow] = []
        self._active_idx: int = -1

        self.widget.setMinimumWidth(620)
        self.widget.setMinimumHeight(540)

        # Header with Cover Art + Track Info + Sync Badge
        header_card = CardWidget(self)
        header_card.setStyleSheet("""
            CardWidget {
                background-color: #1e1e1e;
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 8px;
            }
        """)
        h_lay = QHBoxLayout(header_card)
        h_lay.setContentsMargins(12, 10, 14, 10)
        h_lay.setSpacing(12)

        self.cover_lbl = QLabel(header_card)
        self.cover_lbl.setFixedSize(48, 48)
        self.cover_lbl.setStyleSheet("background-color: #2a2a2a; border-radius: 6px;")
        h_lay.addWidget(self.cover_lbl)

        meta_v = QVBoxLayout()
        meta_v.setSpacing(2)
        title = self.player_bar.title_label.text() or "No Track Playing"
        artist = self.player_bar.artist_label.text() or ""
        self.title_lbl = StrongBodyLabel(title, header_card)
        self.title_lbl.setStyleSheet("font-size: 15px; font-weight: 700; color: #FFFFFF;")
        self.artist_lbl = CaptionLabel(artist, header_card)
        self.artist_lbl.setTextColor(TEXT_MUTED, TEXT_MUTED)
        meta_v.addWidget(self.title_lbl)
        meta_v.addWidget(self.artist_lbl)
        h_lay.addLayout(meta_v, 1)

        self.mode_badge = QLabel("Synchronized LRC", header_card)
        self.mode_badge.setStyleSheet("""
            QLabel {
                background-color: rgba(29, 185, 84, 0.18);
                color: #1ED760;
                font-size: 11px;
                font-weight: 700;
                padding: 3px 8px;
                border-radius: 4px;
                border: 1px solid rgba(29, 185, 84, 0.35);
            }
        """)
        h_lay.addWidget(self.mode_badge)
        self.viewLayout.addWidget(header_card)

        # Action toolbar row
        tools_row = QHBoxLayout()
        tools_row.setSpacing(8)

        self.fetch_btn = PushButton(FluentIcon.SYNC, "Fetch / Sync Lyrics Online", self)
        self.fetch_btn.setFixedHeight(30)
        self.fetch_btn.clicked.connect(self._fetch_lyrics_online)

        self.copy_btn = PushButton(FluentIcon.COPY, "Copy Lyrics", self)
        self.copy_btn.setFixedHeight(30)
        self.copy_btn.clicked.connect(self._copy_lyrics)

        self.export_btn = PushButton(FluentIcon.SAVE, "Save .lrc File", self)
        self.export_btn.setFixedHeight(30)
        self.export_btn.clicked.connect(self._export_lrc_file)

        tools_row.addWidget(self.fetch_btn)
        tools_row.addWidget(self.copy_btn)
        tools_row.addWidget(self.export_btn)
        tools_row.addStretch(1)

        hint_lbl = CaptionLabel("Tip: Click any timestamped line to jump directly to that part of the song", self)
        hint_lbl.setTextColor(TEXT_MUTED, TEXT_MUTED)
        tools_row.addWidget(hint_lbl)
        self.viewLayout.addLayout(tools_row)

        # Scrollable Karaoke Viewport
        self.scroll_area = SmoothScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setMinimumHeight(330)
        self.scroll_area.setStyleSheet("""
            QScrollArea, SmoothScrollArea {
                background-color: #161616;
                border: 1px solid rgba(255, 255, 255, 0.07);
                border-radius: 8px;
            }
        """)
        self.scroll_area.viewport().setStyleSheet("background-color: #161616;")

        self.lines_container = QWidget()
        self.lines_container.setStyleSheet("background: transparent;")
        self.lines_layout = QVBoxLayout(self.lines_container)
        self.lines_layout.setContentsMargins(10, 16, 10, 16)
        self.lines_layout.setSpacing(4)
        self.lines_layout.addStretch(1)

        self.scroll_area.setWidget(self.lines_container)
        self.viewLayout.addWidget(self.scroll_area, 1)

        self.yesButton.setText("Close")
        self.cancelButton.setVisible(False)

        self.sig_lyrics_fetched.connect(self._on_lyrics_fetched)

        self._load_header_cover()
        self.rebuild_lyrics_view()

        # Live 100ms sync timer while drawer is open
        self._sync_timer = QTimer(self)
        self._sync_timer.setInterval(120)
        self._sync_timer.timeout.connect(self._sync_active_line)
        self._sync_timer.start()

    def _load_header_cover(self):
        fp = self.player_bar.current_file_path
        if fp and os.path.isfile(fp):
            art = extract_embedded_cover(fp)
            if art:
                img = QImage()
                if img.loadFromData(art) and not img.isNull():
                    scaled = img.scaled(48, 48, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
                    pix = QPixmap(48, 48)
                    pix.fill(Qt.GlobalColor.transparent)
                    p = QPainter(pix)
                    p.setRenderHint(QPainter.RenderHint.Antialiasing)
                    path = QPainterPath()
                    path.addRoundedRect(0, 0, 48, 48, 6, 6)
                    p.setClipPath(path)
                    p.drawPixmap(0, 0, QPixmap.fromImage(scaled))
                    p.end()
                    self.cover_lbl.setPixmap(pix)

    def rebuild_lyrics_view(self):
        while self.lines_layout.count() > 1:
            child = self.lines_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        self.line_widgets.clear()
        self._active_idx = -1

        timeline: List[Tuple[int, str]] = list(getattr(self.player_bar, "lyrics_timeline", []))
        is_synced = getattr(self.player_bar, "lyrics_are_synced", True)

        if not timeline:
            self.mode_badge.setText("No Lyrics Embedded")
            empty_lbl = BodyLabel(
                "No lyrics were found embedded in this track.\n"
                "Click 'Fetch / Sync Lyrics Online' above to search LRCLIB for synchronized karaoke lyrics.",
                self.lines_container
            )
            empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty_lbl.setStyleSheet("color: #888888; font-size: 13px; padding: 48px 20px;")
            self.lines_layout.insertWidget(0, empty_lbl)
            return

        if is_synced:
            self.mode_badge.setText(f"Synchronized LRC ({len(timeline)} lines)")
        else:
            self.mode_badge.setText(f"Plain Lyrics ({len(timeline)} lines)")

        for ts_ms, text in timeline:
            row = LyricLineRow(ts_ms, text, is_synced=is_synced, parent=self.lines_container)
            row.clicked_timestamp.connect(self._on_line_clicked)
            self.lines_layout.insertWidget(self.lines_layout.count() - 1, row)
            self.line_widgets.append(row)

        self._sync_active_line(force=True)

    def _on_line_clicked(self, timestamp_ms: int):
        if self.player_bar and self.player_bar.player.duration() > 0:
            self.player_bar.player.setPosition(timestamp_ms)
            self._sync_active_line(force=True)

    def _sync_active_line(self, force: bool = False):
        if not self.line_widgets or not getattr(self.player_bar, "lyrics_are_synced", True):
            return
        pos_ms = self.player_bar.player.position()
        idx = -1
        for i, w in enumerate(self.line_widgets):
            if w.timestamp_ms <= pos_ms:
                idx = i
            else:
                break

        if idx != self._active_idx or force:
            self.update_active_line(idx)

    def set_track_info(self, title: str, artist: str, timeline: List[Tuple[int, str]], plain_text: str = "", has_synced: bool = True):
        self.title_lbl.setText(title)
        self.artist_lbl.setText(artist)
        if self.player_bar:
            self.player_bar.lyrics_timeline = list(timeline)
            self.player_bar.lyrics_are_synced = has_synced
        self.rebuild_lyrics_view()

    def update_active_line(self, idx: int):
        self._active_idx = idx
        for i, w in enumerate(self.line_widgets):
            w.set_active(i == idx, is_past=(i < idx))
        if 0 <= idx < len(self.line_widgets):
            target_w = self.line_widgets[idx]
            QTimer.singleShot(10, lambda: self.scroll_area.ensureWidgetVisible(target_w, 0, 120))

    def _fetch_lyrics_online(self):
        fp = self.player_bar.current_file_path
        if not fp or not os.path.isfile(fp):
            return
        track = self.player_bar.current_track
        title = track.title if track else self.player_bar.title_label.text()
        artist = track.artist_str if track else self.player_bar.artist_label.text()
        album = getattr(track, "album", "") if track else ""
        dur_ms = (getattr(track, "duration_ms", 0) if track else 0) or self.player_bar.player.duration()

        self.fetch_btn.setEnabled(False)
        self.fetch_btn.setText("Fetching from LRCLIB...")

        def worker():
            try:
                from core.lyrics import LyricsEngine
                from core.tagger import AudioTagger
                from core.spotify_client import TrackMetadata

                eng = LyricsEngine()
                t_meta = track or TrackMetadata(
                    id="local",
                    title=title,
                    artists=[a.strip() for a in artist.split(",") if a.strip()] or ["Unknown"],
                    album=album,
                    duration_ms=dur_ms
                )
                lyr = eng.fetch_lyrics(t_meta)
                if lyr and (lyr.get("synced") or lyr.get("plain")):
                    AudioTagger().tag_file(fp, t_meta, lyrics_data=lyr, embed_art=False, embed_lyrics=True)
                    if lyr.get("synced"):
                        base, _ = os.path.splitext(fp)
                        eng.save_lrc_file(lyr["synced"], f"{base}.lrc")
                    self.sig_lyrics_fetched.emit(True, "Synchronized lyrics fetched and embedded!" if lyr.get("synced") else "Plain lyrics fetched and embedded!")
                else:
                    self.sig_lyrics_fetched.emit(False, "No lyrics found on LRCLIB for this track.")
            except Exception as e:
                self.sig_lyrics_fetched.emit(False, str(e))

        threading.Thread(target=worker, daemon=True, name="LiveLyricsFetch").start()

    def _on_lyrics_fetched(self, ok: bool, msg: str):
        self.fetch_btn.setEnabled(True)
        self.fetch_btn.setText("Fetch / Sync Lyrics Online")
        if ok:
            self.player_bar._load_lyrics(self.player_bar.current_file_path, self.player_bar.current_track)
            self.rebuild_lyrics_view()
            InfoBar.success("Lyrics Updated", msg, duration=3500, parent=self)
        else:
            InfoBar.warning("Lyrics Not Found", msg, duration=4000, parent=self)

    def _copy_lyrics(self):
        timeline = getattr(self.player_bar, "lyrics_timeline", [])
        if not timeline:
            return
        text = "\n".join(line for _, line in timeline)
        QApplication.clipboard().setText(text)
        InfoBar.success("Copied", "Copied lyrics to clipboard.", duration=2500, parent=self)

    def _export_lrc_file(self):
        timeline = getattr(self.player_bar, "lyrics_timeline", [])
        fp = self.player_bar.current_file_path
        if not timeline or not fp:
            return
        default_lrc = os.path.splitext(fp)[0] + ".lrc"
        out_path, _ = QFileDialog.getSaveFileName(self, "Save Synchronized .lrc File", default_lrc, "LRC Files (*.lrc)")
        if out_path:
            lines = []
            for ts_ms, txt in timeline:
                mins = max(0, ts_ms // 60000)
                secs = max(0, (ts_ms % 60000) // 1000)
                centis = max(0, (ts_ms % 1000) // 10)
                lines.append(f"[{mins:02d}:{secs:02d}.{centis:02d}] {txt}")
            with open(out_path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
            InfoBar.success("Saved .lrc", f"Exported lyrics to {os.path.basename(out_path)}", duration=3000, parent=self)


class EqualizerDialog(MessageBoxBase):
    """
    10-Band Parametric Equalizer & Bass Boost Studio Panel.
    Provides 12 curated presets, Preamp & Bass Boost controls, 10 ISO octave sliders,
    instant live preview in MiniPlayerBar, and permanent track rendering.
    """

    sig_bake_done = pyqtSignal(bool, str)

    def __init__(self, player_bar, parent=None):
        super().__init__(parent or player_bar)
        self.player_bar = player_bar
        self.band_sliders: List[Slider] = []
        self.band_val_labels: List[CaptionLabel] = []
        self._updating_preset = False

        self.widget.setMinimumWidth(680)
        self.widget.setMinimumHeight(470)

        # Title + Enable Switch + Preset Selector
        top_row = QHBoxLayout()
        top_row.setSpacing(12)

        self.titleLabel = SubtitleLabel("10-Band Equalizer & Bass Boost", self)
        top_row.addWidget(self.titleLabel)
        top_row.addStretch(1)

        en_lbl = CaptionLabel("Enable Live EQ:", self)
        self.enable_switch = SwitchButton(self)
        self.enable_switch.setOnText("On")
        self.enable_switch.setOffText("Off")
        self.enable_switch.setChecked(bool(config.get("ui.eq_enabled", False)))
        self.enable_switch.checkedChanged.connect(self._on_settings_changed)

        top_row.addWidget(en_lbl)
        top_row.addWidget(self.enable_switch)
        self.viewLayout.addLayout(top_row)

        # Preset & Preamp/Bass Boost Card
        ctrl_card = CardWidget(self)
        ctrl_card.setStyleSheet("""
            CardWidget {
                background-color: #1e1e1e;
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 8px;
            }
        """)
        ctrl_lay = QVBoxLayout(ctrl_card)
        ctrl_lay.setContentsMargins(14, 10, 14, 10)
        ctrl_lay.setSpacing(8)

        preset_row = QHBoxLayout()
        preset_row.setSpacing(10)
        preset_lbl = StrongBodyLabel("Acoustic Preset:", ctrl_card)
        self.preset_combo = ComboBox(ctrl_card)
        preset_names = list(EQ_PRESETS.keys()) + ["Custom"]
        self.preset_combo.addItems(preset_names)
        saved_preset = str(config.get("ui.eq_preset", "Flat (Default)"))
        idx = self.preset_combo.findText(saved_preset)
        self.preset_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.preset_combo.setFixedWidth(230)
        self.preset_combo.currentIndexChanged.connect(self._on_preset_selected)

        self.reset_btn = PushButton(FluentIcon.SYNC, "Reset Flat", ctrl_card)
        self.reset_btn.setFixedHeight(30)
        self.reset_btn.clicked.connect(self._reset_flat)

        preset_row.addWidget(preset_lbl)
        preset_row.addWidget(self.preset_combo)
        preset_row.addWidget(self.reset_btn)
        preset_row.addStretch(1)
        ctrl_lay.addLayout(preset_row)

        # Preamp & Sub-Bass Boost Sliders Row
        knobs_row = QHBoxLayout()
        knobs_row.setSpacing(20)

        pre_lbl = CaptionLabel("Preamp:", ctrl_card)
        self.preamp_slider = Slider(Qt.Orientation.Horizontal, ctrl_card)
        self.preamp_slider.setRange(-120, 120)
        pre_init = int(round(float(config.get("ui.eq_preamp", 0.0) or 0.0) * 10))
        self.preamp_slider.setValue(pre_init)
        self.preamp_val_lbl = CaptionLabel(f"{pre_init / 10.0:+.1f} dB", ctrl_card)
        self.preamp_val_lbl.setFixedWidth(54)
        self.preamp_slider.valueChanged.connect(self._on_preamp_or_bass_moved)

        bass_lbl = CaptionLabel("Sub-Bass Boost (85Hz):", ctrl_card)
        self.bass_slider = Slider(Qt.Orientation.Horizontal, ctrl_card)
        self.bass_slider.setRange(-60, 120)
        bass_init = int(round(float(config.get("ui.eq_bass_boost", 0.0) or 0.0) * 10))
        self.bass_slider.setValue(bass_init)
        self.bass_val_lbl = CaptionLabel(f"{bass_init / 10.0:+.1f} dB", ctrl_card)
        self.bass_val_lbl.setFixedWidth(54)
        self.bass_slider.valueChanged.connect(self._on_preamp_or_bass_moved)

        knobs_row.addWidget(pre_lbl)
        knobs_row.addWidget(self.preamp_slider, 1)
        knobs_row.addWidget(self.preamp_val_lbl)
        knobs_row.addSpacing(8)
        knobs_row.addWidget(bass_lbl)
        knobs_row.addWidget(self.bass_slider, 1)
        knobs_row.addWidget(self.bass_val_lbl)
        ctrl_lay.addLayout(knobs_row)

        self.viewLayout.addWidget(ctrl_card)

        # 10-Band Vertical Sliders Rack
        bands_card = CardWidget(self)
        bands_card.setStyleSheet("""
            CardWidget {
                background-color: #171717;
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 8px;
            }
        """)
        bands_lay = QHBoxLayout(bands_card)
        bands_lay.setContentsMargins(16, 14, 16, 14)
        bands_lay.setSpacing(10)

        saved_bands = config.get("ui.eq_bands", [0.0] * 10) or [0.0] * 10
        freq_labels = ["31", "62", "125", "250", "500", "1k", "2k", "4k", "8k", "16k"]

        for i, f_txt in enumerate(freq_labels):
            col = QVBoxLayout()
            col.setSpacing(6)
            col.setAlignment(Qt.AlignmentFlag.AlignHCenter)

            g_val = float(saved_bands[i]) if i < len(saved_bands) else 0.0
            val_lbl = CaptionLabel(f"{g_val:+.1f}", bands_card)
            val_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            val_lbl.setFixedWidth(44)
            val_lbl.setStyleSheet("color: #1ED760; font-size: 11px; font-weight: 600;")

            sl = Slider(Qt.Orientation.Vertical, bands_card)
            sl.setRange(-120, 120)
            sl.setValue(int(round(g_val * 10)))
            sl.setFixedHeight(165)
            sl.valueChanged.connect(lambda v, idx=i: self._on_band_moved(idx, v))

            hz_lbl = CaptionLabel(f_txt, bands_card)
            hz_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            hz_lbl.setTextColor(TEXT_MUTED, TEXT_MUTED)

            col.addWidget(val_lbl, 0, Qt.AlignmentFlag.AlignHCenter)
            col.addWidget(sl, 1, Qt.AlignmentFlag.AlignHCenter)
            col.addWidget(hz_lbl, 0, Qt.AlignmentFlag.AlignHCenter)

            bands_lay.addLayout(col)
            self.band_sliders.append(sl)
            self.band_val_labels.append(val_lbl)

        self.viewLayout.addWidget(bands_card, 1)

        # Bottom Action Row: Apply Live vs Bake Permanently to File
        act_row = QHBoxLayout()
        act_row.setSpacing(10)

        self.apply_live_btn = PrimaryPushButton(FluentIcon.PLAY, "Apply Live EQ to Player", self)
        self.apply_live_btn.setFixedHeight(32)
        self.apply_live_btn.clicked.connect(self._apply_live_now)

        self.bake_btn = PushButton(FluentIcon.SAVE, "Save EQ Permanently to Current Track", self)
        self.bake_btn.setFixedHeight(32)
        self.bake_btn.setToolTip("Applies this 10-band EQ & Bass Boost curve directly to the audio file on disk (preserving all tags & cover art)")
        self.bake_btn.clicked.connect(self._bake_to_current_file)
        if not (self.player_bar and self.player_bar.current_file_path and os.path.isfile(self.player_bar.current_file_path)):
            self.bake_btn.setEnabled(False)

        act_row.addWidget(self.apply_live_btn)
        act_row.addWidget(self.bake_btn)
        act_row.addStretch(1)
        self.viewLayout.addLayout(act_row)

        self.yesButton.setText("Done")
        self.cancelButton.setVisible(False)
        self.sig_bake_done.connect(self._on_bake_done)

    def _on_preset_selected(self, index: int):
        if self._updating_preset:
            return
        name = self.preset_combo.currentText()
        if name not in EQ_PRESETS:
            return
        self._updating_preset = True
        try:
            p = EQ_PRESETS[name]
            pre = float(p.get("preamp", 0.0))
            bass = float(p.get("bass_boost", 0.0))
            bands = list(p.get("bands", [0.0] * 10))
            self.preamp_slider.setValue(int(round(pre * 10)))
            self.preamp_val_lbl.setText(f"{pre:+.1f} dB")
            self.bass_slider.setValue(int(round(bass * 10)))
            self.bass_val_lbl.setText(f"{bass:+.1f} dB")
            for i, sl in enumerate(self.band_sliders):
                gv = float(bands[i]) if i < len(bands) else 0.0
                sl.setValue(int(round(gv * 10)))
                self.band_val_labels[i].setText(f"{gv:+.1f}")
            if name != "Flat (Default)" and not self.enable_switch.isChecked():
                self.enable_switch.setChecked(True)
            self._save_to_config()
        finally:
            self._updating_preset = False

    def _reset_flat(self):
        idx = self.preset_combo.findText("Flat (Default)")
        if idx >= 0:
            self.preset_combo.setCurrentIndex(idx)
        self._apply_live_now()

    def _on_preamp_or_bass_moved(self):
        pre = self.preamp_slider.value() / 10.0
        bass = self.bass_slider.value() / 10.0
        self.preamp_val_lbl.setText(f"{pre:+.1f} dB")
        self.bass_val_lbl.setText(f"{bass:+.1f} dB")
        if not self._updating_preset:
            self._set_combo_custom()
            self._save_to_config()

    def _on_band_moved(self, idx: int, val: int):
        gv = val / 10.0
        self.band_val_labels[idx].setText(f"{gv:+.1f}")
        if not self._updating_preset:
            self._set_combo_custom()
            self._save_to_config()

    def _set_combo_custom(self):
        self._updating_preset = True
        try:
            c_idx = self.preset_combo.findText("Custom")
            if c_idx >= 0:
                self.preset_combo.setCurrentIndex(c_idx)
        finally:
            self._updating_preset = False

    def _on_settings_changed(self, *args):
        self._save_to_config()

    def _get_current_values(self) -> Tuple[bool, str, float, float, List[float]]:
        enabled = self.enable_switch.isChecked()
        preset = self.preset_combo.currentText()
        preamp = round(self.preamp_slider.value() / 10.0, 1)
        bass = round(self.bass_slider.value() / 10.0, 1)
        bands = [round(sl.value() / 10.0, 1) for sl in self.band_sliders]
        return enabled, preset, preamp, bass, bands

    def _save_to_config(self):
        enabled, preset, preamp, bass, bands = self._get_current_values()
        config.set("ui.eq_enabled", enabled, auto_save=False)
        config.set("ui.eq_preset", preset, auto_save=False)
        config.set("ui.eq_preamp", preamp, auto_save=False)
        config.set("ui.eq_bass_boost", bass, auto_save=False)
        config.set("ui.eq_bands", bands, auto_save=True)
        if self.player_bar and hasattr(self.player_bar, "_update_eq_button_state"):
            self.player_bar._update_eq_button_state()

    def _apply_live_now(self):
        self._save_to_config()
        if self.player_bar and hasattr(self.player_bar, "apply_live_equalizer"):
            self.apply_live_btn.setEnabled(False)
            self.apply_live_btn.setText("Applying EQ...")
            self.player_bar.apply_live_equalizer(
                on_done=lambda: (
                    self.apply_live_btn.setEnabled(True),
                    self.apply_live_btn.setText("Apply Live EQ to Player"),
                    InfoBar.success("Equalizer Active", f"Applied '{self.preset_combo.currentText()}' to active playback.", duration=2500, parent=self)
                )
            )

    def _bake_to_current_file(self):
        fp = self.player_bar.current_file_path if self.player_bar else None
        if not fp or not os.path.isfile(fp):
            return
        self._save_to_config()
        _, preset, preamp, bass, bands = self._get_current_values()
        self.bake_btn.setEnabled(False)
        self.bake_btn.setText("Saving EQ to Track...")

        # Pause and release file handle temporarily on Windows if playing raw file
        was_playing = self.player_bar.player.playbackState() == self.player_bar.player.PlaybackState.PlayingState
        pos_ms = self.player_bar.player.position()
        self.player_bar.player.stop()
        from PyQt6.QtCore import QUrl
        self.player_bar.player.setSource(QUrl())

        def worker():
            ok = apply_equalizer_to_file(fp, bands, preamp_db=preamp, bass_boost_db=bass)
            self.sig_bake_done.emit(ok, f"{pos_ms}|{1 if was_playing else 0}|{preset}")

        threading.Thread(target=worker, daemon=True, name="BakeEQWorker").start()

    def _on_bake_done(self, ok: bool, state_str: str):
        self.bake_btn.setEnabled(True)
        self.bake_btn.setText("Save EQ Permanently to Current Track")
        parts = state_str.split("|", 2)
        pos_ms = int(parts[0]) if parts and parts[0].isdigit() else 0
        was_playing = parts[1] == "1" if len(parts) > 1 else False
        preset = parts[2] if len(parts) > 2 else "Custom"

        if self.player_bar and self.player_bar.current_file_path:
            from PyQt6.QtCore import QUrl
            self.player_bar.player.setSource(QUrl.fromLocalFile(self.player_bar.current_file_path))
            self.player_bar.player.setPosition(pos_ms)
            if was_playing:
                self.player_bar.player.play()

        if ok:
            InfoBar.success(
                "Saved to Track",
                f"Permanently applied '{preset}' EQ curve to '{os.path.basename(self.player_bar.current_file_path)}' with all tags preserved.",
                duration=4000,
                parent=self
            )
        else:
            InfoBar.error("EQ Save Failed", "Could not apply equalizer curve to track.", duration=3500, parent=self)

