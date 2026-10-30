import os
import sys
import logging
from PyQt6.QtCore import Qt, QSize, QTimer, pyqtSignal, QEasingCurve, QPoint, QCoreApplication
if os.environ.get("QT_QPA_PLATFORM", "").lower() != "offscreen":
    try:
        QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
        import PyQt6.QtWebEngineWidgets  # noqa: F401
    except Exception:
        pass
from PyQt6.QtGui import QIcon, QKeySequence, QShortcut, QColor
from PyQt6.QtWidgets import QApplication, QSystemTrayIcon, QMenu, QVBoxLayout
from qfluentwidgets import (
    FluentWindow, NavigationItemPosition, FluentIcon,
    setTheme, Theme, isDarkTheme, setThemeColor
)
from gui.player_bar import MiniPlayerBar
from gui.media_keys import MediaControllerManager

from core.queue_manager import DownloadQueueManager
from core.musilon import MusilonEngine
from core.melobot import MeloBotEngine
from core.ytdlp_engine import YtdlpEngine
from core.lyrics import LyricsEngine
from core.tagger import AudioTagger
from core.resolver import CascadingAudioEngine
from core.archive import ArchiveManager
from core.config import config
from core.utils import resource_path
from core.paths import get_asset_path

from gui.bridge import EngineSignalBridge
from gui.views.web_studio_view import WebStudioView
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
        self.setWindowTitle("Flacify — High-Fidelity Audio Studio")
        self.resize(1240, 800)
        self.setMinimumSize(960, 640)

        # Set Window Icon
        icon_path = get_asset_path("assets/icon.ico")
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        # Center on screen
        try:
            screen = QApplication.primaryScreen()
            if screen:
                geom = screen.availableGeometry()
                x = max(0, (geom.width() - 1240) // 2)
                y = max(0, (geom.height() - 800) // 2)
                self.move(x, y)
        except Exception as e:
            logger.debug(f"Could not center window: {e}")

        # Force Dark Theme and Spotify Green accent (prevents Windows red system accent bleed)
        setTheme(Theme.DARK)
        try:
            setThemeColor(QColor("#1DB954"))
        except Exception:
            pass
        self.setStyleSheet("MainWindow, FluentWindow { background-color: #000000; }")

        # Initialize Headless Core Engine & Persistent Archive
        self.archive_manager = ArchiveManager()
        self.archive_manager.checkpoint_wal()

        self.musilon_engine = MusilonEngine(
            session_cookie=config.get("musilon.session_cookie", ""),
            username=config.get("musilon.username", ""),
            password=config.get("musilon.password", ""),
            enabled=config.get("musilon.enabled", True)
        )
        self.melobot_engine = MeloBotEngine()
        self.ytdlp_engine = YtdlpEngine(
            output_dir=config.get("download.output_dir", "")
        )
        self.lyrics_engine = LyricsEngine()
        self.tagger = AudioTagger()

        self.audio_engine = CascadingAudioEngine(
            musilon_engine=self.musilon_engine,
            melobot_engine=self.melobot_engine,
            ytdlp_engine=self.ytdlp_engine,
            lyrics_engine=self.lyrics_engine,
            tagger=self.tagger
        )

        self.queue_manager = DownloadQueueManager(
            audio_engine=self.audio_engine,
            archive_manager=self.archive_manager,
            max_concurrent_downloads=config.get("download.concurrency", 5)
        )

        # Signal Bridge between Core Callbacks and Qt Event Loop
        self.bridge = EngineSignalBridge()
        self.bridge.bind_queue_manager(self.queue_manager)

        # Primary Chromium-powered Spotify Desktop Web Studio View
        self.web_studio_view = WebStudioView(
            queue_manager=self.queue_manager,
            archive_manager=self.archive_manager,
            parent=self,
        )

        # Create Sub-Interface Views with explicit object names (preserved for tests & fallback)
        self.queue_view = QueueView(self.queue_manager, self.bridge, self)
        self.queue_view.setObjectName("queue_view")

        self.playlists_view = PlaylistsView(
            archive_manager=self.archive_manager,
            queue_manager=self.queue_manager,
            bridge=self.bridge,
            parent=self
        )
        self.playlists_view.setObjectName("playlists_view")

        self.completed_view = CompletedView(self.bridge, archive_manager=self.archive_manager, queue_manager=self.queue_manager, parent=self)
        self.completed_view.setObjectName("completed_view")

        self.settings_view = SettingsView(
            musilon_engine=self.musilon_engine,
            melobot_engine=self.melobot_engine,
            queue_manager=self.queue_manager,
            parent=self
        )
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

        # Launch into the new full-bleed Spotify Desktop Web Studio by default
        self.switchTo(self.web_studio_view)
        if hasattr(self, "navigationInterface"):
            self.navigationInterface.setVisible(False)
        self.widgetLayout.setContentsMargins(0, 32, 0, 0)

    def _init_navigation(self):
        self.addSubInterface(
            self.web_studio_view,
            FluentIcon.HOME,
            "Studio",
            NavigationItemPosition.TOP
        )
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
        if hasattr(self, "archive_manager"):
            try:
                self.archive_manager.checkpoint_wal()
            except Exception as e_wal:
                logger.debug(f"Error checkpointing WAL on quit: {e_wal}")
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
        if hasattr(self, "web_studio_view") and self.web_studio_view.web_server:
            self.web_studio_view.web_server.state.invalidate_library_cache()
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

    def _show_musilon_limit_dialog(self, track, item, reason_or_cb, decision_callback=None):
        if decision_callback is None and callable(reason_or_cb):
            decision_callback = reason_or_cb
            reason = "Musilon download rate limit or daily VIP quota reached."
        else:
            reason = str(reason_or_cb or "Musilon stream download rejected.")

        source_engine = str(config.get("source_engine", "musilon")).strip().lower()
        pref_eng = getattr(track, "preferred_engine", None) or getattr(item, "preferred_engine", None)
        item_source = getattr(item, "source_type", "")
        if source_engine == "melobot" or pref_eng == "melobot" or item_source == "MeloBot" or (config.get("telegram.enabled", False) and not config.get("musilon.enabled", True)):
            logger.info("MeloBot active; suppressing Musilon limit dialog and continuing via YouTube fallback.")
            if decision_callback:
                decision_callback("continue_youtube")
            return

        from qfluentwidgets import MessageBox
        track_title = getattr(track, "title", "Track")
        artist_name = getattr(track, "primary_artist", "Unknown Artist")

        is_quota = any(w in reason.lower() for w in ("limit", "quota", "429", "budget"))
        is_vip = any(w in reason.lower() for w in ("vip", "auth", "401", "402", "403", "credential", "subscription", "session"))

        if is_quota:
            title = "Musilon Download Limit Reached"
            desc = "Musilon has reached its download rate limit or daily VIP quota while downloading:"
            action_prompt = "Would you like to continue downloading from YouTube Music, or stop the downloading process?"
        elif is_vip:
            title = "Musilon VIP / Account Issue"
            desc = "Musilon encountered an account or VIP subscription issue while downloading:"
            action_prompt = "Would you like to continue downloading from YouTube Music, or stop to fix your VIP credentials in Settings?"
        else:
            title = "Musilon Download Failed"
            desc = "Musilon failed or rejected the download stream for:"
            action_prompt = "Would you like to continue downloading from YouTube Music, or stop the downloading process?"

        dialog = MessageBox(
            title=title,
            content=(
                f"{desc}\n\n"
                f"  • {track_title} - {artist_name}\n\n"
                f"Details: {reason}\n\n"
                f"{action_prompt}"
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
        if hasattr(self, "archive_manager"):
            try:
                self.archive_manager.checkpoint_wal()
            except Exception as e_wal:
                logger.debug(f"Error checkpointing WAL on exit: {e_wal}")
        if hasattr(self, "media_controller"):
            self.media_controller.cleanup()
        if hasattr(self, "web_studio_view"):
            try:
                self.web_studio_view.shutdown()
            except Exception:
                pass
        if hasattr(self, "player_bar"):
            self.player_bar.player.stop()
        self.queue_manager.stop()
        super().closeEvent(event)
