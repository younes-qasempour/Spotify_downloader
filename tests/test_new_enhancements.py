import os
import shutil
import tempfile
import unittest

from core.utils import (
    sanitize_path_template,
    generate_m3u8_file,
    calculate_replaygain
)
from core.archive import ArchiveManager
from core.spotify_client import TrackMetadata
from core.ytdlp_engine import YtdlpEngine


class TestNewEnhancements(unittest.TestCase):

    def setUp(self):
        ArchiveManager._instance = None
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "test_archive.db")
        self.archive = ArchiveManager(db_path=self.db_path)

    def tearDown(self):
        ArchiveManager._instance = None
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_sanitize_path_template(self):
        # Forward and backslashes should be preserved for directory hierarchy
        expected = os.path.normpath("{artist}/{album}/{title}")
        self.assertEqual(sanitize_path_template("{artist}/{album}/{title}"), expected)
        self.assertEqual(sanitize_path_template(r"{artist}\{title}"), os.path.normpath(r"{artist}\{title}"))
        # Illegal characters like colons, asterisks, question marks should be sanitized
        self.assertEqual(sanitize_path_template("{artist}: *best*?/{title}"), os.path.normpath("{artist} best/{title}"))

    def test_m3u8_generator(self):
        playlist_dir = os.path.join(self.test_dir, "Chill Mix")
        os.makedirs(playlist_dir, exist_ok=True)
        track1 = os.path.join(playlist_dir, "01. Artist - Song One.flac")
        track2 = os.path.join(playlist_dir, "02. Artist - Song Two.flac")
        for t in [track1, track2]:
            with open(t, "wb") as f:
                f.write(b"RIFF dummy audio content")

        m3u8_path = generate_m3u8_file(playlist_dir, "Chill Mix")
        self.assertTrue(os.path.isfile(m3u8_path))
        with open(m3u8_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertTrue(content.startswith("#EXTM3U"))
        self.assertIn("01. Artist - Song One.flac", content)
        self.assertIn("02. Artist - Song Two.flac", content)

    def test_wal_checkpoint(self):
        # WAL checkpointing should execute without raising
        self.archive.checkpoint_wal()

    def test_sync_saved_playlist(self):
        # Save initial playlist with 3 tracks
        t1 = TrackMetadata(id="t1", title="Song 1", artists=["Artist A"], album="Album A", duration_ms=180000)
        t2 = TrackMetadata(id="t2", title="Song 2", artists=["Artist A"], album="Album A", duration_ms=200000)
        t3 = TrackMetadata(id="t3", title="Song 3", artists=["Artist B"], album="Album B", duration_ms=210000)

        self.archive.save_playlist(
            name="My Playlist",
            spotify_url="https://open.spotify.com/playlist/test1",
            cover_url="https://cover.jpg",
            tracks=[t1, t2, t3],
            playlist_id="pl_1"
        )

        # Mark t1 as downloaded
        self.archive.mark_saved_track_downloaded("t1", "/music/t1.flac", "FLAC 16", "Musilon")

        # Now sync with updated tracks: t2 was removed, t4 was added
        t4 = TrackMetadata(id="t4", title="Song 4", artists=["Artist C"], album="Album C", duration_ms=240000)
        updated_tracks = [t1, t3, t4]

        sync_summary = self.archive.sync_saved_playlist("pl_1", updated_tracks)
        self.assertEqual(sync_summary["added"], 1)
        self.assertEqual(sync_summary["removed"], 1)
        self.assertEqual(sync_summary["total"], 3)

        # Verify t1 is still marked downloaded
        all_tracks = self.archive.get_saved_playlist_tracks("pl_1")
        track_map = {t["spotify_id"]: t for t in all_tracks}
        self.assertIn("t1", track_map)
        self.assertEqual(track_map["t1"]["status"], "downloaded")
        from core.archive import normalize_path
        self.assertEqual(track_map["t1"]["file_path"], normalize_path("/music/t1.flac"))
        self.assertIn("t4", track_map)
        self.assertEqual(track_map["t4"]["status"], "pending")
        self.assertNotIn("t2", track_map)

    def test_direct_youtube_id_resolution(self):
        engine = YtdlpEngine()
        yt_track = TrackMetadata(
            id="yt_dQw4w9WgXcQ",
            title="Never Gonna Give You Up",
            artists=["Rick Astley"],
            album="Singles",
            duration_ms=213000
        )
        src = engine.resolve_track(yt_track)
        self.assertIsNotNone(src)
        self.assertEqual(src.video_id, "dQw4w9WgXcQ")
        self.assertEqual(src.url, "https://www.youtube.com/watch?v=dQw4w9WgXcQ")


if __name__ == "__main__":
    unittest.main()
