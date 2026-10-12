import os
import tempfile
import unittest
from pathlib import Path

from core.types import (
    ArchivedTrackRecord,
    SavedPlaylistRecord,
    DownloadProgressCallback,
    StatusCallback,
    CancelCheckCallback,
    PauseWaitCallback
)
from core.exceptions import (
    FlacifyError,
    MetadataResolutionError,
    AudioSourceNotFoundError,
    AudioIntegrityError,
    TaggingError,
    TranscodeError,
    PlaylistSyncError
)
from core.utils import detect_audio_header, is_valid_audio_file
from core.transcoder import AudioTranscoder, SUPPORTED_TARGET_FORMATS
from core.archive import ArchiveManager
from core.spotify_client import TrackMetadata


class TestV132Features(unittest.TestCase):
    def test_types_and_protocols(self):
        # Verify Protocol type checking capability
        def dummy_progress(cur: int, tot: int, spd: float) -> None:
            pass

        def dummy_status(msg: str) -> None:
            pass

        def dummy_cancel() -> bool:
            return False

        def dummy_pause() -> None:
            pass

        self.assertTrue(isinstance(dummy_progress, DownloadProgressCallback))
        self.assertTrue(isinstance(dummy_status, StatusCallback))
        self.assertTrue(isinstance(dummy_cancel, CancelCheckCallback))
        self.assertTrue(isinstance(dummy_pause, PauseWaitCallback))

        # Test TypedDict structure
        track_rec: ArchivedTrackRecord = {
            "spotify_id": "test_id",
            "title": "Title",
            "artist": "Artist",
            "album": "Album",
            "duration_ms": 180000,
            "track_number": 1,
            "disc_number": 1,
            "isrc": "US1234567890",
            "cover_url": "https://example.com/cover.jpg",
            "file_path": "C:/Music/test.flac",
            "quality_badge": "FLAC",
            "source_type": "musilon",
            "genre": "Rock",
            "archived_at": "2026-10-12 12:00:00"
        }
        self.assertEqual(track_rec["spotify_id"], "test_id")

    def test_domain_exception_hierarchy(self):
        self.assertTrue(issubclass(MetadataResolutionError, FlacifyError))
        self.assertTrue(issubclass(AudioSourceNotFoundError, FlacifyError))
        self.assertTrue(issubclass(AudioIntegrityError, FlacifyError))
        self.assertTrue(issubclass(TaggingError, FlacifyError))
        self.assertTrue(issubclass(TranscodeError, FlacifyError))
        self.assertTrue(issubclass(PlaylistSyncError, FlacifyError))

        try:
            raise TranscodeError("FFmpeg transcode failed")
        except FlacifyError as e:
            self.assertIn("FFmpeg transcode failed", str(e))

    def test_webm_audio_header_detection(self):
        with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as f:
            # EBML header (WebM container)
            f.write(b"\x1a\x45\xdf\xa3\x9f\x42\x86\x81\x01\x42\xf7\x81\x01\x42\xf2\x81\x04\x42\xf3\x81\x08")
            f.write(b"\x00" * 4096)
            temp_path = f.name

        try:
            self.assertEqual(detect_audio_header(temp_path), "webm")
            is_valid, _ = is_valid_audio_file(temp_path, min_size=100)
            self.assertTrue(is_valid)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_transcoder_supported_formats(self):
        transcoder = AudioTranscoder()
        self.assertIn("alac", SUPPORTED_TARGET_FORMATS)
        self.assertIn("mp3", SUPPORTED_TARGET_FORMATS)
        self.assertIn("flac", SUPPORTED_TARGET_FORMATS)
        self.assertIn("opus", SUPPORTED_TARGET_FORMATS)

        self.assertEqual(transcoder.get_extension_for_format("alac"), ".m4a")
        self.assertEqual(transcoder.get_extension_for_format("mp3"), ".mp3")
        self.assertEqual(transcoder.get_extension_for_format("flac"), ".flac")
        self.assertEqual(transcoder.get_extension_for_format("opus"), ".opus")

    def test_archive_connection_context_and_differential_sync(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "test_archive.db"
            ArchiveManager._instance = None
            archive = ArchiveManager(db_path=db_path)

            # Test connection context manager
            with archive.connection() as conn:
                cur = conn.execute("PRAGMA journal_mode")
                mode = cur.fetchone()[0]
                self.assertEqual(mode.lower(), "wal")

            # Seed initial saved playlist
            initial_tracks = [
                TrackMetadata(id="sp1", title="Track 1", artists=["Artist A"], album="Album 1"),
                TrackMetadata(id="sp2", title="Track 2", artists=["Artist A"], album="Album 1"),
            ]
            archive.save_playlist(
                name="Test Playlist",
                spotify_url="https://open.spotify.com/playlist/pl1",
                cover_url="",
                tracks=initial_tracks,
                playlist_id="pl1"
            )

            saved = archive.get_saved_playlist("pl1")
            self.assertIsNotNone(saved)
            self.assertEqual(saved["total_tracks"], 2)

            # Differential sync: Add sp3, remove sp1, keep sp2
            updated_tracks = [
                TrackMetadata(id="sp2", title="Track 2", artists=["Artist A"], album="Album 1"),
                TrackMetadata(id="sp3", title="Track 3", artists=["Artist B"], album="Album 2"),
            ]
            res = archive.sync_saved_playlist("pl1", updated_tracks)
            self.assertEqual(res["added"], 1)
            self.assertEqual(res["removed"], 1)
            self.assertEqual(res["total"], 2)
            self.assertEqual(len(res["delta_tracks"]), 1)
            self.assertEqual(res["delta_tracks"][0].id, "sp3")

            # Verify remaining playlist tracks in database
            current_tracks = archive.get_saved_playlist_tracks("pl1")
            current_ids = {t["spotify_id"] for t in current_tracks}
            self.assertIn("sp2", current_ids)
            self.assertIn("sp3", current_ids)
            self.assertNotIn("sp1", current_ids)


if __name__ == "__main__":
    unittest.main()
