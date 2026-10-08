import os
import sys
import shutil
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger("core.paths")

APP_NAME = "Flacify"


def is_frozen() -> bool:
    """Returns True if running inside a PyInstaller frozen bundle."""
    return getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")


def get_bundle_dir() -> Path:
    """
    Returns the read-only bundle directory:
    - In frozen PyInstaller app: sys._MEIPASS
    - In development mode: root directory of the repository
    """
    if is_frozen():
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent.parent


def get_resource_path(*subpaths: str) -> Path:
    """
    Resolves an absolute path to a read-only static bundled resource
    (icons, assets, style sheets, bundled binaries, templates).
    """
    return get_bundle_dir().joinpath(*subpaths)


def get_asset_path(relative_path: str = "") -> Path:
    """
    Returns sys._MEIPASS / relative_path when frozen, or repo root / relative_path in dev.
    """
    if relative_path:
        return get_bundle_dir() / relative_path
    return get_bundle_dir()


def get_app_data_dir() -> Path:
    """
    Returns the writable user application data directory:
    Windows: %LOCALAPPDATA%\\Flacify (or %APPDATA%\\Flacify)
    Non-Windows: ~/.flacify
    Ensures the directory exists.
    """
    if os.name == "nt":
        base = os.getenv("LOCALAPPDATA") or os.getenv("APPDATA")
        if base:
            app_dir = Path(base) / APP_NAME
        else:
            app_dir = Path.home() / "AppData" / "Local" / APP_NAME
    else:
        app_dir = Path.home() / f".{APP_NAME.lower()}"

    app_dir.mkdir(parents=True, exist_ok=True)
    return app_dir


def get_config_path() -> Path:
    """
    Returns the path to config.json inside the user's AppData directory.
    Automatically seeds from local/bundled config.example.json or config.json if missing.
    """
    target = get_app_data_dir() / "config.json"
    if not target.exists():
        # Seed from dev config.json or config.example.json
        dev_root = Path(__file__).resolve().parent.parent
        seed_candidates = [
            dev_root / "config.json",
            dev_root / "config.example.json",
            get_resource_path("config.example.json"),
            get_resource_path("config.json"),
        ]
        for cand in seed_candidates:
            if cand.exists() and cand.is_file():
                try:
                    shutil.copy2(str(cand), str(target))
                    logger.info(f"Initialized user configuration from {cand} -> {target}")
                    break
                except Exception as e:
                    logger.warning(f"Could not seed config from {cand}: {e}")
    return target


def get_archive_db_path() -> Path:
    """
    Returns the path to archive.db inside the user's AppData directory.
    If archive.db does not exist in AppData, copies any existing local archive.db
    from the project root to preserve historical downloads.
    """
    target = get_app_data_dir() / "archive.db"
    if not target.exists():
        dev_db = Path(__file__).resolve().parent.parent / "archive.db"
        if dev_db.exists() and dev_db.is_file():
            try:
                shutil.copy2(str(dev_db), str(target))
                logger.info(f"Migrated existing archive.db from {dev_db} -> {target}")
            except Exception as e:
                logger.warning(f"Could not migrate archive.db: {e}")
    return target


def get_cache_dir() -> Path:
    """Returns the writable cache directory inside AppData."""
    p = get_app_data_dir() / "cache"
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_covers_dir() -> Path:
    """Returns the cover artwork cache directory inside AppData."""
    p = get_cache_dir() / "covers"
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_logs_dir() -> Path:
    """Returns the writable logging directory inside AppData."""
    p = get_app_data_dir() / "logs"
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_user_bin_dir() -> Path:
    """Returns the writable user binary directory inside AppData for downloaded engines."""
    p = get_app_data_dir() / "bin"
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_default_download_dir() -> Path:
    """Returns the user's default music download directory."""
    music_dir = Path.home() / "Music" / "Spotify Downloads"
    return music_dir
