import os
import threading
from typing import Optional
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QHeaderView,
    QApplication, QMenu
)
from qfluentwidgets import (
    TableView, LineEdit, PrimaryPushButton, PushButton, ToolButton,
    FluentIcon, SubtitleLabel, CaptionLabel, StrongBodyLabel, BodyLabel,
    CardWidget, InfoBar, InfoBarPosition
)

from core.spotify_client import SpotifyClient, TrackMetadata
from core.queue_manager import DownloadQueueManager
from core.config import config
from gui.queue_model import TrackQueueModel
from gui.queue_delegate import TrackCardDelegate
from gui.bridge import EngineSignalBridge
from gui.styles import BG_PRIMARY, BG_CARD, SPOTIFY_EMERALD, TEXT_PRIMARY, TEXT_MUTED


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


class QueueView(QWidget):
    """
    Main download queue management interface.
    Features:
    - Sticky top bar with URL input and clipboard auto-detect
    - Start / Pause / Clear controls
    - Metric summary cards
    - Virtualized TableView with custom card delegate
    """

    sig_resolved_tracks = pyqtSignal(list)
    sig_resolve_error = pyqtSignal(str)

    def __init__(self, queue_manager: DownloadQueueManager, bridge: EngineSignalBridge, parent=None):
        super().__init__(parent)
        self.qm = queue_manager
        self.bridge = bridge
        self.spotify_client = SpotifyClient(
            client_id=config.get("spotify.client_id", ""),
            client_secret=config.get("spotify.client_secret", "")
        )

        self.model = TrackQueueModel(self)
        self.delegate = TrackCardDelegate(self)

        self._init_ui()
        self._connect_signals()

        # Clipboard auto-detect timer (checks every 2s if URL is on clipboard)
        self.clipboard_timer = QTimer(self)
        self.clipboard_timer.timeout.connect(self._check_clipboard)
        self.clipboard_timer.start(2000)

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(24, 20, 24, 20)
        main_layout.setSpacing(16)

        # 1. Title
        title_label = SubtitleLabel("Download Queue", self)
        main_layout.addWidget(title_label)

        # 2. Input Bar & Enqueue Controls
        input_container = CardWidget(self)
        input_layout = QHBoxLayout(input_container)
        input_layout.setContentsMargins(12, 10, 12, 10)
        input_layout.setSpacing(10)

        self.url_input = LineEdit(self)
        self.url_input.setPlaceholderText("Paste Spotify track, album, or playlist URL (e.g. https://open.spotify.com/track/...)")
        self.url_input.setClearButtonEnabled(True)
        self.url_input.returnPressed.connect(self._on_enqueue_clicked)

        self.paste_btn = ToolButton(FluentIcon.PASTE, self)
        self.paste_btn.setToolTip("Paste from Clipboard")
        self.paste_btn.clicked.connect(self._paste_from_clipboard)

        self.enqueue_btn = PrimaryPushButton(FluentIcon.DOWNLOAD, "Analyze & Enqueue", self)
        self.enqueue_btn.clicked.connect(self._on_enqueue_clicked)

        input_layout.addWidget(self.url_input, 1)
        input_layout.addWidget(self.paste_btn)
        input_layout.addWidget(self.enqueue_btn)
        main_layout.addWidget(input_container)

        # 3. Metric Cards & Queue Controls Row
        ctrl_layout = QHBoxLayout()
        ctrl_layout.setSpacing(12)

        self.card_total = MetricCard("Total Tracks", "0", self)
        self.card_active = MetricCard("Downloading", "0", self)
        self.card_completed = MetricCard("Completed", "0", self)
        self.card_failed = MetricCard("Failed", "0", self)

        ctrl_layout.addWidget(self.card_total)
        ctrl_layout.addWidget(self.card_active)
        ctrl_layout.addWidget(self.card_completed)
        ctrl_layout.addWidget(self.card_failed)
        ctrl_layout.addStretch(1)

        self.start_btn = PrimaryPushButton(FluentIcon.PLAY, "Start All", self)
        self.start_btn.clicked.connect(self._on_start_clicked)

        self.pause_btn = PushButton(FluentIcon.PAUSE, "Pause", self)
        self.pause_btn.clicked.connect(self._on_pause_clicked)

        self.retry_btn = PushButton(FluentIcon.SYNC, "Retry Failed", self)
        self.retry_btn.clicked.connect(self._on_retry_failed_clicked)
        self.retry_btn.setEnabled(False)

        self.clear_btn = PushButton(FluentIcon.DELETE, "Clear Completed", self)
        self.clear_btn.clicked.connect(self._on_clear_clicked)

        ctrl_layout.addWidget(self.start_btn)
        ctrl_layout.addWidget(self.pause_btn)
        ctrl_layout.addWidget(self.retry_btn)
        ctrl_layout.addWidget(self.clear_btn)

        main_layout.addLayout(ctrl_layout)

        # 4. Central Virtualized TableView
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

        # Context menu
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)

        main_layout.addWidget(self.table, 1)

    def _connect_signals(self):
        self.bridge.sig_track_enqueued.connect(self._handle_enqueued)
        self.bridge.sig_source_resolved.connect(self._handle_source_resolved)
        self.bridge.sig_progress.connect(self._handle_progress)
        self.bridge.sig_status_changed.connect(self._handle_status_changed)
        self.bridge.sig_completed.connect(self._handle_completed)
        self.bridge.sig_failed.connect(self._handle_failed)
        self.sig_resolved_tracks.connect(self._on_tracks_resolved)
        self.sig_resolve_error.connect(self._on_resolve_error)

    def _check_clipboard(self):
        clipboard_text = QApplication.clipboard().text().strip()
        if SpotifyClient.parse_url(clipboard_text):
            if not self.url_input.text():
                self.paste_btn.setIcon(FluentIcon.LINK)
                self.paste_btn.setToolTip(f"Spotify link ready: {clipboard_text[:40]}...")
        else:
            self.paste_btn.setIcon(FluentIcon.PASTE)

    def _paste_from_clipboard(self):
        text = QApplication.clipboard().text().strip()
        if text:
            self.url_input.setText(text)

    def _on_enqueue_clicked(self):
        url = self.url_input.text().strip()
        if not url:
            InfoBar.warning(
                title="Empty URL",
                content="Please enter a valid Spotify track, album, or playlist link.",
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
                content="The link provided is not a supported Spotify track, album, or playlist URL.",
                orient=Qt.Orientation.Horizontal,
                position=InfoBarPosition.TOP,
                duration=3500,
                parent=self
            )
            return

        self.enqueue_btn.setEnabled(False)
        self.enqueue_btn.setText("Analyzing...")
        InfoBar.info(
            title="Analyzing Spotify Link",
            content="Resolving metadata and track details...",
            orient=Qt.Orientation.Horizontal,
            position=InfoBarPosition.TOP,
            duration=2500,
            parent=self
        )

        def resolve_worker():
            try:
                tracks = self.spotify_client.resolve(url)
                self.sig_resolved_tracks.emit(tracks)
            except Exception as e:
                self.sig_resolve_error.emit(str(e))

        threading.Thread(target=resolve_worker, daemon=True).start()

    def _on_tracks_resolved(self, tracks):
        self.enqueue_btn.setEnabled(True)
        self.enqueue_btn.setText("Analyze & Enqueue")
        self.url_input.clear()

        if not tracks:
            InfoBar.warning(
                title="No Tracks Found",
                content="No tracks could be extracted from this Spotify link.",
                orient=Qt.Orientation.Horizontal,
                position=InfoBarPosition.TOP,
                duration=3000,
                parent=self
            )
            return

        self.qm.enqueue(tracks)
        self.qm.start()

        InfoBar.success(
            title="Enqueued Successfully",
            content=f"Added {len(tracks)} track(s) to the download queue.",
            orient=Qt.Orientation.Horizontal,
            position=InfoBarPosition.TOP,
            duration=3500,
            parent=self
        )
        self._update_metrics()
        self.table.viewport().update()

    def _on_resolve_error(self, err: str):
        self.enqueue_btn.setEnabled(True)
        self.enqueue_btn.setText("Analyze & Enqueue")
        InfoBar.error(
            title="Resolution Error",
            content=f"Failed to resolve Spotify metadata: {err}",
            orient=Qt.Orientation.Horizontal,
            position=InfoBarPosition.TOP,
            duration=5000,
            parent=self
        )

    def _on_start_clicked(self):
        self.qm.start()
        self.qm.resume()
        self.pause_btn.setText("Pause")
        self.pause_btn.setIcon(FluentIcon.PAUSE)
        InfoBar.info("Queue Started", "Download queue is active.", duration=2000, parent=self)

    def _on_pause_clicked(self):
        if self.qm.is_paused():
            self.qm.resume()
            self.pause_btn.setText("Pause")
            self.pause_btn.setIcon(FluentIcon.PAUSE)
            InfoBar.info("Queue Resumed", "Download queue resumed.", duration=2000, parent=self)
        else:
            self.qm.pause()
            self.pause_btn.setText("Resume")
            self.pause_btn.setIcon(FluentIcon.PLAY)
            InfoBar.warning("Queue Paused", "Downloads paused.", duration=2000, parent=self)

    def _on_retry_failed_clicked(self):
        count = self.qm.retry_failed()
        if count > 0:
            InfoBar.success("Retrying Downloads", f"Re-queued {count} failed track(s).", duration=3000, parent=self)
        else:
            InfoBar.info("No Failed Tracks", "There are no failed tracks to retry.", duration=2000, parent=self)
        self._update_metrics()
        self.table.viewport().update()

    def _on_clear_clicked(self):
        self.model.clear_completed()
        self.qm.clear_completed()
        self._update_metrics()
        self.table.viewport().update()

    def _handle_enqueued(self, item):
        self.model.add_item(item)
        row = self.model.rowCount() - 1
        if row >= 0:
            self.table.setRowHeight(row, 76)
        self.table.viewport().update()
        self._update_metrics()

    def _handle_source_resolved(self, track_id: str, source_type: str, quality_badge: str):
        self.model.update_source(track_id, source_type, quality_badge)
        self.table.viewport().update()

    def _handle_progress(self, track_id: str, percent: float, speed_str: str, eta_str: str):
        self.model.update_progress(track_id, percent, speed_str, eta_str)
        self.table.viewport().update()

    def _handle_status_changed(self, track_id: str, status: str):
        self.model.update_status(track_id, status)
        self.table.viewport().update()
        self._update_metrics()

    def _handle_completed(self, track_id: str, path: str):
        self.table.viewport().update()
        self._update_metrics()

    def _handle_failed(self, track_id: str, err: str):
        self.table.viewport().update()
        self._update_metrics()

    def _update_metrics(self):
        total, active, completed, failed = self.model.get_stats()
        self.card_total.set_value(total)
        self.card_active.set_value(active)
        self.card_completed.set_value(completed)
        self.card_failed.set_value(failed)

        if failed > 0:
            self.retry_btn.setEnabled(True)
            self.retry_btn.setText(f"Retry Failed ({failed})")
        else:
            self.retry_btn.setEnabled(False)
            self.retry_btn.setText("Retry Failed")

    def _show_context_menu(self, pos):
        index = self.table.indexAt(pos)
        if not index.isValid():
            return
        item = self.model.get_item(index.row())
        if not item:
            return

        menu = QMenu(self)
        retry_act = None
        if item.status in ("Failed", "Cancelled"):
            retry_act = menu.addAction("Retry Download")
        cancel_act = None
        if item.status in ("Queued", "Downloading", "Resolving", "Paused"):
            cancel_act = menu.addAction("Cancel Download")
        copy_act = menu.addAction("Copy Track Title")

        action = menu.exec(self.table.viewport().mapToGlobal(pos))
        if action == cancel_act and cancel_act:
            self.qm.cancel_track(item.track.id)
        elif action == retry_act and retry_act:
            self.qm.retry_track(item.track.id)
            self._update_metrics()
        elif action == copy_act:
            QApplication.clipboard().setText(f"{item.track.title} - {item.track.artist_str}")
