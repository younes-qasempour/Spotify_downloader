import os
import subprocess
import threading
from typing import Optional
from PyQt6.QtCore import Qt, QTimer, QSize, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFileDialog, QScrollArea,
    QFrame, QApplication
)
from qfluentwidgets import (
    SubtitleLabel, StrongBodyLabel, BodyLabel, CaptionLabel,
    LineEdit, PrimaryPushButton, PushButton, ToolButton, SwitchButton,
    CardWidget, InfoBar, InfoBarPosition, FluentIcon, Slider, ComboBox, SpinBox
)

from core.config import config
from core.musilon import MusilonEngine
from core.spotify_client import SpotifyClient
from core.utils import ensure_ffmpeg, download_ffmpeg
from gui.styles import (
    BG_CARD, BORDER_SUBTLE, SPOTIFY_EMERALD, TEXT_PRIMARY,
    TEXT_SECONDARY, TEXT_MUTED, STATUS_COLORS
)


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
    sig_test_result = pyqtSignal(bool, bool, str)
    sig_spotify_result = pyqtSignal(bool, str)
    sig_spotify_auth_result = pyqtSignal(bool, str)
    sig_ffmpeg_progress = pyqtSignal(float, str)
    sig_ffmpeg_finished = pyqtSignal(bool, str)

    def __init__(self, musilon_engine: Optional[MusilonEngine] = None, parent=None):
        super().__init__(parent)
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

        # Connect thread-safe result signals
        self.sig_login_result.connect(self._on_login_finished)
        self.sig_test_result.connect(self._on_test_finished)
        self.sig_spotify_result.connect(self._on_spotify_valid)
        self.sig_spotify_auth_result.connect(self._on_spotify_auth_done)
        self.sig_ffmpeg_progress.connect(self._on_ffmpeg_progress)
        self.sig_ffmpeg_finished.connect(self._on_ffmpeg_finished)

        self._init_ui()

    def _init_ui(self):
        main_layout = QVBoxLayout(self.container)
        main_layout.setContentsMargins(28, 24, 28, 40)
        main_layout.setSpacing(24)

        # Page Header
        page_title = SubtitleLabel("Settings & Preferences", self.container)
        main_layout.addWidget(page_title)

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
        m_layout.addWidget(desc)

        # Session Cookie Input
        cookie_label = CaptionLabel("Session Cookie / Full Cookie Header:", musilon_card)
        cookie_label.setStyleSheet("font-weight: bold;")
        m_layout.addWidget(cookie_label)

        cookie_row = QHBoxLayout()
        cookie_row.setSpacing(8)

        self.cookie_input = LineEdit(musilon_card)
        self.cookie_input.setPlaceholderText("Paste cookies: __arcsjs=...; __arcsjsc=...; wordpress_logged_in_...;")
        self.cookie_input.setText(config.get("musilon.session_cookie", ""))
        self.cookie_input.textChanged.connect(self._on_cookie_changed)

        self.paste_cookie_btn = PushButton(FluentIcon.PASTE, "Paste", musilon_card)
        self.paste_cookie_btn.clicked.connect(self._paste_cookie)

        cookie_row.addWidget(self.cookie_input, 1)
        cookie_row.addWidget(self.paste_cookie_btn)
        m_layout.addLayout(cookie_row)

        # Or Credentials Row
        cred_label = CaptionLabel("Or Log In with Account Credentials:", musilon_card)
        cred_label.setStyleSheet("font-weight: bold;")
        m_layout.addWidget(cred_label)

        cred_row = QHBoxLayout()
        cred_row.setSpacing(10)

        self.user_input = LineEdit(musilon_card)
        self.user_input.setPlaceholderText("Username or Email")
        self.user_input.setText(config.get("musilon.username", ""))
        self.user_input.textChanged.connect(self._on_user_changed)

        self.pwd_input = LineEdit(musilon_card)
        self.pwd_input.setPlaceholderText("Password")
        self.pwd_input.setEchoMode(LineEdit.EchoMode.Password)
        self.pwd_input.setText(config.get("musilon.password", ""))
        self.pwd_input.textChanged.connect(self._on_pwd_changed)

        self.login_btn = PushButton(FluentIcon.PEOPLE, "Log In", musilon_card)
        self.login_btn.clicked.connect(self._login_musilon)

        cred_row.addWidget(self.user_input, 1)
        cred_row.addWidget(self.pwd_input, 1)
        cred_row.addWidget(self.login_btn)
        m_layout.addLayout(cred_row)

        # Action and Diagnostics Row
        action_row = QHBoxLayout()
        action_row.setSpacing(10)

        self.test_btn = PrimaryPushButton(FluentIcon.SYNC, "Test Connection & VIP Status", musilon_card)
        self.test_btn.clicked.connect(self._test_musilon)

        self.result_label = CaptionLabel("", musilon_card)
        self.result_label.setStyleSheet("font-size: 11px;")

        action_row.addWidget(self.test_btn)
        action_row.addWidget(self.result_label, 1)
        m_layout.addLayout(action_row)

        # Instructions Helper Card
        guide_card = QFrame(musilon_card)
        guide_card.setStyleSheet("background-color: #202020; border-radius: 8px; padding: 8px;")
        g_layout = QVBoxLayout(guide_card)
        g_layout.setContentsMargins(12, 10, 12, 10)
        g_layout.setSpacing(4)

        guide_title = CaptionLabel("💡 How to copy session cookies from your browser:", guide_card)
        guide_title.setStyleSheet("font-weight: bold; color: #1DB954;")
        guide_step1 = CaptionLabel("1. Open https://musilon.com in Chrome or Edge and log in to your VIP account.", guide_card)
        guide_step2 = CaptionLabel("2. Press F12 (Developer Tools) → Application tab → Storage → Cookies → https://musilon.com.", guide_card)
        guide_step3 = CaptionLabel("3. Copy the value of `wordpress_logged_in_*` (or right-click → copy all cookies) and click Paste above.", guide_card)

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
        cooldown_info.addWidget(cooldown_title)
        cooldown_info.addWidget(cooldown_desc)

        spin_box_layout = QHBoxLayout()
        spin_box_layout.setSpacing(10)

        min_lbl = CaptionLabel("Min:", musilon_card)
        self.cooldown_min_spin = SpinBox(musilon_card)
        self.cooldown_min_spin.setRange(0, 300)
        self.cooldown_min_spin.setValue(int(config.get("musilon.cooldown_min_sec", 15)))
        self.cooldown_min_spin.setFixedWidth(85)
        self.cooldown_min_spin.valueChanged.connect(self._on_cooldown_min_changed)

        max_lbl = CaptionLabel("Max:", musilon_card)
        self.cooldown_max_spin = SpinBox(musilon_card)
        self.cooldown_max_spin.setRange(0, 300)
        self.cooldown_max_spin.setValue(int(config.get("musilon.cooldown_max_sec", 35)))
        self.cooldown_max_spin.setFixedWidth(85)
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
        s_layout.addWidget(s_desc)

        s_btn_row = QHBoxLayout()
        self.open_sp_dash_btn = PushButton(FluentIcon.LINK, "Open Spotify Developer Dashboard", spotify_card)
        self.open_sp_dash_btn.clicked.connect(lambda: subprocess.Popen(["cmd", "/c", "start", "https://developer.spotify.com/dashboard"]))
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
        yt_guide_step2 = CaptionLabel("2. Open youtube.com and ensure you are logged into your Google account.", yt_guide_card)
        yt_guide_step3 = CaptionLabel("3. Click the extension icon and click 'Export As cookies.txt'.", yt_guide_card)
        yt_guide_step4 = CaptionLabel("4. Select the exported file via 'Browse...' above (or save it as 'cookies.txt' in the app folder).", yt_guide_card)

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
        clean_info.addWidget(clean_title)
        clean_info.addWidget(clean_desc)

        self.clean_lib_btn = PushButton(FluentIcon.DELETE, "Clean Library", down_card)
        self.clean_lib_btn.clicked.connect(self._clean_library)

        clean_row.addLayout(clean_info, 1)
        clean_row.addWidget(self.clean_lib_btn)
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
        art_info.addWidget(art_title)
        art_info.addWidget(art_desc)

        self.art_switch = SwitchButton(tag_card)
        self.art_switch.setChecked(config.get("download.embed_cover_art", True))
        self.art_switch.checkedChanged.connect(lambda v: config.set("download.embed_cover_art", v))

        art_row.addLayout(art_info, 1)
        art_row.addWidget(self.art_switch)
        t_layout.addLayout(art_row)

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
        ff_layout.addWidget(ff_desc)

        # Download / Reinstall Action Row
        ff_action_row = QHBoxLayout()
        ff_action_row.setSpacing(10)

        self.download_ffmpeg_btn = PushButton(FluentIcon.DOWNLOAD, "Download / Reinstall Standalone FFmpeg", ffmpeg_card)
        self.download_ffmpeg_btn.clicked.connect(self._download_ffmpeg)

        self.ffmpeg_status_label = CaptionLabel("", ffmpeg_card)
        self.ffmpeg_status_label.setStyleSheet("font-size: 11px;")

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
        maint_layout.addWidget(maint_desc)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        self.repair_lib_btn = PushButton(FluentIcon.SYNC, "Scan & Auto-Repair All Tracks", maint_card)
        self.repair_lib_btn.clicked.connect(self._repair_library)

        self.clean_lib_btn = PushButton(FluentIcon.DELETE, "Clean Corrupt Files & Cache", maint_card)
        self.clean_lib_btn.clicked.connect(self._clean_library)

        btn_row.addWidget(self.repair_lib_btn)
        btn_row.addWidget(self.clean_lib_btn)
        btn_row.addStretch(1)
        maint_layout.addLayout(btn_row)

        self.maint_status_label = CaptionLabel("", maint_card)
        self.maint_status_label.setStyleSheet("font-size: 11px;")
        maint_layout.addWidget(self.maint_status_label)

        main_layout.addWidget(maint_card)
        main_layout.addStretch(1)

        # Check initial status
        self._update_status_badge()
        self._update_ffmpeg_badge()

    # -------------------------------------------------------------------------
    # Event Handlers
    # -------------------------------------------------------------------------
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

    def _on_fallback_switch_changed(self, enabled: bool):
        config.set("download.allow_fallback", enabled)
        if enabled:
            InfoBar.info("Safety-Net Fallback Enabled", "YouTube Music fallback is active if Musilon has no match.", duration=3000, parent=self)
        else:
            InfoBar.warning("Strict Musilon Mode", "YouTube fallback disabled. Downloads restricted strictly to Musilon.", duration=3500, parent=self)

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
            InfoBar.warning("Empty Credentials", "Please enter your Musilon username and password.", parent=self)
            return

        self.login_btn.setEnabled(False)
        self.login_btn.setText("Logging In...")
        self.result_label.setText("Attempting automated login to musilon.com...")

        def worker():
            success, msg = self.musilon_engine.login_with_credentials(user, pwd)
            self.sig_login_result.emit(success, msg)

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
            self._set_status_badge(True)
            InfoBar.success("Login Successful", "Authenticated with Musilon VIP account!", duration=4000, parent=self)
        else:
            self._set_status_badge(False)
            InfoBar.error("Login Failed", msg, duration=5000, parent=self)

    def _test_musilon(self, *args):
        self.test_btn.setEnabled(False)
        self.test_btn.setText("Connecting...")
        self.result_label.setText("Testing connection to musilon.com...")

        def worker():
            connected, is_vip, msg = self.musilon_engine.test_connection()
            self.sig_test_result.emit(connected, is_vip, msg)

        threading.Thread(target=worker, daemon=True).start()

    def _on_test_finished(self, connected: bool, is_vip: bool, msg: str):
        self.test_btn.setEnabled(True)
        self.test_btn.setText("Test Connection & VIP Status")
        self.result_label.setText(msg)

        if is_vip:
            self._set_status_badge(True)
            InfoBar.success("VIP Session Valid", msg, duration=4500, parent=self)
        elif connected:
            self._set_status_badge(False, text="Guest Connected")
            InfoBar.warning("Unauthenticated", msg, duration=5000, parent=self)
        else:
            self._set_status_badge(False, text="Offline")
            InfoBar.error("Connection Failed", msg, duration=5000, parent=self)

    def _update_status_badge(self):
        cookie = self.cookie_input.text().strip()
        has_auth = "wordpress_logged_in" in cookie or "wordpress_sec" in cookie
        self._set_status_badge(has_auth)

    def _set_status_badge(self, is_vip: bool, text: str = ""):
        if is_vip:
            self.status_badge.setText("VIP Active" if not text else text)
            self.status_badge.setStyleSheet(
                "background-color: rgba(29, 185, 84, 0.2); color: #1ED760; "
                "padding: 3px 10px; border-radius: 10px; font-weight: bold; border: 1px solid #1DB954;"
            )
        else:
            self.status_badge.setText("Not Authenticated" if not text else text)
            self.status_badge.setStyleSheet(
                "background-color: rgba(239, 68, 68, 0.15); color: #F87171; "
                "padding: 3px 10px; border-radius: 10px; font-weight: bold; border: 1px solid rgba(239, 68, 68, 0.4);"
            )

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
            if client.has_user_auth():
                user_name = client.get_current_user_name()
                user_str = f" as @{user_name}" if user_name else ""
                self.sp_status_badge.setText(f"Authorized{user_str} (Full Access Active)")
                self.sp_status_badge.setStyleSheet(
                    "background-color: rgba(29, 185, 84, 0.2); color: #1ED760; "
                    "padding: 3px 10px; border-radius: 10px; font-weight: bold; border: 1px solid #1DB954;"
                )
                self.auth_sp_btn.setText("Switch Account / Re-Authorize")
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
                    self.sig_spotify_auth_result.emit(True, msg)
                else:
                    self.sig_spotify_auth_result.emit(False, "Authorization was cancelled or did not return tokens.")
            except Exception as e:
                self.sig_spotify_auth_result.emit(False, str(e))

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
                self.sig_spotify_result.emit(True, f"API Verified: '{res[0].title}' — {auth_status}")
            except Exception as e:
                self.sig_spotify_result.emit(False, str(e))

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
            self.sig_ffmpeg_progress.emit(pct, msg)

        def worker():
            res = download_ffmpeg(progress_callback=progress_cb)
            if res:
                self.sig_ffmpeg_finished.emit(True, f"FFmpeg installed at {res}")
            else:
                self.sig_ffmpeg_finished.emit(False, "FFmpeg download or validation failed.")

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

        def worker():
            try:
                arc = ArchiveManager()
                stats = arc.purge_corrupt_and_cleanup_library()
                msg = (
                    f"Purged {stats['purged_corrupt_files']} corrupt HTML files, "
                    f"relocated {stats['relocated_covers']} covers to cache, "
                    f"reorganized {stats['reorganized_lyrics']} lyrics files."
                )
                QTimer.singleShot(0, lambda: self._on_clean_finished(True, msg))
            except Exception as e:
                QTimer.singleShot(0, lambda: self._on_clean_finished(False, str(e)))

        threading.Thread(target=worker, daemon=True).start()

    def _on_clean_finished(self, success: bool, msg: str):
        self.clean_lib_btn.setEnabled(True)
        self.clean_lib_btn.setText("Clean Corrupt Files & Cache")
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
            QTimer.singleShot(0, lambda: self.maint_status_label.setText(f"[{cur}/{total}] {msg}"))

        def worker():
            try:
                arc = ArchiveManager()
                stats = arc.repair_library(progress_callback=progress_cb)
                msg = (
                    f"Audit complete: {stats['scanned']} files scanned. "
                    f"Healed {stats['healed_covers']} covers, "
                    f"embedded {stats['healed_lyrics']} lyrics."
                )
                QTimer.singleShot(0, lambda: self._on_repair_finished(True, msg))
            except Exception as e:
                QTimer.singleShot(0, lambda: self._on_repair_finished(False, str(e)))

        threading.Thread(target=worker, daemon=True).start()

    def _on_repair_finished(self, success: bool, msg: str):
        self.repair_lib_btn.setEnabled(True)
        self.repair_lib_btn.setText("Scan & Auto-Repair All Tracks")
        self.maint_status_label.setText(msg)
        if success:
            InfoBar.success("Library Repaired", msg, duration=5000, parent=self)
        else:
            InfoBar.error("Repair Error", f"Failed to repair library: {msg}", duration=5000, parent=self)

