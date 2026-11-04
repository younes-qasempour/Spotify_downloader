import copy
import json
import logging
import math
import os
import shutil
import tempfile
import threading
import time
import string
from pathlib import Path
from urllib.parse import urlsplit
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
        "save_in_subfolders": False,
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
        "normalize_volume": True,
        "target_lufs": -9.0,
        "target_format": "original",
        "review_uncertain_matches": True,
    },
    "ui": {
        "theme": "Dark",
        "clipboard_auto_detect": True,
        "player_volume": 100,
        "eq_enabled": False,
        "eq_preset": "Flat (Default)",
        "eq_preamp": 0.0,
        "eq_bass_boost": 0.0,
        "eq_bands": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        "lyrics_translation_lang": "none",
    },
    "playlists": {
        "auto_sync_on_startup": True,
        "auto_sync_interval_hours": 6,
        "auto_download_synced_tracks": True,
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

            self._lock: threading.RLock = threading.RLock()
            self._listeners: List[Callable[[str, Any], None]] = []
            self._error_handler: Optional[Callable[[str], None]] = None

            if config_path:
                self.config_path = Path(config_path)
            else:
                self.config_path = get_config_path()

            self.data: Dict[str, Any] = {}
            self.load()
            self._initialized = True

    def load(self) -> None:
        """Load configuration, recovering malformed JSON only after a durable backup."""
        with self._lock:
            previous_data = self.data
            self._load_failed = True
            try:
                needs_save = False
                try:
                    with open(self.config_path, "r", encoding="utf-8") as f:
                        disk_data = json.load(f)
                except FileNotFoundError:
                    disk_data = copy.deepcopy(DEFAULT_CONFIG)
                    needs_save = True
                except json.JSONDecodeError:
                    self._backup_corrupt_config()
                    disk_data = copy.deepcopy(DEFAULT_CONFIG)
                    needs_save = True

                if not isinstance(disk_data, dict):
                    raise ValueError(f"Root JSON entity must be a dict, got {type(disk_data).__name__}")

                self.data = self._deep_merge(DEFAULT_CONFIG, disk_data)
                self._migrate()
                self._load_failed = False
                if needs_save:
                    self.save()
                logger.info(f"Loaded configuration from {self.config_path}")
            except Exception as e:
                self.data = previous_data
                self._load_failed = True
                logger.error(f"Failed to load configuration from {self.config_path}: {e}")
                raise

    def _backup_corrupt_config(self) -> None:
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        fd, name = tempfile.mkstemp(
            prefix=f"{self.config_path.stem}.corrupted_{timestamp}_",
            suffix=f"{self.config_path.suffix}.bak",
            dir=self.config_path.parent,
        )
        backup_path = Path(name)
        try:
            with os.fdopen(fd, "wb") as backup:
                with open(self.config_path, "rb") as source:
                    shutil.copyfileobj(source, backup)
                backup.flush()
                os.fsync(backup.fileno())
        except Exception:
            try:
                backup_path.unlink()
            except OSError:
                pass
            raise
        logger.warning(f"Corrupted config safely preserved at: {backup_path}")

    def save(self) -> None:
        """Atomically persist current configuration to disk with retry backoff for Windows file locks."""
        with self._lock:
            if getattr(self, "_load_failed", False):
                raise OSError("Configuration was not loaded safely; reload successfully before saving.")
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
                raise
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

        try:
            self._validate_setting(key_path, value)
        except (TypeError, ValueError) as exc:
            self._report_error(str(exc))
            raise

        has_changed = False

        with self._lock:
            previous_data = copy.deepcopy(self.data)
            try:
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
                if target_key not in d or old_val != value:
                    has_changed = True
                    d[target_key] = copy.deepcopy(value) if isinstance(value, (dict, list)) else value
                    if auto_save:
                        self.save()
            except Exception:
                self.data = previous_data
                self._report_error("Settings could not be saved. Check disk space and folder permissions, then retry; the previous saved settings were preserved.")
                raise

        if has_changed:
            self._notify_listeners(key_path, value)

    def set_many(self, updates: Dict[str, Any]) -> None:
        """Validate and atomically persist multiple dot-path settings as one change."""
        if not isinstance(updates, dict) or not updates:
            raise ValueError("Settings update must be a non-empty mapping.")
        try:
            for key_path, value in updates.items():
                if not isinstance(key_path, str) or not key_path:
                    raise ValueError("Setting paths must be non-empty strings.")
                self._validate_setting(key_path, value)
        except (TypeError, ValueError) as exc:
            self._report_error(str(exc))
            raise
        with self._lock:
            previous_data = copy.deepcopy(self.data)
            try:
                for key_path, value in updates.items():
                    keys = [key for key in key_path.split(".") if key]
                    if not keys:
                        raise ValueError(f"Invalid key path: '{key_path}'")
                    target = self.data
                    for key in keys[:-1]:
                        child = target.get(key)
                        if child is None:
                            child = {}
                            target[key] = child
                        if not isinstance(child, dict):
                            raise TypeError(f"Cannot set '{key_path}': intermediate key '{key}' is not a mapping.")
                        target = child
                    target[keys[-1]] = copy.deepcopy(value) if isinstance(value, (dict, list)) else value
                self.save()
            except Exception:
                self.data = previous_data
                self._report_error("Settings could not be saved. Check disk space and folder permissions, then retry; the previous saved settings were preserved.")
                raise
        for key_path, value in updates.items():
            self._notify_listeners(key_path, value)

    def set_error_handler(self, callback: Optional[Callable[[str], None]]) -> None:
        with self._lock:
            self._error_handler = callback

    def _report_error(self, message: str) -> None:
        with self._lock:
            callback = self._error_handler
        if callback:
            try:
                callback(message)
            except Exception as exc:
                logger.debug(f"Settings error handler failed: {exc}")

    def _validate_setting(self, key_path: str, value: Any) -> None:
        keys = [key for key in key_path.split(".") if key]
        if not keys:
            raise ValueError("Setting path cannot be empty.")
        with self._lock:
            expected = DEFAULT_CONFIG
            for key in keys:
                if not isinstance(expected, dict) or key not in expected:
                    expected = None
                    break
                expected = expected[key]
        if expected is not None:
            if isinstance(expected, bool) and not isinstance(value, bool):
                raise TypeError(f"'{key_path}' must be a boolean.")
            if isinstance(expected, int) and not isinstance(expected, bool) and (not isinstance(value, int) or isinstance(value, bool)):
                raise TypeError(f"'{key_path}' must be an integer.")
            if isinstance(expected, float) and (not isinstance(value, (int, float)) or isinstance(value, bool)):
                raise TypeError(f"'{key_path}' must be a number.")
            if isinstance(expected, str) and not isinstance(value, str):
                raise TypeError(f"'{key_path}' must be text.")
            if isinstance(expected, list) and not isinstance(value, list):
                raise TypeError(f"'{key_path}' must be a list.")
            if isinstance(expected, dict) and not isinstance(value, dict):
                raise TypeError(f"'{key_path}' must be a mapping.")
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError(f"'{key_path}' must be a finite number.")
        if key_path in {"download.concurrency", "musilon.stream_concurrency"} and not 1 <= value <= 32:
            raise ValueError(f"'{key_path}' must be between 1 and 32.")
        if key_path == "ui.player_volume" and not 0 <= value <= 100:
            raise ValueError("'ui.player_volume' must be between 0 and 100.")
        if key_path == "download.target_lufs" and not -24 <= value <= -5:
            raise ValueError("'download.target_lufs' must be between -24 and -5 LUFS.")
        if key_path == "source_engine" and value not in {"musilon", "melobot", "ytm", "youtube"}:
            raise ValueError("'source_engine' must be 'musilon', 'melobot', or 'ytm'.")
        if key_path == "download.target_format":
            from core.transcoder import SUPPORTED_TARGET_FORMATS
            if value not in SUPPORTED_TARGET_FORMATS:
                raise ValueError("'download.target_format' is not a supported audio format.")
        if key_path in {"musilon.cooldown_min_sec", "musilon.cooldown_max_sec"} and not 0 <= value <= 600:
            raise ValueError(f"'{key_path}' must be between 0 and 600 seconds.")
        if key_path == "download.musilon_max_retries" and not 1 <= value <= 20:
            raise ValueError("'download.musilon_max_retries' must be between 1 and 20.")
        if key_path == "download.output_dir" and (not value.strip() or not os.path.isabs(value) or any(char in value for char in "\x00\r\n")):
            raise ValueError("Choose a non-empty absolute output folder path.")
        if key_path in {"download.naming_template", "download.album_naming_template"}:
            allowed = {"artist", "title", "album", "track_num", "track_number", "track", "disc_num", "disc_number"}
            try:
                fields = [field for _, field, _, _ in string.Formatter().parse(value) if field is not None]
                if not value.strip() or any(field not in allowed for field in fields):
                    raise ValueError()
                value.format(**{field: "01" if "track" in field or "disc" in field else "Example" for field in allowed})
            except (ValueError, KeyError, IndexError, AttributeError):
                raise ValueError("Naming templates must use valid artist, title, album, track, or disc placeholders.") from None
        if key_path == "download.proxy" and value:
            try:
                proxy = urlsplit(value)
                if proxy.scheme not in {"http", "https", "socks4", "socks4a", "socks5", "socks5h"} or not proxy.hostname or proxy.port == 0:
                    raise ValueError()
            except ValueError:
                raise ValueError("Proxy must be a valid HTTP, HTTPS, or SOCKS URL with a host and valid port.") from None

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
