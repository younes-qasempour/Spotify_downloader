import unittest
from pathlib import Path
from core.paths import (
    APP_NAME,
    is_frozen,
    get_bundle_dir,
    get_resource_path,
    get_asset_path,
    get_app_data_dir,
    get_config_path,
    get_archive_db_path,
    get_cache_dir,
    get_covers_dir,
    get_logs_dir,
    get_user_bin_dir,
    get_default_download_dir
)


class TestPaths(unittest.TestCase):
    def test_app_name(self):
        self.assertEqual(APP_NAME, "Flacify")

    def test_bundle_dir(self):
        d = get_bundle_dir()
        self.assertTrue(d.exists())
        self.assertTrue(d.is_dir())

    def test_resource_path(self):
        p = get_resource_path("config.example.json")
        self.assertTrue(p.exists())

    def test_asset_path(self):
        p = get_asset_path("assets/icon.ico")
        self.assertTrue(p.exists())

    def test_app_data_directories(self):
        app_data = get_app_data_dir()
        self.assertTrue(app_data.exists())

        cache_dir = get_cache_dir()
        self.assertTrue(cache_dir.exists())

        covers_dir = get_covers_dir()
        self.assertTrue(covers_dir.exists())

        logs_dir = get_logs_dir()
        self.assertTrue(logs_dir.exists())

        bin_dir = get_user_bin_dir()
        self.assertTrue(bin_dir.exists())

    def test_config_and_db_paths(self):
        cfg_p = get_config_path()
        self.assertIn("config.json", str(cfg_p))

        db_p = get_archive_db_path()
        self.assertIn("archive.db", str(db_p))

    def test_default_download_dir(self):
        dl_dir = get_default_download_dir()
        self.assertIn("Spotify Downloads", str(dl_dir))


if __name__ == "__main__":
    unittest.main()
