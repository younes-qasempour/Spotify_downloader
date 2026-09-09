import os
import subprocess
from typing import Optional, List, Dict, Any
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QHeaderView, QMenu, QApplication,
    QStackedWidget, QFrame, QLabel
)
from PyQt6.QtGui import QImage, QPixmap, QPainter, QPainterPath
from qfluentwidgets import (
    TableView, SubtitleLabel, PushButton, PrimaryPushButton, ToolButton,
    FluentIcon, InfoBar, LineEdit, CaptionLabel, StrongBodyLabel, BodyLabel,
    SegmentedWidget, CardWidget, SmoothScrollArea, IconWidget
)

from gui.queue_model import TrackQueueModel
from gui.queue_delegate import TrackCardDelegate
from gui.bridge import EngineSignalBridge
from gui.styles import TEXT_MUTED, BG_CARD, SPOTIFY_EMERALD
from core.archive import ArchiveManager
from core.spotify_client import TrackMetadata
from core.queue_manager import QueueItem
from core.config import config


class CollectionCard(CardWidget):
    """
    Sleek modern card representing a downloaded Playlist or Album.
    Provides folder thumbnail, info, track counts, and quick actions to open folder or browse tracks.
    """

    def __init__(
        self,
        title: str,
        subtitle: str,
        folder_path: str,
        icon: FluentIcon = FluentIcon.FOLDER,
        cover_path: Optional[str] = None,
        on_browse=None,
        parent=None
    ):
        super().__init__(parent)
        self.folder_path = folder_path
        self.cover_path = cover_path
        self.on_browse = on_browse
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 12, 18, 12)
        layout.setSpacing(16)

        self.setStyleSheet("""
            CardWidget, CollectionCard {
                background-color: #222222;
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 8px;
            }
            CardWidget:hover, CollectionCard:hover {
                background-color: #2a2a2a;
                border: 1px solid rgba(255, 255, 255, 0.16);
            }
        """)

        # 1. Collection Cover Thumbnail / Icon (54x54)
        self.thumb_label = QLabel(self)
        self.thumb_label.setFixedSize(54, 54)
        self.thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb_label.setStyleSheet("""
            QLabel {
                background-color: #2b2b2b;
                border: 1px solid rgba(255, 255, 255, 0.10);
                border-radius: 8px;
            }
        """)

        loaded_pixmap = False
        if cover_path and os.path.isfile(cover_path):
            try:
                img = QImage(cover_path)
                if not img.isNull():
                    scaled = img.scaled(54, 54, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
                    rounded = QPixmap(54, 54)
                    rounded.fill(Qt.GlobalColor.transparent)
                    p = QPainter(rounded)
                    p.setRenderHint(QPainter.RenderHint.Antialiasing)
                    path = QPainterPath()
                    path.addRoundedRect(0, 0, 54, 54, 8, 8)
                    p.setClipPath(path)
                    p.drawPixmap(0, 0, QPixmap.fromImage(scaled))
                    p.end()
                    self.thumb_label.setPixmap(rounded)
                    loaded_pixmap = True
            except Exception:
                pass

        if not loaded_pixmap:
            icon_w = IconWidget(icon, self.thumb_label)
            icon_w.setFixedSize(30, 30)
            icon_lay = QHBoxLayout(self.thumb_label)
            icon_lay.setContentsMargins(0, 0, 0, 0)
            icon_lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
            icon_lay.addWidget(icon_w)

        layout.addWidget(self.thumb_label)

        # 2. Text Metadata
        text_layout = QVBoxLayout()
        text_layout.setSpacing(4)

        self.title_label = StrongBodyLabel(title, self)
        self.title_label.setStyleSheet("font-size: 15px; font-weight: 600; color: #FFFFFF;")

        self.subtitle_label = CaptionLabel(subtitle, self)
        self.subtitle_label.setTextColor(TEXT_MUTED, TEXT_MUTED)

        text_layout.addWidget(self.title_label)
        text_layout.addWidget(self.subtitle_label)
        layout.addLayout(text_layout, 1)

        # 3. Action Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)

        if on_browse:
            self.browse_btn = PushButton(FluentIcon.MUSIC, "Browse Tracks", self)
            self.browse_btn.clicked.connect(on_browse)
            btn_layout.addWidget(self.browse_btn)

        self.open_btn = PrimaryPushButton(FluentIcon.FOLDER, "Open Folder", self)
        self.open_btn.clicked.connect(self._open_folder)
        btn_layout.addWidget(self.open_btn)

        layout.addLayout(btn_layout)

    def mousePressEvent(self, event):
        """Clicking anywhere on the collection card opens the collection songs."""
        if event.button() == Qt.MouseButton.LeftButton:
            if self.on_browse:
                self.on_browse()
                return
        super().mousePressEvent(event)

    def _open_folder(self):
        if self.folder_path and os.path.isdir(self.folder_path):
            os.startfile(self.folder_path)
        else:
            base_dir = config.get("download.output_dir", os.path.expanduser("~/Music/Spotify Downloads"))
            if os.path.isdir(base_dir):
                os.startfile(base_dir)


class CompletedView(QWidget):
    """
    Persistent Downloaded Music Library & Archive View.
    Features:
    - Backed by SQLite ArchiveManager (preserves all downloads across sessions)
    - 3-Tab Segmented Switcher: All Songs (60) | Playlists (3) | Albums (12)
    - Real-time search across songs, artists, albums, or playlists
    - Double-click to play audio file natively
    - Right-click context menu (Play, Open in Explorer, Remove)
    - Direct folder navigation and one-click Rescan & Sync
    """

    def __init__(self, bridge: EngineSignalBridge, archive_manager: Optional[ArchiveManager] = None, parent=None):
        super().__init__(parent)
        self.bridge = bridge
        self.archive = archive_manager or ArchiveManager()

        self.model = TrackQueueModel(self)
        self.delegate = TrackCardDelegate(self)

        self._current_collection_name: Optional[str] = None
        self._current_collection_type: str = "playlist"
        self._current_collection_folder: str = ""

        self._init_ui()
        self.reload_all()

        # Connect Signal Bridge for live completed events
        self.bridge.sig_completed.connect(self._on_track_completed)

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(24, 20, 24, 20)
        main_layout.setSpacing(14)

        # 1. Header Row
        header_layout = QHBoxLayout()
        header_layout.setSpacing(12)

        title_box = QVBoxLayout()
        title = SubtitleLabel("Music Library & Archive", self)
        self.stats_label = CaptionLabel("Loading library...", self)
        self.stats_label.setTextColor(TEXT_MUTED, TEXT_MUTED)
        title_box.addWidget(title)
        title_box.addWidget(self.stats_label)

        header_layout.addLayout(title_box)
        header_layout.addStretch(1)

        self.open_folder_btn = PushButton(FluentIcon.FOLDER, "Open Downloads Folder", self)
        self.open_folder_btn.clicked.connect(self._open_download_folder)

        self.rescan_btn = ToolButton(FluentIcon.SYNC, self)
        self.rescan_btn.setToolTip("Rescan & Sync Downloads from Disk")
        self.rescan_btn.clicked.connect(self._on_rescan_clicked)

        header_layout.addWidget(self.open_folder_btn)
        header_layout.addWidget(self.rescan_btn)
        main_layout.addLayout(header_layout)

        # 2. Segmented Navigation & Search Row
        nav_row = QHBoxLayout()
        nav_row.setSpacing(16)

        self.segmented = SegmentedWidget(self)
        self.segmented.addItem("tracks", "🎵 All Songs", onClick=lambda: self._switch_tab(0))
        self.segmented.addItem("playlists", "📁 Playlists", onClick=lambda: self._switch_tab(1))
        self.segmented.addItem("albums", "💿 Albums", onClick=lambda: self._switch_tab(2))
        nav_row.addWidget(self.segmented)

        nav_row.addStretch(1)

        self.search_input = LineEdit(self)
        self.search_input.setPlaceholderText("Search songs, artists, albums, or playlists...")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.setFixedWidth(360)
        self.search_input.textChanged.connect(self._on_search_changed)
        nav_row.addWidget(self.search_input)

        main_layout.addLayout(nav_row)

        # 3. Stacked Widget (Pages)
        self.stacked = QStackedWidget(self)

        # --- Page 0: All Songs Table ---
        self.table_page = QWidget(self)
        table_layout = QVBoxLayout(self.table_page)
        table_layout.setContentsMargins(0, 0, 0, 0)
        table_layout.setSpacing(10)

        # Collection Context Banner (displayed when browsing a specific playlist or album)
        self.coll_banner = QFrame(self.table_page)
        self.coll_banner.setStyleSheet("""
            QFrame {
                background-color: #1f1f1f;
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 8px;
            }
        """)
        self.coll_banner.setVisible(False)
        banner_layout = QHBoxLayout(self.coll_banner)
        banner_layout.setContentsMargins(14, 10, 16, 10)
        banner_layout.setSpacing(14)

        self.back_btn = PushButton(FluentIcon.LEFT_ARROW, "Back to Playlists", self.coll_banner)
        self.back_btn.clicked.connect(self._on_back_to_collections)
        banner_layout.addWidget(self.back_btn)

        self.banner_thumb = QLabel(self.coll_banner)
        self.banner_thumb.setFixedSize(44, 44)
        self.banner_thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.banner_thumb.setStyleSheet("background-color: #2a2a2a; border-radius: 6px; border: 1px solid rgba(255, 255, 255, 0.08);")
        banner_layout.addWidget(self.banner_thumb)

        banner_text_box = QVBoxLayout()
        banner_text_box.setSpacing(2)
        self.banner_title = StrongBodyLabel("", self.coll_banner)
        self.banner_title.setStyleSheet("font-size: 15px; font-weight: 600; color: #FFFFFF;")
        self.banner_desc = CaptionLabel("", self.coll_banner)
        self.banner_desc.setTextColor(TEXT_MUTED, TEXT_MUTED)
        banner_text_box.addWidget(self.banner_title)
        banner_text_box.addWidget(self.banner_desc)
        banner_layout.addLayout(banner_text_box, 1)

        self.banner_open_folder_btn = ToolButton(FluentIcon.FOLDER, self.coll_banner)
        self.banner_open_folder_btn.setToolTip("Open Folder in Explorer")
        self.banner_open_folder_btn.clicked.connect(self._open_current_collection_folder)
        banner_layout.addWidget(self.banner_open_folder_btn)

        table_layout.addWidget(self.coll_banner)

        self.table = TableView(self.table_page)
        self.table.setModel(self.model)
        self.table.setItemDelegate(self.delegate)
        self.table.setShowGrid(False)
        self.table.horizontalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(76)
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self.table.setSelectionBehavior(TableView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(TableView.SelectionMode.SingleSelection)
        self.table.setVerticalScrollMode(TableView.ScrollMode.ScrollPerPixel)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.table.setStyleSheet("QTableView { border: none; background-color: transparent; }")
        self.table.doubleClicked.connect(self._on_double_click)

        # Context menu
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)

        table_layout.addWidget(self.table)
        self.stacked.addWidget(self.table_page)

        # --- Page 1: Playlists Grid/List ---
        self.playlists_page = QWidget(self)
        playlists_page_layout = QVBoxLayout(self.playlists_page)
        playlists_page_layout.setContentsMargins(0, 0, 0, 0)

        self.playlists_scroll = SmoothScrollArea(self.playlists_page)
        self.playlists_scroll.setWidgetResizable(True)
        self.playlists_scroll.setStyleSheet("QScrollArea, SmoothScrollArea { border: none; background: transparent; }")
        self.playlists_scroll.viewport().setStyleSheet("background: transparent;")

        self.playlists_container = QWidget()
        self.playlists_container.setStyleSheet("background: transparent;")
        self.playlists_layout = QVBoxLayout(self.playlists_container)
        self.playlists_layout.setContentsMargins(0, 0, 0, 0)
        self.playlists_layout.setSpacing(10)
        self.playlists_layout.addStretch(1)

        self.playlists_scroll.setWidget(self.playlists_container)
        playlists_page_layout.addWidget(self.playlists_scroll)
        self.stacked.addWidget(self.playlists_page)

        # --- Page 2: Albums Grid/List ---
        self.albums_page = QWidget(self)
        albums_page_layout = QVBoxLayout(self.albums_page)
        albums_page_layout.setContentsMargins(0, 0, 0, 0)

        self.albums_scroll = SmoothScrollArea(self.albums_page)
        self.albums_scroll.setWidgetResizable(True)
        self.albums_scroll.setStyleSheet("QScrollArea, SmoothScrollArea { border: none; background: transparent; }")
        self.albums_scroll.viewport().setStyleSheet("background: transparent;")

        self.albums_container = QWidget()
        self.albums_container.setStyleSheet("background: transparent;")
        self.albums_layout = QVBoxLayout(self.albums_container)
        self.albums_layout.setContentsMargins(0, 0, 0, 0)
        self.albums_layout.setSpacing(10)
        self.albums_layout.addStretch(1)

        self.albums_scroll.setWidget(self.albums_container)
        albums_page_layout.addWidget(self.albums_scroll)
        self.stacked.addWidget(self.albums_page)

        main_layout.addWidget(self.stacked, 1)

        # Default to Tracks tab
        self.segmented.setCurrentItem("tracks")
        self.stacked.setCurrentIndex(0)

    def _switch_tab(self, index: int):
        if index != 0 or not self._current_collection_name:
            # Clear collection filter banner when switching tabs or clicking All Songs
            self._current_collection_name = None
            if hasattr(self, "coll_banner"):
                self.coll_banner.setVisible(False)

        self.stacked.setCurrentIndex(index)
        search_query = self.search_input.text().strip()
        if index == 0:
            if self._current_collection_name:
                self._load_collection_tracks(self._current_collection_name, self._current_collection_type, search_query)
            else:
                self.reload_from_archive(search_query)
        elif index == 1:
            self.reload_playlists(search_query)
        elif index == 2:
            self.reload_albums(search_query)

    def reload_all(self):
        """Refreshes high-level library counters and all view tabs."""
        stats = self.archive.get_library_stats()
        t_count = stats["total_tracks"]
        p_count = stats["total_playlists"]
        a_count = stats["total_albums"]
        size_str = stats["size_str"]

        self.segmented.setItemText("tracks", f"🎵 All Songs ({t_count})")
        self.segmented.setItemText("playlists", f"📁 Playlists ({p_count})")
        self.segmented.setItemText("albums", f"💿 Albums ({a_count})")

        self.stats_label.setText(f"{t_count} song(s) • {p_count} collection(s) • {size_str} offline library")

        # Refresh all tabs so switching is instantaneous
        search_query = self.search_input.text().strip()
        if self._current_collection_name and self.stacked.currentIndex() == 0:
            self._load_collection_tracks(self._current_collection_name, self._current_collection_type, search_query)
        else:
            self.reload_from_archive(search_query)
        self.reload_playlists(search_query)
        self.reload_albums(search_query)

    def reload_from_archive(self, search_query: str = ""):
        """Loads or filters tracks from SQLite archive into the virtualized TableView."""
        rows = self.archive.get_all_tracks(search_query)
        self.model.clear()

        for r in rows:
            track = TrackMetadata(
                id=r["spotify_id"],
                title=r["title"],
                artists=[a.strip() for a in r["artist"].split(",")],
                album=r.get("album", ""),
                release_date="",
                duration_ms=r.get("duration_ms", 0),
                collection_name=r.get("collection_name", ""),
                collection_type=r.get("collection_type", "track")
            )
            item = QueueItem(
                track=track,
                status="Completed",
                source_type=r.get("source_type", "Musilon"),
                quality_badge=r.get("quality_badge", "FLAC 16"),
                progress_percent=100.0,
                output_path=r.get("file_path", "")
            )
            self.model.add_item(item)
            row = self.model.rowCount() - 1
            if row >= 0:
                self.table.setRowHeight(row, 76)

        self.table.viewport().update()

    def reload_playlists(self, search_query: str = ""):
        """Populates the Playlists page with cards."""
        while self.playlists_layout.count() > 1:
            child = self.playlists_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        playlists = self.archive.get_playlists(search_query)
        if not playlists:
            empty_card = CardWidget(self.playlists_container)
            empty_card.setStyleSheet("background-color: #1e1e1e; border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 8px;")
            empty_layout = QVBoxLayout(empty_card)
            empty_layout.setContentsMargins(24, 36, 24, 36)
            empty_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty_layout.setSpacing(10)

            icon = IconWidget(FluentIcon.FOLDER, empty_card)
            icon.setFixedSize(48, 48)
            empty_layout.addWidget(icon, 0, Qt.AlignmentFlag.AlignCenter)

            title = StrongBodyLabel("No Playlists Found", empty_card)
            title.setStyleSheet("font-size: 16px; font-weight: 600; color: #FFFFFF;")
            empty_layout.addWidget(title, 0, Qt.AlignmentFlag.AlignCenter)

            desc = CaptionLabel(
                "No playlists match your current filter or no playlists have been downloaded yet.",
                empty_card
            )
            desc.setTextColor(TEXT_MUTED, TEXT_MUTED)
            desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty_layout.addWidget(desc, 0, Qt.AlignmentFlag.AlignCenter)

            self.playlists_layout.insertWidget(0, empty_card)
            return

        for pl in playlists:
            name = pl["name"]
            track_count = pl["track_count"]
            sz_str = pl["size_str"]
            folder = pl["folder_path"]
            cover_path = pl.get("cover_path", "")
            subtitle = f"{track_count} song(s) • {sz_str}  |  {folder}"

            card = CollectionCard(
                title=name,
                subtitle=subtitle,
                folder_path=folder,
                icon=FluentIcon.FOLDER,
                cover_path=cover_path,
                on_browse=lambda n=name, cp=cover_path, fp=folder, sub=subtitle: self._browse_collection(n, "playlist", cp, fp, sub),
                parent=self.playlists_container
            )
            self.playlists_layout.insertWidget(self.playlists_layout.count() - 1, card)

    def reload_albums(self, search_query: str = ""):
        """Populates the Albums page with cards."""
        while self.albums_layout.count() > 1:
            child = self.albums_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        albums = self.archive.get_albums(search_query)
        if not albums:
            empty_card = CardWidget(self.albums_container)
            empty_card.setStyleSheet("background-color: #1e1e1e; border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 8px;")
            empty_layout = QVBoxLayout(empty_card)
            empty_layout.setContentsMargins(24, 36, 24, 36)
            empty_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty_layout.setSpacing(10)

            icon = IconWidget(FluentIcon.ALBUM, empty_card)
            icon.setFixedSize(48, 48)
            empty_layout.addWidget(icon, 0, Qt.AlignmentFlag.AlignCenter)

            title = StrongBodyLabel("No Downloaded Albums", empty_card)
            title.setStyleSheet("font-size: 16px; font-weight: 600; color: #FFFFFF;")
            empty_layout.addWidget(title, 0, Qt.AlignmentFlag.AlignCenter)

            desc = CaptionLabel(
                "You have only downloaded playlists and individual singles so far.\n"
                "When you download a Spotify album URL, its complete discography will appear here.",
                empty_card
            )
            desc.setTextColor(TEXT_MUTED, TEXT_MUTED)
            desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty_layout.addWidget(desc, 0, Qt.AlignmentFlag.AlignCenter)

            self.albums_layout.insertWidget(0, empty_card)
            return

        for alb in albums:
            name = alb["name"]
            artist = alb["artist"]
            track_count = alb["track_count"]
            sz_str = alb["size_str"]
            folder = alb["folder_path"]
            cover_path = alb.get("cover_path", "")
            subtitle = f"by {artist} • {track_count} song(s) • {sz_str}"

            card = CollectionCard(
                title=name,
                subtitle=subtitle,
                folder_path=folder,
                icon=FluentIcon.MUSIC,
                cover_path=cover_path,
                on_browse=lambda n=name, cp=cover_path, fp=folder, sub=subtitle: self._browse_collection(n, "album", cp, fp, sub),
                parent=self.albums_container
            )
            self.albums_layout.insertWidget(self.albums_layout.count() - 1, card)

    def _browse_collection(self, name: str, coll_type: str = "playlist", cover_path: str = "", folder_path: str = "", subtitle: str = ""):
        """Opens collection and displays all of its tracks inside the GUI with a breadcrumb header."""
        self._current_collection_name = name
        self._current_collection_type = coll_type
        self._current_collection_folder = folder_path

        # Update Back button label
        if coll_type == "album":
            self.back_btn.setText("Back to Albums")
        else:
            self.back_btn.setText("Back to Playlists")

        self.banner_title.setText(name)
        self.banner_desc.setText(subtitle if subtitle else ("Playlist" if coll_type == "playlist" else "Album"))

        # Load banner thumbnail if available
        loaded_thumb = False
        if cover_path and os.path.isfile(cover_path):
            try:
                img = QImage(cover_path)
                if not img.isNull():
                    scaled = img.scaled(44, 44, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
                    rounded = QPixmap(44, 44)
                    rounded.fill(Qt.GlobalColor.transparent)
                    p = QPainter(rounded)
                    p.setRenderHint(QPainter.RenderHint.Antialiasing)
                    path = QPainterPath()
                    path.addRoundedRect(0, 0, 44, 44, 6, 6)
                    p.setClipPath(path)
                    p.drawPixmap(0, 0, QPixmap.fromImage(scaled))
                    p.end()
                    self.banner_thumb.setPixmap(rounded)
                    loaded_thumb = True
            except Exception:
                pass

        if not loaded_thumb:
            self.banner_thumb.setPixmap(QPixmap())
            self.banner_thumb.setText("📁" if coll_type == "playlist" else "💿")

        self.coll_banner.setVisible(True)

        # Clear search input temporarily when opening a collection
        self.search_input.blockSignals(True)
        self.search_input.clear()
        self.search_input.blockSignals(False)

        # Load tracks belonging to this collection
        self._load_collection_tracks(name, coll_type)

        # Switch to table page
        self.stacked.setCurrentIndex(0)

    def _load_collection_tracks(self, name: str, coll_type: str = "playlist", filter_query: str = ""):
        """Loads all tracks from SQLite archive belonging specifically to this collection."""
        rows = self.archive.get_collection_tracks(name, coll_type)
        self.model.clear()

        q = filter_query.strip().lower()
        for r in rows:
            if q:
                t_title = r.get("title", "").lower()
                t_artist = r.get("artist", "").lower()
                t_album = r.get("album", "").lower()
                if q not in t_title and q not in t_artist and q not in t_album:
                    continue

            track = TrackMetadata(
                id=r["spotify_id"],
                title=r["title"],
                artists=[a.strip() for a in r["artist"].split(",")],
                album=r.get("album", ""),
                release_date="",
                duration_ms=r.get("duration_ms", 0),
                collection_name=r.get("collection_name", ""),
                collection_type=r.get("collection_type", "track")
            )
            item = QueueItem(
                track=track,
                status="Completed",
                source_type=r.get("source_type", "Musilon"),
                quality_badge=r.get("quality_badge", "FLAC 16"),
                progress_percent=100.0,
                output_path=r.get("file_path", "")
            )
            self.model.add_item(item)
            row = self.model.rowCount() - 1
            if row >= 0:
                self.table.setRowHeight(row, 76)

        self.table.viewport().update()

    def _on_back_to_collections(self):
        """Returns from collection tracks back to the Playlists or Albums grid."""
        self.coll_banner.setVisible(False)
        target_tab = "albums" if self._current_collection_type == "album" else "playlists"
        target_idx = 2 if self._current_collection_type == "album" else 1
        self._current_collection_name = None
        self.segmented.setCurrentItem(target_tab)
        self._switch_tab(target_idx)

    def _open_current_collection_folder(self):
        """Opens current collection folder in Windows Explorer."""
        folder = getattr(self, "_current_collection_folder", "")
        if folder and os.path.isdir(folder):
            os.startfile(folder)
        else:
            self._open_download_folder()

    def _on_search_changed(self, text: str):
        curr = self.stacked.currentIndex()
        if curr == 0:
            if self._current_collection_name:
                self._load_collection_tracks(self._current_collection_name, self._current_collection_type, text.strip())
            else:
                self.reload_from_archive(text.strip())
        elif curr == 1:
            self.reload_playlists(text.strip())
        elif curr == 2:
            self.reload_albums(text.strip())

    def _on_track_completed(self, track_id: str, path: str):
        # Refresh views when a track finishes
        self.reload_all()

    def add_completed_item(self, item: QueueItem):
        """Immediately updates views upon track completion."""
        self.reload_all()

    def _on_rescan_clicked(self):
        out_dir = config.get("download.output_dir", os.path.expanduser("~/Music/Spotify Downloads"))
        if os.path.isdir(out_dir):
            indexed = self.archive.scan_and_index_directory(out_dir)
            self.reload_all()
            InfoBar.success("Library Synced", f"Scanned folder and synchronized {indexed} file(s).", duration=3000, parent=self)
        else:
            InfoBar.warning("Folder Not Found", f"Directory does not exist: {out_dir}", parent=self)

    def _open_download_folder(self):
        out_dir = config.get("download.output_dir", os.path.expanduser("~/Music/Spotify Downloads"))
        if os.path.exists(out_dir):
            os.startfile(out_dir)
        else:
            InfoBar.warning("Folder Not Found", f"Directory does not exist: {out_dir}", parent=self)

    def _on_double_click(self, index):
        item = self.model.get_item(index.row())
        if item and item.output_path and os.path.isfile(item.output_path):
            os.startfile(item.output_path)
        else:
            InfoBar.warning("File Missing", "The audio file could not be found on disk.", parent=self)

    def _show_context_menu(self, pos):
        index = self.table.indexAt(pos)
        if not index.isValid():
            return
        item = self.model.get_item(index.row())
        if not item:
            return

        menu = QMenu(self)
        play_act = menu.addAction("Play Track")
        show_act = menu.addAction("Show in Explorer")
        copy_act = menu.addAction("Copy Track Title")
        menu.addSeparator()
        delete_act = menu.addAction("Remove from Archive")

        action = menu.exec(self.table.viewport().mapToGlobal(pos))
        if action == play_act:
            if item.output_path and os.path.isfile(item.output_path):
                os.startfile(item.output_path)
            else:
                InfoBar.warning("File Missing", "The audio file was not found on disk.", parent=self)
        elif action == show_act:
            if item.output_path and os.path.isfile(item.output_path):
                subprocess.Popen(f'explorer /select,"{os.path.normpath(item.output_path)}"')
            else:
                InfoBar.warning("File Missing", "The audio file was not found on disk.", parent=self)
        elif action == copy_act:
            QApplication.clipboard().setText(f"{item.track.title} - {item.track.artist_str}")
        elif action == delete_act:
            self.archive.delete_track(item.track.id)
            self.reload_all()
            InfoBar.info("Removed", f"Removed '{item.track.title}' from archive.", duration=2500, parent=self)
