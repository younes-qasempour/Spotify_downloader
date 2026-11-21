import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from backend.app import create_app
from backend.state import BackendState
from core.archive import ArchiveManager
from core.queue_manager import DownloadQueueManager
from tests.test_backend_core import FakeConfig


class TestBackendWebSpa(unittest.TestCase):
    def setUp(self):
        self._prev_archive_instance = ArchiveManager._instance
        ArchiveManager._instance = None
        self.tmp_dir = tempfile.mkdtemp(prefix="flacify_spa_test_")
        self.db_path = os.path.join(self.tmp_dir, "test_archive.db")
        self.archive = ArchiveManager(db_path=self.db_path)

        self.dist_dir = os.path.join(self.tmp_dir, "dist")
        os.makedirs(os.path.join(self.dist_dir, "assets"), exist_ok=True)
        with open(os.path.join(self.dist_dir, "index.html"), "w", encoding="utf-8") as fh:
            fh.write("<!doctype html><html><body>Flacify SPA Shell</body></html>")
        with open(
            os.path.join(self.dist_dir, "manifest.webmanifest"),
            "w",
            encoding="utf-8",
        ) as fh:
            fh.write('{"short_name": "Flacify"}')
        with open(
            os.path.join(self.dist_dir, "assets", "app-123.js"),
            "w",
            encoding="utf-8",
        ) as fh:
            fh.write("console.log('flacify');")

        self.fake_config = FakeConfig()
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
            lyrics_engine=MagicMock(),
            tagger=MagicMock(),
            audio_engine=self.mock_audio_engine,
            queue_manager=self.qm,
            spotify_client=MagicMock(),
            config_manager=self.fake_config,
            run_startup_scan=False,
        )

    def tearDown(self):
        ArchiveManager._instance = self._prev_archive_instance
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_spa_serves_index_assets_manifest_and_client_routes(self):
        app = create_app(
            state=self.state,
            run_startup_scan=False,
            run_auto_sync_scheduler=False,
            frontend_dist_dir=self.dist_dir,
        )
        with TestClient(app) as client:
            health = client.get("/api/health")
            self.assertEqual(health.status_code, 200)
            self.assertTrue(health.json()["web_ui_enabled"])

            for route in ("/", "/playlists", "/playlists/pl_1", "/library", "/tools", "/settings"):
                resp = client.get(route)
                self.assertEqual(resp.status_code, 200, f"Route {route} failed")
                self.assertIn("Flacify SPA Shell", resp.text)
                self.assertEqual(resp.headers.get("cache-control"), "no-cache")

            asset = client.get("/assets/app-123.js")
            self.assertEqual(asset.status_code, 200)
            self.assertIn("flacify", asset.text)
            self.assertIn("immutable", asset.headers.get("cache-control", ""))

            manifest = client.get("/manifest.webmanifest")
            self.assertEqual(manifest.status_code, 200)
            self.assertEqual(manifest.json()["short_name"], "Flacify")

            missing_asset = client.get("/assets/missing.js")
            self.assertEqual(missing_asset.status_code, 404)

            missing_api = client.get("/api/nonexistent")
            self.assertEqual(missing_api.status_code, 404)
            self.assertEqual(missing_api.json().get("detail"), "Not Found")

    def test_api_only_mode_when_dist_missing(self):
        missing_dir = os.path.join(self.tmp_dir, "does_not_exist")
        app = create_app(
            state=self.state,
            run_startup_scan=False,
            run_auto_sync_scheduler=False,
            frontend_dist_dir=missing_dir,
        )
        with TestClient(app) as client:
            health = client.get("/api/health")
            self.assertEqual(health.status_code, 200)
            self.assertFalse(health.json()["web_ui_enabled"])

            root = client.get("/")
            self.assertEqual(root.status_code, 404)

    def test_real_frontend_dist_served_if_built(self):
        repo_dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
        if not (repo_dist / "index.html").is_file():
            self.skipTest("frontend/dist not built")

        app = create_app(
            state=self.state,
            run_startup_scan=False,
            run_auto_sync_scheduler=False,
        )
        with TestClient(app) as client:
            health = client.get("/api/health")
            self.assertTrue(health.json()["web_ui_enabled"])

            home = client.get("/")
            self.assertEqual(home.status_code, 200)
            self.assertIn("Flacify", home.text)

            manifest = client.get("/manifest.webmanifest")
            self.assertEqual(manifest.status_code, 200)
            self.assertEqual(manifest.json()["short_name"], "Flacify")


if __name__ == "__main__":
    unittest.main()
