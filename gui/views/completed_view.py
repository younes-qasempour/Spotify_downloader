import os
import subprocess
import threading
from typing import Optional, List, Dict, Any
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QHeaderView, QMenu, QApplication,
    QStackedWidget, QFrame, QLabel
)
from PyQt6.QtGui import QImage, QPixmap, QPainter, QPainterPath
from qfluentwidgets import (
    TableView, SubtitleLabel, PushButton, PrimaryPushButton, ToolButton,
    FluentIcon, InfoBar, InfoBarPosition, LineEdit, CaptionLabel, StrongBodyLabel, BodyLabel,
    SegmentedWidget, CardWidget, SmoothScrollArea, IconWidget, ComboBox, MessageBoxBase
)

from gui.queue_model import TrackQueueModel
from gui.queue_delegate import TrackCardDelegate
from gui.bridge import EngineSignalBridge, safe_invoke, safe_emit
from gui.styles import TEXT_MUTED, BG_CARD, SPOTIFY_EMERALD
from core.archive import ArchiveManager
from core.spotify_client import TrackMetadata
from core.queue_manager import QueueItem
from core.config import config
from gui.dialogs.export_dialog import ExportDialog
from gui.dialogs.export_m3u_dialog import ExportM3UDialog


class RenameCollectionDialog(MessageBoxBase):
    """Fluent Dialog allowing users to rename a downloaded playlist/collection."""
    def __init__(self, current_name: str, parent=None):
        super().__init__(parent)
        self.titleLabel = SubtitleLabel("Rename Playlist", self)
        self.viewLayout.addWidget(self.titleLabel)

        desc = CaptionLabel("Enter a new name for this playlist. Archive records and storage folders will be updated.", self)
        desc.setTextColor(TEXT_MUTED, TEXT_MUTED)
        self.viewLayout.addWidget(desc)

        self.name_input = LineEdit(self)
        self.name_input.setText(current_name)
        self.name_input.setClearButtonEnabled(True)
        self.name_input.setPlaceholderText("Enter new playlist name...")
        self.viewLayout.addWidget(self.name_input)

        self.yesButton.setText("Rename")
        self.cancelButton.setText("Cancel")

        self.name_input.textChanged.connect(self._validate)
        self._validate()

    def _validate(self):
        self.yesButton.setEnabled(bool(self.name_input.text().strip()))


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
        on_rename=None,
        on_export=None,
        on_export_m3u=None,
        parent=None
    ):
        super().__init__(parent)
        self.title = title
        self.folder_path = folder_path
        self.cover_path = cover_path
        self.on_browse = on_browse
        self.on_rename = on_rename
        self.on_export = on_export
        self.on_export_m3u = on_export_m3u
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_card_menu)

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
            self.browse_btn.clicked.connect(lambda checked=False: self.on_browse() if self.on_browse else None)
            btn_layout.addWidget(self.browse_btn)

        if on_rename:
            self.rename_btn = ToolButton(FluentIcon.EDIT, self)
            self.rename_btn.setToolTip("Rename Playlist")
            self.rename_btn.clicked.connect(lambda checked=False: self.on_rename() if self.on_rename else None)
            btn_layout.addWidget(self.rename_btn)

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

    def _show_card_menu(self, pos):
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
        act_browse = menu.addAction("Browse Tracks")
        act_rename = None
        if self.on_rename:
            act_rename = menu.addAction("Rename Playlist...")
        act_export = None
        if self.on_export:
            act_export = menu.addAction("Export Playlist to Device / Folder...")
        act_export_m3u = None
        if self.on_export_m3u:
            act_export_m3u = menu.addAction("Export Playlist File (.m3u8)...")
        menu.addSeparator()
        act_folder = menu.addAction("Open Folder in Explorer")

        action = menu.exec(self.mapToGlobal(pos))
        if not action:
            return

        if action == act_browse and self.on_browse:
            self.on_browse()
        elif act_rename and action == act_rename and self.on_rename:
            self.on_rename()
        elif act_export and action == act_export and self.on_export:
            self.on_export()
        elif act_export_m3u and action == act_export_m3u and self.on_export_m3u:
            self.on_export_m3u()
        elif action == act_folder:
            self._open_folder()

    def _open_folder(self, *args):
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

    def __init__(self, bridge: EngineSignalBridge, archive_manager: Optional[ArchiveManager] = None, queue_manager: Optional[Any] = None, parent=None):
        super().__init__(parent)
        self.bridge = bridge
        self.archive = archive_manager or ArchiveManager()
        self.qm = queue_manager

        self.model = TrackQueueModel(self)
        self.delegate = TrackCardDelegate(self)

        self._current_collection_name: Optional[str] = None
        self._current_collection_type: str = "playlist"
        self._current_collection_folder: str = ""

        self._tracks_dirty = False
        self._playlists_dirty = False
        self._albums_dirty = False

        self._init_ui()
        self.reload_all()

        # Connect Signal Bridge for live completed events
        self.bridge.sig_completed.connect(self._on_track_completed)

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(18, 12, 18, 12)
        main_layout.setSpacing(8)

        # 1. Unified Navigation, Filter & Action Toolbar Row
        nav_row = QHBoxLayout()
        nav_row.setSpacing(10)

        self.segmented = SegmentedWidget(self)
        self.segmented.addItem("tracks", "🎵 All Songs", onClick=lambda: self._switch_tab(0))
        self.segmented.addItem("playlists", "📁 Playlists", onClick=lambda: self._switch_tab(1))
        self.segmented.addItem("albums", "💿 Albums", onClick=lambda: self._switch_tab(2))
        nav_row.addWidget(self.segmented)

        self.stats_label = CaptionLabel("Loading library...", self)
        self.stats_label.setTextColor(TEXT_MUTED, TEXT_MUTED)
        self.stats_label.setStyleSheet("font-size: 11px;")
        nav_row.addWidget(self.stats_label)

        nav_row.addStretch(1)

        self.search_input = LineEdit(self)
        self.search_input.setFixedHeight(30)
        self.search_input.setPlaceholderText("Search songs, artists, albums, or playlists...")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.setFixedWidth(220)
        self.search_input.textChanged.connect(self._on_search_changed)
        nav_row.addWidget(self.search_input)

        self.sort_combo = ComboBox(self)
        self.sort_combo.setFixedHeight(30)
        self.sort_combo.addItems([
            "Sort: Title (A-Z)",
            "Sort: Track Number",
            "Sort: Artist (A-Z)",
            "Sort: Duration (Shortest)",
            "Sort: Duration (Longest)",
            "Sort: Recently Added",
            "Sort: Genre (A-Z)"
        ])
        self.sort_combo.setCurrentIndex(0)
        self.sort_combo.setFixedWidth(160)
        self.sort_combo.currentIndexChanged.connect(self._on_sort_changed)
        nav_row.addWidget(self.sort_combo)

        self.genre_combo = ComboBox(self)
        self.genre_combo.setFixedHeight(30)
        self.genre_combo.setFixedWidth(125)
        self.genre_combo.addItems(["All Genres"])
        self.genre_combo.currentIndexChanged.connect(self._on_genre_changed)
        nav_row.addWidget(self.genre_combo)

        self.open_folder_btn = PushButton(FluentIcon.FOLDER, "Downloads", self)
        self.open_folder_btn.setFixedHeight(30)
        self.open_folder_btn.setToolTip("Open local download directory in Windows Explorer")
        self.open_folder_btn.clicked.connect(self._open_download_folder)
        nav_row.addWidget(self.open_folder_btn)

        self.rescan_btn = ToolButton(FluentIcon.SYNC, self)
        self.rescan_btn.setFixedHeight(30)
        self.rescan_btn.setToolTip("Rescan & Sync Downloads from Disk")
        self.rescan_btn.clicked.connect(self._on_rescan_clicked)
        nav_row.addWidget(self.rescan_btn)

        main_layout.addLayout(nav_row)

        # 2. Stacked Widget (Pages)
        self.stacked = QStackedWidget(self)

        # --- Page 0: All Songs Table ---
        self.table_page = QWidget(self)
        table_layout = QVBoxLayout(self.table_page)
        table_layout.setContentsMargins(0, 0, 0, 0)
        table_layout.setSpacing(6)

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
        banner_layout.setContentsMargins(10, 6, 12, 6)
        banner_layout.setSpacing(10)

        self.back_btn = PushButton(FluentIcon.LEFT_ARROW, "Back to Collections", self.coll_banner)
        self.back_btn.setFixedHeight(28)
        self.back_btn.clicked.connect(self._on_back_to_collections)
        banner_layout.addWidget(self.back_btn)

        self.banner_thumb = QLabel(self.coll_banner)
        self.banner_thumb.setFixedSize(36, 36)
        self.banner_thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.banner_thumb.setStyleSheet("background-color: #2a2a2a; border-radius: 6px; border: 1px solid rgba(255, 255, 255, 0.08);")
        banner_layout.addWidget(self.banner_thumb)

        banner_text_box = QVBoxLayout()
        banner_text_box.setSpacing(1)
        self.banner_title = StrongBodyLabel("", self.coll_banner)
        self.banner_title.setStyleSheet("font-size: 13px; font-weight: 600; color: #FFFFFF;")
        self.banner_desc = CaptionLabel("", self.coll_banner)
        self.banner_desc.setTextColor(TEXT_MUTED, TEXT_MUTED)
        self.banner_desc.setStyleSheet("font-size: 11px;")
        banner_text_box.addWidget(self.banner_title)
        banner_text_box.addWidget(self.banner_desc)
        banner_layout.addLayout(banner_text_box, 1)

        self.banner_open_folder_btn = ToolButton(FluentIcon.FOLDER, self.coll_banner)
        self.banner_open_folder_btn.setToolTip("Open Folder in Explorer")
        self.banner_open_folder_btn.clicked.connect(self._open_current_collection_folder)

        self.banner_export_btn = ToolButton(FluentIcon.FOLDER_ADD, self.coll_banner)
        self.banner_export_btn.setToolTip("Export Songs to Device / Folder...")
        self.banner_export_btn.clicked.connect(self._export_current_collection)

        self.banner_export_m3u_btn = ToolButton(FluentIcon.SAVE, self.coll_banner)
        self.banner_export_m3u_btn.setToolTip("Export Playlist File (.m3u8)...")
        self.banner_export_m3u_btn.clicked.connect(self._export_current_collection_m3u)

        self.banner_rename_btn = ToolButton(FluentIcon.EDIT, self.coll_banner)
        self.banner_rename_btn.setToolTip("Rename Playlist")
        self.banner_rename_btn.clicked.connect(self._rename_current_collection)

        banner_layout.addWidget(self.banner_open_folder_btn)
        banner_layout.addWidget(self.banner_export_btn)
        banner_layout.addWidget(self.banner_export_m3u_btn)
        banner_layout.addWidget(self.banner_rename_btn)

        table_layout.addWidget(self.coll_banner)

        self.table = TableView(self.table_page)
        self.table.setModel(self.model)
        self.table.setItemDelegate(self.delegate)
        self.table.setShowGrid(False)
        self.table.horizontalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(56)
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
            elif getattr(self, "_tracks_dirty", False) or search_query:
                self.reload_from_archive(search_query)
                self._tracks_dirty = False
        elif index == 1:
            if getattr(self, "_playlists_dirty", False) or search_query:
                self.reload_playlists(search_query)
                self._playlists_dirty = False
        elif index == 2:
            if getattr(self, "_albums_dirty", False) or search_query:
                self.reload_albums(search_query)
                self._albums_dirty = False

    def reload_all(self):
        """Refreshes high-level library counters and active view tab."""
        stats = self.archive.get_library_stats()
        t_count = stats["total_tracks"]
        p_count = stats["total_playlists"]
        a_count = stats["total_albums"]
        size_str = stats["size_str"]

        self.segmented.setItemText("tracks", f"🎵 All Songs ({t_count})")
        self.segmented.setItemText("playlists", f"📁 Playlists ({p_count})")
        self.segmented.setItemText("albums", f"💿 Albums ({a_count})")

        self.stats_label.setText(f"{t_count} song(s) • {p_count} collection(s) • {size_str} offline library")

        # Update available genre options dynamically
        self._update_genre_combo()

        # Refresh only active tab immediately; mark others dirty for lazy load
        search_query = self.search_input.text().strip()
        curr_idx = self.stacked.currentIndex()
        if curr_idx == 0:
            if self._current_collection_name:
                self._load_collection_tracks(self._current_collection_name, self._current_collection_type, search_query)
            else:
                self.reload_from_archive(search_query)
            self._tracks_dirty = False
            self._playlists_dirty = True
            self._albums_dirty = True
        elif curr_idx == 1:
            self.reload_playlists(search_query)
            self._tracks_dirty = True
            self._playlists_dirty = False
            self._albums_dirty = True
        elif curr_idx == 2:
            self.reload_albums(search_query)
            self._tracks_dirty = True
            self._playlists_dirty = True
            self._albums_dirty = False

    def showEvent(self, event):
        super().showEvent(event)
        search_query = self.search_input.text().strip()
        curr_idx = self.stacked.currentIndex()
        if curr_idx == 0 and getattr(self, "_tracks_dirty", False):
            if self._current_collection_name:
                self._load_collection_tracks(self._current_collection_name, self._current_collection_type, search_query)
            else:
                self.reload_from_archive(search_query)
            self._tracks_dirty = False
        elif curr_idx == 1 and getattr(self, "_playlists_dirty", False):
            self.reload_playlists(search_query)
            self._playlists_dirty = False
        elif curr_idx == 2 and getattr(self, "_albums_dirty", False):
            self.reload_albums(search_query)
            self._albums_dirty = False

    def _update_genre_combo(self):
        """Populates the genre dropdown with all genres present in the local archive."""
        if not hasattr(self, "genre_combo"):
            return
        curr_text = self.genre_combo.currentText() or "All Genres"
        all_genres = ["All Genres"] + self.archive.get_all_genres()
        self.genre_combo.blockSignals(True)
        self.genre_combo.clear()
        self.genre_combo.addItems(all_genres)
        idx = self.genre_combo.findText(curr_text)
        self.genre_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.genre_combo.blockSignals(False)

    def _on_genre_changed(self, index: int):
        search_query = self.search_input.text().strip()
        curr_page = self.stacked.currentIndex()
        if self._current_collection_name and curr_page == 0:
            self._load_collection_tracks(self._current_collection_name, self._current_collection_type, search_query)
        elif curr_page == 0:
            self.reload_from_archive(search_query)
        elif curr_page == 1:
            self.reload_playlists(search_query)
        elif curr_page == 2:
            self.reload_albums(search_query)

    def _sort_rows(self, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        idx = self.sort_combo.currentIndex() if hasattr(self, "sort_combo") else 0
        if idx == 0:  # Title (A-Z)
            return sorted(rows, key=lambda r: (r.get("title") or "").strip().lower())
        elif idx == 1:  # Track Number
            return sorted(rows, key=lambda r: (
                r.get("disc_number", 1) or 1,
                r.get("track_number") if (r.get("track_number") is not None and r.get("track_number") > 0) else 9999,
                (r.get("title") or "").strip().lower()
            ))
        elif idx == 2:  # Artist (A-Z)
            return sorted(rows, key=lambda r: (r.get("artist") or "").strip().lower())
        elif idx == 3:  # Duration (Shortest)
            return sorted(rows, key=lambda r: r.get("duration_ms") or 0)
        elif idx == 4:  # Duration (Longest)
            return sorted(rows, key=lambda r: r.get("duration_ms") or 0, reverse=True)
        elif idx == 5:  # Recently Added
            return sorted(rows, key=lambda r: r.get("downloaded_at") or "", reverse=True)
        elif idx == 6:  # Genre (A-Z)
            return sorted(rows, key=lambda r: (
                0 if (r.get("genre") or "").strip() else 1,
                (r.get("genre") or "").strip().lower(),
                (r.get("artist") or "").strip().lower(),
                (r.get("title") or "").strip().lower()
            ))
        return rows

    def _on_sort_changed(self, index: int):
        search_query = self.search_input.text().strip()
        curr_page = self.stacked.currentIndex()
        if self._current_collection_name and curr_page == 0:
            self._load_collection_tracks(self._current_collection_name, self._current_collection_type, search_query)
        elif curr_page == 0:
            self.reload_from_archive(search_query)
        elif curr_page == 1:
            self.reload_playlists(search_query)
        elif curr_page == 2:
            self.reload_albums(search_query)

    def reload_from_archive(self, search_query: str = ""):
        """Loads or filters tracks from SQLite archive into the virtualized TableView."""
        genre_filter = self.genre_combo.currentText() if hasattr(self, "genre_combo") else ""
        if genre_filter == "All Genres":
            genre_filter = ""
        rows = self.archive.get_all_tracks(search_query, genre_filter=genre_filter)
        rows = self._sort_rows(rows)
        items = []

        for r in rows:
            genre_raw = r.get("genre", "") or ""
            track_genres = [g.strip() for g in genre_raw.split(";") if g.strip()]
            track = TrackMetadata(
                id=r["spotify_id"],
                title=r["title"],
                artists=[a.strip() for a in r["artist"].split(",")],
                album=r.get("album", ""),
                release_date="",
                duration_ms=r.get("duration_ms", 0),
                track_number=r.get("track_number", 1) or 1,
                disc_number=r.get("disc_number", 1) or 1,
                collection_name=r.get("collection_name", ""),
                collection_type=r.get("collection_type", "track"),
                genres=track_genres
            )
            q_badge = r.get("quality_badge") or ""
            f_path = r.get("file_path", "")
            s_type = r.get("source_type") or ""
            if not q_badge and f_path:
                q_inf, s_inf = self.archive.infer_badge_from_file(f_path)
                q_badge = q_inf or "FLAC 16"
                s_type = s_type or s_inf or "Musilon"
            elif not q_badge:
                q_badge = "FLAC 16"
                s_type = s_type or "Musilon"

            item = QueueItem(
                track=track,
                status="Completed",
                source_type=s_type,
                quality_badge=q_badge,
                progress_percent=100.0,
                output_path=f_path
            )
            items.append(item)

        self.model.set_items(items)
        self.table.viewport().update()

    def reload_playlists(self, search_query: str = ""):
        """Populates the Playlists page with cards."""
        while self.playlists_layout.count() > 1:
            child = self.playlists_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        genre_filter = self.genre_combo.currentText() if hasattr(self, "genre_combo") else ""
        if genre_filter == "All Genres":
            genre_filter = ""
        playlists = self.archive.get_playlists(search_query, genre_filter=genre_filter)

        # Sort playlists
        sort_idx = self.sort_combo.currentIndex() if hasattr(self, "sort_combo") else 0
        if sort_idx == 6:  # Genre (A-Z)
            playlists = sorted(playlists, key=lambda p: (
                0 if p.get("genre") else 1,
                (p.get("genre") or "").strip().lower(),
                p["name"].strip().lower()
            ))
        elif sort_idx == 0:  # Title (A-Z)
            playlists = sorted(playlists, key=lambda p: p["name"].strip().lower())
        elif sort_idx == 1:  # Track count
            playlists = sorted(playlists, key=lambda p: p.get("track_count") or 0, reverse=True)
        elif sort_idx in (3, 4):  # Size
            playlists = sorted(playlists, key=lambda p: p.get("total_size_bytes") or 0, reverse=(sort_idx == 4))
        elif sort_idx == 5:  # Recently Added
            playlists = sorted(playlists, key=lambda p: p.get("latest_download") or "", reverse=True)

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
            genre_str = f" • {pl['genre']}" if pl.get("genre") else ""
            subtitle = f"{track_count} song(s){genre_str} • {sz_str}  |  {folder}"

            card = CollectionCard(
                title=name,
                subtitle=subtitle,
                folder_path=folder,
                icon=FluentIcon.FOLDER,
                cover_path=cover_path,
                on_browse=lambda *args, n=name, cp=cover_path, fp=folder, sub=subtitle: self._browse_collection(n, "playlist", cp, fp, sub),
                on_rename=lambda n=name: self._rename_playlist_collection(n),
                on_export=lambda n=name: self._export_collection(n, "playlist"),
                on_export_m3u=lambda n=name: self._export_collection_m3u(n, "playlist"),
                parent=self.playlists_container
            )
            self.playlists_layout.insertWidget(self.playlists_layout.count() - 1, card)

    def reload_albums(self, search_query: str = ""):
        """Populates the Albums page with cards."""
        while self.albums_layout.count() > 1:
            child = self.albums_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        genre_filter = self.genre_combo.currentText() if hasattr(self, "genre_combo") else ""
        if genre_filter == "All Genres":
            genre_filter = ""
        albums = self.archive.get_albums(search_query, genre_filter=genre_filter)

        sort_idx = self.sort_combo.currentIndex() if hasattr(self, "sort_combo") else 0
        if sort_idx == 6:  # Genre (A-Z)
            albums = sorted(albums, key=lambda a: (
                0 if a.get("genre") else 1,
                (a.get("genre") or "").strip().lower(),
                (a.get("artist") or "").strip().lower(),
                a["name"].strip().lower()
            ))
        elif sort_idx == 0:  # Title (A-Z)
            albums = sorted(albums, key=lambda a: a["name"].strip().lower())
        elif sort_idx == 2:  # Artist (A-Z)
            albums = sorted(albums, key=lambda a: (a.get("artist") or "").strip().lower())
        elif sort_idx == 1:  # Track count
            albums = sorted(albums, key=lambda a: a.get("track_count") or 0, reverse=True)
        elif sort_idx in (3, 4):  # Size
            albums = sorted(albums, key=lambda a: a.get("total_size_bytes") or 0, reverse=(sort_idx == 4))
        elif sort_idx == 5:  # Recently Added
            albums = sorted(albums, key=lambda a: a.get("latest_download") or "", reverse=True)

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
            genre_str = f" • {alb['genre']}" if alb.get("genre") else ""
            subtitle = f"by {artist}{genre_str} • {track_count} song(s) • {sz_str}"

            card = CollectionCard(
                title=name,
                subtitle=subtitle,
                folder_path=folder,
                icon=FluentIcon.MUSIC,
                cover_path=cover_path,
                on_browse=lambda *args, n=name, cp=cover_path, fp=folder, sub=subtitle: self._browse_collection(n, "album", cp, fp, sub),
                on_export=lambda n=name: self._export_collection(n, "album"),
                on_export_m3u=lambda n=name: self._export_collection_m3u(n, "album"),
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

        self.banner_title.setText(str(name))
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

        # Update sort selection: preserve user's custom sort if already set (e.g. Genre or Artist)
        if hasattr(self, "sort_combo"):
            curr_sort = self.sort_combo.currentIndex()
            if curr_sort not in (2, 3, 4, 5, 6):
                self.sort_combo.blockSignals(True)
                if coll_type == "album":
                    self.sort_combo.setCurrentIndex(1)  # Track Number
                else:
                    self.sort_combo.setCurrentIndex(0)  # Title (A-Z)
                self.sort_combo.blockSignals(False)

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
        genre_filter = self.genre_combo.currentText() if hasattr(self, "genre_combo") else ""
        if genre_filter == "All Genres":
            genre_filter = ""
        rows = self.archive.get_collection_tracks(name, coll_type, genre_filter=genre_filter)
        rows = self._sort_rows(rows)
        items = []

        q = filter_query.strip().lower()
        for r in rows:
            if q:
                t_title = r.get("title", "").lower()
                t_artist = r.get("artist", "").lower()
                t_album = r.get("album", "").lower()
                if q not in t_title and q not in t_artist and q not in t_album:
                    continue

            genre_raw = r.get("genre", "") or ""
            track_genres = [g.strip() for g in genre_raw.split(";") if g.strip()]
            track = TrackMetadata(
                id=r["spotify_id"],
                title=r["title"],
                artists=[a.strip() for a in r["artist"].split(",")],
                album=r.get("album", ""),
                release_date="",
                duration_ms=r.get("duration_ms", 0),
                track_number=r.get("track_number", 1) or 1,
                disc_number=r.get("disc_number", 1) or 1,
                collection_name=r.get("collection_name", ""),
                collection_type=r.get("collection_type", coll_type),
                genres=track_genres
            )
            q_badge = r.get("quality_badge") or ""
            f_path = r.get("file_path", "")
            s_type = r.get("source_type") or ""
            if not q_badge and f_path:
                q_inf, s_inf = self.archive.infer_badge_from_file(f_path)
                q_badge = q_inf or "FLAC 16"
                s_type = s_type or s_inf or "Musilon"
            elif not q_badge:
                q_badge = "FLAC 16"
                s_type = s_type or "Musilon"

            item = QueueItem(
                track=track,
                status="Completed",
                source_type=s_type,
                quality_badge=q_badge,
                progress_percent=100.0,
                output_path=f_path
            )
            items.append(item)

        self.model.set_items(items)
        self.table.viewport().update()

    def _on_back_to_collections(self, *args):
        """Returns from collection tracks back to the Playlists or Albums grid."""
        self.coll_banner.setVisible(False)
        target_tab = "albums" if self._current_collection_type == "album" else "playlists"
        target_idx = 2 if self._current_collection_type == "album" else 1
        self._current_collection_name = None
        self.segmented.setCurrentItem(target_tab)
        self._switch_tab(target_idx)

    def _open_current_collection_folder(self, *args):
        """Opens current collection folder in Windows Explorer."""
        folder = getattr(self, "_current_collection_folder", "")
        if folder and os.path.isdir(folder):
            os.startfile(folder)
        else:
            self._open_download_folder()

    def _rename_current_collection(self):
        curr_name = getattr(self, "_current_collection_name", None)
        curr_type = getattr(self, "_current_collection_type", "playlist")
        if curr_name and curr_type == "playlist":
            self._rename_playlist_collection(curr_name)

    def _rename_playlist_collection(self, current_name: str):
        diag = RenameCollectionDialog(current_name, self.window() or self)
        if diag.exec():
            new_name = diag.name_input.text().strip()
            if new_name and new_name != current_name:
                ok = self.archive.rename_collection(current_name, new_name, collection_type="playlist")
                if ok:
                    InfoBar.success(
                        title="Playlist Renamed",
                        content=f"Successfully renamed to '{new_name}'.",
                        orient=Qt.Orientation.Horizontal,
                        position=InfoBarPosition.TOP,
                        duration=3500,
                        parent=self
                    )
                    self.reload_playlists()
                    if getattr(self, "_current_collection_name", None) == current_name:
                        self._current_collection_name = new_name
                        self.banner_title.setText(new_name)
                        self._load_collection_tracks(new_name, "playlist")

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
        self._tracks_dirty = True
        self._playlists_dirty = True
        self._albums_dirty = True

    def add_completed_item(self, item: QueueItem):
        """Incrementally updates active view or marks dirty upon track completion."""
        self._playlists_dirty = True
        self._albums_dirty = True
        if self.isVisible() and self.stacked.currentIndex() == 0 and not self.search_input.text().strip():
            self.model.add_item(item)
            c = self.model.rowCount()
            self.segmented.setItemText("tracks", f"🎵 All Songs ({c})")
        else:
            self._tracks_dirty = True

    def _on_rescan_clicked(self, *args):
        out_dir = config.get("download.output_dir", os.path.expanduser("~/Music/Spotify Downloads"))
        if not os.path.isdir(out_dir):
            InfoBar.warning("Folder Not Found", f"Directory does not exist: {out_dir}", parent=self)
            return

        InfoBar.info("Syncing Library", "Scanning audio folder in background...", duration=3000, parent=self)

        def worker():
            indexed = self.archive.scan_and_index_directory(out_dir)
            QTimer.singleShot(0, lambda: safe_invoke(self._on_rescan_done, indexed))

        threading.Thread(target=worker, daemon=True, name="ManualRescanWorker").start()

    def _on_rescan_done(self, indexed: int):
        self.reload_all()
        InfoBar.success("Library Synced", f"Scanned folder and synchronized {indexed} file(s).", duration=3000, parent=self)

    def _open_download_folder(self, *args):
        out_dir = config.get("download.output_dir", os.path.expanduser("~/Music/Spotify Downloads"))
        if os.path.exists(out_dir):
            os.startfile(out_dir)
        else:
            InfoBar.warning("Folder Not Found", f"Directory does not exist: {out_dir}", parent=self)

    def _on_double_click(self, index):
        item = self.model.get_item(index.row())
        if item and item.output_path and os.path.isfile(item.output_path):
            main_win = self.window()
            if hasattr(main_win, "play_audio_track"):
                items = getattr(self.model, "items", None) or [self.model.get_item(i) for i in range(self.model.rowCount())]
                valid_items = [it for it in items if it and it.output_path and os.path.isfile(it.output_path)]
                curr_idx = valid_items.index(item) if item in valid_items else -1
                main_win.play_audio_track(item.output_path, item.track, item.quality_badge, playlist=valid_items, index=curr_idx)
            else:
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

        play_act = menu.addAction("Play Track")
        show_act = menu.addAction("Show in Explorer")
        copy_act = menu.addAction("Copy Track Title")
        menu.addSeparator()

        redl_menu = menu.addMenu("Re-download Track")
        redl_menu.setStyleSheet(menu_style)
        act_redl_auto = redl_menu.addAction("Auto (Best Available)")
        act_redl_melo = redl_menu.addAction("Via Telegram Bot (MeloBot)")
        act_redl_musi = redl_menu.addAction("Via Musilon (320k MP3)")
        act_redl_yt = redl_menu.addAction("Via YouTube Music")

        act_del_file = menu.addAction("Delete File from Disk")
        menu.addSeparator()

        act_export_selected = None
        selected_rows = self.table.selectionModel().selectedRows()
        if len(selected_rows) > 0 or (item.output_path and os.path.isfile(item.output_path)):
            act_export_selected = menu.addAction("Export Selected Tracks to Folder / Device...")

        m3u_act = menu.addAction("Export Playlist (.m3u8)...")
        details_act = menu.addAction("View Metadata & Genres")
        boost_vol_act = menu.addAction("Boost & Balance Track Volume")
        rg_act = menu.addAction("Calculate ReplayGain 2.0")
        menu.addSeparator()
        delete_act = menu.addAction("Remove from Archive Only")

        action = menu.exec(self.table.viewport().mapToGlobal(pos))
        if not action:
            return

        if action == play_act:
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
                InfoBar.warning("File Missing", "The audio file was not found on disk.", parent=self)
        elif action == show_act:
            if item.output_path and os.path.isfile(item.output_path):
                flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
                subprocess.Popen(["explorer", f"/select,{os.path.normpath(item.output_path)}"], creationflags=flags)
            else:
                InfoBar.warning("File Missing", "The audio file was not found on disk.", parent=self)
        elif action == copy_act:
            QApplication.clipboard().setText(f"{item.track.title} - {item.track.artist_str}")
        elif act_redl_auto and action in (act_redl_auto, act_redl_melo, act_redl_musi, act_redl_yt):
            t = item.track
            if item.output_path and os.path.exists(item.output_path):
                try:
                    os.remove(item.output_path)
                except Exception:
                    pass
            self.archive.remove_downloaded_track(t.id)

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
            qm = self.qm or getattr(self.window(), "queue_manager", None)
            if qm:
                qm.enqueue([t])
                qm.start_all()
            self.reload_all()
            InfoBar.info("Re-downloading", f"Re-downloading '{t.title}' via {engine_label}...", duration=4000, parent=self)
        elif act_del_file and action == act_del_file:
            t = item.track
            if item.output_path and os.path.exists(item.output_path):
                try:
                    os.remove(item.output_path)
                except Exception:
                    pass
            self.archive.remove_downloaded_track(t.id)
            self.reload_all()
            InfoBar.success("File Deleted", f"Deleted '{t.title}' from disk and removed from library.", duration=3500, parent=self)
        elif act_export_selected and action == act_export_selected:
            self._on_export_selected_clicked(fallback_item=item)
        elif action == m3u_act:
            self._export_m3u_playlist()
        elif action == details_act:
            self._show_track_details_dialog(item)
        elif action == boost_vol_act:
            if item.output_path and os.path.isfile(item.output_path):
                self._boost_track_volume_single(item)
            else:
                InfoBar.warning("File Missing", "The audio file was not found on disk.", parent=self)
        elif action == rg_act:
            if item.output_path and os.path.isfile(item.output_path):
                self._apply_replaygain_single(item)
            else:
                InfoBar.warning("File Missing", "The audio file was not found on disk.", parent=self)
        elif action == delete_act:
            self.archive.delete_track(item.track.id)
            self.reload_all()
            InfoBar.info("Removed", f"Removed '{item.track.title}' from archive.", duration=2500, parent=self)

    def _boost_track_volume_single(self, item: QueueItem):
        """Boosts and balances loudness on a single track using EBU R128 + lookahead limiter."""
        fpath = item.output_path
        title = item.track.title
        InfoBar.info("Boosting & Balancing Volume", f"Normalizing volume for '{title}' (-9.0 LUFS)...", duration=3000, parent=self)

        def worker():
            from core.utils import normalize_audio_loudness
            try:
                target_lufs = float(config.get("download.target_lufs", -9.0) or -9.0)
                res = normalize_audio_loudness(fpath, target_lufs=target_lufs, force=True)
                if res:
                    orig_lufs, gain_db = res
                    QTimer.singleShot(
                        0,
                        lambda: safe_invoke(
                            InfoBar.success,
                            "Volume Boosted & Balanced",
                            f"'{title}': {orig_lufs:.1f} LUFS -> {target_lufs:.1f} LUFS (gain {gain_db:+.1f} dB)",
                            duration=4500,
                            parent=self
                        )
                    )
                else:
                    QTimer.singleShot(0, lambda: safe_invoke(InfoBar.warning, "Normalization Skipped", f"Could not normalize '{title}'.", duration=4000, parent=self))
            except Exception as e:
                QTimer.singleShot(0, lambda: safe_invoke(InfoBar.error, "Volume Error", str(e), duration=4000, parent=self))

        threading.Thread(target=worker, daemon=True, name=f"BoostVol_{item.track.id}").start()

    def _apply_replaygain_single(self, item: QueueItem):
        """Calculates and tags EBU R128 ReplayGain on a single track in background."""
        fpath = item.output_path
        title = item.track.title
        InfoBar.info("Analyzing Loudness", f"Calculating EBU R128 ReplayGain for '{title}'...", duration=3000, parent=self)

        def worker():
            from core.utils import calculate_replaygain
            from core.tagger import AudioTagger
            try:
                rg = calculate_replaygain(fpath)
                if rg:
                    ok = AudioTagger().tag_replaygain(fpath, rg[0], rg[1])
                    if ok:
                        QTimer.singleShot(0, lambda: safe_invoke(InfoBar.success, "ReplayGain Applied", f"Tagged '{title}' ({rg[0]}, peak {rg[1]})", duration=4000, parent=self))
                        return
                QTimer.singleShot(0, lambda: safe_invoke(InfoBar.warning, "Analysis Missed", f"Could not calculate loudness for '{title}'.", duration=4000, parent=self))
            except Exception as e:
                QTimer.singleShot(0, lambda: safe_invoke(InfoBar.error, "ReplayGain Error", str(e), duration=4000, parent=self))

        threading.Thread(target=worker, daemon=True, name=f"RG_{item.track.id}").start()

    def _export_m3u_playlist(self):
        """Exports tracks currently matching view filters or selection into an M3U8 playlist file."""
        selected_indexes = self.table.selectionModel().selectedRows()
        if len(selected_indexes) > 1:
            items = [self.model.get_item(idx.row()) for idx in selected_indexes]
        else:
            items = [self.model.get_item(i) for i in range(self.model.rowCount())]

        valid_items = [it for it in items if it and it.output_path and os.path.isfile(it.output_path)]
        if not valid_items:
            InfoBar.warning("No Tracks", "There are no playable tracks in the current view to export.", parent=self)
            return

        pl_name = self._current_collection_name or "Playlist"
        diag = ExportM3UDialog(
            playlist_name=pl_name,
            tracks=valid_items,
            archive=self.archive,
            parent=self.window() or self
        )
        diag.exec()

    def _export_current_collection_m3u(self):
        if not self._current_collection_name:
            return
        self._export_collection_m3u(self._current_collection_name, self._current_collection_type or "playlist")

    def _export_collection_m3u(self, name: str, coll_type: str = "playlist"):
        tracks = self.archive.get_collection_tracks(name, coll_type)
        valid_tracks = [t for t in tracks if t.get("file_path") and os.path.isfile(t.get("file_path"))]
        if not valid_tracks:
            InfoBar.warning(
                title="No Downloaded Songs",
                content=f"No downloaded songs found on disk for '{name}'.",
                orient=Qt.Orientation.Horizontal,
                position=InfoBarPosition.TOP,
                duration=4000,
                parent=self
            )
            return

        diag = ExportM3UDialog(
            playlist_name=name,
            tracks=valid_tracks,
            archive=self.archive,
            parent=self.window() or self
        )
        diag.exec()

    def _export_current_collection(self):
        if not self._current_collection_name:
            return
        self._export_collection(self._current_collection_name, self._current_collection_type or "playlist")

    def _export_collection(self, name: str, coll_type: str = "playlist"):
        tracks = self.archive.get_collection_tracks(name, coll_type)
        valid_tracks = [t for t in tracks if t.get("file_path") and os.path.isfile(t.get("file_path"))]
        if not valid_tracks:
            InfoBar.warning(
                title="No Downloaded Songs",
                content=f"No downloaded songs found on disk for '{name}'.",
                orient=Qt.Orientation.Horizontal,
                position=InfoBarPosition.TOP,
                duration=4000,
                parent=self
            )
            return

        diag = ExportDialog(name, valid_tracks, self.window() or self)
        diag.exec()

    def _on_export_selected_clicked(self, fallback_item: Optional[QueueItem] = None):
        pl_name = self._current_collection_name or "Exported Songs"
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

    def _show_track_details_dialog(self, item: QueueItem):
        """Displays full metadata and embedded genre tags for the track."""
        from qfluentwidgets import MessageBox
        genres_str = item.track.genre_str or "None"
        content = (
            f"Title: {item.track.title}\n"
            f"Artist: {item.track.artist_str}\n"
            f"Album: {item.track.album or 'N/A'}\n"
            f"Genre(s): {genres_str}\n"
            f"Quality: {item.quality_badge or 'Audio'}\n"
            f"Source: {item.source_type or 'Local Archive'}\n"
            f"Track #: {item.track.track_number}  |  Disc #: {getattr(item.track, 'disc_number', 1) or 1}\n"
            f"ISRC: {item.track.isrc or 'N/A'}\n\n"
            f"Location on disk:\n{item.output_path}"
        )
        diag = MessageBox(f"Track Details — {item.track.title}", content, self)
        diag.yesButton.setText("Close")
        diag.cancelButton.setVisible(False)
        diag.exec()
