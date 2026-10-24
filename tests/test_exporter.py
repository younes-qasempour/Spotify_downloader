import os
import shutil
import tempfile
import unittest
import threading
from unittest.mock import patch, MagicMock

from core.exporter import ExportConfig, ExportResult, PlaylistExporter


class TestPlaylistExporter(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.src_dir = os.path.join(self.temp_dir, "master_library")
        self.dest_dir = os.path.join(self.temp_dir, "export_destination")
        os.makedirs(self.src_dir, exist_ok=True)
        os.makedirs(self.dest_dir, exist_ok=True)

        # Create dummy track files
        self.track1_path = os.path.join(self.src_dir, "Song One.flac")
        with open(self.track1_path, "wb") as f:
            f.write(b"FLAC_DATA_" * 200)

        self.track2_path = os.path.join(self.src_dir, "Song Two.mp3")
        with open(self.track2_path, "wb") as f:
            f.write(b"MP3_DATA_" * 200)

        self.tracks = [
            {
                "file_path": self.track1_path,
                "title": "Song One",
                "artist": "Artist Alpha",
                "duration_ms": 180000
            },
            {
                "file_path": self.track2_path,
                "title": "Song Two",
                "artist": "Artist Beta",
                "duration_ms": 210000
            }
        ]

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_export_original_direct_copy_and_m3u8(self):
        config = ExportConfig(
            destination_dir=self.dest_dir,
            create_playlist_subfolder=True,
            target_format="original",
            generate_m3u8=True,
            skip_existing=True
        )

        progress_reports = []
        def on_progress(current, total, msg):
            progress_reports.append((current, total, msg))

        result = PlaylistExporter.export_tracks(
            playlist_name="Gym Workout",
            tracks=self.tracks,
            config=config,
            progress_callback=on_progress
        )

        self.assertEqual(result.total, 2)
        self.assertEqual(result.exported, 2)
        self.assertEqual(result.skipped, 0)
        self.assertEqual(result.failed, 0)
        self.assertFalse(result.cancelled)

        expected_folder = os.path.join(self.dest_dir, "Gym Workout")
        self.assertTrue(os.path.isdir(expected_folder))

        # Check copied files
        dest_track1 = os.path.join(expected_folder, "Song One.flac")
        dest_track2 = os.path.join(expected_folder, "Song Two.mp3")
        self.assertTrue(os.path.isfile(dest_track1))
        self.assertTrue(os.path.isfile(dest_track2))

        # Check m3u8 playlist file
        self.assertIsNotNone(result.m3u8_path)
        self.assertTrue(os.path.isfile(result.m3u8_path))
        with open(result.m3u8_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("#EXTM3U", content)
        self.assertIn("#PLAYLIST:Gym Workout", content)
        self.assertIn("#EXTINF:180,Artist Alpha - Song One", content)
        self.assertIn("Song One.flac", content)
        self.assertIn("#EXTINF:210,Artist Beta - Song Two", content)
        self.assertIn("Song Two.mp3", content)
        # Verify relative filenames used for portable playback
        self.assertNotIn(self.src_dir, content)

    def test_export_skip_existing(self):
        config = ExportConfig(
            destination_dir=self.dest_dir,
            create_playlist_subfolder=True,
            target_format="original",
            skip_existing=True
        )

        # First export copies both
        res1 = PlaylistExporter.export_tracks("Chill", self.tracks, config)
        self.assertEqual(res1.exported, 2)
        self.assertEqual(res1.skipped, 0)

        # Second export with skip_existing should skip both
        res2 = PlaylistExporter.export_tracks("Chill", self.tracks, config)
        self.assertEqual(res2.exported, 0)
        self.assertEqual(res2.skipped, 2)
        self.assertEqual(res2.total, 2)

    @patch("core.exporter.transcode_audio")
    def test_export_transcode_target_format(self, mock_transcode):
        def fake_transcode(input_file, target_format, delete_source, output_file):
            with open(output_file, "wb") as f:
                f.write(b"MOCK_MP3_DATA")
            return output_file

        mock_transcode.side_effect = fake_transcode

        config = ExportConfig(
            destination_dir=self.dest_dir,
            create_playlist_subfolder=False,
            target_format="mp3",
            generate_m3u8=True,
            skip_existing=False
        )

        result = PlaylistExporter.export_tracks("Road Trip", self.tracks, config)
        self.assertEqual(result.exported, 2)
        self.assertEqual(mock_transcode.call_count, 2)

        # Verifies calls were made with output_file parameter to export dir
        calls = mock_transcode.call_args_list
        self.assertEqual(calls[0].kwargs["target_format"], "mp3")
        self.assertTrue(calls[0].kwargs["output_file"].endswith("Song One.mp3"))

    def test_export_cancellation(self):
        cancel_event = threading.Event()
        cancel_event.set()

        config = ExportConfig(
            destination_dir=self.dest_dir,
            create_playlist_subfolder=True
        )

        result = PlaylistExporter.export_tracks(
            "Quick",
            self.tracks,
            config,
            cancel_event=cancel_event
        )

        self.assertTrue(result.cancelled)
        self.assertEqual(result.exported, 0)

    def test_export_missing_file_graceful(self):
        tracks_with_missing = [
            {
                "file_path": os.path.join(self.src_dir, "Ghost.mp3"),
                "title": "Ghost Song",
                "artist": "Nobody",
                "duration_ms": 100000
            },
            self.tracks[0]
        ]

        config = ExportConfig(
            destination_dir=self.dest_dir,
            create_playlist_subfolder=True,
            target_format="original"
        )

        result = PlaylistExporter.export_tracks("Mixed", tracks_with_missing, config)
        self.assertEqual(result.total, 2)
        self.assertEqual(result.failed, 1)
        self.assertEqual(result.exported, 1)
        self.assertEqual(len(result.errors), 1)
        self.assertIn("Ghost Song", result.errors[0])

    def test_export_dialog_progress_and_completion(self):
        import sys
        from PyQt6.QtWidgets import QApplication
        from gui.dialogs.export_dialog import ExportDialog

        app = QApplication.instance() or QApplication(sys.argv)
        diag = ExportDialog("Test Playlist", self.tracks)
        self.assertFalse(diag.validate(), "validate() must return False so MessageBoxBase does not close early")
        self.assertEqual(len(diag.valid_tracks), 2)
        self.assertTrue(hasattr(diag, "progress_bar"))
        self.assertTrue(hasattr(diag, "progress_pct_label"))

        # Test live progress update
        diag._on_progress_update(1, 2, "Converting: Song One - Artist Alpha")
        self.assertEqual(diag.progress_bar.value(), 50)
        self.assertEqual(diag.progress_pct_label.text(), "50%")
        self.assertIn("1 of 2", diag.progress_counter_label.text())
        self.assertIn("Converting: Song One", diag.progress_caption.text())

        # Test completion display
        dummy_result = ExportResult(total=2, exported=2, export_dir=self.dest_dir, m3u8_path=os.path.join(self.dest_dir, "test.m3u8"))
        diag._on_export_finished(dummy_result)
        self.assertEqual(diag.progress_bar.value(), 100)
        self.assertEqual(diag.progress_pct_label.text(), "100%")
        self.assertFalse(diag.result_card.isHidden())
        self.assertFalse(diag.open_folder_btn.isHidden())
        self.assertEqual(diag.cancelButton.text(), "Done")
        self.assertIn("Successfully exported 2 song(s)", diag.result_body.text())
        diag.close()


if __name__ == "__main__":
    unittest.main()
