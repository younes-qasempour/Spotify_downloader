import os
import json
import logging
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger("core.config")

DEFAULT_CONFIG: Dict[str, Any] = {
    "musilon": {
        "session_cookie": "",
        "username": "",
        "password": "",
        "enabled": True,
        "arcsjs": "",
        "arcsjsc": "",
    },
    "spotify": {
        "client_id": "",
        "client_secret": "",
    },
    "download": {
        "output_dir": os.path.normpath(os.path.expanduser("~/Music/Spotify Downloads")),
        "naming_template": "{artist} - {title}",
        "save_lrc": True,
        "embed_lyrics": True,
        "embed_cover_art": True,
        "allow_fallback": True,
        "quality_priority": [
            "musilon_flac_16",
            "musilon_flac_24",
            "musilon_mp3_320",
            "ytm_opus",
        ],
        "concurrency": 2,
    },
    "ui": {
        "theme": "Dark",
        "clipboard_auto_detect": True,
    }
}


class ConfigManager:
    """
    Thread-safe persistent configuration manager storing settings in config.json.
    """
    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(ConfigManager, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, config_path: str | None = None):
        if self._initialized:
            return
        self._initialized = True
        if config_path:
            self.config_path = Path(config_path)
        else:
            # Default to config.json in app directory
            self.config_path = Path(__file__).resolve().parent.parent / "config.json"
        
        self.data: Dict[str, Any] = {}
        self.load()

    def load(self) -> None:
        """Load configuration from disk, creating default if not found."""
        if self.config_path.exists():
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    disk_data = json.load(f)
                    self.data = self._deep_merge(DEFAULT_CONFIG, disk_data)
                    logger.info(f"Loaded configuration from {self.config_path}")
                    return
            except Exception as e:
                logger.error(f"Failed to read {self.config_path}, fallback to default: {e}")
        
        self.data = json.loads(json.dumps(DEFAULT_CONFIG))
        self.save()

    def save(self) -> None:
        """Persist current configuration to disk."""
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)
            logger.info(f"Configuration saved to {self.config_path}")
        except Exception as e:
            logger.error(f"Failed to save configuration: {e}")

    def get(self, key_path: str, default: Any = None) -> Any:
        """
        Get value using dot-separated path (e.g. 'musilon.session_cookie').
        """
        keys = key_path.split(".")
        val = self.data
        for k in keys:
            if isinstance(val, dict) and k in val:
                val = val[k]
            else:
                return default
        return val

    def set(self, key_path: str, value: Any, auto_save: bool = True) -> None:
        """
        Set value using dot-separated path (e.g. 'musilon.session_cookie', 'val').
        """
        keys = key_path.split(".")
        d = self.data
        for k in keys[:-1]:
            if k not in d or not isinstance(d[k], dict):
                d[k] = {}
            d = d[k]
        d[keys[-1]] = value
        if auto_save:
            self.save()

    def _deep_merge(self, base: dict, override: dict) -> dict:
        result = json.loads(json.dumps(base))
        for k, v in override.items():
            if k in result and isinstance(result[k], dict) and isinstance(v, dict):
                result[k] = self._deep_merge(result[k], v)
            else:
                result[k] = v
        return result


config = ConfigManager()
