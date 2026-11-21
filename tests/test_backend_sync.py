import copy
import os
import shutil
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from backend.app import create_app
from backend.state import BackendState
from core.archive import ArchiveManager
from core.config import DEFAULT_CONFIG
from core.queue_manager import DownloadQueueManager
from core.spotify_client import TrackMetadata


class FakeConfig:
    """In-memory config stub without disk side effects."""

    def __init__(self):
        self._data = copy.deepcopy(DEFAULT_CONFIG)
        self._listeners = []
        self._lock = threading.RLock()

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

    def to_dict(self, mask_secrets: bool = False):
        with self._lock:
            return copy.deepcopy(self._data)

    def add_listener(self, cb):
        with self._lock:
            if cb not in self._listeners:
                self._listeners.append(cb)

    def remove_listener(self, cb):
        with self._lock:
            if cb in self._listeners:
                self._listeners.remove(cb)


class TestBackendSyncAndMobile(unittest.TestCase):
    def setUp(self):
        self._prev_archive_instance = ArchiveManager._instance
        ArchiveManager._instance = None
        self.tmp_dir = tempfile.mkdtemp(prefix="flacify_sync_test_")
        self.db_path = os.path.join(self.tmp_dir, "test_archive.db")
        self.archive = ArchiveManager(db_path=self.db_path)

        self.fake_config = FakeConfig()
        self.fake_config.set("download.output_dir", self.tmp_dir)
        self.fake_config.set("mobile.lan_enabled", True)
        self.fake_config.set("mobile.pair_token", "test_pair_token_xyz_123")
        self.fake_config.set("mobile.device_name", "TestRig")

        self.mock_audio_engine = MagicMock()
        self.mock_spotify = MagicMock()
        self.qm = DownloadQueueManager(
            audio_engine=self.mock_audio_engine,
            archive_manager=self.archive,
            max_concurrent_downloads=2,
        )
        self.state = BackendState(
            archive_manager=self.archive,
            musilon_engine=MagicMock(),
            melobot_engine=MagicMock(),
            ytdlp_engine=MagicMock(),
            lyrics_engine=MagicMock(),
            tagger=MagicMock(),
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

    def _valid_flac_bytes(self, body: bytes) -> bytes:
        hdr = (
            b"fLaC\x80\x00\x00\x22"
            + b"\x10\x00\x10\x00\x00\x00\x00\x00\x00\x00\x0a\xc4\x42\xf0\x00\x00\x00\x00"
            + b"\x00" * 16
        )
        return hdr + body

    def _create_flac(self, filename: str, pattern_len: int = 160 * 1024) -> tuple[str, bytes]:
        payload = self._valid_flac_bytes(bytes((i % 247) for i in range(pattern_len)))
        fp = os.path.join(self.tmp_dir, filename)
        with open(fp, "wb") as fh:
            fh.write(payload)
        return fp, payload

    def test_pair_token_auth_middleware_and_websocket_enforcement(self):
        with TestClient(self.app) as local_client:
            # Loopback client bypasses token requirement & receives secret QR/token
            h_local = local_client.get("/api/health")
            self.assertEqual(h_local.status_code, 200)
            self.assertTrue(h_local.json()["pair_required"])
            self.assertEqual(h_local.json()["device_name"], "TestRig")

            info_local = local_client.get("/api/sync/info")
            self.assertEqual(info_local.status_code, 200)
            self.assertEqual(info_local.json()["pair_token"], "test_pair_token_xyz_123")
            self.assertIn("flacify://pair?", info_local.json()["pair_uri"])

            qr_resp = local_client.get("/api/sync/pairing-qr")
            self.assertEqual(qr_resp.status_code, 200)
            self.assertIn("image/svg+xml", qr_resp.headers["content-type"])
            self.assertIn(b"<svg", qr_resp.content)

        # Remote LAN IP simulation
        with TestClient(self.app, client=("192.168.1.42", 54321)) as lan_client:
            # Health check stays open for discovery probe
            self.assertEqual(lan_client.get("/api/health").status_code, 200)

            # Unauthenticated /api/* call is rejected with 401
            self.assertEqual(lan_client.get("/api/sync/info").status_code, 401)
            self.assertEqual(
                lan_client.get(
                    "/api/sync/info",
                    headers={"Authorization": "Bearer wrong_token"},
                ).status_code,
                401,
            )

            # Valid Bearer, X-Flacify-Token, and ?token= all work; secret pair_token hidden from remote client
            ok_bearer = lan_client.get(
                "/api/sync/info",
                headers={"Authorization": "Bearer test_pair_token_xyz_123"},
            )
            self.assertEqual(ok_bearer.status_code, 200)
            self.assertNotIn("pair_token", ok_bearer.json())
            self.assertNotIn("pair_uri", ok_bearer.json())

            ok_hdr = lan_client.get(
                "/api/library/stats",
                headers={"X-Flacify-Token": "test_pair_token_xyz_123"},
            )
            self.assertEqual(ok_hdr.status_code, 200)

            ok_qs = lan_client.get(
                "/api/library/stats",
                params={"token": "test_pair_token_xyz_123"},
            )
            self.assertEqual(ok_qs.status_code, 200)

            # Host-only pairing QR & regenerate remain 403 remotely even with valid token
            self.assertEqual(
                lan_client.get(
                    "/api/sync/pairing-qr",
                    headers={"Authorization": "Bearer test_pair_token_xyz_123"},
                ).status_code,
                403,
            )
            self.assertEqual(
                lan_client.post(
                    "/api/sync/token/regenerate",
                    headers={"Authorization": "Bearer test_pair_token_xyz_123"},
                ).status_code,
                403,
            )

            # WebSocket rejects missing token and accepts valid ?token=
            with self.assertRaises(WebSocketDisconnect):
                with lan_client.websocket_connect("/ws/events"):
                    pass

            with lan_client.websocket_connect(
                "/ws/events?token=test_pair_token_xyz_123"
            ) as ws:
                msg = ws.receive_json()
                self.assertEqual(msg["type"], "connected")

            # Remote clients cannot mutate mobile.pair_token or mobile.lan_enabled via /api/settings
            self.assertEqual(
                lan_client.patch(
                    "/api/settings",
                    json={"values": {"mobile.pair_token": "attacker_token"}},
                    headers={"Authorization": "Bearer test_pair_token_xyz_123"},
                ).status_code,
                403,
            )
            self.assertEqual(
                lan_client.patch(
                    "/api/settings",
                    json={"values": {"mobile.lan_enabled": False}},
                    headers={"Authorization": "Bearer test_pair_token_xyz_123"},
                ).status_code,
                403,
            )

            # Disabling LAN blocks remote HTTP & WebSocket callers with 403/4403
            self.fake_config.set("mobile.lan_enabled", False)
            self.assertEqual(
                lan_client.get(
                    "/api/sync/info",
                    headers={"Authorization": "Bearer test_pair_token_xyz_123"},
                ).status_code,
                403,
            )
            with self.assertRaises(WebSocketDisconnect):
                with lan_client.websocket_connect(
                    "/ws/events?token=test_pair_token_xyz_123"
                ):
                    pass

        # Token rotation invalidates old token immediately; PATCH mobile.pair_token blocked locally too
        self.fake_config.set("mobile.lan_enabled", True)
        with TestClient(self.app) as local_client:
            from backend.routes.sync import is_loopback_host

            self.assertTrue(is_loopback_host("::ffff:127.0.0.1"))
            self.assertEqual(
                local_client.patch(
                    "/api/settings",
                    json={"values": {"mobile.pair_token": "manual_override"}},
                ).status_code,
                403,
            )
            rot = local_client.post("/api/sync/token/regenerate")
            self.assertEqual(rot.status_code, 200)
            new_tok = rot.json()["pair_token"]
            self.assertNotEqual(new_tok, "test_pair_token_xyz_123")

        with TestClient(self.app, client=("192.168.1.42", 54322)) as lan_client:
            self.assertEqual(
                lan_client.get(
                    "/api/sync/info",
                    headers={"Authorization": "Bearer test_pair_token_xyz_123"},
                ).status_code,
                401,
            )
            self.assertEqual(
                lan_client.get(
                    "/api/sync/info",
                    headers={"Authorization": f"Bearer {new_tok}"},
                ).status_code,
                200,
            )

    def test_sync_manifest_dedup_lossless_download_and_range_resume(self):
        fp1, payload1 = self._create_flac("Song Alpha.flac")
        lrc_fp = os.path.splitext(fp1)[0] + ".lrc"
        with open(lrc_fp, "w", encoding="utf-8") as fh:
            fh.write("[00:01.00] Hello FLAC\n")
        fp2, _ = self._create_flac("Song Beta.flac", pattern_len=64 * 1024)

        master1 = TrackMetadata(
            id="sp_alpha_master",
            title="Song Alpha",
            artists=["Artist A"],
            album="Album A",
            duration_ms=200000,
            genres=["Indie Rock"],
        )
        alt1 = TrackMetadata(
            id="sp_alpha_alt",
            title="Song Alpha",
            artists=["Artist A"],
            album="Album A",
            duration_ms=200000,
        )
        master2 = TrackMetadata(
            id="sp_beta_master",
            title="Song Beta",
            artists=["Artist B"],
            album="Album B",
            duration_ms=180000,
        )
        pending3 = TrackMetadata(
            id="sp_gamma_pending",
            title="Song Gamma",
            artists=["Artist C"],
            album="Album C",
        )

        self.archive.add_track(master1, fp1, "FLAC 16", "Musilon", genre="Indie Rock")
        self.archive.add_track(master2, fp2, "FLAC 16", "Musilon")
        self.archive.save_playlist(
            "Roadtrip Mix",
            "https://open.spotify.com/playlist/plroad",
            "",
            [alt1, pending3],
            playlist_id="plroad",
        )
        self.archive.mark_saved_track_downloaded("sp_alpha_alt", fp1, "FLAC 16", "Musilon")

        with TestClient(self.app, client=("10.70.159.99", 55000)) as client:
            hdrs = {"Authorization": "Bearer test_pair_token_xyz_123"}

            # Full manifest returns 2 unique physical files + alias mapping for alt1
            m_full = client.get("/api/sync/manifest", headers=hdrs)
            self.assertEqual(m_full.status_code, 200)
            mdata = m_full.json()
            self.assertEqual(mdata["total_unique_tracks"], 2)
            self.assertEqual(len(mdata["tracks"]), 2)
            alpha_entry = next(t for t in mdata["tracks"] if t["id"] == "sp_alpha_master")
            self.assertIn("sp_alpha_alt", alpha_entry["alias_ids"])
            self.assertTrue(alpha_entry["has_lrc"])
            self.assertEqual(alpha_entry["file_size"], len(payload1))

            pl_entry = mdata["playlists"][0]
            self.assertEqual(pl_entry["downloaded_tracks"], 1)
            self.assertEqual(pl_entry["tracks"][0]["canonical_id"], "sp_alpha_master")
            self.assertTrue(pl_entry["tracks"][0]["downloaded"])
            self.assertFalse(pl_entry["tracks"][1]["downloaded"])

            # Manifest with include_tracks=false keeps exact total_unique_tracks and total_bytes
            m_meta_only = client.get(
                "/api/sync/manifest",
                params={"include_tracks": "false"},
                headers=hdrs,
            )
            self.assertEqual(m_meta_only.status_code, 200)
            self.assertEqual(m_meta_only.json()["total_unique_tracks"], 2)
            self.assertEqual(m_meta_only.json()["tracks"], [])
            self.assertGreater(m_meta_only.json()["total_bytes"], len(payload1))

            # Playlist-scoped manifest returns only tracks needed for that playlist
            m_pl = client.get(
                "/api/sync/manifest",
                params={"playlist_id": "plroad"},
                headers=hdrs,
            )
            self.assertEqual(m_pl.status_code, 200)
            self.assertEqual(m_pl.json()["total_unique_tracks"], 1)
            self.assertEqual(m_pl.json()["tracks"][0]["id"], "sp_alpha_master")
            self.assertIn("remote_cover_url", m_pl.json()["playlists"][0])

            m_pl_meta_only = client.get(
                "/api/sync/manifest",
                params={"playlist_id": "plroad", "include_tracks": "false"},
                headers=hdrs,
            )
            self.assertEqual(m_pl_meta_only.status_code, 200)
            self.assertEqual(m_pl_meta_only.json()["total_unique_tracks"], 1)
            self.assertEqual(m_pl_meta_only.json()["total_bytes"], len(payload1))
            self.assertEqual(m_pl_meta_only.json()["tracks"], [])

            # HEAD & full lossless download + byte-range resume work via both canonical & alias IDs
            head_resp = client.head("/api/sync/tracks/sp_alpha_alt/file", headers=hdrs)
            self.assertEqual(head_resp.status_code, 200)
            self.assertEqual(head_resp.headers["x-file-size"], str(len(payload1)))

            full_dl = client.get("/api/sync/tracks/sp_alpha_master/file", headers=hdrs)
            self.assertEqual(full_dl.status_code, 200)
            self.assertEqual(full_dl.content, payload1)
            self.assertIn("Song%20Alpha.flac", full_dl.headers["content-disposition"])

            part_dl = client.get(
                "/api/sync/tracks/sp_alpha_alt/file",
                headers={**hdrs, "Range": "bytes=100-199"},
            )
            self.assertEqual(part_dl.status_code, 206)
            self.assertEqual(part_dl.content, payload1[100:200])

    def test_share_endpoint_extracts_spotify_url_and_enqueues(self):
        resolved_track = TrackMetadata(
            id="shared_sp_1",
            title="Shared Song",
            artists=["Shared Artist"],
            album="Shared Album",
            duration_ms=210000,
        )
        self.mock_spotify.resolve.return_value = [resolved_track]

        with (
            patch.object(DownloadQueueManager, "start_all", lambda _self: None),
            TestClient(self.app, client=("192.168.1.99", 55001)) as client,
        ):
            hdrs = {"X-Flacify-Token": "test_pair_token_xyz_123"}

            bad_resp = client.post(
                "/api/sync/share",
                json={"url": "plain text with no link"},
                headers=hdrs,
            )
            self.assertEqual(bad_resp.status_code, 400)

            ok_resp = client.post(
                "/api/sync/share",
                json={
                    "url": "Here is a song for you https://open.spotify.com/track/4uLU6hMCjMI75M1A2tKUQC?si=12345!",
                    "auto_download": True,
                },
                headers=hdrs,
            )
            self.assertEqual(ok_resp.status_code, 200)
            sdata = ok_resp.json()
            self.assertTrue(sdata["accepted"])
            self.assertEqual(
                sdata["extracted_url"],
                "https://open.spotify.com/track/4uLU6hMCjMI75M1A2tKUQC?si=12345",
            )
            self.assertEqual(sdata["entity_type"], "track")
            self.assertEqual(sdata["queued_count"], 1)
            self.assertIn("shared_sp_1", self.qm._items)

    def test_mdns_dns_label_sanitization(self):
        from backend.mdns import FlacifyMdnsBroadcaster

        self.assertEqual(
            FlacifyMdnsBroadcaster._build_dns_host_label("My_PC_Name 01!"),
            "my-pc-name-01",
        )
        self.assertEqual(FlacifyMdnsBroadcaster._build_dns_host_label("___"), "flacify")


if __name__ == "__main__":
    unittest.main()
