import os
import threading
import logging
from typing import Optional, Dict, Any, List

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame
)
from qfluentwidgets import (
    MessageBoxBase, SubtitleLabel, StrongBodyLabel, BodyLabel, CaptionLabel,
    PushButton, PrimaryPushButton, ProgressBar, CardWidget, SmoothScrollArea,
    FluentIcon, InfoBar
)

from core.utils import inspect_audio_spectrum
from gui.styles import TEXT_MUTED

logger = logging.getLogger("gui.dialogs.spectrum_dialog")


class AudioSpectrumDialog(MessageBoxBase):
    """
    True Audio Spectrum & Fake-Bitrate Inspector Dialog.
    Analyzes ultrasonic frequency cutoff (e.g., 15.5 kHz transcode shelf vs 20.5 kHz true master),
    displays a visual RGB spectrogram + high-frequency band chart, and allows one-click track upgrading.
    """

    sig_analysis_ready = pyqtSignal(object)

    def __init__(self, file_path: str, track_title: str = "", track_artist: str = "", track=None, on_upgrade_callback=None, parent=None):
        super().__init__(parent)
        self.file_path = file_path
        self.track = track
        if track and not track_title:
            track_title = getattr(track, "title", "")
        if track and not track_artist:
            track_artist = getattr(track, "artist_str", "")
        self.track_title = track_title or os.path.splitext(os.path.basename(file_path))[0]
        self.track_artist = track_artist
        self.on_upgrade_callback = on_upgrade_callback
        self.result_data: Optional[Dict[str, Any]] = None

        self.widget.setMinimumWidth(700)
        self.widget.setMinimumHeight(540)

        self.titleLabel = SubtitleLabel("True Audio Spectrum & Bitrate Inspector", self)
        self.viewLayout.addWidget(self.titleLabel)

        sub = CaptionLabel(f"{self.track_title}" + (f" — {self.track_artist}" if self.track_artist else ""), self)
        sub.setTextColor(TEXT_MUTED, TEXT_MUTED)
        self.viewLayout.addWidget(sub)

        # Verdict Banner Card
        self.verdict_card = CardWidget(self)
        v_lay = QHBoxLayout(self.verdict_card)
        v_lay.setContentsMargins(14, 10, 14, 10)
        v_lay.setSpacing(12)

        self.verdict_title_lbl = StrongBodyLabel("Analyzing ultrasonic frequency spectrum...", self.verdict_card)
        self.verdict_title_lbl.setStyleSheet("font-size: 14px; font-weight: 700; color: #FFFFFF;")
        self.verdict_sub_lbl = CaptionLabel("Decoding core PCM stream & computing Goertzel DFT + RGB Spectrogram...", self.verdict_card)
        self.verdict_sub_lbl.setTextColor(TEXT_MUTED, TEXT_MUTED)

        v_text_col = QVBoxLayout()
        v_text_col.setSpacing(2)
        v_text_col.addWidget(self.verdict_title_lbl)
        v_text_col.addWidget(self.verdict_sub_lbl)
        v_lay.addLayout(v_text_col, 1)

        self.upgrade_btn = PrimaryPushButton(FluentIcon.DOWNLOAD, "Upgrade / Re-Download Track", self.verdict_card)
        self.upgrade_btn.setFixedHeight(32)
        self.upgrade_btn.setVisible(False)
        self.upgrade_btn.clicked.connect(self._on_upgrade_clicked)
        v_lay.addWidget(self.upgrade_btn)

        self.viewLayout.addWidget(self.verdict_card)

        # Technical Metrics Row
        metrics_row = QHBoxLayout()
        metrics_row.setSpacing(10)
        self.metric_codec = self._make_metric_box("Container / Codec", "...")
        self.metric_claimed = self._make_metric_box("Container Bitrate", "...")
        self.metric_true = self._make_metric_box("True Effective Quality", "...")
        self.metric_cutoff = self._make_metric_box("Ultrasonic Cutoff", "...")
        metrics_row.addWidget(self.metric_codec[0], 1)
        metrics_row.addWidget(self.metric_claimed[0], 1)
        metrics_row.addWidget(self.metric_true[0], 1)
        metrics_row.addWidget(self.metric_cutoff[0], 1)
        self.viewLayout.addLayout(metrics_row)

        # Spectrogram Image Box
        self.spec_frame = QFrame(self)
        self.spec_frame.setMinimumHeight(230)
        self.spec_frame.setStyleSheet("""
            QFrame {
                background-color: #121212;
                border: 1px solid rgba(255, 255, 255, 0.10);
                border-radius: 8px;
            }
        """)
        spec_lay = QVBoxLayout(self.spec_frame)
        spec_lay.setContentsMargins(6, 6, 6, 6)
        self.spec_img_lbl = QLabel("Rendering 20 Hz – 22 kHz Spectrogram...", self.spec_frame)
        self.spec_img_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.spec_img_lbl.setStyleSheet("color: #888888; font-size: 12px; border: none;")
        spec_lay.addWidget(self.spec_img_lbl, 1)
        self.viewLayout.addWidget(self.spec_frame, 1)

        # High-Frequency Shelf Bar Breakdown (12 kHz -> 21.2 kHz)
        self.bands_card = CardWidget(self)
        self.bands_card.setStyleSheet("CardWidget { background-color: #1b1b1b; border-radius: 8px; }")
        self.bands_lay = QHBoxLayout(self.bands_card)
        self.bands_lay.setContentsMargins(12, 8, 12, 8)
        self.bands_lay.setSpacing(8)
        self.viewLayout.addWidget(self.bands_card)

        self.yesButton.setText("Close")
        self.cancelButton.setVisible(False)

        self.sig_analysis_ready.connect(self._on_analysis_ready)
        threading.Thread(target=self._run_worker, daemon=True, name="SpectrumInspectorWorker").start()

    def _make_metric_box(self, title: str, val: str):
        card = CardWidget(self)
        card.setStyleSheet("CardWidget { background-color: #1e1e1e; border: 1px solid rgba(255,255,255,0.07); border-radius: 6px; }")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(10, 6, 10, 6)
        lay.setSpacing(2)
        t_lbl = CaptionLabel(title, card)
        t_lbl.setTextColor(TEXT_MUTED, TEXT_MUTED)
        v_lbl = StrongBodyLabel(val, card)
        v_lbl.setStyleSheet("font-size: 13px; font-weight: 700; color: #FFFFFF;")
        lay.addWidget(t_lbl)
        lay.addWidget(v_lbl)
        return card, v_lbl

    def _run_worker(self):
        res = inspect_audio_spectrum(self.file_path, generate_spectrogram=True)
        self.sig_analysis_ready.emit(res)

    def _on_analysis_ready(self, res: Optional[Dict[str, Any]]):
        if not res:
            self.verdict_title_lbl.setText("Could Not Analyze Audio Spectrum")
            self.verdict_sub_lbl.setText("Verify that FFmpeg is available and the audio file is not corrupted.")
            return

        self.result_data = res
        verdict = res.get("verdict", "good")
        cutoff = res.get("cutoff_khz", 0.0)
        claimed_br = res.get("container_bitrate_kbps", 0)
        true_br = res.get("estimated_true_kbps", 0)
        codec = res.get("codec", "AUDIO")
        sr = res.get("sample_rate", 44100)
        bps = res.get("bits_per_sample", 16)

        self.metric_codec[1].setText(f"{codec} ({sr // 1000}.{ (sr % 1000) // 100 } kHz / {bps}-bit)")
        self.metric_claimed[1].setText(f"{claimed_br} kbps" if claimed_br else "Lossless")
        self.metric_true[1].setText("Lossless / 320k" if cutoff >= 19.8 else f"~{true_br} kbps")
        self.metric_cutoff[1].setText(f"{cutoff:.1f} kHz")

        if verdict == "authentic":
            self.verdict_title_lbl.setText(f"✓ {res.get('verdict_title')}")
            self.verdict_title_lbl.setStyleSheet("font-size: 14px; font-weight: 700; color: #4ADE80;")
            self.verdict_sub_lbl.setText(
                f"Full ultrasonic frequency extension detected up to {cutoff:.1f} kHz. No lossy low-bitrate transcode shelf found."
            )
            self.verdict_card.setStyleSheet("CardWidget { background-color: rgba(74, 222, 128, 0.10); border: 1px solid rgba(74, 222, 128, 0.35); border-radius: 8px; }")
            self.upgrade_btn.setVisible(bool(self.on_upgrade_callback))
            self.upgrade_btn.setText("Re-Download Track")
        elif verdict == "good":
            self.verdict_title_lbl.setText(f"✓ {res.get('verdict_title')}")
            self.verdict_title_lbl.setStyleSheet("font-size: 14px; font-weight: 700; color: #60A5FA;")
            self.verdict_sub_lbl.setText(
                f"Clean high-frequency extension up to {cutoff:.1f} kHz."
            )
            self.verdict_card.setStyleSheet("CardWidget { background-color: rgba(96, 165, 250, 0.10); border: 1px solid rgba(96, 165, 250, 0.35); border-radius: 8px; }")
            self.upgrade_btn.setVisible(bool(self.on_upgrade_callback))
        else:
            self.verdict_title_lbl.setText(f"⚠️ {res.get('verdict_title')}")
            self.verdict_title_lbl.setStyleSheet("font-size: 14px; font-weight: 700; color: #FBBF24;")
            self.verdict_sub_lbl.setText(
                f"Sharp high-frequency brickwall cutoff detected at {cutoff:.1f} kHz (claimed {claimed_br} kbps {codec}, true effective quality ~{true_br} kbps)."
            )
            self.verdict_card.setStyleSheet("CardWidget { background-color: rgba(251, 191, 36, 0.12); border: 1px solid rgba(251, 191, 36, 0.40); border-radius: 8px; }")
            if self.on_upgrade_callback:
                self.upgrade_btn.setVisible(True)
                self.upgrade_btn.setText("Upgrade / Re-Download True 320k")

        # Load spectrogram image
        spec_path = res.get("spectrogram_path", "")
        if spec_path and os.path.isfile(spec_path):
            pix = QPixmap(spec_path)
            if not pix.isNull():
                scaled = pix.scaled(660, 220, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                self.spec_img_lbl.setText("")
                self.spec_img_lbl.setPixmap(scaled)

        # Populate ultrasonic energy readout
        band_db = res.get("band_db", {})
        for f_hz in [8000, 12000, 15000, 16000, 17000, 18000, 19000, 19800, 20500]:
            db_v = band_db.get(f_hz, -95.0)
            col = QVBoxLayout()
            col.setSpacing(2)
            col.setAlignment(Qt.AlignmentFlag.AlignCenter)
            f_str = f"{f_hz / 1000.0:.1f}k".replace(".0k", "k")
            val_c = "#4ADE80" if db_v > -62.0 else ("#FBBF24" if db_v > -75.0 else "#666666")
            v_l = CaptionLabel(f"{db_v:.0f} dB", self.bands_card)
            v_l.setStyleSheet(f"color: {val_c}; font-weight: 700; font-size: 11px;")
            f_l = CaptionLabel(f_str, self.bands_card)
            f_l.setTextColor(TEXT_MUTED, TEXT_MUTED)
            col.addWidget(v_l, 0, Qt.AlignmentFlag.AlignCenter)
            col.addWidget(f_l, 0, Qt.AlignmentFlag.AlignCenter)
            self.bands_lay.addLayout(col)

    def _on_upgrade_clicked(self):
        if self.on_upgrade_callback:
            try:
                self.on_upgrade_callback(self.file_path, self.track)
            except TypeError:
                self.on_upgrade_callback()
            self.accept()


class BatchSpectrumScannerDialog(MessageBoxBase):
    """
    Batch Library Fake-Bitrate & Ultrasonic Spectrum Scanner Dialog.
    Scans all downloaded songs in the library, flags upscaled/transcoded files (< 16.8 kHz cutoff),
    and lets the user upgrade all flagged songs with one click.
    """

    sig_progress = pyqtSignal(int, int, str)
    sig_finished = pyqtSignal(list)

    def __init__(self, archive_manager, queue_manager=None, on_upgrade_tracks_callback=None, parent=None):
        super().__init__(parent)
        self.archive = archive_manager
        self.qm = queue_manager
        self.on_upgrade_tracks_callback = on_upgrade_tracks_callback
        self.flagged_tracks: List[Dict[str, Any]] = []

        self.widget.setMinimumWidth(680)
        self.widget.setMinimumHeight(500)

        self.titleLabel = SubtitleLabel("Library True-Bitrate & Spectrum Audit", self)
        self.viewLayout.addWidget(self.titleLabel)

        self.status_lbl = CaptionLabel("Scanning downloaded tracks for fake bitrates & ultrasonic frequency cutoffs...", self)
        self.status_lbl.setTextColor(TEXT_MUTED, TEXT_MUTED)
        self.viewLayout.addWidget(self.status_lbl)

        self.prog_bar = ProgressBar(self)
        self.prog_bar.setRange(0, 100)
        self.prog_bar.setValue(0)
        self.viewLayout.addWidget(self.prog_bar)

        self.scroll_area = SmoothScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setMinimumHeight(310)
        self.scroll_area.setStyleSheet("QScrollArea, SmoothScrollArea { background-color: #161616; border-radius: 8px; border: 1px solid rgba(255,255,255,0.08); }")
        self.scroll_area.viewport().setStyleSheet("background-color: #161616;")

        self.list_container = QWidget()
        self.list_container.setStyleSheet("background: transparent;")
        self.list_lay = QVBoxLayout(self.list_container)
        self.list_lay.setContentsMargins(10, 10, 10, 10)
        self.list_lay.setSpacing(6)
        self.list_lay.addStretch(1)
        self.scroll_area.setWidget(self.list_container)
        self.viewLayout.addWidget(self.scroll_area, 1)

        self.upgrade_all_btn = PrimaryPushButton(FluentIcon.DOWNLOAD, "Upgrade Flagged Transcodes (0)", self)
        self.upgrade_all_btn.setEnabled(False)
        self.upgrade_all_btn.clicked.connect(self._upgrade_all_flagged)
        self.viewLayout.addWidget(self.upgrade_all_btn)

        self.yesButton.setText("Close")
        self.cancelButton.setVisible(False)

        self.sig_progress.connect(self._on_progress)
        self.sig_finished.connect(self._on_finished)

        threading.Thread(target=self._worker, daemon=True, name="BatchSpectrumAudit").start()

    def _worker(self):
        results = self.archive.scan_library_spectrum(
            progress_callback=lambda cur, tot, msg: self.sig_progress.emit(cur, tot, msg)
        )
        self.sig_finished.emit(results)

    def _on_progress(self, cur: int, tot: int, msg: str):
        pct = int(cur / max(1, tot) * 100)
        self.prog_bar.setValue(pct)
        self.status_lbl.setText(f"[{cur}/{tot}] {msg}")

    def _on_finished(self, results: List[Dict[str, Any]]):
        self.prog_bar.setValue(100)
        upscaled = [r for r in results if r.get("verdict") == "upscaled"]
        authentic = len(results) - len(upscaled)
        self.flagged_tracks = upscaled
        self.status_lbl.setText(
            f"Audit Complete: {len(results)} track(s) analyzed — {authentic} authentic high-bitrate, {len(upscaled)} upscaled/low-cutoff transcode(s) found."
        )

        if upscaled and (self.qm or self.on_upgrade_tracks_callback):
            self.upgrade_all_btn.setEnabled(True)
            self.upgrade_all_btn.setText(f"Upgrade All Flagged Tracks ({len(upscaled)})")

        for r in results[:120]:
            card = CardWidget(self.list_container)
            is_up = r.get("verdict") == "upscaled"
            border_c = "rgba(251, 191, 36, 0.35)" if is_up else "rgba(255, 255, 255, 0.06)"
            card.setStyleSheet(f"CardWidget {{ background-color: #1f1f1f; border: 1px solid {border_c}; border-radius: 6px; }}")
            row = QHBoxLayout(card)
            row.setContentsMargins(12, 6, 12, 6)
            row.setSpacing(10)

            title = r.get("title") or os.path.basename(r.get("file_path", ""))
            artist = r.get("artist") or ""
            lbl = StrongBodyLabel(f"{title}" + (f" — {artist}" if artist else ""), card)
            lbl.setStyleSheet("font-size: 12px; color: #FFFFFF;")
            row.addWidget(lbl, 1)

            badge_txt = f"{r.get('cutoff_khz', 0):.1f} kHz  •  {r.get('verdict_title', '')}"
            badge = CaptionLabel(badge_txt, card)
            badge.setStyleSheet(f"color: {'#FBBF24' if is_up else '#4ADE80'}; font-weight: 600;")
            row.addWidget(badge)

            self.list_lay.insertWidget(self.list_lay.count() - 1, card)

    def _upgrade_all_flagged(self):
        if not self.flagged_tracks or (not self.qm and not self.on_upgrade_tracks_callback):
            return
        from core.spotify_client import TrackMetadata
        to_queue = []
        for r in self.flagged_tracks:
            fp = r.get("file_path", "")
            sid = r.get("spotify_id", "")
            meta = self.archive.get_track_by_path(fp) if fp else None
            if not meta and sid:
                meta = self.archive.find_track(spotify_id=sid)
            if meta:
                if fp and os.path.exists(fp):
                    try:
                        os.remove(fp)
                    except Exception:
                        pass
                self.archive.remove_downloaded_track(meta["spotify_id"])
                to_queue.append(TrackMetadata(
                    id=meta["spotify_id"],
                    title=meta["title"],
                    artists=[a.strip() for a in meta["artist"].split(",")],
                    album=meta.get("album", ""),
                    duration_ms=meta.get("duration_ms", 0),
                    collection_name=meta.get("collection_name", ""),
                    collection_type=meta.get("collection_type", "track"),
                ))
        if to_queue:
            if self.on_upgrade_tracks_callback:
                self.on_upgrade_tracks_callback(to_queue)
            elif self.qm:
                self.qm.enqueue(to_queue)
                self.qm.start_all()
                InfoBar.success("Upgrading Tracks", f"Queued {len(to_queue)} track(s) for fresh high-bitrate download.", duration=4000, parent=self.window())
            self.accept()
