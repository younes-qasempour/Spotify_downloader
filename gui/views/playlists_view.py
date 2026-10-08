import os
import subprocess
import threading
from typing import Optional, List, Dict, Any

from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QModelIndex, QRectF, QUrl
from PyQt6.QtGui import QImage, QPixmap, QPainter, QPainterPath, QColor, QDesktopServices
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QHeaderView, QMenu, QApplication,
    QStackedWidget, QLabel, QFrame
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
from gui.bridge import EngineSignalBridge
from gui.styles import TEXT_MUTED, TEXT_PRIMARY, TEXT_SECONDARY, BG_CARD, SPOTIFY_EMERALD

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


class MetricCard(CardWidget):
    """Sleek metric summary card."""
    def __init__(self, title: str, initial_value: str = "0", parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(4)

        self.title_label = CaptionLabel(title, self)
        self.title_label.setTextColor(TEXT_MUTED, TEXT_MUTED)
        self.value_label = StrongBodyLabel(initial_value, self)
        self.value_label.setStyleSheet("font-size: 20px; font-weight: bold; color: white;")

        layout.addWidget(self.title_label)
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
        parent=None
    ):
        super().__init__(parent)
        self.data = playlist_data
        self.on_open = on_open
        self.on_delete = on_delete
        self.setCursor(Qt.CursorShape.PointingHandCursor)

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
        layout.setContentsMargins(16, 14, 18, 14)
        layout.setSpacing(16)

        # 1. Playlist Cover Artwork (64x64)
        self.thumb_label = QLabel(self)
        self.thumb_label.setFixedSize(64, 64)
        self.thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb_label.setStyleSheet("""
            QLabel {
                background-color: #2c2c2c;
                border: 1px solid rgba(255, 255, 255, 0.10);
                border-radius: 8px;
            }
        """)

        self._load_cover(playlist_data)
        layout.addWidget(self.thumb_label)

        # 2. Metadata Section (Title, Stats, Progress Bar)
        info_layout = QVBoxLayout()
        info_layout.setSpacing(4)

        name = playlist_data.get("name") or "Untitled Playlist"
        tot = playlist_data.get("total_tracks") or 0
        down = playlist_data.get("downloaded_count") or 0
        pend = playlist_data.get("pending_count") or (tot - down)
        pct = playlist_data.get("progress_percent") or (round(down / tot * 100.0, 1) if tot > 0 else 0.0)

        self.title_label = StrongBodyLabel(name, self)
        self.title_label.setStyleSheet("font-size: 15px; font-weight: bold; color: #FFFFFF;")

        status_text = f"{tot} tracks  •  {down} downloaded  •  {pend} pending ({pct}%)"
        self.meta_label = CaptionLabel(status_text, self)
        self.meta_label.setTextColor(TEXT_MUTED, TEXT_MUTED)

        # Progress bar
        self.progress_bar = ProgressBar(self)
        self.progress_bar.setFixedHeight(4)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(int(pct))
        self.progress_bar.setStyleSheet("""
            ProgressBar {
                background-color: #333333;
                border-radius: 2px;
            }
        """)

        info_layout.addWidget(self.title_label)
        info_layout.addWidget(self.meta_label)
        info_layout.addWidget(self.progress_bar)
        layout.addLayout(info_layout, 1)

        # 3. Actions Section
        action_layout = QHBoxLayout()
        action_layout.setSpacing(8)

        self.browse_btn = PrimaryPushButton(FluentIcon.CHEVRON_RIGHT, "Browse & Download", self)
        self.browse_btn.clicked.connect(self._handle_open)

        self.copy_btn = ToolButton(FluentIcon.COPY, self)
        self.copy_btn.setToolTip("Copy Spotify Link")
        self.copy_btn.clicked.connect(self._copy_link)

        self.delete_btn = ToolButton(FluentIcon.DELETE, self)
        self.delete_btn.setToolTip("Remove from Saved Playlists")
        self.delete_btn.clicked.connect(self._handle_delete)

        action_layout.addWidget(self.browse_btn)
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
                    scaled = img.scaled(64, 64, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
                    rounded = QPixmap(64, 64)
                    rounded.fill(Qt.GlobalColor.transparent)
                    p = QPainter(rounded)
                    p.setRenderHint(QPainter.RenderHint.Antialiasing)
                    path = QPainterPath()
                    path.addRoundedRect(0, 0, 64, 64, 8, 8)
                    p.setClipPath(path)
                    p.drawPixmap(0, 0, QPixmap.fromImage(scaled))
                    p.end()
                    self.thumb_label.setPixmap(rounded)
                    loaded = True
            except Exception:
                pass

        if not loaded:
            icon_w = IconWidget(FluentIcon.MUSIC_FOLDER, self.thumb_label)
            icon_w.setFixedSize(36, 36)
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

    def _handle_delete(self):
        if self.on_delete:
            self.on_delete(self.data.get("id"))

    def _copy_link(self):
        url = self.data.get("spotify_url", "")
        if url:
            QApplication.clipboard().setText(url)


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

        self._init_ui()
        self._connect_signals()

        # Load initial saved playlists
        self.reload_playlists()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(24, 20, 24, 20)
        main_layout.setSpacing(16)

        self.stacked = QStackedWidget(self)

        # -------------------------------------------------------------
        # Page 0: Playlists List / Overview
        # -------------------------------------------------------------
        self.list_page = QWidget(self)
        list_layout = QVBoxLayout(self.list_page)
        list_layout.setContentsMargins(0, 0, 0, 0)
        list_layout.setSpacing(16)

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

        input_layout.addWidget(self.url_input, 1)
        input_layout.addWidget(self.paste_btn)
        input_layout.addWidget(self.save_btn)
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
        detail_layout.setSpacing(14)

        # 1. Detail Top Navigation & Header
        nav_layout = QHBoxLayout()
        self.back_btn = PushButton(FluentIcon.LEFT_ARROW, "Back to Playlists", self)
        self.back_btn.clicked.connect(self._show_overview)
        nav_layout.addWidget(self.back_btn)
        nav_layout.addStretch(1)
        detail_layout.addLayout(nav_layout)

        # Playlist Banner Card
        self.banner_card = CardWidget(self.detail_page)
        banner_layout = QHBoxLayout(self.banner_card)
        banner_layout.setContentsMargins(16, 14, 16, 14)
        banner_layout.setSpacing(16)

        self.detail_thumb = QLabel(self)
        self.detail_thumb.setFixedSize(72, 72)
        self.detail_thumb.setStyleSheet("""
            QLabel {
                background-color: #2c2c2c;
                border: 1px solid rgba(255, 255, 255, 0.10);
                border-radius: 8px;
            }
        """)
        self.detail_thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        banner_layout.addWidget(self.detail_thumb)

        detail_info_layout = QVBoxLayout()
        detail_info_layout.setSpacing(4)
        self.detail_title = SubtitleLabel("Playlist Name", self)
        self.detail_stats_label = CaptionLabel("0 Total • 0 Downloaded • 0 Pending", self)
        self.detail_stats_label.setTextColor(TEXT_MUTED, TEXT_MUTED)

        self.detail_progress_bar = ProgressBar(self)
        self.detail_progress_bar.setFixedHeight(5)
        self.detail_progress_bar.setRange(0, 100)

        detail_info_layout.addWidget(self.detail_title)
        detail_info_layout.addWidget(self.detail_stats_label)
        detail_info_layout.addWidget(self.detail_progress_bar)
        banner_layout.addLayout(detail_info_layout, 1)

        detail_layout.addWidget(self.banner_card)

        # 2. Batch Download Controls Panel
        batch_card = CardWidget(self.detail_page)
        batch_layout = QVBoxLayout(batch_card)
        batch_layout.setContentsMargins(16, 14, 16, 14)
        batch_layout.setSpacing(10)

        batch_header = QHBoxLayout()
        batch_title = StrongBodyLabel("Batch Audio Download", self)
        batch_desc = CaptionLabel("Download pending songs in controlled batches to preserve Musilon VIP daily limits.", self)
        batch_desc.setTextColor(TEXT_MUTED, TEXT_MUTED)
        batch_header.addWidget(batch_title)
        batch_header.addWidget(batch_desc)
        batch_header.addStretch(1)
        batch_layout.addLayout(batch_header)

        spin_lbl = BodyLabel("Batch Size:", self)
        self.batch_spinbox = SpinBox(self)
        self.batch_spinbox.setRange(1, 5000)
        self.batch_spinbox.setValue(50)
        self.batch_spinbox.setFixedWidth(135)
        self.batch_spinbox.setStyleSheet("""
            SpinBox {
                color: #FFFFFF;
                font-weight: 600;
                font-size: 13px;
                background-color: rgba(255, 255, 255, 0.08);
                border: 1px solid rgba(255, 255, 255, 0.18);
                border-radius: 6px;
                padding-left: 10px;
                padding-right: 68px;
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

        # Preset buttons
        self.preset_25 = PushButton("25", self)
        self.preset_25.setFixedWidth(46)
        self.preset_25.setStyleSheet(PRESET_NORMAL_STYLE)
        self.preset_25.clicked.connect(lambda: self._select_batch_preset(25))

        self.preset_50 = PushButton("50", self)
        self.preset_50.setFixedWidth(46)
        self.preset_50.setStyleSheet(PRESET_NORMAL_STYLE)
        self.preset_50.clicked.connect(lambda: self._select_batch_preset(50))

        self.preset_100 = PushButton("100", self)
        self.preset_100.setFixedWidth(52)
        self.preset_100.setStyleSheet(PRESET_NORMAL_STYLE)
        self.preset_100.clicked.connect(lambda: self._select_batch_preset(100))

        self.preset_200 = PushButton("200", self)
        self.preset_200.setFixedWidth(52)
        self.preset_200.setStyleSheet(PRESET_NORMAL_STYLE)
        self.preset_200.clicked.connect(lambda: self._select_batch_preset(200))

        self.preset_all = PushButton("All Pending", self)
        self.preset_all.setFixedWidth(92)
        self.preset_all.setStyleSheet(PRESET_NORMAL_STYLE)
        self.preset_all.clicked.connect(self._set_batch_to_all_pending)

        # Main Download Button
        self.download_batch_btn = PrimaryPushButton(FluentIcon.DOWNLOAD, "Download Next Batch (50)", self)
        self.download_batch_btn.clicked.connect(self._on_download_batch_clicked)

        self.download_selected_btn = PushButton(FluentIcon.CHECKBOX, "Download Selected", self)
        self.download_selected_btn.clicked.connect(self._on_download_selected_clicked)

        self.pause_btn = PushButton(FluentIcon.PAUSE, "Pause", self)
        self.pause_btn.clicked.connect(self._on_pause_clicked)

        self.stop_btn = PushButton(FluentIcon.CLOSE, "Stop", self)
        self.stop_btn.clicked.connect(self._on_stop_clicked)

        self.reset_btn = ToolButton(FluentIcon.SYNC, self)
        self.reset_btn.setToolTip("Reset queued & failed tracks in this playlist back to pending")
        self.reset_btn.clicked.connect(self._on_reset_queued_clicked)

        self.open_folder_btn = PushButton(FluentIcon.FOLDER, "Open Folder", self)
        self.open_folder_btn.clicked.connect(self._open_download_folder)

        # Row 1: Batch Size Selection & Quick Presets
        batch_size_layout = QHBoxLayout()
        batch_size_layout.setSpacing(8)
        batch_size_layout.addWidget(spin_lbl)
        batch_size_layout.addWidget(self.batch_spinbox)
        batch_size_layout.addWidget(self.preset_25)
        batch_size_layout.addWidget(self.preset_50)
        batch_size_layout.addWidget(self.preset_100)
        batch_size_layout.addWidget(self.preset_200)
        batch_size_layout.addWidget(self.preset_all)
        batch_size_layout.addStretch(1)

        # Row 2: Action Buttons
        batch_action_layout = QHBoxLayout()
        batch_action_layout.setSpacing(10)
        batch_action_layout.addWidget(self.download_batch_btn)
        batch_action_layout.addWidget(self.download_selected_btn)
        batch_action_layout.addWidget(self.pause_btn)
        batch_action_layout.addWidget(self.stop_btn)
        batch_action_layout.addWidget(self.reset_btn)
        batch_action_layout.addWidget(self.open_folder_btn)
        batch_action_layout.addStretch(1)

        batch_layout.addLayout(batch_size_layout)
        batch_layout.addSpacing(6)
        batch_layout.addLayout(batch_action_layout)
        detail_layout.addWidget(batch_card)

        # 3. Track Search & Status Filter Row
        filter_layout = QHBoxLayout()
        filter_layout.setSpacing(10)

        self.track_search_input = LineEdit(self)
        self.track_search_input.setPlaceholderText("Filter tracks in this playlist by title or artist...")
        self.track_search_input.setClearButtonEnabled(True)
        self.track_search_input.textChanged.connect(self._on_track_filter_changed)

        self.status_filter_combo = ComboBox(self)
        self.status_filter_combo.addItems(["All Statuses", "Pending Only", "Queued Only", "Downloaded Only"])
        self.status_filter_combo.currentIndexChanged.connect(self._on_track_filter_changed)
        self.status_filter_combo.setFixedWidth(150)

        filter_layout.addWidget(self.track_search_input, 1)
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
        self.table.verticalHeader().setDefaultSectionSize(76)
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
        has_auth = self.spotify_client.has_user_auth()

        if has_auth:
            user_name = self.spotify_client.get_current_user_name()
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
                    self.sig_auth_done.emit(True, msg)
                else:
                    self.sig_auth_done.emit(False, "Could not complete Spotify authorization.")
            except Exception as e:
                self.sig_auth_done.emit(False, str(e))
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
        if entity_type not in ("playlist", "album"):
            InfoBar.warning(
                title="Not a Playlist",
                content="Please provide a Spotify Playlist or Album link to save tracks to offline storage.",
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

                pl_name = tracks[0].collection_name or "Spotify Playlist"
                pl_cover = tracks[0].collection_cover_url or tracks[0].cover_url or ""

                saved_info = self.archive.save_playlist(
                    name=pl_name,
                    spotify_url=url,
                    cover_url=pl_cover,
                    tracks=tracks,
                    playlist_id=entity_id
                )
                is_guest = getattr(self.spotify_client, "last_resolution_mode", "api") == "guest"
                was_truncated = getattr(self.spotify_client, "last_was_truncated", False) or (is_guest and len(tracks) == 100)
                saved_info["was_truncated"] = was_truncated
                saved_info["is_guest"] = is_guest
                saved_info["api_error"] = getattr(self.spotify_client, "last_api_error", "")
                saved_info["owner_name"] = getattr(self.spotify_client, "last_owner_name", "")
                saved_info["auth_user"] = self.spotify_client.get_current_user_name()

                self.sig_playlist_saved.emit(saved_info)
            except Exception as e:
                self.sig_save_failed.emit(str(e))

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
                parent=self.playlists_container
            )
            self.playlists_layout.insertWidget(self.playlists_layout.count() - 1, card)

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

    # -------------------------------------------------------------
    # Detail View Logic
    # -------------------------------------------------------------
    def _open_playlist_detail(self, playlist_data: Dict[str, Any]):
        self.current_playlist_id = playlist_data["id"]
        self.current_playlist_data = playlist_data

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
                    scaled = img.scaled(72, 72, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
                    rounded = QPixmap(72, 72)
                    rounded.fill(Qt.GlobalColor.transparent)
                    p = QPainter(rounded)
                    p.setRenderHint(QPainter.RenderHint.Antialiasing)
                    path = QPainterPath()
                    path.addRoundedRect(0, 0, 72, 72, 8, 8)
                    p.setClipPath(path)
                    p.drawPixmap(0, 0, QPixmap.fromImage(scaled))
                    p.end()
                    self.detail_thumb.setPixmap(rounded)
            except Exception:
                pass
        else:
            self.detail_thumb.clear()
            icon_w = IconWidget(FluentIcon.MUSIC_FOLDER, self.detail_thumb)
            icon_w.setFixedSize(40, 40)
            icon_lay = QHBoxLayout(self.detail_thumb)
            icon_lay.setContentsMargins(0, 0, 0, 0)
            icon_lay.addWidget(icon_w, 0, Qt.AlignmentFlag.AlignCenter)

        # Batch spinbox setup (unclamped up to 5000)
        self.batch_spinbox.setRange(1, 5000)
        self.batch_spinbox.setValue(50)
        self._on_batch_size_changed(self.batch_spinbox.value())

        # Reset search and combo
        self.track_search_input.clear()
        self.status_filter_combo.setCurrentIndex(0)

        self._load_detail_tracks()
        self.stacked.setCurrentIndex(1)

    def _show_overview(self):
        self.stacked.setCurrentIndex(0)
        self.current_playlist_id = None
        self.current_playlist_data = None
        self.reload_playlists()

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

        rows = self.archive.get_saved_playlist_tracks(
            self.current_playlist_id,
            status=status_filter,
            search_query=search_query
        )

        self.model.clear()
        for r in rows:
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
                collection_type="playlist"
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
            self.model.add_item(item)
            row_idx = self.model.rowCount() - 1
            if row_idx >= 0:
                self.table.setRowHeight(row_idx, 76)

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
        if self.current_playlist_data:
            from core.utils import sanitize_filename
            safe_name = sanitize_filename(self.current_playlist_data.get("name", ""))
            specific_folder = os.path.join(out_dir, safe_name)
            if os.path.isdir(specific_folder):
                out_dir = specific_folder

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
        menu.setStyleSheet("""
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
        """)

        act_download = menu.addAction("Download This Track")
        act_copy_title = menu.addAction("Copy Title & Artist")
        act_copy_url = menu.addAction("Copy Spotify URL")

        act_cancel = None
        if item.status in ("Downloading", "Resolving", "Queued", "Paused"):
            menu.addSeparator()
            act_cancel = menu.addAction("Cancel / Stop Download")

        act_retry = None
        if item.status in ("Failed", "Stopped"):
            menu.addSeparator()
            act_retry = menu.addAction("Retry Download")

        act_reveal = None
        if item.output_path and os.path.isfile(item.output_path):
            menu.addSeparator()
            act_reveal = menu.addAction("Reveal in File Explorer")

        act_reset = None
        if item.status in ("Failed", "Queued", "Stopped"):
            menu.addSeparator()
            act_reset = menu.addAction("Reset Status to Pending")

        action = menu.exec(self.table.viewport().mapToGlobal(pos))
        if action == act_download:
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
        elif act_reset and action == act_reset:
            self.archive.update_saved_track_status(self.current_playlist_id, item.track.id, "pending")
            item.status = "Pending"
            self.model.update_status(item.track.id, "Pending")
            self._refresh_detail_header()

    # -------------------------------------------------------------
    # Live Bridging
    # -------------------------------------------------------------
    def _handle_bridge_completed(self, track_id: str, path: str):
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
        self._update_api_banner()
        if self.stacked.currentIndex() == 1 and self.current_playlist_id:
            self._load_detail_tracks()
            self._refresh_detail_header()
        elif self.stacked.currentIndex() == 0:
            self.reload_playlists()
