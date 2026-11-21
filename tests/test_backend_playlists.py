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


class TestBackendPlaylists(unittest.TestCase):
    def setUp(self):
        self._prev_archive_instance = ArchiveManager._instance
        ArchiveManager._instance = None
        self.tmp_dir = tempfile.mkdtemp(prefix="flacify_playlists_api_test_")
        self.db_path = os.path.join(self.tmp_dir, "test_archive.db")
        self.archive = ArchiveManager(db_path=self.db_path)

        self.fake_config = FakeConfig()
        self.fake_config.set("download.output_dir", self.tmp_dir)
        self.mock_ytdlp = MagicMock()
        self.mock_audio_engine = MagicMock()
        self.mock_audio_engine.ytdlp = self.mock_ytdlp
        self.mock_spotify = MagicMock()
        self.mock_spotify.last_resolution_mode = "api"
        self.mock_spotify.last_was_truncated = False
        self.mock_spotify.last_api_error = ""
        self.mock_spotify.last_owner_name = ""
        self.mock_spotify._cached_user_name = ""
        self.mock_spotify.has_user_auth.return_value = False
        self.mock_spotify.get_current_user_name.return_value = ""

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

    @staticmethod
    def _track(
        track_id: str,
        title: str,
        artist: str = "Daft Punk",
        album: str = "Discovery",
        duration_ms: int = 200000,
        genres=None,
        track_number: int = 1,
        collection_name: str = "Synthwave Hits",
    ) -> TrackMetadata:
        return TrackMetadata(
            id=track_id,
            title=title,
            artists=[artist],
            album=album,
            duration_ms=duration_ms,
            track_number=track_number,
            genres=genres or [],
            collection_type="playlist",
            collection_name=collection_name,
            collection_cover_url="",
            cover_url="",
        )

    def test_save_list_get_filter_sort_and_delete_playlist(self):
        t1 = self._track("t1", "Zebra Song", artist="B Artist", duration_ms=120000, genres=["Synthpop"], track_number=1)
        t2 = self._track("t2", "Alpha Song", artist="A Artist", duration_ms=320000, genres=["Electronic"], track_number=2)
        t3 = self._track("t3", "Middle Song", artist="C Artist", duration_ms=220000, genres=[], track_number=3)
        self.mock_spotify.resolve.return_value = [t1, t2, t3]
        self.mock_spotify.last_resolution_mode = "guest"
        self.mock_spotify.last_was_truncated = True

        with TestClient(self.app) as client:
            save_resp = client.post(
                "/api/playlists",
                json={"url": "https://open.spotify.com/playlist/pl1001"},
            )
            self.assertEqual(save_resp.status_code, 200)
            save_data = save_resp.json()
            self.assertTrue(save_data["is_guest"])
            self.assertTrue(save_data["was_truncated"])
            self.assertEqual(save_data["playlist"]["id"], "pl1001")
            self.assertEqual(save_data["playlist"]["total_tracks"], 3)

            list_resp = client.get("/api/playlists", params={"search": "synth"})
            self.assertEqual(list_resp.status_code, 200)
            list_data = list_resp.json()
            self.assertEqual(len(list_data["playlists"]), 1)
            self.assertEqual(list_data["summary"]["total_playlists"], 1)
            self.assertEqual(list_data["summary"]["total_tracks"], 3)
            self.assertEqual(list_data["summary"]["pending_count"], 3)

            # Detail view with sort by title
            det_title = client.get("/api/playlists/pl1001", params={"sort": "title", "reconcile": "false"})
            self.assertEqual(det_title.status_code, 200)
            det_data = det_title.json()
            self.assertEqual([t["title"] for t in det_data["tracks"]], ["Alpha Song", "Middle Song", "Zebra Song"])
            self.assertEqual(det_data["available_genres"], ["Electronic", "Synthpop"])

            # Sort duration_desc
            det_dur = client.get("/api/playlists/pl1001", params={"sort": "duration_desc", "reconcile": "false"})
            self.assertEqual([t["spotify_id"] for t in det_dur.json()["tracks"]], ["t2", "t3", "t1"])

            # Sort genre (populated genres first, alphabetically)
            det_genre = client.get("/api/playlists/pl1001", params={"sort": "genre", "reconcile": "false"})
            self.assertEqual([t["spotify_id"] for t in det_genre.json()["tracks"]], ["t2", "t1", "t3"])

            # Filter by genre, search, status
            det_filt = client.get(
                "/api/playlists/pl1001",
                params={"genre": "Synthpop", "search": "Zebra", "status": "pending", "reconcile": "false"},
            )
            self.assertEqual([t["spotify_id"] for t in det_filt.json()["tracks"]], ["t1"])

            # Patch metadata
            patch_resp = client.patch(
                "/api/playlists/pl1001",
                json={"name": "Renamed Mix", "spotify_url": "https://open.spotify.com/playlist/pl1001"},
            )
            self.assertEqual(patch_resp.status_code, 200)
            self.assertEqual(patch_resp.json()["playlist"]["name"], "Renamed Mix")

            # Delete playlist
            del_resp = client.delete("/api/playlists/pl1001")
            self.assertEqual(del_resp.status_code, 200)
            self.assertEqual(client.get("/api/playlists/pl1001").status_code, 404)

    def test_save_playlist_validation_errors(self):
        with TestClient(self.app) as client:
            self.assertEqual(
                client.post("/api/playlists", json={"url": "   "}).status_code, 400
            )
            self.assertEqual(
                client.post("/api/playlists", json={"url": "https://example.com/nope"}).status_code, 400
            )
            self.assertEqual(
                client.post("/api/playlists", json={"url": "https://open.spotify.com/track/tr999"}).status_code, 400
            )

    def test_batch_download_selected_download_and_reset_queued(self):
        t1 = self._track("t1", "Track 1", track_number=1)
        t2 = self._track("t2", "Track 2", track_number=2)
        t3 = self._track("t3", "Track 3", track_number=3)
        self.archive.save_playlist("Batch Mix", "https://open.spotify.com/playlist/pl2002", "", [t1, t2, t3], playlist_id="pl2002")

        with patch.object(DownloadQueueManager, "_worker_loop", lambda self: None):
            with TestClient(self.app) as client:
                batch_resp = client.post("/api/playlists/pl2002/download-batch", json={"batch_size": 2})
                self.assertEqual(batch_resp.status_code, 200)
                batch_data = batch_resp.json()
                self.assertEqual(batch_data["queued_count"], 2)
                self.assertEqual(batch_data["track_ids"], ["t1", "t2"])

                # Download selected (only remaining t3 is pending; t1 is already queued, mark t2 downloaded to verify skip)
                self.archive.mark_saved_track_downloaded("t2", os.path.join(self.tmp_dir, "t2.flac"), "16-BIT FLAC", "Musilon")
                sel_resp = client.post(
                    "/api/playlists/pl2002/download-selected",
                    json={"track_ids": ["t2", "t3"], "preferred_engine": "musilon"},
                )
                self.assertEqual(sel_resp.status_code, 200)
                self.assertEqual(sel_resp.json()["track_ids"], ["t3"])
                self.assertEqual(self.qm._items["t3"].preferred_engine, "musilon")

                # Reset queued (t1 and t3 are queued -> revert to pending)
                reset_resp = client.post("/api/playlists/pl2002/reset-queued")
                self.assertEqual(reset_resp.status_code, 200)
                self.assertEqual(reset_resp.json()["reverted_count"], 2)
                pending = self.archive.get_saved_playlist_tracks("pl2002", status="pending")
                self.assertEqual({r["spotify_id"] for r in pending}, {"t1", "t3"})

    def test_track_edit_cancel_reset_delete_file_and_redownload(self):
        t1 = self._track("t10", "Original Title", artist="Old Artist", album="Old Album")
        audio_path = os.path.join(self.tmp_dir, "Old Artist - Original Title.flac")
        with open(audio_path, "wb") as fh:
            fh.write(b"fLaC" + b"\x00" * 128)

        self.archive.add_track(t1, audio_path, "16-BIT FLAC", "Musilon")
        self.archive.save_playlist("Edit Mix", "https://open.spotify.com/playlist/pl3003", "", [t1], playlist_id="pl3003")

        with patch.object(DownloadQueueManager, "_worker_loop", lambda self: None):
            with TestClient(self.app) as client:
                # Edit track metadata
                edit_resp = client.patch(
                    "/api/playlists/pl3003/tracks/t10",
                    json={"title": "New Title", "artist": "New Artist", "album": "New Album"},
                )
                self.assertEqual(edit_resp.status_code, 200)
                det = client.get("/api/playlists/pl3003", params={"reconcile": "false"}).json()
                self.assertEqual(det["tracks"][0]["title"], "New Title")
                self.assertEqual(det["tracks"][0]["artist"], "New Artist")

                # Redownload via melobot (deletes old file, removes downloaded record, enqueues)
                redl_resp = client.post(
                    "/api/playlists/pl3003/download-selected",
                    json={"track_ids": ["t10"], "preferred_engine": "melobot", "redownload": True},
                )
                self.assertEqual(redl_resp.status_code, 200)
                self.assertEqual(redl_resp.json()["queued_count"], 1)
                self.assertFalse(os.path.exists(audio_path))
                self.assertEqual(self.qm._items["t10"].preferred_engine, "melobot")

                # Cancel track in playlist
                cancel_resp = client.post("/api/playlists/pl3003/tracks/t10/cancel")
                self.assertEqual(cancel_resp.status_code, 200)
                self.assertEqual(self.qm._items["t10"].status, "Cancelled")
                pending = self.archive.get_saved_playlist_tracks("pl3003", status="pending")
                self.assertEqual(len(pending), 1)

                # Reset track status & test deleting file from disk
                second_path = os.path.join(self.tmp_dir, "recreated.flac")
                with open(second_path, "wb") as fh:
                    fh.write(b"fLaC" + b"\x00" * 128)
                self.archive.add_track(t1, second_path, "16-BIT FLAC", "MeloBot")
                self.archive.mark_saved_track_downloaded("t10", second_path, "16-BIT FLAC", "MeloBot")

                del_file_resp = client.delete("/api/playlists/pl3003/tracks/t10/file")
                self.assertEqual(del_file_resp.status_code, 200)
                self.assertTrue(del_file_resp.json()["file_removed"])
                self.assertFalse(os.path.exists(second_path))
                self.assertEqual(del_file_resp.json()["playlist"]["pending_count"], 1)

                # Single reset status endpoint
                reset_single = client.post("/api/playlists/pl3003/tracks/t10/reset")
                self.assertEqual(reset_single.status_code, 200)

    def test_sync_single_playlist_and_sync_all(self):
        t1 = self._track("s1", "Existing Song", track_number=1)
        t2 = self._track("s2", "Delta Song", track_number=2)
        self.archive.save_playlist("Sync Mix", "https://open.spotify.com/playlist/pl4004", "", [t1], playlist_id="pl4004")

        def fake_resolve(url, progress_callback=None):
            if progress_callback:
                progress_callback(2, 2)
            return [t1, t2]

        self.mock_spotify.resolve.side_effect = fake_resolve

        with patch.object(DownloadQueueManager, "_worker_loop", lambda self: None):
            with TestClient(self.app) as client:
                with client.websocket_connect("/ws/events") as ws:
                    ws.receive_json()  # connected

                    sync_resp = client.post("/api/playlists/pl4004/sync")
                    self.assertEqual(sync_resp.status_code, 200)
                    sync_data = sync_resp.json()
                    self.assertEqual(sync_data["added"], 1)
                    self.assertEqual(sync_data["total"], 2)
                    self.assertEqual(sync_data["queued_count"], 1)
                    self.assertIn("s2", self.qm._items)

                    seen_types = set()
                    for _ in range(10):
                        msg = ws.receive_json()
                        seen_types.add(msg["type"])
                        if {"playlist_sync_progress", "playlist_synced"}.issubset(seen_types):
                            break
                    self.assertIn("playlist_sync_progress", seen_types)
                    self.assertIn("playlist_synced", seen_types)

                # Sync all
                t3 = self._track("s3", "Third Song", track_number=3)
                self.mock_spotify.resolve.side_effect = lambda url, progress_callback=None: [t1, t2, t3]
                sync_all_resp = client.post("/api/playlists/sync-all")
                self.assertEqual(sync_all_resp.status_code, 200)
                all_data = sync_all_resp.json()
                self.assertEqual(all_data["checked_count"], 1)
                self.assertEqual(all_data["total_added"], 1)

    def test_auto_sync_toggle_schedule_and_watched_run(self):
        t1 = self._track("w1", "Watch Base", track_number=1)
        t2 = self._track("w2", "Watch Delta", track_number=2)
        self.archive.save_playlist("Watched Mix", "https://open.spotify.com/playlist/pl5005", "", [t1], playlist_id="pl5005")
        self.mock_spotify.resolve.return_value = [t1, t2]

        with patch.object(DownloadQueueManager, "_worker_loop", lambda self: None):
            with TestClient(self.app) as client:
                with client.websocket_connect("/ws/events") as ws:
                    ws.receive_json()  # connected

                    tog_resp = client.put("/api/playlists/pl5005/auto-sync", json={"enabled": True})
                    self.assertEqual(tog_resp.status_code, 200)
                    self.assertTrue(tog_resp.json()["auto_sync"])

                    sched_resp = client.put(
                        "/api/playlists/auto-sync/schedule",
                        json={"on_startup": False, "interval_hours": 3, "auto_download_synced_tracks": True},
                    )
                    self.assertEqual(sched_resp.status_code, 200)
                    self.assertFalse(sched_resp.json()["on_startup"])
                    self.assertEqual(sched_resp.json()["interval_hours"], 3)

                    run_resp = client.post("/api/playlists/auto-sync/run")
                    self.assertEqual(run_resp.status_code, 200)
                    run_data = run_resp.json()
                    self.assertEqual(run_data["checked_count"], 1)
                    self.assertEqual(run_data["total_added"], 1)
                    self.assertEqual(run_data["queued_count"], 1)
                    self.assertIn("w2", self.qm._items)

                    found_watched_event = False
                    for _ in range(12):
                        msg = ws.receive_json()
                        if msg["type"] == "watched_playlists_synced":
                            self.assertEqual(msg["payload"]["total_added"], 1)
                            found_watched_event = True
                            break
                    self.assertTrue(found_watched_event)


if __name__ == "__main__":
    unittest.main()
