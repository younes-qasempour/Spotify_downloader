import io
import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QImage, QPixmap, QColor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea, QFrame,
    QPlainTextEdit, QApplication
)
from qfluentwidgets import (
    TitleLabel, SubtitleLabel, BodyLabel, CaptionLabel,
    PrimaryPushButton, PushButton, ProgressBar, CardWidget,
    FluentIcon, IconWidget, InfoBar, InfoBarPosition
)
import qrcode

from core.config import config
from sync_server import WifiSyncServerThread, get_local_ip

logger = logging.getLogger("gui.views.sync_view")


class SyncView(QWidget):
    """
    Wi-Fi Sync & Android Pairing View.
    Displays local network address, QR code for instant pairing,
    real-time transfer progress, and connected client status.
    """

    def __init__(self, archive_manager=None, parent=None):
        import secrets
        super().__init__(parent)
        self.setObjectName("sync_view")
        self.archive_manager = archive_manager

        self.port = 8765
        token = config.get("sync.token", "")
        if not token or token == "flacify-lan-sync":
            token = secrets.token_urlsafe(24)
            try:
                config.set("sync.token", token)
            except Exception:
                pass
        self.token = token
        self.current_ip = get_local_ip()
        self.music_dir = config.get("download.output_dir", "downloads")
        self.sync_thread: Optional[WifiSyncServerThread] = None

        self._build_ui()
        if config.get("sync.auto_start", False):
            self.start_server()
        else:
            self.status_badge.setText("Offline (Ready)")

    def _build_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(36, 24, 36, 24)
        main_layout.setSpacing(18)

        # Scroll area for clean responsive layout
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("background: transparent;")

        container = QWidget()
        lay = QVBoxLayout(container)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(20)

        # Header Title
        title_box = QVBoxLayout()
        title_box.setSpacing(4)
        self.title_lbl = TitleLabel("Wi-Fi Sync & Phone Pairing", self)
        self.desc_lbl = BodyLabel(
            "Synchronize your music library, playlists, and synced lyrics bidirectionally with your Android phone "
            "over your local Wi-Fi network without any cloud servers or internet bandwidth.",
            self
        )
        self.desc_lbl.setStyleSheet("color: #AAAAAA;")
        title_box.addWidget(self.title_lbl)
        title_box.addWidget(self.desc_lbl)
        lay.addLayout(title_box)

        # Top Section: Two Columns (Left: Connection & QR Code; Right: Live Status & Progress)
        cols_row = QHBoxLayout()
        cols_row.setSpacing(20)

        # Card 1: QR Code & Connection Info
        self.qr_card = CardWidget(self)
        qr_lay = QVBoxLayout(self.qr_card)
        qr_lay.setContentsMargins(20, 20, 20, 20)
        qr_lay.setSpacing(14)

        qr_header = QHBoxLayout()
        qr_title = SubtitleLabel("Mobile Device Pairing", self.qr_card)
        qr_header.addWidget(qr_title)
        qr_header.addStretch(1)

        self.status_badge = QLabel("Initializing...", self.qr_card)
        self.status_badge.setStyleSheet(
            "background-color: #2D2D2D; color: #CCCCCC; padding: 4px 10px; "
            "border-radius: 12px; font-size: 12px; font-weight: bold;"
        )
        qr_header.addWidget(self.status_badge)
        qr_lay.addLayout(qr_header)

        qr_desc = CaptionLabel(
            "Scan this QR code in the Flacify Android app to auto-pair instantly with this PC.",
            self.qr_card
        )
        qr_desc.setStyleSheet("color: #888888;")
        qr_lay.addWidget(qr_desc)

        # QR Code Image Container
        self.qr_label = QLabel(self.qr_card)
        self.qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.qr_label.setFixedSize(220, 220)
        self.qr_label.setStyleSheet(
            "background-color: #FFFFFF; border-radius: 12px; padding: 8px;"
        )
        qr_box = QHBoxLayout()
        qr_box.addStretch(1)
        qr_box.addWidget(self.qr_label)
        qr_box.addStretch(1)
        qr_lay.addLayout(qr_box)

        # Connection Details
        self.ip_lbl = BodyLabel("LAN IP: Loading...", self.qr_card)
        self.port_lbl = BodyLabel(f"Port: {self.port}", self.qr_card)
        self.mdns_lbl = CaptionLabel("mDNS: _musicsync._tcp.local. (Auto-Discovery Active)", self.qr_card)
        self.mdns_lbl.setStyleSheet("color: #1DB954;")

        qr_lay.addWidget(self.ip_lbl)
        qr_lay.addWidget(self.port_lbl)
        qr_lay.addWidget(self.mdns_lbl)

        # Action Buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        self.toggle_btn = PrimaryPushButton(FluentIcon.PLAY, "Start Server", self.qr_card)
        self.toggle_btn.clicked.connect(self._on_toggle_server)
        self.copy_code_btn = PushButton(FluentIcon.COPY, "Copy Pairing Code", self.qr_card)
        self.copy_code_btn.clicked.connect(self._copy_pairing_code)
        self.open_folder_btn = PushButton(FluentIcon.FOLDER, "Open Music Folder", self.qr_card)
        self.open_folder_btn.clicked.connect(self._open_music_folder)

        btn_row.addWidget(self.toggle_btn, 1)
        btn_row.addWidget(self.copy_code_btn, 1)
        btn_row.addWidget(self.open_folder_btn, 1)
        qr_lay.addLayout(btn_row)

        cols_row.addWidget(self.qr_card, 1)

        # Card 2: Live Activity, Device Connection & Transfer Progress
        self.activity_card = CardWidget(self)
        act_lay = QVBoxLayout(self.activity_card)
        act_lay.setContentsMargins(20, 20, 20, 20)
        act_lay.setSpacing(14)

        act_title = SubtitleLabel("Real-Time Synchronization Status", self.activity_card)
        act_lay.addWidget(act_title)

        self.device_lbl = BodyLabel("Connected Device: No active client connected", self.activity_card)
        self.device_lbl.setStyleSheet("color: #E0E0E0;")
        act_lay.addWidget(self.device_lbl)

        # Current Transfer Progress Card
        progress_box = QVBoxLayout()
        progress_box.setSpacing(6)
        self.transfer_title = CaptionLabel("Ready for incoming sync requests...", self.activity_card)
        self.transfer_title.setStyleSheet("color: #1DB954; font-weight: bold;")
        self.progress_bar = ProgressBar(self.activity_card)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(8)

        progress_box.addWidget(self.transfer_title)
        progress_box.addWidget(self.progress_bar)
        act_lay.addLayout(progress_box)

        # Live Activity Log Area
        act_lay.addWidget(CaptionLabel("Activity History & Transfer Events:", self.activity_card))
        self.log_view = QPlainTextEdit(self.activity_card)
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(1000)
        self.log_view.setStyleSheet(
            "background-color: #181818; color: #BBBBBB; font-family: 'Consolas', 'Courier New', monospace; "
            "font-size: 12px; border-radius: 8px; border: 1px solid #282828; padding: 8px;"
        )
        act_lay.addWidget(self.log_view, 1)

        cols_row.addWidget(self.activity_card, 1)
        lay.addLayout(cols_row)

        scroll.setWidget(container)
        main_layout.addWidget(scroll)

    def start_server(self):
        """Launches the sync server in a background QThread."""
        if self.sync_thread and self.sync_thread.isRunning():
            return

        self.music_dir = config.get("download.output_dir", "downloads")
        self.sync_thread = WifiSyncServerThread(
            music_dir=self.music_dir,
            port=self.port,
            token=self.token,
            archive_manager=self.archive_manager
        )
        self.sync_thread.server_started.connect(self._on_server_started)
        self.sync_thread.server_stopped.connect(self._on_server_stopped)
        self.sync_thread.status_changed.connect(self._on_status_changed)
        self.sync_thread.progress_updated.connect(self._on_progress_updated)
        self.sync_thread.device_connected.connect(self._on_device_connected)
        self.sync_thread.start()

    def stop_server(self):
        """Stops the sync server and unregisters mDNS."""
        if self.sync_thread and self.sync_thread.isRunning():
            self.sync_thread.stop()
            self.sync_thread.wait(3000)

    def _on_toggle_server(self):
        if self.sync_thread and self.sync_thread.isRunning():
            self.toggle_btn.setEnabled(False)
            self.toggle_btn.setText("Stopping...")
            self.status_badge.setText("Stopping...")
            self.status_badge.setStyleSheet(
                "background-color: #331A1A; color: #FF6B6B; padding: 4px 10px; "
                "border-radius: 12px; font-size: 12px; font-weight: bold;"
            )
            self.sync_thread.stop()
        else:
            self.start_server()
            self.toggle_btn.setText("Stop Server")
            self.toggle_btn.setIcon(FluentIcon.PAUSE)

    def _on_server_started(self, ip: str, port: int, token: str):
        self.current_ip = ip
        self.ip_lbl.setText(f"LAN IP: {ip}")
        self.port_lbl.setText(f"Port: {port}")
        self.status_badge.setText("Online (Broadcasting)")
        self.status_badge.setStyleSheet(
            "background-color: #12331C; color: #1DB954; padding: 4px 10px; "
            "border-radius: 12px; font-size: 12px; font-weight: bold;"
        )
        self.toggle_btn.setEnabled(True)
        self.toggle_btn.setText("Stop Server")
        self.toggle_btn.setIcon(FluentIcon.PAUSE)

        # Render QR code
        qr_data = json.dumps({"ip": ip, "port": port, "token": token})
        self._render_qr_code(qr_data)
        self.log_view.appendPlainText(f"[System] Server started on http://{ip}:{port}")

    def _on_server_stopped(self):
        self.status_badge.setText("Offline")
        self.status_badge.setStyleSheet(
            "background-color: #2D2D2D; color: #888888; padding: 4px 10px; "
            "border-radius: 12px; font-size: 12px; font-weight: bold;"
        )
        self.toggle_btn.setEnabled(True)
        self.toggle_btn.setText("Start Server")
        self.toggle_btn.setIcon(FluentIcon.PLAY)
        self.log_view.appendPlainText("[System] Wi-Fi Sync Server stopped.")

    def _on_status_changed(self, message: str):
        self.log_view.appendPlainText(f"[Sync] {message}")

    def _on_progress_updated(self, item_name: str, direction: str, progress: float):
        pct = int(progress * 100)
        self.progress_bar.setValue(pct)
        dir_text = "Sending to phone" if direction == "download" else "Receiving from phone"
        self.transfer_title.setText(f"{dir_text}: {item_name} ({pct}%)")

    def _on_device_connected(self, client_ip: str):
        self.device_lbl.setText(f"Connected Device: Android Client ({client_ip})")
        self.device_lbl.setStyleSheet("color: #1DB954; font-weight: bold;")

    def _render_qr_code(self, data: str):
        try:
            qr = qrcode.QRCode(
                version=1,
                error_correction=qrcode.constants.ERROR_CORRECT_M,
                box_size=5,
                border=1,
            )
            qr.add_data(data)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")

            buf = io.BytesIO()
            img.save(buf, format="PNG")
            buf.seek(0)

            qimg = QImage.fromData(buf.getvalue())
            pixmap = QPixmap.fromImage(qimg)
            self.qr_label.setPixmap(pixmap.scaled(200, 200, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        except Exception as e:
            logger.error(f"Error rendering QR code: {e}")
            self.qr_label.setText("QR Generation Failed")

    def _copy_pairing_code(self):
        ip = getattr(self, "current_ip", None) or get_local_ip()
        pairing_data = json.dumps({"ip": ip, "port": self.port, "token": self.token})
        QApplication.clipboard().setText(pairing_data)
        InfoBar.success(
            title="Pairing Code Copied",
            content="Mobile pairing configuration copied to clipboard.",
            orient=Qt.Orientation.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=3000,
            parent=self
        )

    def _open_music_folder(self):
        music_path = Path(self.music_dir).resolve()
        if not music_path.exists():
            music_path.mkdir(parents=True, exist_ok=True)
        if os.name == 'nt':
            os.startfile(str(music_path))
        else:
            subprocess.Popen(["xdg-open", str(music_path)])

    def shutdown(self):
        self.stop_server()

