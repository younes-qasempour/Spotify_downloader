import copy
import os
import shutil
import tempfile
import threading
import unittest
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from backend.app import create_app
from backend.state import BackendState
from core import __version__
from core.archive import ArchiveManager
from core.config import DEFAULT_CONFIG
from core.queue_manager import DownloadQueueManager, QueueItem
from core.spotify_client import TrackMetadata


class FakeConfig:
    """Isolated in-memory config store mimicking ConfigManager without touching disk."""

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

    def add_listener(self, cb):
        with self._lock:
            if cb not in self._listeners:
                self._listeners.append(cb)

    def remove_listener(self, cb):
        with self._lock:
            if cb in self._listeners:
                self._listeners.remove(cb)


class TestBackendCore(unittest.TestCase):
    def setUp(self):
        self._prev_archive_instance = ArchiveManager._instance
        ArchiveManager._instance = None
        self.tmp_dir = tempfile.mkdtemp(prefix="flacify_backend_test_")
        self.db_path = os.path.join(self.tmp_dir, "test_archive.db")
        self.archive = ArchiveManager(db_path=self.db_path)

        self.fake_config = FakeConfig()
        self.mock_audio_engine = MagicMock()
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
            spotify_client=MagicMock(),
            config_manager=self.fake_config,
            run_startup_scan=False,
        )
        self.app = create_app(state=self.state, run_startup_scan=False)

    def tearDown(self):
        ArchiveManager._instance = self._prev_archive_instance
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    @staticmethod
    def _sample_track(track_id: str = "tr_1") -> TrackMetadata:
        return TrackMetadata(
            id=track_id,
            title="Digital Love",
            artists=["Daft Punk"],
            album="Discovery",
            release_date="2001-03-12",
            duration_ms=301000,
            track_number=3,
            disc_number=1,
            isrc="GBDUW0000059",
            cover_url="https://example.com/cover.jpg",
            collection_type="album",
            collection_name="Discovery",
            collection_cover_url="https://example.com/album.jpg",
            genres=["French House"],
        )

    def test_health_endpoint(self):
        with TestClient(self.app) as client:
            resp = client.get("/api/health")
            self.assertEqual(resp.status_code, 200)
            body = resp.json()
            self.assertEqual(body["status"], "ok")
            self.assertEqual(body["version"], __version__)
            self.assertEqual(body["api_version"], "2.0")
            self.assertFalse(body["queue_paused"])
            self.assertEqual(body["queue_count"], 0)
            self.assertEqual(body["pending_prompts"], 0)

    def test_websocket_handshake_and_ping(self):
        with TestClient(self.app) as client:
            with client.websocket_connect("/ws/events") as ws:
                hello = ws.receive_json()
                self.assertEqual(hello["type"], "connected")
                self.assertEqual(hello["payload"]["version"], __version__)
                self.assertEqual(hello["payload"]["api_version"], "2.0")
                self.assertIn("timestamp", hello)

                ws.send_json({"type": "ping"})
                pong = ws.receive_json()
                self.assertEqual(pong["type"], "pong")

    def test_queue_callbacks_broadcast_from_worker_thread(self):
        track = self._sample_track("tr_worker")
        item = QueueItem(
            track=track,
            status="Downloading",
            source_type="Musilon",
            quality_badge="16-BIT FLAC",
            progress_percent=50.0,
        )
        with self.qm._lock:
            self.qm._items[track.id] = item

        with TestClient(self.app) as client:
            with client.websocket_connect("/ws/events") as ws:
                ws.receive_json()  # connected

                def trigger_worker_events():
                    self.qm.on_tracks_enqueued([item])
                    self.qm.on_track_source_resolved(track.id, "Musilon", "16-BIT FLAC")
                    self.qm.on_track_progress(track.id, 62.5, "4.2 MB/s", "00:04")
                    self.qm.on_track_status_changed(track.id, "Tagging")
                    self.qm.on_track_completed(track.id, "/music/Daft Punk - Digital Love.flac")
                    self.qm.on_track_failed("tr_fail", "Network timeout")

                t = threading.Thread(target=trigger_worker_events)
                t.start()
                t.join(timeout=5)

                received = [ws.receive_json() for _ in range(6)]
                by_type = {msg["type"]: msg["payload"] for msg in received}

                self.assertEqual(len(by_type["tracks_enqueued"]["items"]), 1)
                self.assertEqual(
                    by_type["tracks_enqueued"]["items"][0]["track"]["title"], "Digital Love"
                )
                self.assertEqual(by_type["source_resolved"]["quality_badge"], "16-BIT FLAC")
                self.assertEqual(by_type["track_progress"]["percent"], 62.5)
                self.assertEqual(by_type["status_changed"]["status"], "Tagging")
                self.assertEqual(
                    by_type["track_completed"]["output_path"],
                    "/music/Daft Punk - Digital Love.flac",
                )
                self.assertIsNotNone(by_type["track_completed"]["item"])
                self.assertEqual(by_type["track_failed"]["error"], "Network timeout")

    def test_config_change_masks_secrets_over_websocket(self):
        with TestClient(self.app) as client:
            with client.websocket_connect("/ws/events") as ws:
                ws.receive_json()  # connected

                self.fake_config.set("download.concurrency", 4)
                ev1 = ws.receive_json()
                self.assertEqual(ev1["type"], "config_changed")
                self.assertEqual(ev1["payload"]["key"], "download.concurrency")
                self.assertEqual(ev1["payload"]["value"], 4)

                self.fake_config.set("musilon.password", "supersecretpass")
                ev2 = ws.receive_json()
                self.assertEqual(ev2["type"], "config_changed")
                self.assertEqual(ev2["payload"]["key"], "musilon.password")
                self.assertEqual(ev2["payload"]["value"], "sup***ass")
                self.assertNotIn("supersecretpass", str(ev2))

    def test_musilon_limit_prompt_and_ws_resolution(self):
        track = self._sample_track("tr_limit")
        item = QueueItem(track=track, status="Musilon Issue")
        decision_result = []
        decision_event = threading.Event()

        def on_decision(action: str):
            decision_result.append(action)
            decision_event.set()

        with TestClient(self.app) as client:
            with client.websocket_connect("/ws/events") as ws:
                ws.receive_json()  # connected

                def trigger_limit():
                    self.qm.on_musilon_limit_reached(
                        track, item, "HTTP 429 daily VIP quota exceeded", on_decision
                    )

                t = threading.Thread(target=trigger_limit)
                t.start()
                t.join(timeout=5)

                prompt_msg = ws.receive_json()
                self.assertEqual(prompt_msg["type"], "musilon_limit_reached")
                payload = prompt_msg["payload"]
                self.assertEqual(payload["category"], "quota")
                self.assertEqual(payload["track"]["id"], "tr_limit")
                prompt_id = payload["prompt_id"]
                self.assertEqual(len(self.state.get_pending_musilon_prompts()), 1)

                ws.send_json(
                    {
                        "type": "musilon_decision",
                        "prompt_id": prompt_id,
                        "action": "continue_youtube",
                    }
                )

                msgs = [ws.receive_json(), ws.receive_json()]
                types = {m["type"]: m["payload"] for m in msgs}
                self.assertIn("ack", types)
                self.assertTrue(types["ack"]["resolved"])
                self.assertIn("musilon_limit_resolved", types)
                self.assertEqual(types["musilon_limit_resolved"]["action"], "continue_youtube")

                self.assertTrue(decision_event.wait(timeout=2))
                self.assertEqual(decision_result, ["continue_youtube"])
                self.assertEqual(self.state.get_pending_musilon_prompts(), [])

    def test_musilon_limit_suppressed_when_melobot_active(self):
        self.fake_config.set("source_engine", "melobot")
        track = self._sample_track("tr_melo")
        item = QueueItem(track=track, status="Resolving")
        decisions = []

        self.qm.on_musilon_limit_reached(
            track, item, "HTTP 429 rate limit", lambda act: decisions.append(act)
        )

        self.assertEqual(decisions, ["continue_youtube"])
        self.assertEqual(self.state.get_pending_musilon_prompts(), [])


if __name__ == "__main__":
    unittest.main()
