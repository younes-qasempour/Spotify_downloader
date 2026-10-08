import unittest
import tempfile
import os
import json
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


if __name__ == "__main__":
    unittest.main()
