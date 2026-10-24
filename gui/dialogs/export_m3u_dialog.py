import os
import subprocess
import logging
from typing import List, Dict, Any, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFileDialog, QStackedWidget
)
from qfluentwidgets import (
    MessageBoxBase, SubtitleLabel, CaptionLabel, StrongBodyLabel, BodyLabel,
    LineEdit, PushButton, PrimaryPushButton, ComboBox, FluentIcon, CardWidget,
    InfoBar, InfoBarPosition
)

from core.config import config
from core.archive import ArchiveManager
from core.utils import sanitize_filename
from gui.styles import TEXT_MUTED, TEXT_PRIMARY, TEXT_SECONDARY, SPOTIFY_EMERALD

logger = logging.getLogger("gui.dialogs.export_m3u")


class ExportM3UDialog(MessageBoxBase):
    """
    Fluent Design Modal Dialog for exporting portable .m3u8 / .m3u playlist files
    optimized for external media players (VLC, PotPlayer, KMPlayer on PC, or
    Poweramp, Musicolet, VLC on Android).
    Guarantees exact Spotify playlist track order and standard RFC 8216 EXTM3U metadata.
    """

    def __init__(
        self,
        playlist_name: str,
        tracks: List[Any],
        archive: Optional[ArchiveManager] = None,
        playlist_id: Optional[str] = None,
        parent=None
    ):
        self._fallback_parent = None
        if parent is None:
            from PyQt6.QtWidgets import QApplication
            app = QApplication.instance()
            parent = (app.activeWindow() if app else None)
            if parent is None:
                self._fallback_parent = QWidget()
                parent = self._fallback_parent

        super().__init__(parent)
        self.playlist_name = playlist_name or "Playlist"
        self.archive = archive or ArchiveManager()
        self.playlist_id = playlist_id
        self.raw_tracks = tracks or []

        # Filter for tracks actually on disk
        self.valid_tracks = []
        for t in self.raw_tracks:
            fp = t.get("file_path") if isinstance(t, dict) else getattr(t, "output_path", "")
            if fp and os.path.isfile(fp):
                self.valid_tracks.append(t)

        self.exported_file_path: Optional[str] = None

        self._init_ui()
        self._connect_signals()

    def validate(self) -> bool:
        """Prevent MessageBoxBase from automatically closing modal on yesButton click."""
        return False

    def _init_ui(self):
        self.titleLabel = SubtitleLabel("Export Playlist File (.m3u8)", self)
        self.viewLayout.addWidget(self.titleLabel)

        desc = CaptionLabel(
            "Export a playlist file for VLC, PotPlayer, KMPlayer on PC, or Poweramp, Musicolet, VLC on Android.",
            self
        )
        desc.setTextColor(TEXT_MUTED, TEXT_MUTED)
        self.viewLayout.addWidget(desc)

        # Summary Card
        summary_card = CardWidget(self)
        summary_card.setStyleSheet("background-color: rgba(255, 255, 255, 0.04); border-radius: 6px; padding: 6px;")
        summary_layout = QVBoxLayout(summary_card)
        summary_layout.setContentsMargins(12, 10, 12, 10)
        summary_layout.setSpacing(2)

        src_title = StrongBodyLabel(f"Playlist: {self.playlist_name}", summary_card)
        src_info = CaptionLabel(
            f"{len(self.valid_tracks)} downloaded song(s) ready (preserved in original Spotify playlist order)",
            summary_card
        )
        src_info.setTextColor(TEXT_MUTED, TEXT_MUTED)
        summary_layout.addWidget(src_title)
        summary_layout.addWidget(src_info)
        self.viewLayout.addWidget(summary_card)

        # Stacked Pages: 0 = Config, 1 = Success
        self.pages = QStackedWidget(self)

        # --- Page 0: Configuration ---
        self.page_config = QWidget()
        cfg_layout = QVBoxLayout(self.page_config)
        cfg_layout.setContentsMargins(0, 8, 0, 0)
        cfg_layout.setSpacing(10)

        # 1. Target Player / Device Preset
        target_lbl = CaptionLabel("Target Player & Path Mode", self.page_config)
        target_lbl.setTextColor(TEXT_SECONDARY, TEXT_SECONDARY)
        cfg_layout.addWidget(target_lbl)

        self.target_combo = ComboBox(self.page_config)
        self.target_combo.addItems([
            "📱 Android Players (Poweramp, Musicolet, VLC - Universal Filename)",
            "💻 Windows Players (VLC, PotPlayer, KMPlayer - Absolute Path)",
            "📂 Relative Paths (Portable next to music folder)",
            "🤖 Custom Android Directory Prefix (/storage/...)"
        ])
        last_mode = config.get("export_m3u.last_mode", 0)
        if 0 <= last_mode < self.target_combo.count():
            self.target_combo.setCurrentIndex(last_mode)
        cfg_layout.addWidget(self.target_combo)

        # Explanatory helper label for selected mode
        self.mode_helper_label = CaptionLabel("", self.page_config)
        self.mode_helper_label.setTextColor(TEXT_MUTED, TEXT_MUTED)
        self.mode_helper_label.setWordWrap(True)
        cfg_layout.addWidget(self.mode_helper_label)

        # 2. Custom Android prefix input (revealed only for mode 3)
        self.prefix_container = QWidget(self.page_config)
        prefix_layout = QVBoxLayout(self.prefix_container)
        prefix_layout.setContentsMargins(0, 0, 0, 0)
        prefix_layout.setSpacing(4)
        pfx_lbl = CaptionLabel("Android Storage Prefix:", self.prefix_container)
        pfx_lbl.setTextColor(TEXT_SECONDARY, TEXT_SECONDARY)
        self.prefix_input = LineEdit(self.prefix_container)
        self.prefix_input.setText(config.get("export_m3u.android_prefix", "/storage/emulated/0/Music"))
        prefix_layout.addWidget(pfx_lbl)
        prefix_layout.addWidget(self.prefix_input)
        self.prefix_container.setVisible(False)
        cfg_layout.addWidget(self.prefix_container)

        # 3. Destination File Picker
        dest_lbl = CaptionLabel("Save Location (.m3u8):", self.page_config)
        dest_lbl.setTextColor(TEXT_SECONDARY, TEXT_SECONDARY)
        cfg_layout.addWidget(dest_lbl)

        dest_row = QHBoxLayout()
        dest_row.setSpacing(8)

        safe_name = sanitize_filename(self.playlist_name, max_length=50) or "Playlist"
        last_save_dir = config.get("export_m3u.last_save_dir", "")
        if not last_save_dir or not os.path.isdir(last_save_dir):
            last_save_dir = os.path.join(os.path.expanduser("~"), "Desktop")
            if not os.path.isdir(last_save_dir):
                last_save_dir = os.path.expanduser("~/Music")

        default_file_path = os.path.join(last_save_dir, f"{safe_name}.m3u8")

        self.dest_input = LineEdit(self.page_config)
        self.dest_input.setText(os.path.normpath(default_file_path))
        self.dest_input.setClearButtonEnabled(True)

        self.browse_btn = PushButton(FluentIcon.FOLDER, "Browse...", self.page_config)
        self.browse_btn.clicked.connect(self._browse_save_path)

        dest_row.addWidget(self.dest_input, 1)
        dest_row.addWidget(self.browse_btn)
        cfg_layout.addLayout(dest_row)

        self.pages.addWidget(self.page_config)

        # --- Page 1: Success & Open ---
        self.page_success = QWidget()
        success_layout = QVBoxLayout(self.page_success)
        success_layout.setContentsMargins(0, 10, 0, 0)
        success_layout.setSpacing(12)

        self.success_card = CardWidget(self.page_success)
        self.success_card.setStyleSheet("""
            CardWidget {
                background-color: rgba(255, 255, 255, 0.05);
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 8px;
            }
        """)
        succ_card_lay = QVBoxLayout(self.success_card)
        succ_card_lay.setContentsMargins(14, 12, 14, 12)
        succ_card_lay.setSpacing(6)

        self.succ_title = StrongBodyLabel("Playlist File Exported Successfully!", self.success_card)
        self.succ_title.setStyleSheet("color: #1ED760; font-size: 15px; font-weight: 600;")
        self.succ_details = CaptionLabel("", self.success_card)
        self.succ_details.setTextColor(TEXT_PRIMARY, TEXT_PRIMARY)
        self.succ_details.setWordWrap(True)

        succ_card_lay.addWidget(self.succ_title)
        succ_card_lay.addWidget(self.succ_details)
        success_layout.addWidget(self.success_card)

        action_row = QHBoxLayout()
        action_row.setSpacing(10)

        self.play_btn = PrimaryPushButton(FluentIcon.PLAY, "Play in Default Player (VLC / PotPlayer)", self.page_success)
        self.play_btn.clicked.connect(self._play_in_default_player)

        self.open_folder_btn = PushButton(FluentIcon.FOLDER, "Reveal in File Explorer", self.page_success)
        self.open_folder_btn.clicked.connect(self._reveal_in_explorer)

        action_row.addWidget(self.play_btn)
        action_row.addWidget(self.open_folder_btn)
        action_row.addStretch(1)

        success_layout.addLayout(action_row)
        success_layout.addStretch(1)

        self.pages.addWidget(self.page_success)
        self.viewLayout.addWidget(self.pages)

        # Bottom dialog buttons
        self.yesButton.setText("Export Playlist")
        self.cancelButton.setText("Cancel")

        self.widget.setMinimumWidth(540)
        self._update_mode_helper()

    def _connect_signals(self):
        self.target_combo.currentIndexChanged.connect(self._update_mode_helper)
        self.yesButton.clicked.connect(self._on_export_clicked)
        self.cancelButton.clicked.connect(self._on_cancel_clicked)

    def _update_mode_helper(self):
        idx = self.target_combo.currentIndex()
        if idx == 0:
            self.mode_helper_label.setText(
                "• Universal filename matching (e.g. 'Song.flac').\n"
                "• Best for Android: Poweramp, Musicolet, VLC Android, GoneMAD automatically match songs already on your phone."
            )
            self.prefix_container.setVisible(False)
        elif idx == 1:
            self.mode_helper_label.setText(
                "• Full system file paths (e.g. 'D:/Spotify-Downloader/downloads/Song.flac').\n"
                "• Best for Windows: Double-click the file anywhere on your PC to immediately stream in VLC, PotPlayer, KMPlayer."
            )
            self.prefix_container.setVisible(False)
        elif idx == 2:
            self.mode_helper_label.setText(
                "• Relative paths from the playlist file to the songs.\n"
                "• Best when keeping the .m3u8 file in or right next to your music directory."
            )
            self.prefix_container.setVisible(False)
        elif idx == 3:
            self.mode_helper_label.setText(
                "• Explicit Android Unix paths (e.g. '/storage/emulated/0/Music/Song.flac').\n"
                "• Recommended if your Android player requires full internal storage / SD card paths."
            )
            self.prefix_container.setVisible(True)

    def _browse_save_path(self):
        curr_text = self.dest_input.text().strip()
        start_dir = os.path.dirname(curr_text) if curr_text else os.path.expanduser("~/Desktop")
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save M3U8 Playlist File",
            curr_text or os.path.join(start_dir, f"{self.playlist_name}.m3u8"),
            "M3U8 Playlist (*.m3u8);;M3U Playlist (*.m3u);;All Files (*.*)"
        )
        if file_path:
            self.dest_input.setText(os.path.normpath(file_path))

    def _on_export_clicked(self):
        save_path = self.dest_input.text().strip()
        if not save_path:
            self.dest_input.setFocus()
            return

        if not self.valid_tracks:
            InfoBar.warning(
                title="No Downloaded Songs",
                content=f"No downloaded songs found on disk for '{self.playlist_name}'.",
                duration=4000,
                parent=self
            )
            return

        idx = self.target_combo.currentIndex()
        mode_map = {0: "filename", 1: "absolute", 2: "relative", 3: "android_prefix"}
        path_mode = mode_map.get(idx, "filename")
        android_prefix = self.prefix_input.text().strip() or "/storage/emulated/0/Music"

        # Save preferences
        config.set("export_m3u.last_mode", idx)
        config.set("export_m3u.last_save_dir", os.path.dirname(os.path.abspath(save_path)))
        config.set("export_m3u.android_prefix", android_prefix)

        # Perform export
        try:
            if self.playlist_id:
                out_path = self.archive.export_saved_playlist_m3u8(
                    playlist_id=self.playlist_id,
                    dest_path=save_path,
                    path_mode=path_mode,
                    android_prefix=android_prefix
                )
            else:
                out_path = self.archive.export_tracks_to_m3u8(
                    playlist_name=self.playlist_name,
                    tracks=self.valid_tracks,
                    dest_path=save_path,
                    path_mode=path_mode,
                    android_prefix=android_prefix
                )

            if not out_path or not os.path.isfile(out_path):
                raise IOError("Failed to create M3U8 file on disk.")

            self.exported_file_path = out_path

            # Update success card
            mode_names = {
                0: "Android Universal (Filename Only)",
                1: "Windows VLC / PotPlayer (Absolute Paths)",
                2: "Relative Paths",
                3: f"Android Storage Path ({android_prefix})"
            }
            details = [
                f"✓ File created: {os.path.basename(out_path)}",
                f"✓ Total: {len(self.valid_tracks)} song(s) ordered by original Spotify playlist sequence",
                f"✓ Preset: {mode_names.get(idx, 'Custom')}",
                f"✓ Saved to: {out_path}"
            ]
            self.succ_details.setText("\n".join(details))

            # Switch to success page
            self.pages.setCurrentIndex(1)
            self.yesButton.setVisible(False)
            self.cancelButton.setText("Done")

            # Also trigger InfoBar toast on parent window
            parent_win = self.parent() or self.window()
            if parent_win:
                try:
                    InfoBar.success(
                        title="Playlist Exported",
                        content=f"Exported '{self.playlist_name}.m3u8' with {len(self.valid_tracks)} tracks in original order.",
                        orient=Qt.Orientation.Horizontal,
                        position=InfoBarPosition.TOP,
                        duration=5000,
                        parent=parent_win
                    )
                except Exception as e_toast:
                    logger.debug(f"Could not show InfoBar toast: {e_toast}")

        except Exception as e:
            logger.error(f"Error exporting M3U8: {e}")
            InfoBar.error(
                title="Export Failed",
                content=f"Could not write playlist file: {e}",
                duration=4000,
                parent=self
            )

    def _play_in_default_player(self):
        """Launches default system player (VLC, PotPlayer, KMPlayer, WMP) for the exported playlist."""
        if self.exported_file_path and os.path.isfile(self.exported_file_path):
            try:
                os.startfile(self.exported_file_path)
            except Exception as e:
                InfoBar.warning("Launch Error", f"Could not launch media player: {e}", parent=self)

    def _reveal_in_explorer(self):
        """Highlights the exported .m3u8 file in Windows Explorer."""
        if self.exported_file_path and os.path.isfile(self.exported_file_path):
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
            if os.name == "nt":
                subprocess.Popen(["explorer", f"/select,{os.path.normpath(self.exported_file_path)}"], creationflags=flags)
            else:
                subprocess.Popen(["xdg-open", os.path.dirname(self.exported_file_path)], creationflags=flags)

    def _on_cancel_clicked(self):
        if self.pages.currentIndex() == 1:
            self.accept()
        else:
            self.reject()
