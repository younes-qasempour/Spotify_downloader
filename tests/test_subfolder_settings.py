import os
import unittest
from unittest.mock import MagicMock
from core.config import config
from core.spotify_client import TrackMetadata

class TestSubfolderSettings(unittest.TestCase):
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

if __name__ == "__main__":
    unittest.main()
