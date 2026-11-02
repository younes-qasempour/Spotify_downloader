"""Offline storage regressions; no application singletons or user files are imported.

Run only this module: python -B -m unittest discover -s tests -p test_audit_storage.py -v
"""
import ast
import builtins
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import sys
import tempfile
import threading
import types
import unittest
from contextlib import closing
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]


class IsolatedStorageTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="audit-storage-", dir=ROOT)
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.music = self.root / "music"
        self.music.mkdir()
        self.cache = self.root / "cache"
        self.cache.mkdir()
        self.covers = self.cache / "covers"
        self.covers.mkdir()
        package = types.ModuleType("core")
        package.__path__ = [str(ROOT / "core")]
        self.enterContext(patch.dict(sys.modules, {"core": package}))
        for name in ("paths", "config", "archive", "utils", "spotify_client", "transcoder", "exporter"):
            sys.modules.pop(f"core.{name}", None)
        self.enterContext(patch.object(socket.socket, "connect", side_effect=AssertionError("Network forbidden")))
        self.enterContext(patch.object(Path, "home", return_value=self.root))
        self.paths = self.load_module("paths")
        self.enterContext(patch.object(self.paths, "get_app_data_dir", return_value=self.root))
        self.enterContext(patch.object(self.paths, "get_config_path", return_value=self.root / "settings.json"))
        self.enterContext(patch.object(self.paths, "get_default_download_dir", return_value=self.music))
        self.enterContext(patch.object(self.paths, "get_cache_dir", return_value=self.cache))
        self.enterContext(patch.object(self.paths, "get_covers_dir", return_value=self.covers))
        self.config_module = self.load_module("config")
        self.cfg = self.config_module.config
        utilities = types.ModuleType("core.utils")
        utilities.sanitize_filename = lambda value, max_length=100: value[:max_length]
        utilities.extract_embedded_cover = Mock(return_value=None)
        utilities.is_valid_audio_file = Mock(return_value=(True, ""))
        sys.modules[utilities.__name__] = utilities
        spotify = types.ModuleType("core.spotify_client")
        spotify.TrackMetadata = object
        sys.modules[spotify.__name__] = spotify
        transcoder = types.ModuleType("core.transcoder")
        transcoder.get_extension_for_format = lambda fmt: {"mp3": ".mp3", "flac": ".flac", "alac": ".m4a"}.get(fmt)
        transcoder.transcode_audio = Mock(side_effect=AssertionError("Unexpected transcode"))
        sys.modules[transcoder.__name__] = transcoder
        self.exporter = self.load_module("exporter")
        self.archive_module = self.load_module("archive")
        self.archive = self.archive_module.ArchiveManager(str(self.root / "library.sqlite"))
        self.dest = self.root / "export"
        self.dest.mkdir()

    def load_module(self, name):
        spec = importlib.util.spec_from_file_location(f"core.{name}", ROOT / "core" / f"{name}.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module

    def source(self, name="song.flac", data=b"source-audio" * 400):
        path = self.music / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def add_record(self, path, track_id="track"):
        with self.archive.connection() as conn, conn:
            conn.execute(
                "INSERT INTO downloaded_tracks (spotify_id, title, artist, file_path) VALUES (?, ?, ?, ?)",
                (track_id, "Song", "Artist", str(path)),
            )

    def records(self):
        with self.archive.connection() as conn:
            return [dict(row) for row in conn.execute("SELECT * FROM downloaded_tracks ORDER BY spotify_id")]

    def export(self, sources, **options):
        config_options = dict(destination_dir=str(self.dest), create_playlist_subfolder=False)
        config_options.update(options.pop("config_options", {}))
        return self.exporter.PlaylistExporter.export_tracks(
            "Playlist",
            [{"file_path": str(path), "title": f"Track {idx}", "artist": "Artist"} for idx, path in enumerate(sources)],
            self.exporter.ExportConfig(**config_options),
            **options,
        )

    def playlist_files(self, result):
        return [line for line in Path(result.m3u8_path).read_text(encoding="utf-8").splitlines() if line and not line.startswith("#")]


class ConfigStorageTests(IsolatedStorageTest):
    def test_unreadable_config_is_not_replaced(self):
        self.cfg.set("spotify.client_secret", "test-only-secret")
        original = self.cfg.config_path.read_bytes()
        previous = self.cfg.to_dict()
        real_open = builtins.open

        def denied_read(path, mode="r", *args, **kwargs):
            if Path(path) == self.cfg.config_path and mode == "r":
                raise PermissionError("simulated locked config")
            return real_open(path, mode, *args, **kwargs)

        with patch("builtins.open", side_effect=denied_read):
            with self.assertRaises(PermissionError):
                self.cfg.load()
        self.assertEqual(self.cfg.config_path.read_bytes(), original)
        self.assertEqual(self.cfg.to_dict(), previous)

    def test_failed_load_blocks_later_save_until_reload(self):
        original = b'["valid JSON, unsupported schema"]'
        self.cfg.config_path.write_bytes(original)
        with self.assertRaises(ValueError):
            self.cfg.load()
        with self.assertRaises(OSError):
            self.cfg.set("ui.theme", "Light")
        self.assertEqual(self.cfg.config_path.read_bytes(), original)
        self.cfg.config_path.write_text('{"ui": {"theme": "Dark"}}', encoding="utf-8")
        self.cfg.load()
        self.cfg.set("ui.theme", "Light")
        self.assertEqual(json.loads(self.cfg.config_path.read_text())["ui"]["theme"], "Light")

    def test_non_json_errors_do_not_recover_over_existing_file(self):
        for contents, error in ((b"[]", ValueError), (b"null", ValueError), (b"\xff", UnicodeDecodeError),
                                (b'{"version": "invalid"}', TypeError)):
            with self.subTest(contents=contents):
                self.cfg.config_path.write_bytes(contents)
                previous = self.cfg.to_dict()
                with self.assertRaises(error):
                    self.cfg.load()
                self.assertEqual(self.cfg.config_path.read_bytes(), contents)
                self.assertEqual(self.cfg.to_dict(), previous)
        self.assertEqual(list(self.root.glob("*.bak")), [])

    def test_malformed_and_empty_json_are_backed_up_before_recovery(self):
        for contents in (b'{"secret": "test-only",', b""):
            with self.subTest(contents=contents):
                self.cfg.config_path.write_bytes(contents)
                before = set(self.root.glob("*.bak"))
                self.cfg.load()
                backups = set(self.root.glob("*.bak")) - before
                self.assertEqual(len(backups), 1)
                self.assertEqual(backups.pop().read_bytes(), contents)
                self.assertEqual(json.loads(self.cfg.config_path.read_text())["ui"]["theme"], "Dark")

    def test_backup_failure_prevents_recovery(self):
        contents = b'{"secret": "test-only",'
        self.cfg.config_path.write_bytes(contents)
        previous = self.cfg.to_dict()
        with patch.object(self.config_module.shutil, "copy2", side_effect=OSError("backup failed")), \
                patch.object(self.config_module.shutil, "copyfileobj", side_effect=OSError("backup failed")):
            with self.assertRaises(OSError):
                self.cfg.load()
        self.assertEqual(self.cfg.config_path.read_bytes(), contents)
        self.assertEqual(self.cfg.to_dict(), previous)

    def test_save_failure_is_reported_and_set_is_rolled_back(self):
        original = self.cfg.config_path.read_bytes()
        previous = self.cfg.to_dict()
        listener = Mock()
        self.cfg.add_listener(listener)
        with patch.object(self.config_module.os, "replace", side_effect=PermissionError("locked")), \
                patch.object(self.config_module.time, "sleep"):
            with self.assertRaises(PermissionError):
                self.cfg.save()
            with self.assertRaises(PermissionError):
                self.cfg.set("new.nested.value", "test-only")
            with self.assertRaises(PermissionError):
                self.cfg.set("ui.theme", "Light")
        self.assertEqual(self.cfg.config_path.read_bytes(), original)
        self.assertEqual(self.cfg.to_dict(), previous)
        listener.assert_not_called()
        self.assertEqual(list(self.root.glob("*.tmp")), [])

    def test_serialization_failure_rolls_back_without_notification(self):
        previous = self.cfg.to_dict()
        original = self.cfg.config_path.read_bytes()
        listener = Mock()
        self.cfg.add_listener(listener)
        with self.assertRaises(TypeError):
            self.cfg.set("new.value", object())
        self.assertEqual(self.cfg.to_dict(), previous)
        self.assertEqual(self.cfg.config_path.read_bytes(), original)
        listener.assert_not_called()

    def test_successful_set_persists_before_notifying(self):
        seen = []
        self.cfg.add_listener(lambda key, value: seen.append(json.loads(self.cfg.config_path.read_text())["ui"]["theme"]))
        self.cfg.set("ui.theme", "Light")
        self.cfg.set("ui.theme", "Light")
        self.assertEqual(seen, ["Light"])

    def test_backup_flush_failure_prevents_replacement(self):
        original = b'{"test-only-secret":'
        self.cfg.config_path.write_bytes(original)
        with patch.object(self.config_module.os, "fsync", side_effect=OSError("disk failure")):
            with self.assertRaises(OSError):
                self.cfg.load()
        self.assertEqual(self.cfg.config_path.read_bytes(), original)
        with self.assertRaises(OSError):
            self.cfg.save()

    def test_failed_initial_load_can_be_retried(self):
        manager = self.config_module.ConfigManager
        manager._instance = None
        self.cfg.config_path.write_text("[]", encoding="utf-8")
        with self.assertRaises(ValueError):
            manager(self.cfg.config_path)
        self.cfg.config_path.write_text('{"ui": {"theme": "Light"}}', encoding="utf-8")
        recovered = manager(self.cfg.config_path)
        self.assertEqual(recovered.get("ui.theme"), "Light")


class ArchiveStorageTests(IsolatedStorageTest):
    def test_invalid_track_read_preserves_file_and_record(self):
        source = self.source()
        original = source.read_bytes()
        self.add_record(source)
        records = self.records()
        with patch.object(self.archive_module, "is_valid_audio_file", return_value=(False, "temporarily unreadable")):
            self.assertIsNone(self.archive.find_track("track"))
        self.assertTrue(source.exists())
        self.assertEqual(source.read_bytes(), original)
        self.assertEqual(self.records(), records)

    def test_offline_track_read_preserves_record(self):
        self.add_record(self.root / "offline-drive" / "song.flac")
        records = self.records()
        self.assertIsNone(self.archive.find_track("track"))
        self.assertEqual(self.records(), records)

    def test_validation_exception_preserves_track(self):
        source = self.source()
        self.add_record(source)
        records = self.records()
        with patch.object(self.archive_module, "is_valid_audio_file", side_effect=OSError("drive removed")):
            self.assertIsNone(self.archive.find_track("track"))
        self.assertTrue(source.exists())
        self.assertEqual(self.records(), records)

    def test_valid_track_remains_reusable(self):
        source = self.source()
        self.add_record(source)
        self.assertEqual(self.archive.find_track("track")["file_path"], str(source))

    def test_cleanup_preserves_failed_validation_and_offline_rows(self):
        source = self.source()
        original = source.read_bytes()
        outside = self.root / "other-library.mp3"
        outside.write_bytes(b"other-library-audio")
        self.add_record(source)
        self.add_record(outside, "outside")
        self.add_record(self.root / "offline-drive" / "song.flac", "offline")
        records = self.records()
        with patch.object(self.archive_module, "is_valid_audio_file", return_value=(False, "I/O failure")):
            stats = self.archive.purge_corrupt_and_cleanup_library(str(self.music))
        self.assertTrue(source.exists())
        self.assertEqual(source.read_bytes(), original)
        self.assertEqual(outside.read_bytes(), b"other-library-audio")
        self.assertEqual(self.records(), records)
        self.assertEqual(stats["purged_corrupt_files"], 0)
        self.assertEqual(stats["purged_db_records"], 0)

    def test_cleanup_validation_exception_is_non_destructive(self):
        source = self.source()
        self.add_record(source)
        records = self.records()
        with patch.object(self.archive_module, "is_valid_audio_file", side_effect=PermissionError("locked")):
            stats = self.archive.purge_corrupt_and_cleanup_library(str(self.music))
        self.assertTrue(source.exists())
        self.assertEqual(self.records(), records)
        self.assertEqual(stats["purged_corrupt_files"], 0)

    def test_failed_alternate_path_validation_does_not_change_offline_record(self):
        alternate = self.source()
        self.add_record(self.root / "offline-drive" / alternate.name)
        records = self.records()
        with patch.object(self.archive_module, "is_valid_audio_file", return_value=(False, "locked")):
            self.assertIsNone(self.archive.find_track("track"))
        self.assertEqual(self.records(), records)
        self.assertTrue(alternate.exists())


class PathStorageTests(IsolatedStorageTest):
    def legacy_database(self):
        legacy = self.root / "legacy"
        legacy.mkdir()
        self.enterContext(patch.object(self.paths, "__file__", str(legacy / "core" / "paths.py")))
        self.enterContext(patch.object(self.paths, "is_frozen", return_value=False))
        return legacy / "archive.db"

    def test_migration_includes_committed_active_wal(self):
        source = self.legacy_database()
        with closing(sqlite3.connect(source)) as writer:
            writer.execute("PRAGMA journal_mode=WAL")
            writer.execute("PRAGMA wal_autocheckpoint=0")
            writer.execute("CREATE TABLE evidence (value TEXT)")
            writer.execute("INSERT INTO evidence VALUES ('committed-in-wal')")
            writer.commit()
            self.assertGreater(Path(str(source) + "-wal").stat().st_size, 0)
            target = self.paths.get_archive_db_path()
            with closing(sqlite3.connect(target)) as migrated:
                self.assertEqual(migrated.execute("SELECT value FROM evidence").fetchall(), [("committed-in-wal",)])
                self.assertEqual(migrated.execute("PRAGMA integrity_check").fetchone(), ("ok",))
            self.assertEqual(writer.execute("SELECT COUNT(*) FROM evidence").fetchone(), (1,))

    def test_failed_migration_does_not_publish_empty_database(self):
        source = self.legacy_database()
        source.write_bytes(b"not a sqlite database")
        with self.assertRaises(sqlite3.DatabaseError):
            self.paths.get_archive_db_path()
        self.assertFalse((self.root / "archive.db").exists())
        self.assertEqual(source.read_bytes(), b"not a sqlite database")
        self.assertEqual(list(self.root.glob("*.tmp*")), [])

    def test_existing_target_is_not_migrated(self):
        self.legacy_database().write_bytes(b"unrelated legacy file")
        target = self.root / "archive.db"
        target.write_bytes(b"existing destination")
        self.assertEqual(self.paths.get_archive_db_path(), target)
        self.assertEqual(target.read_bytes(), b"existing destination")

    def test_migration_publication_does_not_replace_concurrently_created_target(self):
        source = self.legacy_database()
        with closing(sqlite3.connect(source)) as connection:
            connection.execute("CREATE TABLE evidence (value TEXT)")
            connection.commit()
        target = self.root / "archive.db"

        def concurrent_target(operation):
            def publish(src, dst):
                target.write_bytes(b"another instance owns this database")
                return operation(src, dst)
            return publish

        with patch.object(self.paths.os, "replace", side_effect=concurrent_target(os.replace)), \
                patch.object(self.paths.os, "rename", side_effect=concurrent_target(os.rename)), \
                patch.object(self.paths.os, "link", side_effect=concurrent_target(os.link)):
            self.assertEqual(self.paths.get_archive_db_path(), target)
        self.assertEqual(target.read_bytes(), b"another instance owns this database")
        self.assertEqual(list(self.root.glob("archive-migration-*")), [])


class ExportStorageTests(IsolatedStorageTest):
    def test_identical_basenames_have_distinct_stable_playlist_entries(self):
        sources = [self.source("one/song.flac", b"a" * 4096), self.source("two/song.flac", b"b" * 4096)]
        result = self.export(sources)
        self.assertEqual((result.exported, result.skipped, result.failed), (2, 0, 0))
        names = self.playlist_files(result)
        self.assertEqual(len(set(name.casefold() for name in names)), 2)
        self.assertEqual([(self.dest / name).read_bytes() for name in names], [path.read_bytes() for path in sources])
        again = self.export(list(reversed(sources)))
        self.assertEqual(self.playlist_files(again), list(reversed(names)))
        self.assertEqual(again.skipped, 2)

    def test_converged_format_names_do_not_overwrite_each_other(self):
        sources = [self.source("song.flac", b"a" * 4096), self.source("song.mp3", b"b" * 4096)]

        def transcode(input_file, target_format, delete_source, output_file, cancel_check=None):
            self.assertFalse(delete_source)
            Path(output_file).write_bytes(Path(input_file).read_bytes() + b"converted")
            return output_file

        with patch.object(self.exporter, "transcode_audio", side_effect=transcode):
            result = self.export(sources, config_options={"target_format": "mp3"})
        self.assertEqual((result.exported, result.skipped, result.failed), (2, 0, 0))
        names = self.playlist_files(result)
        self.assertEqual(len(set(names)), 2)
        self.assertTrue(all(name.endswith(".mp3") for name in names))
        self.assertEqual([(self.dest / name).read_bytes() for name in names], [p.read_bytes() + b"converted" for p in sources])

    def test_large_partial_and_same_size_wrong_copy_are_not_skipped(self):
        source = self.source()
        destination = self.dest / source.name
        for bad in (source.read_bytes()[:2048], b"x" * source.stat().st_size):
            with self.subTest(size=len(bad)):
                destination.write_bytes(bad)
                result = self.export([source])
                self.assertEqual((result.exported, result.skipped, result.failed), (1, 0, 0))
                self.assertEqual(destination.read_bytes(), source.read_bytes())

    def test_verified_copy_is_skipped_even_if_small(self):
        source = self.source(data=b"small-complete-copy")
        (self.dest / source.name).write_bytes(source.read_bytes())
        result = self.export([source])
        self.assertEqual((result.exported, result.skipped, result.failed), (0, 1, 0))

    def test_interrupted_copy_preserves_destination_and_cleans_staging(self):
        source = self.source()
        destination = self.dest / source.name
        destination.write_bytes(b"previous complete export")

        def interrupted(src, dst):
            Path(dst).write_bytes(b"partial")
            raise OSError("device full")

        with patch.object(self.exporter.shutil, "copy2", side_effect=interrupted):
            result = self.export([source], config_options={"skip_existing": False})
        self.assertEqual(result.failed, 1)
        self.assertEqual(destination.read_bytes(), b"previous complete export")
        self.assertEqual(sorted(p.name for p in self.dest.iterdir()), [source.name])
        self.assertEqual(source.read_bytes(), b"source-audio" * 400)
        self.assertIsNone(result.m3u8_path)

    def test_same_source_destination_is_safe_with_skip_disabled(self):
        source = self.source()
        result = self.export([source], config_options={"destination_dir": str(self.music), "skip_existing": False})
        self.assertEqual((result.exported, result.skipped, result.failed), (0, 1, 0))
        self.assertEqual(source.read_bytes(), b"source-audio" * 400)

    def test_conversion_into_library_never_modifies_master_files(self):
        source = self.source("song.m4a")
        original = source.read_bytes()

        def transcode(input_file, target_format, delete_source, output_file, cancel_check=None):
            Path(output_file).write_bytes(b"converted-alac" * 400)
            return output_file

        with patch.object(self.exporter, "transcode_audio", side_effect=transcode):
            result = self.export([source], config_options={"destination_dir": str(self.music), "target_format": "alac", "skip_existing": False})
        self.assertEqual(result.exported, 1)
        self.assertEqual(source.read_bytes(), original)
        self.assertNotEqual(self.playlist_files(result), [source.name])

    def test_partial_transcode_is_not_treated_as_complete(self):
        source = self.source()
        destination = self.dest / "song.mp3"
        destination.write_bytes(b"partial" * 400)

        def transcode(input_file, target_format, delete_source, output_file, cancel_check=None):
            Path(output_file).write_bytes(b"complete-converted" * 400)
            return output_file

        with patch.object(self.exporter, "transcode_audio", side_effect=transcode) as converter:
            result = self.export([source], config_options={"target_format": "mp3"})
        self.assertEqual(result.exported, 1)
        self.assertEqual(converter.call_count, 1)
        self.assertEqual(destination.read_bytes(), b"complete-converted" * 400)

    def test_transcode_cancellation_is_forwarded_and_not_published(self):
        source = self.source()
        event = threading.Event()
        destination = self.dest / "song.mp3"
        destination.write_bytes(b"previous-export")
        callbacks = []

        def transcode(input_file, target_format, delete_source, output_file, cancel_check=None):
            callbacks.append(cancel_check)
            Path(output_file).write_bytes(b"cancelled-output" * 400)
            event.set()
            raise RuntimeError("cancelled")

        with patch.object(self.exporter, "transcode_audio", transcode):
            result = self.export([source], cancel_event=event, config_options={"target_format": "mp3", "skip_existing": False})
        self.assertTrue(result.cancelled)
        self.assertEqual((result.exported, result.failed), (0, 0))
        self.assertTrue(callable(callbacks[0]))
        self.assertTrue(callbacks[0]())
        self.assertEqual(destination.read_bytes(), b"previous-export")
        self.assertEqual(sorted(p.name for p in self.dest.iterdir()), [destination.name])
        self.assertIsNone(result.m3u8_path)

    def test_cancel_after_copy_does_not_replace_existing_destination(self):
        source = self.source()
        destination = self.dest / source.name
        destination.write_bytes(b"previous-export")
        event = threading.Event()
        real_copy = shutil.copy2

        def cancel_copy(src, dst):
            real_copy(src, dst)
            event.set()

        with patch.object(self.exporter.shutil, "copy2", side_effect=cancel_copy):
            result = self.export([source], cancel_event=event, config_options={"skip_existing": False})
        self.assertTrue(result.cancelled)
        self.assertEqual((result.exported, result.failed), (0, 0))
        self.assertEqual(destination.read_bytes(), b"previous-export")
        self.assertEqual(sorted(p.name for p in self.dest.iterdir()), [source.name])

    def test_missing_source_and_pre_cancel_are_reported(self):
        result = self.export([self.music / "missing.flac"])
        self.assertEqual(result.failed, 1)
        event = threading.Event()
        event.set()
        cancelled = self.export([self.source()], cancel_event=event)
        self.assertTrue(cancelled.cancelled)
        self.assertEqual(cancelled.exported, 0)

    def test_hardlink_to_source_is_safe_with_skip_disabled(self):
        source = self.source()
        destination = self.dest / source.name
        os.link(source, destination)
        result = self.export([source], config_options={"skip_existing": False})
        self.assertEqual((result.exported, result.skipped, result.failed), (0, 1, 0))
        self.assertEqual(source.read_bytes(), b"source-audio" * 400)
        self.assertTrue(os.path.samefile(source, destination))

    def test_duplicate_source_keeps_playlist_order_without_duplicate_files(self):
        source = self.source()
        result = self.export([source, source])
        self.assertEqual((result.exported, result.skipped, result.failed), (1, 1, 0))
        self.assertEqual(self.playlist_files(result), [source.name, source.name])

    def test_case_and_generated_suffix_collisions_are_disambiguated(self):
        first = self.source("first/Song.flac", b"first" * 400)
        second = self.source("second/song.flac", b"second" * 400)
        key = os.path.normcase(os.path.realpath(first))
        suffix = hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]
        third = self.source(f"third/Song [{suffix}].flac", b"third" * 400)
        sources = [first, second, third]
        result = self.export(sources)
        names = self.playlist_files(result)
        self.assertEqual((result.exported, result.skipped, result.failed), (3, 0, 0))
        self.assertEqual(len(set(name.casefold() for name in names)), 3)
        self.assertEqual([(self.dest / name).read_bytes() for name in names], [path.read_bytes() for path in sources])

    def test_publish_failure_preserves_destination(self):
        source = self.source()
        destination = self.dest / source.name
        destination.write_bytes(b"previous complete export")
        with patch.object(self.exporter.os, "replace", side_effect=PermissionError("destination locked")):
            result = self.export([source], config_options={"skip_existing": False})
        self.assertEqual(result.failed, 1)
        self.assertEqual(destination.read_bytes(), b"previous complete export")
        self.assertEqual(sorted(p.name for p in self.dest.iterdir()), [source.name])

    def test_transcoder_returning_source_is_not_false_success(self):
        source = self.source()
        destination = self.dest / "song.mp3"
        destination.write_bytes(b"previous complete export")
        with patch.object(self.exporter, "transcode_audio", return_value=str(source)):
            result = self.export([source], config_options={"target_format": "mp3", "skip_existing": False})
        self.assertEqual((result.exported, result.failed), (0, 1))
        self.assertEqual(destination.read_bytes(), b"previous complete export")
        self.assertEqual(sorted(p.name for p in self.dest.iterdir()), [destination.name])


class PackagingStorageTests(unittest.TestCase):
    def test_spec_only_includes_explicit_gui_web_assets(self):
        tree = ast.parse((ROOT / "app.spec").read_text(encoding="utf-8"))
        datas = next(ast.literal_eval(node.value) for node in tree.body
                     if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "datas" for target in node.targets))
        self.assertNotIn(("core", "core"), datas)
        self.assertNotIn(("gui", "gui"), datas)
        self.assertIn(("assets", "assets"), datas)
        for name in ("app.js", "index.html", "mini.html", "styles.css"):
            self.assertIn((f"gui/web_ui/{name}", "gui/web_ui"), datas)

    def test_session_journals_are_ignored(self):
        self.assertIn("*.session-journal", (ROOT / ".gitignore").read_text().splitlines())


if __name__ == "__main__":
    unittest.main()