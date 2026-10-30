import os
import shutil
import subprocess
import tempfile
import unittest

from core.archive import ArchiveManager
from core.lyrics import LyricsData
from core.spotify_client import TrackMetadata
from core.tagger import AudioTagger
from core.utils import (
    EQ_FREQUENCIES,
    EQ_PRESETS,
    apply_equalizer_to_file,
    build_equalizer_af_filter,
    compute_acoustic_fingerprint,
    ensure_ffmpeg,
    extract_embedded_lyrics,
    fingerprint_similarity,
    inspect_audio_spectrum,
    render_equalizer_preview,
)


def _generate_sine_sweep_mp3(path: str, lowpass_hz: int = 0, bitrate: str = "320k"):
    """Generates a 10-second multi-tone audio file (with optional low-pass filter to simulate fake transcode)."""
    ffmpeg_bin = ensure_ffmpeg() or "ffmpeg"
    expr = (
        "0.25*sin(2*PI*440*t)+0.15*sin(2*PI*4000*t)+0.12*sin(2*PI*12000*t)+"
        "0.10*sin(2*PI*16000*t)+0.08*sin(2*PI*18500*t)+0.07*sin(2*PI*19800*t)"
    )
    af = f"lowpass=f={lowpass_hz}:poles=2,lowpass=f={lowpass_hz}:poles=2" if lowpass_hz > 0 else "anull"
    cmd = [
        ffmpeg_bin, "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", f"aevalsrc='{expr}':s=44100:d=10",
        "-af", af,
        "-c:a", "libmp3lame", "-b:a", bitrate,
        path,
    ]
    subprocess.run(cmd, check=True)


class TestV170Features(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="sp_dl_v170_test_")
        self.db_path = os.path.join(self.tmp_dir, "test_archive.db")
        self.archive = ArchiveManager(db_path=self.db_path)

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    # -----------------------------------------------------------------
    # 1. Synchronized Lyrics & 10-Band Equalizer
    # -----------------------------------------------------------------
    def test_extract_embedded_lyrics_and_equalizer(self):
        mp3_path = os.path.join(self.tmp_dir, "test_lyrics_eq.mp3")
        _generate_sine_sweep_mp3(mp3_path)

        track = TrackMetadata(
            id="sp_test_1",
            title="Test Song",
            artists=["Test Artist"],
            album="Test Album",
            duration_ms=10000,
        )
        synced_lrc = "[00:01.00] First line of karaoke\n[00:04.50] Second line of karaoke\n[00:08.00] Final line"
        AudioTagger().tag_file(
            mp3_path,
            track,
            lyrics_data=LyricsData(synced_lyrics=synced_lrc, plain_lyrics="First line of karaoke\nSecond line of karaoke\nFinal line"),
            embed_art=False,
            embed_lyrics=True,
        )

        extracted = extract_embedded_lyrics(mp3_path)
        self.assertIn("[00:01.00] First line of karaoke", extracted)
        self.assertIn("[00:04.50] Second line of karaoke", extracted)

        # Verify EQ filter builder
        self.assertEqual(len(EQ_FREQUENCIES), 10)
        self.assertIn("Bass Boost", EQ_PRESETS)
        flat_filter = build_equalizer_af_filter([0.0] * 10, preamp_db=0.0, bass_boost_db=0.0)
        self.assertEqual(flat_filter, "anull")

        bass_filter = build_equalizer_af_filter(EQ_PRESETS["Bass Boost"], preamp_db=1.5, bass_boost_db=4.0)
        self.assertIn("bass=g=4.00:f=85", bass_filter)
        self.assertIn("equalizer=f=31", bass_filter)
        self.assertIn("alimiter=", bass_filter)

        # Verify live preview render & permanent apply_equalizer_to_file preserve embedded lyrics
        preview_path = render_equalizer_preview(mp3_path, EQ_PRESETS["Bass Boost"], preamp_db=1.0, bass_boost_db=3.0)
        self.assertIsNotNone(preview_path)
        self.assertTrue(os.path.isfile(preview_path))
        if preview_path != mp3_path:
            try:
                os.remove(preview_path)
            except Exception:
                pass

        ok = apply_equalizer_to_file(mp3_path, EQ_PRESETS["Rock / Metal"], preamp_db=0.5, bass_boost_db=2.0)
        self.assertTrue(ok)
        # Ensure embedded lyrics survived permanent EQ rendering
        extracted_after = extract_embedded_lyrics(mp3_path)
        self.assertIn("[00:01.00] First line of karaoke", extracted_after)

    # -----------------------------------------------------------------
    # 2. Scheduled Auto-Sync ("Watch Playlists")
    # -----------------------------------------------------------------
    def test_watch_playlists_auto_sync(self):
        t1 = TrackMetadata(id="tr_1", title="One", artists=["Art"], album="Alb", duration_ms=180000)
        t2 = TrackMetadata(id="tr_2", title="Two", artists=["Art"], album="Alb", duration_ms=190000)

        self.archive.save_playlist("Alpha Playlist", "https://open.spotify.com/playlist/pl_alpha", "", [t1], playlist_id="pl_alpha")
        self.archive.save_playlist("Beta Playlist", "https://open.spotify.com/playlist/pl_beta", "", [t1, t2], playlist_id="pl_beta")

        self.assertEqual(len(self.archive.get_watched_playlists()), 0)

        # Enable Watch / Auto-Sync on Beta Playlist
        self.archive.set_playlist_auto_sync("pl_beta", True)
        watched = self.archive.get_watched_playlists()
        self.assertEqual(len(watched), 1)
        self.assertEqual(watched[0]["id"], "pl_beta")
        self.assertTrue(watched[0]["auto_sync"])

        # Watched playlists should sort first in get_saved_playlists()
        all_pls = self.archive.get_saved_playlists()
        self.assertEqual(all_pls[0]["id"], "pl_beta")

        # Syncing playlist updates last_synced_at and returns delta
        t3 = TrackMetadata(id="tr_3", title="Three", artists=["Art"], album="Alb", duration_ms=200000)
        sync_res = self.archive.sync_saved_playlist("pl_beta", [t1, t2, t3])
        self.assertEqual(sync_res["added"], 1)
        updated_pl = self.archive.get_saved_playlist("pl_beta")
        self.assertTrue(bool(updated_pl.get("last_synced_at")))

    # -----------------------------------------------------------------
    # 3. True Audio Spectrum / Fake-Bitrate Inspector
    # -----------------------------------------------------------------
    def test_audio_spectrum_inspector(self):
        true_320_path = os.path.join(self.tmp_dir, "true_320.mp3")
        fake_320_path = os.path.join(self.tmp_dir, "fake_transcode_13k.mp3")

        _generate_sine_sweep_mp3(true_320_path, lowpass_hz=0, bitrate="320k")
        _generate_sine_sweep_mp3(fake_320_path, lowpass_hz=12500, bitrate="320k")

        res_true = inspect_audio_spectrum(true_320_path, generate_spectrogram=True)
        self.assertIsNotNone(res_true)
        self.assertGreaterEqual(res_true["cutoff_khz"], 18.5)
        self.assertEqual(res_true["verdict"], "authentic")
        self.assertTrue(os.path.isfile(res_true["spectrogram_path"]))

        res_fake = inspect_audio_spectrum(fake_320_path, generate_spectrogram=False)
        self.assertIsNotNone(res_fake)
        self.assertLess(res_fake["cutoff_khz"], 16.8)
        self.assertEqual(res_fake["verdict"], "upscaled")

    # -----------------------------------------------------------------
    # 4. Smart Duplicate & Acoustic Fingerprint Merger
    # -----------------------------------------------------------------
    def test_duplicate_detector_and_merger(self):
        folder_a = os.path.join(self.tmp_dir, "Playlist_A")
        folder_b = os.path.join(self.tmp_dir, "Playlist_B")
        os.makedirs(folder_a, exist_ok=True)
        os.makedirs(folder_b, exist_ok=True)

        file_a = os.path.join(folder_a, "Artist - DupSong.mp3")
        file_b = os.path.join(folder_b, "Artist - DupSong.mp3")
        _generate_sine_sweep_mp3(file_a, lowpass_hz=0, bitrate="320k")
        shutil.copy2(file_a, file_b)

        # Verify acoustic fingerprint similarity on identical audio
        fp_a = compute_acoustic_fingerprint(file_a)
        fp_b = compute_acoustic_fingerprint(file_b)
        self.assertIsNotNone(fp_a)
        self.assertGreaterEqual(fingerprint_similarity(fp_a, fp_b), 0.95)

        t_a = TrackMetadata(
            id="sp_dup_1",
            title="DupSong",
            artists=["Artist"],
            album="Album A",
            duration_ms=10000,
            isrc="USAAA2600001",
            collection_name="Playlist A",
            collection_type="playlist",
        )
        t_b = TrackMetadata(
            id="sp_dup_2",
            title="DupSong (Remastered)",
            artists=["Artist"],
            album="Album B",
            duration_ms=10000,
            isrc="USAAA2600001",
            collection_name="Playlist B",
            collection_type="playlist",
        )
        self.archive.add_track(t_a, file_a, "320k MP3", "Musilon")
        self.archive.add_track(t_b, file_b, "320k MP3", "Musilon")

        groups = self.archive.find_library_duplicates(root_dir=self.tmp_dir, use_acoustic_fingerprint=False)
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(groups[0]["duplicates"]), 1)

        # Test Hard-Link consolidation first
        stats_hl = self.archive.merge_library_duplicates(groups, mode="hardlink")
        self.assertEqual(stats_hl["groups_processed"], 1)
        self.assertTrue(os.path.isfile(file_a))
        self.assertTrue(os.path.isfile(file_b))
        self.assertEqual(os.stat(file_a).st_ino, os.stat(file_b).st_ino)

        # Now create a separate second physical copy and test Clean Merge mode
        file_c = os.path.join(folder_b, "Artist - DupSong Copy2.mp3")
        _generate_sine_sweep_mp3(file_c, lowpass_hz=0, bitrate="192k")
        t_c = TrackMetadata(
            id="sp_dup_3",
            title="DupSong",
            artists=["Artist"],
            album="Album C",
            duration_ms=10000,
            isrc="USAAA2600001",
            collection_name="Playlist B",
            collection_type="playlist",
        )
        self.archive.add_track(t_c, file_c, "YTM Opus", "YouTube Music")

        groups2 = self.archive.find_library_duplicates(root_dir=self.tmp_dir, use_acoustic_fingerprint=False)
        self.assertEqual(len(groups2), 1)
        stats_merge = self.archive.merge_library_duplicates(groups2, mode="merge")
        self.assertEqual(stats_merge["groups_processed"], 1)
        self.assertGreaterEqual(stats_merge["files_merged"], 1)
        self.assertFalse(os.path.exists(file_c))
        # Database reference for sp_dup_3 should now point to the primary file
        row_c = self.archive.find_track(spotify_id="sp_dup_3")
        self.assertIsNotNone(row_c)
        self.assertTrue(os.path.isfile(row_c["file_path"]))

    # -----------------------------------------------------------------
    # 5. GUI Dialogs & Controls Instantiation Verification
    # -----------------------------------------------------------------
    def test_gui_v170_dialogs_and_controls(self):
        from unittest.mock import patch
        from PyQt6.QtWidgets import QApplication
        from core.lyrics import LyricsEngine
        from gui.dialogs.player_panels import KaraokeLyricsDrawer, EqualizerDialog
        from gui.player_bar import MiniPlayerBar

        app = QApplication.instance() or QApplication([])
        player_bar = MiniPlayerBar()
        self.assertTrue(hasattr(player_bar, "lyrics_btn"))
        self.assertTrue(hasattr(player_bar, "translate_btn"))
        self.assertTrue(hasattr(player_bar, "eq_btn"))

        drawer = KaraokeLyricsDrawer(player_bar)
        self.assertTrue(hasattr(drawer, "translate_off_btn"))
        self.assertTrue(hasattr(drawer, "translate_en_btn"))
        self.assertTrue(hasattr(drawer, "translate_fa_btn"))
        drawer.set_track_info(
            "Test Song",
            "Test Artist",
            [(1000, "Bonjour le monde"), (4000, "Yeah, yeah")],
            "Bonjour le monde\nYeah, yeah",
            has_synced=True,
        )
        drawer.update_active_line(1)
        self.assertEqual(drawer._active_idx, 1)

        # Verify bilingual translation display on LyricLineRow (English & Persian)
        drawer.current_trans_lang = "en"
        drawer._on_translation_ready("en", ["Hello world", "Yeah, yeah"])
        self.assertEqual(drawer.line_widgets[0].translated_text, "Hello world")
        self.assertFalse(drawer.line_widgets[0].trans_lbl.isHidden())
        # Same-language line ("Yeah, yeah" -> "Yeah, yeah") should hide redundant subtitle
        self.assertTrue(drawer.line_widgets[1].trans_lbl.isHidden())

        drawer.current_trans_lang = "fa"
        drawer._on_translation_ready("fa", ["سلام دنیا", "آره، آره"])
        self.assertEqual(drawer.line_widgets[1].translated_text, "آره، آره")
        self.assertIn("آره، آره", drawer.line_widgets[1].trans_lbl.text())

        # Verify LyricsEngine.translate_lyrics deduplication, batching & sanitization
        eng = LyricsEngine()
        self.assertEqual(eng._sanitize_translated_line("PLEASE SELECT TWO DISTINCT LANGUAGES", "Yeah, yeah"), "Yeah, yeah")
        with patch.object(eng, "_translate_batch_gtx", return_value=["سلام دنیا", "موسیقی زیباست"]):
            res_fa = eng.translate_lyrics(
                ["Bonjour le monde", "♪ Instrumental ♪", "La musique est belle", "Bonjour le monde"],
                target_lang="fa",
            )
            self.assertEqual(res_fa[0], "سلام دنیا")
            self.assertEqual(res_fa[1], "♪ Instrumental ♪")
            self.assertEqual(res_fa[2], "موسیقی زیباست")
            self.assertEqual(res_fa[3], "سلام دنیا")

        eq_dlg = EqualizerDialog(player_bar)
        self.assertEqual(len(eq_dlg.band_sliders), 10)
        drawer.close()
        eq_dlg.close()
        player_bar.close()

    # -----------------------------------------------------------------
    # 6. Spotify Web Studio Backend API & Byte-Range Audio Streaming
    # -----------------------------------------------------------------
    def test_web_studio_api_and_streaming(self):
        import urllib.request
        import json
        from unittest.mock import MagicMock
        from gui.web_api import FlacifyWebServer

        mp3_path = os.path.join(self.tmp_dir, "stream_test.mp3")
        _generate_sine_sweep_mp3(mp3_path, lowpass_hz=0, bitrate="192k")
        t1 = TrackMetadata(id="sp_web_1", title="Web Studio Song", artists=["Web Artist"], album="Web Album", duration_ms=10000)
        self.archive.add_track(t1, mp3_path, "320k MP3", "MeloBot")

        mock_qm = MagicMock()
        mock_qm.get_all_items.return_value = []
        mock_qm._paused = False

        web_root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui", "web_ui")
        server = FlacifyWebServer(queue_manager=mock_qm, archive_manager=self.archive, web_root=web_root)
        base_url = server.start()
        try:
            # Verify index.html & app.js
            with urllib.request.urlopen(f"{base_url}/") as resp:
                html = resp.read().decode("utf-8")
                self.assertIn("Flacify", html)
                self.assertIn("lyrics-drawer", html)

            # Verify /api/state
            with urllib.request.urlopen(f"{base_url}/api/state") as resp:
                st = json.loads(resp.read().decode("utf-8"))
                self.assertTrue(st["ok"])

            # Verify /api/library
            with urllib.request.urlopen(f"{base_url}/api/library?refresh=1") as resp:
                lib = json.loads(resp.read().decode("utf-8"))
                self.assertGreaterEqual(len(lib["tracks"]), 1)

            # Verify HTTP 206 Byte-Range audio streaming
            import urllib.parse
            req = urllib.request.Request(
                f"{base_url}/api/audio?path={urllib.parse.quote(mp3_path)}",
                headers={"Range": "bytes=0-1023"},
            )
            with urllib.request.urlopen(req) as resp:
                self.assertEqual(resp.status, 206)
                chunk = resp.read()
                self.assertEqual(len(chunk), 1024)
        finally:
            server.stop()


if __name__ == "__main__":
    unittest.main()
