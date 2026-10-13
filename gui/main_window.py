import os
import sys
import logging
from PyQt6.QtCore import Qt, QSize, QTimer, pyqtSignal, QEasingCurve, QPoint
from PyQt6.QtGui import QIcon, QKeySequence, QShortcut, QColor
from PyQt6.QtWidgets import QApplication, QSystemTrayIcon, QMenu, QVBoxLayout
from qfluentwidgets import (
    FluentWindow, NavigationItemPosition, FluentIcon,
    setTheme, Theme, isDarkTheme
)
from gui.player_bar import MiniPlayerBar
from gui.media_keys import MediaControllerManager

from core.queue_manager import DownloadQueueManager
from core.musilon import MusilonEngine
from core.ytdlp_engine import YtdlpEngine
from core.lyrics import LyricsEngine
from core.tagger import AudioTagger
from core.resolver import CascadingAudioEngine
from core.archive import ArchiveManager
from core.config import config
from core.utils import resource_path
from core.paths import get_asset_path

from gui.bridge import EngineSignalBridge
from gui.views.queue_view import QueueView
from gui.views.playlists_view import PlaylistsView
from gui.views.completed_view import CompletedView
from gui.views.settings_view import SettingsView

logger = logging.getLogger("gui.main_window")


class MainWindow(FluentWindow):
    """
    Windows 11 Fluent Design Main Application Window.
    Integrates Navigation Sidebar, Queue View, Completed View, and Settings View.
    """

    sig_reload_library = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setObjectName("flacify_main_window")
        self.setWindowTitle("Flacify — High-Fidelity Audio Scraper")
        self.resize(1060, 720)
        self.setMinimumSize(880, 600)

        # Set Window Icon
        icon_path = get_asset_path("assets/icon.ico")
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

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

        self.playlists_view = PlaylistsView(
            archive_manager=self.archive_manager,
            queue_manager=self.queue_manager,
            bridge=self.bridge,
            parent=self
        )
        self.playlists_view.setObjectName("playlists_view")

        self.completed_view = CompletedView(self.bridge, archive_manager=self.archive_manager, parent=self)
        self.completed_view.setObjectName("completed_view")

        self.settings_view = SettingsView(musilon_engine=self.musilon_engine, parent=self)
        self.settings_view.setObjectName("settings_view")

        # Setup Navigation
        self._init_navigation()

        # Connect Bridge to Completed View
        self.bridge.sig_completed.connect(self._on_track_completed)
        self.bridge.sig_musilon_limit_reached.connect(self._show_musilon_limit_dialog)
        self.sig_reload_library.connect(self.completed_view.reload_all)

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

        # Mini-Player Dock
        self.player_bar = MiniPlayerBar(self)
        try:
            self.widgetLayout.removeWidget(self.stackedWidget)
            v_player_lay = QVBoxLayout()
            v_player_lay.setContentsMargins(0, 0, 0, 0)
            v_player_lay.setSpacing(0)
            v_player_lay.addWidget(self.stackedWidget, 1)
            v_player_lay.addWidget(self.player_bar, 0)
            self.widgetLayout.addLayout(v_player_lay)
        except Exception as e_dock:
            logger.debug(f"Could not dock player bar into layout: {e_dock}")

        # Media Key & Hardware Controller System
        self.media_controller = MediaControllerManager(self)
        self.media_controller.setup()

        # Optimize tab switching animation: prevent position drift and ensure snappy, smooth transition
        self._setup_smooth_tab_transitions()

        # Windows 11 System Tray Icon & Toasts
        self._init_system_tray(icon_path)

        # Ensure Queue View is selected on initial display
        self.switchTo(self.queue_view)

    def _init_navigation(self):
        self.addSubInterface(
            self.queue_view,
            FluentIcon.DOWNLOAD,
            "Queue",
            NavigationItemPosition.TOP
        )
        self.addSubInterface(
            self.playlists_view,
            FluentIcon.ALBUM,
            "Playlists",
            NavigationItemPosition.TOP
        )
        self.addSubInterface(
            self.completed_view,
            FluentIcon.MUSIC,
            "Library",
            NavigationItemPosition.TOP
        )
        self.addSubInterface(
            self.settings_view,
            FluentIcon.SETTING,
            "Settings",
            NavigationItemPosition.BOTTOM
        )

    def _setup_smooth_tab_transitions(self):
        """
        Hardens PopUpAniStackedWidget tab transitions:
        - Prevents position drift when switching tabs rapidly
        - Replaces jarring 76px jump with subtle, elegant 24px Fluent slide
        - Reduces animation duration from 300ms to a snappy 160ms
        - Guarantees views are always cleanly positioned at (0, 0)
        """
        view = self.stackedWidget.view
        for info in view.aniInfos:
            info.deltaY = 24

        orig_setCurrentIndex = view.setCurrentIndex

        def safe_setCurrentIndex(index: int, *args, **kwargs):
            if index == view.currentIndex():
                return
            if view._ani and view._ani.state() == view._ani.State.Running:
                view._ani.stop()
            for info in view.aniInfos:
                info.widget.move(0, 0)
            return orig_setCurrentIndex(
                index,
                needPopOut=False,
                showNextWidgetDirectly=True,
                duration=160,
                easingCurve=QEasingCurve.Type.OutCubic
            )

        view.setCurrentIndex = safe_setCurrentIndex
        view.aniFinished.connect(lambda: view.currentWidget().move(0, 0) if view.currentWidget() else None)

    def _init_system_tray(self, icon_path):
        """Initializes Windows 11 System Tray icon with quick actions and toast notifications."""
        if not QSystemTrayIcon.isSystemTrayAvailable():
            self.tray_icon = None
            return

        self.tray_icon = QSystemTrayIcon(self)
        if icon_path and icon_path.exists():
            self.tray_icon.setIcon(QIcon(str(icon_path)))
        else:
            self.tray_icon.setIcon(self.windowIcon())
        self.tray_icon.setToolTip("Flacify — High-Fidelity Audio Scraper")

        # Context Menu
        menu = QMenu()
        open_act = menu.addAction("Open Flacify")
        open_act.triggered.connect(self._restore_from_tray)

        menu.addSeparator()

        pause_act = menu.addAction("Pause Downloads")
        pause_act.triggered.connect(self.queue_manager.pause)

        resume_act = menu.addAction("Resume Downloads")
        resume_act.triggered.connect(self.queue_manager.resume)

        menu.addSeparator()

        exit_act = menu.addAction("Exit")
        exit_act.triggered.connect(self._quit_application)

        self.tray_icon.setContextMenu(menu)
        self.tray_icon.activated.connect(self._on_tray_activated)
        self.tray_icon.show()

    def _restore_from_tray(self):
        self.showNormal()
        self.activateWindow()
        self.raise_()

    def _on_tray_activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            if self.isVisible():
                if self.isMinimized():
                    self.showNormal()
                self.activateWindow()
                self.raise_()
            else:
                self.showNormal()
                self.activateWindow()
                self.raise_()

    def _quit_application(self):
        if hasattr(self, "player_bar"):
            self.player_bar.player.stop()
        self.close()
        QApplication.quit()

    def play_audio_track(
        self,
        file_path: str,
        track: Optional[TrackMetadata] = None,
        quality_badge: str = "",
        playlist: Optional[List[Any]] = None,
        index: int = -1
    ):
        """Plays track via the built-in mini-player dock with synchronized lyrics and playlist navigation."""
        if hasattr(self, "player_bar"):
            self.player_bar.play_track(file_path, track, quality_badge, playlist=playlist, index=index)

    def showEvent(self, event):
        super().showEvent(event)
        self.raise_()
        self.activateWindow()

    def _on_track_completed(self, track_id: str, path: str):
        title_str = os.path.basename(path)
        for it in self.queue_manager.get_items():
            if it.track.id == track_id:
                self.completed_view.add_completed_item(it)
                title_str = f"{it.track.title} — {it.track.artist_str}"
                break

        # Show desktop notification via System Tray
        if getattr(self, "tray_icon", None) and self.tray_icon.isVisible():
            self.tray_icon.showMessage(
                "Download Completed",
                title_str,
                QSystemTrayIcon.MessageIcon.Information,
                3000
            )

    def _show_musilon_limit_dialog(self, track, item, decision_callback):
        from qfluentwidgets import MessageBox
        track_title = getattr(track, "title", "Track")
        artist_name = getattr(track, "primary_artist", "Unknown Artist")

        dialog = MessageBox(
            title="Musilon Download Limit Reached",
            content=(
                f"Musilon has reached its download rate limit or daily VIP quota while downloading:\n\n"
                f"  • {track_title} - {artist_name}\n\n"
                "This track was found on Musilon, but the site rejected the download stream due to rate restrictions.\n\n"
                "Would you like to continue downloading from YouTube Music, or stop the downloading process?"
            ),
            parent=self
        )
        dialog.yesButton.setText("Continue with YouTube")
        dialog.cancelButton.setText("Stop Downloads")

        if dialog.exec():
            decision_callback("continue_youtube")
        else:
            decision_callback("stop")

    def _scan_and_index_startup(self, output_dir: str):
        try:
            indexed = self.archive_manager.scan_and_index_directory(output_dir)
            if indexed > 0:
                logger.info(f"Startup scan indexed {indexed} tracks into download archive.")
                # Safe thread-safe reload of the completed library on the Qt event loop
                try:
                    self.sig_reload_library.emit()
                except (RuntimeError, AttributeError):
                    pass
        except Exception as e:
            logger.warning(f"Error during startup archive directory scan: {e}")

    def _on_paste_shortcut(self):
        from PyQt6.QtWidgets import QLineEdit, QTextEdit
        from qfluentwidgets import LineEdit
        focus_w = QApplication.focusWidget()
        if isinstance(focus_w, (QLineEdit, QTextEdit, LineEdit)) and focus_w != self.queue_view.url_input:
            return  # Allow standard paste in active input fields
        clipboard_text = QApplication.clipboard().text().strip()
        if "spotify.com" in clipboard_text:
            self.switchTo(self.queue_view)
            self.queue_view.url_input.setText(clipboard_text)
            self.queue_view.url_input.setFocus()

    def closeEvent(self, event):
        try:
            from core.genre import get_genre_resolver
            get_genre_resolver().save_cache()
        except Exception as e_cache:
            logger.debug(f"Error saving genre cache on exit: {e_cache}")
        if hasattr(self, "media_controller"):
            self.media_controller.cleanup()
        if hasattr(self, "player_bar"):
            self.player_bar.player.stop()
        self.queue_manager.stop()
        super().closeEvent(event)
