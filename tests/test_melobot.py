import os
import unittest
from unittest.mock import MagicMock, patch

from core.config import config
from core.melobot import MeloBotEngine, MeloBotSource, MeloBotDownloadError, MeloBotError
from core.resolver import CascadingAudioEngine, ResolvedTrackSource
from core.spotify_client import TrackMetadata


class TestMeloBotIntegration(unittest.TestCase):
    def setUp(self):
        self.original_source = config.get("source_engine", "musilon")
        self.original_tg_enabled = config.get("telegram.enabled", False)
        self.original_fallback = config.get("download.allow_fallback", True)

    def tearDown(self):
        config.set("source_engine", self.original_source)
        config.set("telegram.enabled", self.original_tg_enabled)
        config.set("download.allow_fallback", self.original_fallback)

    def test_engine_initialization(self):
        engine = MeloBotEngine(session_name="test_dummy_unauth_session")
        self.assertEqual(engine.api_id, 2040)
        self.assertEqual(engine.bot_username, "melobot")
        self.assertFalse(engine.is_authorized())

    def test_melobot_source_dataclass(self):
        src = MeloBotSource(
            track_id="sp_123",
            title="Song Title",
            artist="Artist Name",
            quality_tier="MeloBot FLAC",
            message_id=456,
            chat_id=789,
            file_extension="flac",
            file_size=25000000
        )
        self.assertEqual(src.track_id, "sp_123")
        self.assertEqual(src.file_extension, "flac")
        self.assertEqual(src.quality_tier, "MeloBot FLAC")

    def test_resolver_routes_to_melobot_when_primary(self):
        mock_melobot = MagicMock(spec=MeloBotEngine)
        mock_melobot.enabled = True
        mock_source = MeloBotSource(
            track_id="sp_test",
            title="Test Song",
            artist="Test Artist",
            quality_tier="MeloBot 320k",
            message_id=100,
            chat_id=200,
            file_extension="mp3"
        )
        mock_melobot.resolve_track.return_value = mock_source

        engine = CascadingAudioEngine(melobot_engine=mock_melobot)
        track = TrackMetadata(id="sp_test", title="Test Song", artists=["Test Artist"], album="Test Album")

        config.set("source_engine", "melobot")
        config.set("telegram.enabled", True)

        resolved = engine.resolve_source(track)
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved.source_type, "MeloBot")
        self.assertEqual(resolved.quality_badge, "MeloBot 320k")
        self.assertEqual(resolved.file_extension, "mp3")
        mock_melobot.resolve_track.assert_called_once()

    def test_resolver_falls_back_to_ytm_when_melobot_fails(self):
        mock_melobot = MagicMock(spec=MeloBotEngine)
        mock_melobot.enabled = True
        mock_melobot.resolve_track.return_value = None  # MeloBot cannot find track

        mock_yt = MagicMock()
        mock_yt_source = MagicMock()
        mock_yt_source.audio_format = "opus"
        mock_yt.resolve_track.return_value = mock_yt_source

        engine = CascadingAudioEngine(melobot_engine=mock_melobot, ytdlp_engine=mock_yt)
        track = TrackMetadata(id="sp_test_fallback", title="Unknown Song", artists=["Unknown Artist"], album="Unknown Album")

        config.set("source_engine", "melobot")
        config.set("download.allow_fallback", True)

        resolved = engine.resolve_source(track)
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved.source_type, "YouTube Music")
        self.assertEqual(resolved.quality_badge, "YTM Opus")
        mock_melobot.resolve_track.assert_called_once()
        mock_yt.resolve_track.assert_called_once()

    def test_telegram_login_dialog_flow(self):
        import sys, time
        from PyQt6.QtWidgets import QApplication, QWidget
        from gui.views.settings_view import TelegramLoginDialog

        app = QApplication.instance() or QApplication(sys.argv)
        parent = QWidget()
        parent.resize(800, 600)

        mock_engine = MagicMock()
        mock_engine.send_code.return_value = {"success": True, "phone_code_hash": "hash_xyz"}
        mock_engine.sign_in.return_value = {"success": True, "user": {"first_name": "AntigravityUser", "phone": "989123456789"}}

        diag = TelegramLoginDialog(mock_engine, parent=parent)
        self.assertFalse(diag.validate(), "validate() must return False so MessageBoxBase does not close early")
        self.assertFalse(diag.yesButton.isEnabled(), "Log In button should initially be disabled")

        diag.phone_input.setText("+989139758747")
        diag._on_send_code_clicked()

        t0 = time.time()
        while time.time() - t0 < 2.0:
            app.processEvents()
            if diag.send_code_btn.isEnabled():
                break
            time.sleep(0.02)

        self.assertEqual(diag._phone_code_hash, "hash_xyz")
        self.assertIn("Code sent", diag.status_label.text())

        diag.code_input.setText("77875")
        self.assertTrue(diag.yesButton.isEnabled(), "Log In button should dynamically enable with code")

        diag._on_login_clicked()
        t0 = time.time()
        while time.time() - t0 < 2.0:
            app.processEvents()
            if "Success" in diag.status_label.text():
                break
            time.sleep(0.02)

        self.assertIn("Success", diag.status_label.text())
        mock_engine.sign_in.assert_called_once_with(
            code="77875", password=None, phone_code_hash="hash_xyz", phone="+989139758747"
        )


    def test_candidate_scoring_perfect_match(self):
        engine = MeloBotEngine(session_name="test_dummy")
        track = TrackMetadata(
            id="sp_gary",
            title="Still Got The Blues",
            artists=["Gary Moore"],
            album="Still Got The Blues"
        )

        candidates = [
            "🎵 Gary Moore, Still Got the Blues",
            "📀 Gary Moore, Still Got the Blues",
            "🎵 Gary Moore, Still Got The Blues - Live from the Blues Alive T…",
            "🗣 Gary Moore",
            "🎵 John Mayer, Still Got the Blues",
            "⬅️ صفحه اصلی"
        ]

        scores = {c: engine._score_candidate(c, track) for c in candidates}
        # Clean studio track should have highest score and > 40
        self.assertGreater(scores["🎵 Gary Moore, Still Got the Blues"], 100.0)
        # Studio single is preferred over album
        self.assertGreater(
            scores["🎵 Gary Moore, Still Got the Blues"],
            scores["📀 Gary Moore, Still Got the Blues"]
        )
        # Live version disqualified for studio request
        self.assertEqual(scores["🎵 Gary Moore, Still Got The Blues - Live from the Blues Alive T…"], -1.0)
        # Artist button and navigation disqualified
        self.assertEqual(scores["🗣 Gary Moore"], -1.0)
        self.assertEqual(scores["⬅️ صفحه اصلی"], -1.0)
        # Cover by different artist disqualified
        self.assertEqual(scores["🎵 John Mayer, Still Got the Blues"], -1.0)

    def test_candidate_scoring_persian_and_variants(self):
        engine = MeloBotEngine(session_name="test_dummy")
        track = TrackMetadata(
            id="sp_shadmehr",
            title="تقدیر",
            artists=["شادمهر عقیلی"],
            album="تقدیر"
        )

        candidates = [
            "🎵 شادمهر عقیلی، تقدیر",
            "🎵 شادمهر عقیلی، تقدیر (ریمیکس)",
            "🎵 شادمهر عقیلی، تقدیر (کنسرت دبی)",
            "🎵 شادمهر عقیلی، تقدیر (بی کلام)",
            "🎵 مهدی یراحی، تقدیر"
        ]

        scores = {c: engine._score_candidate(c, track) for c in candidates}
        self.assertGreater(scores["🎵 شادمهر عقیلی، تقدیر"], 100.0)
        self.assertEqual(scores["🎵 شادمهر عقیلی، تقدیر (ریمیکس)"], -1.0)
        self.assertEqual(scores["🎵 شادمهر عقیلی، تقدیر (کنسرت دبی)"], -1.0)
        self.assertEqual(scores["🎵 شادمهر عقیلی، تقدیر (بی کلام)"], -1.0)
        self.assertEqual(scores["🎵 مهدی یراحی، تقدیر"], -1.0)

    def test_queue_manager_effective_concurrency_serialization(self):
        from core.queue_manager import DownloadQueueManager
        qm = DownloadQueueManager(max_concurrent_downloads=5)

        # 1. When source is Musilon, concurrency respects user setting (5)
        config.set("source_engine", "musilon")
        config.set("musilon.enabled", True)
        config.set("telegram.enabled", False)
        self.assertEqual(qm.get_effective_concurrency(), 5)

        # 2. When source is MeloBot, concurrency is strictly locked to 1
        config.set("source_engine", "melobot")
        config.set("telegram.enabled", True)
        self.assertEqual(qm.get_effective_concurrency(), 1)

        # 3. Dynamic scaling back to Musilon restores 5
        config.set("source_engine", "musilon")
        config.set("musilon.enabled", True)
        config.set("telegram.enabled", False)
        self.assertEqual(qm.get_effective_concurrency(), 5)


    def test_multi_artist_and_album_tracklist_matching(self):
        engine = MeloBotEngine(session_name="test_dummy")
        track = TrackMetadata(
            id="4DwfypvzPkpvaAreeCS8Ex",
            title="Naghshe Khial",
            artists=["Shayan Gorjidouz", "Homayoun Shajarian", "Ali Ghamsari"],
            album="Naghshe Khial"
        )

        # 1. Main Search Candidates
        candidates = [
            "📀 Homayoun Shajarian, Naghshe Khial",
            "🎵 Homayoun Shajarian, Naghshe Khial (Instrumental)",
            "🎵 Shayan Shirin, Bikhial",
            "🎵 Pooria Mirzaee, Naghshe Khial",
            "🗣 Shayan Yo"
        ]

        # Multi-artist should recognize Homayoun Shajarian and select the authentic album/track
        score_homayoun = engine._score_candidate(candidates[0], track)
        score_wrong = engine._score_candidate(candidates[2], track)  # Shayan Shirin, Bikhial
        self.assertGreater(score_homayoun, 100.0)
        self.assertEqual(score_wrong, -1.0)  # Bikhial != Naghshe Khial, rejected

        # 2. Album Tracklist Menu
        album_tracks = [
            "🎵 Moghadameye Nava x 198.1k",
            "🎵 Naghshe Khial (Saaz Va Avaz) x 295k",
            "🎵 Naghshe Khial (Instrumental) x 194.3k",
            "🎵 Naghshe Khial (Ham Navazi Taar Va Tonbak) x 192.9k",
            "دانلود همه (عالی)"
        ]

        score_vocal = engine._score_candidate(album_tracks[1], track, is_album_menu=True)
        score_inst = engine._score_candidate(album_tracks[2], track, is_album_menu=True)
        score_bulk = engine._score_candidate(album_tracks[4], track, is_album_menu=True)

        self.assertGreater(score_vocal, 75.0)
        self.assertGreater(score_vocal, score_inst)
        self.assertEqual(score_bulk, -1.0)

    def test_compound_artist_and_coartist_limits(self):
        engine = MeloBotEngine(session_name="test_dummy")
        track = TrackMetadata(
            id="test_chashm",
            title="Chashm Yari",
            artists=["Shayan Gorjidouz", "Mohammad-Reza Shajarian"],
            album="Nava"
        )

        # 1. Compound Transliteration matching (Mohammad-Reza -> Mohammadreza)
        btn_correct = "🎵 Mohammadreza Shajarian, Tasnife Chasme Yari"
        btn_wrong = "🎬🎵 Bidad, Chashme Yari"
        btn_unrelated = "🎵 Shayan Shirin, Bikhial"

        score_correct = engine._score_candidate(btn_correct, track)
        score_wrong = engine._score_candidate(btn_wrong, track)
        score_unrelated = engine._score_candidate(btn_unrelated, track)

        self.assertGreater(score_correct, 90.0)
        self.assertEqual(score_wrong, -1.0)
        self.assertEqual(score_unrelated, -1.0)

    def test_candidate_vs_quality_button_isolation(self):
        """
        Guarantees candidate buttons containing 'Original' (e.g. Original Studio Cast)
        are never mistaken for quality buttons (320k/VIP).
        """
        import asyncio
        engine = MeloBotEngine(session_name="test_dummy")
        track = TrackMetadata(
            id="test_goosebumps",
            title="Goosebumps - Remix",
            artists=["Travis Scott", "HVME"],
            album="Goosebumps (Remix)",
            duration_ms=162000
        )

        # Mock candidate message
        mock_cand_btn_1 = MagicMock()
        mock_cand_btn_1.text = "🎵 Goosebumps Original Studio Cast Recording Company"
        mock_cand_btn_1.click = unittest.mock.AsyncMock()
        mock_cand_btn_2 = MagicMock()
        mock_cand_btn_2.text = "🎵 Travis Scott - Goosebumps (HVME Remix)"
        mock_cand_btn_2.click = unittest.mock.AsyncMock()

        mock_msg = MagicMock()
        mock_msg.text = "نتایج جستجو:"
        mock_msg.buttons = [[mock_cand_btn_1], [mock_cand_btn_2]]

        # Run _handle_bot_keyboard
        clicked = asyncio.run(engine._handle_bot_keyboard(mock_msg, track, "bot_entity"))
        self.assertTrue(clicked)
        # Should click the authentic candidate mock_cand_btn_2, NEVER mock_cand_btn_1
        mock_cand_btn_2.click.assert_called_once()
        mock_cand_btn_1.click.assert_not_called()

        # Mock quality message (including MeloBot's '🗣 خوانندهها' info button)
        mock_q_btn_320 = MagicMock()
        mock_q_btn_320.text = "📥 کیفیت عالی"
        mock_q_btn_320.click = unittest.mock.AsyncMock()
        mock_q_btn_128 = MagicMock()
        mock_q_btn_128.text = "📥 کیفیت معمولی"
        mock_q_btn_128.click = unittest.mock.AsyncMock()
        mock_singer_btn = MagicMock()
        mock_singer_btn.text = "🗣 خوانندهها"
        mock_singer_btn.click = unittest.mock.AsyncMock()

        mock_q_msg = MagicMock()
        mock_q_msg.text = "خب حالا میخوای با این آهنگ چه کنی ؟"
        mock_q_msg.buttons = [
            [mock_q_btn_128, mock_q_btn_320],
            [mock_singer_btn]
        ]

        clicked_q = asyncio.run(engine._handle_bot_keyboard(mock_q_msg, track, "bot_entity"))
        self.assertTrue(clicked_q)
        mock_q_btn_320.click.assert_called_once()
        mock_q_btn_128.click.assert_not_called()
        mock_singer_btn.click.assert_not_called()


if __name__ == "__main__":
    unittest.main()

