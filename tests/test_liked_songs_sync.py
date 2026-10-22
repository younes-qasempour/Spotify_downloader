import unittest
from unittest.mock import MagicMock, patch
from core.spotify_client import SpotifyClient, TrackMetadata
from core.archive import ArchiveManager
import tempfile
import os
import shutil


class TestLikedSongsSync(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test_archive.db")
        self.archive = ArchiveManager(db_path=self.db_path)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_parse_collection_urls(self):
        """Verifies SpotifyClient.parse_url correctly identifies Liked Songs collection URLs."""
        test_cases = [
            ("https://open.spotify.com/collection/tracks", ("collection", "tracks")),
            ("https://open.spotify.com/collection/tracks?si=12345", ("collection", "tracks")),
            ("spotify:collection:tracks", ("collection", "tracks")),
            ("spotify:user:user123:collection", ("collection", "tracks")),
            ("spotify:user:user123:collection:tracks", ("collection", "tracks")),
            ("https://open.spotify.com/collection", ("collection", "tracks")),
            ("https://open.spotify.com/playlist/77Se18cY0wrjmYyp2WgHDk", ("playlist", "77Se18cY0wrjmYyp2WgHDk")),
            ("spotify:playlist:77Se18cY0wrjmYyp2WgHDk", ("playlist", "77Se18cY0wrjmYyp2WgHDk")),
        ]
        for url, expected in test_cases:
            with self.subTest(url=url):
                self.assertEqual(SpotifyClient.parse_url(url), expected)

    def test_resolve_collection_with_api(self):
        """Verifies _resolve_with_api paginates current_user_saved_tracks and invokes progress_callback."""
        client = SpotifyClient()
        mock_sp = MagicMock()
        client._sp = mock_sp

        # Mock 2 batches of saved tracks
        batch1 = {
            "total": 3,
            "next": "url_to_page_2",
            "items": [
                {
                    "track": {
                        "id": "trk_1",
                        "name": "死ぬか生きるか",
                        "artists": [{"name": "Yuki Chiba"}],
                        "album": {"name": "Album 1", "release_date": "2024", "images": []},
                        "duration_ms": 165000,
                        "track_number": 1,
                        "disc_number": 1,
                        "external_ids": {"isrc": "JP123"}
                    }
                },
                {
                    "track": {
                        "id": "trk_2",
                        "name": "SPIN",
                        "artists": [{"name": "Kroi"}],
                        "album": {"name": "Album 2", "release_date": "2024", "images": []},
                        "duration_ms": 305000,
                        "track_number": 2,
                        "disc_number": 1,
                        "external_ids": {"isrc": "JP456"}
                    }
                }
            ]
        }
        batch2 = {
            "total": 3,
            "next": None,
            "items": [
                {
                    "track": {
                        "id": "trk_3",
                        "name": "BLUE",
                        "artists": [{"name": "Billie Eilish"}],
                        "album": {"name": "HIT ME HARD AND SOFT", "release_date": "2024", "images": []},
                        "duration_ms": 343000,
                        "track_number": 3,
                        "disc_number": 1,
                        "external_ids": {"isrc": "US789"}
                    }
                }
            ]
        }

        mock_sp.current_user_saved_tracks.side_effect = [batch1, batch2]

        progress_calls = []
        def on_progress(cur, total):
            progress_calls.append((cur, total))

        tracks = client._resolve_with_api("collection", "tracks", progress_callback=on_progress)

        self.assertEqual(len(tracks), 3)
        self.assertEqual(tracks[0].title, "死ぬか生きるか")
        self.assertEqual(tracks[0].primary_artist, "Yuki Chiba")
        self.assertEqual(tracks[0].collection_name, "Liked Songs")
        self.assertEqual(tracks[1].title, "SPIN")
        self.assertEqual(tracks[1].primary_artist, "Kroi")
        self.assertEqual(tracks[2].title, "BLUE")

        # Verify progress callback was invoked
        self.assertTrue(len(progress_calls) >= 2)
        self.assertEqual(progress_calls[-1], (3, 3))

    def test_sync_liked_songs_delta(self):
        """Verifies syncing new liked tracks into an existing playlist correctly detects delta tracks."""
        initial_tracks = [
            TrackMetadata(
                id="trk_3",
                title="BLUE",
                artists=["Billie Eilish"],
                album="HIT ME HARD AND SOFT",
                collection_name="Liked Songs"
            )
        ]
        save_res = self.archive.save_playlist(
            name="Liked Songs",
            spotify_url="https://open.spotify.com/collection/tracks",
            cover_url="",
            tracks=initial_tracks,
            playlist_id="collection_tracks"
        )
        self.assertEqual(save_res["total_tracks"], 1)

        # Now simulate 2 new songs added in Spotify Liked Songs
        updated_tracks = [
            TrackMetadata(
                id="trk_1",
                title="死ぬか生きるか",
                artists=["Yuki Chiba"],
                album="Single",
                collection_name="Liked Songs"
            ),
            TrackMetadata(
                id="trk_2",
                title="SPIN",
                artists=["Kroi"],
                album="Single",
                collection_name="Liked Songs"
            ),
            TrackMetadata(
                id="trk_3",
                title="BLUE",
                artists=["Billie Eilish"],
                album="HIT ME HARD AND SOFT",
                collection_name="Liked Songs"
            )
        ]

        sync_res = self.archive.sync_saved_playlist("collection_tracks", updated_tracks)
        self.assertEqual(sync_res["added"], 2)
        self.assertEqual(sync_res["removed"], 0)
        self.assertEqual(sync_res["total"], 3)
        delta_ids = [t.id for t in sync_res["delta_tracks"]]
        self.assertIn("trk_1", delta_ids)
        self.assertIn("trk_2", delta_ids)
        self.assertNotIn("trk_3", delta_ids)


if __name__ == "__main__":
    unittest.main()
