import os
import subprocess
import threading
from typing import Optional, Any, Union
from PyQt6.QtCore import Qt, QTimer, QSize, pyqtSignal, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFileDialog, QScrollArea,
    QFrame, QApplication
)
from qfluentwidgets import (
    SubtitleLabel, StrongBodyLabel, BodyLabel, CaptionLabel,
    LineEdit, PrimaryPushButton, PushButton, ToolButton, SwitchButton,
    CardWidget, InfoBar, InfoBarPosition, FluentIcon, Slider, ComboBox, CompactSpinBox,
    MessageBoxBase
)

from core.config import config
from core.musilon import MusilonEngine
from core.melobot import MeloBotEngine
from core.spotify_client import SpotifyClient
from core.utils import ensure_ffmpeg, download_ffmpeg
from gui.styles import (
    BG_CARD, BORDER_SUBTLE, SPOTIFY_EMERALD, TEXT_PRIMARY,
    TEXT_SECONDARY, TEXT_MUTED, STATUS_COLORS
)
from gui.bridge import safe_emit, safe_invoke


class TelegramLoginDialog(MessageBoxBase):
    """Fluent Dialog for authenticating a Telegram account via phone and OTP verification code."""

    sig_send_code_done = pyqtSignal(dict)
    sig_sign_in_done = pyqtSignal(dict)

    def __init__(self, melobot_engine: MeloBotEngine, parent=None):
        super().__init__(parent)
        self.engine = melobot_engine
        self._phone_code_hash = None

        self.titleLabel = SubtitleLabel("Connect Telegram Account", self)
        self.viewLayout.addWidget(self.titleLabel)

        guide_text = (
            "Enter your Telegram phone number with international country code (e.g. +989123456789 or +1...).\n"
            "Telegram will send an official verification code directly to your Telegram app."
        )
        self.guide_label = CaptionLabel(guide_text, self)
        self.guide_label.setTextColor(TEXT_SECONDARY, TEXT_SECONDARY)
        self.guide_label.setWordWrap(True)
        self.viewLayout.addWidget(self.guide_label)

        # Phone Number Input + Send Code Button
        phone_row = QHBoxLayout()
        self.phone_input = LineEdit(self)
        self.phone_input.setPlaceholderText("+989123456789")
        self.phone_input.setText(config.get("telegram.phone", ""))
        self.phone_input.setClearButtonEnabled(True)

        self.send_code_btn = PushButton(FluentIcon.SEND, "Send Code", self)
        self.send_code_btn.setMinimumWidth(110)
        self.send_code_btn.clicked.connect(self._on_send_code_clicked)

        phone_row.addWidget(self.phone_input, 1)
        phone_row.addWidget(self.send_code_btn)
        self.viewLayout.addLayout(phone_row)

        # Verification Code
        self.code_label = CaptionLabel("Enter Verification Code:", self)
        self.code_label.setStyleSheet("font-weight: bold; margin-top: 6px;")
        self.viewLayout.addWidget(self.code_label)

        self.code_input = LineEdit(self)
        self.code_input.setPlaceholderText("5-digit code sent to Telegram")
        self.code_input.setClearButtonEnabled(True)
        self.code_input.textChanged.connect(self._on_code_text_changed)
        self.code_input.returnPressed.connect(self._on_login_clicked)
        self.phone_input.returnPressed.connect(self._on_send_code_clicked)
        self.viewLayout.addWidget(self.code_input)

        # Optional 2FA password
        self.pwd_label = CaptionLabel("Two-Factor (2FA) Cloud Password (if enabled):", self)
        self.pwd_label.setStyleSheet("font-weight: bold; margin-top: 6px;")
        self.pwd_label.setVisible(False)
        self.viewLayout.addWidget(self.pwd_label)

        self.pwd_input = LineEdit(self)
        self.pwd_input.setPlaceholderText("2FA Cloud Password")
        self.pwd_input.setEchoMode(LineEdit.EchoMode.Password)
        self.pwd_input.setVisible(False)
        self.pwd_input.returnPressed.connect(self._on_login_clicked)
        self.viewLayout.addWidget(self.pwd_input)

        # Status feedback label
        self.status_label = CaptionLabel("", self)
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("color: #AAAAAA; font-size: 12px; margin-top: 4px;")
        self.viewLayout.addWidget(self.status_label)

        self.yesButton.setText("Log In")
        self.cancelButton.setText("Cancel")
        self.yesButton.setEnabled(False)
        self.yesButton.clicked.connect(self._on_login_clicked)

        # Connect thread-safe signals
        self.sig_send_code_done.connect(self._on_send_code_done)
        self.sig_sign_in_done.connect(self._on_login_done)

    def validate(self) -> bool:
        """Prevent MessageBoxBase from automatically closing dialog on yesButton click."""
        return False

    def _on_code_text_changed(self, text: str):
        self.yesButton.setEnabled(len(text.strip()) >= 3)

    def _on_send_code_clicked(self):
        phone = self.phone_input.text().strip()
        if not phone:
            self.status_label.setText("Please enter a valid phone number.")
            self.status_label.setStyleSheet("color: #FF5555; font-size: 12px;")
            return

        self.send_code_btn.setEnabled(False)
        self.status_label.setText("Sending verification code to Telegram...")
        self.status_label.setStyleSheet("color: #AAAAAA; font-size: 12px;")

        def worker():
            res = self.engine.send_code(phone)
            safe_emit(self.sig_send_code_done, res)

        threading.Thread(target=worker, daemon=True).start()

    def _on_send_code_done(self, res: dict):
        self.send_code_btn.setEnabled(True)
        if res.get("success"):
            self._phone_code_hash = res.get("phone_code_hash")
            self.status_label.setText("Code sent! Check your Telegram app for the official message.")
            self.status_label.setStyleSheet("color: #1DB954; font-size: 12px;")
            self.code_input.setFocus()
            if len(self.code_input.text().strip()) >= 3:
                self.yesButton.setEnabled(True)
        else:
            err = res.get("error", "Failed to send code.")
            self.status_label.setText(f"Error: {err}")
            self.status_label.setStyleSheet("color: #FF5555; font-size: 12px;")

    def _on_login_clicked(self):
        code = self.code_input.text().strip()
        if not code:
            self.status_label.setText("Please enter the verification code.")
            self.status_label.setStyleSheet("color: #FF5555; font-size: 12px;")
            return

        phone = self.phone_input.text().strip()
        pwd = self.pwd_input.text().strip() if self.pwd_input.isVisible() else None
        self.yesButton.setEnabled(False)
        self.send_code_btn.setEnabled(False)
        self.status_label.setText("Verifying with Telegram...")
        self.status_label.setStyleSheet("color: #AAAAAA; font-size: 12px;")

        def worker():
            res = self.engine.sign_in(
                code=code,
                password=pwd,
                phone_code_hash=self._phone_code_hash,
                phone=phone
            )
            safe_emit(self.sig_sign_in_done, res)

        threading.Thread(target=worker, daemon=True).start()

    def _on_login_done(self, res: dict):
        self.yesButton.setEnabled(True)
        self.send_code_btn.setEnabled(True)
        if res.get("success"):
            user = res.get("user") or {}
            name = user.get("first_name") or user.get("username") or "User"
            self.status_label.setText(f"Success! Logged in as {name}.")
            self.status_label.setStyleSheet("color: #1DB954; font-size: 12px;")
            QTimer.singleShot(600, self.accept)
        elif res.get("needs_password"):
            self.pwd_label.setVisible(True)
            self.pwd_input.setVisible(True)
            self.status_label.setText("Two-Step Verification password is required.")
            self.status_label.setStyleSheet("color: #FFA500; font-size: 12px;")
            self.pwd_input.setFocus()
        else:
            err = res.get("error", "Sign in failed.")
            self.status_label.setText(f"Error: {err}")
            self.status_label.setStyleSheet("color: #FF5555; font-size: 12px;")



class SettingsView(QScrollArea):
    """
    Comprehensive, ultra-reliable Fluent Settings view.
    Fixes layout collapse bugs by using robust standard layouts on CardWidgets.
    Supports:
    - Direct Session Cookie paste & automated credential login for Musilon VIP
    - Real-time connection testing with visual status badges
    - Spotify Web API credentials
    - Folder picker and file naming templates
    - Lyrics & artwork embedding toggles
    - FFmpeg status detection & one-click auto-download
    """

    sig_login_result = pyqtSignal(bool, str)
    sig_test_result = pyqtSignal(bool, bool, bool, str)  # connected, is_authenticated, is_vip, msg
    sig_spotify_result = pyqtSignal(bool, str)
    sig_spotify_auth_result = pyqtSignal(bool, str)
    sig_ffmpeg_progress = pyqtSignal(float, str)
    sig_ffmpeg_finished = pyqtSignal(bool, str)
    sig_tg_status_result = pyqtSignal(bool, str)
    sig_tg_logout_result = pyqtSignal()

    def __init__(
        self,
        musilon_engine: Optional[MusilonEngine] = None,
        melobot_engine: Optional[MeloBotEngine] = None,
        queue_manager: Optional[Any] = None,
        parent=None
    ):
        super().__init__(parent)
        self.qm = queue_manager
        self.setObjectName("settings_view")
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setStyleSheet("QScrollArea { border: none; background-color: transparent; }")

        self.container = QWidget(self)
        self.container.setStyleSheet("background-color: transparent;")
        self.setWidget(self.container)

        self.musilon_engine = musilon_engine or MusilonEngine(
            session_cookie=config.get("musilon.session_cookie", ""),
            username=config.get("musilon.username", ""),
            password=config.get("musilon.password", ""),
            enabled=config.get("musilon.enabled", True)
        )
        self.melobot_engine = melobot_engine or MeloBotEngine(
            api_id=config.get("telegram.api_id", 2040),
            api_hash=config.get("telegram.api_hash", "b18441a1ff607e10a989891a5462e627"),
            bot_username=config.get("telegram.bot_username", "melobot")
        )

        # Connect thread-safe result signals
        self.sig_login_result.connect(self._on_login_finished)
        self.sig_test_result.connect(self._on_test_finished)
        self.sig_spotify_result.connect(self._on_spotify_valid)
        self.sig_spotify_auth_result.connect(self._on_spotify_auth_done)
        self.sig_ffmpeg_progress.connect(self._on_ffmpeg_progress)
        self.sig_ffmpeg_finished.connect(self._on_ffmpeg_finished)
        self.sig_tg_status_result.connect(self._on_tg_status_done)
        self.sig_tg_logout_result.connect(self._on_tg_logout_done)

        self._init_ui()

    def _init_ui(self):
        main_layout = QVBoxLayout(self.container)
        main_layout.setContentsMargins(28, 24, 28, 40)
        main_layout.setSpacing(24)

        # Page Header
        page_title = SubtitleLabel("Settings & Preferences", self.container)
        main_layout.addWidget(page_title)

        # =====================================================================
        # 0. High-Quality Audio Source Selection
        # =====================================================================
        main_layout.addWidget(StrongBodyLabel("High-Quality Audio Engine Selection", self.container))

        source_card = CardWidget(self.container)
        sc_layout = QVBoxLayout(source_card)
        sc_layout.setContentsMargins(20, 18, 20, 20)
        sc_layout.setSpacing(12)

        sc_row = QHBoxLayout()
        sc_info = QVBoxLayout()
        sc_title = BodyLabel("Primary High-Quality Download Source", source_card)
        sc_title.setStyleSheet("font-weight: bold;")
        sc_desc = CaptionLabel(
            "Select which service to use for Lossless FLAC & 320 kbps MP3. "
            "If a song is not found in the selected source, Flacify automatically falls back to YouTube Music.",
            source_card
        )
        sc_desc.setTextColor(TEXT_SECONDARY, TEXT_SECONDARY)
        sc_desc.setWordWrap(True)
        sc_info.addWidget(sc_title)
        sc_info.addWidget(sc_desc)

        self.source_combo = ComboBox(source_card)
        self.source_combo.addItems([
            "👑 Musilon VIP / Premium CDN",
            "✈️ MeloBot Premium (@melobot Telegram)"
        ])
        current_engine = str(config.get("source_engine", "musilon")).lower()
        if current_engine == "melobot" or (config.get("telegram.enabled", False) and not config.get("musilon.enabled", True)):
            self.source_combo.setCurrentIndex(1)
        else:
            self.source_combo.setCurrentIndex(0)

        self.source_combo.currentIndexChanged.connect(self._on_source_engine_changed)
        self.source_combo.setMinimumWidth(280)

        sc_row.addLayout(sc_info, 1)
        sc_row.addWidget(self.source_combo)
        sc_layout.addLayout(sc_row)

        main_layout.addWidget(source_card)

        # =====================================================================
        # 1. Musilon VIP Account Section
        # =====================================================================
        main_layout.addWidget(StrongBodyLabel("Musilon VIP / Premium Account", self.container))

        musilon_card = CardWidget(self.container)
        m_layout = QVBoxLayout(musilon_card)
        m_layout.setContentsMargins(20, 18, 20, 20)
        m_layout.setSpacing(14)

        # Status Header Row
        status_row = QHBoxLayout()
        m_icon = BodyLabel("👑", musilon_card)
        m_icon.setStyleSheet("font-size: 18px;")
        m_title = BodyLabel("VIP Authentication & Session Token", musilon_card)
        m_title.setStyleSheet("font-weight: bold; font-size: 14px;")

        self.status_badge = CaptionLabel("Checking...", musilon_card)
        self.status_badge.setStyleSheet(
            "background-color: #333333; color: #AAAAAA; padding: 3px 10px; border-radius: 10px;"
        )

        status_row.addWidget(m_icon)
        status_row.addWidget(m_title)
        status_row.addStretch(1)
        status_row.addWidget(self.status_badge)
        m_layout.addLayout(status_row)

        desc = CaptionLabel(
            "Enter your authenticated Musilon VIP session cookies to unlock Lossless FLAC 16-bit, "
            "Hi-Res FLAC 24-bit, and 320 kbps MP3 downloads directly from the high-speed CDN.",
            musilon_card
        )
        desc.setTextColor(TEXT_SECONDARY, TEXT_SECONDARY)
        desc.setWordWrap(True)
        m_layout.addWidget(desc)

        # Account Credentials (Primary Login)
        cred_label = CaptionLabel("Musilon Account Credentials (Email & Password):", musilon_card)
        cred_label.setStyleSheet("font-weight: bold;")
        m_layout.addWidget(cred_label)

        # Clean side-by-side credentials inputs
        inputs_layout = QHBoxLayout()
        inputs_layout.setSpacing(12)

        self.user_input = LineEdit(musilon_card)
        self.user_input.setPlaceholderText("Registered Email Address (e.g. name@gmail.com)")
        self.user_input.setText(config.get("musilon.username", ""))
        self.user_input.setClearButtonEnabled(True)
        self.user_input.textChanged.connect(self._on_user_changed)

        self.pwd_input = LineEdit(musilon_card)
        self.pwd_input.setPlaceholderText("Password")
        self.pwd_input.setEchoMode(LineEdit.EchoMode.Password)
        self.pwd_input.setText(config.get("musilon.password", ""))
        self.pwd_input.setClearButtonEnabled(True)
        self.pwd_input.textChanged.connect(self._on_pwd_changed)

        inputs_layout.addWidget(self.user_input, 1)
        inputs_layout.addWidget(self.pwd_input, 1)
        m_layout.addLayout(inputs_layout)

        # Action Buttons Row (Log In + Test Connection)
        action_btn_row = QHBoxLayout()
        action_btn_row.setSpacing(10)

        self.login_btn = PrimaryPushButton(FluentIcon.PEOPLE, "Log In", musilon_card)
        self.login_btn.setMinimumWidth(110)
        self.login_btn.clicked.connect(self._login_musilon)

        self.test_btn = PushButton(FluentIcon.SYNC, "Test Connection && VIP Status", musilon_card)
        self.test_btn.setMinimumWidth(190)
        self.test_btn.clicked.connect(self._test_musilon)

        action_btn_row.addWidget(self.login_btn)
        action_btn_row.addWidget(self.test_btn)
        action_btn_row.addStretch(1)
        m_layout.addLayout(action_btn_row)

        # Diagnostics & Status Banner (Dedicated Box with setWordWrap(True))
        self.result_container = QFrame(musilon_card)
        self.result_container.setStyleSheet(
            "background-color: rgba(255, 255, 255, 0.04); "
            "border: 1px solid #333333; border-radius: 6px; padding: 8px 12px;"
        )
        rc_layout = QHBoxLayout(self.result_container)
        rc_layout.setContentsMargins(8, 6, 8, 6)
        rc_layout.setSpacing(8)

        rc_icon = CaptionLabel("ℹ️", self.result_container)
        self.result_label = CaptionLabel("Ready to test connection.", self.result_container)
        self.result_label.setWordWrap(True)
        self.result_label.setStyleSheet("font-size: 12px; color: #CCCCCC;")

        rc_layout.addWidget(rc_icon, 0, Qt.AlignmentFlag.AlignTop)
        rc_layout.addWidget(self.result_label, 1)
        m_layout.addWidget(self.result_container)

        # Advanced / Session Cookie Section
        cookie_label = CaptionLabel("Advanced: Session Cookie (Optional / Auto-Saved on Login):", musilon_card)
        cookie_label.setStyleSheet("font-weight: bold; color: #888888;")
        m_layout.addWidget(cookie_label)

        cookie_row = QHBoxLayout()
        cookie_row.setSpacing(8)

        self.cookie_input = LineEdit(musilon_card)
        self.cookie_input.setPlaceholderText("Optional: __arcsjs=...; __Secure-next-auth.session-token=...")
        self.cookie_input.setText(config.get("musilon.session_cookie", ""))
        self.cookie_input.setClearButtonEnabled(True)
        self.cookie_input.textChanged.connect(self._on_cookie_changed)

        self.paste_cookie_btn = PushButton(FluentIcon.PASTE, "Paste", musilon_card)
        self.paste_cookie_btn.setFixedWidth(90)
        self.paste_cookie_btn.clicked.connect(self._paste_cookie)

        cookie_row.addWidget(self.cookie_input, 1)
        cookie_row.addWidget(self.paste_cookie_btn)
        m_layout.addLayout(cookie_row)

        # Instructions Helper Card
        guide_card = QFrame(musilon_card)
        guide_card.setStyleSheet("background-color: #202020; border-radius: 8px; padding: 8px;")
        g_layout = QVBoxLayout(guide_card)
        g_layout.setContentsMargins(12, 10, 12, 10)
        g_layout.setSpacing(4)

        guide_title = CaptionLabel("💡 How to copy session cookies from your browser:", guide_card)
        guide_title.setStyleSheet("font-weight: bold; color: #1DB954;")
        guide_step1 = CaptionLabel("1. Open https://open.musilon.com in Chrome or Edge and log in to your account.", guide_card)
        guide_step1.setWordWrap(True)
        guide_step2 = CaptionLabel("2. You can log in directly using your email and password above for automated session renewal.", guide_card)
        guide_step2.setWordWrap(True)
        guide_step3 = CaptionLabel("3. Or copy manually: Press F12 → Application → Cookies → copy `__Secure-next-auth.session-token`.", guide_card)
        guide_step3.setWordWrap(True)

        g_layout.addWidget(guide_title)
        g_layout.addWidget(guide_step1)
        g_layout.addWidget(guide_step2)
        g_layout.addWidget(guide_step3)
        m_layout.addWidget(guide_card)

        # Musilon Engine Toggle Row
        toggle_row = QHBoxLayout()
        toggle_info = QVBoxLayout()
        toggle_title = BodyLabel("Enable Musilon Tier 1-3 Engine", musilon_card)
        toggle_title.setStyleSheet("font-weight: bold;")
        toggle_desc = CaptionLabel("When active, tracks are searched on Musilon before falling back to YouTube Music.", musilon_card)
        toggle_desc.setTextColor(TEXT_SECONDARY, TEXT_SECONDARY)
        toggle_desc.setWordWrap(True)
        toggle_info.addWidget(toggle_title)
        toggle_info.addWidget(toggle_desc)

        self.musilon_switch = SwitchButton(musilon_card)
        self.musilon_switch.setChecked(config.get("musilon.enabled", True))
        self.musilon_switch.checkedChanged.connect(self._on_musilon_switch_changed)

        toggle_row.addLayout(toggle_info, 1)
        toggle_row.addWidget(self.musilon_switch)
        m_layout.addLayout(toggle_row)

        # VIP Stealth Rate-Limit Shield (Safe Mode) Toggle Row
        safe_mode_row = QHBoxLayout()
        safe_mode_info = QVBoxLayout()
        safe_mode_title = BodyLabel("VIP Anti-Ban Stealth Shield (Safe Mode)", musilon_card)
        safe_mode_title.setStyleSheet("font-weight: bold;")
        safe_mode_desc = CaptionLabel(
            "Protects your VIP account against 429 rate-limit blocks by enforcing single-stream connection, "
            "authentic station referer headers, and human cooldown intervals between songs.",
            musilon_card
        )
        safe_mode_desc.setTextColor(TEXT_SECONDARY, TEXT_SECONDARY)
        safe_mode_desc.setWordWrap(True)
        safe_mode_info.addWidget(safe_mode_title)
        safe_mode_info.addWidget(safe_mode_desc)

        self.safe_mode_switch = SwitchButton(musilon_card)
        self.safe_mode_switch.setChecked(config.get("musilon.safe_mode", True))
        self.safe_mode_switch.checkedChanged.connect(self._on_safe_mode_changed)

        safe_mode_row.addLayout(safe_mode_info, 1)
        safe_mode_row.addWidget(self.safe_mode_switch)
        m_layout.addLayout(safe_mode_row)

        # Cooldown Duration Settings Row
        cooldown_row = QHBoxLayout()
        cooldown_info = QVBoxLayout()
        cooldown_title = CaptionLabel("Musilon Song Download Cooldown (Seconds):", musilon_card)
        cooldown_title.setStyleSheet("font-weight: bold;")
        cooldown_desc = CaptionLabel("Randomized pause between min and max seconds mimics human listening and evades bot detection.", musilon_card)
        cooldown_desc.setTextColor(TEXT_SECONDARY, TEXT_SECONDARY)
        cooldown_desc.setWordWrap(True)
        cooldown_info.addWidget(cooldown_title)
        cooldown_info.addWidget(cooldown_desc)

        spin_box_layout = QHBoxLayout()
        spin_box_layout.setSpacing(10)

        min_lbl = CaptionLabel("Min:", musilon_card)
        self.cooldown_min_spin = CompactSpinBox(musilon_card)
        self.cooldown_min_spin.setRange(0, 300)
        self.cooldown_min_spin.setValue(int(config.get("musilon.cooldown_min_sec", 15)))
        self.cooldown_min_spin.setFixedWidth(95)
        self.cooldown_min_spin.valueChanged.connect(self._on_cooldown_min_changed)

        max_lbl = CaptionLabel("Max:", musilon_card)
        self.cooldown_max_spin = CompactSpinBox(musilon_card)
        self.cooldown_max_spin.setRange(0, 300)
        self.cooldown_max_spin.setValue(int(config.get("musilon.cooldown_max_sec", 35)))
        self.cooldown_max_spin.setFixedWidth(95)
        self.cooldown_max_spin.valueChanged.connect(self._on_cooldown_max_changed)

        spin_box_layout.addWidget(min_lbl)
        spin_box_layout.addWidget(self.cooldown_min_spin)
        spin_box_layout.addWidget(max_lbl)
        spin_box_layout.addWidget(self.cooldown_max_spin)

        cooldown_row.addLayout(cooldown_info, 1)
        cooldown_row.addLayout(spin_box_layout)
        m_layout.addLayout(cooldown_row)

        main_layout.addWidget(musilon_card)

        # =====================================================================
        # 1b. MeloBot VIP (Telegram Bot @melobot) Section
        # =====================================================================
        main_layout.addWidget(StrongBodyLabel("MeloBot VIP / Telegram Account", self.container))

        melobot_card = CardWidget(self.container)
        mb_layout = QVBoxLayout(melobot_card)
        mb_layout.setContentsMargins(20, 18, 20, 20)
        mb_layout.setSpacing(14)

        # Status Header Row
        mb_status_row = QHBoxLayout()
        mb_icon = BodyLabel("✈️", melobot_card)
        mb_icon.setStyleSheet("font-size: 18px;")
        mb_title = BodyLabel("MeloBot Account & Telegram Connection", melobot_card)
        mb_title.setStyleSheet("font-weight: bold; font-size: 14px;")

        self.tg_status_badge = CaptionLabel("Checking...", melobot_card)
        self.tg_status_badge.setStyleSheet(
            "background-color: #333333; color: #AAAAAA; padding: 3px 10px; border-radius: 10px;"
        )

        mb_status_row.addWidget(mb_icon)
        mb_status_row.addWidget(mb_title)
        mb_status_row.addStretch(1)
        mb_status_row.addWidget(self.tg_status_badge)
        mb_layout.addLayout(mb_status_row)

        mb_desc = CaptionLabel(
            "Connect your Telegram account to search and download directly from @melobot with your MeloBot Premium subscription. "
            "Tracks are fetched in Lossless FLAC or highest 320 kbps MP3 quality. Telegram credentials are pre-configured.",
            melobot_card
        )
        mb_desc.setTextColor(TEXT_SECONDARY, TEXT_SECONDARY)
        mb_desc.setWordWrap(True)
        mb_layout.addWidget(mb_desc)

        # Action Buttons Row (Connect Account + Disconnect + Check Status)
        mb_btn_row = QHBoxLayout()
        mb_btn_row.setSpacing(10)

        self.tg_connect_btn = PrimaryPushButton(FluentIcon.PEOPLE, "Connect Telegram Account", melobot_card)
        self.tg_connect_btn.setMinimumWidth(210)
        self.tg_connect_btn.clicked.connect(self._open_telegram_login)

        self.tg_check_btn = PushButton(FluentIcon.SYNC, "Check Status", melobot_card)
        self.tg_check_btn.setMinimumWidth(130)
        self.tg_check_btn.clicked.connect(self._check_telegram_status)

        self.tg_logout_btn = PushButton(FluentIcon.DELETE, "Log Out / Disconnect", melobot_card)
        self.tg_logout_btn.setMinimumWidth(170)
        self.tg_logout_btn.clicked.connect(self._logout_telegram)

        mb_btn_row.addWidget(self.tg_connect_btn)
        mb_btn_row.addWidget(self.tg_check_btn)
        mb_btn_row.addWidget(self.tg_logout_btn)
        mb_btn_row.addStretch(1)
        mb_layout.addLayout(mb_btn_row)

        # MeloBot Toggle Row
        mb_toggle_row = QHBoxLayout()
        mb_toggle_info = QVBoxLayout()
        mb_toggle_title = BodyLabel("Enable MeloBot Telegram Engine", melobot_card)
        mb_toggle_title.setStyleSheet("font-weight: bold;")
        mb_toggle_desc = CaptionLabel("When active, tracks are queried from @melobot using your connected Telegram account.", melobot_card)
        mb_toggle_desc.setTextColor(TEXT_SECONDARY, TEXT_SECONDARY)
        mb_toggle_desc.setWordWrap(True)
        mb_toggle_info.addWidget(mb_toggle_title)
        mb_toggle_info.addWidget(mb_toggle_desc)

        self.melobot_switch = SwitchButton(melobot_card)
        self.melobot_switch.setChecked(config.get("telegram.enabled", False) or config.get("source_engine") == "melobot")
        self.melobot_switch.checkedChanged.connect(self._on_melobot_switch_changed)

        mb_toggle_row.addLayout(mb_toggle_info, 1)
        mb_toggle_row.addWidget(self.melobot_switch)
        mb_layout.addLayout(mb_toggle_row)

        # Telegram Safe Delay Row
        delay_row = QHBoxLayout()
        delay_info = QVBoxLayout()
        delay_title = CaptionLabel("Telegram Request Delay (Seconds):", melobot_card)
        delay_title.setStyleSheet("font-weight: bold;")
        delay_desc = CaptionLabel("Polite pause between songs to prevent bot flood limits.", melobot_card)
        delay_desc.setTextColor(TEXT_SECONDARY, TEXT_SECONDARY)
        delay_info.addWidget(delay_title)
        delay_info.addWidget(delay_desc)

        self.tg_delay_spin = CompactSpinBox(melobot_card)
        self.tg_delay_spin.setRange(0, 30)
        self.tg_delay_spin.setValue(int(config.get("telegram.safe_delay_sec", 2)))
        self.tg_delay_spin.setFixedWidth(95)
        self.tg_delay_spin.valueChanged.connect(lambda val: (config.set("telegram.safe_delay_sec", val), config.save()))

        delay_row.addLayout(delay_info, 1)
        delay_row.addWidget(self.tg_delay_spin)
        mb_layout.addLayout(delay_row)

        main_layout.addWidget(melobot_card)

        # =====================================================================
        # 2. Spotify Metadata Credentials Section
        # =====================================================================
        sp_header_row = QHBoxLayout()
        sp_header_row.addWidget(StrongBodyLabel("Spotify Metadata Credentials", self.container))
        sp_header_row.addStretch(1)
        self.sp_status_badge = CaptionLabel(self.container)
        sp_header_row.addWidget(self.sp_status_badge)
        main_layout.addLayout(sp_header_row)

        spotify_card = CardWidget(self.container)
        s_layout = QVBoxLayout(spotify_card)
        s_layout.setContentsMargins(20, 18, 20, 20)
        s_layout.setSpacing(12)

        s_desc = CaptionLabel(
            "Spotify Developer Client ID & Secret for official Web API metadata extraction with full pagination.\n"
            "• Required to download or save playlists with more than 100 tracks (guest embed mode is capped by Spotify at 100 songs max).\n"
            "• Since late 2024, Spotify requires a 1-time user account login to fetch playlist tracks beyond 100 songs.\n"
            "• Setup: In developer.spotify.com/dashboard, set Redirect URI to http://127.0.0.1:9900/callback, paste keys below, then click 'Authorize Spotify Account'.",
            spotify_card
        )
        s_desc.setTextColor(TEXT_SECONDARY, TEXT_SECONDARY)
        s_desc.setWordWrap(True)
        s_layout.addWidget(s_desc)

        s_btn_row = QHBoxLayout()
        self.open_sp_dash_btn = PushButton(FluentIcon.LINK, "Open Spotify Developer Dashboard", spotify_card)
        self.open_sp_dash_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://developer.spotify.com/dashboard")))
        s_btn_row.addWidget(self.open_sp_dash_btn)
        s_btn_row.addStretch(1)
        s_layout.addLayout(s_btn_row)

        s_inputs = QHBoxLayout()
        s_inputs.setSpacing(10)

        self.spotify_id = LineEdit(spotify_card)
        self.spotify_id.setPlaceholderText("Spotify Client ID")
        self.spotify_id.setText(config.get("spotify.client_id", ""))
        self.spotify_id.textChanged.connect(self._on_sp_id_changed)

        self.spotify_secret = LineEdit(spotify_card)
        self.spotify_secret.setPlaceholderText("Spotify Client Secret")
        self.spotify_secret.setEchoMode(LineEdit.EchoMode.Password)
        self.spotify_secret.setText(config.get("spotify.client_secret", ""))
        self.spotify_secret.textChanged.connect(self._on_sp_sec_changed)

        self.validate_sp_btn = PushButton(FluentIcon.SEND, "Validate Keys", spotify_card)
        self.validate_sp_btn.clicked.connect(self._validate_spotify)

        self.auth_sp_btn = PrimaryPushButton(FluentIcon.PEOPLE, "Authorize Spotify Account", spotify_card)
        self.auth_sp_btn.clicked.connect(self._authorize_spotify)

        s_inputs.addWidget(self.spotify_id, 1)
        s_inputs.addWidget(self.spotify_secret, 1)
        s_inputs.addWidget(self.validate_sp_btn)
        s_inputs.addWidget(self.auth_sp_btn)
        s_layout.addLayout(s_inputs)

        main_layout.addWidget(spotify_card)
        self._update_spotify_badge()

        # =====================================================================
        # 3. Download & Organization Section
        # =====================================================================
        main_layout.addWidget(StrongBodyLabel("Download & Organization", self.container))

        down_card = CardWidget(self.container)
        d_layout = QVBoxLayout(down_card)
        d_layout.setContentsMargins(20, 18, 20, 20)
        d_layout.setSpacing(14)

        # Output Folder Row
        folder_label = CaptionLabel("Download Output Directory:", down_card)
        folder_label.setStyleSheet("font-weight: bold;")
        d_layout.addWidget(folder_label)

        f_row = QHBoxLayout()
        f_row.setSpacing(8)

        self.folder_input = LineEdit(down_card)
        self.folder_input.setText(config.get("download.output_dir", ""))
        self.folder_input.textChanged.connect(lambda t: config.set("download.output_dir", t))

        self.browse_btn = PushButton(FluentIcon.FOLDER, "Browse...", down_card)
        self.browse_btn.clicked.connect(self._browse_folder)

        self.open_folder_btn = ToolButton(FluentIcon.SEND, down_card)
        self.open_folder_btn.setToolTip("Open Folder in Explorer")
        self.open_folder_btn.clicked.connect(self._open_folder)

        f_row.addWidget(self.folder_input, 1)
        f_row.addWidget(self.browse_btn)
        f_row.addWidget(self.open_folder_btn)
        d_layout.addLayout(f_row)

        # Naming Pattern Row (Playlists & Singles)
        name_label = CaptionLabel("Playlist & Single Naming Pattern:", down_card)
        name_label.setStyleSheet("font-weight: bold;")
        d_layout.addWidget(name_label)

        n_row = QHBoxLayout()
        self.naming_input = LineEdit(down_card)
        self.naming_input.setText(config.get("download.naming_template", "{artist} - {title}"))
        self.naming_input.textChanged.connect(lambda t: config.set("download.naming_template", t))
        n_desc = CaptionLabel("Tags: {artist}, {title}, {album}", down_card)
        n_desc.setTextColor(TEXT_MUTED, TEXT_MUTED)

        n_row.addWidget(self.naming_input, 1)
        n_row.addWidget(n_desc)
        d_layout.addLayout(n_row)

        # Album Naming Pattern Row
        album_name_label = CaptionLabel("Album Naming Pattern:", down_card)
        album_name_label.setStyleSheet("font-weight: bold;")
        d_layout.addWidget(album_name_label)

        an_row = QHBoxLayout()
        self.album_naming_input = LineEdit(down_card)
        self.album_naming_input.setText(config.get("download.album_naming_template", "{track_num}. {artist} - {title}"))
        self.album_naming_input.textChanged.connect(lambda t: config.set("download.album_naming_template", t))
        an_desc = CaptionLabel("Tags: {track_num}, {artist}, {title}, {album}", down_card)
        an_desc.setTextColor(TEXT_MUTED, TEXT_MUTED)

        an_row.addWidget(self.album_naming_input, 1)
        an_row.addWidget(an_desc)
        d_layout.addLayout(an_row)

        # Organize into Subfolders Switch Row
        subfolder_row = QHBoxLayout()
        subfolder_info = QVBoxLayout()
        subfolder_title = BodyLabel("Organize Downloads into Subfolders", down_card)
        subfolder_title.setStyleSheet("font-weight: bold;")
        subfolder_desc = CaptionLabel(
            "When enabled, saves songs into subfolders named after their playlist or album. "
            "When disabled (Default), saves all downloaded songs directly into your main output folder.",
            down_card
        )
        subfolder_desc.setTextColor(TEXT_SECONDARY, TEXT_SECONDARY)
        subfolder_desc.setWordWrap(True)
        subfolder_info.addWidget(subfolder_title)
        subfolder_info.addWidget(subfolder_desc)

        self.subfolder_switch = SwitchButton(down_card)
        self.subfolder_switch.setChecked(config.get("download.save_in_subfolders", False))
        self.subfolder_switch.checkedChanged.connect(self._on_subfolder_switch_changed)

        subfolder_row.addLayout(subfolder_info, 1)
        subfolder_row.addWidget(self.subfolder_switch)
        d_layout.addLayout(subfolder_row)

        # Concurrent Downloads & Searches Row
        concurrency_row = QHBoxLayout()
        concurrency_info = QVBoxLayout()
        concurrency_title = BodyLabel("Concurrent Downloads & Searches", down_card)
        concurrency_title.setStyleSheet("font-weight: bold;")
        self.concurrency_desc = CaptionLabel(
            "Number of simultaneous songs to search and download in parallel (Default: 5). "
            "Parallel resolution prevents searches from blocking subsequent songs in the queue.",
            down_card
        )
        self.concurrency_desc.setTextColor(TEXT_SECONDARY, TEXT_SECONDARY)
        self.concurrency_desc.setWordWrap(True)
        concurrency_info.addWidget(concurrency_title)
        concurrency_info.addWidget(self.concurrency_desc)

        self.concurrency_spin = CompactSpinBox(down_card)
        self.concurrency_spin.setRange(1, 10)
        self.concurrency_spin.setValue(int(config.get("download.concurrency", 5)))
        self.concurrency_spin.valueChanged.connect(self._on_concurrency_changed)

        concurrency_row.addLayout(concurrency_info, 1)
        concurrency_row.addWidget(self.concurrency_spin)
        d_layout.addLayout(concurrency_row)

        # Preferred Audio Quality Row
        qual_row = QHBoxLayout()
        qual_info = QVBoxLayout()
        qual_title = BodyLabel("Preferred Download Audio Quality", down_card)
        qual_title.setStyleSheet("font-weight: bold;")
        qual_desc = CaptionLabel(
            "Select preferred format from Musilon. If unavailable, falls back gracefully to next highest tier.",
            down_card
        )
        qual_desc.setTextColor(TEXT_SECONDARY, TEXT_SECONDARY)
        qual_desc.setWordWrap(True)
        qual_info.addWidget(qual_title)
        qual_info.addWidget(qual_desc)

        self.quality_combo = ComboBox(down_card)
        self.quality_combo.addItems([
            "MP3 320 kbps (High Quality MP3 - Default)",
            "Lossless FLAC (16-bit CD / 24-bit Hi-Res)"
        ])
        current_pref = str(config.get("download.preferred_quality", "320")).strip().lower()
        self.quality_combo.setCurrentIndex(0 if current_pref in ("320", "mp3", "320k", "mp3_320") else 1)
        self.quality_combo.currentIndexChanged.connect(self._on_quality_changed)

        qual_row.addLayout(qual_info, 1)
        qual_row.addWidget(self.quality_combo)
        d_layout.addLayout(qual_row)

        # Target Audio Format (Universal Transcoder) Row
        target_fmt_row = QHBoxLayout()
        target_fmt_info = QVBoxLayout()
        target_fmt_title = BodyLabel("Target Audio Format (Universal Transcoder)", down_card)
        target_fmt_title.setStyleSheet("font-weight: bold;")
        target_fmt_desc = CaptionLabel(
            "Auto-transcodes downloaded audio to your preferred format via FFmpeg. "
            "Keep as 'Original' to retain pristine native audio streams (fastest).",
            down_card
        )
        target_fmt_desc.setTextColor(TEXT_SECONDARY, TEXT_SECONDARY)
        target_fmt_desc.setWordWrap(True)
        target_fmt_info.addWidget(target_fmt_title)
        target_fmt_info.addWidget(target_fmt_desc)

        self.target_fmt_combo = ComboBox(down_card)
        self.target_fmt_combo.addItems([
            "Original / Native Stream (Default)",
            "Apple Lossless (ALAC .m4a — iPhone & Apple Music)",
            "MP3 320 kbps CBR (Universal / Car Stereos)",
            "FLAC 16/24-bit (Lossless Audio)",
            "Opus 256 kbps (High Efficiency)"
        ])
        fmt_map = {"original": 0, "alac": 1, "mp3": 2, "flac": 3, "opus": 4}
        current_fmt = str(config.get("download.target_format", "original")).strip().lower()
        self.target_fmt_combo.setCurrentIndex(fmt_map.get(current_fmt, 0))
        self.target_fmt_combo.currentIndexChanged.connect(self._on_target_format_changed)

        target_fmt_row.addLayout(target_fmt_info, 1)
        target_fmt_row.addWidget(self.target_fmt_combo)
        d_layout.addLayout(target_fmt_row)

        # Safety-Net Fallback Switch Row
        fb_row = QHBoxLayout()
        fb_info = QVBoxLayout()
        fb_title = BodyLabel("Enable YouTube Music Safety-Net Fallback", down_card)
        fb_title.setStyleSheet("font-weight: bold;")
        fb_desc = CaptionLabel(
            "Activates high-bitrate Opus via YouTube Music strictly when a track cannot be found on Musilon "
            "after exhaustive multi-vector catalog search.",
            down_card
        )
        fb_desc.setTextColor(TEXT_SECONDARY, TEXT_SECONDARY)
        fb_desc.setWordWrap(True)
        fb_info.addWidget(fb_title)
        fb_info.addWidget(fb_desc)

        self.fallback_switch = SwitchButton(down_card)
        self.fallback_switch.setChecked(config.get("download.allow_fallback", True))
        self.fallback_switch.checkedChanged.connect(self._on_fallback_switch_changed)

        fb_row.addLayout(fb_info, 1)
        fb_row.addWidget(self.fallback_switch)
        d_layout.addLayout(fb_row)

        # YouTube Cookies Row
        yt_cookie_label = CaptionLabel("YouTube Cookies File (cookies.txt):", down_card)
        yt_cookie_label.setStyleSheet("font-weight: bold;")
        d_layout.addWidget(yt_cookie_label)

        yt_cookie_row = QHBoxLayout()
        yt_cookie_row.setSpacing(8)

        self.yt_cookie_input = LineEdit(down_card)
        self.yt_cookie_input.setPlaceholderText("Path to cookies.txt (or place cookies.txt in app folder)")
        self.yt_cookie_input.setText(config.get("download.cookies_file", ""))
        self.yt_cookie_input.textChanged.connect(lambda t: config.set("download.cookies_file", t.strip()))

        self.yt_cookie_browse_btn = PushButton(FluentIcon.DOCUMENT, "Browse...", down_card)
        self.yt_cookie_browse_btn.clicked.connect(self._browse_cookies_file)

        yt_cookie_row.addWidget(self.yt_cookie_input, 1)
        yt_cookie_row.addWidget(self.yt_cookie_browse_btn)
        d_layout.addLayout(yt_cookie_row)

        # YouTube Cookies Guide Card
        yt_guide_card = QFrame(down_card)
        yt_guide_card.setStyleSheet("background-color: #202020; border-radius: 8px; padding: 8px;")
        yt_g_layout = QVBoxLayout(yt_guide_card)
        yt_g_layout.setContentsMargins(12, 10, 12, 10)
        yt_g_layout.setSpacing(4)

        yt_guide_title = CaptionLabel("💡 How to fix YouTube bot blocks with cookies.txt:", yt_guide_card)
        yt_guide_title.setStyleSheet("font-weight: bold; color: #1DB954;")
        yt_guide_step1 = CaptionLabel("1. Install 'Get cookies.txt LOCALLY' extension in Chrome, Edge, or Firefox.", yt_guide_card)
        yt_guide_step1.setWordWrap(True)
        yt_guide_step2 = CaptionLabel("2. Open youtube.com and ensure you are logged into your Google account.", yt_guide_card)
        yt_guide_step2.setWordWrap(True)
        yt_guide_step3 = CaptionLabel("3. Click the extension icon and click 'Export As cookies.txt'.", yt_guide_card)
        yt_guide_step3.setWordWrap(True)
        yt_guide_step4 = CaptionLabel("4. Select the exported file via 'Browse...' above (or save it as 'cookies.txt' in the app folder).", yt_guide_card)
        yt_guide_step4.setWordWrap(True)

        yt_g_layout.addWidget(yt_guide_title)
        yt_g_layout.addWidget(yt_guide_step1)
        yt_g_layout.addWidget(yt_guide_step2)
        yt_g_layout.addWidget(yt_guide_step3)
        yt_g_layout.addWidget(yt_guide_step4)
        d_layout.addWidget(yt_guide_card)

        # YouTube / Network Proxy Row
        proxy_label = CaptionLabel("Network Proxy (Optional):", down_card)
        proxy_label.setStyleSheet("font-weight: bold;")
        d_layout.addWidget(proxy_label)

        p_row = QHBoxLayout()
        self.proxy_input = LineEdit(down_card)
        self.proxy_input.setPlaceholderText("e.g. http://127.0.0.1:10809 or socks5://127.0.0.1:10808")
        self.proxy_input.setText(config.get("download.proxy", ""))
        self.proxy_input.textChanged.connect(lambda t: config.set("download.proxy", t.strip()))

        p_desc = CaptionLabel("Optional proxy for YouTube requests. Leave empty for direct connection.", down_card)
        p_desc.setTextColor(TEXT_MUTED, TEXT_MUTED)
        p_desc.setWordWrap(True)

        p_row.addWidget(self.proxy_input, 1)
        p_row.addWidget(p_desc)
        d_layout.addLayout(p_row)

        # Library Clean & Repair Row
        clean_row = QHBoxLayout()
        clean_info = QVBoxLayout()
        clean_title = BodyLabel("Clean Library & Purge Corrupted Files", down_card)
        clean_title.setStyleSheet("font-weight: bold;")
        clean_desc = CaptionLabel(
            "Purges unplayable HTML files (<500KB), relocates cover artwork to cache, and removes marker files.",
            down_card
        )
        clean_desc.setTextColor(TEXT_SECONDARY, TEXT_SECONDARY)
        clean_desc.setWordWrap(True)
        clean_info.addWidget(clean_title)
        clean_info.addWidget(clean_desc)

        self.clean_lib_top_btn = PushButton(FluentIcon.DELETE, "Clean Library", down_card)
        self.clean_lib_top_btn.clicked.connect(self._clean_library)

        clean_row.addLayout(clean_info, 1)
        clean_row.addWidget(self.clean_lib_top_btn)
        d_layout.addLayout(clean_row)

        main_layout.addWidget(down_card)

        # =====================================================================
        # 4. Lyrics & Tagging Section
        # =====================================================================
        main_layout.addWidget(StrongBodyLabel("Lyrics & Tagging", self.container))

        tag_card = CardWidget(self.container)
        t_layout = QVBoxLayout(tag_card)
        t_layout.setContentsMargins(20, 18, 20, 20)
        t_layout.setSpacing(14)

        # Lyrics Storage Mode Row
        lrc_row = QHBoxLayout()
        lrc_info = QVBoxLayout()
        lrc_title = BodyLabel("Lyrics Storage Location", tag_card)
        lrc_title.setStyleSheet("font-weight: bold;")
        lrc_desc = CaptionLabel(
            "Embedded-Only keeps your music folders 100% clean with ONLY songs (lyrics are embedded in audio tags).\n"
            "Dedicated Subfolder saves .lrc files inside a separate 'lyrics/' subfolder.",
            tag_card
        )
        lrc_desc.setTextColor(TEXT_SECONDARY, TEXT_SECONDARY)
        lrc_desc.setWordWrap(True)
        lrc_info.addWidget(lrc_title)
        lrc_info.addWidget(lrc_desc)

        self.lyrics_combo = ComboBox(tag_card)
        self.lyrics_combo.addItems([
            "Embedded in Audio Only (Cleanest - No .lrc files)",
            "Dedicated Subfolder (lyrics/)",
            "Same Folder as Audio (.lrc)"
        ])
        current_lrc_mode = config.get("download.lyrics_mode", "embedded_only")
        lrc_map = {"embedded_only": 0, "separate_folder": 1, "same_folder": 2}
        self.lyrics_combo.setCurrentIndex(lrc_map.get(current_lrc_mode, 0))
        self.lyrics_combo.currentIndexChanged.connect(self._on_lyrics_mode_changed)

        lrc_row.addLayout(lrc_info, 1)
        lrc_row.addWidget(self.lyrics_combo)
        t_layout.addLayout(lrc_row)

        # Embed lyrics switch
        embed_lrc_row = QHBoxLayout()
        embed_info = QVBoxLayout()
        embed_title = BodyLabel("Embed Lyrics in Audio Container", tag_card)
        embed_title.setStyleSheet("font-weight: bold;")
        embed_desc = CaptionLabel("Embeds plain lyrics into MP3 ID3 (USLT), FLAC Vorbis (LYRICS), and M4A tags.", tag_card)
        embed_desc.setTextColor(TEXT_SECONDARY, TEXT_SECONDARY)
        embed_desc.setWordWrap(True)
        embed_info.addWidget(embed_title)
        embed_info.addWidget(embed_desc)

        self.embed_switch = SwitchButton(tag_card)
        self.embed_switch.setChecked(config.get("download.embed_lyrics", True))
        self.embed_switch.checkedChanged.connect(lambda v: config.set("download.embed_lyrics", v))

        embed_lrc_row.addLayout(embed_info, 1)
        embed_lrc_row.addWidget(self.embed_switch)
        t_layout.addLayout(embed_lrc_row)

        # Embed Artwork switch
        art_row = QHBoxLayout()
        art_info = QVBoxLayout()
        art_title = BodyLabel("Embed Front Cover Artwork", tag_card)
        art_title.setStyleSheet("font-weight: bold;")
        art_desc = CaptionLabel("Embeds high-resolution front-cover album artwork directly into the file.", tag_card)
        art_desc.setTextColor(TEXT_SECONDARY, TEXT_SECONDARY)
        art_desc.setWordWrap(True)
        art_info.addWidget(art_title)
        art_info.addWidget(art_desc)

        self.art_switch = SwitchButton(tag_card)
        self.art_switch.setChecked(config.get("download.embed_cover_art", True))
        self.art_switch.checkedChanged.connect(lambda v: config.set("download.embed_cover_art", v))

        art_row.addLayout(art_info, 1)
        art_row.addWidget(self.art_switch)
        t_layout.addLayout(art_row)

        # Automatic .m3u8 playlist file generator switch
        m3u_row = QHBoxLayout()
        m3u_info = QVBoxLayout()
        m3u_title = BodyLabel("Generate Companion .m3u8 Playlist Files", tag_card)
        m3u_title.setStyleSheet("font-weight: bold;")
        m3u_desc = CaptionLabel(
            "Automatically generates UTF-8 .m3u8 playlist files in each downloaded playlist folder "
            "for plug-and-play playback on DAP players, foobar2000, and mobile devices.",
            tag_card
        )
        m3u_desc.setTextColor(TEXT_SECONDARY, TEXT_SECONDARY)
        m3u_desc.setWordWrap(True)
        m3u_info.addWidget(m3u_title)
        m3u_info.addWidget(m3u_desc)

        self.m3u_switch = SwitchButton(tag_card)
        self.m3u_switch.setChecked(config.get("download.generate_m3u8", True))
        self.m3u_switch.checkedChanged.connect(lambda v: config.set("download.generate_m3u8", v))

        m3u_row.addLayout(m3u_info, 1)
        m3u_row.addWidget(self.m3u_switch)
        t_layout.addLayout(m3u_row)

        # Auto-Boost & Balance Audio Volume (EBU R128) switch
        norm_row = QHBoxLayout()
        norm_info = QVBoxLayout()
        norm_title = BodyLabel("Auto-Boost & Balance Audio Volume (EBU R128)", tag_card)
        norm_title.setStyleSheet("font-weight: bold;")
        norm_desc = CaptionLabel(
            "Automatically boosts quiet songs and balances loud tracks to a uniform, punchy -9.0 LUFS master level "
            "using transparent 5ms lookahead true-peak limiting (-0.4 dBFS) with zero clipping or metadata loss.",
            tag_card
        )
        norm_desc.setTextColor(TEXT_SECONDARY, TEXT_SECONDARY)
        norm_desc.setWordWrap(True)
        norm_info.addWidget(norm_title)
        norm_info.addWidget(norm_desc)

        self.norm_vol_switch = SwitchButton(tag_card)
        self.norm_vol_switch.setChecked(config.get("download.normalize_volume", True))
        self.norm_vol_switch.checkedChanged.connect(lambda v: config.set("download.normalize_volume", v))

        norm_row.addLayout(norm_info, 1)
        norm_row.addWidget(self.norm_vol_switch)
        t_layout.addLayout(norm_row)

        # ReplayGain 2.0 Normalization Tagging switch
        rg_row = QHBoxLayout()
        rg_info = QVBoxLayout()
        rg_title = BodyLabel("ReplayGain 2.0 Loudness Normalization Tagging", tag_card)
        rg_title.setStyleSheet("font-weight: bold;")
        rg_desc = CaptionLabel(
            "Calculates EBU R128 loudness metrics and embeds non-destructive REPLAYGAIN_TRACK_GAIN and "
            "REPLAYGAIN_TRACK_PEAK tags for uniform playback volume without audio re-encoding.",
            tag_card
        )
        rg_desc.setTextColor(TEXT_SECONDARY, TEXT_SECONDARY)
        rg_desc.setWordWrap(True)
        rg_info.addWidget(rg_title)
        rg_info.addWidget(rg_desc)

        self.rg_switch = SwitchButton(tag_card)
        self.rg_switch.setChecked(config.get("download.replaygain_tagging", False))
        self.rg_switch.checkedChanged.connect(lambda v: config.set("download.replaygain_tagging", v))

        rg_row.addLayout(rg_info, 1)
        rg_row.addWidget(self.rg_switch)
        t_layout.addLayout(rg_row)

        main_layout.addWidget(tag_card)

        # =====================================================================
        # 5. FFmpeg Media Engine Section
        # =====================================================================
        main_layout.addWidget(StrongBodyLabel("FFmpeg Audio Processing Engine", self.container))

        ffmpeg_card = CardWidget(self.container)
        ff_layout = QVBoxLayout(ffmpeg_card)
        ff_layout.setContentsMargins(20, 18, 20, 20)
        ff_layout.setSpacing(14)

        # FFmpeg Status Header Row
        ff_status_row = QHBoxLayout()
        ff_icon = BodyLabel("🎬", ffmpeg_card)
        ff_icon.setStyleSheet("font-size: 18px;")
        ff_title = BodyLabel("FFmpeg Binary Status", ffmpeg_card)
        ff_title.setStyleSheet("font-weight: bold; font-size: 14px;")

        self.ffmpeg_badge = CaptionLabel("Checking...", ffmpeg_card)
        self.ffmpeg_badge.setStyleSheet(
            "background-color: #333333; color: #AAAAAA; padding: 3px 10px; border-radius: 10px;"
        )

        ff_status_row.addWidget(ff_icon)
        ff_status_row.addWidget(ff_title)
        ff_status_row.addStretch(1)
        ff_status_row.addWidget(self.ffmpeg_badge)
        ff_layout.addLayout(ff_status_row)

        ff_desc = CaptionLabel(
            "FFmpeg is used for lossless audio container extraction, YouTube Music Opus/M4A streams, "
            "and flawless metadata and cover-art muxing.",
            ffmpeg_card
        )
        ff_desc.setTextColor(TEXT_SECONDARY, TEXT_SECONDARY)
        ff_desc.setWordWrap(True)
        ff_layout.addWidget(ff_desc)

        # Download / Reinstall Action Row
        ff_action_row = QHBoxLayout()
        ff_action_row.setSpacing(10)

        self.download_ffmpeg_btn = PushButton(FluentIcon.DOWNLOAD, "Download / Reinstall Standalone FFmpeg", ffmpeg_card)
        self.download_ffmpeg_btn.clicked.connect(self._download_ffmpeg)

        self.ffmpeg_status_label = CaptionLabel("", ffmpeg_card)
        self.ffmpeg_status_label.setStyleSheet("font-size: 11px;")
        self.ffmpeg_status_label.setWordWrap(True)

        ff_action_row.addWidget(self.download_ffmpeg_btn)
        ff_action_row.addWidget(self.ffmpeg_status_label, 1)
        ff_layout.addLayout(ff_action_row)

        main_layout.addWidget(ffmpeg_card)

        # =====================================================================
        # 6. Library Maintenance & Auto-Repair Section
        # =====================================================================
        main_layout.addWidget(StrongBodyLabel("Library Maintenance & Auto-Repair", self.container))

        maint_card = CardWidget(self.container)
        maint_layout = QVBoxLayout(maint_card)
        maint_layout.setContentsMargins(20, 18, 20, 20)
        maint_layout.setSpacing(14)

        maint_desc = CaptionLabel(
            "Audit all downloaded songs in your library, auto-resolve any missing high-resolution album artwork "
            "or embedded lyrics, and clean/reorganize corrupt files.",
            maint_card
        )
        maint_desc.setTextColor(TEXT_SECONDARY, TEXT_SECONDARY)
        maint_desc.setWordWrap(True)
        maint_layout.addWidget(maint_desc)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        self.repair_lib_btn = PushButton(FluentIcon.SYNC, "Scan & Auto-Repair All Tracks", maint_card)
        self.repair_lib_btn.clicked.connect(self._repair_library)

        self.retag_genres_btn = PushButton(FluentIcon.TAG, "Scan & Retag Library Genres", maint_card)
        self.retag_genres_btn.clicked.connect(self._retag_genres)

        self.clean_lib_btn = PushButton(FluentIcon.DELETE, "Clean Corrupt Files & Cache", maint_card)
        self.clean_lib_btn.clicked.connect(self._clean_library)

        self.boost_vol_btn = PrimaryPushButton(FluentIcon.VOLUME, "Boost & Balance All Songs Volume", maint_card)
        self.boost_vol_btn.clicked.connect(self._boost_library_volume)

        self.batch_replaygain_btn = PushButton(FluentIcon.MIX_VOLUMES, "Calculate ReplayGain 2.0", maint_card)
        self.batch_replaygain_btn.clicked.connect(self._batch_replaygain)

        btn_row.addWidget(self.boost_vol_btn)
        btn_row.addWidget(self.repair_lib_btn)
        btn_row.addWidget(self.retag_genres_btn)
        btn_row.addWidget(self.clean_lib_btn)
        btn_row.addWidget(self.batch_replaygain_btn)
        btn_row.addStretch(1)
        maint_layout.addLayout(btn_row)

        self.maint_status_label = CaptionLabel("", maint_card)
        self.maint_status_label.setStyleSheet("font-size: 11px;")
        self.maint_status_label.setWordWrap(True)
        maint_layout.addWidget(self.maint_status_label)

        main_layout.addWidget(maint_card)
        main_layout.addStretch(1)

        # Check initial status
        self._update_status_badge()
        self._update_ffmpeg_badge()
        self._update_concurrency_ui()
        QTimer.singleShot(400, self._check_telegram_status)

    def _update_concurrency_ui(self):
        engine_name = str(config.get("source_engine", "musilon")).lower()
        is_melobot = (engine_name == "melobot" or (config.get("telegram.enabled", False) and not config.get("musilon.enabled", True)))
        if hasattr(self, "concurrency_desc") and hasattr(self, "concurrency_spin"):
            if is_melobot:
                self.concurrency_desc.setText(
                    "MeloBot Premium is active: Telegram queries are strictly serialized to 1 song at a time to prevent chat state collisions. Concurrency is locked to 1."
                )
                self.concurrency_spin.setEnabled(False)
            else:
                self.concurrency_desc.setText(
                    "Number of simultaneous songs to search and download in parallel (Default: 5). Parallel resolution prevents searches from blocking subsequent songs in the queue."
                )
                self.concurrency_spin.setEnabled(True)

    # -------------------------------------------------------------------------
    # Event Handlers
    # -------------------------------------------------------------------------
    def _on_source_engine_changed(self, idx: int):
        engine_name = "melobot" if idx == 1 else "musilon"
        config.set("source_engine", engine_name)
        if engine_name == "melobot":
            config.set("musilon.enabled", False)
            config.set("telegram.enabled", True)
            self.musilon_engine.enabled = False
            if hasattr(self, "musilon_switch"):
                self.musilon_switch.setChecked(False)
            if hasattr(self, "melobot_switch"):
                self.melobot_switch.setChecked(True)
            if self.qm and hasattr(self.qm, "update_concurrency"):
                self.qm.update_concurrency(1)
        else:
            config.set("musilon.enabled", True)
            config.set("telegram.enabled", False)
            self.musilon_engine.enabled = True
            if hasattr(self, "musilon_switch"):
                self.musilon_switch.setChecked(True)
            if hasattr(self, "melobot_switch"):
                self.melobot_switch.setChecked(False)
            if self.qm and hasattr(self.qm, "update_concurrency"):
                base_concur = int(config.get("download.concurrency", 5))
                self.qm.update_concurrency(base_concur)
        config.save()
        self._update_concurrency_ui()
        InfoBar.success(
            "Primary Source Updated",
            f"Active high-quality source set to: {'MeloBot Premium (@melobot Telegram)' if engine_name == 'melobot' else 'Musilon VIP'}",
            parent=self.window() or self,
            duration=3000
        )

    def _on_melobot_switch_changed(self, enabled: bool):
        config.set("telegram.enabled", enabled)
        if enabled:
            config.set("source_engine", "melobot")
            config.set("musilon.enabled", False)
            self.musilon_engine.enabled = False
            if hasattr(self, "source_combo"):
                self.source_combo.setCurrentIndex(1)
            if hasattr(self, "musilon_switch"):
                self.musilon_switch.setChecked(False)
            if self.qm and hasattr(self.qm, "update_concurrency"):
                self.qm.update_concurrency(1)
            InfoBar.info("MeloBot Enabled", "MeloBot Telegram VIP engine is active.", duration=2500, parent=self)
        else:
            config.set("source_engine", "musilon")
            config.set("musilon.enabled", True)
            self.musilon_engine.enabled = True
            if hasattr(self, "source_combo"):
                self.source_combo.setCurrentIndex(0)
            if hasattr(self, "musilon_switch"):
                self.musilon_switch.setChecked(True)
            if self.qm and hasattr(self.qm, "update_concurrency"):
                base_concur = int(config.get("download.concurrency", 5))
                self.qm.update_concurrency(base_concur)
            InfoBar.info("MeloBot Disabled", "Switched back to Musilon VIP engine.", duration=2500, parent=self)
        config.save()
        self._update_concurrency_ui()

    def _open_telegram_login(self):
        diag = TelegramLoginDialog(self.melobot_engine, parent=self.window() or self)
        if diag.exec():
            self._check_telegram_status()
            InfoBar.success(
                "Telegram Connected",
                "Your Telegram account has been connected to MeloBot!",
                parent=self.window() or self,
                duration=4000
            )

    def _check_telegram_status(self):
        self.tg_status_badge.setText("Checking...")
        self.tg_status_badge.setStyleSheet("background-color: #333333; color: #AAAAAA; padding: 3px 10px; border-radius: 10px;")

        def worker():
            try:
                is_auth = self.melobot_engine.is_authorized()
                user_info = self.melobot_engine.get_me() if is_auth else None
                disp = ""
                if user_info:
                    name = user_info.get("first_name") or user_info.get("username") or "Connected"
                    phone = user_info.get("phone") or ""
                    disp = f"Connected: {name} (+{phone})" if phone else f"Connected: {name}"
                safe_emit(self.sig_tg_status_result, is_auth, disp)
            except Exception:
                pass

        threading.Thread(target=worker, daemon=True).start()

    def _on_tg_status_done(self, is_auth: bool, disp: str):
        if is_auth:
            self.tg_status_badge.setText(disp or "Connected")
            self.tg_status_badge.setStyleSheet("background-color: #1DB954; color: #FFFFFF; font-weight: bold; padding: 3px 10px; border-radius: 10px;")
        else:
            self.tg_status_badge.setText("Not Connected")
            self.tg_status_badge.setStyleSheet("background-color: #555555; color: #CCCCCC; padding: 3px 10px; border-radius: 10px;")

    def _logout_telegram(self):
        def worker():
            self.melobot_engine.log_out()
            safe_emit(self.sig_tg_logout_result)

        threading.Thread(target=worker, daemon=True).start()

    def _on_tg_logout_done(self):
        self.tg_status_badge.setText("Not Connected")
        self.tg_status_badge.setStyleSheet("background-color: #555555; color: #CCCCCC; padding: 3px 10px; border-radius: 10px;")
        InfoBar.info("Telegram Disconnected", "You have been logged out of Telegram.", parent=self.window() or self, duration=3000)

    def _on_cookie_changed(self, text: str):
        config.set("musilon.session_cookie", text.strip())
        self.musilon_engine.set_credentials(
            session_cookie=text.strip(),
            username=config.get("musilon.username", ""),
            password=config.get("musilon.password", ""),
            enabled=config.get("musilon.enabled", True)
        )
        self._update_status_badge()

    def _on_musilon_switch_changed(self, enabled: bool):
        config.set("musilon.enabled", enabled)
        self.musilon_engine.enabled = enabled
        if enabled:
            InfoBar.info("Musilon Enabled", "Musilon Tier 1-3 lossless engine is active.", duration=2500, parent=self)
        else:
            InfoBar.warning("Musilon Disabled", "Switched to direct YouTube Music high-speed mode.", duration=3000, parent=self)

    def _on_safe_mode_changed(self, enabled: bool):
        config.set("musilon.safe_mode", enabled)
        if enabled:
            InfoBar.info("Stealth Shield Active", "Musilon rate-limit protection and pacing active.", duration=3000, parent=self)
        else:
            InfoBar.warning("Stealth Shield Disabled", "Warning: Downloading without cooldown may trigger rate-limits.", duration=3500, parent=self)

    def _on_cooldown_min_changed(self, val: int):
        cur_max = int(config.get("musilon.cooldown_max_sec", 35))
        if val > cur_max:
            val = cur_max
            self.cooldown_min_spin.setValue(val)
        config.set("musilon.cooldown_min_sec", val)

    def _on_cooldown_max_changed(self, val: int):
        cur_min = int(config.get("musilon.cooldown_min_sec", 15))
        if val < cur_min:
            val = cur_min
            self.cooldown_max_spin.setValue(val)
        config.set("musilon.cooldown_max_sec", val)

    def _on_subfolder_switch_changed(self, enabled: bool):
        config.set("download.save_in_subfolders", enabled)
        if enabled:
            InfoBar.info("Folder Organization", "Songs will be sorted into playlist and album subfolders.", duration=3000, parent=self)
        else:
            InfoBar.info("Single Folder Mode", "All songs will be saved directly into your download output folder.", duration=3000, parent=self)

    def _on_fallback_switch_changed(self, enabled: bool):
        config.set("download.allow_fallback", enabled)
        if enabled:
            InfoBar.info("Safety-Net Fallback Enabled", "YouTube Music fallback is active if Musilon has no match.", duration=3000, parent=self)
        else:
            InfoBar.warning("Strict Musilon Mode", "YouTube fallback disabled. Downloads restricted strictly to Musilon.", duration=3500, parent=self)

    def _on_concurrency_changed(self, val: int):
        config.set("download.concurrency", val)
        if self.qm and hasattr(self.qm, "update_concurrency"):
            self.qm.update_concurrency(val)
        InfoBar.info("Concurrency Updated", f"Download concurrency set to {val} simultaneous worker(s).", duration=2500, parent=self)

    def _on_quality_changed(self, index: int):
        if index == 0:
            config.set("download.preferred_quality", "320")
            config.set("download.quality_priority", [
                "musilon_mp3_320",
                "musilon_flac_16",
                "musilon_flac_24",
                "ytm_opus"
            ])
            InfoBar.info("Quality Set: MP3 320k", "Musilon downloads will prioritize 320 kbps MP3 files.", duration=3000, parent=self)
        else:
            config.set("download.preferred_quality", "flac")
            config.set("download.quality_priority", [
                "musilon_flac_16",
                "musilon_flac_24",
                "musilon_mp3_320",
                "ytm_opus"
            ])
            InfoBar.info("Quality Set: Lossless FLAC", "Musilon downloads will prioritize Lossless FLAC (16/24-bit).", duration=3000, parent=self)

    def _on_target_format_changed(self, index: int):
        fmt_keys = ["original", "alac", "mp3", "flac", "opus"]
        fmt_key = fmt_keys[index] if 0 <= index < len(fmt_keys) else "original"
        config.set("download.target_format", fmt_key)
        labels = {
            "original": "Original / Native Stream (No Transcoding)",
            "alac": "Apple Lossless (ALAC .m4a)",
            "mp3": "MP3 320 kbps CBR",
            "flac": "Lossless FLAC",
            "opus": "Opus 256 kbps"
        }
        InfoBar.info("Target Audio Format", f"Transcoder format set to {labels.get(fmt_key, fmt_key)}.", duration=3000, parent=self)

    def _on_user_changed(self, text: str):
        val = text.strip()
        config.set("musilon.username", val)
        self.musilon_engine.username = val

    def _on_pwd_changed(self, text: str):
        val = text.strip()
        config.set("musilon.password", val)
        self.musilon_engine.password = val

    def _paste_cookie(self, *args):
        text = QApplication.clipboard().text().strip()
        if text:
            self.cookie_input.setText(text)

    def _login_musilon(self, *args):
        user = self.user_input.text().strip()
        pwd = self.pwd_input.text().strip()
        if not user or not pwd:
            InfoBar.warning("Empty Credentials", "Please enter your Musilon email and password.", parent=self)
            return

        if "@" not in user:
            InfoBar.warning(
                "Email Required",
                "Musilon requires your registered email address (e.g. your_email@gmail.com), not your username.",
                duration=5000,
                parent=self
            )
            return

        self.login_btn.setEnabled(False)
        self.login_btn.setText("Logging In...")
        self.result_label.setText("Attempting automated login to open.musilon.com...")

        def worker():
            success, msg = self.musilon_engine.login_with_credentials(user, pwd)
            safe_emit(self.sig_login_result, success, msg)

        threading.Thread(target=worker, daemon=True).start()

    def _on_login_finished(self, success: bool, msg: str):
        self.login_btn.setEnabled(True)
        self.login_btn.setText("Log In")
        self.result_label.setText(msg)

        if success:
            # Save session cookies extracted by session
            cookie_dict = self.musilon_engine.session.cookies.get_dict()
            cookie_str = "; ".join(f"{k}={v}" for k, v in cookie_dict.items())
            self.cookie_input.setText(cookie_str)
            config.set("musilon.session_cookie", cookie_str)
            self._set_status_badge("active", "Logged In")
            InfoBar.success("Login Successful", "Authenticated with Musilon account!", duration=3500, parent=self)
            # Auto-refresh connection status and VIP quota display
            self._test_musilon()
        else:
            self._set_status_badge("offline", "Login Failed")
            InfoBar.error("Login Failed", msg, duration=5000, parent=self)

    def _test_musilon(self, *args):
        self.test_btn.setEnabled(False)
        self.test_btn.setText("Connecting...")
        self.result_label.setText("Testing connection to open.musilon.com...")

        def worker():
            connected, is_auth, is_vip, msg = self.musilon_engine.test_connection()
            safe_emit(self.sig_test_result, connected, is_auth, is_vip, msg)

        threading.Thread(target=worker, daemon=True).start()

    def _on_test_finished(self, connected: bool, is_authenticated: bool, is_vip: bool, msg: str):
        self.test_btn.setEnabled(True)
        self.test_btn.setText("Test Connection && VIP Status")
        self.result_label.setText(msg)

        if is_vip:
            self._set_status_badge("vip", "VIP Active")
            InfoBar.success("VIP Active", msg, duration=4500, parent=self)
        elif is_authenticated:
            self._set_status_badge("active", "Account Active")
            InfoBar.warning("VIP Expired", msg, duration=6000, parent=self)
        elif connected:
            self._set_status_badge("guest", "Guest Mode")
            InfoBar.info("Guest Mode", msg, duration=4500, parent=self)
        else:
            self._set_status_badge("offline", "Offline / Blocked")
            InfoBar.error("Connection Failed", msg, duration=6000, parent=self)

    def _update_status_badge(self):
        cookie = self.cookie_input.text().strip()
        has_cookie_auth = (
            "next-auth" in cookie
            or "__Secure-next-auth" in cookie
            or "wordpress_logged_in" in cookie
            or "wordpress_sec" in cookie
            or cookie.startswith("eyJ")
        )
        has_cred_auth = bool(self.user_input.text().strip() and self.pwd_input.text().strip())
        if has_cookie_auth or has_cred_auth:
            self._set_status_badge("active", "Credentials Saved")
        else:
            self._set_status_badge("guest", "Not Configured")

    def _set_status_badge(self, state: Any, text: str = ""):
        if state is True or state == "vip":
            self.status_badge.setText(text or "VIP Active")
            self.status_badge.setStyleSheet(
                "background-color: rgba(29, 185, 84, 0.2); color: #1ED760; "
                "padding: 4px 12px; border-radius: 10px; font-weight: bold; border: 1px solid #1DB954;"
            )
        elif state == "active":
            self.status_badge.setText(text or "Account Active")
            self.status_badge.setStyleSheet(
                "background-color: rgba(245, 158, 11, 0.2); color: #FBBF24; "
                "padding: 4px 12px; border-radius: 10px; font-weight: bold; border: 1px solid #F59E0B;"
            )
        elif state == "guest":
            self.status_badge.setText(text or "Guest Mode")
            self.status_badge.setStyleSheet(
                "background-color: rgba(156, 163, 175, 0.2); color: #D1D5DB; "
                "padding: 4px 12px; border-radius: 10px; font-weight: bold; border: 1px solid #6B7280;"
            )
        else:
            self.status_badge.setText(text or "Offline")
            self.status_badge.setStyleSheet(
                "background-color: rgba(239, 68, 68, 0.2); color: #F87171; "
                "padding: 4px 12px; border-radius: 10px; font-weight: bold; border: 1px solid rgba(239, 68, 68, 0.5);"
            )
        self.status_badge.adjustSize()

    def _on_sp_id_changed(self, text: str):
        config.set("spotify.client_id", text.strip())
        self._update_spotify_badge()

    def _on_sp_sec_changed(self, text: str):
        config.set("spotify.client_secret", text.strip())
        self._update_spotify_badge()

    def _update_spotify_badge(self):
        cid = self.spotify_id.text().strip()
        sec = self.spotify_secret.text().strip()
        if not cid or not sec:
            self.sp_status_badge.setText("Guest Mode (Capped at 100 tracks)")
            self.sp_status_badge.setStyleSheet(
                "background-color: rgba(148, 163, 184, 0.15); color: #94A3B8; "
                "padding: 3px 10px; border-radius: 10px; font-weight: bold; border: 1px solid rgba(148, 163, 184, 0.3);"
            )
            self.auth_sp_btn.setEnabled(False)
            return

        self.auth_sp_btn.setEnabled(True)
        try:
            client = SpotifyClient(client_id=cid, client_secret=sec)
            if client.has_user_auth(allow_network=False):
                user_name = client._cached_user_name or ""
                user_str = f" as @{user_name}" if user_name else ""
                self.sp_status_badge.setText(f"Authorized{user_str} (Full Access Active)")
                self.sp_status_badge.setStyleSheet(
                    "background-color: rgba(29, 185, 84, 0.2); color: #1ED760; "
                    "padding: 3px 10px; border-radius: 10px; font-weight: bold; border: 1px solid #1DB954;"
                )
                self.auth_sp_btn.setText("Switch Account / Re-Authorize")
                if not user_name and not getattr(self, "_fetching_sp_user", False):
                    self._fetching_sp_user = True
                    def _fetch():
                        try:
                            name = client.get_current_user_name()
                            if name:
                                QTimer.singleShot(0, lambda: safe_invoke(self._update_spotify_badge))
                        finally:
                            self._fetching_sp_user = False
                    threading.Thread(target=_fetch, daemon=True, name="SettingsSpotifyNameFetcher").start()
            else:
                self.sp_status_badge.setText("Keys Set — Authorization Needed for >100 Tracks")
                self.sp_status_badge.setStyleSheet(
                    "background-color: rgba(234, 179, 8, 0.2); color: #EAB308; "
                    "padding: 3px 10px; border-radius: 10px; font-weight: bold; border: 1px solid rgba(234, 179, 8, 0.4);"
                )
                self.auth_sp_btn.setText("Authorize Spotify Account")
        except Exception:
            self.sp_status_badge.setText("Configuration Error")
            self.sp_status_badge.setStyleSheet(
                "background-color: rgba(239, 68, 68, 0.15); color: #F87171; "
                "padding: 3px 10px; border-radius: 10px; font-weight: bold; border: 1px solid rgba(239, 68, 68, 0.4);"
            )

    def _authorize_spotify(self, *args):
        cid = self.spotify_id.text().strip()
        sec = self.spotify_secret.text().strip()
        if not cid or not sec:
            InfoBar.warning("Missing Keys", "Please enter both Client ID and Client Secret before authorizing.", parent=self)
            return

        self.auth_sp_btn.setEnabled(False)
        self.auth_sp_btn.setText("Authorizing in browser...")
        InfoBar.info("Spotify Login", "Opening Spotify authorization in your web browser. Click 'Agree' or switch accounts.", duration=7000, parent=self)

        def worker():
            try:
                client = SpotifyClient(client_id=cid, client_secret=sec)
                ok = client.authorize_user(force_new=True)
                if ok:
                    user_name = client.get_current_user_name()
                    msg = f"Logged in as @{user_name}! Full playlist access unlocked." if user_name else "Spotify account successfully authorized!"
                    safe_emit(self.sig_spotify_auth_result, True, msg)
                else:
                    safe_emit(self.sig_spotify_auth_result, False, "Authorization was cancelled or did not return tokens.")
            except Exception as e:
                safe_emit(self.sig_spotify_auth_result, False, str(e))

        threading.Thread(target=worker, daemon=True, name="SettingsSpotifyAuthWorker").start()

    def _on_spotify_auth_done(self, success: bool, msg: str):
        self._update_spotify_badge()
        if success:
            InfoBar.success("Authorization Successful", msg, duration=5000, parent=self)
        else:
            InfoBar.error("Authorization Failed", msg, duration=6000, parent=self)

    def _validate_spotify(self, *args):
        cid = self.spotify_id.text().strip()
        sec = self.spotify_secret.text().strip()
        if not cid or not sec:
            InfoBar.warning("Missing Keys", "Please enter both Client ID and Client Secret.", parent=self)
            return

        self.validate_sp_btn.setEnabled(False)
        self.validate_sp_btn.setText("Checking...")

        def worker():
            try:
                client = SpotifyClient(client_id=cid, client_secret=sec)
                res = client.resolve("https://open.spotify.com/track/3AJwUDP919kvQ9QcozQPxg")
                auth_status = "User Authorized (Full Library Access)" if client.has_user_auth() else "Keys Valid (Click 'Authorize' to unlock >100 songs)"
                safe_emit(self.sig_spotify_result, True, f"API Verified: '{res[0].title}' — {auth_status}")
            except Exception as e:
                safe_emit(self.sig_spotify_result, False, str(e))

        threading.Thread(target=worker, daemon=True).start()

    def _on_spotify_valid(self, success: bool, msg: str):
        self.validate_sp_btn.setEnabled(True)
        self.validate_sp_btn.setText("Validate Keys")
        self._update_spotify_badge()
        if success:
            InfoBar.success("Spotify API Valid", msg, duration=4500, parent=self)
        else:
            InfoBar.error("Spotify Error", msg, duration=5000, parent=self)

    def _browse_folder(self, *args):
        cur = self.folder_input.text().strip() or os.path.expanduser("~/Music")
        chosen = QFileDialog.getExistingDirectory(self, "Select Download Directory", cur)
        if chosen:
            norm = os.path.normpath(chosen)
            self.folder_input.setText(norm)
            config.set("download.output_dir", norm)
            InfoBar.success("Saved", f"Download directory updated: {norm}", duration=2500, parent=self)

    def _browse_cookies_file(self, *args):
        cur = self.yt_cookie_input.text().strip() or os.getcwd()
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select YouTube Cookies File",
            cur,
            "Cookie Files (*.txt);;All Files (*)"
        )
        if path:
            norm = os.path.normpath(path)
            self.yt_cookie_input.setText(norm)
            config.set("download.cookies_file", norm)
            InfoBar.success("Cookies Loaded", f"YouTube cookies: {os.path.basename(norm)}", duration=3000, parent=self)

    def _open_folder(self, *args):
        path = self.folder_input.text().strip()
        if os.path.exists(path):
            os.startfile(path)
        else:
            InfoBar.warning("Folder Not Found", f"Directory does not exist: {path}", parent=self)

    def _update_ffmpeg_badge(self):
        ff_path = ensure_ffmpeg()
        if ff_path:
            self.ffmpeg_badge.setText("Installed & Ready")
            self.ffmpeg_badge.setStyleSheet(
                "background-color: rgba(29, 185, 84, 0.2); color: #1ED760; "
                "padding: 3px 10px; border-radius: 10px; font-weight: bold; border: 1px solid #1DB954;"
            )
            self.ffmpeg_status_label.setText(f"Active binary: {ff_path}")
        else:
            self.ffmpeg_badge.setText("Missing")
            self.ffmpeg_badge.setStyleSheet(
                "background-color: rgba(239, 68, 68, 0.15); color: #F87171; "
                "padding: 3px 10px; border-radius: 10px; font-weight: bold; border: 1px solid rgba(239, 68, 68, 0.4);"
            )
            self.ffmpeg_status_label.setText("FFmpeg is not found. Click the button to auto-download.")

    def _download_ffmpeg(self, *args):
        self.download_ffmpeg_btn.setEnabled(False)
        self.download_ffmpeg_btn.setText("Downloading...")
        self.ffmpeg_status_label.setText("Connecting to repository...")

        def progress_cb(pct: float, msg: str):
            safe_emit(self.sig_ffmpeg_progress, pct, msg)

        def worker():
            res = download_ffmpeg(progress_callback=progress_cb)
            if res:
                safe_emit(self.sig_ffmpeg_finished, True, f"FFmpeg installed at {res}")
            else:
                safe_emit(self.sig_ffmpeg_finished, False, "FFmpeg download or validation failed.")

        threading.Thread(target=worker, daemon=True).start()

    def _on_ffmpeg_progress(self, pct: float, msg: str):
        self.ffmpeg_status_label.setText(f"[{pct:.0f}%] {msg}")

    def _on_ffmpeg_finished(self, success: bool, msg: str):
        self.download_ffmpeg_btn.setEnabled(True)
        self.download_ffmpeg_btn.setText("Download / Reinstall Standalone FFmpeg")
        self._update_ffmpeg_badge()
        if success:
            InfoBar.success("FFmpeg Installed", msg, duration=4000, parent=self)
        else:
            InfoBar.error("FFmpeg Download Error", msg, duration=5000, parent=self)

    def _on_lyrics_mode_changed(self, idx: int):
        rev_map = {
            0: "embedded_only",
            1: "separate_folder",
            2: "same_folder"
        }
        mode = rev_map.get(idx, "embedded_only")
        config.set("download.lyrics_mode", mode)
        config.set("download.save_lrc", mode != "embedded_only")
        desc_map = {
            "embedded_only": "Lyrics will be embedded directly in songs (no .lrc files).",
            "separate_folder": "Lyrics will be saved to a 'lyrics/' subfolder.",
            "same_folder": "Lyrics will be saved alongside songs as .lrc files."
        }
        InfoBar.info("Lyrics Setting Updated", desc_map.get(mode, ""), duration=3000, parent=self)

    def _clean_library(self):
        from core.archive import ArchiveManager
        self.clean_lib_btn.setEnabled(False)
        self.clean_lib_btn.setText("Cleaning...")
        if hasattr(self, "clean_lib_top_btn"):
            self.clean_lib_top_btn.setEnabled(False)
            self.clean_lib_top_btn.setText("Cleaning...")

        def worker():
            try:
                arc = ArchiveManager()
                stats = arc.purge_corrupt_and_cleanup_library()
                msg = (
                    f"Purged {stats['purged_corrupt_files']} corrupt HTML files, "
                    f"relocated {stats['relocated_covers']} covers to cache, "
                    f"reorganized {stats['reorganized_lyrics']} lyrics files."
                )
                QTimer.singleShot(0, lambda: safe_invoke(self._on_clean_finished, True, msg))
            except Exception as e:
                QTimer.singleShot(0, lambda: safe_invoke(self._on_clean_finished, False, str(e)))

        threading.Thread(target=worker, daemon=True).start()

    def _on_clean_finished(self, success: bool, msg: str):
        self.clean_lib_btn.setEnabled(True)
        self.clean_lib_btn.setText("Clean Corrupt Files & Cache")
        if hasattr(self, "clean_lib_top_btn"):
            self.clean_lib_top_btn.setEnabled(True)
            self.clean_lib_top_btn.setText("Clean Library")
        if success:
            InfoBar.success("Library Cleaned", msg, duration=5000, parent=self)
        else:
            InfoBar.error("Cleanup Error", f"Failed to clean library: {msg}", duration=5000, parent=self)

    def _repair_library(self):
        from core.archive import ArchiveManager
        self.repair_lib_btn.setEnabled(False)
        self.repair_lib_btn.setText("Scanning & Repairing...")
        self.maint_status_label.setText("Starting library scan across downloads...")

        def progress_cb(cur: int, total: int, msg: str):
            QTimer.singleShot(0, lambda: safe_invoke(self.maint_status_label.setText, f"[{cur}/{total}] {msg}"))

        def worker():
            try:
                arc = ArchiveManager()
                stats = arc.repair_library(progress_callback=progress_cb)
                msg = (
                    f"Audit complete: {stats['scanned']} files scanned. "
                    f"Healed {stats['healed_covers']} covers, "
                    f"embedded {stats['healed_lyrics']} lyrics."
                )
                QTimer.singleShot(0, lambda: safe_invoke(self._on_repair_finished, True, msg))
            except Exception as e:
                QTimer.singleShot(0, lambda: safe_invoke(self._on_repair_finished, False, str(e)))

        threading.Thread(target=worker, daemon=True).start()

    def _on_repair_finished(self, success: bool, msg: str):
        self.repair_lib_btn.setEnabled(True)
        self.repair_lib_btn.setText("Scan & Auto-Repair All Tracks")
        self.maint_status_label.setText(msg)
        if success:
            InfoBar.success("Library Repaired", msg, duration=5000, parent=self)
        else:
            InfoBar.error("Repair Error", f"Failed to repair library: {msg}", duration=5000, parent=self)

    def _retag_genres(self):
        from core.archive import ArchiveManager
        self.retag_genres_btn.setEnabled(False)
        self.retag_genres_btn.setText("Retagging Genres...")
        self.maint_status_label.setText("Starting multi-source genre retagger across library...")

        def progress_cb(cur: int, total: int, msg: str):
            QTimer.singleShot(0, lambda: safe_invoke(self.maint_status_label.setText, f"[{cur}/{total}] {msg}"))

        def worker():
            try:
                arc = ArchiveManager()
                stats = arc.retag_all_library_genres(progress_callback=progress_cb)
                msg = (
                    f"Genre retag complete: {stats['scanned']} files scanned. "
                    f"Retagged {stats['retagged']} files, "
                    f"{stats['already_tagged']} already tagged, {stats['errors']} error(s)."
                )
                QTimer.singleShot(0, lambda: safe_invoke(self._on_retag_finished, True, msg))
            except Exception as e:
                QTimer.singleShot(0, lambda: safe_invoke(self._on_retag_finished, False, str(e)))

        threading.Thread(target=worker, daemon=True, name="GenreRetaggerWorker").start()

    def _on_retag_finished(self, success: bool, msg: str):
        self.retag_genres_btn.setEnabled(True)
        self.retag_genres_btn.setText("Scan & Retag Library Genres")
        self.maint_status_label.setText(msg)
        if success:
            InfoBar.success("Genres Synchronized", msg, duration=5000, parent=self)
            win = self.window()
            if hasattr(win, "sig_reload_library"):
                safe_emit(win.sig_reload_library)
        else:
            InfoBar.error("Retag Error", f"Failed to retag genres: {msg}", duration=5000, parent=self)

    def _batch_replaygain(self):
        from core.archive import ArchiveManager
        self.batch_replaygain_btn.setEnabled(False)
        self.batch_replaygain_btn.setText("Calculating Loudness...")
        self.maint_status_label.setText("Analyzing audio loudness & peak via EBU R128...")

        def progress_cb(cur: int, total: int, msg: str):
            QTimer.singleShot(0, lambda: safe_invoke(self.maint_status_label.setText, f"[{cur}/{total}] {msg}"))

        def worker():
            try:
                arc = ArchiveManager()
                stats = arc.retag_all_library_replaygain(progress_callback=progress_cb)
                msg = (
                    f"ReplayGain 2.0 analysis complete: {stats['scanned']} files scanned. "
                    f"Calculated and embedded loudness tags on {stats['calculated']} files ({stats['errors']} error(s))."
                )
                QTimer.singleShot(0, lambda: safe_invoke(self._on_replaygain_finished, True, msg))
            except Exception as e:
                QTimer.singleShot(0, lambda: safe_invoke(self._on_replaygain_finished, False, str(e)))

        threading.Thread(target=worker, daemon=True, name="ReplayGainWorker").start()

    def _on_replaygain_finished(self, success: bool, msg: str):
        self.batch_replaygain_btn.setEnabled(True)
        self.batch_replaygain_btn.setText("Calculate ReplayGain 2.0")
        self.maint_status_label.setText(msg)
        if success:
            InfoBar.success("ReplayGain 2.0 Complete", msg, duration=5000, parent=self)
        else:
            InfoBar.error("ReplayGain Error", f"Failed to calculate ReplayGain: {msg}", duration=5000, parent=self)

    def _boost_library_volume(self):
        from core.archive import ArchiveManager
        self.boost_vol_btn.setEnabled(False)
        self.boost_vol_btn.setText("Boosting & Balancing Volume...")
        self.maint_status_label.setText("Measuring & normalizing audio loudness across library (-9.0 LUFS EBU R128)...")

        def progress_cb(cur: int, total: int, msg: str):
            QTimer.singleShot(0, lambda: safe_invoke(self.maint_status_label.setText, f"[{cur}/{total}] {msg}"))

        def worker():
            try:
                arc = ArchiveManager()
                target_lufs = float(config.get("download.target_lufs", -9.0) or -9.0)
                workers = min(12, max(4, (os.cpu_count() or 4)))
                stats = arc.normalize_all_library_tracks(target_lufs=target_lufs, max_workers=workers, progress_callback=progress_cb)
                msg = (
                    f"Volume boost & balance complete: {stats['scanned']} tracks processed — "
                    f"{stats['boosted']} boosted, {stats['attenuated']} balanced, "
                    f"{stats['already_balanced']} already optimal ({stats['errors']} skipped)."
                )
                QTimer.singleShot(0, lambda: safe_invoke(self._on_boost_volume_finished, True, msg))
            except Exception as e:
                QTimer.singleShot(0, lambda: safe_invoke(self._on_boost_volume_finished, False, str(e)))

        threading.Thread(target=worker, daemon=True, name="VolumeBoostWorker").start()

    def _on_boost_volume_finished(self, success: bool, msg: str):
        self.boost_vol_btn.setEnabled(True)
        self.boost_vol_btn.setText("Boost & Balance All Songs Volume")
        self.maint_status_label.setText(msg)
        if success:
            InfoBar.success("Library Volume Boosted & Balanced", msg, duration=6000, parent=self)
        else:
            InfoBar.error("Volume Normalization Error", f"Failed to normalize library volume: {msg}", duration=5000, parent=self)

