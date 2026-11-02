import io
import os
import tempfile
import unittest
import urllib.parse
from email.message import Message
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


class TestWebSecurity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.import_dir = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        cls.addClassCleanup(cls.import_dir.cleanup)
        root = Path(cls.import_dir.name)
        # Importing config normally loads (and can save) the user's configuration.
        with patch("core.paths.get_app_data_dir", return_value=root), \
                patch("core.paths.get_config_path", return_value=root / "config.json"), \
                patch("core.paths.get_default_download_dir", return_value=root / "music"):
            from gui.web_api import FlacifyWebRequestHandler
        cls.handler_type = FlacifyWebRequestHandler

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.web_root = self.root / "web_ui"
        self.web_root.mkdir()
        (self.web_root / "index.html").write_bytes(b"embedded UI")

    def handler(self, method="GET", path="/api/settings", headers=None, production=True):
        handler = object.__new__(self.handler_type)
        handler.path = path
        handler.command = method
        handler.web_root = str(self.web_root)
        handler.headers = Message()
        for key, value in (headers or {}).items():
            handler.headers[key] = value
        if production:
            handler.server = SimpleNamespace(server_address=("127.0.0.1", 8765))
        handler.wfile = io.BytesIO()
        handler.rfile = io.BytesIO(b'{"settings":{"concurrency":99}}')
        handler.status_code = None
        handler.response_headers = {}
        handler.send_response = lambda code, message=None: setattr(handler, "status_code", code)
        handler.send_header = lambda key, value: handler.response_headers.__setitem__(key, value)
        handler.end_headers = lambda: None
        handler._handle_get_settings = Mock(side_effect=lambda: handler._send_json({"ok": True}))
        handler._handle_save_settings = Mock(side_effect=lambda body: handler._send_json({"ok": True}))
        return handler

    def assert_blocked(self, handler):
        getattr(handler, "do_" + handler.command)()
        self.assertEqual(handler.status_code, 403)
        handler._handle_get_settings.assert_not_called()
        handler._handle_save_settings.assert_not_called()
        self.assertEqual(handler.rfile.tell(), 0, "Rejected requests must not consume their body")
        self.assertNotIn("Access-Control-Allow-Origin", handler.response_headers)
        self.assertNotIn("Access-Control-Allow-Credentials", handler.response_headers)

    def test_untrusted_origins_rejected_before_dispatch(self):
        origins = (
            "http://localhost.evil.test", "http://127.0.0.1.evil.test",
            "http://localhost@evil.test", "http://127.0.0.10:8765",
            "https://evil.test", "null", "", "file://", "https://localhost:8765",
            "http://localhost:8766", "http://localhost:8765/",
            "http://localhost:8765?x=1", "http://localhost:8765#fragment",
            "http://localhost:8765:", "http://localhost:99999",
            "http://localhost:8765 http://evil.test", "http://[::1",
            "http://localhost:8765\t", " http://localhost:8765",
        )
        for origin in origins:
            for method in ("GET", "POST", "OPTIONS"):
                with self.subTest(origin=origin, method=method):
                    self.assert_blocked(self.handler(method, headers={
                        "Host": "127.0.0.1:8765", "Origin": origin, "Content-Length": "31",
                    }))

    def test_host_required_and_strict_for_real_requests(self):
        hosts = (
            None, "", "evil.test:8765", "localhost.evil.test:8765",
            "127.0.0.1.evil.test:8765", "localhost@evil.test:8765",
            "localhost:8766", "localhost", "localhost:", "127.1:8765",
            "2130706433:8765", "0.0.0.0:8765", "localhost:8765/path",
            "localhost:8765?", "localhost:8765#", "localhost:8765,evil.test",
            "localhost:99999", "[::1", "localhost:8765\t",
        )
        for host in hosts:
            for method in ("GET", "POST", "OPTIONS"):
                with self.subTest(host=host, method=method):
                    headers = {"Origin": "http://127.0.0.1:8765"}
                    if host is not None:
                        headers["Host"] = host
                    self.assert_blocked(self.handler(method, headers=headers))

    def test_originless_dns_rebinding_rejected(self):
        self.assert_blocked(self.handler(headers={"Host": "attacker.test:8765"}))

    def test_duplicate_security_headers_rejected(self):
        for name, value in (("Host", "127.0.0.1:8765"), ("Origin", "http://localhost:8765"),
                            ("Referer", "http://localhost:8765/"), ("Sec-Fetch-Site", "same-origin")):
            with self.subTest(header=name):
                handler = self.handler(headers={"Host": "127.0.0.1:8765"})
                if name != "Host":
                    handler.headers[name] = value
                handler.headers[name] = value
                self.assert_blocked(handler)

    def test_originless_foreign_browser_requests_rejected(self):
        for extra in ({"Sec-Fetch-Site": "cross-site"}, {"Sec-Fetch-Site": "same-site"},
                      {"Referer": "https://evil.test/page"},
                      {"Referer": "http://localhost:8766/page"}):
            for method in ("GET", "POST", "OPTIONS"):
                with self.subTest(headers=extra, method=method):
                    self.assert_blocked(self.handler(method, headers={"Host": "127.0.0.1:8765", **extra}))

    def test_local_origins_and_ui_requests_remain_usable(self):
        for host in ("127.0.0.1:8765", "localhost:8765", "[::1]:8765"):
            for extra in ({}, {"Origin": "http://" + host}, {"Sec-Fetch-Site": "same-origin"},
                          {"Sec-Fetch-Site": "none"}, {"Referer": "http://" + host + "/library?tab=1"}):
                for method in ("GET", "POST", "OPTIONS"):
                    with self.subTest(host=host, headers=extra, method=method):
                        handler = self.handler(method, headers={"Host": host, **extra})
                        getattr(handler, "do_" + method)()
                        self.assertEqual(handler.status_code, 204 if method == "OPTIONS" else 200)
                        if "Origin" in extra:
                            self.assertEqual(handler.response_headers["Access-Control-Allow-Origin"], extra["Origin"])

    def test_legacy_dummy_handlers_without_server_or_host(self):
        for headers in ({}, {"Origin": "http://127.0.0.1:8765"}):
            handler = self.handler(headers=headers, production=False)
            handler.do_GET()
            self.assertEqual(handler.status_code, 200)
        self.assert_blocked(self.handler(headers={"Origin": "http://localhost.evil.test"}, production=False))

    def test_cors_does_not_reflect_untrusted_origin(self):
        handler = self.handler(headers={"Host": "127.0.0.1:8765", "Origin": "http://localhost.evil.test"})
        handler._send_cors_headers()
        self.assertNotIn("Access-Control-Allow-Origin", handler.response_headers)
        self.assertNotIn("Access-Control-Allow-Credentials", handler.response_headers)

    def test_raw_http_parser_requires_host_without_network(self):
        class MemorySocket:
            def __init__(self, raw):
                self.input = io.BytesIO(raw)
                self.output = bytearray()

            def makefile(self, *args, **kwargs):
                return self.input

            def sendall(self, data):
                self.output.extend(data)

        handler_type = type("BoundHandler", (self.handler_type,), {"web_root": str(self.web_root)})
        for headers, expected in ((b"Host: localhost:8765\r\n", b"200"),
                                  (b"", b"403"), (b"Host: evil.test:8765\r\n", b"403"),
                                  (b"Host: localhost:8765\r\nHost: evil.test:8765\r\n", b"403")):
            with self.subTest(headers=headers):
                sock = MemorySocket(b"GET / HTTP/1.0\r\n" + headers + b"\r\n")
                handler_type(sock, ("127.0.0.1", 54321), SimpleNamespace(server_address=("127.0.0.1", 8765)))
                self.assertEqual(bytes(sock.output).split(b" ")[1], expected)

    def test_static_prefix_sibling_traversal_rejected(self):
        sibling = self.root / "web_ui_private"
        sibling.mkdir()
        (sibling / "secret.txt").write_bytes(b"private fixture")
        for path in ("/../web_ui_private/secret.txt", "/%2e%2e/web_ui_private/secret.txt",
                     "/..\\web_ui_private\\secret.txt", "/%2e%2e%5cweb_ui_private%5csecret.txt"):
            with self.subTest(path=path):
                handler = self.handler(path=path, headers={"Host": "localhost:8765"})
                handler.do_GET()
                self.assertEqual(handler.status_code, 403)
                self.assertNotIn(b"private fixture", handler.wfile.getvalue())

    def test_static_resolved_path_must_stay_inside_root(self):
        outside = self.root / "secret.txt"
        outside.write_bytes(b"private fixture")
        link = self.web_root / "link.txt"
        link.write_bytes(b"placeholder")
        original_realpath = os.path.realpath

        def resolve(path):
            return str(outside) if os.path.normpath(path) == str(link) else original_realpath(path)

        # Model a symlink/junction without requiring Windows symlink privileges.
        handler = self.handler(path="/link.txt", headers={"Host": "localhost:8765"})
        with patch("gui.web_api.os.path.realpath", side_effect=resolve):
            handler.do_GET()
        self.assertEqual(handler.status_code, 403)

    def test_static_index_fallback_is_also_confined(self):
        outside = self.root / "secret.html"
        outside.write_bytes(b"private fixture")
        index = self.web_root / "index.html"
        original_realpath = os.path.realpath

        def resolve(path):
            return str(outside) if os.path.normpath(path) == str(index) else original_realpath(path)

        handler = self.handler(path="/library", headers={"Host": "localhost:8765"})
        with patch("gui.web_api.os.path.realpath", side_effect=resolve):
            handler.do_GET()
        self.assertEqual(handler.status_code, 403)

    def test_static_ui_assets_and_spa_fallback(self):
        (self.web_root / "app.js").write_bytes(b"application fixture")
        for path, expected in (("/", b"embedded UI"), ("/library", b"embedded UI"),
                               ("/app.js", b"application fixture")):
            with self.subTest(path=path):
                handler = self.handler(path=path, headers={"Host": "localhost:8765"})
                handler.do_GET()
                self.assertEqual(handler.status_code, 200)
                self.assertEqual(handler.wfile.getvalue(), expected)

    def test_static_drive_stream_and_null_paths_rejected(self):
        for path in ("/C:/private.txt", "/index.html:private", "/index.html%00"):
            with self.subTest(path=path):
                handler = self.handler(path=path, headers={"Host": "localhost:8765"})
                handler.do_GET()
                self.assertEqual(handler.status_code, 403)

    def test_audio_endpoint_does_not_serve_arbitrary_files(self):
        for name in ("config.json", "archive.db", "telegram_session.session", "cookies.txt"):
            with self.subTest(name=name):
                private = self.root / name
                private.write_bytes(b"private fixture")
                for transcode in ("0", "1"):
                    path = "/api/audio?path=" + urllib.parse.quote(str(private)) + "&transcode=" + transcode
                    handler = self.handler(path=path, headers={"Host": "localhost:8765"})
                    with patch("gui.web_api.get_cached_transcode", return_value=None) as convert:
                        handler.do_GET()
                    self.assertEqual(handler.status_code, 403)
                    self.assertNotIn(b"private fixture", handler.wfile.getvalue())
                    convert.assert_not_called()

    def test_audio_link_cannot_disguise_non_audio_target(self):
        private = self.root / "config.json"
        private.write_bytes(b"private fixture")
        link = self.root / "track.mp3"
        link.write_bytes(b"placeholder")
        original_realpath = os.path.realpath

        def resolve(path):
            return str(private) if os.path.normpath(path) == str(link) else original_realpath(path)

        handler = self.handler(path="/api/audio?path=" + urllib.parse.quote(str(link)),
                               headers={"Host": "localhost:8765"})
        with patch("gui.web_api.os.path.realpath", side_effect=resolve):
            handler.do_GET()
        self.assertEqual(handler.status_code, 403)
        self.assertNotIn(b"private fixture", handler.wfile.getvalue())

    def test_audio_byte_ranges_remain_usable(self):
        audio = self.root / "track.mp3"
        audio.write_bytes(b"0123456789")
        handler = self.handler(path="/api/audio?path=" + urllib.parse.quote(str(audio)),
                               headers={"Host": "localhost:8765", "Range": "bytes=2-5"})
        handler.do_GET()
        self.assertEqual(handler.status_code, 206)
        self.assertEqual(handler.wfile.getvalue(), b"2345")
        self.assertEqual(handler.response_headers["Content-Range"], "bytes 2-5/10")


if __name__ == "__main__":
    unittest.main()