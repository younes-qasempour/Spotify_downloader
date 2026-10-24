import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock
from core.config import config
from core.spotify_client import TrackMetadata
from core.archive import ArchiveManager

class TestSubfolderSettings(unittest.TestCase):
    def setUp(self):
        self.original_output_dir = config.get("download.output_dir")
        self.original_subfolders = config.get("download.save_in_subfolders", False)
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "test_archive.db")
        self.archive = ArchiveManager(db_path=self.db_path)
        config.set("download.output_dir", self.test_dir)
        config.set("download.save_in_subfolders", False)

    def tearDown(self):
        if self.original_output_dir:
            config.set("download.output_dir", self.original_output_dir)
        config.set("download.save_in_subfolders", self.original_subfolders)
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_save_in_subfolders_toggle(self):
        # Default should be False
        self.assertFalse(config.get("download.save_in_subfolders", False))

        track = TrackMetadata(
            id="test1",
            title="Song",
            artists=["Artist"],
            album="Album",
            collection_name="My Playlist",
            collection_type="playlist"
        )
        self.assertEqual(track.target_folder, "My Playlist")

        base_output_dir = r"D:\Spotify-Downloader\downloads"

        # When save_in_subfolders is False
        config.set("download.save_in_subfolders", False)
        save_in_subfolders = config.get("download.save_in_subfolders", False)
        subfolder = getattr(track, "target_folder", "") if save_in_subfolders else ""
        self.assertEqual(subfolder, "")
        output_dir = os.path.join(base_output_dir, subfolder) if subfolder else base_output_dir
        self.assertEqual(output_dir, base_output_dir)

        # When save_in_subfolders is True
        config.set("download.save_in_subfolders", True)
        save_in_subfolders = config.get("download.save_in_subfolders", False)
        subfolder = getattr(track, "target_folder", "") if save_in_subfolders else ""
        self.assertEqual(subfolder, "My Playlist")
        output_dir = os.path.join(base_output_dir, subfolder) if subfolder else base_output_dir
        self.assertEqual(output_dir, os.path.join(base_output_dir, "My Playlist"))

        # Restore default
        config.set("download.save_in_subfolders", False)

    def test_m3u8_central_playlists_folder(self):
        # Create audio files in central download folder
        t1_file = os.path.join(self.test_dir, "Artist - Track One.mp3")
        t2_file = os.path.join(self.test_dir, "Artist - Track Two.flac")
        with open(t1_file, "wb") as f:
            f.write(b"dummy mp3 data")
        with open(t2_file, "wb") as f:
            f.write(b"dummy flac data")

        t1 = TrackMetadata(id="t1", title="Track One", artists=["Artist"], album="Album", duration_ms=180000)
        t2 = TrackMetadata(id="t2", title="Track Two", artists=["Artist"], album="Album", duration_ms=200000)

        # Add to archive
        self.archive.add_track(t1, t1_file, "MP3 320k", "Musilon")
        self.archive.add_track(t2, t2_file, "FLAC 16", "Musilon")

        # Save playlist
        self.archive.save_playlist(
            name="Workout Beats",
            spotify_url="https://open.spotify.com/playlist/workout",
            cover_url="",
            tracks=[t1, t2],
            playlist_id="pl_workout"
        )

        # Export M3U8 in single-folder mode
        m3u8_path = self.archive.export_saved_playlist_m3u8("pl_workout")
        self.assertIsNotNone(m3u8_path)
        self.assertTrue(os.path.isfile(m3u8_path))

        # Must be located in playlists/ subfolder
        expected_dir = os.path.join(self.test_dir, "playlists")
        self.assertEqual(os.path.dirname(m3u8_path), expected_dir)

        # Must contain relative paths pointing to ../<filename>
        with open(m3u8_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("#PLAYLIST:Workout Beats", content)
        self.assertIn("../Artist - Track One.mp3", content)
        self.assertIn("../Artist - Track Two.flac", content)

    def test_export_collection_m3u8(self):
        t1_file = os.path.join(self.test_dir, "Rock - Anthem.mp3")
        with open(t1_file, "wb") as f:
            f.write(b"audio")
        t1 = TrackMetadata(id="r1", title="Anthem", artists=["Rock"], album="Rock Album", duration_ms=120000)
        self.archive.add_track(t1, t1_file, "MP3 320k", "Musilon")
        self.archive.save_playlist(name="Rock Classics", spotify_url="", cover_url="", tracks=[t1], playlist_id="rock_pl")

        p = self.archive.export_collection_m3u8("Rock Classics")
        self.assertIsNotNone(p)
        self.assertTrue(os.path.isfile(p))
        self.assertTrue(p.endswith("Rock Classics.m3u8"))

if __name__ == "__main__":
    unittest.main()
