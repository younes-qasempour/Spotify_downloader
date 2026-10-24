import os
import threading
import subprocess
import logging
from typing import List, Dict, Any, Optional

from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QFileDialog, QStackedWidget
from qfluentwidgets import (
    MessageBoxBase, SubtitleLabel, CaptionLabel, StrongBodyLabel, BodyLabel,
    LineEdit, PushButton, PrimaryPushButton, CheckBox, ComboBox, ProgressBar,
    FluentIcon, CardWidget, InfoBar, InfoBarPosition
)

from core.config import config
from core.exporter import ExportConfig, ExportResult, PlaylistExporter
from gui.styles import TEXT_MUTED, TEXT_PRIMARY, TEXT_SECONDARY, SPOTIFY_EMERALD

logger = logging.getLogger("gui.dialogs.export")


class ExportDialog(MessageBoxBase):
    """
    Fluent Design Modal Dialog for exporting downloaded songs/playlists
    to an external drive, USB stick, SD card, DAP player, or local directory.
    Supports on-the-fly MP3/FLAC/Opus transcoding, portable .m3u8 generation,
    real-time percentage progress, and completion confirmation.
    """

    sig_progress = pyqtSignal(int, int, str)
    sig_finished = pyqtSignal(object)

    def __init__(self, playlist_name: str, tracks: List[Dict[str, Any]], parent=None):
        self._fallback_parent = None
        if parent is None:
            from PyQt6.QtWidgets import QApplication, QWidget
            app = QApplication.instance()
            parent = (app.activeWindow() if app else None)
            if parent is None:
                self._fallback_parent = QWidget()
                parent = self._fallback_parent
        super().__init__(parent)
        self.playlist_name = playlist_name or "Playlist"

        # Filter for tracks that are actually present on disk
        self.valid_tracks = []
        for t in tracks:
            fp = t.get("file_path") if isinstance(t, dict) else getattr(t, "output_path", "")
            if fp and os.path.isfile(fp):
                self.valid_tracks.append(t)

        self.cancel_event = threading.Event()
        self.export_result: Optional[ExportResult] = None
        self._is_running = False

        self._init_ui()
        self._connect_signals()

    def validate(self) -> bool:
        """
        Prevent MessageBoxBase from automatically closing the dialog on yesButton click.
        Export will progress on Page 1 and user closes when done.
        """
        return False

    def closeEvent(self, event):
        """Cancel worker cleanly if user closes dialog while running."""
        if self._is_running:
            self.cancel_event.set()
        super().closeEvent(event)

    def _init_ui(self):
        self.titleLabel = SubtitleLabel("Export Songs to Device / Folder", self)
        self.viewLayout.addWidget(self.titleLabel)

        desc = CaptionLabel(
            "Copy playlist tracks to a USB drive, portable music player, SD card, or local folder.",
            self
        )
        desc.setTextColor(TEXT_MUTED, TEXT_MUTED)
        self.viewLayout.addWidget(desc)

        # Source summary card
        summary_card = CardWidget(self)
        summary_card.setStyleSheet("background-color: rgba(255, 255, 255, 0.04); border-radius: 6px; padding: 6px;")
        summary_layout = QVBoxLayout(summary_card)
        summary_layout.setContentsMargins(12, 10, 12, 10)
        summary_layout.setSpacing(2)

        src_title = StrongBodyLabel(f"Source: {self.playlist_name}", summary_card)
        src_info = CaptionLabel(f"{len(self.valid_tracks)} downloaded song(s) available for export", summary_card)
        src_info.setTextColor(TEXT_MUTED, TEXT_MUTED)
        summary_layout.addWidget(src_title)
        summary_layout.addWidget(src_info)
        self.viewLayout.addWidget(summary_card)

        # Stacked pages: 0 = Settings, 1 = Progress & Complete
        self.pages = QStackedWidget(self)

        # --- Page 0: Settings ---
        self.page_settings = QWidget()
        settings_layout = QVBoxLayout(self.page_settings)
        settings_layout.setContentsMargins(0, 8, 0, 0)
        settings_layout.setSpacing(12)

        # 1. Destination directory picker
        dest_lbl = CaptionLabel("Destination Folder (e.g. USB Drive, SD Card, or Music Folder)", self)
        dest_lbl.setTextColor(TEXT_SECONDARY, TEXT_SECONDARY)
        settings_layout.addWidget(dest_lbl)

        dest_row = QHBoxLayout()
        dest_row.setSpacing(8)

        default_dest = config.get("export.last_destination", "")
        if not default_dest or not os.path.isdir(default_dest):
            default_dest = os.path.expanduser("~/Music")
            if not os.path.isdir(default_dest):
                default_dest = "D:\\" if os.path.isdir("D:\\") else "C:\\"

        self.dest_input = LineEdit(self.page_settings)
        self.dest_input.setPlaceholderText("Select destination directory...")
        self.dest_input.setText(default_dest)
        self.dest_input.setClearButtonEnabled(True)

        self.browse_btn = PushButton(FluentIcon.FOLDER, "Browse...", self.page_settings)
        self.browse_btn.clicked.connect(self._browse_destination)

        dest_row.addWidget(self.dest_input, 1)
        dest_row.addWidget(self.browse_btn)
        settings_layout.addLayout(dest_row)

        # 2. Subfolder option
        self.subfolder_cb = CheckBox(
            f'Create dedicated subfolder for playlist ("{self.playlist_name}")',
            self.page_settings
        )
        self.subfolder_cb.setChecked(config.get("export.create_subfolder", True))
        settings_layout.addWidget(self.subfolder_cb)

        # 3. Audio format selector
        fmt_lbl = CaptionLabel("Export Audio Format", self)
        fmt_lbl.setTextColor(TEXT_SECONDARY, TEXT_SECONDARY)
        settings_layout.addWidget(fmt_lbl)

        self.format_combo = ComboBox(self.page_settings)
        self.format_combo.addItems([
            "Original (Direct Copy - Fastest, 100% Quality)",
            "MP3 320 kbps (Maximum compatibility for Car / MP3 Player)",
            "FLAC (Lossless CD Quality)",
            "Opus (Compact high-efficiency audio)"
        ])

        last_fmt = config.get("export.last_format", "original")
        fmt_map = {"original": 0, "mp3": 1, "flac": 2, "opus": 3}
        self.format_combo.setCurrentIndex(fmt_map.get(last_fmt, 0))
        settings_layout.addWidget(self.format_combo)

        # 4. Additional options
        self.m3u8_cb = CheckBox("Generate portable .m3u8 playlist file in export folder", self.page_settings)
        self.m3u8_cb.setChecked(config.get("export.generate_m3u8", True))
        settings_layout.addWidget(self.m3u8_cb)

        self.skip_cb = CheckBox("Skip tracks already present in destination (fast incremental update)", self.page_settings)
        self.skip_cb.setChecked(config.get("export.skip_existing", True))
        settings_layout.addWidget(self.skip_cb)

        self.pages.addWidget(self.page_settings)

        # --- Page 1: Progress & Complete ---
        self.page_progress = QWidget()
        progress_layout = QVBoxLayout(self.page_progress)
        progress_layout.setContentsMargins(0, 10, 0, 0)
        progress_layout.setSpacing(10)

        self.progress_title = StrongBodyLabel("Exporting tracks...", self.page_progress)
        self.progress_title.setStyleSheet("font-size: 15px; font-weight: 600; color: #FFFFFF;")

        # Counter & percentage row
        stats_row = QHBoxLayout()
        stats_row.setSpacing(8)
        self.progress_counter_label = CaptionLabel("0 of 0 tracks", self.page_progress)
        self.progress_counter_label.setTextColor(TEXT_MUTED, TEXT_MUTED)
        self.progress_pct_label = StrongBodyLabel("0%", self.page_progress)
        self.progress_pct_label.setStyleSheet("color: #1ED760; font-size: 14px; font-weight: 700;")
        stats_row.addWidget(self.progress_counter_label)
        stats_row.addStretch(1)
        stats_row.addWidget(self.progress_pct_label)

        self.progress_bar = ProgressBar(self.page_progress)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(8)

        # Current track caption
        self.progress_caption = CaptionLabel("Preparing tracks for export...", self.page_progress)
        self.progress_caption.setTextColor(TEXT_SECONDARY, TEXT_SECONDARY)
        self.progress_caption.setWordWrap(True)

        # Result card (shown on completion)
        self.result_card = CardWidget(self.page_progress)
        self.result_card.setStyleSheet("""
            CardWidget {
                background-color: rgba(255, 255, 255, 0.05);
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 8px;
            }
        """)
        result_card_layout = QVBoxLayout(self.result_card)
        result_card_layout.setContentsMargins(14, 12, 14, 12)
        result_card_layout.setSpacing(6)

        self.result_header = StrongBodyLabel("Export Finished Successfully!", self.result_card)
        self.result_header.setStyleSheet("color: #1ED760; font-size: 15px; font-weight: 600;")
        self.result_body = CaptionLabel("", self.result_card)
        self.result_body.setTextColor(TEXT_PRIMARY, TEXT_PRIMARY)
        self.result_body.setWordWrap(True)

        result_card_layout.addWidget(self.result_header)
        result_card_layout.addWidget(self.result_body)
        self.result_card.setVisible(False)

        # Action buttons
        action_btn_layout = QHBoxLayout()
        action_btn_layout.setSpacing(10)
        self.open_folder_btn = PrimaryPushButton(FluentIcon.FOLDER, "Open Export Folder", self.page_progress)
        self.open_folder_btn.clicked.connect(self._open_export_folder)
        self.open_folder_btn.setVisible(False)
        action_btn_layout.addWidget(self.open_folder_btn)
        action_btn_layout.addStretch(1)

        progress_layout.addWidget(self.progress_title)
        progress_layout.addLayout(stats_row)
        progress_layout.addWidget(self.progress_bar)
        progress_layout.addWidget(self.progress_caption)
        progress_layout.addWidget(self.result_card)
        progress_layout.addLayout(action_btn_layout)
        progress_layout.addStretch(1)

        self.pages.addWidget(self.page_progress)
        self.viewLayout.addWidget(self.pages)

        # Buttons
        self.yesButton.setText("Start Export")
        self.cancelButton.setText("Cancel")

        self.widget.setMinimumWidth(540)

    def _connect_signals(self):
        self.sig_progress.connect(self._on_progress_update)
        self.sig_finished.connect(self._on_export_finished)
        self.yesButton.clicked.connect(self._start_export)
        self.cancelButton.clicked.connect(self._handle_cancel_click)

    def _browse_destination(self):
        curr = self.dest_input.text().strip() or os.path.expanduser("~/Music")
        folder = QFileDialog.getExistingDirectory(
            self,
            "Select Export Destination (USB Drive, SD Card, or Music Folder)",
            curr
        )
        if folder:
            self.dest_input.setText(os.path.normpath(folder))

    def _start_export(self):
        if self._is_running:
            return

        dest = self.dest_input.text().strip()
        if not dest:
            self.dest_input.setFocus()
            return

        if not os.path.isdir(dest):
            try:
                os.makedirs(dest, exist_ok=True)
            except Exception as e:
                self.progress_caption.setText(f"Error creating destination folder: {e}")
                return

        fmt_idx = self.format_combo.currentIndex()
        fmt_keys = ["original", "mp3", "flac", "opus"]
        selected_fmt = fmt_keys[fmt_idx] if 0 <= fmt_idx < len(fmt_keys) else "original"

        exp_config = ExportConfig(
            destination_dir=dest,
            create_playlist_subfolder=self.subfolder_cb.isChecked(),
            target_format=selected_fmt,
            generate_m3u8=self.m3u8_cb.isChecked(),
            skip_existing=self.skip_cb.isChecked()
        )

        # Save preferences
        config.set("export.last_destination", dest)
        config.set("export.last_format", selected_fmt)
        config.set("export.create_subfolder", self.subfolder_cb.isChecked())
        config.set("export.generate_m3u8", self.m3u8_cb.isChecked())
        config.set("export.skip_existing", self.skip_cb.isChecked())

        # Switch to progress page
        self._is_running = True
        self.cancel_event.clear()
        self.pages.setCurrentIndex(1)
        self.yesButton.setVisible(False)
        self.cancelButton.setText("Cancel Export")
        self.progress_bar.setValue(0)
        self.progress_pct_label.setText("0%")
        self.progress_counter_label.setText(f"0 of {len(self.valid_tracks)} tracks")
        self.progress_title.setText(f"Exporting '{self.playlist_name}'...")
        self.result_card.setVisible(False)
        self.open_folder_btn.setVisible(False)

        def worker():
            def cb(cur, tot, msg):
                self.sig_progress.emit(cur, tot, msg)

            try:
                res = PlaylistExporter.export_tracks(
                    playlist_name=self.playlist_name,
                    tracks=self.valid_tracks,
                    config=exp_config,
                    progress_callback=cb,
                    cancel_event=self.cancel_event
                )
                self.sig_finished.emit(res)
            except Exception as e_w:
                res = ExportResult(total=len(self.valid_tracks), errors=[str(e_w)])
                self.sig_finished.emit(res)

        threading.Thread(target=worker, daemon=True, name="PlaylistExporterWorker").start()

    def _on_progress_update(self, current: int, total: int, msg: str):
        pct = int((current / max(1, total)) * 100)
        self.progress_bar.setValue(pct)
        self.progress_pct_label.setText(f"{pct}%")
        self.progress_counter_label.setText(f"{current} of {total} tracks")
        self.progress_caption.setText(msg)

    def _on_export_finished(self, result: ExportResult):
        self._is_running = False
        self.export_result = result
        self.progress_bar.setValue(100)
        self.progress_pct_label.setText("100%")
        self.progress_counter_label.setText(f"{result.total} of {result.total} tracks")

        if result.cancelled:
            self.progress_title.setText("Export Cancelled")
            self.result_header.setText("Export Cancelled")
            self.result_header.setStyleSheet("color: #FFB900; font-size: 15px; font-weight: 600;")
            self.result_body.setText(f"Process stopped by user. Exported {result.exported} track(s) before cancellation.")
            self.progress_caption.setText("Export stopped.")
        elif result.errors and result.exported == 0 and result.skipped == 0:
            self.progress_title.setText("Export Failed")
            self.result_header.setText("Export Failed")
            self.result_header.setStyleSheet("color: #E81123; font-size: 15px; font-weight: 600;")
            self.result_body.setText(f"Error: {'; '.join(result.errors[:2])}")
            self.progress_caption.setText("Could not export tracks.")
        else:
            self.progress_title.setText("Export Finished!")
            self.result_header.setText("Export Completed Successfully!")
            self.result_header.setStyleSheet("color: #1ED760; font-size: 15px; font-weight: 600;")

            details = [f"✓ Successfully exported {result.exported} song(s) to destination."]
            if result.skipped > 0:
                details.append(f"✓ {result.skipped} song(s) already existed and were skipped.")
            if result.m3u8_path:
                details.append(f"✓ Created portable playlist: {os.path.basename(result.m3u8_path)}")
            if result.export_dir:
                details.append(f"✓ Location: {result.export_dir}")
            if result.failed > 0:
                details.append(f"⚠ {result.failed} song(s) failed or were missing from disk.")

            self.result_body.setText("\n".join(details))
            self.progress_caption.setText(f"Done! {result.exported} track(s) ready in export folder.")

            # Trigger a toast notification on the parent window as well
            parent_win = self.parent() or self.window()
            if parent_win:
                try:
                    folder_name = os.path.basename(result.export_dir) or result.export_dir
                    InfoBar.success(
                        title="Export Finished",
                        content=f"Successfully exported {result.exported} track(s) to '{folder_name}'.",
                        orient=Qt.Orientation.Horizontal,
                        position=InfoBarPosition.TOP,
                        duration=6000,
                        parent=parent_win
                    )
                except Exception as e_toast:
                    logger.debug(f"Could not show InfoBar toast: {e_toast}")

        self.result_card.setVisible(True)
        if result.export_dir and os.path.isdir(result.export_dir):
            self.open_folder_btn.setVisible(True)

        self.cancelButton.setText("Done")
        self.cancelButton.setEnabled(True)

    def _open_export_folder(self):
        if self.export_result and self.export_result.export_dir and os.path.isdir(self.export_result.export_dir):
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
            if os.name == "nt":
                os.startfile(self.export_result.export_dir)
            else:
                subprocess.Popen(["xdg-open", self.export_result.export_dir], creationflags=flags)

    def _handle_cancel_click(self):
        if self._is_running:
            self.cancel_event.set()
            self.cancelButton.setEnabled(False)
            self.cancelButton.setText("Cancelling...")
            self.progress_caption.setText("Cancelling export and cleaning up...")
        else:
            self.accept()
