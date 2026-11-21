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
from core.lyrics import LyricsData
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


class TestBackendLibraryMediaLyrics(unittest.TestCase):
    def setUp(self):
        self._prev_archive_instance = ArchiveManager._instance
        ArchiveManager._instance = None
        self.tmp_dir = tempfile.mkdtemp(prefix="flacify_lib_media_test_")
        self.db_path = os.path.join(self.tmp_dir, "test_archive.db")
        self.archive = ArchiveManager(db_path=self.db_path)

        self.fake_config = FakeConfig()
        self.fake_config.set("download.output_dir", self.tmp_dir)
        self.mock_lyrics = MagicMock()
        self.mock_tagger = MagicMock()
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
            lyrics_engine=self.mock_lyrics,
            tagger=self.mock_tagger,
            audio_engine=self.mock_audio_engine,
            queue_manager=self.qm,
            spotify_client=MagicMock(),
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

    def _valid_flac_bytes(self, body: bytes | None = None) -> bytes:
        hdr = (
            b"fLaC\x80\x00\x00\x22"
            + b"\x10\x00\x10\x00\x00\x00\x00\x00\x00\x00\x0a\xc4\x42\xf0\x00\x00\x00\x00"
            + b"\x00" * 16
        )
        if body is None:
            return hdr + b"\x00" * (160 * 1024 - len(hdr))
        return hdr + body

    def _create_dummy_audio(self, rel_path: str, data: bytes | None = None) -> str:
        full_path = os.path.join(self.tmp_dir, rel_path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "wb") as fh:
            fh.write(self._valid_flac_bytes() if data is None else data)
        return full_path

    def test_library_stats_tracks_collections_filter_sort_and_rename(self):
        fp1 = self._create_dummy_audio(os.path.join("Roadtrip", "Zebra.flac"))
        fp2 = self._create_dummy_audio(os.path.join("Roadtrip", "Alpha.flac"))
        fp3 = self._create_dummy_audio(os.path.join("Discovery", "Digital Love.flac"))

        t1 = TrackMetadata(
            id="lib_1",
            title="Zebra",
            artists=["Artist B"],
            album="Mix",
            duration_ms=150000,
            track_number=2,
            collection_type="playlist",
            collection_name="Roadtrip",
            genres=["Indie"],
        )
        t2 = TrackMetadata(
            id="lib_2",
            title="Alpha",
            artists=["Artist A"],
            album="Mix",
            duration_ms=300000,
            track_number=1,
            collection_type="playlist",
            collection_name="Roadtrip",
            genres=["Electronic"],
        )
        t3 = TrackMetadata(
            id="lib_3",
            title="Digital Love",
            artists=["Daft Punk"],
            album="Discovery",
            duration_ms=280000,
            track_number=3,
            collection_type="album",
            collection_name="Discovery",
            genres=["French House"],
        )

        self.archive.add_track(t1, fp1, "16-BIT FLAC", "Musilon", genre="Indie")
        self.archive.add_track(t2, fp2, "16-BIT FLAC", "Musilon", genre="Electronic")
        self.archive.add_track(t3, fp3, "24-BIT FLAC", "MeloBot", genre="French House")

        with TestClient(self.app) as client:
            stats_resp = client.get("/api/library/stats")
            self.assertEqual(stats_resp.status_code, 200)
            stats = stats_resp.json()
            self.assertEqual(stats["total_tracks"], 3)
            self.assertEqual(stats["total_playlists"], 1)
            self.assertEqual(stats["total_albums"], 1)

            # Sort by title
            tracks_resp = client.get("/api/library/tracks", params={"sort": "title"})
            self.assertEqual(tracks_resp.status_code, 200)
            tdata = tracks_resp.json()
            self.assertEqual(
                [t["title"] for t in tdata["tracks"]],
                ["Alpha", "Digital Love", "Zebra"],
            )
            self.assertEqual(tdata["tracks"][0]["audio_url"], "/api/media/audio/lib_2")

            # Filter by genre & sort duration_desc
            filt_resp = client.get(
                "/api/library/tracks",
                params={"genre": "Electronic", "sort": "duration_desc"},
            )
            self.assertEqual([t["spotify_id"] for t in filt_resp.json()["tracks"]], ["lib_2"])

            # Playlists and Albums
            pl_resp = client.get("/api/library/playlists")
            self.assertEqual(pl_resp.status_code, 200)
            self.assertEqual(len(pl_resp.json()["playlists"]), 1)
            self.assertEqual(pl_resp.json()["playlists"][0]["name"], "Roadtrip")
            self.assertIn("/api/media/cover/collection?name=Roadtrip", pl_resp.json()["playlists"][0]["cover_url_local"])

            alb_resp = client.get("/api/library/albums")
            self.assertEqual(alb_resp.status_code, 200)
            self.assertEqual(len(alb_resp.json()["albums"]), 1)
            self.assertEqual(alb_resp.json()["albums"][0]["name"], "Discovery")

            # Collection tracks
            coll_resp = client.get(
                "/api/library/collections/tracks",
                params={"name": "Roadtrip", "type": "playlist", "sort": "track_number"},
            )
            self.assertEqual(coll_resp.status_code, 200)
            self.assertEqual(
                [t["spotify_id"] for t in coll_resp.json()["tracks"]], ["lib_2", "lib_1"]
            )

            # Rename collection
            ren_resp = client.patch(
                "/api/library/collections/rename",
                json={
                    "old_name": "Roadtrip",
                    "new_name": "Highway Mix",
                    "collection_type": "playlist",
                },
            )
            self.assertEqual(ren_resp.status_code, 200)
            self.assertTrue(ren_resp.json()["renamed"])
            pl_after = client.get("/api/library/playlists").json()
            self.assertEqual(pl_after["playlists"][0]["name"], "Highway Mix")

            # Rescan
            rescan_resp = client.post("/api/library/rescan")
            self.assertEqual(rescan_resp.status_code, 200)
            self.assertEqual(rescan_resp.json()["directory"], self.tmp_dir)

    def test_library_track_detail_delete_and_redownload(self):
        fp1 = self._create_dummy_audio("TrackKeep.flac")
        fp2 = self._create_dummy_audio("TrackDrop.flac")
        fp3 = self._create_dummy_audio("TrackRedl.flac")

        t1 = TrackMetadata(id="d1", title="Keep File", artists=["Artist"], album="Alb")
        t2 = TrackMetadata(id="d2", title="Drop File", artists=["Artist"], album="Alb")
        t3 = TrackMetadata(id="d3", title="Redl File", artists=["Artist"], album="Alb")

        self.archive.add_track(t1, fp1, "16-BIT FLAC", "Musilon")
        self.archive.add_track(t2, fp2, "16-BIT FLAC", "Musilon")
        self.archive.add_track(t3, fp3, "16-BIT FLAC", "Musilon")

        with patch.object(DownloadQueueManager, "_worker_loop", lambda self: None):
            with TestClient(self.app) as client:
                det = client.get("/api/library/tracks/d1")
                self.assertEqual(det.status_code, 200)
                self.assertTrue(det.json()["track"]["file_exists"])

                # Delete archive entry only
                del_keep = client.delete("/api/library/tracks/d1", params={"delete_file": "false"})
                self.assertEqual(del_keep.status_code, 200)
                self.assertFalse(del_keep.json()["file_removed"])
                self.assertTrue(os.path.exists(fp1))
                self.assertEqual(client.get("/api/library/tracks/d1").status_code, 404)

                # Delete archive entry + file on disk
                del_drop = client.delete("/api/library/tracks/d2", params={"delete_file": "true"})
                self.assertEqual(del_drop.status_code, 200)
                self.assertTrue(del_drop.json()["file_removed"])
                self.assertFalse(os.path.exists(fp2))

                # Redownload track
                redl = client.post(
                    "/api/library/tracks/d3/redownload",
                    json={"preferred_engine": "melobot"},
                )
                self.assertEqual(redl.status_code, 200)
                self.assertTrue(redl.json()["queued"])
                self.assertFalse(os.path.exists(fp3))
                self.assertIn("d3", self.qm._items)
                self.assertEqual(self.qm._items["d3"].preferred_engine, "melobot")

    def test_media_audio_streaming_full_and_byte_ranges(self):
        pattern = bytes((i % 251) for i in range(160 * 1024))
        payload = self._valid_flac_bytes(body=pattern)
        total_len = len(payload)
        fp = self._create_dummy_audio("stream_test.flac", data=payload)
        t = TrackMetadata(id="m1", title="Stream Song", artists=["Artist"], album="Alb")
        self.archive.add_track(t, fp, "16-BIT FLAC", "Musilon")

        with TestClient(self.app) as client:
            head_resp = client.head("/api/media/audio/m1")
            self.assertEqual(head_resp.status_code, 200)
            self.assertEqual(head_resp.headers["accept-ranges"], "bytes")
            self.assertEqual(head_resp.headers["content-length"], str(total_len))
            self.assertEqual(head_resp.headers["content-type"], "audio/flac")

            full_resp = client.get("/api/media/audio/m1")
            self.assertEqual(full_resp.status_code, 200)
            self.assertEqual(full_resp.content, payload)

            r1 = client.get("/api/media/audio/m1", headers={"Range": "bytes=0-9"})
            self.assertEqual(r1.status_code, 206)
            self.assertEqual(r1.content, payload[0:10])
            self.assertEqual(r1.headers["content-range"], f"bytes 0-9/{total_len}")

            tail_start = total_len - 10
            r2 = client.get("/api/media/audio/m1", headers={"Range": f"bytes={tail_start}-"})
            self.assertEqual(r2.status_code, 206)
            self.assertEqual(r2.content, payload[tail_start:])
            self.assertEqual(
                r2.headers["content-range"], f"bytes {tail_start}-{total_len - 1}/{total_len}"
            )

            r3 = client.get("/api/media/audio/m1", headers={"Range": "bytes=-5"})
            self.assertEqual(r3.status_code, 206)
            self.assertEqual(r3.content, payload[-5:])
            self.assertEqual(
                r3.headers["content-range"], f"bytes {total_len - 5}-{total_len - 1}/{total_len}"
            )

            r_oob = client.get("/api/media/audio/m1", headers={"Range": "bytes=999999-1000010"})
            self.assertEqual(r_oob.status_code, 416)
            self.assertEqual(r_oob.headers["content-range"], f"bytes */{total_len}")

            self.assertEqual(client.get("/api/media/audio/missing").status_code, 404)

    def test_media_cover_embedded_folder_and_collection(self):
        album_dir = os.path.join(self.tmp_dir, "AlbumFolder")
        fp = self._create_dummy_audio(os.path.join("AlbumFolder", "song.flac"))
        folder_cover = os.path.join(album_dir, "cover.jpg")
        with open(folder_cover, "wb") as fh:
            fh.write(b"\xff\xd8\xff\xe0fake_jpeg_data")

        coll_cover = os.path.join(self.tmp_dir, "playlist_cover.jpg")
        with open(coll_cover, "wb") as fh:
            fh.write(b"\xff\xd8\xff\xe0coll_jpeg_data")

        t = TrackMetadata(
            id="cov1",
            title="Cover Song",
            artists=["Artist"],
            album="AlbumFolder",
            collection_type="album",
            collection_name="AlbumFolder",
        )
        self.archive.add_track(t, fp, "16-BIT FLAC", "Musilon")
        self.archive.save_playlist("Cover Mix", "https://open.spotify.com/playlist/plcov", "", [t], playlist_id="plcov")

        with TestClient(self.app) as client:
            # 1. Embedded cover art
            with patch("backend.routes.media.extract_embedded_cover", return_value=b"\x89PNG\r\n\x1a\nfake_png"):
                resp_emb = client.get("/api/media/cover/track/cov1")
                self.assertEqual(resp_emb.status_code, 200)
                self.assertEqual(resp_emb.headers["content-type"], "image/png")
                self.assertTrue(resp_emb.content.startswith(b"\x89PNG"))

            # 2. Fallback to folder cover.jpg
            with patch("backend.routes.media.extract_embedded_cover", return_value=None), patch(
                "backend.routes.media.resolve_collection_cover", return_value=""
            ):
                resp_fld = client.get("/api/media/cover/track/cov1")
                self.assertEqual(resp_fld.status_code, 200)
                self.assertEqual(resp_fld.content, b"\xff\xd8\xff\xe0fake_jpeg_data")

            # 3. Collection cover lookup
            with patch("backend.routes.media.resolve_collection_cover", return_value=coll_cover):
                resp_coll = client.get("/api/media/cover/collection", params={"name": "Cover Mix"})
                self.assertEqual(resp_coll.status_code, 200)
                self.assertEqual(resp_coll.content, b"\xff\xd8\xff\xe0coll_jpeg_data")

            # 4. Missing collection cover
            with patch("backend.routes.media.resolve_collection_cover", return_value=""):
                self.assertEqual(
                    client.get("/api/media/cover/collection", params={"name": "Nope"}).status_code,
                    404,
                )

    def test_lyrics_load_parse_translate_fetch_and_export_lrc(self):
        fp = self._create_dummy_audio("Karaoke Track.flac")
        lrc_fp = os.path.splitext(fp)[0] + ".lrc"
        with open(lrc_fp, "w", encoding="utf-8") as fh:
            fh.write("[00:01.00] Hello world\n[00:05.50] Second line\n")

        t = TrackMetadata(
            id="lyr1",
            title="Karaoke Track",
            artists=["Artist"],
            album="Album",
            duration_ms=180000,
        )
        self.archive.add_track(t, fp, "16-BIT FLAC", "Musilon")
        self.mock_lyrics.translate_lyrics.return_value = ["سلام دنیا", "خط دوم"]

        with TestClient(self.app) as client:
            # 1. Load & parse synced LRC + inline translation
            get_resp = client.get("/api/lyrics/lyr1", params={"lang": "fa"})
            self.assertEqual(get_resp.status_code, 200)
            ldata = get_resp.json()
            self.assertTrue(ldata["has_lyrics"])
            self.assertTrue(ldata["is_synced"])
            self.assertEqual(ldata["source"], "lrc_file")
            self.assertEqual(len(ldata["lines"]), 2)
            self.assertEqual(ldata["lines"][0]["timestamp_ms"], 1000)
            self.assertEqual(ldata["lines"][0]["translated"], "سلام دنیا")
            self.assertEqual(ldata["lines"][1]["timestamp_ms"], 5500)
            self.assertEqual(ldata["lines"][1]["translated"], "خط دوم")

            # 2. Translate endpoint persists preference
            tr_resp = client.post(
                "/api/lyrics/translate",
                json={"lines": ["Hello world", "Second line"], "target_lang": "fa"},
            )
            self.assertEqual(tr_resp.status_code, 200)
            self.assertEqual(tr_resp.json()["translated_lines"], ["سلام دنیا", "خط دوم"])
            self.assertEqual(self.fake_config.get("ui.lyrics_translation_lang"), "fa")

            # 3. Export bilingual LRC file
            custom_lrc = os.path.join(self.tmp_dir, "exported.lrc")
            exp_resp = client.post(
                "/api/lyrics/lyr1/export-lrc",
                json={
                    "include_translation": True,
                    "target_lang": "fa",
                    "output_path": custom_lrc,
                    "write_to_disk": True,
                },
            )
            self.assertEqual(exp_resp.status_code, 200)
            self.assertEqual(exp_resp.json()["saved_path"], custom_lrc)
            self.assertTrue(os.path.isfile(custom_lrc))
            with open(custom_lrc, "r", encoding="utf-8") as fh:
                content = fh.read()
            self.assertIn("[00:01.00] Hello world / سلام دنیا", content)

            # 4. Fetch lyrics online from LRCLIB & embed
            self.mock_lyrics.fetch_lyrics.return_value = LyricsData(
                synced_lyrics="[00:02.00] Fetched line\n",
                plain_lyrics="Fetched line",
                instrumental=False,
            )
            self.mock_lyrics.save_lrc_file.return_value = lrc_fp
            fetch_resp = client.post("/api/lyrics/lyr1/fetch")
            self.assertEqual(fetch_resp.status_code, 200)
            fdata = fetch_resp.json()
            self.assertTrue(fdata["found"])
            self.assertTrue(fdata["is_synced"])
            self.assertTrue(fdata["lrc_saved"])
            self.mock_tagger.tag_file.assert_called_once()

    def test_deduplicated_saved_playlist_track_resolves_audio_cover_and_lyrics(self):
        fp = self._create_dummy_audio("Dream On.flac", data=self._valid_flac_bytes())
        lrc_fp = os.path.splitext(fp)[0] + ".lrc"
        with open(lrc_fp, "w", encoding="utf-8") as fh:
            fh.write("[00:10.00] Dream on\n")

        master = TrackMetadata(
            id="master_id_1",
            title="Dream On",
            artists=["Aerosmith"],
            album="Aerosmith",
            isrc="USSM10011897",
            cover_url="https://i.scdn.co/image/master_cover",
        )
        self.archive.add_track(master, fp, "16-BIT FLAC", "Musilon")

        alt_track = TrackMetadata(
            id="alt_playlist_id_1",
            title="Dream On",
            artists=["Aerosmith"],
            album="Aerosmith",
            isrc="USSM10011897",
            cover_url="https://i.scdn.co/image/alt_cover",
        )
        self.archive.save_playlist(
            "Rock",
            "https://open.spotify.com/playlist/plrock",
            "",
            [alt_track],
            playlist_id="plrock",
        )
        self.archive.mark_saved_track_downloaded(
            "alt_playlist_id_1",
            fp,
            quality_badge="16-BIT FLAC",
            source_type="Musilon",
        )

        with TestClient(self.app) as client:
            audio_head = client.head("/api/media/audio/alt_playlist_id_1")
            self.assertEqual(audio_head.status_code, 200)

            audio_get = client.get("/api/media/audio/alt_playlist_id_1")
            self.assertEqual(audio_get.status_code, 200)
            self.assertTrue(audio_get.content.startswith(b"fLaC"))

            with patch(
                "backend.routes.media.extract_embedded_cover",
                return_value=b"\x89PNG\r\n\x1a\nfake_png",
            ):
                cov_emb = client.get("/api/media/cover/track/alt_playlist_id_1")
                self.assertEqual(cov_emb.status_code, 200)
                self.assertEqual(cov_emb.headers["content-type"], "image/png")

            with patch("backend.routes.media.extract_embedded_cover", return_value=None), patch(
                "backend.routes.media.resolve_collection_cover", return_value=""
            ):
                cov_redir = client.get(
                    "/api/media/cover/track/alt_playlist_id_1",
                    follow_redirects=False,
                )
                self.assertEqual(cov_redir.status_code, 302)
                self.assertEqual(cov_redir.headers["location"], "https://i.scdn.co/image/alt_cover")

            lyr_resp = client.get("/api/lyrics/alt_playlist_id_1")
            self.assertEqual(lyr_resp.status_code, 200)
            self.assertTrue(lyr_resp.json()["has_lyrics"])
            self.assertEqual(lyr_resp.json()["lines"][0]["text"], "Dream on")

    def test_duplicate_file_path_rows_deduplicated_in_library_and_stats(self):
        fp = self._create_dummy_audio("Arctic Monkeys - 505.flac")
        disk_size = os.path.getsize(fp)

        # Row 1: Musilon in Creep Radio (generic album)
        t1 = TrackMetadata(
            id="58ge6dfP91o9oXMzq3XkIS",
            title="505",
            artists=["Arctic Monkeys"],
            album="Spotify Playlist",
            duration_ms=253586,
            collection_type="playlist",
            collection_name="Creep Radio",
            genres=["Alternative Rock"],
        )
        # Row 2: Local Archive in another playlist collection with specific album
        t2 = TrackMetadata(
            id="0BxE4FqsDD1Ot4YuBXwAPp",
            title="505",
            artists=["Arctic Monkeys"],
            album="505",
            duration_ms=253586,
            collection_type="playlist",
            collection_name="Calm Relaxing Night",
            genres=["Alternative Rock"],
        )
        # Row 3: Synthetic local_* scan row with empty genre & 0 duration in same Creep Radio collection
        t3 = TrackMetadata(
            id="local_69a213511a74eba5",
            title="505",
            artists=["Arctic Monkeys"],
            album="505",
            duration_ms=0,
            collection_type="playlist",
            collection_name="Creep Radio",
            genres=[],
        )

        # Insert synthetic first to simulate rescan before or alongside real rows, and verify dedup
        self.archive.add_track(t3, fp, "FLAC 16", "Local File")
        self.archive.add_track(t2, fp, "Musilon FLAC 16", "Local Archive", genre="Alternative Rock")
        self.archive.add_track(t1, fp, "Musilon FLAC 16", "Musilon", genre="Alternative Rock")

        with TestClient(self.app) as client:
            # All Songs must collapse sibling rows sharing fp to 1 track with richest metadata
            tracks_resp = client.get("/api/library/tracks", params={"search": "505"})
            self.assertEqual(tracks_resp.status_code, 200)
            tracks = tracks_resp.json()["tracks"]
            self.assertEqual(len(tracks), 1)
            self.assertEqual(tracks[0]["spotify_id"], "58ge6dfP91o9oXMzq3XkIS")
            self.assertEqual(tracks[0]["duration_ms"], 253586)
            self.assertEqual(tracks[0]["album"], "505")
            self.assertEqual(tracks[0]["quality_badge"], "Musilon FLAC 16")

            # Library stats must count unique physical file size once, not 2x/3x
            stats_resp = client.get("/api/library/stats")
            self.assertEqual(stats_resp.status_code, 200)
            self.assertEqual(stats_resp.json()["total_tracks"], 1)
            self.assertEqual(stats_resp.json()["total_bytes"], disk_size)

            # Virtual playlists remain intact with deduplicated counts
            pl_resp = client.get("/api/library/playlists")
            self.assertEqual(pl_resp.status_code, 200)
            pl_names = {p["name"]: p["track_count"] for p in pl_resp.json()["playlists"]}
            self.assertEqual(pl_names.get("Creep Radio"), 1)
            self.assertEqual(pl_names.get("Calm Relaxing Night"), 1)

            # Deleting with delete_file=true must clean all sibling rows referencing that file
            del_resp = client.delete(
                "/api/library/tracks/58ge6dfP91o9oXMzq3XkIS",
                params={"delete_file": "true"},
            )
            self.assertEqual(del_resp.status_code, 200)
            self.assertTrue(del_resp.json()["file_removed"])
            self.assertEqual(client.get("/api/library/stats").json()["total_tracks"], 0)

    def test_consolidate_and_organize_library_moves_stray_files_and_cleans_db(self):
        # 1. File in a subfolder inside output_dir
        sub_fp = self._create_dummy_audio(os.path.join("SubPlaylist", "Sub Track.flac"))
        # 2. File in an external stray temp directory outside output_dir
        stray_dir = tempfile.mkdtemp(prefix="flacify_stray_src_")
        try:
            stray_fp = os.path.join(stray_dir, "Stray Song.flac")
            with open(stray_fp, "wb") as fh:
                fh.write(self._valid_flac_bytes())
            # 3. File already in root output_dir with duplicate rows (real + local_ + same collection)
            root_fp = self._create_dummy_audio("Root Song.flac")

            t_sub = TrackMetadata(
                id="sub_id_1",
                title="Sub Track",
                artists=["Sub Artist"],
                album="Sub Alb",
                duration_ms=190000,
                collection_type="playlist",
                collection_name="SubPlaylist",
            )
            t_stray = TrackMetadata(
                id="stray_id_1",
                title="Stray Song",
                artists=["Stray Artist"],
                album="Stray Alb",
                duration_ms=210000,
                collection_type="playlist",
                collection_name="Mixed",
            )
            t_root_main = TrackMetadata(
                id="root_id_1",
                title="Root Song",
                artists=["Root Artist"],
                album="Spotify Playlist",
                duration_ms=225000,
                collection_type="playlist",
                collection_name="Mixed",
                genres=["Indie"],
            )
            t_root_dup = TrackMetadata(
                id="root_id_dup",
                title="Root Song",
                artists=["Root Artist"],
                album="Real Album",
                duration_ms=225000,
                collection_type="playlist",
                collection_name="Mixed",
            )
            t_missing = TrackMetadata(
                id="missing_id_1",
                title="Gone Track",
                artists=["Ghost"],
                album="Ghost Alb",
            )

            self.archive.add_track(t_sub, sub_fp, "FLAC 16", "Musilon")
            self.archive.add_track(t_stray, stray_fp, "FLAC 16", "Musilon")
            self.archive.add_track(t_root_main, root_fp, "FLAC 16", "Musilon", genre="Indie")
            # Insert duplicate same-collection row directly via SQL to simulate legacy DB state
            with self.archive.connection() as conn:
                with conn:
                    conn.execute(
                        """
                        INSERT INTO downloaded_tracks
                        (spotify_id, title, artist, album, duration_ms, file_path, file_size, quality_badge, source_type, collection_name, collection_type, genre)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        ("root_id_dup", "Root Song", "Root Artist", "Real Album", 225000, root_fp, 163840, "FLAC 16", "Local Archive", "Mixed", "playlist", ""),
                    )
                    conn.execute(
                        """
                        INSERT INTO downloaded_tracks
                        (spotify_id, title, artist, album, duration_ms, file_path, file_size, quality_badge, source_type, collection_name, collection_type, genre)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        ("local_dead_1", "Do Me Good", "Amy Winehouse", "", 0, os.path.join(self.tmp_dir, "Amy Winehouse - Do Me Good.opus.norm_tmp.opus"), 1024, "YTM Opus", "Local File", "downloads", "track", ""),
                    )

            self.archive.save_playlist(
                "Mixed",
                "https://open.spotify.com/playlist/plmix",
                "",
                [t_stray, t_missing],
                playlist_id="plmix",
            )
            self.archive.mark_saved_track_downloaded("stray_id_1", stray_fp, "FLAC 16", "Musilon")
            self.archive.mark_saved_track_downloaded("missing_id_1", os.path.join(stray_dir, "missing.flac"), "FLAC 16", "Musilon")

            self.fake_config.set("download.save_in_subfolders", True)
            with TestClient(self.app) as client:
                resp = client.post("/api/tools/maintenance/organize", json={"enforce_single_folder": True})
                self.assertEqual(resp.status_code, 200)
                data = resp.json()
                self.assertEqual(data["files_moved"], 2)
                self.assertEqual(data["missing_db_rows_removed"], 1)
                self.assertGreaterEqual(data["duplicate_db_rows_removed"], 1)
                self.assertEqual(data["saved_tracks_reset"], 1)
                self.assertFalse(self.fake_config.get("download.save_in_subfolders"))

                # Every surviving downloaded_tracks file_path is directly inside self.tmp_dir
                with self.archive.connection() as conn:
                    dt_rows = conn.execute("SELECT spotify_id, file_path, album, genre FROM downloaded_tracks").fetchall()
                    self.assertEqual(len(dt_rows), 3)
                    for r in dt_rows:
                        self.assertEqual(
                            os.path.normcase(os.path.dirname(r["file_path"])),
                            os.path.normcase(os.path.normpath(self.tmp_dir)),
                        )
                        self.assertTrue(os.path.isfile(r["file_path"]))
                        if os.path.basename(r["file_path"]) == "Root Song.flac":
                            self.assertEqual(r["album"], "Real Album")
                            self.assertEqual(r["genre"], "Indie")

                    sp_stray = conn.execute(
                        "SELECT status, file_path FROM saved_playlist_tracks WHERE spotify_id = 'stray_id_1'"
                    ).fetchone()
                    self.assertEqual(sp_stray["status"], "downloaded")
                    self.assertEqual(
                        os.path.normcase(sp_stray["file_path"]),
                        os.path.normcase(os.path.normpath(os.path.join(self.tmp_dir, "Stray Song.flac"))),
                    )

                    sp_miss = conn.execute(
                        "SELECT status, file_path FROM saved_playlist_tracks WHERE spotify_id = 'missing_id_1'"
                    ).fetchone()
                    self.assertEqual(sp_miss["status"], "pending")
                    self.assertEqual(sp_miss["file_path"], "")
        finally:
            shutil.rmtree(stray_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
