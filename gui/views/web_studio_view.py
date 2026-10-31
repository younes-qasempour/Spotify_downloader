import logging
import os
import threading
from typing import Optional, Any

from PyQt6.QtCore import Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QFileDialog, QVBoxLayout, QWidget

from core.archive import ArchiveManager
from core.paths import get_asset_path
from core.queue_manager import DownloadQueueManager
from gui.web_api import FlacifyWebServer

logger = logging.getLogger("gui.views.web_studio_view")


class WebStudioView(QWidget):
    """
    Chromium-powered Spotify Desktop Web UI & Real-Time WebAudio DSP Studio.
    Hosts the React/ES6 + CSS3 Glassmorphic UI inside QWebEngineView backed by FlacifyWebServer.
    """

    _sig_request_folder = pyqtSignal(str)

    def __init__(
        self,
        queue_manager: DownloadQueueManager,
        archive_manager: ArchiveManager,
        musilon_engine: Optional[Any] = None,
        melobot_engine: Optional[Any] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.setObjectName("web_studio_view")
        self.qm = queue_manager
        self.archive = archive_manager

        self._folder_event = threading.Event()
        self._chosen_folder = ""
        self._sig_request_folder.connect(self._on_main_thread_folder_dialog)

        # Resolve web_ui directory path
        web_root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web_ui")
        if not os.path.isdir(web_root):
            web_root = str(get_asset_path("gui/web_ui"))

        self.web_server = FlacifyWebServer(
            queue_manager=self.qm,
            archive_manager=self.archive,
            web_root=web_root,
            folder_picker_cb=self._pick_folder_threadsafe,
            musilon_engine=musilon_engine,
            melobot_engine=melobot_engine,
        )
        self.server_url = self.web_server.start()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.webview = None
        is_offscreen = os.environ.get("QT_QPA_PLATFORM", "").lower() == "offscreen"
        if not is_offscreen:
            try:
                from PyQt6.QtWebEngineCore import QWebEngineSettings
                from PyQt6.QtWebEngineWidgets import QWebEngineView

                self.webview = QWebEngineView(self)
                self.webview.page().setBackgroundColor(QColor("#000000"))

                settings = self.webview.settings()
                settings.setAttribute(QWebEngineSettings.WebAttribute.PlaybackRequiresUserGesture, False)
                settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
                settings.setAttribute(QWebEngineSettings.WebAttribute.Accelerated2dCanvasEnabled, True)
                settings.setAttribute(QWebEngineSettings.WebAttribute.ScrollAnimatorEnabled, True)

                self.webview.setUrl(QUrl(self.server_url))
                layout.addWidget(self.webview, 1)
            except Exception as e:
                logger.error(f"Could not initialize QWebEngineView: {e}")

    def _pick_folder_threadsafe(self, current_dir: str) -> str:
        self._chosen_folder = ""
        self._folder_event.clear()
        self._sig_request_folder.emit(current_dir)
        self._folder_event.wait(timeout=60.0)
        return self._chosen_folder

    def _on_main_thread_folder_dialog(self, current_dir: str):
        try:
            folder = QFileDialog.getExistingDirectory(
                self.window() or self,
                "Select Download Directory",
                current_dir or os.path.expanduser("~"),
            )
            self._chosen_folder = folder or ""
        except Exception as e:
            logger.debug(f"Folder dialog error: {e}")
            self._chosen_folder = ""
        finally:
            self._folder_event.set()

    def shutdown(self):
        if self.web_server:
            self.web_server.stop()
