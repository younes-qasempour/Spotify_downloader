"""Offline network regressions; no application config, token cache, or services are used."""
import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, mock_open, patch

import requests


TRACK_ID = "A" * 22
ROOT = Path(__file__).resolve().parents[1]


def load_clients():
    # Load private copies so boundary doubles cannot affect other test modules.
    utils = types.ModuleType("core.utils")
    utils.clean_watermarks = lambda text: text
    for name in ("sanitize_filename", "format_bytes", "is_valid_audio_file", "detect_audio_header"):
        setattr(utils, name, Mock(side_effect=AssertionError("Unexpected utility call")))
    paths = types.ModuleType("core.paths")
    paths.get_cache_dir = Mock(side_effect=AssertionError("Real cache access forbidden"))
    paths.get_app_data_dir = Mock(side_effect=AssertionError("Real app-data access forbidden"))

    def load(name):
        spec = importlib.util.spec_from_file_location(f"_audit_network_{name}", ROOT / "core" / f"{name}.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module

    with patch.dict(sys.modules, {"core.utils": utils, "core.paths": paths}):
        spotify = load("spotify_client")
        sys.modules["core.spotify_client"] = spotify
        return spotify, load("musilon"), load("lyrics")


class Response:
    def __init__(self, status=200, data=None, text="", headers=None, chunks=(), forbid_text=False):
        self.status_code = status
        self.data = data
        self._text = text
        self.headers = headers or {}
        self.chunks = chunks
        self.chunks_read = 0
        self.forbid_text = forbid_text
        self.close = Mock()
        self.iter_content = Mock(side_effect=self._iter_content)

    @property
    def text(self):
        if self.forbid_text:
            raise AssertionError("Reading .text buffers the entire streamed error body")
        return self._text

    def json(self):
        if isinstance(self.data, Exception):
            raise self.data
        return self.data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}", response=self)

    def _iter_content(self, chunk_size):
        for chunk in self.chunks:
            self.chunks_read += 1
            if isinstance(chunk, Exception):
                raise chunk
            yield chunk[:chunk_size]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class NetworkTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spotify, cls.musilon, cls.lyrics = load_clients()

    def setUp(self):
        from core.provider_cooldown import provider_cooldowns
        with provider_cooldowns._lock:
            provider_cooldowns._deadlines.clear()
        self.enterContext(patch.object(provider_cooldowns, "wait", return_value=True))
        config_module = types.ModuleType("core.config")
        self.config = Mock()
        self.config.get.side_effect = lambda key, default=None: default
        config_module.config = self.config
        self.enterContext(patch.dict(sys.modules, {"core.config": config_module}))
        self.network = self.enterContext(patch.object(requests.Session, "request", side_effect=AssertionError("Live HTTP forbidden")))
        self.addCleanup(self.network.assert_not_called)
        self.socket = self.enterContext(patch("socket.socket.connect", side_effect=AssertionError("Live sockets forbidden")))
        self.addCleanup(self.socket.assert_not_called)
        self.track = self.spotify.TrackMetadata(TRACK_ID, "Song - Alternate (feat. Guest)", ["Artist"], "Album", duration_ms=180000)

    def spotify_client(self):
        client = self.spotify.SpotifyClient()
        self.addCleanup(client._session.close)
        client._session = Mock()
        return client

    def musilon_engine(self):
        engine = self.musilon.MusilonEngine()
        self.addCleanup(engine.session.close)
        engine.session = Mock()
        engine._rate_limit_shield = Mock()
        return engine

    def lyrics_engine(self):
        return self.lyrics.LyricsEngine(session=Mock())


class TestSpotifyNetworkAudit(NetworkTestCase):
    def test_valid_links_and_private_collection_forms(self):
        for kind in ("track", "album", "playlist", "artist"):
            for link in (f"https://open.spotify.com/{kind}/{TRACK_ID}?si=test", f"spotify:{kind}:{TRACK_ID}"):
                with self.subTest(link=link):
                    self.assertEqual(self.spotify.SpotifyClient.parse_url(link), (kind, TRACK_ID))
        for link in ("https://open.spotify.com/collection/tracks?si=test", "spotify:collection:tracks",
                     "spotify:user:test-user:collection", "spotify:user:test-user:collection:tracks",
                     "https://open.spotify.com/collection", "spotify:collection:liked"):
            with self.subTest(link=link):
                self.assertEqual(self.spotify.SpotifyClient.parse_url(link), ("collection", "tracks"))

    def test_malformed_links_are_not_partial_matches(self):
        invalid = [None, 42, "", "https://example.invalid/spotify:collection:tracks",
                   "prefix spotify:collection:tracks", "https://open.spotify.com.evil/collection/tracks",
                   f"https://open.spoti\nfy.com/track/{TRACK_ID}", f"https://open.spotify.com/tra\tck/{TRACK_ID}"]
        for kind in ("track", "album", "playlist"):
            url = f"https://open.spotify.com/{kind}/{TRACK_ID}"
            invalid.extend([f"prefix {url}", f"https://example.invalid/{url}", url + "extra", url + "/extra",
                            url + "%20extra", url + "-extra", f"spotify:{kind}:{TRACK_ID}:extra",
                            f"spotify:{kind}/{TRACK_ID}", f"https://open.spotify.com/{kind}:{TRACK_ID}",
                            f"spotify:{kind}:short", f"https://open.spotify.com/{kind}/"])
        for link in invalid:
            with self.subTest(link=link):
                self.assertIsNone(self.spotify.SpotifyClient.parse_url(link))

    def test_invalid_resolve_does_not_call_network(self):
        client = self.spotify_client()
        client._sp = Mock()
        with self.assertRaises(ValueError):
            client.resolve("https://open.spotify.com/track/short")
        client._sp.track.assert_not_called()
        client._session.get.assert_not_called()

    def test_private_collection_never_uses_guest(self):
        client = self.spotify_client()
        with self.assertRaisesRegex(RuntimeError, "private collection"):
            client.resolve("spotify:collection:tracks")
        client._session.get.assert_not_called()

    def test_album_without_images(self):
        client = self.spotify_client()
        client._sp = Mock()
        client._sp.album.return_value = {"name": "Album", "images": []}
        client._sp.album_tracks.return_value = {"items": [{"id": TRACK_ID, "name": "Song"}], "next": None}
        tracks = client._resolve_with_api("album", TRACK_ID)
        self.assertEqual(len(tracks), 1)
        self.assertEqual(tracks[0].cover_url, "")

    def test_api_rate_limit_does_not_fall_back_to_guest(self):
        client = self.spotify_client()
        error = RuntimeError("Too many requests")
        error.http_status = 429
        error.headers = {"Retry-After": "3600"}
        client._sp = Mock()
        client._sp.track.side_effect = error
        with self.assertRaises(RuntimeError) as caught:
            client.resolve(f"spotify:track:{TRACK_ID}")
        self.assertIs(caught.exception, error)
        self.assertEqual(client.last_api_error, "rate_limited")
        client._session.get.assert_not_called()

    def test_pagination_does_not_retry_sdk_rate_limit(self):
        client = self.spotify_client()
        for kind, method in (("playlist", "playlist_items"), ("collection", "current_user_saved_tracks")):
            with self.subTest(kind=kind):
                error = RuntimeError("Too many requests")
                error.http_status = 429
                client._sp = Mock()
                client._sp.playlist.return_value = {}
                request = getattr(client._sp, method)
                request.side_effect = error
                with patch.object(self.spotify.time, "sleep") as sleep:
                    with self.assertRaises(RuntimeError):
                        client._resolve_with_api(kind, TRACK_ID)
                self.assertEqual(request.call_count, 1)
                sleep.assert_not_called()

    def test_playlist_metadata_rate_limit_stops_items_request(self):
        client = self.spotify_client()
        client._sp = Mock()
        error = RuntimeError("Too many requests")
        error.http_status = 429
        client._sp.playlist.side_effect = error
        client._sp.playlist_items.return_value = {"items": []}
        with self.assertRaises(RuntimeError):
            client._resolve_with_api("playlist", TRACK_ID)
        client._sp.playlist_items.assert_not_called()

    def test_guest_missing_or_error_entity_is_not_success(self):
        client = self.spotify_client()
        for kind in ("track", "album", "playlist"):
            for entity in ({}, None, {"error": "private or unavailable"}):
                with self.subTest(kind=kind, entity=entity):
                    data = {"props": {"pageProps": {"state": {"data": {"entity": entity}}}}}
                    response = Response(text='<script id="__NEXT_DATA__">' + json.dumps(data) + '</script>')
                    client._session.get.return_value = response
                    with self.assertRaises(self.spotify.MetadataResolutionError):
                        client._resolve_with_guest(kind, TRACK_ID)
                    response.close.assert_called_once()

    def test_guest_multiline_metadata(self):
        client = self.spotify_client()
        data = {"props": {"pageProps": {"state": {"data": {"entity": {"id": TRACK_ID, "title": "Song"}}}}}}
        response = Response(text='<script id="__NEXT_DATA__">\n' + json.dumps(data, indent=2) + '\n</script>')
        client._session.get.return_value = response
        self.assertEqual(client._resolve_with_guest("track", TRACK_ID)[0].title, "Song")
        response.close.assert_called_once()

    def test_guest_http_and_json_errors_are_metadata_errors(self):
        client = self.spotify_client()
        for response in (Response(status=404), Response(status=429), Response(text='<script id="__NEXT_DATA__">invalid</script>')):
            with self.subTest(status=response.status_code):
                client._session.get.return_value = response
                with self.assertRaises(self.spotify.MetadataResolutionError):
                    client._resolve_with_guest("playlist", TRACK_ID)
                response.close.assert_called_once()

    def test_guest_timeout_is_metadata_error(self):
        client = self.spotify_client()
        client._session.get.side_effect = requests.Timeout("offline timeout")
        with self.assertRaises(self.spotify.MetadataResolutionError):
            client._resolve_with_guest("track", TRACK_ID)
        self.assertEqual(client._session.get.call_args.kwargs["timeout"], 12)

    def test_guest_empty_playlist_remains_valid(self):
        client = self.spotify_client()
        data = {"props": {"pageProps": {"state": {"data": {"entity": {"title": "Empty", "trackList": []}}}}}}
        response = Response(text='<script id="__NEXT_DATA__">' + json.dumps(data) + '</script>')
        client._session.get.return_value = response
        self.assertEqual(client._resolve_with_guest("playlist", TRACK_ID), [])
        response.close.assert_called_once()

    def test_cover_response_closed_on_success_and_bad_json(self):
        client = self.spotify_client()
        for data, expected in (({"thumbnail_url": "https://example.invalid/ab67616d00001e02"},
                                "https://example.invalid/ab67616d0000b273"), (ValueError("bad JSON"), "")):
            with self.subTest(data=data):
                response = Response(data=data)
                client._session.get.return_value = response
                self.assertEqual(client._fetch_track_cover(TRACK_ID), expected)
                response.close.assert_called_once()

    def test_oauth_and_client_credentials_have_timeouts(self):
        client = self.spotify_client()
        client.client_id, client.client_secret = "synthetic-id", "synthetic-secret"
        oauth = Mock()
        oauth.return_value.cache_handler.get_cached_token.return_value = None
        credentials = Mock()
        sdk = Mock()
        with patch.object(self.spotify, "SpotifyOAuth", oauth), patch.object(self.spotify, "SpotifyClientCredentials", credentials), \
             patch.object(self.spotify, "spotipy", sdk), patch.object(self.spotify, "CacheFileHandler", Mock()), \
             patch.object(self.spotify, "get_cache_dir", return_value=ROOT):
            client._init_api()
        for factory in (oauth, credentials, sdk.Spotify):
            timeout = factory.call_args.kwargs.get("requests_timeout")
            self.assertIsInstance(timeout, (int, float))
            self.assertGreater(timeout, 0)


class TestMusilonNetworkAudit(NetworkTestCase):
    def test_challenge_retries_are_bounded_and_responses_closed(self):
        engine = self.musilon_engine()
        responses = [Response(text="<script>__arcsjs</script>") for _ in range(4)]
        engine.session.request.side_effect = responses
        engine._solve_arvancloud_challenge = Mock(side_effect=[True, True, True, False])
        with self.assertRaises(self.musilon.FlacifyError):
            engine._request("GET", "https://example.invalid/catalog", max_retries=3)
        self.assertEqual(engine.session.request.call_count, 3)
        for response in responses[:3]:
            response.close.assert_called_once()

    def test_rate_limit_retains_type_and_does_not_sleep_after_last_attempt(self):
        engine = self.musilon_engine()
        responses = [Response(status=429, headers={"Retry-After": "7"}) for _ in range(3)]
        engine.session.request.side_effect = responses
        with patch.object(self.musilon.time, "sleep") as sleep:
            with self.assertRaises(self.musilon.MusilonRateLimitExceededError):
                engine._request("GET", "https://example.invalid/catalog")
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [7, 7])
        for response in responses:
            response.close.assert_called_once()

    def test_long_retry_after_fails_fast_instead_of_retrying_early(self):
        engine = self.musilon_engine()
        response = Response(status=429, headers={"Retry-After": "3600"})
        engine.session.request.return_value = response
        with patch.object(self.musilon.time, "sleep") as sleep:
            with self.assertRaises(self.musilon.MusilonRateLimitExceededError):
                engine._request("GET", "https://example.invalid/catalog")
        self.assertEqual(engine.session.request.call_count, 1)
        sleep.assert_not_called()
        response.close.assert_called_once()

    def test_service_unavailable_recovers_and_closes_discarded_response(self):
        engine = self.musilon_engine()
        unavailable, success = Response(status=503), Response(data={"tracks": []})
        engine.session.request.side_effect = [unavailable, success]
        with patch.object(self.musilon.time, "sleep") as sleep:
            self.assertIs(engine._request("GET", "https://example.invalid/catalog"), success)
        unavailable.close.assert_called_once()
        success.close.assert_not_called()
        sleep.assert_called_once_with(1.5)

    def test_timeout_retries_are_finite(self):
        engine = self.musilon_engine()
        engine.session.request.side_effect = requests.Timeout("offline timeout")
        with patch.object(self.musilon.time, "sleep") as sleep:
            with self.assertRaises(requests.Timeout):
                engine._request("GET", "https://example.invalid/catalog", timeout=4, max_retries=2)
        self.assertEqual(engine.session.request.call_count, 2)
        self.assertEqual(engine.session.request.call_args.kwargs["timeout"], 4)
        sleep.assert_called_once_with(1.5)

    def test_retry_after_http_date_and_malformed_values(self):
        for header, delay in (("Thu, 01 Jan 1970 00:16:47 GMT", 7), ("invalid", 1.5),
                              ("nan", 1.5), ("inf", 1.5), ("-7", 1.5)):
            with self.subTest(header=header):
                engine = self.musilon_engine()
                limited, success = Response(status=429, headers={"Retry-After": header}), Response()
                engine.session.request.side_effect = [limited, success]
                with patch.object(self.musilon.time, "time", return_value=1000), patch.object(self.musilon.time, "sleep") as sleep:
                    self.assertIs(engine._request("GET", "https://example.invalid/catalog"), success)
                sleep.assert_called_once_with(delay)
                limited.close.assert_called_once()

    def test_final_503_is_closed_without_sleep(self):
        engine = self.musilon_engine()
        response = Response(status=503)
        engine.session.request.return_value = response
        with patch.object(self.musilon.time, "sleep") as sleep:
            with self.assertRaises(self.musilon.MusilonError):
                engine._request("GET", "https://example.invalid/catalog", max_retries=1)
        sleep.assert_not_called()
        response.close.assert_called_once()

    def test_catalog_does_not_swallow_rate_limit(self):
        engine = self.musilon_engine()
        engine._request = Mock(side_effect=self.musilon.MusilonRateLimitExceededError("offline quota"))
        with self.assertRaises(self.musilon.MusilonRateLimitExceededError):
            engine._search_catalog("Song Artist")

    def test_login_session_closed_on_http_json_timeout_and_success(self):
        engine = self.musilon_engine()
        engine.session.proxies = {}
        engine.session.cookies = requests.cookies.RequestsCookieJar()
        for result in (Response(status=503), Response(data=ValueError("bad JSON")), requests.Timeout("offline timeout"),
                       Response(data={"csrfToken": "synthetic-csrf"})):
            with self.subTest(result=type(result).__name__):
                login = Mock()
                login.cookies = requests.cookies.RequestsCookieJar()
                login.get.side_effect = [result, Response(data={"user": {"name": "Test User"}})]
                login.post.return_value = Response(data={})
                with patch.object(self.musilon.requests, "Session", return_value=login):
                    ok, _ = engine.login_with_credentials("test@example.invalid", "synthetic-password")
                self.assertEqual(ok, isinstance(result, Response) and result.status_code == 200 and isinstance(result.data, dict))
                login.close.assert_called_once()

    def test_replacing_or_clearing_credentials_drops_old_cookies(self):
        engine = self.musilon_engine()
        for new_cookie in ("", "fresh=synthetic-new"):
            with self.subTest(new_cookie=new_cookie):
                engine.session.cookies = requests.cookies.RequestsCookieJar()
                engine.session.cookies.set("old", "synthetic-old", domain="open.musilon.com")
                engine.set_credentials(session_cookie=new_cookie)
                self.assertNotIn("old", engine.session.cookies.get_dict())
                if new_cookie:
                    self.assertEqual(engine.session.cookies.get_dict()["fresh"], "synthetic-new")

    def test_stream_error_preview_is_bounded_and_preserves_quota_error(self):
        engine = self.musilon_engine()
        response = Response(status=403, headers={"content-type": "application/json"},
                            chunks=[b'{"error":"download_budget_exhausted"}'], forbid_text=True)
        engine.session.get.return_value = response
        engine.is_budget_exhausted = Mock(return_value=False)
        with patch.object(self.musilon.os, "makedirs"), patch.object(self.musilon.os.path, "exists", return_value=False):
            with self.assertRaises(self.musilon.MusilonRateLimitExceededError):
                engine.download_file("https://example.invalid/audio", "offline.ogg")
        response.iter_content.assert_called_once_with(chunk_size=4000)
        response.close.assert_called_once()

    def test_midstream_timeout_closes_response_and_removes_partial_file(self):
        engine = self.musilon_engine()
        response = Response(chunks=[b"OggSsynthetic", requests.Timeout("offline timeout")])
        engine.session.get.return_value = response
        with patch.object(self.musilon.os, "makedirs"), patch.object(self.musilon.os.path, "exists", return_value=True), \
             patch.object(self.musilon.os, "remove") as remove, patch("builtins.open", mock_open()), \
             patch.object(self.musilon, "detect_audio_header", return_value="ogg"):
            with self.assertRaises(requests.Timeout):
                engine.download_file("https://example.invalid/audio", "offline.ogg")
        remove.assert_called_once_with("offline.ogg.part")
        response.close.assert_called_once()

    def test_stream_error_preview_does_not_read_past_limit(self):
        engine = self.musilon_engine()
        response = Response(headers={"content-type": "text/html"}, forbid_text=True,
                            chunks=[b"x" * 4000, AssertionError("Preview read beyond limit")])
        engine.session.get.return_value = response
        with patch.object(self.musilon.os, "makedirs"), patch.object(self.musilon.os.path, "exists", return_value=False):
            with self.assertRaises(self.musilon.MusilonVipError):
                engine.download_file("https://example.invalid/audio", "offline.ogg")
        response.iter_content.assert_called_once_with(chunk_size=4000)
        self.assertEqual(response.chunks_read, 1)
        response.close.assert_called_once()


class TestLyricsNetworkAudit(NetworkTestCase):
    def test_exact_rate_limit_and_server_errors_stop_fallback(self):
        for status in (429, 503):
            with self.subTest(status=status):
                engine = self.lyrics_engine()
                response = Response(status=status)
                engine.session.get.return_value = response
                self.assertIsNone(engine.fetch_lyrics(self.track))
                self.assertEqual(engine.session.get.call_count, 1)
                response.close.assert_called_once()

    def test_exact_timeout_does_not_fan_out_to_search(self):
        engine = self.lyrics_engine()
        engine.session.get.side_effect = requests.Timeout("offline timeout")
        self.assertIsNone(engine.fetch_lyrics(self.track))
        self.assertEqual(engine.session.get.call_count, 1)
        self.assertEqual(engine.session.get.call_args.kwargs["timeout"], 10)

    def test_search_rate_limit_and_timeout_stop_variants(self):
        for result in (Response(status=429), requests.Timeout("offline timeout")):
            with self.subTest(result=type(result).__name__):
                engine = self.lyrics_engine()
                if isinstance(result, Exception):
                    engine.session.get.side_effect = result
                else:
                    engine.session.get.return_value = result
                self.assertIsNone(engine._search_lyrics(self.track, self.track.title))
                self.assertEqual(engine.session.get.call_count, 1)
                if isinstance(result, Response):
                    result.close.assert_called_once()

    def test_404_without_album_retry_preserved_and_responses_closed(self):
        engine = self.lyrics_engine()
        first, second = Response(status=404), Response(data={"plainLyrics": "Words"})
        params = []

        def get(url, **kwargs):
            params.append(dict(kwargs["params"]))
            return first if len(params) == 1 else second

        engine.session.get.side_effect = get
        self.assertEqual(engine.fetch_lyrics(self.track).plain_lyrics, "Words")
        self.assertIn("album_name", params[0])
        self.assertNotIn("album_name", params[1])
        first.close.assert_called_once()
        second.close.assert_called_once()

    def test_bad_exact_json_still_allows_search(self):
        engine = self.lyrics_engine()
        first = Response(data=ValueError("bad JSON"))
        second = Response(data=[{"plainLyrics": "Words", "duration": 180}])
        engine.session.get.side_effect = [first, second]
        self.assertEqual(engine.fetch_lyrics(self.track).plain_lyrics, "Words")
        first.close.assert_called_once()
        second.close.assert_called_once()

    def test_requests_json_error_preserves_exact_and_search_fallback(self):
        for exact in (True, False):
            with self.subTest(exact=exact):
                engine = self.lyrics_engine()
                first = Response(data=requests.exceptions.JSONDecodeError("bad JSON", "{", 1))
                second = Response(data=[{"plainLyrics": "Words", "duration": 180}])
                engine.session.get.side_effect = [first, second]
                result = engine.fetch_lyrics(self.track) if exact else engine._search_lyrics(self.track, self.track.title)
                self.assertIsNotNone(result)
                self.assertEqual(result.plain_lyrics, "Words")
                first.close.assert_called_once()
                second.close.assert_called_once()

    def test_album_retry_timeout_closes_first_response(self):
        engine = self.lyrics_engine()
        first = Response(status=404)
        engine.session.get.side_effect = [first, requests.Timeout("offline timeout")]
        self.assertIsNone(engine.fetch_lyrics(self.track))
        self.assertEqual(engine.session.get.call_count, 2)
        first.close.assert_called_once()

    def test_instrumental_exact_match_preserved(self):
        engine = self.lyrics_engine()
        response = Response(data={"instrumental": True})
        engine.session.get.return_value = response
        self.assertTrue(engine.fetch_lyrics(self.track).instrumental)
        self.assertEqual(engine.session.get.call_count, 1)
        response.close.assert_called_once()

    def test_translation_rate_limit_and_timeout_do_not_trigger_fallback_storm(self):
        for result in (Response(status=429), requests.Timeout("offline timeout")):
            with self.subTest(result=type(result).__name__):
                engine = self.lyrics_engine()
                if isinstance(result, Exception):
                    engine.session.post.side_effect = result
                else:
                    engine.session.post.return_value = result
                self.assertEqual(engine._translate_batch_gtx(["Original"], "fa"), ["Original"])
                engine.session.get.assert_not_called()
                if isinstance(result, Response):
                    result.close.assert_called_once()

    def test_successful_translation_closes_response(self):
        engine = self.lyrics_engine()
        response = Response(data=[["Translated", "en"]])
        engine.session.post.return_value = response
        self.assertEqual(engine._translate_batch_gtx(["Original"], "fa"), ["Translated"])
        response.close.assert_called_once()

    def test_translation_json_error_preserves_secondary_fallback(self):
        engine = self.lyrics_engine()
        first = Response(data=requests.exceptions.JSONDecodeError("bad JSON", "{", 1))
        second = Response(data=[[["Translated"]]])
        engine.session.post.return_value = first
        engine.session.get.return_value = second
        self.assertEqual(engine._translate_batch_gtx(["Original"], "fa"), ["Translated"])
        first.close.assert_called_once()
        second.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()