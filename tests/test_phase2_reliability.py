"""Offline contracts for the approved reliability improvements."""
import copy
import json
import os
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import requests

from core.config import ConfigManager
from core.musilon import MusilonEngine
from core.output_preview import format_track_basename, next_output_path, preview_outputs
from core.provider_cooldown import ProviderCooldowns, retry_after_seconds
from core.queue_manager import DownloadQueueManager
from core.reliability_store import ReliabilityStore
from core.source_review import diagnostic_hint, processing_stage, source_review_summary
from core.spotify_client import SpotifyClient, TrackMetadata


def track(track_id="A" * 22, title="Song"):
    return TrackMetadata(id=track_id, title=title, artists=["Artist"], album="Album", duration_ms=180000)


class ReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = ReliabilityStore(Path(self.temp.name) / "jobs.sqlite3")
        self.enterContext(patch("core.queue_manager.ReliabilityStore", return_value=self.store))

    def manager(self):
        manager = DownloadQueueManager(audio_engine=Mock(), archive_manager=Mock())
        self.addCleanup(manager.stop)
        return manager

    def test_queue_round_trip_never_starts_network_work(self):
        manager = self.manager()
        manager.enqueue([track()])
        restored = self.manager()
        self.assertEqual(len(restored.get_items()), 1)
        self.assertEqual(restored.get_items()[0].status, "Stopped")
        self.assertFalse(restored._running)
        self.assertEqual(restored._queue.qsize(), 0)
        restored.engine.resolve_source.assert_not_called()
        record = self.store.load_queue()[0]
        self.assertEqual(record["track"], asdict(track()))
        self.assertNotIn("source_obj", record)

    def test_completed_and_cancelled_jobs_are_not_restored(self):
        manager = self.manager()
        first, second = track(), track("B" * 22)
        manager.enqueue([first, second])
        manager.cancel_track(first.id)
        manager._running = True
        manager._update_status(manager._items[second.id], "Completed")
        self.assertEqual(self.store.load_queue(), [])

    def test_removing_a_job_updates_the_snapshot(self):
        manager = self.manager()
        manager.enqueue([track()])
        manager.remove_track(track().id)
        self.assertEqual(self.store.load_queue(), [])

    def test_manual_recovery_can_complete_a_stopped_job(self):
        manager = self.manager()
        manager.enqueue([track()])
        manager.archive.infer_badge_from_file.return_value = ("FLAC 16", "Local")
        with patch("core.queue_manager.is_valid_audio_file", return_value=(True, "ok")):
            self.assertTrue(manager.complete_recovered_track(track().id, "recovered.flac"))
        self.assertEqual(manager.get_items()[0].status, "Completed")
        self.assertEqual(self.store.load_queue(), [])
        self.assertFalse(manager.complete_recovered_track("missing", "unused"))

    def test_cache_expiry_and_bound(self):
        for index in range(3):
            with patch("core.reliability_store.time.time", return_value=100 + index):
                self.store.set_metadata(str(index), {"index": index}, ttl_seconds=10, max_entries=2)
        with patch("core.reliability_store.time.time", return_value=103):
            self.assertIsNone(self.store.get_metadata("0"))
            self.assertEqual(self.store.get_metadata("1"), {"index": 1})
        with patch("core.reliability_store.time.time", return_value=120):
            self.assertIsNone(self.store.get_metadata("2"))

    def test_store_releases_windows_database_handles(self):
        self.store.save_queue([])
        self.store.get_metadata("missing")
        moved = self.store.path.with_suffix(".moved")
        os.replace(self.store.path, moved)
        os.replace(moved, self.store.path)

    def test_source_summary_contains_no_authenticated_url(self):
        resolved = SimpleNamespace(
            source_type="Provider", quality_badge="Lossless",
            source_obj=SimpleNamespace(title="Song (Live)", artist="Wrong Artist", duration_sec=240,
                                       download_url="https://private.example/?token=secret"),
        )
        summary = source_review_summary(track(), resolved)
        self.assertTrue(summary["uncertain"])
        self.assertGreaterEqual(len(summary["reasons"]), 3)
        self.assertNotIn("secret", json.dumps(summary))
        self.assertIn("live", summary["version"])

    def test_matching_source_does_not_require_approval(self):
        resolved = SimpleNamespace(source_type="Provider", quality_badge="Lossless",
                                   source_obj=SimpleNamespace(title="Song", artist="Artist", duration_sec=180))
        self.assertFalse(source_review_summary(track(), resolved)["uncertain"])

    def test_source_review_accept_reject_and_cancellation(self):
        manager = self.manager()
        manager.enqueue([track()])
        manager._running = True
        item = manager.get_items()[0]
        resolved = SimpleNamespace(source_type="Provider", quality_badge="Lossless",
                                   source_obj=SimpleNamespace(title="Different (Live)", artist="Artist"))
        manager.on_source_review_required = lambda trk, summary, decide: decide(True)
        self.assertTrue(manager._review_source(item, resolved, lambda: False))
        manager.on_source_review_required = lambda trk, summary, decide: decide(False)
        self.assertFalse(manager._review_source(item, resolved, lambda: False))
        cancelled = threading.Event()
        requested = threading.Event()
        manager.on_source_review_required = lambda *args: requested.set()
        result = []
        worker = threading.Thread(target=lambda: result.append(manager._review_source(item, resolved, cancelled.is_set)))
        worker.start()
        self.assertTrue(requested.wait(1))
        cancelled.set()
        worker.join(1)
        self.assertFalse(worker.is_alive())
        self.assertEqual(result, [False])

    def test_stage_and_actionable_error(self):
        self.assertEqual(processing_stage("Transcoding (MP3)"), "Conversion")
        self.assertEqual(processing_stage("Balancing Volume"), "Normalization")
        self.assertIn("cooldown", diagnostic_hint("HTTP 429 rate limit"))
        self.assertIn("disk", diagnostic_hint("Permission denied"))


class CooldownTests(unittest.TestCase):
    def test_deadline_extensions_never_shorten_existing_cooldown(self):
        coordinator = ProviderCooldowns()
        with patch("core.provider_cooldown.time.monotonic", return_value=10):
            coordinator.defer("provider", 10)
        with patch("core.provider_cooldown.time.monotonic", return_value=11):
            coordinator.defer("provider", 2)
            self.assertEqual(coordinator.remaining("provider"), 9)
            self.assertEqual(coordinator.remaining("unrelated"), 0)
        self.assertFalse(coordinator.wait("provider", cancel_check=lambda: True))

    def test_wait_observes_a_cooldown_extended_by_another_worker(self):
        coordinator = ProviderCooldowns()
        clock = [10.0]
        waits = []

        def wait(delay):
            waits.append(delay)
            clock[0] += delay
            if len(waits) == 1:
                coordinator.defer("provider", 0.15)

        with patch("core.provider_cooldown.time.monotonic", side_effect=lambda: clock[0]), patch.object(coordinator._waiter, "wait", side_effect=wait):
            coordinator.defer("provider", 0.1)
            self.assertTrue(coordinator.wait("provider"))
        self.assertGreaterEqual(len(waits), 3)
        self.assertGreaterEqual(clock[0], 10.25)

    def test_retry_after_is_bounded_to_finite_nonnegative_delays(self):
        self.assertEqual(retry_after_seconds("12"), 12)
        self.assertEqual(retry_after_seconds("-1"), 0)
        self.assertEqual(retry_after_seconds("inf"), 30)
        self.assertEqual(retry_after_seconds("invalid"), 30)


class MetadataAndPreviewTests(unittest.TestCase):
    def test_prefetch_bounds_workers_and_pending_jobs(self):
        client = SpotifyClient.__new__(SpotifyClient)
        client._prefetch_executor = ThreadPoolExecutor(max_workers=3)
        self.addCleanup(client._prefetch_executor.shutdown, wait=True, cancel_futures=True)
        client._prefetch_lock = threading.Lock()
        client._prefetch_futures = set()
        release = threading.Event()
        self.addCleanup(release.set)
        lock = threading.Lock()
        concurrent = [0, 0]

        def fetch(url):
            with lock:
                concurrent[0] += 1
                concurrent[1] = max(concurrent)
            release.wait(3)
            with lock:
                concurrent[0] -= 1
            return []

        client._prefetch_one = fetch
        urls = [f"https://open.spotify.com/track/{index:022d}" for index in range(120)]
        futures = client.prefetch_metadata(urls, max_items=100)
        self.assertEqual(len(futures), 100)
        self.assertEqual(client.prefetch_metadata(urls), [])
        release.set()
        for future in futures:
            future.result(timeout=3)
        self.assertLessEqual(concurrent[1], 3)

    def test_cached_public_metadata_avoids_a_network_call(self):
        client = SpotifyClient.__new__(SpotifyClient)
        client._reliability_store = Mock()
        client._reliability_store.get_metadata.return_value = [asdict(track())]
        client._resolve_with_guest = Mock(side_effect=AssertionError("No network"))
        result = client.resolve(f"spotify:track:{track().id}")
        self.assertEqual(result[0], track())
        self.assertEqual(client.last_resolution_mode, "cache")
        client._resolve_with_guest.assert_not_called()

    def test_output_preview_uses_shared_names_and_collision_policy(self):
        with tempfile.TemporaryDirectory() as directory, patch("core.output_preview.config.get", return_value=False):
            base = format_track_basename(track())
            Path(directory, base + ".mp3").write_bytes(b"existing")
            previews = preview_outputs([track(), track("B" * 22)], directory,
                                       naming_template="{artist} - {title}", target_format="mp3")
            self.assertTrue(previews[0]["path"].endswith("(2).mp3"))
            self.assertTrue(previews[1]["path"].endswith("(3).mp3"))
            self.assertEqual(next_output_path(str(Path(directory, base + ".mp3"))), previews[0]["path"])
            self.assertFalse(previews[0]["provisional"])
            self.assertEqual(Path(directory, base + ".mp3").read_bytes(), b"existing")

    def test_native_format_preview_is_explicitly_provisional(self):
        with patch("core.output_preview.config.get", return_value=False):
            result = preview_outputs([track()], "unused", naming_template="{title}", target_format="original")[0]
        self.assertTrue(result["provisional"])
        self.assertIn("determined", result["format"])

    def test_preview_uses_transcoder_extensions(self):
        for target, extension in (("alac", ".m4a"), ("mp3_320", ".mp3"), ("flac", ".flac"), ("opus", ".opus")):
            with self.subTest(target=target), patch("core.output_preview.config.get", return_value=False):
                result = preview_outputs([track()], "unused", naming_template="{title}", target_format=target)[0]
                self.assertTrue(result["path"].endswith(extension))
                self.assertFalse(result["provisional"])

    def test_unsupported_legacy_format_preview_shows_native_fallback(self):
        with patch("core.output_preview.config.get", return_value=False):
            result = preview_outputs([track()], "unused", naming_template="{title}", target_format="wav")[0]
        self.assertTrue(result["provisional"])
        self.assertIn("unsupported", result["format"].lower())


class SettingsValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.enterContext(patch.object(ConfigManager, "_instance", None))
        self.config = ConfigManager(Path(self.temp.name) / "settings.json")

    def test_invalid_settings_do_not_mutate_or_save(self):
        previous = copy.deepcopy(self.config.data)
        for key, value in (
            ("download.concurrency", True), ("download.concurrency", 0),
            ("download.target_format", "exe"), ("download.target_lufs", float("nan")),
            ("download.output_dir", "relative"), ("download.naming_template", "{invalid}"),
            ("download.proxy", "file:///private"),
        ):
            with self.subTest(key=key, value=value), self.assertRaises((TypeError, ValueError)):
                self.config.set(key, value)
        self.assertEqual(self.config.data, previous)

    def test_target_formats_match_the_transcoder(self):
        from core.transcoder import SUPPORTED_TARGET_FORMATS
        for target in SUPPORTED_TARGET_FORMATS:
            with self.subTest(target=target):
                self.config.set("download.target_format", target)
        for target in ("wav", "ogg", "m4a"):
            with self.subTest(target=target), self.assertRaises(ValueError):
                self.config.set("download.target_format", target)

    def test_batch_save_rolls_back_without_notifying_on_failure(self):
        previous = copy.deepcopy(self.config.data)
        notified = Mock()
        reported = Mock()
        self.config.add_listener(notified)
        self.config.set_error_handler(reported)
        with patch.object(self.config, "save", side_effect=OSError("disk full")), self.assertRaises(OSError):
            self.config.set_many({"source_engine": "melobot", "telegram.enabled": True, "musilon.enabled": False})
        self.assertEqual(self.config.data, previous)
        notified.assert_not_called()
        reported.assert_called_once()

    def test_batch_is_persisted_once(self):
        with patch.object(self.config, "save", wraps=self.config.save) as save:
            self.config.set_many({"download.concurrency": 2, "download.target_format": "flac"})
        save.assert_called_once()
        saved = json.loads(self.config.config_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["download"]["concurrency"], 2)
        self.assertEqual(saved["download"]["target_format"], "flac")


class ChallengeIsolationTests(unittest.TestCase):
    def setUp(self):
        self.engine = MusilonEngine.__new__(MusilonEngine)
        self.engine.session = requests.Session()
        self.addCleanup(self.engine.session.close)

    def solve(self, script):
        return self.engine._solve_arvancloud_challenge("<script>" + script + "</script>")

    def test_runtime_has_no_filesystem_network_or_process_capabilities(self):
        self.assertTrue(self.solve("if (typeof process !== 'undefined' || typeof require !== 'undefined' || typeof fetch !== 'undefined') throw Error('host capability'); document.cookie='__arcsjs=ok';"))
        self.assertEqual(self.engine.session.cookies.get("__arcsjs", domain="open.musilon.com"), "ok")
        self.assertFalse(self.solve("require('fs'); document.cookie='__arcsjs=bad';"))

    def test_infinite_loop_and_memory_exhaustion_fail_closed(self):
        start = time.monotonic()
        self.assertFalse(self.solve("var __arcsjs; while(true){}"))
        self.assertLess(time.monotonic() - start, 5)
        self.assertFalse(self.solve("var __arcsjs=[]; while(true){ __arcsjs.push('x'.repeat(100000)); }"))

    def test_oversized_script_and_missing_runtime_fail_closed(self):
        self.assertFalse(self.solve("var __arcsjs;" + " " * 33000))
        with patch.dict("sys.modules", {"quickjs": None}):
            self.assertFalse(self.solve("document.cookie='__arcsjs=ok';"))


if __name__ == "__main__":
    unittest.main()