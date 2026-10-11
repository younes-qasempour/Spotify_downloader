import glob
import json
import os
import tempfile
import unittest
from pathlib import Path

from core.config import ConfigManager, DEFAULT_CONFIG


class TestConfig(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self.tmp.close()
        # Reset singleton instance
        ConfigManager._instance = None

    def tearDown(self):
        ConfigManager._instance = None
        if os.path.exists(self.tmp.name):
            try:
                os.remove(self.tmp.name)
            except Exception:
                pass
        # Clean up any test backups created in temp directory
        pattern = self.tmp.name.replace(".json", "") + "*.bak"
        for bak in glob.glob(pattern):
            try:
                os.remove(bak)
            except Exception:
                pass

    def test_default_config_creation(self):
        cfg = ConfigManager(config_path=self.tmp.name)
        self.assertTrue(os.path.exists(self.tmp.name))
        self.assertEqual(cfg.get("ui.theme"), "Dark")
        self.assertEqual(cfg.get("musilon.enabled"), True)

    def test_get_and_set(self):
        cfg = ConfigManager(config_path=self.tmp.name)
        cfg.set("spotify.client_id", "my_test_client_id")
        self.assertEqual(cfg.get("spotify.client_id"), "my_test_client_id")

        # Reload from disk to verify persistence
        with open(self.tmp.name, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["spotify"]["client_id"], "my_test_client_id")

    def test_fallback_defaults(self):
        cfg = ConfigManager(config_path=self.tmp.name)
        self.assertEqual(cfg.get("nonexistent.key", "default_val"), "default_val")

    def test_mutable_collection_isolation(self):
        cfg = ConfigManager(config_path=self.tmp.name)
        # Mutating the returned list from get() must not corrupt internal state
        qualities = cfg.get("download.quality_priority")
        self.assertIsInstance(qualities, list)
        qualities.append("fake_codec")
        self.assertNotIn("fake_codec", cfg.get("download.quality_priority"))

    def test_intermediate_scalar_overwrite_protection(self):
        cfg = ConfigManager(config_path=self.tmp.name)
        # Attempting to treat a boolean as an intermediate dictionary should raise TypeError
        with self.assertRaises(TypeError):
            cfg.set("download.save_lrc.invalid_subnode", 123)

    def test_listeners_pubsub(self):
        cfg = ConfigManager(config_path=self.tmp.name)
        events = []

        def on_change(key, val):
            events.append((key, val))

        cfg.add_listener(on_change)
        cfg.set("ui.theme", "Light")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0], ("ui.theme", "Light"))

        # Redundant set should not trigger listener
        cfg.set("ui.theme", "Light")
        self.assertEqual(len(events), 1)

        cfg.remove_listener(on_change)
        cfg.set("ui.theme", "Dark")
        self.assertEqual(len(events), 1)

    def test_mask_secrets(self):
        cfg = ConfigManager(config_path=self.tmp.name)
        cfg.set("musilon.password", "super_secret_pw")
        cfg.set("spotify.client_secret", "spotify_secret_12345")

        masked = cfg.to_dict(mask_secrets=True)
        self.assertNotEqual(masked["musilon"]["password"], "super_secret_pw")
        self.assertIn("*", masked["musilon"]["password"])
        self.assertNotEqual(masked["spotify"]["client_secret"], "spotify_secret_12345")

        raw = cfg.to_dict(mask_secrets=False)
        self.assertEqual(raw["musilon"]["password"], "super_secret_pw")

    def test_corrupt_config_backup(self):
        # Write corrupted JSON to the file
        with open(self.tmp.name, "w", encoding="utf-8") as f:
            f.write("{\ninvalid_json: true, trailing_comma: [")

        ConfigManager._instance = None
        cfg = ConfigManager(config_path=self.tmp.name)
        # Should gracefully recover with defaults
        self.assertEqual(cfg.get("ui.theme"), "Dark")

        # Verify a .bak backup file was created
        pattern = self.tmp.name.replace(".json", "") + "*.bak"
        backups = glob.glob(pattern)
        self.assertTrue(len(backups) >= 1)

    def test_dict_style_access(self):
        cfg = ConfigManager(config_path=self.tmp.name)
        cfg["ui.theme"] = "Light"
        self.assertEqual(cfg["ui.theme"], "Light")
        self.assertTrue("ui.theme" in cfg)


if __name__ == "__main__":
    unittest.main()
