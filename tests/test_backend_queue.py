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


class TestBackendQueue(unittest.TestCase):
    def setUp(self):
        self._prev_archive_instance = ArchiveManager._instance
        ArchiveManager._instance = None
        self.tmp_dir = tempfile.mkdtemp(prefix="flacify_queue_api_test_")
        self.db_path = os.path.join(self.tmp_dir, "test_archive.db")
        self.archive = ArchiveManager(db_path=self.db_path)

        self.fake_config = FakeConfig()
        self.mock_ytdlp = MagicMock()
        self.mock_audio_engine = MagicMock()
        self.mock_audio_engine.ytdlp = self.mock_ytdlp
        self.mock_spotify = MagicMock()
        self.mock_spotify.last_was_truncated = False
        self.mock_spotify.has_credentials.return_value = True

        self.qm = DownloadQueueManager(
            audio_engine=self.mock_audio_engine,
            archive_manager=self.archive,
            max_concurrent_downloads=2,
        )
        self.state = BackendState(
            archive_manager=self.archive,
            musilon_engine=MagicMock(),
            melobot_engine=MagicMock(),
            ytdlp_engine=self.mock_ytdlp,
            lyrics_engine=MagicMock(),
            tagger=MagicMock(),
            audio_engine=self.mock_audio_engine,
            queue_manager=self.qm,
            spotify_client=self.mock_spotify,
            config_manager=self.fake_config,
            run_startup_scan=False,
        )
        self.app = create_app(state=self.state, run_startup_scan=False)

    def tearDown(self):
        ArchiveManager._instance = self._prev_archive_instance
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    @staticmethod
    def _track(
        track_id: str,
        title: str,
        artist: str = "Daft Punk",
        album: str = "Discovery",
        collection_type: str = "track",
        collection_name: str = "Singles",
    ) -> TrackMetadata:
        return TrackMetadata(
            id=track_id,
            title=title,
            artists=[artist],
            album=album,
            duration_ms=240000,
            collection_type=collection_type,
            collection_name=collection_name,
            collection_cover_url="https://example.com/coll.jpg",
            cover_url="https://example.com/track.jpg",
        )

    def test_get_queue_empty_and_filtered_stats(self):
        with TestClient(self.app) as client:
            empty_resp = client.get("/api/queue")
            self.assertEqual(empty_resp.status_code, 200)
            empty_data = empty_resp.json()
            self.assertEqual(empty_data["items"], [])
            self.assertEqual(
                empty_data["stats"],
                {
                    "total": 0,
                    "active": 0,
                    "queued": 0,
                    "completed": 0,
                    "failed": 0,
                    "overall_progress_percent": 0,
                },
            )

            items = [
                QueueItem(track=self._track("t1", "One More Time"), status="Completed"),
                QueueItem(track=self._track("t2", "Aerodynamic"), status="Downloading"),
                QueueItem(track=self._track("t3", "Digital Love"), status="Queued"),
                QueueItem(track=self._track("t4", "Harder Better"), status="Failed"),
                QueueItem(track=self._track("t5", "Crescendolls", artist="Justice"), status="Resolving (YTM Fallback)"),
            ]
            with self.qm._lock:
                for it in items:
                    self.qm._items[it.track.id] = it

            all_resp = client.get("/api/queue")
            self.assertEqual(all_resp.status_code, 200)
            body = all_resp.json()
            self.assertEqual(len(body["items"]), 5)
            self.assertEqual(
                body["stats"],
                {
                    "total": 5,
                    "active": 2,
                    "queued": 1,
                    "completed": 1,
                    "failed": 1,
                    "overall_progress_percent": 20,
                },
            )

            active_resp = client.get("/api/queue", params={"status": "active"})
            self.assertEqual(
                {it["track"]["id"] for it in active_resp.json()["items"]},
                {"t2", "t5"},
            )

            queued_resp = client.get("/api/queue", params={"status": "queued"})
            self.assertEqual(
                [it["track"]["id"] for it in queued_resp.json()["items"]], ["t3"]
            )

            completed_resp = client.get("/api/queue", params={"status": "completed"})
            self.assertEqual(
                [it["track"]["id"] for it in completed_resp.json()["items"]], ["t1"]
            )

            failed_resp = client.get("/api/queue", params={"status": "failed"})
            self.assertEqual(
                [it["track"]["id"] for it in failed_resp.json()["items"]], ["t4"]
            )

            search_resp = client.get("/api/queue", params={"query": "digital"})
            self.assertEqual(
                [it["track"]["id"] for it in search_resp.json()["items"]], ["t3"]
            )

    def test_enqueue_empty_input_returns_400(self):
        with TestClient(self.app) as client:
            resp = client.post("/api/queue/enqueue", json={"input": "   \n  ", "urls": []})
            self.assertEqual(resp.status_code, 400)

    def test_enqueue_spotify_playlist_auto_saves_and_detects_guest_truncation(self):
        pl_url = "https://open.spotify.com/playlist/pl123"
        t1 = self._track("sp_1", "Track One", collection_type="playlist", collection_name="Gym Mix")
        t2 = self._track("sp_2", "Track Two", collection_type="playlist", collection_name="Gym Mix")
        self.mock_spotify.resolve.return_value = [t1, t2]
        self.mock_spotify.last_was_truncated = True

        with TestClient(self.app) as client:
            with client.websocket_connect("/ws/events") as ws:
                ws.receive_json()  # connected

                resp = client.post("/api/queue/enqueue", json={"input": pl_url})
                self.assertEqual(resp.status_code, 200)
                data = resp.json()
                self.assertEqual(data["enqueued_count"], 2)
                self.assertTrue(data["truncated_guest_limit"])
                self.assertTrue(data["saved_playlists_updated"])
                self.assertFalse(data["started"])
                self.assertEqual(len(data["items"]), 2)

                saved = self.archive.get_saved_playlist("pl123")
                self.assertIsNotNone(saved)
                self.assertEqual(saved["name"], "Gym Mix")
                self.assertEqual(saved["total_tracks"], 2)

                events = [ws.receive_json(), ws.receive_json()]
                event_types = {ev["type"] for ev in events}
                self.assertEqual(event_types, {"tracks_enqueued", "playlists_updated"})

    def test_enqueue_youtube_search_and_multi_line_input(self):
        sp_url = "https://open.spotify.com/track/tr_sp_1"
        search_q = "Nujabes Aruarian Dance"
        t_sp = self._track("tr_sp_1", "Instant Crush")
        t_yt = self._track("yt_1", "Aruarian Dance", artist="Nujabes")
        self.mock_spotify.resolve.return_value = [t_sp]
        self.mock_ytdlp.extract_from_url_or_search.return_value = [t_yt]

        with TestClient(self.app) as client:
            resp = client.post(
                "/api/queue/enqueue",
                json={"input": f"{sp_url}\n{search_q}", "preferred_engine": "ytdlp"},
            )
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertEqual(data["enqueued_count"], 2)
            self.assertEqual(data["errors"], [])
            self.assertFalse(data["saved_playlists_updated"])
            self.assertEqual(
                [it["track"]["id"] for it in data["items"]], ["tr_sp_1", "yt_1"]
            )
            self.assertTrue(all(it["preferred_engine"] == "ytdlp" for it in data["items"]))
            self.mock_ytdlp.extract_from_url_or_search.assert_called_once_with(search_q)

    def test_enqueue_all_errors_returns_502(self):
        self.mock_spotify.resolve.side_effect = RuntimeError("Spotify API unreachable")
        with TestClient(self.app) as client:
            resp = client.post(
                "/api/queue/enqueue",
                json={"input": "https://open.spotify.com/track/bad_1"},
            )
            self.assertEqual(resp.status_code, 502)
            self.assertIn("Spotify API unreachable", resp.json()["detail"])

    def test_transport_controls_start_pause_resume_stop_retry_clear(self):
        t1 = self._track("tr_1", "Song 1")
        t2 = self._track("tr_2", "Song 2")
        t3 = self._track("tr_3", "Song 3")
        with self.qm._lock:
            self.qm._items[t1.id] = QueueItem(track=t1, status="Queued")
            self.qm._items[t2.id] = QueueItem(track=t2, status="Completed")
            self.qm._items[t3.id] = QueueItem(track=t3, status="Failed", error_message="err")

        with patch.object(DownloadQueueManager, "_worker_loop", lambda self: None):
            with TestClient(self.app) as client:
                with client.websocket_connect("/ws/events") as ws:
                    ws.receive_json()  # connected

                    start_resp = client.post("/api/queue/start")
                    self.assertEqual(start_resp.status_code, 200)
                    self.assertEqual(start_resp.json()["started_count"], 2)
                    self.assertTrue(start_resp.json()["running"])
                    self.assertFalse(start_resp.json()["paused"])

                    pause_resp = client.post("/api/queue/pause")
                    self.assertEqual(pause_resp.status_code, 200)
                    self.assertTrue(pause_resp.json()["paused"])

                    resume_resp = client.post("/api/queue/resume")
                    self.assertEqual(resume_resp.status_code, 200)
                    self.assertFalse(resume_resp.json()["paused"])

                    stop_resp = client.post("/api/queue/stop")
                    self.assertEqual(stop_resp.status_code, 200)
                    self.assertTrue(stop_resp.json()["stopped"])
                    self.assertFalse(stop_resp.json()["running"])

                    retry_resp = client.post("/api/queue/retry-failed")
                    self.assertEqual(retry_resp.status_code, 200)
                    self.assertEqual(retry_resp.json()["retried_count"], 2)

                    clear_resp = client.post("/api/queue/clear-completed")
                    self.assertEqual(clear_resp.status_code, 200)
                    self.assertTrue(clear_resp.json()["cleared"])
                    self.assertEqual(clear_resp.json()["remaining_count"], 2)

                    seen_types = []
                    for _ in range(15):
                        msg = ws.receive_json()
                        seen_types.append(msg["type"])
                        if msg["type"] == "queue_cleared":
                            break
                    self.assertIn("queue_state_changed", seen_types)
                    self.assertIn("queue_cleared", seen_types)

    def test_single_and_batch_track_actions(self):
        t1 = self._track("tr_a", "Track A")
        t2 = self._track("tr_b", "Track B")
        t3 = self._track("tr_c", "Track C")
        with self.qm._lock:
            self.qm._items[t1.id] = QueueItem(track=t1, status="Failed")
            self.qm._items[t2.id] = QueueItem(track=t2, status="Queued")
            self.qm._items[t3.id] = QueueItem(track=t3, status="Stopped")

        with patch.object(DownloadQueueManager, "_worker_loop", lambda self: None):
            with TestClient(self.app) as client:
                with client.websocket_connect("/ws/events") as ws:
                    ws.receive_json()  # connected

                    # Unknown track returns 404
                    self.assertEqual(
                        client.post("/api/queue/tracks/missing/retry").status_code, 404
                    )
                    self.assertEqual(
                        client.post("/api/queue/tracks/missing/cancel").status_code, 404
                    )
                    self.assertEqual(
                        client.delete("/api/queue/tracks/missing").status_code, 404
                    )

                    # Single retry (promote tr_a from Failed -> Queued)
                    r1 = client.post("/api/queue/tracks/tr_a/retry")
                    self.assertEqual(r1.status_code, 200)
                    self.assertEqual(self.qm._items["tr_a"].status, "Queued")

                    # Single cancel (tr_b from Queued -> Cancelled)
                    r2 = client.post("/api/queue/tracks/tr_b/cancel")
                    self.assertEqual(r2.status_code, 200)
                    self.assertEqual(self.qm._items["tr_b"].status, "Cancelled")

                    # Batch retry (tr_b is Cancelled, tr_a is Queued)
                    r3 = client.post(
                        "/api/queue/tracks/retry", json={"track_ids": ["tr_b", "tr_a"]}
                    )
                    self.assertEqual(r3.status_code, 200)
                    self.assertEqual(r3.json()["retried_ids"], ["tr_b"])

                    # Batch cancel
                    r4 = client.post(
                        "/api/queue/tracks/cancel", json={"track_ids": ["tr_a", "tr_b"]}
                    )
                    self.assertEqual(r4.status_code, 200)
                    self.assertEqual(r4.json()["cancelled_count"], 2)

                    # Single delete
                    r5 = client.delete("/api/queue/tracks/tr_a")
                    self.assertEqual(r5.status_code, 200)
                    self.assertNotIn("tr_a", self.qm._items)

                    # Batch remove
                    r6 = client.post(
                        "/api/queue/tracks/remove",
                        json={"track_ids": ["tr_b", "tr_c", "nonexistent"]},
                    )
                    self.assertEqual(r6.status_code, 200)
                    self.assertEqual(r6.json()["removed_ids"], ["tr_b", "tr_c"])
                    self.assertEqual(r6.json()["removed_count"], 2)
                    self.assertEqual(self.qm.get_items(), [])

                    removed_events = []
                    for _ in range(30):
                        msg = ws.receive_json()
                        if msg["type"] == "tracks_removed":
                            removed_events.append(msg["payload"]["track_ids"])
                            if msg["payload"]["track_ids"] == ["tr_b", "tr_c"]:
                                break
                    self.assertIn(["tr_a"], removed_events)
                    self.assertIn(["tr_b", "tr_c"], removed_events)

    def test_musilon_prompts_rest_list_and_resolve(self):
        track = self._track("tr_prompt", "Limit Song")
        item = QueueItem(track=track, status="Musilon Issue")
        decisions = []

        with TestClient(self.app) as client:
            self.qm.on_musilon_limit_reached(
                track, item, "HTTP 429 rate limit exceeded", lambda act: decisions.append(act)
            )

            prompts_resp = client.get("/api/queue/prompts")
            self.assertEqual(prompts_resp.status_code, 200)
            prompts = prompts_resp.json()["prompts"]
            self.assertEqual(len(prompts), 1)
            prompt_id = prompts[0]["prompt_id"]
            self.assertEqual(prompts[0]["category"], "quota")

            resolve_resp = client.post(
                f"/api/queue/prompts/{prompt_id}/resolve",
                json={"action": "continue_youtube"},
            )
            self.assertEqual(resolve_resp.status_code, 200)
            self.assertEqual(resolve_resp.json()["action"], "continue_youtube")
            self.assertEqual(decisions, ["continue_youtube"])

            second_resp = client.post(
                f"/api/queue/prompts/{prompt_id}/resolve",
                json={"action": "stop"},
            )
            self.assertEqual(second_resp.status_code, 404)


if __name__ == "__main__":
    unittest.main()
