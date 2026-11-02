import os
import sys
import shutil
import logging
import sqlite3
import tempfile
from contextlib import closing
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
    Automatically seeds from clean template config.example.json if missing.
    """
    target = get_app_data_dir() / "config.json"
    if not target.exists():
        # Seed only from clean config.example.json template candidates
        dev_root = Path(__file__).resolve().parent.parent
        seed_candidates = [
            get_resource_path("config.example.json"),
            dev_root / "config.example.json",
        ]
        for cand in seed_candidates:
            if cand.exists() and cand.is_file():
                try:
                    shutil.copy2(str(cand), str(target))
                    logger.info(f"Initialized user configuration from template {cand} -> {target}")
                    break
                except Exception as e:
                    logger.warning(f"Could not seed config from {cand}: {e}")
    return target


def get_archive_db_path() -> Path:
    """
    Returns the path to archive.db inside the user's AppData directory.
    In development mode, snapshots an existing local archive.db, including its WAL.
    """
    target = get_app_data_dir() / "archive.db"
    if not target.exists() and not is_frozen():
        dev_db = Path(__file__).resolve().parent.parent / "archive.db"
        if dev_db.exists() and dev_db.is_file():
            tmp_path = None
            try:
                fd, name = tempfile.mkstemp(prefix="archive-migration-", suffix=".tmp", dir=target.parent)
                os.close(fd)
                tmp_path = Path(name)
                with closing(sqlite3.connect(dev_db.as_uri() + "?mode=ro", uri=True)) as source:
                    with closing(sqlite3.connect(str(tmp_path))) as destination:
                        source.backup(destination)
                        destination.execute("PRAGMA journal_mode=DELETE")
                try:
                    # Publish without overwriting a database created by another instance.
                    if os.name == "nt":
                        os.rename(tmp_path, target)
                    else:
                        os.link(tmp_path, target)
                except FileExistsError:
                    logger.info(f"Archive database already initialized at {target}")
                else:
                    logger.info(f"Migrated existing archive.db from {dev_db} -> {target}")
            except Exception as e:
                logger.warning(f"Could not migrate archive.db: {e}")
                raise
            finally:
                if tmp_path is not None:
                    tmp_path.unlink(missing_ok=True)
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
