import os
import subprocess
from typing import Optional
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QHeaderView, QMenu, QApplication
)
from qfluentwidgets import (
    TableView, SubtitleLabel, PushButton, ToolButton, FluentIcon, InfoBar, LineEdit, CaptionLabel
)

from gui.queue_model import TrackQueueModel
from gui.queue_delegate import TrackCardDelegate
from gui.bridge import EngineSignalBridge
from gui.styles import TEXT_MUTED
from core.archive import ArchiveManager
from core.spotify_client import TrackMetadata
from core.queue_manager import QueueItem


class CompletedView(QWidget):
    """
    Persistent Downloaded Music Library view.
    Features:
    - Backed by SQLite ArchiveManager (preserves all downloads across sessions)
    - Real-time search by song, artist, album, or playlist
    - Total library counter
    - Right-click context menu (Play, Open in Explorer, Remove)
    - Double-click to instantly play file
    """

    def __init__(self, bridge: EngineSignalBridge, archive_manager: Optional[ArchiveManager] = None, parent=None):
        super().__init__(parent)
        self.bridge = bridge
        self.archive = archive_manager or ArchiveManager()

        self.model = TrackQueueModel(self)
        self.delegate = TrackCardDelegate(self)

        self._init_ui()
        self.reload_from_archive()

        # Connect Signal Bridge for live completed events
        self.bridge.sig_completed.connect(self._on_track_completed)

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)

        # 1. Header Row
        header_layout = QHBoxLayout()
        header_layout.setSpacing(12)

        title_box = QVBoxLayout()
        title = SubtitleLabel("Downloaded Library", self)
        self.stats_label = CaptionLabel("Loading library...", self)
        self.stats_label.setTextColor(TEXT_MUTED, TEXT_MUTED)
        title_box.addWidget(title)
        title_box.addWidget(self.stats_label)

        header_layout.addLayout(title_box)
        header_layout.addStretch(1)

        self.open_folder_btn = PushButton(FluentIcon.FOLDER, "Open Music Folder", self)
        self.open_folder_btn.clicked.connect(self._open_download_folder)

        self.refresh_btn = ToolButton(FluentIcon.SYNC, self)
        self.refresh_btn.setToolTip("Refresh Library")
        self.refresh_btn.clicked.connect(lambda: self.reload_from_archive(self.search_input.text()))

        header_layout.addWidget(self.open_folder_btn)
        header_layout.addWidget(self.refresh_btn)
        layout.addLayout(header_layout)

        # 2. Search & Filter Bar
        search_layout = QHBoxLayout()
        self.search_input = LineEdit(self)
        self.search_input.setPlaceholderText("Search library by song title, artist, album, or playlist name...")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.textChanged.connect(self._on_search_changed)
        search_layout.addWidget(self.search_input)
        layout.addLayout(search_layout)

        # 3. Virtualized Table View
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
        self.table.setSelectionMode(TableView.SelectionMode.SingleSelection)
        self.table.setVerticalScrollMode(TableView.ScrollMode.ScrollPerPixel)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.table.setStyleSheet("QTableView { border: none; background-color: transparent; }")
        self.table.doubleClicked.connect(self._on_double_click)

        # Context menu
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)

        layout.addWidget(self.table, 1)

    def reload_from_archive(self, search_query: str = ""):
        """Loads or filters all tracks from SQLite archive."""
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

        count = len(rows)
        if search_query:
            self.stats_label.setText(f"Showing {count} match(es) for '{search_query}'")
        else:
            self.stats_label.setText(f"{count} track(s) in offline library")

        self.table.viewport().update()

    def _on_search_changed(self, text: str):
        self.reload_from_archive(text.strip())

    def _on_track_completed(self, track_id: str, path: str):
        # Refresh current view when a track finishes
        self.reload_from_archive(self.search_input.text())

    def add_completed_item(self, item: QueueItem):
        """Immediately adds a completed item to the view."""
        self.reload_from_archive(self.search_input.text())

    def _open_download_folder(self):
        from core.config import config
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
            self.reload_from_archive(self.search_input.text())
            InfoBar.info("Removed", f"Removed '{item.track.title}' from archive.", duration=2500, parent=self)
