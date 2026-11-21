import copy
import os
import shutil
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from backend.app import create_app
from backend.state import BackendState
from core.archive import ArchiveManager
from core.config import DEFAULT_CONFIG
from core.queue_manager import DownloadQueueManager
from core.spotify_client import TrackMetadata


class FakeConfig:
    """Isolated in-memory config store mimicking ConfigManager without touching disk."""

    def __init__(self):
        self._data = copy.deepcopy(DEFAULT_CONFIG)
        self._listeners = []
        self._lock = threading.RLock()
        self.save_calls = 0

    def get(self, key_path: str, default=None):
        keys = [k for k in key_path.split(".") if k]
        with self._lock:
            val = self._data
            for k in keys:
                if isinstance(val, dict) and k in val:
                    val = val[k]
                else:
                    return default
            return copy.deepcopy(val) if isinstance(val, (dict, list)) else val

    def set(self, key_path: str, value, auto_save: bool = True):
        keys = [k for k in key_path.split(".") if k]
        with self._lock:
            d = self._data
            for k in keys[:-1]:
                d = d.setdefault(k, {})
            d[keys[-1]] = copy.deepcopy(value) if isinstance(value, (dict, list)) else value
            listeners = list(self._listeners)
        for cb in listeners:
            cb(key_path, value)

    def save(self):
        self.save_calls += 1

    def add_listener(self, cb):
        with self._lock:
            if cb not in self._listeners:
                self._listeners.append(cb)

    def remove_listener(self, cb):
        with self._lock:
            if cb in self._listeners:
                self._listeners.remove(cb)


class TestBackendSettingsAndTools(unittest.TestCase):
    def setUp(self):
        self._prev_archive_instance = ArchiveManager._instance
        ArchiveManager._instance = None
        self.tmp_dir = tempfile.mkdtemp(prefix="flacify_settings_tools_test_")
        self.db_path = os.path.join(self.tmp_dir, "test_archive.db")
        self.archive = ArchiveManager(db_path=self.db_path)

        self.fake_config = FakeConfig()
        self.fake_config.set("download.output_dir", self.tmp_dir)
        self.fake_config.set("musilon.session_cookie", "__Secure-next-auth.session-token=supersecretcookievalue123")
        self.fake_config.set("musilon.username", "user@example.com")
        self.fake_config.set("musilon.password", "verysecretpassword")
        self.fake_config.set("spotify.client_id", "sp_client_id_123")
        self.fake_config.set("spotify.client_secret", "sp_client_secret_987654")

        self.mock_musilon = MagicMock()
        self.mock_melobot = MagicMock()
        self.mock_ytdlp = MagicMock()
        self.mock_lyrics = MagicMock()
        self.mock_tagger = MagicMock()
        self.mock_audio_engine = MagicMock()
        self.mock_spotify = MagicMock()

        self.qm = DownloadQueueManager(
            audio_engine=self.mock_audio_engine,
            archive_manager=self.archive,
            max_concurrent_downloads=5,
        )
        self.state = BackendState(
            archive_manager=self.archive,
            musilon_engine=self.mock_musilon,
            melobot_engine=self.mock_melobot,
            ytdlp_engine=self.mock_ytdlp,
            lyrics_engine=self.mock_lyrics,
            tagger=self.mock_tagger,
            audio_engine=self.mock_audio_engine,
            queue_manager=self.qm,
            spotify_client=self.mock_spotify,
            config_manager=self.fake_config,
            run_startup_scan=False,
            run_auto_sync_scheduler=False,
        )
        self.app = create_app(
            state=self.state,
            run_startup_scan=False,
            run_auto_sync_scheduler=False,
        )

    def tearDown(self):
        ArchiveManager._instance = self._prev_archive_instance
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _valid_flac_bytes(self, extra_pad: int = 0) -> bytes:
        hdr = (
            b"fLaC\x80\x00\x00\x22"
            + b"\x10\x00\x10\x00\x00\x00\x00\x00\x00\x00\x0a\xc4\x42\xf0\x00\x00\x00\x00"
            + b"\x00" * 16
        )
        return hdr + b"\x00" * (160 * 1024 + extra_pad - len(hdr))

    def _create_dummy_audio(self, rel_path: str, extra_pad: int = 0) -> str:
        full_path = os.path.join(self.tmp_dir, rel_path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "wb") as fh:
            fh.write(self._valid_flac_bytes(extra_pad=extra_pad))
        return full_path

    def _record_track(
        self,
        spotify_id: str,
        title: str,
        artist: str,
        rel_path: str,
        collection_name: str = "Mixtape",
        collection_type: str = "playlist",
    ) -> tuple[TrackMetadata, str]:
        fp = self._create_dummy_audio(rel_path)
        tr = TrackMetadata(
            id=spotify_id,
            title=title,
            artists=[artist],
            album="Test Album",
            duration_ms=200000,
            track_number=1,
            collection_type=collection_type,
            collection_name=collection_name,
            genres=["Electronic"],
        )
        self.archive.add_track(
            tr, fp, quality_badge="FLAC 16", source_type="Musilon", genre="Electronic"
        )
        return tr, fp

    def test_settings_get_masking_and_patch_side_effects(self):
        with TestClient(self.app) as client:
            r_get = client.get("/api/settings")
            self.assertEqual(r_get.status_code, 200)
            data = r_get.json()
            cfg = data["config"]

            self.assertNotIn("supersecretcookievalue123", cfg["musilon"]["session_cookie"])
            self.assertNotIn("verysecretpassword", cfg["musilon"]["password"])
            self.assertNotIn("sp_client_secret_987654", cfg["spotify"]["client_secret"])
            self.assertTrue(data["secrets_set"]["musilon_session_cookie"])
            self.assertTrue(data["secrets_set"]["musilon_password"])
            self.assertTrue(data["secrets_set"]["spotify_client_secret"])
            self.assertTrue(data["derived"]["musilon_configured"])
            self.assertEqual(data["derived"]["effective_source_engine"], "musilon")

            # Switch to melobot -> locks concurrency to 1 and disables musilon
            with patch.object(self.qm, "update_concurrency", wraps=self.qm.update_concurrency) as mock_upd:
                r_patch1 = client.patch(
                    "/api/settings",
                    json={"values": {"source_engine": "melobot"}},
                )
                self.assertEqual(r_patch1.status_code, 200)
                p1 = r_patch1.json()
                self.assertEqual(p1["derived"]["effective_source_engine"], "melobot")
                self.assertTrue(p1["derived"]["concurrency_locked"])
                self.assertEqual(p1["derived"]["effective_concurrency"], 1)
                self.assertFalse(self.fake_config.get("musilon.enabled"))
                self.assertTrue(self.fake_config.get("telegram.enabled"))
                self.assertFalse(self.mock_musilon.enabled)
                mock_upd.assert_called_with(1)

                # Switch back + change quality, lyrics_mode, cooldown & spotify creds
                r_patch2 = client.patch(
                    "/api/settings",
                    json={
                        "values": {
                            "source_engine": "musilon",
                            "download.concurrency": 7,
                            "download.preferred_quality": "flac",
                            "download.lyrics_mode": "separate_folder",
                            "musilon.cooldown_min_sec": 50,
                            "musilon.cooldown_max_sec": 30,
                            "spotify.client_id": "new_cid",
                        }
                    },
                )
                self.assertEqual(r_patch2.status_code, 200)
                p2 = r_patch2.json()
                self.assertEqual(p2["derived"]["effective_source_engine"], "musilon")
                self.assertEqual(p2["derived"]["effective_concurrency"], 7)
                self.assertEqual(
                    self.fake_config.get("download.quality_priority")[0],
                    "musilon_flac_16",
                )
                self.assertTrue(self.fake_config.get("download.save_lrc"))
                self.assertEqual(self.fake_config.get("musilon.cooldown_min_sec"), 30)
                self.assertEqual(self.fake_config.get("musilon.cooldown_max_sec"), 30)
                mock_upd.assert_called_with(7)
                self.mock_spotify.update_credentials.assert_called_with(
                    client_id="new_cid", client_secret="sp_client_secret_987654"
                )

            # Disallowed key / invalid enum rejected
            r_bad_key = client.patch("/api/settings", json={"values": {"version": 999}})
            self.assertEqual(r_bad_key.status_code, 400)

            r_bad_fmt = client.patch(
                "/api/settings", json={"values": {"download.target_format": "wav"}}
            )
            self.assertEqual(r_bad_fmt.status_code, 400)

    def test_musilon_telegram_spotify_ffmpeg_and_open_folder(self):
        fake_session = MagicMock()
        fake_session.cookies.get_dict.return_value = {
            "__Secure-next-auth.session-token": "fresh_token_xyz"
        }
        self.mock_musilon.session = fake_session
        self.mock_musilon.login_with_credentials.return_value = (True, "Logged in!")
        self.mock_musilon.test_connection.return_value = (
            True,
            True,
            True,
            "VIP Active (100/100)",
        )

        self.mock_melobot.is_authorized.side_effect = [False, True, False]
        self.mock_melobot.send_code.return_value = {
            "success": True,
            "phone_code_hash": "hash_abc_123",
        }
        self.mock_melobot.sign_in.side_effect = [
            {"success": False, "needs_password": True, "error": "2FA required"},
            {"success": True, "user": {"first_name": "Alex", "phone": "989120001122"}},
        ]
        self.mock_melobot.get_me.return_value = {
            "first_name": "Alex",
            "phone": "989120001122",
        }
        self.mock_melobot.log_out.return_value = True

        self.mock_spotify.has_user_auth.return_value = True
        self.mock_spotify._cached_user_name = "sp_user"
        self.mock_spotify.resolve.return_value = [
            TrackMetadata(
                id="3AJwUDP919kvQ9QcozQPxg",
                title="Yellow",
                artists=["Coldplay"],
                album="Parachutes",
            )
        ]
        self.mock_spotify.authorize_user.return_value = True
        self.mock_spotify.get_current_user_name.return_value = "sp_user"
        self.mock_spotify.get_auth_url.return_value = "https://accounts.spotify.com/authorize?x=1"
        self.mock_spotify.parse_and_save_auth_code.return_value = True

        with TestClient(self.app) as client:
            # Musilon rejects username without '@'
            r_bad_login = client.post(
                "/api/settings/musilon/login",
                json={"username": "notanemail", "password": "pw"},
            )
            self.assertEqual(r_bad_login.status_code, 400)

            r_login = client.post(
                "/api/settings/musilon/login",
                json={"username": "vip@example.com", "password": "pw", "run_test": True},
            )
            self.assertEqual(r_login.status_code, 200)
            login_json = r_login.json()
            self.assertTrue(login_json["success"])
            self.assertTrue(login_json["is_vip"])
            self.assertEqual(login_json["badge_state"], "vip")
            self.assertTrue(login_json["session_cookie_saved"])
            self.assertNotIn("fresh_token_xyz", str(login_json))
            self.assertIn("fresh_token_xyz", self.fake_config.get("musilon.session_cookie"))

            r_test = client.post("/api/settings/musilon/test")
            self.assertEqual(r_test.status_code, 200)
            self.assertEqual(r_test.json()["badge_state"], "vip")

            # Telegram 2-step + 2FA retry + status + logout
            self.assertFalse(client.get("/api/settings/telegram/status").json()["authorized"])
            r_send = client.post(
                "/api/settings/telegram/send-code", json={"phone": "+989120001122"}
            )
            self.assertTrue(r_send.json()["success"])

            r_ver1 = client.post("/api/settings/telegram/verify", json={"code": "12345"})
            self.assertTrue(r_ver1.json()["needs_password"])
            self.mock_melobot.sign_in.assert_called_with(
                code="12345",
                password=None,
                phone_code_hash="hash_abc_123",
                phone="+989120001122",
            )

            r_ver2 = client.post(
                "/api/settings/telegram/verify",
                json={"code": "12345", "password": "cloud_pw"},
            )
            self.assertTrue(r_ver2.json()["success"])
            self.assertIn("Alex", client.get("/api/settings/telegram/status").json()["display"])
            self.assertTrue(client.post("/api/settings/telegram/logout").json()["success"])

            # Spotify endpoints
            r_sp_st = client.get("/api/settings/spotify/status")
            self.assertEqual(r_sp_st.json()["mode"], "authorized")
            r_sp_val = client.post("/api/settings/spotify/validate", json={})
            self.assertTrue(r_sp_val.json()["valid"])
            self.assertEqual(r_sp_val.json()["sample_title"], "Yellow")
            self.assertTrue(client.post("/api/settings/spotify/authorize").json()["success"])
            self.assertIn("accounts.spotify.com", client.get("/api/settings/spotify/auth-url").json()["auth_url"])
            self.assertTrue(
                client.post(
                    "/api/settings/spotify/auth-callback",
                    json={"code_or_url": "http://127.0.0.1:9900/callback?code=abc"},
                ).json()["success"]
            )
            self.assertTrue(client.post("/api/settings/spotify/disconnect").json()["success"])

            # FFmpeg status + install
            with (
                patch("core.utils.ensure_ffmpeg", return_value="C:/bin/ffmpeg.exe"),
                patch("core.utils.download_ffmpeg") as mock_dl_ff,
            ):
                def _fake_dl(progress_callback=None, **_kw):
                    if progress_callback:
                        progress_callback(100.0, "Done")
                    return "C:/bin/ffmpeg.exe"

                mock_dl_ff.side_effect = _fake_dl
                self.assertTrue(client.get("/api/settings/ffmpeg/status").json()["installed"])
                r_ff = client.post("/api/settings/ffmpeg/install")
                self.assertTrue(r_ff.json()["success"])

            # Open folder (404 on missing, mocked startfile on existing)
            self.assertEqual(
                client.post("/api/settings/open-folder", json={"path": os.path.join(self.tmp_dir, "nope")}).status_code,
                404,
            )
            if os.name == "nt":
                with patch("os.startfile") as mock_start:
                    r_open = client.post("/api/settings/open-folder", json={})
                    self.assertEqual(r_open.status_code, 200)
                    mock_start.assert_called_once()

    def test_spectrum_duplicates_eq_maintenance_and_exporters(self):
        _t1, fp1 = self._record_track("sp_1", "Song One", "Artist A", os.path.join("Mix", "Song One.flac"), collection_name="Mix")
        _t2, fp2 = self._record_track("sp_2", "Song Two", "Artist B", os.path.join("Mix", "Song Two.flac"), collection_name="Mix")

        # Save a playlist pointing to sp_1 & sp_2 for M3U8 & Songs export tests
        self.archive.save_playlist(
            name="Road Playlist",
            spotify_url="https://open.spotify.com/playlist/pl101",
            cover_url="",
            tracks=[_t1, _t2],
            playlist_id="pl101",
        )
        self.archive.mark_saved_track_downloaded(
            "sp_1", fp1, quality_badge="FLAC 16", source_type="Musilon", genre="Electronic"
        )
        self.archive.mark_saved_track_downloaded(
            "sp_2", fp2, quality_badge="FLAC 16", source_type="Musilon", genre="Electronic"
        )

        spec_cache = os.path.join(self.tmp_dir, "cache", "spectrograms")
        os.makedirs(spec_cache, exist_ok=True)
        spec_file = os.path.join(spec_cache, "spec_deadbeef.png")
        with open(spec_file, "wb") as f:
            f.write(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)

        with TestClient(self.app) as client:
            # 1. Spectrum inspect + spectrogram serving + traversal defense + scan + upgrade
            fake_spec_result = {
                "file_path": fp1,
                "codec": "FLAC",
                "sample_rate": 44100,
                "channels": 2,
                "bits_per_sample": 16,
                "container_bitrate_kbps": 950,
                "estimated_true_kbps": 1411,
                "duration_sec": 200.0,
                "cutoff_khz": 21.2,
                "verdict": "authentic",
                "verdict_title": "Authentic Lossless",
                "band_db": {2000: -12.0, 21200: -25.0},
                "spectrogram_path": spec_file,
            }
            with (
                patch("core.paths.get_cache_dir", return_value=os.path.join(self.tmp_dir, "cache")),
                patch("core.utils.inspect_audio_spectrum", return_value=fake_spec_result),
            ):
                r_insp = client.post("/api/tools/spectrum/inspect/sp_1")
                self.assertEqual(r_insp.status_code, 200)
                insp = r_insp.json()
                self.assertEqual(insp["track_id"], "sp_1")
                self.assertEqual(insp["spectrogram_url"], "/api/tools/spectrum/spectrogram/spec_deadbeef.png")

                r_img = client.get(insp["spectrogram_url"])
                self.assertEqual(r_img.status_code, 200)
                self.assertTrue(r_img.content.startswith(b"\x89PNG"))

                self.assertEqual(
                    client.get("/api/tools/spectrum/spectrogram/..%5Csecret.png").status_code,
                    400,
                )
                self.assertIn(
                    client.get("/api/tools/spectrum/spectrogram/..%2Fsecret.png").status_code,
                    (400, 404),
                )
                self.assertEqual(
                    client.get("/api/tools/spectrum/spectrogram/missing_spec.png").status_code,
                    404,
                )

            with patch.object(
                self.archive,
                "scan_library_spectrum",
                return_value=[
                    {"spotify_id": "sp_2", "file_path": fp2, "verdict": "upscaled", "cutoff_khz": 15.0},
                    {"spotify_id": "sp_1", "file_path": fp1, "verdict": "authentic", "cutoff_khz": 21.2},
                ],
            ):
                r_scan = client.post("/api/tools/spectrum/scan", json={})
                self.assertEqual(r_scan.status_code, 200)
                self.assertEqual(r_scan.json()["summary"], {"total": 2, "upscaled": 1, "good": 0, "authentic": 1})

            with patch.object(self.qm, "start_all"):
                r_upg = client.post(
                    "/api/tools/spectrum/upgrade",
                    json={"track_ids": ["sp_2"], "preferred_engine": "melobot"},
                )
                self.assertEqual(r_upg.status_code, 200)
                self.assertEqual(r_upg.json()["queued_count"], 1)
                self.assertFalse(os.path.exists(fp2))
                self.assertIsNone(self.archive.find_track(spotify_id="sp_2"))
                self.assertEqual(len(self.qm.get_items()), 1)

            # 2. Duplicates scan & merge
            fake_groups = [
                {
                    "key": "song_one",
                    "title": "Song One",
                    "artist": "Artist A",
                    "match_reason": "Exact Match",
                    "master": {"file_path": fp1},
                    "duplicates": [{"file_path": fp1 + ".dup.flac", "size_bytes": 1000}],
                    "reclaimable_bytes": 1000,
                }
            ]
            with (
                patch.object(self.archive, "find_library_duplicates", return_value=fake_groups),
                patch.object(
                    self.archive,
                    "merge_library_duplicates",
                    return_value={"groups_processed": 1, "files_merged": 1, "hardlinked": 1, "reclaimed_bytes": 1000, "errors": 0},
                ) as mock_merge,
            ):
                r_dscan = client.post("/api/tools/duplicates/scan", json={"use_acoustic_fingerprint": True})
                self.assertEqual(r_dscan.json()["summary"]["total_groups"], 1)
                self.assertEqual(r_dscan.json()["summary"]["reclaimable_bytes"], 1000)

                r_dmerge = client.post("/api/tools/duplicates/merge", json={"mode": "hardlink"})
                self.assertEqual(r_dmerge.status_code, 200)
                self.assertEqual(r_dmerge.json()["hardlinked"], 1)
                mock_merge.assert_called_once()

            # 3. Volume & ReplayGain
            with patch("core.utils.normalize_audio_loudness", return_value=(-14.2, 5.2)):
                r_nv = client.post("/api/tools/volume/normalize-track/sp_1", json={"target_lufs": -9.0})
                self.assertTrue(r_nv.json()["success"])
                self.assertEqual(r_nv.json()["gain_db"], 5.2)

            with patch.object(
                self.archive,
                "normalize_all_library_tracks",
                return_value={"scanned": 1, "boosted": 1, "attenuated": 0, "already_balanced": 0, "errors": 0},
            ):
                r_nl = client.post("/api/tools/volume/normalize-library", json={})
                self.assertEqual(r_nl.json()["boosted"], 1)

            with patch("core.utils.calculate_replaygain", return_value=("-3.20 dB", "0.950000")):
                self.mock_tagger.tag_replaygain.return_value = True
                r_rg = client.post("/api/tools/replaygain/track/sp_1")
                self.assertTrue(r_rg.json()["success"])
                self.assertEqual(r_rg.json()["track_gain"], "-3.20 dB")

            with patch.object(
                self.archive,
                "retag_all_library_replaygain",
                return_value={"scanned": 1, "calculated": 1, "errors": 0},
            ):
                self.assertEqual(client.post("/api/tools/replaygain/library").json()["calculated"], 1)

            # 4. Equalizer GET / PUT / BAKE
            r_eq_get = client.get("/api/tools/eq")
            self.assertEqual(len(r_eq_get.json()["frequencies"]), 10)
            r_eq_put = client.put(
                "/api/tools/eq",
                json={"enabled": True, "preset": "Bass Boost"},
            )
            self.assertEqual(r_eq_put.status_code, 200)
            self.assertTrue(r_eq_put.json()["config"]["enabled"])
            self.assertEqual(r_eq_put.json()["config"]["bass_boost"], 4.5)
            self.assertEqual(
                client.put("/api/tools/eq", json={"bands": [0.0, 1.0]}).status_code,
                400,
            )
            with patch("core.utils.apply_equalizer_to_file", return_value=True) as mock_bake:
                r_bake = client.post("/api/tools/eq/bake/sp_1")
                self.assertTrue(r_bake.json()["success"])
                mock_bake.assert_called_once()

            # 5. Library maintenance endpoints
            with (
                patch.object(self.archive, "purge_corrupt_and_cleanup_library", return_value={"purged_corrupt_files": 0, "relocated_covers": 0, "reorganized_lyrics": 0}),
                patch.object(self.archive, "repair_library", return_value={"scanned": 1, "healed_covers": 1, "healed_lyrics": 0}),
                patch.object(self.archive, "retag_all_library_genres", return_value={"scanned": 1, "retagged": 1, "already_tagged": 0, "errors": 0}),
            ):
                self.assertEqual(client.post("/api/tools/maintenance/clean").status_code, 200)
                self.assertEqual(client.post("/api/tools/maintenance/repair").json()["healed_covers"], 1)
                self.assertEqual(client.post("/api/tools/maintenance/retag-genres").json()["retagged"], 1)

            # 6. Export Songs & Export M3U8 (real file copy + M3U8 generation)
            export_dest = os.path.join(self.tmp_dir, "exported")
            r_exp = client.post(
                "/api/tools/export/songs",
                json={
                    "destination_dir": export_dest,
                    "playlist_id": "pl101",
                    "target_format": "original",
                    "generate_m3u8": True,
                },
            )
            self.assertEqual(r_exp.status_code, 200)
            exp_data = r_exp.json()
            self.assertEqual(exp_data["exported"], 1)
            self.assertTrue(os.path.isfile(exp_data["m3u8_path"]))
            self.assertEqual(self.fake_config.get("export.last_format"), "original")

            m3u_out = os.path.join(self.tmp_dir, "phone.m3u8")
            r_m3u = client.post(
                "/api/tools/export/m3u8",
                json={
                    "playlist_id": "pl101",
                    "dest_path": m3u_out,
                    "path_mode": "android_prefix",
                    "android_prefix": "/storage/emulated/0/Flacify",
                },
            )
            self.assertEqual(r_m3u.status_code, 200)
            self.assertTrue(os.path.isfile(m3u_out))
            with open(m3u_out, "r", encoding="utf-8") as fh:
                content = fh.read()
            self.assertIn("/storage/emulated/0/Flacify/Song One.flac", content)

            # Cancel non-running tool returns False cleanly
            r_cancel = client.post("/api/tools/cancel/export_songs")
            self.assertEqual(r_cancel.status_code, 200)
            self.assertFalse(r_cancel.json()["cancelled"])


if __name__ == "__main__":
    unittest.main()
