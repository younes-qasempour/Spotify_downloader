import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from core.archive import ArchiveManager
from core.config import config
from core.tagger import AudioTagger
from gui.web_api import FlacifyWebRequestHandler, WebBackendState


class DummyWFile:
    def __init__(self):
        self.data = bytearray()

    def write(self, b):
        self.data.extend(b)


class DummyRFile:
    def __init__(self, data=b""):
        self.data = data
        self.pos = 0

    def read(self, n):
        chunk = self.data[self.pos : self.pos + n]
        self.pos += len(chunk)
        return chunk


class TestV170StudioFeatures(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test_archive.db")
        self.archive = ArchiveManager(db_path=self.db_path)

        self.mock_qm = MagicMock()
        self.mock_musilon = MagicMock()
        self.mock_melobot = MagicMock()

        self.state = WebBackendState(
            queue_manager=self.mock_qm,
            archive_manager=self.archive,
            musilon_engine=self.mock_musilon,
            melobot_engine=self.mock_melobot,
        )

        # Patch mutagen.File so dummy files pass integrity checks in find_track
        self.mutagen_patcher = patch("mutagen.File", return_value=MagicMock())
        self.mutagen_patcher.start()

        # Create dummy audio files
        self.test_flac = os.path.join(self.temp_dir, "Track 01.flac")
        with open(self.test_flac, "wb") as f:
            f.write(b"fLaC" + b"\x00" * 200_000)

        self.test_mp3 = os.path.join(self.temp_dir, "Track 02.mp3")
        with open(self.test_mp3, "wb") as f:
            f.write(b"ID3" + b"\x00" * 200_000)

        # Record in archive
        with self.archive.connection() as conn:
            with conn:
                conn.execute("""
                    INSERT OR REPLACE INTO downloaded_tracks (
                        spotify_id, isrc, title, artist, album, duration_ms,
                        track_number, disc_number, file_path, file_size, quality_badge, source_type,
                        collection_name, collection_type, genre
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    "sp_test_01", "ISRC001", "Track 01", "Old Artist", "Old Album", 180000,
                    1, 1, self.test_flac, 200000, "FLAC", "Musilon", "Singles", "track", ""
                ))

    def tearDown(self):
        self.mutagen_patcher.stop()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _call_handler(self, method, path, body=None):
        handler = FlacifyWebRequestHandler.__new__(FlacifyWebRequestHandler)
        handler.state = self.state
        handler.archive = self.archive
        handler.qm = self.mock_qm
        handler.server_state = self.state
        handler.path = path
        handler.command = method
        handler.headers = {}
        handler.wfile = DummyWFile()

        raw_body = b""
        if body is not None:
            raw_body = json.dumps(body).encode("utf-8")
            handler.headers["Content-Length"] = str(len(raw_body))
            handler.headers["Content-Type"] = "application/json"
        handler.rfile = DummyRFile(raw_body)

        resp_status = []
        resp_headers = {}

        def mock_send_response(code):
            resp_status.append(code)

        def mock_send_header(k, v):
            resp_headers[k] = v

        def mock_end_headers():
            pass

        handler.send_response = mock_send_response
        handler.send_header = mock_send_header
        handler.end_headers = mock_end_headers
        handler._send_cors_headers = lambda: None

        if method == "POST":
            handler.do_POST()
        elif method == "GET":
            handler.do_GET()

        status = resp_status[0] if resp_status else 200
        raw_output = bytes(handler.wfile.data)
        data = {}
        if raw_output:
            try:
                data = json.loads(raw_output.decode("utf-8"))
            except Exception:
                data = {"raw": raw_output}
        return status, data

    def test_lyrics_save_and_reparse(self):
        lrc_text = "[00:10.00] First lyric line\n[00:15.50] Second lyric line\n"
        with patch.object(AudioTagger, "embed_lyrics_only", return_value=True):
            status, res = self._call_handler(
                "POST",
                "/api/lyrics/save",
                {"file_path": self.test_flac, "raw_text": lrc_text, "embed": True},
            )

        self.assertEqual(status, 200)
        self.assertTrue(res.get("ok"))
        self.assertTrue(res.get("synced"))
        self.assertEqual(len(res.get("lines")), 2)
        self.assertEqual(res["lines"][0]["text"], "First lyric line")
        self.assertEqual(res["lines"][0]["time_ms"], 10000)

        expected_lrc = os.path.splitext(self.test_flac)[0] + ".lrc"
        self.assertTrue(os.path.isfile(expected_lrc))
        with open(expected_lrc, "r", encoding="utf-8") as f:
            self.assertIn("First lyric line", f.read())

    def test_batch_tag_set_artist(self):
        with patch.object(AudioTagger, "tag_metadata_in_place", return_value=True):
            status, res = self._call_handler(
                "POST",
                "/api/tools/batch_tag",
                {
                    "action": "set_artist",
                    "file_paths": [self.test_flac],
                    "new_artist": "New Super Artist",
                },
            )

        self.assertEqual(status, 200)
        self.assertTrue(res.get("ok"))
        self.assertEqual(res.get("processed"), 1)

        rec = self.archive.find_track(spotify_id="sp_test_01")
        self.assertIsNotNone(rec)
        self.assertEqual(rec["artist"], "New Super Artist")

    def test_batch_tag_replace_artist(self):
        with patch.object(AudioTagger, "tag_metadata_in_place", return_value=True):
            status, res = self._call_handler(
                "POST",
                "/api/tools/batch_tag",
                {
                    "action": "replace_artist",
                    "file_paths": [self.test_flac],
                    "find_str": "Old",
                    "replace_str": "Brand New",
                },
            )

        self.assertEqual(status, 200)
        self.assertTrue(res.get("ok"))
        self.assertEqual(res.get("processed"), 1)

        rec = self.archive.find_track(spotify_id="sp_test_01")
        self.assertIsNotNone(rec)
        self.assertEqual(rec["artist"], "Brand New Artist")

    def test_batch_tag_set_album(self):
        with patch.object(AudioTagger, "tag_metadata_in_place", return_value=True):
            status, res = self._call_handler(
                "POST",
                "/api/tools/batch_tag",
                {
                    "action": "set_album",
                    "file_paths": [self.test_flac],
                    "new_album": "Masterpiece Deluxe",
                    "renumber": True,
                },
            )

        self.assertEqual(status, 200)
        self.assertTrue(res.get("ok"))

        rec = self.archive.find_track(spotify_id="sp_test_01")
        self.assertIsNotNone(rec)
        self.assertEqual(rec["album"], "Masterpiece Deluxe")
        self.assertEqual(rec["track_number"], 1)

    def test_batch_tag_set_genre(self):
        with patch.object(AudioTagger, "tag_genre_only", return_value=True):
            status, res = self._call_handler(
                "POST",
                "/api/tools/batch_tag",
                {
                    "action": "set_genre",
                    "file_paths": [self.test_flac],
                    "genre": "Synthwave; Retrowave",
                },
            )

        self.assertEqual(status, 200)
        self.assertTrue(res.get("ok"))

        rec = self.archive.find_track(spotify_id="sp_test_01")
        self.assertIsNotNone(rec)
        self.assertEqual(rec["genre"], "Synthwave; Retrowave")

    def test_batch_tag_rename_files(self):
        status, res = self._call_handler(
            "POST",
            "/api/tools/batch_tag",
            {
                "action": "rename_files",
                "file_paths": [self.test_flac],
                "template": "{artist} - {title}",
            },
        )
        self.assertEqual(status, 200)
        self.assertTrue(res.get("ok"))
        self.assertEqual(res.get("processed"), 1)

        expected_new = os.path.join(self.temp_dir, "Old Artist - Track 01.flac")
        self.assertTrue(os.path.isfile(expected_new))

        rec = self.archive.find_track(spotify_id="sp_test_01")
        self.assertIsNotNone(rec)
        self.assertEqual(os.path.normpath(rec["file_path"]), os.path.normpath(expected_new))

    def test_batch_tag_fetch_covers(self):
        dummy_jpg = b"\xff\xd8\xff\xe0" + b"\x00" * 2000
        with patch.object(FlacifyWebRequestHandler, "_fetch_online_cover_art", return_value=dummy_jpg), \
             patch.object(AudioTagger, "tag_metadata_in_place", return_value=True):
            status, res = self._call_handler(
                "POST",
                "/api/tools/batch_tag",
                {
                    "action": "fetch_covers",
                    "file_paths": [self.test_flac],
                },
            )
        self.assertEqual(status, 200)
        self.assertTrue(res.get("ok"))
        self.assertEqual(res.get("processed"), 1)
        self.assertTrue(res["results"][0]["success"])

    def test_archive_update_track_record(self):
        new_path = os.path.join(self.temp_dir, "Renamed.flac")
        shutil.copyfile(self.test_flac, new_path)
        ok = self.archive.update_track_record(
            old_file_path=self.test_flac,
            new_file_path=new_path,
            title="Updated Title",
            artist="Updated Artist",
            album="Updated Album",
            genre="Rock",
            track_number=5,
        )
        self.assertTrue(ok)
        rec = self.archive.find_track(spotify_id="sp_test_01")
        self.assertIsNotNone(rec)
        self.assertEqual(rec["title"], "Updated Title")
        self.assertEqual(rec["artist"], "Updated Artist")
        self.assertEqual(rec["album"], "Updated Album")
        self.assertEqual(rec["genre"], "Rock")
        self.assertEqual(rec["track_number"], 5)
        self.assertEqual(os.path.normpath(rec["file_path"]), os.path.normpath(new_path))


if __name__ == "__main__":
    unittest.main()
