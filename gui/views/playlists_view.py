import os
import subprocess
import threading
import logging
from typing import Optional, List, Dict, Any

logger = logging.getLogger("gui.views.playlists")

from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QModelIndex, QRectF, QUrl
from PyQt6.QtGui import QImage, QPixmap, QPainter, QPainterPath, QColor, QDesktopServices
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QHeaderView, QMenu, QApplication,
    QStackedWidget, QLabel, QFrame, QFileDialog
)
from qfluentwidgets import (
    TableView, SubtitleLabel, PushButton, PrimaryPushButton, ToolButton,
    FluentIcon, InfoBar, InfoBarPosition, LineEdit, CaptionLabel,
    StrongBodyLabel, BodyLabel, CardWidget, SmoothScrollArea, IconWidget,
    SpinBox, CompactSpinBox, ComboBox, ProgressBar, MessageBoxBase
)

from core.archive import ArchiveManager
from core.spotify_client import SpotifyClient, TrackMetadata
from core.queue_manager import DownloadQueueManager, QueueItem
from core.config import config
from core.utils import format_duration
from gui.queue_model import TrackQueueModel
from gui.queue_delegate import TrackCardDelegate
from gui.bridge import EngineSignalBridge, safe_invoke, safe_emit
from gui.styles import TEXT_MUTED, TEXT_PRIMARY, TEXT_SECONDARY, BG_CARD, SPOTIFY_EMERALD
from gui.dialogs.export_dialog import ExportDialog
from gui.dialogs.export_m3u_dialog import ExportM3UDialog

PRESET_NORMAL_STYLE = """
    PushButton {
        background-color: rgba(255, 255, 255, 0.06);
        border: 1px solid rgba(255, 255, 255, 0.15);
        color: #CCCCCC;
        border-radius: 6px;
        font-weight: 500;
        font-size: 12px;
        padding: 4px 6px;
    }
    PushButton:hover {
        background-color: rgba(255, 255, 255, 0.12);
        border: 1px solid rgba(255, 255, 255, 0.28);
        color: #FFFFFF;
    }
"""

PRESET_ACTIVE_STYLE = """
    PushButton {
        background-color: rgba(29, 185, 84, 0.22);
        border: 1.5px solid #1DB954;
        color: #1ED760;
        border-radius: 6px;
        font-weight: 700;
        font-size: 12px;
        padding: 4px 6px;
    }
    PushButton:hover {
        background-color: rgba(29, 185, 84, 0.32);
        border: 1.5px solid #1ED760;
        color: #FFFFFF;
    }
"""


class SpotifyCredentialsDialog(MessageBoxBase):
    """Fluent Dialog allowing users to quickly configure Spotify Developer credentials."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.titleLabel = SubtitleLabel("Configure Spotify Developer API", self)
        self.viewLayout.addWidget(self.titleLabel)

        guide_text = (
            "Spotify requires free API credentials to retrieve playlists larger than 100 songs.\n"
            "Without credentials, Spotify's guest embed strictly limits playlists to 100 songs.\n\n"
            "How to get free credentials in 1 minute:\n"
            "1. Visit developer.spotify.com/dashboard and open your app.\n"
            "2. Go to 'Settings' -> 'Basic Information' -> 'Redirect URIs'.\n"
            "3. Add: http://127.0.0.1:9900/callback (click Add, then click Save at bottom!).\n"
            "4. Copy your Client ID and Client Secret below:"
        )
        self.guide_label = CaptionLabel(guide_text, self)
        self.guide_label.setTextColor(TEXT_MUTED, TEXT_MUTED)
        self.viewLayout.addWidget(self.guide_label)

        self.open_dash_btn = PushButton(FluentIcon.LINK, "Open Spotify Developer Dashboard", self)
        self.open_dash_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://developer.spotify.com/dashboard")))
        self.viewLayout.addWidget(self.open_dash_btn)

        self.cid_input = LineEdit(self)
        self.cid_input.setPlaceholderText("Spotify Client ID")
        self.cid_input.setText(config.get("spotify.client_id", ""))
        self.viewLayout.addWidget(self.cid_input)

        self.sec_input = LineEdit(self)
        self.sec_input.setPlaceholderText("Spotify Client Secret")
        self.sec_input.setEchoMode(LineEdit.EchoMode.Password)
        self.sec_input.setText(config.get("spotify.client_secret", ""))
        self.viewLayout.addWidget(self.sec_input)

        self.yesButton.setText("Save Keys")
        self.cancelButton.setText("Cancel")


class EditPlaylistDialog(MessageBoxBase):
    """Fluent Dialog allowing users to manually rename a playlist and edit its metadata/cover."""
    def __init__(self, playlist_data: Dict[str, Any], parent=None):
        super().__init__(parent)
        self.playlist_data = playlist_data
        self.selected_local_cover: Optional[str] = None

        self.titleLabel = SubtitleLabel("Edit Playlist Details", self)
        self.viewLayout.addWidget(self.titleLabel)

        desc_label = CaptionLabel("Rename your playlist or customize its cover artwork and Spotify source link.", self)
        desc_label.setTextColor(TEXT_MUTED, TEXT_MUTED)
        self.viewLayout.addWidget(desc_label)

        # 1. Playlist Name input
        name_title = CaptionLabel("Playlist Name", self)
        name_title.setTextColor(TEXT_SECONDARY, TEXT_SECONDARY)
        self.viewLayout.addWidget(name_title)

        self.name_input = LineEdit(self)
        self.name_input.setPlaceholderText("Enter playlist name...")
        self.name_input.setClearButtonEnabled(True)
        self.name_input.setText(playlist_data.get("name", ""))
        self.viewLayout.addWidget(self.name_input)

        # 2. Spotify URL input
        url_title = CaptionLabel("Spotify Link / URL", self)
        url_title.setTextColor(TEXT_SECONDARY, TEXT_SECONDARY)
        self.viewLayout.addWidget(url_title)

        self.url_input = LineEdit(self)
        self.url_input.setPlaceholderText("https://open.spotify.com/playlist/... or collection/tracks")
        self.url_input.setClearButtonEnabled(True)
        self.url_input.setText(playlist_data.get("spotify_url", ""))
        self.viewLayout.addWidget(self.url_input)

        url_helper_row = QHBoxLayout()
        url_helper_row.setSpacing(6)
        self.liked_songs_preset_btn = PushButton(FluentIcon.HEART, "Use Spotify Liked Songs (collection/tracks)", self)
        self.liked_songs_preset_btn.clicked.connect(self._set_liked_songs_url)
        url_helper_row.addWidget(self.liked_songs_preset_btn)
        url_helper_row.addStretch(1)
        self.viewLayout.addLayout(url_helper_row)

        # 3. Artwork / Cover section
        cover_title = CaptionLabel("Cover Artwork (URL or local image file)", self)
        cover_title.setTextColor(TEXT_SECONDARY, TEXT_SECONDARY)
        self.viewLayout.addWidget(cover_title)

        cover_row = QHBoxLayout()
        cover_row.setSpacing(10)

        # Cover Preview Box
        self.cover_preview = QLabel(self)
        self.cover_preview.setFixedSize(56, 56)
        self.cover_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cover_preview.setStyleSheet("""
            QLabel {
                background-color: #2b2b2b;
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 8px;
            }
        """)
        cover_row.addWidget(self.cover_preview)

        cover_inputs_layout = QVBoxLayout()
        cover_inputs_layout.setSpacing(6)

        self.cover_input = LineEdit(self)
        self.cover_input.setPlaceholderText("Cover image URL or local file path...")
        self.cover_input.setClearButtonEnabled(True)
        self.cover_input.setText(playlist_data.get("cover_url", ""))
        self.cover_input.textChanged.connect(self._on_cover_text_changed)

        self.browse_cover_btn = PushButton(FluentIcon.PHOTO, "Browse Image...", self)
        self.browse_cover_btn.clicked.connect(self._browse_local_cover)

        cover_inputs_layout.addWidget(self.cover_input)
        cover_inputs_layout.addWidget(self.browse_cover_btn)
        cover_row.addLayout(cover_inputs_layout, 1)

        self.viewLayout.addLayout(cover_row)

        initial_cover = playlist_data.get("local_cover") or playlist_data.get("cover_url", "")
        self._update_preview(initial_cover)

        self.yesButton.setText("Save Changes")
        self.cancelButton.setText("Cancel")

        self.name_input.textChanged.connect(self._validate_inputs)
        self._validate_inputs()

    def _validate_inputs(self):
        self.yesButton.setEnabled(bool(self.name_input.text().strip()))

    def _set_liked_songs_url(self):
        self.url_input.setText("https://open.spotify.com/collection/tracks")
        cur_name = self.name_input.text().strip().lower()
        if not cur_name or cur_name in ("playlist", "spotify playlist"):
            self.name_input.setText("Liked Songs")

    def _browse_local_cover(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Playlist Cover Artwork",
            "",
            "Image Files (*.jpg *.jpeg *.png *.webp);;All Files (*)"
        )
        if file_path:
            self.selected_local_cover = file_path
            self.cover_input.setText(file_path)
            self._update_preview(file_path)

    def _on_cover_text_changed(self, text: str):
        text = text.strip()
        if os.path.isfile(text):
            self.selected_local_cover = text
            self._update_preview(text)
        elif text.startswith("http://") or text.startswith("https://"):
            self.selected_local_cover = None

    def _update_preview(self, path_or_url: str):
        if path_or_url and os.path.isfile(path_or_url):
            try:
                img = QImage(path_or_url)
                if not img.isNull():
                    scaled = img.scaled(56, 56, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
                    rounded = QPixmap(56, 56)
                    rounded.fill(Qt.GlobalColor.transparent)
                    p = QPainter(rounded)
                    p.setRenderHint(QPainter.RenderHint.Antialiasing)
                    path = QPainterPath()
                    path.addRoundedRect(0, 0, 56, 56, 8, 8)
                    p.setClipPath(path)
                    p.drawPixmap(0, 0, QPixmap.fromImage(scaled))
                    p.end()
                    self.cover_preview.setPixmap(rounded)
                    return
            except Exception:
                pass
        self.cover_preview.setText("")
        icon_w = IconWidget(FluentIcon.MUSIC_FOLDER, self.cover_preview)
        icon_w.setFixedSize(28, 28)
        lay = QHBoxLayout(self.cover_preview)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(icon_w, 0, Qt.AlignmentFlag.AlignCenter)


class EditTrackDialog(MessageBoxBase):
    """Fluent Dialog allowing users to edit track title, artist, and album in a playlist."""
    def __init__(self, track_data: Dict[str, Any], parent=None):
        super().__init__(parent)
        self.titleLabel = SubtitleLabel("Edit Track Metadata", self)
        self.viewLayout.addWidget(self.titleLabel)

        desc_label = CaptionLabel("Modify track details for this song in your playlist and offline archive.", self)
        desc_label.setTextColor(TEXT_MUTED, TEXT_MUTED)
        self.viewLayout.addWidget(desc_label)

        title_lbl = CaptionLabel("Track Title", self)
        title_lbl.setTextColor(TEXT_SECONDARY, TEXT_SECONDARY)
        self.viewLayout.addWidget(title_lbl)

        self.title_input = LineEdit(self)
        self.title_input.setText(track_data.get("title", ""))
        self.title_input.setClearButtonEnabled(True)
        self.viewLayout.addWidget(self.title_input)

        artist_lbl = CaptionLabel("Artist(s)", self)
        artist_lbl.setTextColor(TEXT_SECONDARY, TEXT_SECONDARY)
        self.viewLayout.addWidget(artist_lbl)

        self.artist_input = LineEdit(self)
        self.artist_input.setText(track_data.get("artist", ""))
        self.artist_input.setClearButtonEnabled(True)
        self.viewLayout.addWidget(self.artist_input)

        album_lbl = CaptionLabel("Album", self)
        album_lbl.setTextColor(TEXT_SECONDARY, TEXT_SECONDARY)
        self.viewLayout.addWidget(album_lbl)

        self.album_input = LineEdit(self)
        self.album_input.setText(track_data.get("album", ""))
        self.album_input.setClearButtonEnabled(True)
        self.viewLayout.addWidget(self.album_input)

        self.yesButton.setText("Save Track")
        self.cancelButton.setText("Cancel")

        self.title_input.textChanged.connect(self._validate)
        self._validate()

    def _validate(self):
        self.yesButton.setEnabled(bool(self.title_input.text().strip()))


class MetricCard(CardWidget):
    """Sleek compact metric summary card."""
    def __init__(self, title: str, initial_value: str = "0", parent=None):
        super().__init__(parent)
        self.setFixedHeight(38)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 4, 12, 4)
        layout.setSpacing(8)

        self.title_label = CaptionLabel(title, self)
        self.title_label.setTextColor(TEXT_MUTED, TEXT_MUTED)
        self.title_label.setStyleSheet("font-size: 11px;")
        self.value_label = StrongBodyLabel(initial_value, self)
        self.value_label.setStyleSheet("font-size: 14px; font-weight: bold; color: white;")

        layout.addWidget(self.title_label)
        layout.addStretch(1)
        layout.addWidget(self.value_label)

    def set_value(self, val: str | int):
        self.value_label.setText(str(val))


class SavedPlaylistCard(CardWidget):
    """
    Card representing a saved Spotify playlist in offline storage.
    Displays cover thumbnail, title, track counters, progress bar,
    and action buttons to browse & batch download or delete.
    """

    def __init__(
        self,
        playlist_data: Dict[str, Any],
        on_open=None,
        on_delete=None,
        on_sync=None,
        on_edit=None,
        on_export=None,
        on_export_m3u=None,
        on_toggle_watch=None,
        parent=None
    ):
        super().__init__(parent)
        self.data = playlist_data
        self.on_open = on_open
        self.on_delete = on_delete
        self.on_sync = on_sync
        self.on_edit = on_edit
        self.on_export = on_export
        self.on_export_m3u = on_export_m3u
        self.on_toggle_watch = on_toggle_watch
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_card_context_menu)

        self.setStyleSheet("""
            CardWidget, SavedPlaylistCard {
                background-color: #222222;
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 10px;
            }
            CardWidget:hover, SavedPlaylistCard:hover {
                background-color: #2a2a2a;
                border: 1px solid rgba(255, 255, 255, 0.18);
            }
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 14, 8)
        layout.setSpacing(12)

        # 1. Playlist Cover Artwork (48x48)
        self.thumb_label = QLabel(self)
        self.thumb_label.setFixedSize(48, 48)
        self.thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb_label.setStyleSheet("""
            QLabel {
                background-color: #2c2c2c;
                border: 1px solid rgba(255, 255, 255, 0.10);
                border-radius: 6px;
            }
        """)

        self._load_cover(playlist_data)
        layout.addWidget(self.thumb_label)

        # 2. Metadata Section (Title, Stats, Progress Bar)
        info_layout = QVBoxLayout()
        info_layout.setSpacing(3)

        name = playlist_data.get("name") or "Untitled Playlist"
        tot = playlist_data.get("total_tracks") or 0
        down = playlist_data.get("downloaded_count") or 0
        pend = playlist_data.get("pending_count") or (tot - down)
        pct = playlist_data.get("progress_percent") or (round(down / tot * 100.0, 1) if tot > 0 else 0.0)
        is_watched = bool(playlist_data.get("auto_sync"))

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(8)

        self.title_label = StrongBodyLabel(name, self)
        self.title_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #FFFFFF;")
        title_row.addWidget(self.title_label)

        self.watch_badge = QLabel("⚡ Auto-Sync", self)
        self.watch_badge.setStyleSheet("""
            QLabel {
                background-color: rgba(29, 185, 84, 0.20);
                color: #1ED760;
                font-size: 10px;
                font-weight: 700;
                padding: 1px 6px;
                border-radius: 4px;
                border: 1px solid rgba(29, 185, 84, 0.40);
            }
        """)
        self.watch_badge.setVisible(is_watched)
        title_row.addWidget(self.watch_badge)
        title_row.addStretch(1)

        status_text = f"{tot} tracks  •  {down} downloaded  •  {pend} pending ({pct}%)"
        self.meta_label = CaptionLabel(status_text, self)
        self.meta_label.setTextColor(TEXT_MUTED, TEXT_MUTED)

        # Progress bar
        self.progress_bar = ProgressBar(self)
        self.progress_bar.setFixedHeight(3)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(int(pct))
        self.progress_bar.setStyleSheet("""
            ProgressBar {
                background-color: #333333;
                border-radius: 1.5px;
            }
        """)

        info_layout.addLayout(title_row)
        info_layout.addWidget(self.meta_label)
        info_layout.addWidget(self.progress_bar)
        layout.addLayout(info_layout, 1)

        # 3. Actions Section
        action_layout = QHBoxLayout()
        action_layout.setSpacing(6)

        self.browse_btn = PrimaryPushButton(FluentIcon.CHEVRON_RIGHT, "Browse & Download", self)
        self.browse_btn.setFixedHeight(30)
        self.browse_btn.clicked.connect(self._handle_open)

        self.watch_btn = ToolButton(FluentIcon.PIN, self)
        self.watch_btn.setToolTip(
            "Auto-Sync (Watch Playlist): ON — Click to unpin"
            if is_watched else "Pin Playlist for Scheduled Auto-Sync ('Watch Playlist')"
        )
        if is_watched:
            self.watch_btn.setStyleSheet("ToolButton { background-color: rgba(29, 185, 84, 0.22); border: 1px solid #1ED760; border-radius: 5px; }")
        self.watch_btn.clicked.connect(self._handle_toggle_watch)

        self.sync_btn = ToolButton(FluentIcon.SYNC, self)
        self.sync_btn.setToolTip("Sync Playlist (Check for new/removed tracks)")
        self.sync_btn.clicked.connect(self._handle_sync)

        self.edit_btn = ToolButton(FluentIcon.EDIT, self)
        self.edit_btn.setToolTip("Rename or Edit Playlist Data")
        self.edit_btn.clicked.connect(self._handle_edit)

        self.copy_btn = ToolButton(FluentIcon.COPY, self)
        self.copy_btn.setToolTip("Copy Spotify Link")
        self.copy_btn.clicked.connect(self._copy_link)

        self.delete_btn = ToolButton(FluentIcon.DELETE, self)
        self.delete_btn.setToolTip("Remove from Saved Playlists")
        self.delete_btn.clicked.connect(self._handle_delete)

        action_layout.addWidget(self.browse_btn)
        action_layout.addWidget(self.watch_btn)
        action_layout.addWidget(self.sync_btn)
        action_layout.addWidget(self.edit_btn)
        action_layout.addWidget(self.copy_btn)
        action_layout.addWidget(self.delete_btn)

        layout.addLayout(action_layout)

    def _load_cover(self, data: Dict[str, Any]):
        local_cover = data.get("local_cover")
        cover_url = data.get("cover_url")

        loaded = False
        if local_cover and os.path.isfile(local_cover):
            try:
                img = QImage(local_cover)
                if not img.isNull():
                    scaled = img.scaled(48, 48, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
                    rounded = QPixmap(48, 48)
                    rounded.fill(Qt.GlobalColor.transparent)
                    p = QPainter(rounded)
                    p.setRenderHint(QPainter.RenderHint.Antialiasing)
                    path = QPainterPath()
                    path.addRoundedRect(0, 0, 48, 48, 6, 6)
                    p.setClipPath(path)
                    p.drawPixmap(0, 0, QPixmap.fromImage(scaled))
                    p.end()
                    self.thumb_label.setPixmap(rounded)
                    loaded = True
            except Exception:
                pass

        if not loaded:
            icon_w = IconWidget(FluentIcon.MUSIC_FOLDER, self.thumb_label)
            icon_w.setFixedSize(26, 26)
            icon_lay = QHBoxLayout(self.thumb_label)
            icon_lay.setContentsMargins(0, 0, 0, 0)
            icon_lay.addWidget(icon_w, 0, Qt.AlignmentFlag.AlignCenter)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._handle_open()
        super().mousePressEvent(event)

    def _handle_open(self):
        if self.on_open:
            self.on_open(self.data)

    def _handle_edit(self):
        if self.on_edit:
            self.on_edit(self.data)

    def _handle_delete(self):
        if self.on_delete:
            self.on_delete(self.data.get("id"))

    def _handle_sync(self):
        if self.on_sync:
            self.on_sync(self.data.get("id"))

    def _copy_link(self):
        url = self.data.get("spotify_url", "")
        if url:
            QApplication.clipboard().setText(url)

    def _handle_export(self):
        if self.on_export:
            self.on_export(self.data)

    def _handle_export_m3u(self):
        if self.on_export_m3u:
            self.on_export_m3u(self.data)

    def _handle_toggle_watch(self):
        if self.on_toggle_watch:
            self.on_toggle_watch(self.data)

    def _show_card_context_menu(self, pos):
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: #222222;
                border: 1px solid rgba(255, 255, 255, 0.15);
                border-radius: 8px;
                padding: 4px;
                color: #FFFFFF;
            }
            QMenu::item {
                padding: 6px 24px 6px 12px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background-color: rgba(29, 185, 84, 0.25);
                color: #1ED760;
            }
        """)
        act_open = menu.addAction("Browse & Download Tracks")
        act_edit = menu.addAction("Rename / Edit Playlist...")
        act_sync = menu.addAction("Sync Playlist")
        is_watched = bool(self.data.get("auto_sync"))
        act_watch = menu.addAction("Disable Auto-Sync (Unwatch)" if is_watched else "Enable Auto-Sync (Watch Playlist)")
        menu.addSeparator()
        act_export_m3u = menu.addAction("Export Playlist File (.m3u8)...")
        act_export = menu.addAction("Export Songs to Device / Folder...")
        menu.addSeparator()
        act_copy = menu.addAction("Copy Spotify Link")
        menu.addSeparator()
        act_delete = menu.addAction("Remove from Saved Playlists")

        action = menu.exec(self.mapToGlobal(pos))
        if not action:
            return

        if action == act_open:
            self._handle_open()
        elif action == act_edit:
            self._handle_edit()
        elif action == act_sync:
            self._handle_sync()
        elif action == act_watch:
            self._handle_toggle_watch()
        elif action == act_export_m3u:
            self._handle_export_m3u()
        elif action == act_export:
            self._handle_export()
        elif action == act_copy:
            self._copy_link()
        elif action == act_delete:
            self._handle_delete()


class PlaylistsView(QWidget):
    """
    Dedicated Saved Playlists Management & Batch Download Interface.
    Features:
    - Decoupled ingestion: Paste Spotify playlist URL -> Saves full track metadata to SQLite offline.
    - Two-level view:
        Level 0: Saved Playlists Browser with cover art, track counts, and overall progress.
        Level 1: Playlist Detail View with track inspection, search filter, and customizable Batch Download controls.
    - Preserves daily VIP quota by downloading in arbitrary batch sizes (e.g. 22, 33, 50, 100, 200).
    - Real-time download status synchronization with DownloadQueueManager and ArchiveManager.
    """

    sig_playlist_saved = pyqtSignal(dict)
    sig_save_failed = pyqtSignal(str)
    sig_auth_done = pyqtSignal(bool, str)
    sig_sync_done = pyqtSignal(str, dict)
    sig_sync_failed = pyqtSignal(str, str)
    sig_sync_progress = pyqtSignal(str, int, int)

    def __init__(
        self,
        archive_manager: ArchiveManager,
        queue_manager: DownloadQueueManager,
        bridge: EngineSignalBridge,
        parent=None
    ):
        super().__init__(parent)
        self.archive = archive_manager
        self.qm = queue_manager
        self.bridge = bridge

        self.spotify_client = SpotifyClient(
            client_id=config.get("spotify.client_id", ""),
            client_secret=config.get("spotify.client_secret", "")
        )

        self.current_playlist_id: Optional[str] = None
        self.current_playlist_data: Optional[Dict[str, Any]] = None

        # Data model & delegate for playlist detail table
        self.model = TrackQueueModel(self)
        self.delegate = TrackCardDelegate(self)
        self._playlists_dirty = False
        self._detail_dirty = False
        self._banner_dirty = False

        self._init_ui()
        self._connect_signals()

        # Scheduled Auto-Sync ("Watch Playlists") Timer & Startup Check
        self._auto_sync_timer = QTimer(self)
        self._auto_sync_timer.timeout.connect(lambda: self._run_watched_playlists_sync(is_startup=False))
        self._apply_auto_sync_schedule()
        if bool(config.get("playlists.auto_sync_on_startup", True)):
            QTimer.singleShot(5000, lambda: self._run_watched_playlists_sync(is_startup=True))

        # Load initial saved playlists
        self.reload_playlists()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(18, 12, 18, 12)
        main_layout.setSpacing(8)

        self.stacked = QStackedWidget(self)

        # -------------------------------------------------------------
        # Page 0: Playlists List / Overview
        # -------------------------------------------------------------
        self.list_page = QWidget(self)
        list_layout = QVBoxLayout(self.list_page)
        list_layout.setContentsMargins(0, 0, 0, 0)
        list_layout.setSpacing(10)

        # 1. Header
        header_layout = QVBoxLayout()
        header_layout.setSpacing(4)
        title_label = SubtitleLabel("Saved Playlists", self)
        subtitle_label = CaptionLabel(
            "Save complete Spotify playlists offline. Inspect track metadata and download songs in custom batches to preserve your daily quota.",
            self
        )
        subtitle_label.setTextColor(TEXT_MUTED, TEXT_MUTED)
        header_layout.addWidget(title_label)
        header_layout.addWidget(subtitle_label)
        list_layout.addLayout(header_layout)

        # 2. Input Bar (URL, Paste, Save Playlist)
        input_container = CardWidget(self)
        input_layout = QHBoxLayout(input_container)
        input_layout.setContentsMargins(12, 10, 12, 10)
        input_layout.setSpacing(10)

        self.url_input = LineEdit(self)
        self.url_input.setPlaceholderText("Paste Spotify playlist link (e.g. https://open.spotify.com/playlist/... )")
        self.url_input.setClearButtonEnabled(True)
        self.url_input.returnPressed.connect(self._on_save_playlist_clicked)

        self.paste_btn = ToolButton(FluentIcon.PASTE, self)
        self.paste_btn.setToolTip("Paste from Clipboard")
        self.paste_btn.clicked.connect(self._paste_from_clipboard)

        self.save_btn = PrimaryPushButton(FluentIcon.ADD, "Save Playlist", self)
        self.save_btn.clicked.connect(self._on_save_playlist_clicked)

        self.sync_all_btn = PushButton(FluentIcon.SYNC, "Sync All", self)
        self.sync_all_btn.setToolTip("Check all saved playlists for newly added songs online")
        self.sync_all_btn.clicked.connect(self._sync_all_playlists)

        self.auto_sync_combo = ComboBox(self)
        self.auto_sync_combo.setFixedWidth(185)
        self.auto_sync_combo.setToolTip("Configure scheduled Auto-Sync interval for pinned ('Watched') playlists")
        self.auto_sync_combo.addItems([
            "Watch Sync: Every 6h",
            "Watch Sync: Every 1h",
            "Watch Sync: Every 3h",
            "Watch Sync: Every 12h",
            "Watch Sync: Every 24h",
            "Watch Sync: Startup Only",
            "Watch Sync: Manual Only",
        ])
        self._init_auto_sync_combo_selection()
        self.auto_sync_combo.currentIndexChanged.connect(self._on_auto_sync_combo_changed)

        input_layout.addWidget(self.url_input, 1)
        input_layout.addWidget(self.paste_btn)
        input_layout.addWidget(self.save_btn)
        input_layout.addWidget(self.sync_all_btn)
        input_layout.addWidget(self.auto_sync_combo)
        list_layout.addWidget(input_container)

        # 2b. Spotify API Mode Banner
        self.api_banner = CardWidget(self)
        banner_layout = QHBoxLayout(self.api_banner)
        banner_layout.setContentsMargins(14, 8, 14, 8)
        banner_layout.setSpacing(10)

        self.banner_icon = IconWidget(self.api_banner)
        self.banner_icon.setFixedSize(18, 18)

        self.banner_label = CaptionLabel(self.api_banner)
        self.banner_btn = PushButton(self.api_banner)
        self.banner_btn.setFixedHeight(28)
        self.banner_btn.clicked.connect(self._on_banner_btn_clicked)

        banner_layout.addWidget(self.banner_icon)
        banner_layout.addWidget(self.banner_label, 1)
        banner_layout.addWidget(self.banner_btn)
        list_layout.addWidget(self.api_banner)

        self._update_api_banner()

        # 3. Metric Cards Row
        metric_layout = QHBoxLayout()
        metric_layout.setSpacing(12)

        self.card_total_pl = MetricCard("Saved Playlists", "0", self)
        self.card_total_tracks = MetricCard("Total Tracks", "0", self)
        self.card_downloaded = MetricCard("Downloaded", "0", self)
        self.card_pending = MetricCard("Pending", "0", self)

        metric_layout.addWidget(self.card_total_pl)
        metric_layout.addWidget(self.card_total_tracks)
        metric_layout.addWidget(self.card_downloaded)
        metric_layout.addWidget(self.card_pending)
        metric_layout.addStretch(1)

        list_layout.addLayout(metric_layout)

        # 4. Search Filter Bar
        search_layout = QHBoxLayout()
        self.pl_search_input = LineEdit(self)
        self.pl_search_input.setPlaceholderText("Search saved playlists by name...")
        self.pl_search_input.setClearButtonEnabled(True)
        self.pl_search_input.textChanged.connect(self._on_search_text_changed)
        search_layout.addWidget(self.pl_search_input)
        list_layout.addLayout(search_layout)

        # 5. Playlists Scroll Area
        self.scroll_area = SmoothScrollArea(self.list_page)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setStyleSheet("QScrollArea, SmoothScrollArea { border: none; background: transparent; }")
        self.scroll_area.viewport().setStyleSheet("background: transparent;")

        self.playlists_container = QWidget()
        self.playlists_container.setStyleSheet("background: transparent;")
        self.playlists_layout = QVBoxLayout(self.playlists_container)
        self.playlists_layout.setContentsMargins(0, 0, 0, 0)
        self.playlists_layout.setSpacing(10)
        self.playlists_layout.addStretch(1)

        self.scroll_area.setWidget(self.playlists_container)
        list_layout.addWidget(self.scroll_area, 1)

        self.stacked.addWidget(self.list_page)

        # -------------------------------------------------------------
        # Page 1: Single Playlist Detail View
        # -------------------------------------------------------------
        self.detail_page = QWidget(self)
        detail_layout = QVBoxLayout(self.detail_page)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        detail_layout.setSpacing(8)

        # 1. Compact Playlist Header Banner (Back Button, Cover, Title, Stats & Playlist Actions)
        self.banner_card = CardWidget(self.detail_page)
        self.banner_card.setStyleSheet("""
            CardWidget {
                background-color: #1e1e1e;
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 8px;
            }
        """)
        banner_layout = QHBoxLayout(self.banner_card)
        banner_layout.setContentsMargins(10, 6, 12, 6)
        banner_layout.setSpacing(10)

        # Integrated Back Navigation Button
        self.back_btn = PushButton(FluentIcon.LEFT_ARROW, "Back to Playlists", self.banner_card)
        self.back_btn.setFixedHeight(30)
        self.back_btn.clicked.connect(self._show_overview)
        banner_layout.addWidget(self.back_btn)

        # Compact 40x40 Artwork Thumbnail
        self.detail_thumb = QLabel(self.banner_card)
        self.detail_thumb.setFixedSize(40, 40)
        self.detail_thumb.setStyleSheet("""
            QLabel {
                background-color: #2c2c2c;
                border: 1px solid rgba(255, 255, 255, 0.10);
                border-radius: 6px;
            }
        """)
        self.detail_thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        banner_layout.addWidget(self.detail_thumb)

        # Title & Stats in tight 2-line layout
        detail_info_layout = QVBoxLayout()
        detail_info_layout.setSpacing(2)
        detail_info_layout.setContentsMargins(0, 0, 0, 0)

        self.detail_title = StrongBodyLabel("Playlist Name", self.banner_card)
        self.detail_title.setStyleSheet("font-size: 14px; font-weight: 700; color: #FFFFFF;")

        info_sub_row = QHBoxLayout()
        info_sub_row.setSpacing(8)
        self.detail_stats_label = CaptionLabel("0 Total • 0 Downloaded • 0 Pending", self.banner_card)
        self.detail_stats_label.setTextColor(TEXT_MUTED, TEXT_MUTED)
        self.detail_stats_label.setStyleSheet("font-size: 11px;")
        info_sub_row.addWidget(self.detail_stats_label)

        self.detail_progress_bar = ProgressBar(self.banner_card)
        self.detail_progress_bar.setFixedHeight(4)
        self.detail_progress_bar.setRange(0, 100)
        self.detail_progress_bar.setFixedWidth(110)
        info_sub_row.addWidget(self.detail_progress_bar)
        info_sub_row.addStretch(1)

        detail_info_layout.addWidget(self.detail_title)
        detail_info_layout.addLayout(info_sub_row)
        banner_layout.addLayout(detail_info_layout, 1)

        # Playlist-level Action Buttons
        self.detail_watch_btn = PushButton(FluentIcon.PIN, "Auto-Sync", self.banner_card)
        self.detail_watch_btn.setFixedHeight(30)
        self.detail_watch_btn.setToolTip("Pin this playlist for automatic background delta sync & downloading")
        self.detail_watch_btn.clicked.connect(self._handle_detail_toggle_watch)

        self.detail_sync_btn = PushButton(FluentIcon.SYNC, "Sync", self.banner_card)
        self.detail_sync_btn.setFixedHeight(30)
        self.detail_sync_btn.setToolTip("Check for newly added or removed songs from online source")
        self.detail_sync_btn.clicked.connect(self._handle_detail_sync)

        self.detail_edit_btn = PushButton(FluentIcon.EDIT, "Edit", self.banner_card)
        self.detail_edit_btn.setFixedHeight(30)
        self.detail_edit_btn.setToolTip("Rename or edit playlist details & artwork")
        self.detail_edit_btn.clicked.connect(self._handle_detail_edit)

        self.open_folder_btn = PushButton(FluentIcon.FOLDER, "Open Folder", self.banner_card)
        self.open_folder_btn.setFixedHeight(30)
        self.open_folder_btn.setToolTip("Open playlist folder on disk")
        self.open_folder_btn.clicked.connect(self._open_download_folder)

        self.export_m3u8_btn = PushButton(FluentIcon.SHARE, "Export M3U8", self.banner_card)
        self.export_m3u8_btn.setFixedHeight(30)
        self.export_m3u8_btn.setToolTip("Export this playlist to a portable UTF-8 .m3u8 playlist file")
        self.export_m3u8_btn.clicked.connect(self._on_export_m3u8_clicked)

        self.export_songs_btn = PushButton(FluentIcon.FOLDER_ADD, "Export Songs", self.banner_card)
        self.export_songs_btn.setFixedHeight(30)
        self.export_songs_btn.setToolTip("Export downloaded songs from this playlist to an external device, USB drive, or folder")
        self.export_songs_btn.clicked.connect(self._on_export_songs_clicked)

        banner_layout.addWidget(self.detail_watch_btn)
        banner_layout.addWidget(self.detail_sync_btn)
        banner_layout.addWidget(self.detail_edit_btn)
        banner_layout.addWidget(self.open_folder_btn)
        banner_layout.addWidget(self.export_m3u8_btn)
        banner_layout.addWidget(self.export_songs_btn)
        detail_layout.addWidget(self.banner_card)

        # 2. Collapsible Batch Download Controls Panel
        self.batch_card = CardWidget(self.detail_page)
        self.batch_card.setStyleSheet("""
            CardWidget {
                background-color: #191919;
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 8px;
            }
        """)
        batch_layout = QVBoxLayout(self.batch_card)
        batch_layout.setContentsMargins(10, 6, 10, 6)
        batch_layout.setSpacing(6)

        # Row 1: Primary Batch Actions (Always visible, compact 30px)
        batch_action_layout = QHBoxLayout()
        batch_action_layout.setSpacing(8)

        self.download_batch_btn = PrimaryPushButton(FluentIcon.DOWNLOAD, "Download Next Batch (50)", self)
        self.download_batch_btn.setFixedHeight(30)
        self.download_batch_btn.clicked.connect(self._on_download_batch_clicked)

        self.download_selected_btn = PushButton(FluentIcon.CHECKBOX, "Download Selected", self)
        self.download_selected_btn.setFixedHeight(30)
        self.download_selected_btn.clicked.connect(self._on_download_selected_clicked)

        self.pause_btn = PushButton(FluentIcon.PAUSE, "Pause", self)
        self.pause_btn.setFixedHeight(30)
        self.pause_btn.clicked.connect(self._on_pause_clicked)

        self.stop_btn = PushButton(FluentIcon.CLOSE, "Stop", self)
        self.stop_btn.setFixedHeight(30)
        self.stop_btn.clicked.connect(self._on_stop_clicked)

        self.reset_btn = ToolButton(FluentIcon.SYNC, self)
        self.reset_btn.setFixedHeight(30)
        self.reset_btn.setToolTip("Reset queued & failed tracks in this playlist back to pending")
        self.reset_btn.clicked.connect(self._on_reset_queued_clicked)

        batch_action_layout.addWidget(self.download_batch_btn)
        batch_action_layout.addWidget(self.download_selected_btn)
        batch_action_layout.addWidget(self.pause_btn)
        batch_action_layout.addWidget(self.stop_btn)
        batch_action_layout.addWidget(self.reset_btn)
        batch_action_layout.addStretch(1)

        # Toggle button to expand/collapse presets drawer
        self.batch_toggle_btn = PushButton(FluentIcon.SETTING, "Batch Options ▾", self)
        self.batch_toggle_btn.setFixedHeight(30)
        self.batch_toggle_btn.setToolTip("Configure batch download size and preset limits")
        self.batch_toggle_btn.clicked.connect(self._toggle_batch_drawer)
        batch_action_layout.addWidget(self.batch_toggle_btn)

        batch_layout.addLayout(batch_action_layout)

        # Row 2: Collapsible Presets Drawer (Hidden by default to save vertical space)
        self.batch_drawer = QWidget(self.batch_card)
        drawer_layout = QHBoxLayout(self.batch_drawer)
        drawer_layout.setContentsMargins(0, 4, 0, 2)
        drawer_layout.setSpacing(6)

        spin_lbl = CaptionLabel("Batch Size:", self.batch_drawer)
        self.batch_spinbox = SpinBox(self.batch_drawer)
        self.batch_spinbox.setRange(1, 5000)
        self.batch_spinbox.setValue(50)
        self.batch_spinbox.setFixedWidth(110)
        self.batch_spinbox.setFixedHeight(28)
        self.batch_spinbox.setStyleSheet("""
            SpinBox {
                color: #FFFFFF;
                font-weight: 600;
                font-size: 12px;
                background-color: rgba(255, 255, 255, 0.08);
                border: 1px solid rgba(255, 255, 255, 0.18);
                border-radius: 6px;
                padding-left: 8px;
                padding-right: 50px;
            }
            SpinBox:hover {
                background-color: rgba(255, 255, 255, 0.14);
                border: 1px solid rgba(255, 255, 255, 0.3);
            }
            SpinBox:focus {
                border: 1px solid #1DB954;
                background-color: rgba(255, 255, 255, 0.12);
            }
        """)
        self.batch_spinbox.valueChanged.connect(self._on_batch_size_changed)

        self.preset_25 = PushButton("25", self.batch_drawer)
        self.preset_25.setFixedSize(38, 28)
        self.preset_25.setStyleSheet(PRESET_NORMAL_STYLE)
        self.preset_25.clicked.connect(lambda: self._select_batch_preset(25))

        self.preset_50 = PushButton("50", self.batch_drawer)
        self.preset_50.setFixedSize(38, 28)
        self.preset_50.setStyleSheet(PRESET_NORMAL_STYLE)
        self.preset_50.clicked.connect(lambda: self._select_batch_preset(50))

        self.preset_100 = PushButton("100", self.batch_drawer)
        self.preset_100.setFixedSize(44, 28)
        self.preset_100.setStyleSheet(PRESET_NORMAL_STYLE)
        self.preset_100.clicked.connect(lambda: self._select_batch_preset(100))

        self.preset_200 = PushButton("200", self.batch_drawer)
        self.preset_200.setFixedSize(44, 28)
        self.preset_200.setStyleSheet(PRESET_NORMAL_STYLE)
        self.preset_200.clicked.connect(lambda: self._select_batch_preset(200))

        self.preset_all = PushButton("All Pending", self.batch_drawer)
        self.preset_all.setFixedHeight(28)
        self.preset_all.setStyleSheet(PRESET_NORMAL_STYLE)
        self.preset_all.clicked.connect(self._set_batch_to_all_pending)

        batch_desc = CaptionLabel("Download pending songs in controlled batches to preserve Musilon VIP daily limits.", self.batch_drawer)
        batch_desc.setTextColor(TEXT_MUTED, TEXT_MUTED)

        drawer_layout.addWidget(spin_lbl)
        drawer_layout.addWidget(self.batch_spinbox)
        drawer_layout.addWidget(self.preset_25)
        drawer_layout.addWidget(self.preset_50)
        drawer_layout.addWidget(self.preset_100)
        drawer_layout.addWidget(self.preset_200)
        drawer_layout.addWidget(self.preset_all)
        drawer_layout.addSpacing(8)
        drawer_layout.addWidget(batch_desc)
        drawer_layout.addStretch(1)

        self.batch_drawer.setVisible(False)
        batch_layout.addWidget(self.batch_drawer)
        detail_layout.addWidget(self.batch_card)

        # 3. Track Search & Status Filter Row
        filter_layout = QHBoxLayout()
        filter_layout.setContentsMargins(0, 0, 0, 0)
        filter_layout.setSpacing(8)

        self.track_search_input = LineEdit(self)
        self.track_search_input.setFixedHeight(30)
        self.track_search_input.setPlaceholderText("Filter tracks in this playlist by title or artist...")
        self.track_search_input.setClearButtonEnabled(True)
        self.track_search_input.textChanged.connect(self._on_track_filter_changed)

        self.sort_combo = ComboBox(self)
        self.sort_combo.setFixedHeight(30)
        self.sort_combo.addItems([
            "Sort: Default Order",
            "Sort: Genre (A-Z)",
            "Sort: Title (A-Z)",
            "Sort: Artist (A-Z)",
            "Sort: Duration (Shortest)",
            "Sort: Duration (Longest)"
        ])
        self.sort_combo.setFixedWidth(165)
        self.sort_combo.currentIndexChanged.connect(self._on_track_filter_changed)

        self.genre_combo = ComboBox(self)
        self.genre_combo.setFixedHeight(30)
        self.genre_combo.addItems(["All Genres"])
        self.genre_combo.setFixedWidth(135)
        self.genre_combo.currentIndexChanged.connect(self._on_track_filter_changed)

        self.status_filter_combo = ComboBox(self)
        self.status_filter_combo.setFixedHeight(30)
        self.status_filter_combo.addItems(["All Statuses", "Pending Only", "Queued Only", "Downloaded Only"])
        self.status_filter_combo.currentIndexChanged.connect(self._on_track_filter_changed)
        self.status_filter_combo.setFixedWidth(135)

        filter_layout.addWidget(self.track_search_input, 1)
        filter_layout.addWidget(self.sort_combo)
        filter_layout.addWidget(self.genre_combo)
        filter_layout.addWidget(self.status_filter_combo)
        detail_layout.addLayout(filter_layout)

        # 4. Virtualized Tracks Table
        self.table = TableView(self)
        self.table.setModel(self.model)
        self.table.setItemDelegate(self.delegate)
        self.table.setShowGrid(False)
        self.table.horizontalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(56)
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self.table.setSelectionBehavior(TableView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(TableView.SelectionMode.ExtendedSelection)
        self.table.setVerticalScrollMode(TableView.ScrollMode.ScrollPerPixel)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.table.setStyleSheet("QTableView { border: none; background-color: transparent; }")
        self.table.doubleClicked.connect(self._on_table_double_click)

        # Table context menu
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_table_context_menu)

        detail_layout.addWidget(self.table, 1)
        self.stacked.addWidget(self.detail_page)

        main_layout.addWidget(self.stacked, 1)
        self.stacked.setCurrentIndex(0)

    def _connect_signals(self):
        self.sig_playlist_saved.connect(self._on_playlist_saved)
        self.sig_save_failed.connect(self._on_save_failed)
        self.sig_auth_done.connect(self._on_auth_done)
        self.sig_sync_done.connect(self._on_sync_done)
        self.sig_sync_failed.connect(self._on_sync_failed)
        self.sig_sync_progress.connect(self._on_sync_progress)

        # Live bridging from download queue
        self.bridge.sig_completed.connect(self._handle_bridge_completed)
        self.bridge.sig_status_changed.connect(self._handle_bridge_status)
        self.bridge.sig_progress.connect(self._handle_bridge_progress)
        self.bridge.sig_source_resolved.connect(self._handle_bridge_source_resolved)
        self.bridge.sig_failed.connect(self._handle_bridge_failed)

    def _on_banner_btn_clicked(self):
        has_keys = bool(config.get("spotify.client_id", "").strip() and config.get("spotify.client_secret", "").strip())
        has_auth = self.spotify_client.has_user_auth()
        if has_keys:
            self._start_user_authorization()
        else:
            self._open_credentials_dialog()

    def _update_api_banner(self):
        has_keys = bool(config.get("spotify.client_id", "").strip() and config.get("spotify.client_secret", "").strip())
        has_auth = self.spotify_client.has_user_auth(allow_network=False)

        if has_auth:
            user_name = self.spotify_client._cached_user_name or ""
            user_str = f" as @{user_name}" if user_name else ""
            self.banner_icon.setIcon(FluentIcon.COMPLETED)
            self.banner_label.setText(f"Spotify API Connected{user_str}: Full pagination enabled for playlists you own/collaborate on.")
            self.banner_label.setStyleSheet("color: #4ADE80; font-weight: 500;")
            self.banner_btn.setText("Switch Account")
            self.api_banner.setStyleSheet("""
                CardWidget {
                    background-color: rgba(74, 222, 128, 0.08);
                    border: 1px solid rgba(74, 222, 128, 0.25);
                    border-radius: 8px;
                }
            """)
            if not user_name and not getattr(self, "_fetching_user_name", False):
                self._fetching_user_name = True
                import threading
                def _fetch():
                    try:
                        name = self.spotify_client.get_current_user_name()
                        if name:
                            QTimer.singleShot(0, lambda: safe_invoke(self._update_api_banner))
                    finally:
                        self._fetching_user_name = False
                threading.Thread(target=_fetch, daemon=True, name="SpotifyBannerNameFetcher").start()
        elif has_keys:
            self.banner_icon.setIcon(FluentIcon.PEOPLE)
            self.banner_label.setText("Spotify API Keys Set — Account Authorization needed to access playlists > 100 songs.")
            self.banner_label.setStyleSheet("color: #60A5FA; font-weight: 500;")
            self.banner_btn.setText("🔑 Authorize Spotify Account")
            self.api_banner.setStyleSheet("""
                CardWidget {
                    background-color: rgba(96, 165, 250, 0.08);
                    border: 1px solid rgba(96, 165, 250, 0.25);
                    border-radius: 8px;
                }
            """)
        else:
            self.banner_icon.setIcon(FluentIcon.INFO)
            self.banner_label.setText("⚠️ Guest Mode Active (Max 100 songs/playlist). Add free Spotify API keys to download full 1,000+ song playlists.")
            self.banner_label.setStyleSheet("color: #FBBF24; font-weight: 500;")
            self.banner_btn.setText("Configure Free API Keys")
            self.api_banner.setStyleSheet("""
                CardWidget {
                    background-color: rgba(251, 191, 36, 0.08);
                    border: 1px solid rgba(251, 191, 36, 0.25);
                    border-radius: 8px;
                }
            """)

    def _start_user_authorization(self):
        InfoBar.info(
            title="Connecting to Spotify",
            content="Opening your browser. Please log in or click 'Agree' on Spotify to grant playlist access...",
            orient=Qt.Orientation.Horizontal,
            position=InfoBarPosition.TOP,
            duration=7000,
            parent=self
        )
        def worker():
            try:
                success = self.spotify_client.authorize_user(force_new=True)
                if success:
                    user_name = self.spotify_client.get_current_user_name()
                    msg = f"Connected as @{user_name}!" if user_name else "Successfully connected to Spotify account!"
                    safe_emit(self.sig_auth_done, True, msg)
                else:
                    safe_emit(self.sig_auth_done, False, "Could not complete Spotify authorization.")
            except Exception as e:
                safe_emit(self.sig_auth_done, False, str(e))
        threading.Thread(target=worker, daemon=True, name="SpotifyAuthWorker").start()

    def _on_auth_done(self, success: bool, msg: str):
        self._update_api_banner()
        if success:
            InfoBar.success(
                title="Spotify Connected!",
                content="Your Spotify account is now connected. Full pagination is unlocked for all playlists.",
                orient=Qt.Orientation.Horizontal,
                position=InfoBarPosition.TOP,
                duration=6000,
                parent=self
            )
        else:
            InfoBar.error(
                title="Authorization Failed",
                content=msg,
                orient=Qt.Orientation.Horizontal,
                position=InfoBarPosition.TOP,
                duration=6000,
                parent=self
            )

    def _open_credentials_dialog(self):
        diag = SpotifyCredentialsDialog(self.window() or self)
        if diag.exec():
            cid = diag.cid_input.text().strip()
            sec = diag.sec_input.text().strip()
            config.set("spotify.client_id", cid)
            config.set("spotify.client_secret", sec)
            self.spotify_client.update_credentials(cid, sec)
            self._update_api_banner()
            if cid and sec:
                InfoBar.success(
                    title="Spotify API Keys Saved",
                    content="Keys updated. Click 'Authorize Spotify Account' to enable large playlist downloads.",
                    orient=Qt.Orientation.Horizontal,
                    position=InfoBarPosition.TOP,
                    duration=5000,
                    parent=self
                )

    def _paste_from_clipboard(self):
        text = QApplication.clipboard().text().strip()
        if text:
            self.url_input.setText(text)

    def _on_save_playlist_clicked(self):
        url = self.url_input.text().strip()
        if not url:
            InfoBar.warning(
                title="Empty Link",
                content="Please paste a valid Spotify playlist URL.",
                orient=Qt.Orientation.Horizontal,
                position=InfoBarPosition.TOP,
                duration=3000,
                parent=self
            )
            return

        parsed = SpotifyClient.parse_url(url)
        if not parsed:
            InfoBar.error(
                title="Invalid Link",
                content="The provided link is not a recognized Spotify URL.",
                orient=Qt.Orientation.Horizontal,
                position=InfoBarPosition.TOP,
                duration=3500,
                parent=self
            )
            return

        entity_type, entity_id = parsed
        if entity_type not in ("playlist", "album", "collection"):
            InfoBar.warning(
                title="Not a Playlist",
                content="Please provide a Spotify Playlist, Album, or Liked Songs link to save tracks to offline storage.",
                orient=Qt.Orientation.Horizontal,
                position=InfoBarPosition.TOP,
                duration=3500,
                parent=self
            )
            return

        self.save_btn.setEnabled(False)
        self.save_btn.setText("Saving Playlist...")
        InfoBar.info(
            title="Resolving Spotify Playlist",
            content="Fetching all song metadata from Spotify. This may take a moment...",
            orient=Qt.Orientation.Horizontal,
            position=InfoBarPosition.TOP,
            duration=3500,
            parent=self
        )

        def worker():
            try:
                self.spotify_client.update_credentials(
                    client_id=config.get("spotify.client_id", ""),
                    client_secret=config.get("spotify.client_secret", "")
                )
                tracks = self.spotify_client.resolve(url)
                if not tracks:
                    self.sig_save_failed.emit("No tracks could be found in the provided Spotify link.")
                    return

                pl_name = (tracks[0].collection_name if tracks else "") or ("Liked Songs" if entity_type == "collection" else "Spotify Playlist")
                pl_cover = (tracks[0].collection_cover_url if tracks else "") or (tracks[0].cover_url if tracks else "")
                pl_id = entity_id if entity_type != "collection" else "collection_tracks"

                saved_info = self.archive.save_playlist(
                    name=pl_name,
                    spotify_url=url,
                    cover_url=pl_cover,
                    tracks=tracks,
                    playlist_id=pl_id
                )
                is_guest = getattr(self.spotify_client, "last_resolution_mode", "api") == "guest"
                was_truncated = getattr(self.spotify_client, "last_was_truncated", False) or (is_guest and len(tracks) == 100)
                saved_info["was_truncated"] = was_truncated
                saved_info["is_guest"] = is_guest
                saved_info["api_error"] = getattr(self.spotify_client, "last_api_error", "")
                saved_info["owner_name"] = getattr(self.spotify_client, "last_owner_name", "")
                saved_info["auth_user"] = self.spotify_client.get_current_user_name()

                safe_emit(self.sig_playlist_saved, saved_info)
            except Exception as e:
                safe_emit(self.sig_save_failed, str(e))

        threading.Thread(target=worker, daemon=True, name="SavePlaylistWorker").start()

    def _on_playlist_saved(self, saved_info: Dict[str, Any]):
        self.save_btn.setEnabled(True)
        self.save_btn.setText("Save Playlist")
        self.url_input.clear()

        name = saved_info.get("name", "Playlist")
        total = saved_info.get("total_tracks", 0)
        down = saved_info.get("downloaded_count", 0)
        pend = saved_info.get("pending_count", total - down)

        api_err = saved_info.get("api_error")
        owner_name = saved_info.get("owner_name")
        auth_user = saved_info.get("auth_user")

        if api_err == "not_registered":
            InfoBar.error(
                title="Account Not in Developer Allowlist",
                content=(
                    f"Spotify returned: 'The user is not registered for this application'. "
                    f"Go to developer.spotify.com/dashboard -> your app -> 'User Management', "
                    f"click 'Add User' and enter your Spotify account email to unlock full access."
                ),
                orient=Qt.Orientation.Horizontal,
                position=InfoBarPosition.TOP,
                duration=16000,
                parent=self
            )
        elif api_err == "403_not_owner":
            InfoBar.warning(
                title="Playlist Capped at 100 Tracks (Spotify Ownership Policy)",
                content=(
                    f"'{name}' is owned by '{owner_name}', but your app is authorized as '{auth_user}'. "
                    f"In 2026, Spotify requires you to own or collaborate on the playlist to fetch beyond 100 tracks. "
                    f"Click 'Switch Account' above to log in as '{owner_name}', or make it collaborative in Spotify."
                ),
                orient=Qt.Orientation.Horizontal,
                position=InfoBarPosition.TOP,
                duration=15000,
                parent=self
            )
        elif saved_info.get("was_truncated"):
            InfoBar.warning(
                title="Playlist Capped at 100 Tracks (Guest Limit)",
                content=(
                    f"'{name}' saved with 100 tracks. In guest mode, Spotify limits playlist embeds to 100 songs max. "
                    "To fetch all tracks (1,000+ songs), click 'Configure Free API Keys' above."
                ),
                orient=Qt.Orientation.Horizontal,
                position=InfoBarPosition.TOP,
                duration=12000,
                parent=self
            )
        else:
            InfoBar.success(
                title="Playlist Saved Offline",
                content=f"'{name}' saved with {total} tracks ({down} already downloaded, {pend} pending).",
                orient=Qt.Orientation.Horizontal,
                position=InfoBarPosition.TOP,
                duration=5000,
                parent=self
            )
        self.reload_playlists()

    def _on_save_failed(self, err_msg: str):
        self.save_btn.setEnabled(True)
        self.save_btn.setText("Save Playlist")
        InfoBar.error(
            title="Failed to Save Playlist",
            content=f"Error resolving Spotify metadata: {err_msg}",
            orient=Qt.Orientation.Horizontal,
            position=InfoBarPosition.TOP,
            duration=5000,
            parent=self
        )

    def _on_search_text_changed(self, text: str):
        self.reload_playlists(text.strip())

    def reload_playlists(self, search_query: str = ""):
        """Refreshes the playlists grid and top metrics."""
        try:
            self.archive.reconcile_playlist_files()
        except Exception as e_rec:
            logger.debug(f"File reconciliation on reload_playlists skipped: {e_rec}")

        # Clear existing cards
        while self.playlists_layout.count() > 1:
            child = self.playlists_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        playlists = self.archive.get_saved_playlists()
        if search_query:
            playlists = [p for p in playlists if search_query.lower() in (p.get("name") or "").lower()]

        # Compute summary stats
        tot_pl = len(playlists)
        tot_tracks = sum(p.get("total_tracks", 0) for p in playlists)
        tot_down = sum(p.get("downloaded_count", 0) for p in playlists)
        tot_pend = sum(p.get("pending_count", 0) for p in playlists)

        self.card_total_pl.set_value(tot_pl)
        self.card_total_tracks.set_value(tot_tracks)
        self.card_downloaded.set_value(tot_down)
        self.card_pending.set_value(tot_pend)

        if not playlists:
            empty_card = CardWidget(self.playlists_container)
            empty_lay = QVBoxLayout(empty_card)
            empty_lay.setContentsMargins(24, 32, 24, 32)
            empty_lay.setSpacing(8)
            empty_lay.setAlignment(Qt.AlignmentFlag.AlignCenter)

            icon = IconWidget(FluentIcon.ALBUM, empty_card)
            icon.setFixedSize(48, 48)
            empty_lay.addWidget(icon, 0, Qt.AlignmentFlag.AlignCenter)

            lbl = StrongBodyLabel("No Saved Playlists Yet", empty_card)
            lbl.setStyleSheet("font-size: 16px; color: #FFFFFF;")
            empty_lay.addWidget(lbl, 0, Qt.AlignmentFlag.AlignCenter)

            sub = CaptionLabel(
                "Paste a Spotify playlist link in the input bar above to save its full tracklist and download in batches.",
                empty_card
            )
            sub.setTextColor(TEXT_MUTED, TEXT_MUTED)
            empty_lay.addWidget(sub, 0, Qt.AlignmentFlag.AlignCenter)

            self.playlists_layout.insertWidget(0, empty_card)
            return

        for p in playlists:
            card = SavedPlaylistCard(
                playlist_data=p,
                on_open=self._open_playlist_detail,
                on_delete=self._delete_playlist,
                on_sync=self._sync_playlist,
                on_edit=self._edit_playlist,
                on_export=self._export_saved_playlist,
                on_export_m3u=self._export_saved_playlist_m3u8_card,
                on_toggle_watch=self._toggle_playlist_watch,
                parent=self.playlists_container
            )
            self.playlists_layout.insertWidget(self.playlists_layout.count() - 1, card)

    def _init_auto_sync_combo_selection(self):
        startup = bool(config.get("playlists.auto_sync_on_startup", True))
        hrs = int(config.get("playlists.auto_sync_interval_hours", 6) or 0)
        map_hrs = {6: 0, 1: 1, 3: 2, 12: 3, 24: 4}
        if not startup and hrs <= 0:
            self.auto_sync_combo.setCurrentIndex(6)
        elif hrs <= 0:
            self.auto_sync_combo.setCurrentIndex(5)
        else:
            self.auto_sync_combo.setCurrentIndex(map_hrs.get(hrs, 0))

    def _on_auto_sync_combo_changed(self, idx: int):
        idx_map = {
            0: (True, 6),
            1: (True, 1),
            2: (True, 3),
            3: (True, 12),
            4: (True, 24),
            5: (True, 0),
            6: (False, 0),
        }
        startup, hrs = idx_map.get(idx, (True, 6))
        config.set("playlists.auto_sync_on_startup", startup, auto_save=False)
        config.set("playlists.auto_sync_interval_hours", hrs, auto_save=True)
        self._apply_auto_sync_schedule()

    def _apply_auto_sync_schedule(self):
        if not hasattr(self, "_auto_sync_timer"):
            return
        hrs = int(config.get("playlists.auto_sync_interval_hours", 6) or 0)
        if hrs > 0:
            self._auto_sync_timer.start(hrs * 3600 * 1000)
        else:
            self._auto_sync_timer.stop()

    def _toggle_playlist_watch(self, playlist_data: Dict[str, Any]):
        if not playlist_data:
            return
        pl_id = playlist_data.get("id")
        if not pl_id:
            return
        new_state = not bool(playlist_data.get("auto_sync"))
        self.archive.set_playlist_auto_sync(pl_id, new_state)
        pl_name = playlist_data.get("name", "Playlist")
        if new_state:
            InfoBar.success(
                title="Auto-Sync Enabled (Watched)",
                content=f"'{pl_name}' is now pinned for automatic delta sync & downloading.",
                duration=3500,
                parent=self
            )
        else:
            InfoBar.info(
                title="Auto-Sync Disabled",
                content=f"Unpinned '{pl_name}' from scheduled auto-sync.",
                duration=3000,
                parent=self
            )
        self.reload_playlists()
        if str(self.current_playlist_id) == str(pl_id):
            updated = self.archive.get_saved_playlist(pl_id)
            if updated:
                self.current_playlist_data = updated
                self._update_detail_watch_btn()

    def _handle_detail_toggle_watch(self):
        if self.current_playlist_data:
            self._toggle_playlist_watch(self.current_playlist_data)

    def _update_detail_watch_btn(self):
        if not hasattr(self, "detail_watch_btn") or not self.current_playlist_data:
            return
        watched = bool(self.current_playlist_data.get("auto_sync"))
        if watched:
            self.detail_watch_btn.setText("⚡ Auto-Sync: ON")
            self.detail_watch_btn.setStyleSheet(PRESET_ACTIVE_STYLE)
        else:
            self.detail_watch_btn.setText("Auto-Sync: Off")
            self.detail_watch_btn.setStyleSheet("")

    def _run_watched_playlists_sync(self, is_startup: bool = False):
        """Background scheduled runner that checks all pinned ('Watched') playlists for new delta songs on Spotify."""
        if getattr(self, "_watched_sync_running", False):
            return
        watched = self.archive.get_watched_playlists()
        if not watched:
            return

        self._watched_sync_running = True

        def worker():
            try:
                total_added = 0
                all_delta_tracks = []
                for pl in watched:
                    pl_id = pl["id"]
                    pl_url = pl.get("spotify_url", "")
                    if not pl_url:
                        continue
                    try:
                        if SpotifyClient.parse_url(pl_url):
                            self.spotify_client.update_credentials(
                                client_id=config.get("spotify.client_id", ""),
                                client_secret=config.get("spotify.client_secret", "")
                            )
                            tracks = self.spotify_client.resolve(pl_url)
                        else:
                            ytdlp_engine = getattr(self.qm.engine, "ytdlp", None)
                            if not ytdlp_engine:
                                from core.ytdlp_engine import YtdlpEngine
                                ytdlp_engine = YtdlpEngine()
                            tracks = ytdlp_engine.extract_from_url_or_search(pl_url)
                        if tracks:
                            res = self.archive.sync_saved_playlist(pl_id, tracks)
                            added = res.get("added", 0)
                            deltas = res.get("delta_tracks", [])
                            if added > 0 and deltas:
                                total_added += added
                                if bool(config.get("playlists.auto_download_synced_tracks", True)):
                                    self.archive.mark_saved_tracks_queued(pl_id, [t.id for t in deltas])
                                    all_delta_tracks.extend(deltas)
                    except Exception as e_pl:
                        logger.debug(f"Auto-Sync error on watched playlist {pl_id}: {e_pl}")

                def on_done():
                    self._watched_sync_running = False
                    if total_added > 0:
                        if all_delta_tracks:
                            self.qm.enqueue(all_delta_tracks)
                            self.qm.start_all()
                        self.reload_playlists()
                        InfoBar.success(
                            title="Watched Playlists Auto-Synced",
                            content=f"Discovered and queued {total_added} new track(s) across {len(watched)} watched playlist(s)!",
                            duration=5000,
                            parent=self
                        )
                QTimer.singleShot(0, lambda: safe_invoke(on_done))
            except Exception:
                self._watched_sync_running = False

        threading.Thread(target=worker, daemon=True, name="WatchedPlaylistsAutoSync").start()

    def _export_saved_playlist(self, playlist_data: Dict[str, Any]):
        if not playlist_data:
            return
        pl_id = playlist_data.get("id")
        pl_name = playlist_data.get("name", "Playlist")
        if not pl_id:
            return

        tracks = self.archive.get_saved_playlist_tracks(pl_id, status="downloaded")
        valid_tracks = [t for t in tracks if t.get("file_path") and os.path.isfile(t.get("file_path"))]
        if not valid_tracks:
            InfoBar.warning(
                title="No Downloaded Songs",
                content=f"No downloaded songs found on disk for '{pl_name}'. Please download songs first.",
                orient=Qt.Orientation.Horizontal,
                position=InfoBarPosition.TOP,
                duration=4000,
                parent=self
            )
            return

        diag = ExportDialog(pl_name, valid_tracks, self.window() or self)
        diag.exec()

    def _export_saved_playlist_m3u8_card(self, playlist_data: Dict[str, Any]):
        if not playlist_data:
            return
        pl_id = playlist_data.get("id")
        pl_name = playlist_data.get("name", "Playlist")
        if not pl_id:
            return

        tracks = self.archive.get_saved_playlist_tracks(pl_id, status="downloaded")
        valid_tracks = [t for t in tracks if t.get("file_path") and os.path.isfile(t.get("file_path"))]
        if not valid_tracks:
            InfoBar.warning(
                title="No Downloaded Songs",
                content=f"No downloaded songs found on disk for '{pl_name}'. Please download songs first.",
                orient=Qt.Orientation.Horizontal,
                position=InfoBarPosition.TOP,
                duration=4000,
                parent=self
            )
            return

        diag = ExportM3UDialog(
            playlist_name=pl_name,
            tracks=valid_tracks,
            archive=self.archive,
            playlist_id=pl_id,
            parent=self.window() or self
        )
        diag.exec()

    def _delete_playlist(self, playlist_id: str):
        if not playlist_id:
            return
        self.archive.delete_saved_playlist(playlist_id)
        InfoBar.info(
            title="Playlist Removed",
            content="Removed playlist from saved offline records.",
            orient=Qt.Orientation.Horizontal,
            position=InfoBarPosition.TOP,
            duration=3000,
            parent=self
        )
        self.reload_playlists()

    def _edit_playlist(self, playlist_data: Dict[str, Any]):
        if not playlist_data:
            return
        diag = EditPlaylistDialog(playlist_data, self.window() or self)
        if diag.exec():
            new_name = diag.name_input.text().strip()
            new_url = diag.url_input.text().strip()
            new_cover = diag.cover_input.text().strip()
            local_cover = diag.selected_local_cover

            if new_cover and os.path.isfile(new_cover) and not local_cover:
                local_cover = new_cover

            success = self.archive.update_saved_playlist(
                playlist_id=playlist_data["id"],
                name=new_name,
                cover_url=new_cover if not (local_cover and os.path.isfile(local_cover)) else "",
                spotify_url=new_url,
                local_cover_path=local_cover
            )

            if success:
                InfoBar.success(
                    title="Playlist Updated",
                    content=f"Successfully updated '{new_name}'.",
                    orient=Qt.Orientation.Horizontal,
                    position=InfoBarPosition.TOP,
                    duration=3500,
                    parent=self
                )
                self.reload_playlists()
                if self.current_playlist_id == playlist_data["id"]:
                    updated = self.archive.get_saved_playlist(self.current_playlist_id)
                    if updated:
                        self.current_playlist_data = updated
                        self._refresh_detail_header()

    def _handle_detail_edit(self):
        if self.current_playlist_data:
            self._edit_playlist(self.current_playlist_data)

    def _handle_detail_sync(self):
        if self.current_playlist_id:
            self._sync_playlist(self.current_playlist_id)

    def _sync_playlist(self, playlist_id: str):
        if not playlist_id:
            return
        playlists = self.archive.get_saved_playlists()
        target_pl = next((p for p in playlists if str(p.get("id")) == str(playlist_id)), None)
        if not target_pl:
            return

        pl_url = target_pl.get("spotify_url", "")
        if not pl_url:
            InfoBar.warning(
                title="Cannot Sync",
                content="No source link recorded for this saved playlist.",
                orient=Qt.Orientation.Horizontal,
                position=InfoBarPosition.TOP,
                duration=3500,
                parent=self
            )
            return

        if hasattr(self, "detail_sync_btn") and self.detail_sync_btn:
            self.detail_sync_btn.setEnabled(False)
            self.detail_sync_btn.setText("Syncing...")

        pl_name = target_pl.get("name", "Playlist")
        InfoBar.info(
            title="Syncing Playlist",
            content=f"Fetching latest tracks for '{pl_name}'...",
            orient=Qt.Orientation.Horizontal,
            position=InfoBarPosition.TOP,
            duration=3500,
            parent=self
        )

        def on_progress(cur: int, tot: int):
            safe_emit(self.sig_sync_progress, playlist_id, cur, tot)

        def sync_worker():
            try:
                if SpotifyClient.parse_url(pl_url):
                    self.spotify_client.update_credentials(
                        client_id=config.get("spotify.client_id", ""),
                        client_secret=config.get("spotify.client_secret", "")
                    )
                    tracks = self.spotify_client.resolve(pl_url, progress_callback=on_progress)
                else:
                    ytdlp_engine = getattr(self.qm.engine, "ytdlp", None)
                    if not ytdlp_engine:
                        from core.ytdlp_engine import YtdlpEngine
                        ytdlp_engine = YtdlpEngine()
                    tracks = ytdlp_engine.extract_from_url_or_search(pl_url)

                if not tracks:
                    safe_emit(self.sig_sync_failed, playlist_id, "Could not retrieve songs from online source.")
                    return

                res = self.archive.sync_saved_playlist(playlist_id, tracks)
                safe_emit(self.sig_sync_done, playlist_id, res)
            except Exception as e:
                safe_emit(self.sig_sync_failed, playlist_id, str(e))

        threading.Thread(target=sync_worker, daemon=True, name=f"SyncPlaylist_{playlist_id}").start()

    def _on_sync_progress(self, playlist_id: str, current: int, total: int):
        if hasattr(self, "detail_sync_btn") and self.detail_sync_btn and str(self.current_playlist_id) == str(playlist_id):
            self.detail_sync_btn.setText(f"Syncing ({current}/{total})...")

    def _on_sync_done(self, playlist_id: str, summary: Dict[str, Any]):
        if hasattr(self, "detail_sync_btn") and self.detail_sync_btn:
            self.detail_sync_btn.setEnabled(True)
            self.detail_sync_btn.setText("Sync Playlist")

        added = summary.get("added", 0)
        removed = summary.get("removed", 0)
        total = summary.get("total", 0)
        delta_tracks = summary.get("delta_tracks", [])
        target_pl = self.archive.get_saved_playlist(playlist_id)
        pl_name = target_pl.get("name", "Playlist") if target_pl else "Playlist"

        if delta_tracks:
            # Mark newly discovered tracks as queued in DB, enqueue to queue manager, and start download
            self.archive.mark_saved_tracks_queued(playlist_id, [t.id for t in delta_tracks])
            self.qm.enqueue(delta_tracks)
            self.qm.start_all()
            msg = f"Sync complete for '{pl_name}': {added} new track(s) added & enqueued to download, {removed} removed. Total tracks: {total}."
        else:
            msg = f"Sync complete for '{pl_name}': Up to date with Spotify ({removed} removed). Total tracks: {total}."
            if target_pl and "liked" in pl_name.lower() and "collection" not in (target_pl.get("spotify_url") or "").lower():
                msg += " (Tip: To sync with your personal Liked Songs library, click 'Edit Playlist' and set link to: https://open.spotify.com/collection/tracks)"

        InfoBar.success(
            title="Playlist Synced",
            content=msg,
            orient=Qt.Orientation.Horizontal,
            position=InfoBarPosition.TOP,
            duration=6000,
            parent=self
        )
        self.reload_playlists()
        if str(self.current_playlist_id) == str(playlist_id):
            updated_pl = self.archive.get_saved_playlist(playlist_id)
            if updated_pl:
                self._open_playlist_detail(updated_pl)

    def _on_sync_failed(self, playlist_id: str, err_msg: str):
        if hasattr(self, "detail_sync_btn") and self.detail_sync_btn:
            self.detail_sync_btn.setEnabled(True)
            self.detail_sync_btn.setText("Sync Playlist")

        if "scope" in err_msg.lower() or "authorization" in err_msg.lower():
            InfoBar.warning(
                title="Authorization Required",
                content=err_msg,
                orient=Qt.Orientation.Horizontal,
                position=InfoBarPosition.TOP,
                duration=7000,
                parent=self
            )
        else:
            InfoBar.error(
                title="Sync Failed",
                content=f"Error syncing playlist tracks: {err_msg}",
                orient=Qt.Orientation.Horizontal,
                position=InfoBarPosition.TOP,
                duration=5000,
                parent=self
            )

    def _sync_all_playlists(self):
        playlists = self.archive.get_saved_playlists()
        eligible = [p for p in playlists if p.get("spotify_url")]
        if not eligible:
            InfoBar.info("No Playlists", "No saved playlists with online sources found to sync.", duration=3500, parent=self)
            return

        self.sync_all_btn.setEnabled(False)
        self.sync_all_btn.setText("Syncing...")
        InfoBar.info("Syncing All", f"Checking {len(eligible)} saved playlist(s) for online changes...", duration=3500, parent=self)

        def worker():
            total_added = 0
            total_removed = 0
            for pl in eligible:
                pl_id = pl["id"]
                pl_url = pl["spotify_url"]
                try:
                    if SpotifyClient.parse_url(pl_url):
                        self.spotify_client.update_credentials(
                            client_id=config.get("spotify.client_id", ""),
                            client_secret=config.get("spotify.client_secret", "")
                        )
                        tracks = self.spotify_client.resolve(pl_url)
                    else:
                        ytdlp_engine = getattr(self.qm.engine, "ytdlp", None)
                        if not ytdlp_engine:
                            from core.ytdlp_engine import YtdlpEngine
                            ytdlp_engine = YtdlpEngine()
                        tracks = ytdlp_engine.extract_from_url_or_search(pl_url)
                    if tracks:
                        res = self.archive.sync_saved_playlist(pl_id, tracks)
                        total_added += res.get("added", 0)
                        total_removed += res.get("removed", 0)
                except Exception as e:
                    logger.debug(f"Sync error on playlist {pl_id}: {e}")

            def on_finish():
                self.sync_all_btn.setEnabled(True)
                self.sync_all_btn.setText("Sync All")
                self.reload_playlists()
                msg = f"Checked {len(eligible)} playlist(s): {total_added} new song(s) added, {total_removed} removed."
                if total_added > 0:
                    InfoBar.success("Delta Sync Complete", msg, duration=5000, parent=self)
                else:
                    InfoBar.info("All Playlists Up to Date", msg, duration=4000, parent=self)

            QTimer.singleShot(0, lambda: safe_invoke(on_finish))

        threading.Thread(target=worker, daemon=True, name="SyncAllPlaylistsWorker").start()


    # -------------------------------------------------------------
    # Detail View Logic
    # -------------------------------------------------------------
    def _open_playlist_detail(self, playlist_data: Dict[str, Any]):
        self.current_playlist_id = playlist_data["id"]
        try:
            self.archive.reconcile_playlist_files(self.current_playlist_id)
        except Exception as e_rec:
            logger.debug(f"File reconciliation on _open_playlist_detail skipped: {e_rec}")
        fresh_data = self.archive.get_saved_playlist(self.current_playlist_id)
        if fresh_data:
            playlist_data = fresh_data
        self.current_playlist_data = playlist_data
        self._update_detail_watch_btn()

        # Update Header Banner
        self.detail_title.setText(playlist_data.get("name", "Playlist"))
        tot = playlist_data.get("total_tracks", 0)
        down = playlist_data.get("downloaded_count", 0)
        pend = playlist_data.get("pending_count", tot - down)
        pct = playlist_data.get("progress_percent", 0.0)

        self.detail_stats_label.setText(f"{tot} Total Tracks  •  {down} Downloaded  •  {pend} Pending ({pct}%)")
        self.detail_progress_bar.setValue(int(pct))

        # Update thumbnail
        local_cover = playlist_data.get("local_cover")
        if local_cover and os.path.isfile(local_cover):
            try:
                img = QImage(local_cover)
                if not img.isNull():
                    scaled = img.scaled(40, 40, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
                    rounded = QPixmap(40, 40)
                    rounded.fill(Qt.GlobalColor.transparent)
                    p = QPainter(rounded)
                    p.setRenderHint(QPainter.RenderHint.Antialiasing)
                    path = QPainterPath()
                    path.addRoundedRect(0, 0, 40, 40, 6, 6)
                    p.setClipPath(path)
                    p.drawPixmap(0, 0, QPixmap.fromImage(scaled))
                    p.end()
                    self.detail_thumb.setPixmap(rounded)
            except Exception:
                pass
        else:
            self.detail_thumb.clear()
            icon_w = IconWidget(FluentIcon.MUSIC_FOLDER, self.detail_thumb)
            icon_w.setFixedSize(22, 22)
            icon_lay = QHBoxLayout(self.detail_thumb)
            icon_lay.setContentsMargins(0, 0, 0, 0)
            icon_lay.addWidget(icon_w, 0, Qt.AlignmentFlag.AlignCenter)

        # Batch spinbox setup (unclamped up to 5000)
        self.batch_spinbox.setRange(1, 5000)
        self.batch_spinbox.setValue(50)
        self._on_batch_size_changed(self.batch_spinbox.value())

        # Reset search and combos
        self.track_search_input.clear()
        if hasattr(self, "sort_combo"):
            self.sort_combo.blockSignals(True)
            self.sort_combo.setCurrentIndex(0)
            self.sort_combo.blockSignals(False)
        self.status_filter_combo.setCurrentIndex(0)

        # Populate genres combo for this playlist
        all_tracks = self.archive.get_saved_playlist_tracks(self.current_playlist_id)
        genres_set = set()
        for t in all_tracks:
            g_raw = t.get("genre", "") or ""
            for g in g_raw.split(";"):
                c = g.strip()
                if c:
                    genres_set.add(c)
        if hasattr(self, "genre_combo"):
            self.genre_combo.blockSignals(True)
            self.genre_combo.clear()
            self.genre_combo.addItems(["All Genres"] + sorted(list(genres_set)))
            self.genre_combo.setCurrentIndex(0)
            self.genre_combo.blockSignals(False)

        self._load_detail_tracks()
        self.stacked.setCurrentIndex(1)

    def _show_overview(self):
        self.stacked.setCurrentIndex(0)
        self.current_playlist_id = None
        self.current_playlist_data = None
        self.reload_playlists()

    def _toggle_batch_drawer(self):
        if not hasattr(self, "batch_drawer"):
            return
        self._batch_drawer_expanded = not getattr(self, "_batch_drawer_expanded", False)
        self.batch_drawer.setVisible(self._batch_drawer_expanded)
        if hasattr(self, "batch_toggle_btn"):
            self.batch_toggle_btn.setText("Batch Options ▴" if self._batch_drawer_expanded else "Batch Options ▾")

    def _select_batch_preset(self, count: int):
        self.batch_spinbox.setValue(count)
        self._on_batch_size_changed(count)

    def _on_batch_size_changed(self, val: int):
        pend = 0
        if self.current_playlist_data:
            pend = self.current_playlist_data.get("pending_count", 0)

        # 1. Update preset button active highlight states
        self._update_preset_buttons_style(val, pend)

        # 2. Update dynamic text and state of download batch button
        if pend <= 0:
            self.download_batch_btn.setEnabled(False)
            self.download_batch_btn.setText("All Tracks Downloaded")
        else:
            self.download_batch_btn.setEnabled(True)
            if val <= pend:
                self.download_batch_btn.setText(f"Download Next Batch ({val})")
            else:
                self.download_batch_btn.setText(f"Download Batch ({val}) • {pend} Remaining")

        if hasattr(self, "pause_btn"):
            if self.qm.is_paused():
                self.pause_btn.setText("Resume")
                self.pause_btn.setIcon(FluentIcon.PLAY)
            else:
                self.pause_btn.setText("Pause")
                self.pause_btn.setIcon(FluentIcon.PAUSE)

    def _update_preset_buttons_style(self, val: int, pend: int):
        self.preset_25.setStyleSheet(PRESET_ACTIVE_STYLE if val == 25 else PRESET_NORMAL_STYLE)
        self.preset_50.setStyleSheet(PRESET_ACTIVE_STYLE if val == 50 else PRESET_NORMAL_STYLE)
        self.preset_100.setStyleSheet(PRESET_ACTIVE_STYLE if val == 100 else PRESET_NORMAL_STYLE)
        self.preset_200.setStyleSheet(PRESET_ACTIVE_STYLE if val == 200 else PRESET_NORMAL_STYLE)
        self.preset_all.setStyleSheet(PRESET_ACTIVE_STYLE if (pend > 0 and val == pend) else PRESET_NORMAL_STYLE)

    def _set_batch_to_all_pending(self):
        if not self.current_playlist_id:
            return
        pl = self.archive.get_saved_playlist(self.current_playlist_id)
        if pl:
            self.current_playlist_data = pl
            pend = pl.get("pending_count", 0)
            target = max(1, pend)
            self.batch_spinbox.setValue(target)
            self._on_batch_size_changed(target)

    def _on_track_filter_changed(self):
        self._load_detail_tracks()

    def _sort_detail_rows(self, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        idx = self.sort_combo.currentIndex() if hasattr(self, "sort_combo") else 0
        if idx == 1:  # Genre (A-Z)
            return sorted(rows, key=lambda r: (
                0 if (r.get("genre") or "").strip() else 1,
                (r.get("genre") or "").strip().lower(),
                (r.get("artist") or "").strip().lower(),
                (r.get("title") or "").strip().lower()
            ))
        elif idx == 2:  # Title (A-Z)
            return sorted(rows, key=lambda r: (r.get("title") or "").strip().lower())
        elif idx == 3:  # Artist (A-Z)
            return sorted(rows, key=lambda r: (r.get("artist") or "").strip().lower())
        elif idx == 4:  # Duration (Shortest)
            return sorted(rows, key=lambda r: r.get("duration_ms") or 0)
        elif idx == 5:  # Duration (Longest)
            return sorted(rows, key=lambda r: r.get("duration_ms") or 0, reverse=True)
        return rows

    def _load_detail_tracks(self):
        if not self.current_playlist_id:
            return

        search_query = self.track_search_input.text().strip()
        combo_idx = self.status_filter_combo.currentIndex()
        status_filter = None
        if combo_idx == 1:
            status_filter = "pending"
        elif combo_idx == 2:
            status_filter = "queued"
        elif combo_idx == 3:
            status_filter = "downloaded"

        genre_filter = self.genre_combo.currentText() if hasattr(self, "genre_combo") else ""
        if genre_filter == "All Genres":
            genre_filter = ""

        rows = self.archive.get_saved_playlist_tracks(
            self.current_playlist_id,
            status=status_filter,
            search_query=search_query,
            genre_filter=genre_filter
        )
        rows = self._sort_detail_rows(rows)
        items = []

        for r in rows:
            genre_raw = r.get("genre", "") or ""
            track_genres = [g.strip() for g in genre_raw.split(";") if g.strip()]
            track = TrackMetadata(
                id=r["spotify_id"],
                title=r["title"],
                artists=[a.strip() for a in r["artist"].split(",")],
                album=r.get("album", "") or "",
                duration_ms=r.get("duration_ms", 0) or 0,
                track_number=r.get("track_number", 1) or 1,
                disc_number=r.get("disc_number", 1) or 1,
                isrc=r.get("isrc", "") or "",
                cover_url=r.get("cover_url", "") or "",
                collection_name=self.current_playlist_data.get("name", "Playlist") if self.current_playlist_data else "Playlist",
                collection_type="playlist",
                genres=track_genres
            )

            status = r.get("status", "pending")
            status_pill = "Completed" if status == "downloaded" else ("Queued" if status == "queued" else "Pending")
            file_path = r.get("file_path", "")
            q_badge = r.get("quality_badge", "")
            s_type = r.get("source_type", "")
            if status == "downloaded" and not q_badge and file_path:
                q_badge, s_inf = self.archive.infer_badge_from_file(file_path)
                s_type = s_type or s_inf

            item = QueueItem(
                track=track,
                status=status_pill,
                source_type=s_type if status == "downloaded" else "",
                quality_badge=q_badge if status == "downloaded" else "",
                progress_percent=100.0 if status == "downloaded" else 0.0,
                output_path=file_path
            )
            items.append(item)

        self.model.set_items(items)
        self.table.viewport().update()

    def _on_download_batch_clicked(self):
        if not self.current_playlist_id:
            return

        batch_size = self.batch_spinbox.value()
        pending_rows = self.archive.get_saved_playlist_tracks(
            self.current_playlist_id,
            status="pending",
            limit=batch_size
        )

        if not pending_rows:
            InfoBar.info(
                title="No Pending Tracks",
                content="All tracks in this playlist are already downloaded or currently in queue.",
                orient=Qt.Orientation.Horizontal,
                position=InfoBarPosition.TOP,
                duration=3500,
                parent=self
            )
            return

        tracks_to_queue: List[TrackMetadata] = []
        spotify_ids: List[str] = []

        pl_name = self.current_playlist_data.get("name", "Playlist") if self.current_playlist_data else "Playlist"
        pl_cover = self.current_playlist_data.get("cover_url", "") if self.current_playlist_data else ""

        for r in pending_rows:
            t = TrackMetadata(
                id=r["spotify_id"],
                title=r["title"],
                artists=[a.strip() for a in r["artist"].split(",")],
                album=r.get("album", "") or "",
                duration_ms=r.get("duration_ms", 0) or 0,
                track_number=r.get("track_number", 1) or 1,
                disc_number=r.get("disc_number", 1) or 1,
                isrc=r.get("isrc", "") or "",
                cover_url=r.get("cover_url", "") or "",
                collection_name=pl_name,
                collection_type="playlist",
                collection_cover_url=pl_cover
            )
            tracks_to_queue.append(t)
            spotify_ids.append(t.id)

        # 1. Update database
        self.archive.mark_saved_tracks_queued(self.current_playlist_id, spotify_ids)

        # 2. Enqueue into DownloadQueueManager
        self.qm.enqueue(tracks_to_queue)
        self.qm.start()

        if len(tracks_to_queue) < batch_size:
            msg_content = f"Queued all {len(tracks_to_queue)} remaining tracks in playlist (batch requested: {batch_size})."
        else:
            msg_content = f"Queued {len(tracks_to_queue)} track(s) for downloading. You can monitor progress in the Queue tab."

        InfoBar.success(
            title="Batch Enqueued",
            content=msg_content,
            orient=Qt.Orientation.Horizontal,
            position=InfoBarPosition.TOP,
            duration=4500,
            parent=self
        )

        # Reload table to reflect queued badges
        self._load_detail_tracks()
        self._refresh_detail_header()

    def _on_download_selected_clicked(self):
        if not self.current_playlist_id:
            return

        indexes = self.table.selectionModel().selectedRows()
        if not indexes:
            InfoBar.warning(
                title="No Tracks Selected",
                content="Please select one or more tracks from the table below to download.",
                orient=Qt.Orientation.Horizontal,
                position=InfoBarPosition.TOP,
                duration=3000,
                parent=self
            )
            return

        tracks_to_queue: List[TrackMetadata] = []
        spotify_ids: List[str] = []
        pl_name = self.current_playlist_data.get("name", "Playlist") if self.current_playlist_data else "Playlist"
        pl_cover = self.current_playlist_data.get("cover_url", "") if self.current_playlist_data else ""

        for idx in indexes:
            item = self.model.get_item(idx.row())
            if item and item.status != "Completed":
                t = item.track
                t.collection_name = pl_name
                t.collection_type = "playlist"
                t.collection_cover_url = pl_cover
                tracks_to_queue.append(t)
                spotify_ids.append(t.id)

        if not tracks_to_queue:
            InfoBar.info(
                title="Already Downloaded",
                content="The selected tracks are already downloaded.",
                orient=Qt.Orientation.Horizontal,
                position=InfoBarPosition.TOP,
                duration=3000,
                parent=self
            )
            return

        self.archive.mark_saved_tracks_queued(self.current_playlist_id, spotify_ids)
        self.qm.enqueue(tracks_to_queue)
        self.qm.start_all()

        InfoBar.success(
            title="Tracks Enqueued",
            content=f"Queued {len(tracks_to_queue)} selected track(s) for downloading.",
            orient=Qt.Orientation.Horizontal,
            position=InfoBarPosition.TOP,
            duration=4000,
            parent=self
        )

        self._load_detail_tracks()
        self._refresh_detail_header()

    def _on_pause_clicked(self):
        if self.qm.is_paused():
            self.qm.resume()
            self.pause_btn.setText("Pause")
            self.pause_btn.setIcon(FluentIcon.PAUSE)
            InfoBar.info(
                title="Resumed",
                content="Download queue resumed.",
                orient=Qt.Orientation.Horizontal,
                position=InfoBarPosition.TOP,
                duration=2000,
                parent=self
            )
        else:
            self.qm.pause()
            self.pause_btn.setText("Resume")
            self.pause_btn.setIcon(FluentIcon.PLAY)
            InfoBar.info(
                title="Paused",
                content="Download queue paused.",
                orient=Qt.Orientation.Horizontal,
                position=InfoBarPosition.TOP,
                duration=2000,
                parent=self
            )

    def _on_stop_clicked(self):
        self.qm.stop()
        self.pause_btn.setText("Pause")
        self.pause_btn.setIcon(FluentIcon.PAUSE)
        InfoBar.warning(
            title="Downloads Stopped",
            content="Active downloads and pending items have been stopped immediately.",
            orient=Qt.Orientation.Horizontal,
            position=InfoBarPosition.TOP,
            duration=3500,
            parent=self
        )
        self._load_detail_tracks()
        self._refresh_detail_header()

    def _on_reset_queued_clicked(self):
        if not self.current_playlist_id:
            return
        reverted = self.archive.revert_queued_tracks_to_pending(self.current_playlist_id)
        self._load_detail_tracks()
        self._refresh_detail_header()
        InfoBar.success(
            title="Reset Completed",
            content=f"Reverted {reverted} queued/stopped track(s) back to pending.",
            orient=Qt.Orientation.Horizontal,
            position=InfoBarPosition.TOP,
            duration=3500,
            parent=self
        )

    def _refresh_detail_header(self):
        if not self.current_playlist_id:
            return
        pl = self.archive.get_saved_playlist(self.current_playlist_id)
        if pl:
            self.current_playlist_data = pl
            tot = pl.get("total_tracks", 0)
            down = pl.get("downloaded_count", 0)
            pend = pl.get("pending_count", tot - down)
            pct = pl.get("progress_percent", 0.0)

            self.detail_stats_label.setText(f"{tot} Total Tracks  •  {down} Downloaded  •  {pend} Pending ({pct}%)")
            self.detail_progress_bar.setValue(int(pct))
            self._on_batch_size_changed(self.batch_spinbox.value())

    def _open_download_folder(self):
        out_dir = config.get("download.output_dir", "downloads")
        save_in_subfolders = config.get("download.save_in_subfolders", False)
        if self.current_playlist_data:
            from core.utils import sanitize_filename
            safe_name = sanitize_filename(self.current_playlist_data.get("name", ""))
            specific_folder = os.path.join(out_dir, safe_name)
            playlist_m3u8 = os.path.join(out_dir, "playlists", f"{safe_name}.m3u8")
            if save_in_subfolders and os.path.isdir(specific_folder):
                out_dir = specific_folder
            elif not save_in_subfolders and os.path.isfile(playlist_m3u8):
                try:
                    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
                    subprocess.Popen(["explorer", f"/select,{os.path.normpath(playlist_m3u8)}"], creationflags=flags)
                    return
                except Exception:
                    out_dir = os.path.dirname(playlist_m3u8)

        if os.path.exists(out_dir):
            try:
                os.startfile(out_dir)
            except Exception:
                flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
                subprocess.Popen(["explorer", os.path.normpath(out_dir)], creationflags=flags)

    def _on_table_double_click(self, index: QModelIndex):
        item = self.model.get_item(index.row())
        if not item:
            return

        if item.status == "Completed" and item.output_path and os.path.isfile(item.output_path):
            main_win = self.window()
            if hasattr(main_win, "play_audio_track"):
                items = [self.model.get_item(i) for i in range(self.model.rowCount())]
                valid_items = [it for it in items if it and it.output_path and os.path.isfile(it.output_path)]
                curr_idx = valid_items.index(item) if item in valid_items else -1
                main_win.play_audio_track(item.output_path, item.track, item.quality_badge, playlist=valid_items, index=curr_idx)
            else:
                os.startfile(item.output_path)
        elif item.status == "Pending":
            # Quick download single track
            t = item.track
            if self.current_playlist_data:
                t.collection_name = self.current_playlist_data.get("name", "Playlist")
                t.collection_type = "playlist"
                t.collection_cover_url = self.current_playlist_data.get("cover_url", "") or ""
            self.archive.mark_saved_tracks_queued(self.current_playlist_id, [t.id])
            self.qm.enqueue([t])
            self.qm.start_all()
            item.status = "Queued"
            self.model.update_status(t.id, "Queued")

    def _show_table_context_menu(self, pos):
        index = self.table.indexAt(pos)
        if not index.isValid():
            return

        item = self.model.get_item(index.row())
        if not item:
            return

        menu = QMenu(self)
        menu_style = """
            QMenu {
                background-color: #242424;
                color: #FFFFFF;
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 8px;
                padding: 4px;
            }
            QMenu::item {
                padding: 6px 20px 6px 12px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background-color: #383838;
            }
        """
        menu.setStyleSheet(menu_style)

        file_exists = bool(item.output_path and os.path.isfile(item.output_path))
        is_downloaded = (item.status == "Completed" or file_exists)

        act_play = None
        act_reveal = None
        act_spectrum = None
        if file_exists:
            act_play = menu.addAction("Play Track")
            act_reveal = menu.addAction("Reveal in File Explorer")
            act_spectrum = menu.addAction("Inspect Audio Spectrum & True Bitrate...")
            menu.addSeparator()

        act_download = None
        act_dl_melo = None
        act_dl_musi = None
        act_dl_yt = None

        act_redl_auto = None
        act_redl_melo = None
        act_redl_musi = None
        act_redl_yt = None
        act_delete_file = None

        if is_downloaded:
            redl_menu = menu.addMenu("Re-download Track")
            redl_menu.setStyleSheet(menu_style)
            act_redl_auto = redl_menu.addAction("Auto (Best Available)")
            act_redl_melo = redl_menu.addAction("Via Telegram Bot (MeloBot)")
            act_redl_musi = redl_menu.addAction("Via Musilon (320k MP3)")
            act_redl_yt = redl_menu.addAction("Via YouTube Music")

            act_delete_file = menu.addAction("Delete Downloaded File")
        else:
            act_download = menu.addAction("Download This Track")
            dl_sub = menu.addMenu("Download via Specific Source")
            dl_sub.setStyleSheet(menu_style)
            act_dl_melo = dl_sub.addAction("Telegram Bot (MeloBot)")
            act_dl_musi = dl_sub.addAction("Musilon")
            act_dl_yt = dl_sub.addAction("YouTube Music")

        act_cancel = None
        if item.status in ("Downloading", "Resolving", "Queued", "Paused"):
            menu.addSeparator()
            act_cancel = menu.addAction("Cancel / Stop Download")

        act_retry = None
        if item.status in ("Failed", "Stopped"):
            menu.addSeparator()
            act_retry = menu.addAction("Retry Download")

        act_reset = None
        if item.status in ("Failed", "Queued", "Stopped"):
            menu.addSeparator()
            act_reset = menu.addAction("Reset Status to Pending")

        menu.addSeparator()
        act_copy_title = menu.addAction("Copy Title & Artist")
        act_copy_url = menu.addAction("Copy Spotify URL")
        
        act_export_selected = None
        selected_rows = self.table.selectionModel().selectedRows()
        if is_downloaded or len(selected_rows) > 0:
            act_export_selected = menu.addAction("Export Selected Tracks to Folder / Device...")

        act_m3u8 = menu.addAction("Export Playlist (.m3u8)")

        menu.addSeparator()
        act_edit_track = menu.addAction("Edit Track Metadata...")
        act_edit_playlist = menu.addAction("Edit Playlist Details...")

        action = menu.exec(self.table.viewport().mapToGlobal(pos))
        if not action:
            return

        if act_play and action == act_play:
            if item.output_path and os.path.isfile(item.output_path):
                main_win = self.window()
                if hasattr(main_win, "play_audio_track"):
                    items = [self.model.get_item(i) for i in range(self.model.rowCount())]
                    valid_items = [it for it in items if it and it.output_path and os.path.isfile(it.output_path)]
                    curr_idx = valid_items.index(item) if item in valid_items else -1
                    main_win.play_audio_track(item.output_path, item.track, item.quality_badge, playlist=valid_items, index=curr_idx)
                else:
                    os.startfile(item.output_path)
            else:
                InfoBar.warning(title="File Missing", content="The audio file was not found on disk.", parent=self)
        elif act_delete_file and action == act_delete_file:
            t = item.track
            file_to_del = item.output_path
            if not file_to_del:
                row = self.archive.find_track(spotify_id=t.id)
                if row:
                    file_to_del = row.get("file_path", "")
            if file_to_del and os.path.exists(file_to_del):
                try:
                    os.remove(file_to_del)
                except Exception as e_del:
                    logger.warning(f"Failed to delete file {file_to_del}: {e_del}")
            self.archive.remove_downloaded_track(t.id, playlist_id=self.current_playlist_id)
            item.status = "Pending"
            item.output_path = ""
            item.quality_badge = ""
            item.source_type = ""
            item.progress_percent = 0.0
            self.model.update_status(t.id, "Pending")
            self._refresh_detail_header()
            InfoBar.success(
                title="File Deleted",
                content=f"Deleted '{t.title}' from disk and marked as Pending.",
                orient=Qt.Orientation.Horizontal,
                position=InfoBarPosition.TOP,
                duration=3500,
                parent=self
            )
        elif act_redl_auto and action in (act_redl_auto, act_redl_melo, act_redl_musi, act_redl_yt):
            t = item.track
            file_to_del = item.output_path
            if not file_to_del:
                row = self.archive.find_track(spotify_id=t.id)
                if row:
                    file_to_del = row.get("file_path", "")
            if file_to_del and os.path.exists(file_to_del):
                try:
                    os.remove(file_to_del)
                except Exception as e_del:
                    logger.warning(f"Failed to delete old file {file_to_del}: {e_del}")
            self.archive.remove_downloaded_track(t.id, playlist_id=self.current_playlist_id)

            engine_choice = "auto"
            engine_label = "Auto (Best Available)"
            if action == act_redl_melo:
                engine_choice = "melobot"
                engine_label = "Telegram Bot (MeloBot)"
            elif action == act_redl_musi:
                engine_choice = "musilon"
                engine_label = "Musilon"
            elif action == act_redl_yt:
                engine_choice = "youtube"
                engine_label = "YouTube Music"

            t.preferred_engine = engine_choice
            if self.current_playlist_data:
                t.collection_name = self.current_playlist_data.get("name", "Playlist")
                t.collection_type = "playlist"
                t.collection_cover_url = self.current_playlist_data.get("cover_url", "") or ""

            self.archive.mark_saved_tracks_queued(self.current_playlist_id, [t.id])
            self.qm.enqueue([t])
            self.qm.start_all()

            item.status = "Queued"
            item.output_path = ""
            item.quality_badge = ""
            item.source_type = ""
            item.progress_percent = 0.0
            self.model.update_status(t.id, "Queued")
            self._refresh_detail_header()
            InfoBar.info(
                title="Re-downloading",
                content=f"Re-downloading '{t.title}' via {engine_label}...",
                orient=Qt.Orientation.Horizontal,
                position=InfoBarPosition.TOP,
                duration=4000,
                parent=self
            )
        elif act_download and action in (act_download, act_dl_melo, act_dl_musi, act_dl_yt):
            t = item.track
            engine_choice = None
            engine_label = "Auto"
            if action == act_dl_melo:
                engine_choice = "melobot"
                engine_label = "Telegram Bot"
            elif action == act_dl_musi:
                engine_choice = "musilon"
                engine_label = "Musilon"
            elif action == act_dl_yt:
                engine_choice = "youtube"
                engine_label = "YouTube Music"

            t.preferred_engine = engine_choice
            if self.current_playlist_data:
                t.collection_name = self.current_playlist_data.get("name", "Playlist")
                t.collection_type = "playlist"
                t.collection_cover_url = self.current_playlist_data.get("cover_url", "") or ""
            self.archive.mark_saved_tracks_queued(self.current_playlist_id, [t.id])
            self.qm.enqueue([t])
            self.qm.start_all()
            item.status = "Queued"
            self.model.update_status(t.id, "Queued")
            if engine_choice:
                InfoBar.info(
                    title="Downloading",
                    content=f"Downloading '{t.title}' via {engine_label}...",
                    orient=Qt.Orientation.Horizontal,
                    position=InfoBarPosition.TOP,
                    duration=3500,
                    parent=self
                )
        elif act_cancel and action == act_cancel:
            self.qm.cancel_track(item.track.id)
            self.archive.update_saved_track_status(self.current_playlist_id, item.track.id, "pending")
            item.status = "Stopped"
            self.model.update_status(item.track.id, "Stopped")
            self._refresh_detail_header()
        elif act_retry and action == act_retry:
            t = item.track
            if self.current_playlist_data:
                t.collection_name = self.current_playlist_data.get("name", "Playlist")
                t.collection_type = "playlist"
                t.collection_cover_url = self.current_playlist_data.get("cover_url", "") or ""
            self.archive.mark_saved_tracks_queued(self.current_playlist_id, [t.id])
            self.qm.enqueue([t])
            self.qm.start_all()
            item.status = "Queued"
            self.model.update_status(t.id, "Queued")
            self._refresh_detail_header()
        elif action == act_copy_title:
            QApplication.clipboard().setText(f"{item.track.title} - {item.track.artist_str}")
        elif action == act_copy_url:
            QApplication.clipboard().setText(f"https://open.spotify.com/track/{item.track.id}")
        elif act_reveal and action == act_reveal:
            if item.output_path and os.path.exists(item.output_path):
                flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
                subprocess.Popen(["explorer", f"/select,{os.path.normpath(item.output_path)}"], creationflags=flags)
            else:
                InfoBar.warning(
                    title="File Missing",
                    content="The audio file was not found on disk.",
                    orient=Qt.Orientation.Horizontal,
                    position=InfoBarPosition.TOP,
                    duration=3000,
                    parent=self
                )
        elif act_spectrum and action == act_spectrum:
            if item.output_path and os.path.isfile(item.output_path):
                from gui.dialogs.spectrum_dialog import AudioSpectrumDialog
                def _upgrade_from_playlist(fp, tr):
                    if fp and os.path.exists(fp):
                        try:
                            os.remove(fp)
                        except Exception:
                            pass
                    self.archive.remove_downloaded_track(tr.id, playlist_id=self.current_playlist_id)
                    tr.preferred_engine = "auto"
                    if self.current_playlist_data:
                        tr.collection_name = self.current_playlist_data.get("name", "Playlist")
                        tr.collection_type = "playlist"
                        tr.collection_cover_url = self.current_playlist_data.get("cover_url", "") or ""
                    self.archive.mark_saved_tracks_queued(self.current_playlist_id, [tr.id])
                    self.qm.enqueue([tr])
                    self.qm.start_all()
                    item.status = "Queued"
                    self.model.update_status(tr.id, "Queued")
                    self._refresh_detail_header()
                    InfoBar.info("Upgrading Track", f"Re-downloading '{tr.title}' in highest available quality...", duration=4000, parent=self)
                dlg = AudioSpectrumDialog(item.output_path, track=item.track, on_upgrade_callback=_upgrade_from_playlist, parent=self.window() or self)
                dlg.exec()
        elif act_reset and action == act_reset:
            self.archive.update_saved_track_status(self.current_playlist_id, item.track.id, "pending")
            item.status = "Pending"
            self.model.update_status(item.track.id, "Pending")
            self._refresh_detail_header()
        elif act_export_selected and action == act_export_selected:
            self._on_export_selected_clicked(fallback_item=item)
        elif action == act_m3u8:
            self._on_export_m3u8_clicked()
        elif action == act_edit_track:
            self._edit_track_metadata(item)
        elif action == act_edit_playlist:
            self._handle_detail_edit()

    def _edit_track_metadata(self, item: QueueItem):
        if not item or not item.track or not self.current_playlist_id:
            return
        track_dict = {
            "title": item.track.title,
            "artist": item.track.artist_str,
            "album": item.track.album or ""
        }
        diag = EditTrackDialog(track_dict, self.window() or self)
        if diag.exec():
            new_title = diag.title_input.text().strip()
            new_artist = diag.artist_input.text().strip()
            new_album = diag.album_input.text().strip()
            ok = self.archive.update_saved_playlist_track(
                self.current_playlist_id,
                item.track.id,
                title=new_title,
                artist=new_artist,
                album=new_album
            )
            if ok:
                item.track.title = new_title
                item.track.artists = [a.strip() for a in new_artist.split(",")]
                item.track.album = new_album
                self.model.layoutChanged.emit()
                InfoBar.success(
                    title="Track Updated",
                    content=f"Updated '{new_title}'.",
                    orient=Qt.Orientation.Horizontal,
                    position=InfoBarPosition.TOP,
                    duration=3000,
                    parent=self
                )

    def _on_export_m3u8_clicked(self):
        if not self.current_playlist_id:
            return
        pl_name = self.current_playlist_data.get("name", "Playlist") if self.current_playlist_data else "Playlist"
        tracks = self.archive.get_saved_playlist_tracks(self.current_playlist_id, status="downloaded")
        valid_tracks = [t for t in tracks if t.get("file_path") and os.path.isfile(t.get("file_path"))]
        if not valid_tracks:
            InfoBar.warning(
                title="No Downloaded Songs",
                content=f"No downloaded songs found on disk for '{pl_name}'. Please download songs first.",
                orient=Qt.Orientation.Horizontal,
                position=InfoBarPosition.TOP,
                duration=4000,
                parent=self
            )
            return

        diag = ExportM3UDialog(
            playlist_name=pl_name,
            tracks=valid_tracks,
            archive=self.archive,
            playlist_id=self.current_playlist_id,
            parent=self.window() or self
        )
        diag.exec()

    def _on_export_songs_clicked(self):
        if not self.current_playlist_id:
            return
        pl_name = self.current_playlist_data.get("name", "Playlist") if self.current_playlist_data else "Playlist"
        tracks = self.archive.get_saved_playlist_tracks(self.current_playlist_id, status="downloaded")
        valid_tracks = [t for t in tracks if t.get("file_path") and os.path.isfile(t.get("file_path"))]
        if not valid_tracks:
            InfoBar.warning(
                title="No Downloaded Songs",
                content=f"No downloaded songs found on disk for '{pl_name}'. Please download songs first.",
                orient=Qt.Orientation.Horizontal,
                position=InfoBarPosition.TOP,
                duration=4000,
                parent=self
            )
            return

        diag = ExportDialog(pl_name, valid_tracks, self.window() or self)
        diag.exec()

    def _on_export_selected_clicked(self, fallback_item: Optional[QueueItem] = None):
        if not self.current_playlist_id:
            return
        pl_name = self.current_playlist_data.get("name", "Playlist") if self.current_playlist_data else "Exported Songs"

        selected_indexes = self.table.selectionModel().selectedRows()
        selected_items = []
        if selected_indexes:
            for idx in selected_indexes:
                it = self.model.get_item(idx.row())
                if it and it.output_path and os.path.isfile(it.output_path):
                    selected_items.append(it)

        if not selected_items and fallback_item:
            if fallback_item.output_path and os.path.isfile(fallback_item.output_path):
                selected_items.append(fallback_item)

        if not selected_items:
            InfoBar.warning(
                title="No Downloaded Tracks Selected",
                content="Please select at least one downloaded track to export.",
                orient=Qt.Orientation.Horizontal,
                position=InfoBarPosition.TOP,
                duration=3500,
                parent=self
            )
            return

        diag = ExportDialog(pl_name, selected_items, self.window() or self)
        diag.exec()


    # -------------------------------------------------------------
    # Live Bridging
    # -------------------------------------------------------------
    def _handle_bridge_completed(self, track_id: str, path: str):
        self._playlists_dirty = True
        if self.current_playlist_id and self.stacked.currentIndex() == 1:
            self.model.mark_completed(track_id, path)
            self._refresh_detail_header()

    def _handle_bridge_status(self, track_id: str, status: str):
        if self.current_playlist_id and self.stacked.currentIndex() == 1:
            self.model.update_status(track_id, status)

    def _handle_bridge_progress(self, track_id: str, percent: float, speed_str: str, eta_str: str):
        if self.current_playlist_id and self.stacked.currentIndex() == 1:
            self.model.update_progress(track_id, percent, speed_str, eta_str)

    def _handle_bridge_source_resolved(self, track_id: str, source_type: str, quality_badge: str):
        if self.current_playlist_id and self.stacked.currentIndex() == 1:
            self.model.update_source(track_id, source_type, quality_badge)

    def _handle_bridge_failed(self, track_id: str, error_msg: str):
        if self.current_playlist_id and self.stacked.currentIndex() == 1:
            self.model.mark_failed(track_id, error_msg)
            self._refresh_detail_header()

    def showEvent(self, event):
        super().showEvent(event)
        if getattr(self, "_banner_dirty", False):
            self._update_api_banner()
            self._banner_dirty = False
        if self.stacked.currentIndex() == 1 and self.current_playlist_id:
            if getattr(self, "_detail_dirty", False):
                self._load_detail_tracks()
                self._refresh_detail_header()
                self._detail_dirty = False
        elif self.stacked.currentIndex() == 0:
            if getattr(self, "_playlists_dirty", False):
                self.reload_playlists()
                self._playlists_dirty = False
