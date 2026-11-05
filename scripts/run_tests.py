"""Run the full unittest suite offline without reading or changing user application data."""
import argparse
from contextlib import ExitStack
import logging
import os
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class _EngineCleanupResult(unittest.TextTestResult):
    def __init__(self, *args, engines, **kwargs):
        super().__init__(*args, **kwargs)
        self._engines = engines
        self._engine_start = 0

    def startTest(self, test):
        self._engine_start = len(self._engines)
        super().startTest(test)

    def stopTest(self, test):
        created = self._engines[self._engine_start:]
        del self._engines[self._engine_start:]
        for engine in created:
            engine.close()
        super().stopTest(test)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pattern", default="test_*.py")
    args = parser.parse_args()
    logging.basicConfig(level=logging.ERROR)

    from core import paths

    scratch = ROOT / "scratch"
    scratch.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="offline-tests-", dir=scratch) as temporary, ExitStack() as stack:
        sandbox = Path(temporary)
        downloads = sandbox / "Spotify Downloads"
        downloads.mkdir()
        stack.enter_context(patch.object(paths, "get_app_data_dir", return_value=sandbox))
        stack.enter_context(patch.object(paths, "get_config_path", return_value=sandbox / "config.json"))
        stack.enter_context(patch.object(paths, "get_archive_db_path", return_value=sandbox / "archive.db"))
        stack.enter_context(patch.object(paths, "get_default_download_dir", return_value=downloads))

        cache_dir = sandbox / "cache"
        cache_dir.mkdir(exist_ok=True)
        covers_dir = cache_dir / "covers"
        covers_dir.mkdir(exist_ok=True)
        logs_dir = sandbox / "logs"
        logs_dir.mkdir(exist_ok=True)
        user_bin_dir = sandbox / "bin"
        user_bin_dir.mkdir(exist_ok=True)
        stack.enter_context(patch.object(paths, "get_cache_dir", return_value=cache_dir))
        stack.enter_context(patch.object(paths, "get_covers_dir", return_value=covers_dir))
        stack.enter_context(patch.object(paths, "get_logs_dir", return_value=logs_dir))
        stack.enter_context(patch.object(paths, "get_user_bin_dir", return_value=user_bin_dir))

        original_connect = socket.socket.connect
        original_connect_ex = socket.socket.connect_ex
        original_getaddrinfo = socket.getaddrinfo

        def check_host(host):
            if host not in ("127.0.0.1", "localhost", "::1", "0.0.0.0", None):
                raise OSError("External network is disabled during offline tests")

        def connect(sock, address):
            if isinstance(address, tuple):
                check_host(address[0])
            return original_connect(sock, address)

        def connect_ex(sock, address):
            if isinstance(address, tuple):
                check_host(address[0])
            return original_connect_ex(sock, address)

        def getaddrinfo(host, *args, **kwargs):
            check_host(host)
            return original_getaddrinfo(host, *args, **kwargs)

        stack.enter_context(patch.object(socket.socket, "connect", connect))
        stack.enter_context(patch.object(socket.socket, "connect_ex", connect_ex))
        stack.enter_context(patch.object(socket, "getaddrinfo", getaddrinfo))

        from core.melobot import MeloBotEngine

        engines = []
        original_init = MeloBotEngine.__init__

        def initialize(engine, *args, **kwargs):
            original_init(engine, *args, **kwargs)
            engines.append(engine)

        stack.enter_context(patch.object(MeloBotEngine, "__init__", initialize))
        try:
            suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), pattern=args.pattern)
            result_class = lambda *args, **kwargs: _EngineCleanupResult(*args, engines=engines, **kwargs)
            result = unittest.TextTestRunner(verbosity=2, resultclass=result_class).run(suite)
        finally:
            for engine in engines:
                engine.close()
        return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())