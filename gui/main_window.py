import os
import sys
import logging
from PyQt6.QtCore import Qt, QSize, QTimer
from PyQt6.QtGui import QIcon, QKeySequence, QShortcut, QColor
from PyQt6.QtWidgets import QApplication
from qfluentwidgets import (
    FluentWindow, NavigationItemPosition, FluentIcon,
    setTheme, Theme, isDarkTheme
)

from core.queue_manager import DownloadQueueManager
from core.musilon import MusilonEngine
from core.ytdlp_engine import YtdlpEngine
from core.lyrics import LyricsEngine
from core.tagger import AudioTagger
from core.resolver import CascadingAudioEngine
from core.archive import ArchiveManager
from core.config import config
from core.utils import resource_path

from gui.bridge import EngineSignalBridge
from gui.views.queue_view import QueueView
from gui.views.completed_view import CompletedView
from gui.views.settings_view import SettingsView

logger = logging.getLogger("gui.main_window")


class MainWindow(FluentWindow):
    """
    Windows 11 Fluent Design Main Application Window.
    Integrates Navigation Sidebar, Queue View, Completed View, and Settings View.
    """

    def __init__(self):
        super().__init__()
        self.setObjectName("spotify_downloader_main_window")
        self.setWindowTitle("Spotify Downloader — High-Fidelity Suite")
        self.resize(1060, 720)
        self.setMinimumSize(880, 600)

        # Center on screen
        try:
            screen = QApplication.primaryScreen()
            if screen:
                geom = screen.availableGeometry()
                x = max(0, (geom.width() - 1060) // 2)
                y = max(0, (geom.height() - 720) // 2)
                self.move(x, y)
        except Exception as e:
            logger.debug(f"Could not center window: {e}")

        # Force Dark Theme and ensure solid background so window is never transparent
        setTheme(Theme.DARK)
        self.setStyleSheet("MainWindow, FluentWindow { background-color: #181818; }")

        # Initialize Headless Core Engine & Persistent Archive
        self.archive_manager = ArchiveManager()

        self.musilon_engine = MusilonEngine(
            session_cookie=config.get("musilon.session_cookie", ""),
            username=config.get("musilon.username", ""),
            password=config.get("musilon.password", ""),
            enabled=config.get("musilon.enabled", True)
        )
        self.ytdlp_engine = YtdlpEngine(
            output_dir=config.get("download.output_dir", "")
        )
        self.lyrics_engine = LyricsEngine()
        self.tagger = AudioTagger()

        self.audio_engine = CascadingAudioEngine(
            musilon_engine=self.musilon_engine,
            ytdlp_engine=self.ytdlp_engine,
            lyrics_engine=self.lyrics_engine,
            tagger=self.tagger
        )

        self.queue_manager = DownloadQueueManager(
            audio_engine=self.audio_engine,
            archive_manager=self.archive_manager,
            max_concurrent_downloads=config.get("download.concurrency", 2)
        )

        # Signal Bridge between Core Callbacks and Qt Event Loop
        self.bridge = EngineSignalBridge()
        self.bridge.bind_queue_manager(self.queue_manager)

        # Create Sub-Interface Views with explicit object names
        self.queue_view = QueueView(self.queue_manager, self.bridge, self)
        self.queue_view.setObjectName("queue_view")

        self.completed_view = CompletedView(self.bridge, archive_manager=self.archive_manager, parent=self)
        self.completed_view.setObjectName("completed_view")

        self.settings_view = SettingsView(musilon_engine=self.musilon_engine, parent=self)
        self.settings_view.setObjectName("settings_view")

        # Setup Navigation
        self._init_navigation()

        # Connect Bridge to Completed View
        self.bridge.sig_completed.connect(self._on_track_completed)

        # Background scan of output directory to index any pre-existing downloads into archive
        output_dir = config.get("download.output_dir", "downloads")
        if os.path.exists(output_dir):
            import threading
            threading.Thread(
                target=self._scan_and_index_startup,
                args=(output_dir,),
                daemon=True,
                name="ArchiveStartupScanner"
            ).start()

        # Global Hotkey (Ctrl+V to focus and paste into URL bar)
        self.paste_shortcut = QShortcut(QKeySequence("Ctrl+V"), self)
        self.paste_shortcut.activated.connect(self._on_paste_shortcut)

        # Ensure Queue View is selected on initial display
        QTimer.singleShot(50, lambda: self.switchTo(self.queue_view))

    def _init_navigation(self):
        self.addSubInterface(
            self.queue_view,
            FluentIcon.DOWNLOAD,
            "Queue",
            NavigationItemPosition.TOP
        )
        self.addSubInterface(
            self.completed_view,
            FluentIcon.COMPLETED,
            "Completed",
            NavigationItemPosition.TOP
        )
        self.addSubInterface(
            self.settings_view,
            FluentIcon.SETTING,
            "Settings",
            NavigationItemPosition.BOTTOM
        )

    def showEvent(self, event):
        super().showEvent(event)
        self.raise_()
        self.activateWindow()

    def _on_track_completed(self, track_id: str, path: str):
        for it in self.queue_manager.get_items():
            if it.track.id == track_id:
                self.completed_view.add_completed_item(it)
                break

    def _scan_and_index_startup(self, output_dir: str):
        try:
            indexed = self.archive_manager.scan_and_index_directory(output_dir)
            if indexed > 0:
                logger.info(f"Startup scan indexed {indexed} tracks into download archive.")
                # Safe reload of the completed library on the Qt event loop
                QTimer.singleShot(0, self.completed_view.reload_from_archive)
        except Exception as e:
            logger.warning(f"Error during startup archive directory scan: {e}")

    def _on_paste_shortcut(self):
        self.switchTo(self.queue_view)
        clipboard_text = QApplication.clipboard().text().strip()
        if "spotify.com" in clipboard_text:
            self.queue_view.url_input.setText(clipboard_text)
            self.queue_view.url_input.setFocus()

    def closeEvent(self, event):
        self.queue_manager.stop()
        super().closeEvent(event)
