import os
import sys
import tempfile
import shutil
import unittest
from unittest.mock import MagicMock

# Add project root to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.archive import ArchiveManager
from core.spotify_client import TrackMetadata
from core.config import config
from gui.web_api import FlacifyWebRequestHandler, WebBackendState


class TestV170SavedPlaylistsFeatures(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test_v170_saved.db")
        ArchiveManager._instance = None
        self.archive = ArchiveManager(db_path=self.db_path)

        # Mock download directory
        self.orig_out_dir = config.get("download.output_dir", "")
        config.set("download.output_dir", self.temp_dir)

        # Create mock tracks
        self.tracks = [
            TrackMetadata(
                id=f"track_v170_{i}",
                title=f"Song Title {i}",
                artists=[f"Artist {i}"],
                album=f"Album {i}",
                duration_ms=180000 + i * 1000,
                track_number=i,
                disc_number=1,
                isrc=f"ISRC_V170_{i}",
                cover_url=f"https://example.com/cover_{i}.jpg",
                collection_name="Synthwave Classics",
                collection_type="playlist"
            )
            for i in range(1, 11)
        ]

        self.archive.save_playlist(
            name="Synthwave Classics",
            spotify_url="https://open.spotify.com/playlist/synth_001",
            cover_url="https://example.com/cover_synth.jpg",
            tracks=self.tracks,
            playlist_id="synth_001"
        )

        # Set up WebBackendState and mock queue manager
        self.mock_qm = MagicMock()
        self.mock_qm.enqueue = MagicMock()
        self.mock_qm.start_all = MagicMock()

        self.state = WebBackendState(queue_manager=self.mock_qm, archive_manager=self.archive)

    def tearDown(self):
        ArchiveManager._instance = None
        config.set("download.output_dir", self.orig_out_dir)
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _execute_api_action(self, body):
        handler = object.__new__(FlacifyWebRequestHandler)
        handler.state = self.state
        handler.archive = self.archive

        last_json = {}
        last_status = 200

        def mock_send_json(data, status=200):
            nonlocal last_json, last_status
            last_json = data
            last_status = status

        handler._send_json = mock_send_json
        handler._handle_saved_playlists_action(body)
        return last_json, last_status

    def test_archive_reset_status_and_delete_track(self):
        """Test reset_saved_playlist_tracks_status and delete_saved_playlist_track."""
        # 1. Mark some tracks as queued
        self.archive.mark_saved_tracks_queued("synth_001", ["track_v170_1", "track_v170_2"])
        queued = self.archive.get_saved_playlist_tracks("synth_001", status="queued")
        self.assertEqual(len(queued), 2)

        # 2. Reset status
        count_reset = self.archive.reset_saved_playlist_tracks_status("synth_001")
        self.assertEqual(count_reset, 2)
        queued_after = self.archive.get_saved_playlist_tracks("synth_001", status="queued")
        self.assertEqual(len(queued_after), 0)
        pending_after = self.archive.get_saved_playlist_tracks("synth_001", status="pending")
        self.assertEqual(len(pending_after), 10)

        # 3. Delete single track
        ok_del = self.archive.delete_saved_playlist_track("synth_001", "track_v170_5")
        self.assertTrue(ok_del)
        all_tracks = self.archive.get_saved_playlist_tracks("synth_001")
        self.assertEqual(len(all_tracks), 9)
        self.assertNotIn("track_v170_5", [t["spotify_id"] for t in all_tracks])

        # Playlist total_tracks counter in header should update
        pl = self.archive.get_saved_playlist("synth_001")
        self.assertEqual(pl["total_tracks"], 9)

    def test_api_download_batch_with_limit(self):
        """Test Web API download_batch action respecting limit parameter."""
        res, status = self._execute_api_action({
            "action": "download_batch",
            "playlist_id": "synth_001",
            "limit": 3
        })

        self.assertEqual(status, 200)
        self.assertTrue(res.get("ok"))
        self.assertEqual(res.get("queued"), 3)
        self.assertEqual(self.mock_qm.enqueue.call_count, 1)
        enqueued_batch = self.mock_qm.enqueue.call_args[0][0]
        self.assertEqual(len(enqueued_batch), 3)

    def test_api_download_selected(self):
        """Test Web API download_selected action with explicit spotify_ids."""
        res, status = self._execute_api_action({
            "action": "download_selected",
            "playlist_id": "synth_001",
            "spotify_ids": ["track_v170_4", "track_v170_7"]
        })

        self.assertEqual(status, 200)
        self.assertTrue(res.get("ok"))
        self.assertEqual(res.get("queued"), 2)
        self.assertEqual(self.mock_qm.enqueue.call_count, 1)
        enqueued_batch = self.mock_qm.enqueue.call_args[0][0]
        self.assertEqual(len(enqueued_batch), 2)
        queued_ids = [t.id for t in enqueued_batch]
        self.assertIn("track_v170_4", queued_ids)
        self.assertIn("track_v170_7", queued_ids)

    def test_api_edit_playlist_and_track(self):
        """Test editing playlist metadata and individual track metadata via Web API."""
        # Edit playlist
        res_pl, _ = self._execute_api_action({
            "action": "edit_playlist",
            "playlist_id": "synth_001",
            "name": "Updated Synthwave Retrowave",
            "spotify_url": "https://open.spotify.com/playlist/synth_001_updated",
            "cover_url": "https://example.com/new_cover.jpg"
        })
        self.assertTrue(res_pl.get("ok"))
        pl = self.archive.get_saved_playlist("synth_001")
        self.assertEqual(pl["name"], "Updated Synthwave Retrowave")
        self.assertEqual(pl["spotify_url"], "https://open.spotify.com/playlist/synth_001_updated")

        # Edit track metadata
        res_tr, _ = self._execute_api_action({
            "action": "edit_track",
            "playlist_id": "synth_001",
            "spotify_id": "track_v170_1",
            "title": "Neon Nights (Remastered)",
            "artist": "Kavinsky & Gunship",
            "album": "Nightcall EP"
        })
        self.assertTrue(res_tr.get("ok"))
        tracks = self.archive.get_saved_playlist_tracks("synth_001")
        tr1 = next(t for t in tracks if t["spotify_id"] == "track_v170_1")
        self.assertEqual(tr1["title"], "Neon Nights (Remastered)")
        self.assertEqual(tr1["artist"], "Kavinsky & Gunship")
        self.assertEqual(tr1["album"], "Nightcall EP")

    def test_api_export_m3u8(self):
        """Test exporting playlist to M3U8 when downloaded tracks exist."""
        # Create a mock audio file on disk
        audio_file = os.path.join(self.temp_dir, "synth_song1.flac")
        with open(audio_file, "wb") as f:
            f.write(b"fLaCdummy")

        self.archive.mark_saved_track_downloaded("track_v170_1", audio_file, "FLAC 16", "Musilon")

        res, status = self._execute_api_action({
            "action": "export_m3u8",
            "playlist_id": "synth_001"
        })
        self.assertEqual(status, 200)
        self.assertTrue(res.get("ok"))
        m3u_path = res.get("file_path")
        self.assertTrue(os.path.exists(m3u_path))
        with open(m3u_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("#EXTM3U", content)
        self.assertIn("synth_song1.flac", content)


if __name__ == "__main__":
    unittest.main()
