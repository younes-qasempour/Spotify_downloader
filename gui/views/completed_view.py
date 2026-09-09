import os
import subprocess
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QHeaderView
)
from qfluentwidgets import (
    TableView, SubtitleLabel, PushButton, FluentIcon, InfoBar
)

from gui.queue_model import TrackQueueModel
from gui.queue_delegate import TrackCardDelegate
from gui.bridge import EngineSignalBridge


class CompletedView(QWidget):
    """
    Library view displaying successfully downloaded tracks.
    Provides direct 'Open in Explorer' and 'Play' actions.
    """

    def __init__(self, bridge: EngineSignalBridge, parent=None):
        super().__init__(parent)
        self.bridge = bridge
        self.model = TrackQueueModel(self)
        self.delegate = TrackCardDelegate(self)

        self._init_ui()
        self.bridge.sig_completed.connect(self._on_track_completed)

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(16)

        # Header Row
        header_layout = QHBoxLayout()
        title = SubtitleLabel("Completed Downloads", self)
        header_layout.addWidget(title)
        header_layout.addStretch(1)

        self.open_folder_btn = PushButton(FluentIcon.FOLDER, "Open Download Folder", self)
        self.open_folder_btn.clicked.connect(self._open_download_folder)
        header_layout.addWidget(self.open_folder_btn)

        layout.addLayout(header_layout)

        # Table View
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

        layout.addWidget(self.table, 1)

    def _on_track_completed(self, track_id: str, path: str):
        # We can look up the item from parent or add completed item
        pass

    def add_completed_item(self, item):
        self.model.add_item(item)

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
