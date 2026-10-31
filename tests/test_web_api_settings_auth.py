import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from core.config import config
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


class TestWebApiSettingsAndAuth(unittest.TestCase):
    def setUp(self):
        self.mock_qm = MagicMock()
        self.mock_archive = MagicMock()
        self.mock_musilon = MagicMock()
        self.mock_melobot = MagicMock()

        self.mock_musilon.is_authenticated.return_value = True
        self.mock_musilon.is_vip = True
        self.mock_musilon.get_download_budget.return_value = {"quota_text": "VIP Unlimited"}
        self.mock_musilon.test_connection.return_value = (True, True, True, "Connected to Musilon VIP")

        self.mock_melobot.is_authorized.return_value = True
        self.mock_melobot.get_me.return_value = {"username": "test_user", "id": 123456}

        self.orig_concurrency = config.get("download.concurrency", 5)
        self.orig_output_dir = config.get("download.output_dir", "")

        self.state = WebBackendState(
            queue_manager=self.mock_qm,
            archive_manager=self.mock_archive,
            musilon_engine=self.mock_musilon,
            melobot_engine=self.mock_melobot,
        )

    def tearDown(self):
        config.set("download.concurrency", self.orig_concurrency)
        config.set("download.output_dir", self.orig_output_dir)
        config.save()

    def _call_handler(self, method, path, body=None, headers=None):
        handler = object.__new__(FlacifyWebRequestHandler)
        handler.state = self.state
        handler.web_root = os.path.abspath("gui/web_ui")
        handler.path = path
        handler.command = method
        handler.headers = headers or {}
        handler.wfile = DummyWFile()
        handler.status_code = None
        handler.response_headers = {}

        def send_response(code, message=None):
            handler.status_code = code

        def send_header(keyword, value):
            handler.response_headers[keyword] = value

        def end_headers():
            pass

        handler.send_response = send_response
        handler.send_header = send_header
        handler.end_headers = end_headers

        if body is not None:
            raw_body = json.dumps(body).encode("utf-8")
            handler.rfile = DummyRFile(raw_body)
            handler.headers["Content-Length"] = str(len(raw_body))
        else:
            handler.rfile = DummyRFile(b"")

        if method == "GET":
            handler.do_GET()
        elif method == "POST":
            handler.do_POST()

        resp_json = None
        if handler.wfile.data:
            try:
                resp_json = json.loads(handler.wfile.data.decode("utf-8"))
            except Exception:
                pass

        return handler.status_code, handler.response_headers, resp_json

    def test_cors_headers_local_origin(self):
        _, headers, _ = self._call_handler("GET", "/api/settings", headers={"Origin": "http://127.0.0.1:8765"})
        self.assertEqual(headers.get("Access-Control-Allow-Origin"), "http://127.0.0.1:8765")

    def test_get_settings(self):
        code, _, resp = self._call_handler("GET", "/api/settings")
        self.assertEqual(code, 200)
        self.assertTrue(resp.get("ok"))
        self.assertIn("settings", resp)
        s = resp["settings"]
        self.assertIn("output_dir", s)
        self.assertIn("preferred_source", s)
        self.assertIn("target_format", s)
        self.assertIn("musilon_safe_mode", s)
        self.assertIn("telegram_enabled", s)

    def test_save_settings(self):
        new_settings = {
            "download.output_dir": "D:\\test_music",
            "concurrency": 8,
            "preferred_source": "musilon",
            "musilon_safe_mode": True,
        }
        code, _, resp = self._call_handler("POST", "/api/settings", body={"settings": new_settings})
        self.assertEqual(code, 200)
        self.assertTrue(resp.get("ok"))

    def test_musilon_status(self):
        code, _, resp = self._call_handler("GET", "/api/auth/musilon/status")
        self.assertEqual(code, 200)
        self.assertTrue(resp.get("ok"))
        self.assertTrue(resp.get("is_authenticated"))
        self.assertTrue(resp.get("is_vip"))
        self.assertEqual(resp["budget"]["quota_text"], "VIP Unlimited")

    def test_telegram_status(self):
        code, _, resp = self._call_handler("GET", "/api/auth/telegram/status")
        self.assertEqual(code, 200)
        self.assertTrue(resp.get("ok"))
        self.assertTrue(resp.get("authorized"))
        self.assertEqual(resp["user"]["username"], "test_user")

    def test_ffmpeg_status(self):
        code, _, resp = self._call_handler("GET", "/api/diagnostics/ffmpeg")
        self.assertEqual(code, 200)
        self.assertTrue(resp.get("ok"))
        self.assertIn("installed", resp)

    def test_maintenance_status(self):
        code, _, resp = self._call_handler("GET", "/api/maintenance/status")
        self.assertEqual(code, 200)
        self.assertTrue(resp.get("ok"))
        self.assertFalse(resp.get("running"))

    def test_maintenance_clean(self):
        self.mock_archive.purge_corrupt_and_cleanup_library.return_value = {
            "purged_corrupt_files": 0,
            "relocated_covers": 0,
            "reorganized_lyrics": 0,
        }
        code, _, resp = self._call_handler("POST", "/api/maintenance/clean", body={})
        self.assertEqual(code, 200)
        self.assertTrue(resp.get("ok"))

    def test_shell_open_security(self):
        # Empty or non-existent path should be safely rejected
        code, _, resp = self._call_handler("POST", "/api/shell/open", body={"path": ""})
        self.assertEqual(code, 400)

        code, _, resp = self._call_handler("POST", "/api/shell/open", body={"path": "Z:\\this_path_does_not_exist_at_all_12345"})
        self.assertEqual(code, 404)


if __name__ == "__main__":
    unittest.main()

