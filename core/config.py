import copy
import json
import logging
import os
import shutil
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

from core.paths import get_cache_dir, get_config_path, get_default_download_dir

logger = logging.getLogger("core.config")

CONFIG_VERSION: int = 1

SECRET_KEYS: Set[str] = {
    "session_cookie",
    "password",
    "client_secret",
    "arcsjs",
    "arcsjsc",
    "api_hash",
}

DEFAULT_CONFIG: Dict[str, Any] = {
    "version": CONFIG_VERSION,
    "source_engine": "musilon",  # "musilon" or "melobot"
    "musilon": {
        "session_cookie": "",
        "username": "",
        "password": "",
        "enabled": True,
        "arcsjs": "",
        "arcsjsc": "",
        "safe_mode": True,
        "cooldown_min_sec": 15,
        "cooldown_max_sec": 35,
        "stream_concurrency": 1,
    },
    "telegram": {
        "enabled": False,
        "bot_username": "melobot",
        "api_id": 2040,
        "api_hash": "b18441a1ff607e10a989891a5462e627",
        "phone": "",
        "session_name": "telegram_session",
        "preferred_quality": "320",
        "safe_delay_sec": 0.5,
    },
    "spotify": {
        "client_id": "",
        "client_secret": "",
    },
    "download": {
        "output_dir": os.path.normpath(str(get_default_download_dir())),
        "cache_dir": os.path.normpath(str(get_cache_dir())),
        "naming_template": "{artist} - {title}",
        "album_naming_template": "{track_num}. {artist} - {title}",
        "save_lrc": False,
        "lyrics_mode": "embedded_only",
        "embed_lyrics": True,
        "embed_cover_art": True,
        "allow_fallback": True,
        "musilon_max_retries": 5,
        "preferred_quality": "320",
        "quality_priority": [
            "musilon_mp3_320",
            "musilon_flac_16",
            "musilon_flac_24",
            "ytm_opus",
        ],
        "concurrency": 5,
        "cookies_file": "",
        "proxy": "",
        "generate_m3u8": True,
        "replaygain_tagging": False,
        "target_format": "original",
    },
    "ui": {
        "theme": "Dark",
        "clipboard_auto_detect": True,
    },
}


class ConfigManager:
    """
    Thread-safe, crash-resilient persistent configuration manager.
    Supports atomic writes, corrupted JSON recovery, observer notifications,
    and secret redaction.
    """

    _instance: Optional["ConfigManager"] = None
    _init_lock: threading.Lock = threading.Lock()

    def __new__(cls, *args, **kwargs) -> "ConfigManager":
        if cls._instance is None:
            with cls._init_lock:
                if cls._instance is None:
                    cls._instance = super(ConfigManager, cls).__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self, config_path: str | Path | None = None) -> None:
        with self._init_lock:
            if getattr(self, "_initialized", False):
                if config_path and Path(config_path) != self.config_path:
                    self.config_path = Path(config_path)
                    self.load()
                return

            self._initialized = True
            self._lock: threading.RLock = threading.RLock()
            self._listeners: List[Callable[[str, Any], None]] = []

            if config_path:
                self.config_path = Path(config_path)
            else:
                self.config_path = get_config_path()

            self.data: Dict[str, Any] = {}
            self.load()

    def load(self) -> None:
        """Load configuration from disk. Safely creates backups if corrupt."""
        with self._lock:
            if self.config_path.exists():
                # Handle 0-byte temporary test files or empty files gracefully
                if self.config_path.stat().st_size == 0:
                    logger.debug("Config file is empty; initializing with default configuration.")
                    self.data = copy.deepcopy(DEFAULT_CONFIG)
                    self.save()
                    return

                try:
                    with open(self.config_path, "r", encoding="utf-8") as f:
                        disk_data = json.load(f)

                    if not isinstance(disk_data, dict):
                        raise ValueError(f"Root JSON entity must be a dict, got {type(disk_data).__name__}")

                    self.data = self._deep_merge(DEFAULT_CONFIG, disk_data)
                    self._migrate()
                    logger.info(f"Loaded configuration from {self.config_path}")
                    return
                except Exception as e:
                    logger.error(f"Failed to read/parse {self.config_path}: {e}")
                    # Safeguard: Backup the corrupted file before overwriting with defaults
                    try:
                        timestamp = time.strftime("%Y%m%d_%H%M%S")
                        backup_path = self.config_path.with_name(
                            f"{self.config_path.stem}.corrupted_{timestamp}{self.config_path.suffix}.bak"
                        )
                        shutil.copy2(self.config_path, backup_path)
                        logger.warning(f"Corrupted config safely preserved at: {backup_path}")
                    except Exception as backup_err:
                        logger.error(f"Could not create backup of corrupted config: {backup_err}")

            self.data = copy.deepcopy(DEFAULT_CONFIG)
            self.save()

    def save(self) -> None:
        """Atomically persist current configuration to disk with retry backoff for Windows file locks."""
        with self._lock:
            # Use unique PID + thread identifier to eliminate temporary file collisions
            tmp_path = self.config_path.with_name(
                f"{self.config_path.name}.{os.getpid()}_{threading.get_ident()}.tmp"
            )
            try:
                self.config_path.parent.mkdir(parents=True, exist_ok=True)
                with open(tmp_path, "w", encoding="utf-8") as f:
                    json.dump(self.data, f, indent=2, ensure_ascii=False)
                    f.flush()
                    os.fsync(f.fileno())

                # Windows file locking retry logic (guards against AV and indexing locks)
                max_retries = 5
                for attempt in range(max_retries):
                    try:
                        os.replace(tmp_path, self.config_path)
                        logger.debug(f"Configuration saved to {self.config_path}")
                        break
                    except (PermissionError, OSError) as os_err:
                        if attempt < max_retries - 1:
                            time.sleep(0.05 * (2**attempt))
                        else:
                            raise os_err
            except Exception as e:
                logger.error(f"Failed to persist configuration to {self.config_path}: {e}")
            finally:
                if tmp_path.exists():
                    try:
                        tmp_path.unlink()
                    except OSError:
                        pass

    def get(self, key_path: str, default: Any = None) -> Any:
        """
        Get value using dot-separated path (e.g. 'download.quality_priority').
        Returns deep copies of mutable collections to prevent untracked thread mutations.
        """
        if not key_path:
            return default

        keys = [k for k in key_path.split(".") if k]
        with self._lock:
            val = self.data
            for k in keys:
                if isinstance(val, dict) and k in val:
                    val = val[k]
                else:
                    return default

            if isinstance(val, (dict, list)):
                return copy.deepcopy(val)
            return val

    def set(self, key_path: str, value: Any, auto_save: bool = True) -> None:
        """
        Set value using dot-separated path (e.g. 'musilon.session_cookie').
        Guarantees path validity and dispatches notifications to listeners.
        """
        if not key_path:
            raise ValueError("Key path cannot be empty")

        keys = [k for k in key_path.split(".") if k]
        if not keys:
            raise ValueError(f"Invalid key path: '{key_path}'")

        has_changed = False

        with self._lock:
            d = self.data
            for i, k in enumerate(keys[:-1]):
                if k not in d:
                    d[k] = {}
                elif not isinstance(d[k], dict):
                    prefix = ".".join(keys[: i + 1])
                    raise TypeError(
                        f"Cannot set '{key_path}': intermediate key '{prefix}' is {type(d[k]).__name__}, expected dict."
                    )
                d = d[k]

            target_key = keys[-1]
            old_val = d.get(target_key)
            if old_val != value:
                has_changed = True
                d[target_key] = copy.deepcopy(value) if isinstance(value, (dict, list)) else value
                if auto_save:
                    self.save()

        if has_changed:
            self._notify_listeners(key_path, value)

    def add_listener(self, callback: Callable[[str, Any], None]) -> None:
        """Register a callback invoked when a configuration key changes: callback(key_path, new_value)."""
        with self._lock:
            if callback not in self._listeners:
                self._listeners.append(callback)

    def remove_listener(self, callback: Callable[[str, Any], None]) -> None:
        """Unregister a configuration listener callback."""
        with self._lock:
            if callback in self._listeners:
                self._listeners.remove(callback)

    def _notify_listeners(self, key_path: str, value: Any) -> None:
        with self._lock:
            listeners = list(self._listeners)
        for cb in listeners:
            try:
                cb(key_path, value)
            except Exception as e:
                logger.error(f"Error executing config listener for '{key_path}': {e}")

    def to_dict(self, mask_secrets: bool = False) -> Dict[str, Any]:
        """Export a clean copy of the configuration, optionally masking sensitive credentials."""
        with self._lock:
            exported = copy.deepcopy(self.data)
        if mask_secrets:
            self._mask_recursive(exported)
        return exported

    @classmethod
    def _mask_recursive(cls, d: dict) -> None:
        for k, v in d.items():
            if isinstance(v, dict):
                cls._mask_recursive(v)
            elif isinstance(v, str) and k in SECRET_KEYS and v:
                d[k] = "******" if len(v) <= 8 else f"{v[:3]}***{v[-3:]}"

    def _migrate(self) -> None:
        """Handles forward migrations between configuration schema versions."""
        current_version = self.data.get("version", 1)
        self.data["version"] = max(current_version, DEFAULT_CONFIG.get("version", 1))

        # Ensure output_dir is never empty or relative (e.g. 'downloads')
        download_cfg = self.data.setdefault("download", {})
        out_dir = str(download_cfg.get("output_dir", "")).strip()
        if not out_dir or out_dir.lower() == "downloads" or not os.path.isabs(out_dir):
            download_cfg["output_dir"] = os.path.normpath(str(get_default_download_dir()))

    def _deep_merge(self, base: dict, override: dict) -> dict:
        result = copy.deepcopy(base)
        if not isinstance(override, dict):
            return result
        for k, v in override.items():
            if k in result and isinstance(result[k], dict) and isinstance(v, dict):
                result[k] = self._deep_merge(result[k], v)
            else:
                result[k] = copy.deepcopy(v) if isinstance(v, (dict, list)) else v
        return result

    def __getitem__(self, key: str) -> Any:
        return self.get(key)

    def __setitem__(self, key: str, value: Any) -> None:
        self.set(key, value)

    def __contains__(self, key: str) -> bool:
        return self.get(key) is not None


config = ConfigManager()
