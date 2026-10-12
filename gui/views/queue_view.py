import os
import subprocess
import threading
from typing import Optional, List, Dict, Any

from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QModelIndex, QUrl
from PyQt6.QtGui import QDesktopServices, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QHeaderView,
    QApplication, QMenu, QStackedLayout, QFrame, QLabel
)
from qfluentwidgets import (
    TableView, LineEdit, PrimaryPushButton, PushButton, ToolButton,
    FluentIcon, SubtitleLabel, CaptionLabel, StrongBodyLabel, BodyLabel,
    CardWidget, InfoBar, InfoBarPosition, ProgressBar, ComboBox, IconWidget
)

from core.spotify_client import SpotifyClient, TrackMetadata
from core.queue_manager import DownloadQueueManager, QueueItem
from core.config import config
from gui.queue_model import TrackQueueModel
from gui.queue_delegate import TrackCardDelegate
from gui.bridge import EngineSignalBridge
from gui.styles import BG_PRIMARY, BG_CARD, SPOTIFY_EMERALD, TEXT_PRIMARY, TEXT_SECONDARY, TEXT_MUTED


class MetricCard(CardWidget):
    """Sleek metric summary card."""
    def __init__(self, title: str, initial_value: str = "0", parent=None):
        super().__init__(parent)
        self.setMinimumWidth(100)
        self.setMaximumWidth(135)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 9, 14, 9)
        layout.setSpacing(3)

        self.title_label = CaptionLabel(title, self)
        self.title_label.setTextColor(TEXT_MUTED, TEXT_MUTED)
        self.value_label = StrongBodyLabel(initial_value, self)
        self.value_label.setStyleSheet("font-size: 18px; font-weight: 700; color: #FFFFFF;")

        layout.addWidget(self.title_label)
        layout.addWidget(self.value_label)

    def set_value(self, val: str | int):
        self.value_label.setText(str(val))


class EmptyQueueWidget(CardWidget):
    """Modern Fluent empty state placeholder when the queue has no tracks."""

    def __init__(self, on_paste_cb=None, on_browse_folder_cb=None, parent=None):
        super().__init__(parent)
        self.setStyleSheet("""
            EmptyQueueWidget, CardWidget {
                background-color: rgba(255, 255, 255, 0.02);
                border: 1px dashed rgba(255, 255, 255, 0.12);
                border-radius: 12px;
            }
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 38, 32, 38)
        layout.setSpacing(10)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        icon = IconWidget(FluentIcon.DOWNLOAD, self)
        icon.setFixedSize(52, 52)
        layout.addWidget(icon, 0, Qt.AlignmentFlag.AlignCenter)

        title = StrongBodyLabel("Your Download Queue is Empty", self)
        title.setStyleSheet("font-size: 18px; color: #FFFFFF; font-weight: 600;")
        layout.addWidget(title, 0, Qt.AlignmentFlag.AlignCenter)

        desc = QLabel(
            "Paste a Spotify, YouTube, or SoundCloud link above to begin downloading,\n"
            "or drag and drop music links directly into this window.",
            self
        )
        desc.setStyleSheet("color: #9E9E9E; font-size: 13px; line-height: 1.5; background: transparent;")
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(desc, 0, Qt.AlignmentFlag.AlignCenter)

        layout.addSpacing(6)

        # Feature highlights pills
        pills_layout = QHBoxLayout()
        pills_layout.setSpacing(8)
        pills_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        chips = [
            "🎵 Lossless FLAC & 320k",
            "⚡ YouTube Music Opus",
            "📜 Embedded Synced Lyrics",
            "🎚️ Multi-Format Transcoder"
        ]
        for chip_text in chips:
            chip = QLabel(chip_text, self)
            chip.setStyleSheet("""
                background-color: rgba(255, 255, 255, 0.05);
                border: 1px solid rgba(255, 255, 255, 0.10);
                border-radius: 12px;
                padding: 4px 12px;
                color: #B5B5B5;
                font-size: 11px;
                font-weight: 500;
            """)
            pills_layout.addWidget(chip)

        layout.addLayout(pills_layout)
        layout.addSpacing(10)

        # Quick action buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)
        btn_row.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.paste_action_btn = PushButton(FluentIcon.PASTE, "Paste from Clipboard", self)
        if on_paste_cb:
            self.paste_action_btn.clicked.connect(on_paste_cb)

        self.open_folder_action_btn = PushButton(FluentIcon.FOLDER, "Open Downloads Folder", self)
        if on_browse_folder_cb:
            self.open_folder_action_btn.clicked.connect(on_browse_folder_cb)

        btn_row.addWidget(self.paste_action_btn)
        btn_row.addWidget(self.open_folder_action_btn)
        layout.addLayout(btn_row)


class QueueView(QWidget):
    """
    Professional download queue management interface.
    Features:
    - Sticky top bar with URL input, drag & drop, and clipboard auto-detection
    - Master overall progress bar with ETA & completion percentage
    - Extended multi-selection with batch pause, retry, delete, and Explorer reveal
    - In-queue search filter and status filter pills
    - Double-click instant playback in built-in mini-player dock
    - Empty queue placeholder with quick action presets
    - Quick target audio format and download folder indicators
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

        self.setAcceptDrops(True)
        self._init_ui()
        self._connect_signals()

        # Clipboard auto-detect timer
        self.clipboard_timer = QTimer(self)
        self.clipboard_timer.timeout.connect(self._check_clipboard)
        self.clipboard_timer.start(2000)

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(24, 18, 24, 18)
        main_layout.setSpacing(14)

        # 1. Header Toolbar Row: Title + Open Downloads Folder Button
        header_row = QHBoxLayout()
        header_row.setSpacing(12)

        title_label = SubtitleLabel("Download Queue", self)
        header_row.addWidget(title_label)
        header_row.addStretch(1)

        self.open_downloads_btn = PushButton(FluentIcon.FOLDER, "Open Downloads Folder", self)
        self.open_downloads_btn.setToolTip("Open local download directory in Windows Explorer")
        self.open_downloads_btn.clicked.connect(self._open_downloads_folder)
        header_row.addWidget(self.open_downloads_btn)

        main_layout.addLayout(header_row)

        # 2. Input Bar & Enqueue Controls
        input_container = CardWidget(self)
        input_layout = QHBoxLayout(input_container)
        input_layout.setContentsMargins(12, 10, 12, 10)
        input_layout.setSpacing(10)

        self.url_input = LineEdit(self)
        self.url_input.setPlaceholderText("Paste Spotify / YouTube / SoundCloud link, or enter song title & artist to search...")
        self.url_input.setClearButtonEnabled(True)
        self.url_input.returnPressed.connect(self._on_enqueue_clicked)

        self.enqueue_btn = PrimaryPushButton(FluentIcon.DOWNLOAD, "Analyze && Enqueue", self)
        self.enqueue_btn.clicked.connect(self._on_enqueue_clicked)

        input_layout.addWidget(self.url_input, 1)
        input_layout.addWidget(self.enqueue_btn)
        main_layout.addWidget(input_container)

        # 3. Metric Cards & Queue Controls Row
        ctrl_layout = QHBoxLayout()
        ctrl_layout.setSpacing(10)

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

        self.stop_btn = PushButton(FluentIcon.CLOSE, "Stop", self)
        self.stop_btn.clicked.connect(self._on_stop_clicked)

        self.retry_btn = PushButton(FluentIcon.SYNC, "Retry Failed", self)
        self.retry_btn.clicked.connect(self._on_retry_failed_clicked)
        self.retry_btn.setEnabled(False)

        self.clear_btn = PushButton(FluentIcon.DELETE, "Clear Completed", self)
        self.clear_btn.clicked.connect(self._on_clear_clicked)

        ctrl_layout.addWidget(self.start_btn)
        ctrl_layout.addWidget(self.pause_btn)
        ctrl_layout.addWidget(self.stop_btn)
        ctrl_layout.addWidget(self.retry_btn)
        ctrl_layout.addWidget(self.clear_btn)
        main_layout.addLayout(ctrl_layout)

        # 4. Master Overall Progress Bar (Visible when items in queue)
        self.progress_container = QFrame(self)
        self.progress_container.setStyleSheet("background: transparent;")
        prog_layout = QVBoxLayout(self.progress_container)
        prog_layout.setContentsMargins(0, 0, 0, 0)
        prog_layout.setSpacing(4)

        prog_info_row = QHBoxLayout()
        self.overall_prog_label = CaptionLabel("Overall Progress: 0%", self.progress_container)
        self.overall_prog_label.setStyleSheet("color: #CCCCCC; font-size: 11px;")
        self.overall_stat_label = CaptionLabel("0 / 0 completed", self.progress_container)
        self.overall_stat_label.setTextColor(TEXT_MUTED, TEXT_MUTED)

        prog_info_row.addWidget(self.overall_prog_label)
        prog_info_row.addStretch(1)
        prog_info_row.addWidget(self.overall_stat_label)
        prog_layout.addLayout(prog_info_row)

        self.master_progress_bar = ProgressBar(self.progress_container)
        self.master_progress_bar.setRange(0, 100)
        self.master_progress_bar.setValue(0)
        self.master_progress_bar.setFixedHeight(5)
        prog_layout.addWidget(self.master_progress_bar)

        self.progress_container.setVisible(False)
        main_layout.addWidget(self.progress_container)

        # 5. Search & Filter Bar (Embedded in filter_container, hidden when queue is empty)
        self.filter_container = QWidget(self)
        filter_layout = QHBoxLayout(self.filter_container)
        filter_layout.setContentsMargins(0, 0, 0, 0)
        filter_layout.setSpacing(10)

        self.status_combo = ComboBox(self.filter_container)
        self.status_combo.addItems([
            "All Tracks",
            "Active / Downloading",
            "Queued / Pending",
            "Completed Only",
            "Failed / Stopped"
        ])
        self.status_combo.setFixedWidth(165)
        self.status_combo.currentIndexChanged.connect(self._on_filter_changed)

        self.remove_selected_btn = PushButton(FluentIcon.DELETE, "Remove Selected", self.filter_container)
        self.remove_selected_btn.clicked.connect(self._remove_selected_tracks)
        self.remove_selected_btn.setEnabled(False)

        self.sel_count_label = CaptionLabel("", self.filter_container)
        self.sel_count_label.setTextColor(TEXT_MUTED, TEXT_MUTED)

        filter_layout.addWidget(self.status_combo)
        filter_layout.addWidget(self.remove_selected_btn)
        filter_layout.addWidget(self.sel_count_label)
        filter_layout.addStretch(1)

        # Shortened & Collapsible Search Bar (appears when user clicks search or presses Ctrl+F)
        self.search_btn = ToolButton(FluentIcon.SEARCH, self.filter_container)
        self.search_btn.setToolTip("Search Queue (Ctrl+F)")
        self.search_btn.clicked.connect(self._toggle_search_bar)

        self.search_input = LineEdit(self.filter_container)
        self.search_input.setPlaceholderText("Filter queue...")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.setFixedWidth(220)
        self.search_input.setVisible(False)
        self.search_input.textChanged.connect(self._on_filter_changed)

        filter_layout.addWidget(self.search_btn)
        filter_layout.addWidget(self.search_input)

        self.filter_container.setVisible(False)
        main_layout.addWidget(self.filter_container)

        # Search shortcut (Ctrl+F)
        self.search_shortcut = QShortcut(QKeySequence("Ctrl+F"), self)
        self.search_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.search_shortcut.activated.connect(self._on_search_shortcut)

        # 6. Central Display Area: Stack between Empty State and TableView
        self.center_container = QWidget(self)
        self.center_layout = QStackedLayout(self.center_container)
        self.center_layout.setContentsMargins(0, 0, 0, 0)

        # State 0: Empty Queue Widget
        self.empty_widget = EmptyQueueWidget(
            on_paste_cb=self._paste_from_clipboard,
            on_browse_folder_cb=self._open_downloads_folder,
            parent=self.center_container
        )
        self.center_layout.addWidget(self.empty_widget)

        # State 1: Virtualized TableView with ExtendedSelection
        self.table = TableView(self.center_container)
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
        self.table.doubleClicked.connect(self._on_table_double_clicked)
        self.table.selectionModel().selectionChanged.connect(self._on_selection_changed)

        # Context menu
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)

        self.center_layout.addWidget(self.table)
        main_layout.addWidget(self.center_container, 1)

        # Initial view state
        self._update_display_stack()

    def _connect_signals(self):
        self.bridge.sig_track_enqueued.connect(self._handle_enqueued)
        self.bridge.sig_tracks_enqueued.connect(self._handle_tracks_enqueued)
        self.bridge.sig_source_resolved.connect(self._handle_source_resolved)
        self.bridge.sig_progress.connect(self._handle_progress)
        self.bridge.sig_status_changed.connect(self._handle_status_changed)
        self.bridge.sig_completed.connect(self._handle_completed)
        self.bridge.sig_failed.connect(self._handle_failed)
        self.sig_resolved_tracks.connect(self._on_tracks_resolved)
        self.sig_resolve_error.connect(self._on_resolve_error)

    # -------------------------------------------------------------------------
    # Drag & Drop Support
    # -------------------------------------------------------------------------
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() or event.mimeData().hasText():
            event.acceptProposedAction()

    def dropEvent(self, event):
        dropped_text = ""
        if event.mimeData().hasUrls():
            urls = [u.toString() for u in event.mimeData().urls()]
            dropped_text = urls[0] if urls else ""
        elif event.mimeData().hasText():
            dropped_text = event.mimeData().text().strip()

        if dropped_text:
            self.url_input.setText(dropped_text)
            self._on_enqueue_clicked()
            event.acceptProposedAction()

    # -------------------------------------------------------------------------
    # Keyboard Shortcuts & Search Toggles
    # -------------------------------------------------------------------------
    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Delete:
            self._remove_selected_tracks()
        elif event.matches(QKeySequence.StandardKey.SelectAll):
            self.table.selectAll()
        elif event.key() == Qt.Key.Key_Escape and self.search_input.isVisible():
            if not self.search_input.text().strip():
                self.search_input.setVisible(False)
            else:
                self.search_input.clear()
        else:
            super().keyPressEvent(event)

    def _toggle_search_bar(self):
        """Toggles the compact queue search input on and off."""
        if self.search_input.isVisible():
            if not self.search_input.text().strip():
                self.search_input.setVisible(False)
            else:
                self.search_input.setFocus()
                self.search_input.selectAll()
        else:
            self.search_input.setVisible(True)
            self.search_input.setFocus()

    def _on_search_shortcut(self):
        """Handles Ctrl+F shortcut to reveal and focus queue search."""
        if not self.filter_container.isVisible():
            return
        self.search_input.setVisible(True)
        self.search_input.setFocus()
        self.search_input.selectAll()

    # -------------------------------------------------------------------------
    # Filtering & Display Toggles
    # -------------------------------------------------------------------------
    def _on_filter_changed(self):
        query = self.search_input.text().strip()
        status_idx = self.status_combo.currentIndex()
        status_map = {
            0: "All",
            1: "Active",
            2: "Queued",
            3: "Completed",
            4: "Failed"
        }
        status_val = status_map.get(status_idx, "All")
        self.model.set_filter(query, status_val)
        self._update_display_stack()
        self._on_selection_changed()

    def _update_display_stack(self):
        total_items = len(self.model._all_items)
        has_filtered = len(self.model.items) > 0

        if total_items == 0:
            self.center_layout.setCurrentIndex(0)
            self.progress_container.setVisible(False)
            self.filter_container.setVisible(False)
            if self.search_input.isVisible() and not self.search_input.text().strip():
                self.search_input.setVisible(False)
        else:
            self.center_layout.setCurrentIndex(1)
            self.progress_container.setVisible(True)
            self.filter_container.setVisible(True)

    def _on_selection_changed(self):
        selected_rows = self.table.selectionModel().selectedRows()
        count = len(selected_rows)
        if count > 0:
            self.remove_selected_btn.setEnabled(True)
            self.remove_selected_btn.setText(f"Remove Selected ({count})")
            self.sel_count_label.setText(f"{count} track(s) selected")
        else:
            self.remove_selected_btn.setEnabled(False)
            self.remove_selected_btn.setText("Remove Selected")
            self.sel_count_label.setText("")

    # -------------------------------------------------------------------------
    # Clipboard & Ingestion Handlers
    # -------------------------------------------------------------------------
    def _check_clipboard(self):
        clipboard_text = QApplication.clipboard().text().strip()
        if SpotifyClient.parse_url(clipboard_text):
            if not self.url_input.text():
                self.url_input.setPlaceholderText(f"📋 Spotify link in clipboard: {clipboard_text[:40]}... (Press Ctrl+V)")
        else:
            if not self.url_input.text():
                self.url_input.setPlaceholderText("Paste Spotify / YouTube / SoundCloud link, or enter song title & artist to search...")

    def _paste_from_clipboard(self, *args):
        text = QApplication.clipboard().text().strip()
        if text:
            self.url_input.setText(text)

    def _open_downloads_folder(self):
        out_dir = config.get("download.output_dir", "downloads")
        os.makedirs(out_dir, exist_ok=True)
        try:
            os.startfile(out_dir)
        except Exception as e:
            InfoBar.error("Folder Error", f"Could not open directory: {e}", parent=self)

    def _on_enqueue_clicked(self, *args):
        self.spotify_client.update_credentials(
            client_id=config.get("spotify.client_id", ""),
            client_secret=config.get("spotify.client_secret", "")
        )

        raw_input = self.url_input.text().strip()
        if not raw_input:
            InfoBar.warning(
                title="Empty URL",
                content="Please enter a valid Spotify track, album, or playlist link.",
                orient=Qt.Orientation.Horizontal,
                position=InfoBarPosition.TOP,
                duration=3000,
                parent=self
            )
            return

        urls = [u.strip() for u in raw_input.splitlines() if u.strip()]
        url = urls[0] if urls else ""

        parsed = SpotifyClient.parse_url(url)
        if parsed:
            entity_type, entity_id = parsed
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
                    if tracks and entity_type in ("playlist", "album"):
                        try:
                            pl_name = tracks[0].collection_name or ("Spotify Playlist" if entity_type == "playlist" else "Spotify Album")
                            pl_cover = getattr(tracks[0], "collection_cover_url", "") or tracks[0].cover_url or ""
                            self.qm.archive.save_playlist(
                                name=pl_name,
                                spotify_url=url,
                                cover_url=pl_cover,
                                tracks=tracks,
                                playlist_id=entity_id
                            )
                        except Exception:
                            pass
                    self.sig_resolved_tracks.emit(tracks)
                except Exception as e:
                    self.sig_resolve_error.emit(str(e))

            threading.Thread(target=resolve_worker, daemon=True).start()
        else:
            self.enqueue_btn.setEnabled(False)
            self.enqueue_btn.setText("Analyzing...")
            disp_query = url if len(url) <= 40 else f"{url[:37]}..."
            InfoBar.info(
                title="Searching / Extracting",
                content=f"Searching or extracting audio tracks for '{disp_query}'...",
                orient=Qt.Orientation.Horizontal,
                position=InfoBarPosition.TOP,
                duration=2500,
                parent=self
            )

            def yt_resolve_worker():
                try:
                    ytdlp_engine = getattr(self.qm.engine, "ytdlp", None)
                    if not ytdlp_engine:
                        from core.ytdlp_engine import YtdlpEngine
                        ytdlp_engine = YtdlpEngine()
                    tracks = ytdlp_engine.extract_from_url_or_search(url)
                    if tracks and any(t.collection_type == "playlist" for t in tracks):
                        try:
                            pl_name = tracks[0].collection_name or "YouTube Playlist"
                            pl_cover = getattr(tracks[0], "collection_cover_url", "") or tracks[0].cover_url or ""
                            self.qm.archive.save_playlist(
                                name=pl_name,
                                spotify_url=url if url.startswith("http") else "",
                                cover_url=pl_cover,
                                tracks=tracks,
                                playlist_id=url if url.startswith("http") else ""
                            )
                        except Exception:
                            pass
                    self.sig_resolved_tracks.emit(tracks)
                except Exception as e:
                    self.sig_resolve_error.emit(str(e))

            threading.Thread(target=yt_resolve_worker, daemon=True).start()

    def _on_tracks_resolved(self, tracks):
        self.enqueue_btn.setEnabled(True)
        self.enqueue_btn.setText("Analyze && Enqueue")
        self.url_input.clear()

        if not tracks:
            InfoBar.warning(
                title="No Tracks Found",
                content="No tracks could be found or extracted from this link or query.",
                orient=Qt.Orientation.Horizontal,
                position=InfoBarPosition.TOP,
                duration=3000,
                parent=self
            )
            return

        self.qm.enqueue(tracks)

        has_spotify = any(not getattr(t, "id", "").startswith("yt_") for t in tracks)
        if has_spotify and (getattr(self.spotify_client, "last_was_truncated", False) or (not self.spotify_client.has_credentials() and len(tracks) == 100)):
            InfoBar.warning(
                title="Playlist Capped at 100 Tracks (Guest Limit)",
                content="Added 100 tracks. In guest mode, Spotify limits playlist embeds to 100 songs max. Add your free Spotify API keys in Settings to enqueue all 1,000+ songs.",
                orient=Qt.Orientation.Horizontal,
                position=InfoBarPosition.TOP,
                duration=10000,
                parent=self
            )
        else:
            InfoBar.success(
                title="Enqueued Successfully",
                content=f"Added {len(tracks)} track(s) to queue. Click 'Start All' to begin downloading.",
                orient=Qt.Orientation.Horizontal,
                position=InfoBarPosition.TOP,
                duration=4000,
                parent=self
            )
        self._update_metrics()
        self._update_display_stack()
        self.table.viewport().update()

    def _on_resolve_error(self, err: str):
        self.enqueue_btn.setEnabled(True)
        self.enqueue_btn.setText("Analyze && Enqueue")
        InfoBar.error(
            title="Resolution Error",
            content=f"Failed to resolve metadata: {err}",
            orient=Qt.Orientation.Horizontal,
            position=InfoBarPosition.TOP,
            duration=5000,
            parent=self
        )

    # -------------------------------------------------------------------------
    # Queue Control Actions
    # -------------------------------------------------------------------------
    def _on_start_clicked(self, *args):
        count = self.qm.start_all()
        for item in self.model._all_items:
            if item.status in ("Stopped", "Paused", "Failed"):
                item.status = "Queued"
                item.cancelled = False
        self.model.set_filter(self.model.filter_query, self.model.status_filter)
        self.pause_btn.setText("Pause")
        self.pause_btn.setIcon(FluentIcon.PAUSE)
        InfoBar.info("Queue Started", f"Download queue is active ({count} track(s) pending).", duration=2500, parent=self)
        self._update_metrics()
        self.table.viewport().update()

    def _on_stop_clicked(self, *args):
        self.qm.stop()
        for item in self.model._all_items:
            if item.status in ("Downloading", "Resolving", "Paused", "Queued"):
                item.status = "Stopped"
                item.cancelled = True
        self.model.set_filter(self.model.filter_query, self.model.status_filter)
        self.pause_btn.setText("Pause")
        self.pause_btn.setIcon(FluentIcon.PAUSE)
        InfoBar.warning("Queue Stopped", "Downloads stopped.", duration=2000, parent=self)
        self._update_metrics()
        self.table.viewport().update()

    def _on_pause_clicked(self, *args):
        if self.qm.is_paused():
            self.qm.resume()
            for item in self.model._all_items:
                if item.status == "Paused":
                    item.status = "Downloading"
            self.model.set_filter(self.model.filter_query, self.model.status_filter)
            self.pause_btn.setText("Pause")
            self.pause_btn.setIcon(FluentIcon.PAUSE)
            InfoBar.info("Queue Resumed", "Download queue resumed.", duration=2000, parent=self)
        else:
            self.qm.pause()
            for item in self.model._all_items:
                if item.status in ("Downloading", "Resolving"):
                    item.status = "Paused"
            self.model.set_filter(self.model.filter_query, self.model.status_filter)
            self.pause_btn.setText("Resume")
            self.pause_btn.setIcon(FluentIcon.PLAY)
            InfoBar.warning("Queue Paused", "Downloads paused.", duration=2000, parent=self)
        self._update_metrics()
        self.table.viewport().update()

    def _on_retry_failed_clicked(self, *args):
        count = self.qm.retry_failed()
        for item in self.model._all_items:
            if item.status in ("Failed", "Stopped"):
                item.status = "Queued"
                item.cancelled = False
                item.error_message = ""
        self.model.set_filter(self.model.filter_query, self.model.status_filter)
        if count > 0:
            InfoBar.success("Retrying Downloads", f"Re-queued {count} failed/stopped track(s).", duration=3000, parent=self)
        else:
            InfoBar.info("No Failed Tracks", "There are no failed or stopped tracks to retry.", duration=2000, parent=self)
        self._update_metrics()
        self.table.viewport().update()

    def _on_clear_clicked(self, *args):
        self.model.clear_completed()
        self.qm.clear_completed()
        self._update_metrics()
        self._update_display_stack()
        self.table.viewport().update()

    def _remove_selected_tracks(self):
        selected_indexes = self.table.selectionModel().selectedRows()
        if not selected_indexes:
            return
        track_ids = []
        for idx in selected_indexes:
            item = self.model.get_item(idx.row())
            if item:
                track_ids.append(item.track.id)

        if track_ids:
            self.qm.remove_tracks(track_ids)
            self.model.remove_items(track_ids)
            self._update_metrics()
            self._update_display_stack()
            self._on_selection_changed()
            self.table.viewport().update()
            InfoBar.info("Removed", f"Removed {len(track_ids)} track(s) from queue.", duration=2500, parent=self)

    # -------------------------------------------------------------------------
    # Bridge Signal Handlers
    # -------------------------------------------------------------------------
    def _handle_enqueued(self, item):
        self.model.add_item(item)
        self._update_metrics()
        self._update_display_stack()
        self.table.viewport().update()

    def _handle_tracks_enqueued(self, items: list):
        self.model.add_items(items)
        self._update_metrics()
        self._update_display_stack()
        self.table.viewport().update()

    def _handle_source_resolved(self, track_id: str, source_type: str, quality_badge: str):
        self.model.update_source(track_id, source_type, quality_badge)
        self.table.viewport().update()

    def _handle_progress(self, track_id: str, percent: float, speed_str: str, eta_str: str):
        self.model.update_progress(track_id, percent, speed_str, eta_str)
        self._update_metrics()
        self.table.viewport().update()

    def _handle_status_changed(self, track_id: str, status: str):
        self.model.update_status(track_id, status)
        self._update_metrics()
        self.table.viewport().update()

    def _handle_completed(self, track_id: str, path: str):
        self.model.mark_completed(track_id, path)
        self._update_metrics()
        self.table.viewport().update()

    def _handle_failed(self, track_id: str, err: str):
        self.model.mark_failed(track_id, err)
        self._update_metrics()
        self.table.viewport().update()

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

        # Update Master Progress Bar
        if total > 0:
            pct = int((completed / total) * 100)
            self.master_progress_bar.setValue(pct)
            self.overall_prog_label.setText(f"Overall Progress: {pct}% ({completed}/{total} tracks completed)")
            stat_text = f"{active} active • {failed} failed" if failed > 0 else f"{active} active"
            self.overall_stat_label.setText(stat_text)

    # -------------------------------------------------------------------------
    # Interactions: Double Click & Context Menu
    # -------------------------------------------------------------------------
    def _on_table_double_clicked(self, index: QModelIndex):
        item = self.model.get_item(index.row())
        if not item:
            return

        if item.status == "Completed" and item.output_path and os.path.isfile(item.output_path):
            # Play in built-in mini-player dock with full playlist navigation
            completed_items = [
                it for it in self.model._all_items
                if it.status == "Completed" and it.output_path and os.path.isfile(it.output_path)
            ]
            curr_idx = completed_items.index(item) if item in completed_items else -1
            win = self.window()
            if hasattr(win, "player_bar"):
                win.player_bar.play_track(item.output_path, item.track, item.quality_badge, playlist=completed_items, index=curr_idx)
            else:
                try:
                    os.startfile(item.output_path)
                except Exception:
                    pass
        elif item.status in ("Failed", "Cancelled", "Stopped"):
            self.qm.retry_track(item.track.id)
            self._update_metrics()
        elif item.status == "Queued":
            self.qm.start()

    def _show_context_menu(self, pos):
        selected_indexes = self.table.selectionModel().selectedRows()
        if not selected_indexes:
            index = self.table.indexAt(pos)
            if index.isValid():
                self.table.selectRow(index.row())
                selected_indexes = [index]
            else:
                return

        selected_items = [self.model.get_item(idx.row()) for idx in selected_indexes]
        selected_items = [it for it in selected_items if it is not None]
        if not selected_items:
            return

        menu = QMenu(self)

        # 1. Play track (if single completed item)
        if len(selected_items) == 1 and selected_items[0].status == "Completed" and selected_items[0].output_path:
            play_act = menu.addAction(FluentIcon.PLAY.qicon(), "Play Track in Audio Dock")
            explore_act = menu.addAction(FluentIcon.FOLDER.qicon(), "Show in File Explorer")
            menu.addSeparator()
        else:
            play_act = None
            explore_act = None

        # 2. Batch Retry / Cancel / Remove
        has_failed = any(it.status in ("Failed", "Cancelled", "Stopped") for it in selected_items)
        has_active = any(it.status in ("Queued", "Downloading", "Resolving", "Paused") for it in selected_items)

        retry_act = menu.addAction(FluentIcon.SYNC.qicon(), f"Retry Download ({len(selected_items)})") if has_failed else None
        cancel_act = menu.addAction(FluentIcon.CANCEL.qicon(), f"Cancel Download ({len(selected_items)})") if has_active else None
        remove_act = menu.addAction(FluentIcon.DELETE.qicon(), f"Remove from Queue ({len(selected_items)})")
        menu.addSeparator()

        copy_title_act = menu.addAction(FluentIcon.COPY.qicon(), "Copy Track Title(s)")
        copy_url_act = menu.addAction(FluentIcon.LINK.qicon(), "Copy Source Link")

        action = menu.exec(self.table.viewport().mapToGlobal(pos))
        if action == play_act and play_act:
            it = selected_items[0]
            completed_items = [
                x for x in self.model._all_items
                if x.status == "Completed" and x.output_path and os.path.isfile(x.output_path)
            ]
            curr_idx = completed_items.index(it) if it in completed_items else -1
            win = self.window()
            if hasattr(win, "player_bar"):
                win.player_bar.play_track(it.output_path, it.track, it.quality_badge, playlist=completed_items, index=curr_idx)
            else:
                os.startfile(it.output_path)
        elif action == explore_act and explore_act:
            it = selected_items[0]
            if os.path.isfile(it.output_path):
                subprocess.run(f'explorer /select,"{os.path.normpath(it.output_path)}"', shell=True)
            elif os.path.isdir(os.path.dirname(it.output_path)):
                os.startfile(os.path.dirname(it.output_path))
        elif action == retry_act and retry_act:
            for it in selected_items:
                if it.status in ("Failed", "Cancelled", "Stopped"):
                    self.qm.retry_track(it.track.id)
            self._update_metrics()
        elif action == cancel_act and cancel_act:
            for it in selected_items:
                if it.status in ("Queued", "Downloading", "Resolving", "Paused"):
                    self.qm.cancel_track(it.track.id)
            self._update_metrics()
        elif action == remove_act:
            tids = [it.track.id for it in selected_items]
            self.qm.remove_tracks(tids)
            self.model.remove_items(tids)
            self._update_metrics()
            self._update_display_stack()
            self._on_selection_changed()
        elif action == copy_title_act:
            titles = "\n".join(f"{it.track.title} - {it.track.artist_str}" for it in selected_items)
            QApplication.clipboard().setText(titles)
        elif action == copy_url_act:
            urls = "\n".join(it.track.spotify_url for it in selected_items if getattr(it.track, "spotify_url", ""))
            if not urls:
                urls = "\n".join(f"https://open.spotify.com/track/{it.track.id}" for it in selected_items)
            QApplication.clipboard().setText(urls)
