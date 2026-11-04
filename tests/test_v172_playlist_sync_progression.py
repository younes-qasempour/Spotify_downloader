import unittest
from unittest.mock import MagicMock

from core.spotify_client import SpotifyClient
from gui.web_api import WebBackendState, FlacifyWebRequestHandler


class TestV172PlaylistSyncProgression(unittest.TestCase):
    def test_spotify_client_playlist_progress_callback(self):
        sp = SpotifyClient(client_id="dummy_id", client_secret="dummy_secret")
        mock_sp = MagicMock()
        sp._sp = mock_sp

        mock_sp.playlist.return_value = {
            "name": "Heavy Metal Gym",
            "images": [{"url": "https://img.test/cover.jpg"}],
            "owner": {"display_name": "MetalHead"},
        }
        mock_sp.playlist_items.side_effect = [
            {
                "total": 150,
                "items": [
                    {
                        "track": {
                            "id": f"t_{i}",
                            "name": f"Track {i}",
                            "artists": [{"name": "Slayer"}],
                            "album": {"name": "Reign in Blood", "release_date": "1986", "images": []},
                            "duration_ms": 180000,
                        }
                    }
                    for i in range(100)
                ],
                "next": "https://api.spotify.com/v1/playlists/123/tracks?offset=100",
            },
            {
                "total": 150,
                "items": [
                    {
                        "track": {
                            "id": f"t_{i}",
                            "name": f"Track {i}",
                            "artists": [{"name": "Slayer"}],
                            "album": {"name": "Reign in Blood", "release_date": "1986", "images": []},
                            "duration_ms": 180000,
                        }
                    }
                    for i in range(100, 150)
                ],
                "next": None,
            },
        ]

        progress_calls = []

        def on_prog(cur, tot=0):
            progress_calls.append((cur, tot))

        tracks = sp._resolve_with_api("playlist", "test_pl_id", progress_callback=on_prog)

        self.assertEqual(len(tracks), 150)
        # Verify that initial 0/150 was reported, followed by 100/150 and 150/150
        self.assertIn((0, 150), progress_calls)
        self.assertIn((100, 150), progress_calls)
        self.assertIn((150, 150), progress_calls)

    def test_spotify_client_collection_progress_callback(self):
        sp = SpotifyClient(client_id="dummy_id", client_secret="dummy_secret")
        mock_sp = MagicMock()
        sp._sp = mock_sp

        mock_sp.current_user_saved_tracks.side_effect = [
            {
                "total": 100,
                "items": [
                    {
                        "track": {
                            "id": f"t_{i}",
                            "name": f"Liked Track {i}",
                            "artists": [{"name": "Iron Maiden"}],
                            "album": {"name": "Powerslave", "release_date": "1984", "images": []},
                            "duration_ms": 200000,
                        }
                    }
                    for i in range(50)
                ],
                "next": "https://api.spotify.com/v1/me/tracks?offset=50",
            },
            {
                "total": 100,
                "items": [
                    {
                        "track": {
                            "id": f"t_{i}",
                            "name": f"Liked Track {i}",
                            "artists": [{"name": "Iron Maiden"}],
                            "album": {"name": "Powerslave", "release_date": "1984", "images": []},
                            "duration_ms": 200000,
                        }
                    }
                    for i in range(50, 100)
                ],
                "next": None,
            },
        ]

        progress_calls = []

        def on_prog(cur, tot=0):
            progress_calls.append((cur, tot))

        tracks = sp._resolve_with_api("collection", "me", progress_callback=on_prog)

        self.assertEqual(len(tracks), 100)
        self.assertIn((0, 100), progress_calls)
        self.assertIn((50, 100), progress_calls)
        self.assertIn((100, 100), progress_calls)

    def test_web_state_resolving_fields(self):
        state = WebBackendState(queue_manager=MagicMock(), archive_manager=MagicMock())
        self.assertEqual(state.resolving_current, 0)
        self.assertEqual(state.resolving_total, 0)
        self.assertEqual(state.resolving_percent, 0.0)
        self.assertEqual(state.resolving_playlist_id, "")

        state.resolving_current = 2450
        state.resolving_total = 5553
        state.resolving_percent = 44.1
        state.resolving_playlist_id = "liked_songs_pl"

        self.assertEqual(state.resolving_current, 2450)
        self.assertEqual(state.resolving_total, 5553)
        self.assertEqual(state.resolving_percent, 44.1)
        self.assertEqual(state.resolving_playlist_id, "liked_songs_pl")

    def test_web_api_state_endpoint_includes_progression(self):
        state = WebBackendState(queue_manager=MagicMock(), archive_manager=MagicMock())
        state.is_resolving = True
        state.resolving_message = "Syncing 'Liked Songs': 2,450 / 5,553 tracks (44.1%)"
        state.resolving_current = 2450
        state.resolving_total = 5553
        state.resolving_percent = 44.1
        state.resolving_playlist_id = "pl_liked"

        handler = FlacifyWebRequestHandler.__new__(FlacifyWebRequestHandler)
        handler.state = state

        sent_json = None

        def mock_send_json(data, status=200):
            nonlocal sent_json
            sent_json = data

        handler._send_json = mock_send_json
        state.qm.get_items.return_value = []
        state.archive.get_watched_playlists.return_value = []

        handler._handle_get_state()

        self.assertIsNotNone(sent_json)
        self.assertTrue(sent_json["ok"])
        self.assertTrue(sent_json["is_resolving"])
        self.assertEqual(sent_json["resolving_current"], 2450)
        self.assertEqual(sent_json["resolving_total"], 5553)
        self.assertEqual(sent_json["resolving_percent"], 44.1)
        self.assertEqual(sent_json["resolving_playlist_id"], "pl_liked")
        self.assertIn("44.1%", sent_json["resolving_message"])


if __name__ == "__main__":
    unittest.main()
