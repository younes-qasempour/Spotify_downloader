import json
import os
import tempfile
import threading
import time
import unittest
from concurrent.futures import Future
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication

from core.spotify_client import TrackMetadata
from gui.views import reliability_view


PUBLIC_URL = "https://open.spotify.com/track/" + "A" * 22


class ReliabilityViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.main_thread = threading.get_ident()
        self.worker_threads = []
        self.track = TrackMetadata("track-1", "Song", ["Artist"], "Album")
        self.item = SimpleNamespace(track=self.track, status="Stopped", stage="resolution",
                                    error_message="Interrupted https://private.test/audio?token=secret")
        self.queue = Mock()
        self.queue.get_items.return_value = [self.item]
        self.queue.retry_track.return_value = True
        self.queue.retry_failed.return_value = 1
        self.archive = Mock()
        self.path = str(self.directory / "archived.flac")
        self.keeper = str(self.directory / "keeper.flac")
        self.archive.get_track_by_path.return_value = {
            "spotify_id": "track-1", "title": "Song", "artist": "Artist; Guest",
            "album": "Album", "file_path": self.path, "track_number": 2, "genre": "Rock; Pop",
        }
        self.repair = Mock()
        self.repair.list_history.return_value = []
        self.repair.preview_retag.return_value = {"action": "retag", "can_apply": True, "original_hash": "one"}
        self.repair.preview_duplicate.return_value = {"action": "duplicate", "can_apply": True, "original_hash": "one"}
        self.repair.apply_retag.return_value = "repair-1"
        self.repair.apply_duplicate.return_value = "repair-2"
        self.settings = {"download.output_dir": str(self.directory)}
        self.config = Mock()
        self.config.get.side_effect = lambda key, default=None: self.settings.get(key, default)
        self.client = Mock()
        self.client.prefetch_metadata.return_value = [self.future([self.track])]
        self.candidate = {"directory": str(self.directory / "staging"), "track_id": "track-1",
                          "state": "ready", "publication_interrupted": True}
        self.staging_scan = Mock(return_value=[self.candidate])
        self.staging_recover = Mock(return_value=self.path)
        self.staging_discard = Mock()
        for name, value in (("config", self.config), ("LibraryRepairManager", Mock(return_value=self.repair)),
                            ("SpotifyClient", Mock(return_value=self.client)),
                            ("scan_abandoned_staging", self.staging_scan),
                            ("recover_staging", self.staging_recover),
                            ("discard_staging", self.staging_discard)):
            patcher = patch.object(reliability_view, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.view = reliability_view.ReliabilityView(self.queue, self.archive)
        self.addCleanup(self.destroy_view)
        self.wait_idle()

    def destroy_view(self):
        self.wait_idle()
        self.view.close()
        self.view.deleteLater()
        self.app.processEvents()

    @staticmethod
    def future(result=None, error=None):
        future = Future()
        if error:
            future.set_exception(error)
        else:
            future.set_result(result)
        return future

    def wait_for(self, predicate):
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            self.app.processEvents()
            if predicate():
                return
            time.sleep(0.002)
        self.fail("Background GUI work did not finish")

    def wait_idle(self):
        self.wait_for(lambda: not self.view._jobs)

    def assert_worker(self):
        self.worker_threads.append(threading.get_ident())
        self.assertNotEqual(threading.get_ident(), self.main_thread)

    def preview_retag(self):
        self.view.retag_path.setText(self.path)
        self.view.preview_repair("retag")
        self.wait_idle()

    def preview_duplicate(self):
        self.view.duplicate_path.setText(self.path)
        self.view.keeper_path.setText(self.keeper)
        self.view.preview_repair("duplicate")
        self.wait_idle()

    def test_recovery_diagnostics_do_not_start_or_retry(self):
        self.assertEqual(self.view.queue_table.rowCount(), 1)
        self.assertEqual(self.view.queue_table.item(0, 2).text(), "Stopped")
        self.assertEqual(self.view.queue_table.item(0, 3).text(), "resolution")
        self.assertNotIn("private.test", self.view.queue_table.item(0, 4).text())
        self.assertNotIn("secret", self.view.queue_table.item(0, 4).text())
        self.queue.start_all.assert_not_called()
        self.queue.retry_track.assert_not_called()
        self.queue.retry_failed.assert_not_called()
        self.queue.enqueue.assert_not_called()

    def test_completed_items_excluded_and_stage_falls_back_to_status(self):
        completed = SimpleNamespace(track=self.track, status="Completed")
        self.queue.get_items.return_value = [completed, SimpleNamespace(track=self.track, status="Failed")]
        self.view.refresh_queue()
        self.wait_idle()
        self.assertEqual(self.view.queue_table.rowCount(), 1)
        self.assertEqual(self.view.queue_table.item(0, 3).text(), "Failed")

    def test_explicit_retry_selected_and_failed(self):
        self.view.retry_selected()
        self.queue.retry_track.assert_not_called()
        self.view.queue_table.selectRow(0)
        self.view.retry_selected()
        self.wait_idle()
        self.queue.retry_track.assert_called_once_with("track-1")
        self.view.retry_failed()
        self.wait_idle()
        self.queue.retry_failed.assert_called_once_with()

    def test_output_preview_uses_shared_api_without_mutation(self):
        rows = [{"title": "Song", "path": str(self.directory / "Song.<native>"),
                 "format": "Native", "provisional": True, "collision_detected": True,
                 "collision_policy": "Keep existing files"}]

        def preview(tracks, output_dir):
            self.assert_worker()
            self.assertEqual(tracks, [self.track])
            self.assertEqual(output_dir, str(self.directory))
            return rows

        with patch.object(reliability_view, "preview_outputs", side_effect=preview):
            self.view.preview_queue_outputs()
            self.wait_idle()
        self.assertEqual(json.loads(self.view.output_preview.toPlainText()), rows)
        self.assertEqual(list(self.directory.iterdir()), [])
        self.queue.start_all.assert_not_called()

    def test_review_defaults_true_and_saves_off_thread(self):
        self.assertTrue(self.view.review_toggle.isChecked())
        self.config.set.side_effect = lambda *args: self.assert_worker()
        self.view.review_toggle.setChecked(False)
        self.wait_idle()
        self.config.set.assert_called_once_with("download.review_uncertain_matches", False)
        self.assertIn("saved", self.view.status_label.text())

    def test_review_save_error_restores_toggle_and_does_not_claim_success(self):
        self.config.set.side_effect = OSError("Disk is read-only")
        self.view.review_toggle.setChecked(False)
        self.wait_idle()
        self.assertTrue(self.view.review_toggle.isChecked())
        self.assertIn("failed", self.view.status_label.text())
        self.assertNotIn("saved", self.view.status_label.text())
        self.assertTrue(self.view.review_toggle.isEnabled())

    def test_prefetch_is_bounded_background_and_explicit_enqueue_only(self):
        tracks = [TrackMetadata(str(i), f"Song {i}", ["Artist"], "Album") for i in range(30)]

        def fetch(urls, max_items):
            self.assert_worker()
            self.assertEqual(urls, [PUBLIC_URL])
            self.assertEqual(max_items, 24)
            return [self.future(tracks)]

        self.client.prefetch_metadata.side_effect = fetch
        self.client.close.side_effect = self.assert_worker
        self.view.url_input.setPlainText(PUBLIC_URL + "?si=tracking")
        self.view.prefetch_metadata()
        self.wait_idle()
        self.assertEqual(self.view.metadata_table.rowCount(), 24)
        self.client.close.assert_called_once_with()
        self.queue.enqueue.assert_not_called()
        self.queue.start_all.assert_not_called()
        self.assertTrue(self.view.enqueue_button.isEnabled())
        self.view.enqueue_metadata()
        self.wait_idle()
        self.assertEqual(len(self.queue.enqueue.call_args.args[0]), 24)
        self.queue.start_all.assert_not_called()
        self.assertFalse(self.view.enqueue_button.isEnabled())

    def test_prefetch_uses_configured_spotify_credentials(self):
        self.settings["spotify.client_id"] = "test-client"
        self.settings["spotify.client_secret"] = "test-secret"
        self.view.url_input.setPlainText(PUBLIC_URL)
        self.view.prefetch_metadata()
        self.wait_idle()
        reliability_view.SpotifyClient.assert_called_once_with(
            client_id="test-client", client_secret="test-secret"
        )

    def test_invalid_urls_and_excess_input_never_construct_client(self):
        for url in ("", "https://evil.test/track/" + "A" * 22,
                    PUBLIC_URL.replace("/track/", "/playlist/"),
                    PUBLIC_URL.replace("https://", "https://user:password@"),
                    PUBLIC_URL.replace("https://", "http://"), "\n".join([PUBLIC_URL] * 25)):
            with self.subTest(url=url):
                self.view.url_input.setPlainText(url)
                self.view.prefetch_metadata()
                reliability_view.SpotifyClient.assert_not_called()
                self.assertFalse(self.view.enqueue_button.isEnabled())

    def test_prefetch_error_closes_client_and_hides_authenticated_url(self):
        self.client.prefetch_metadata.return_value = [self.future(error=ValueError(
            "Failed https://user:password@source.test/file?token=verysecret"))]
        self.view.url_input.setPlainText(PUBLIC_URL)
        self.view.prefetch_metadata()
        self.wait_idle()
        self.client.close.assert_called_once_with()
        self.assertIn("failed", self.view.status_label.text())
        self.assertNotIn("verysecret", self.view.status_label.text())
        self.assertNotIn("source.test", self.view.status_label.text())
        self.assertFalse(self.view.enqueue_button.isEnabled())

    def test_prefetch_stale_result_ignored_and_gui_remains_responsive(self):
        future = Future()
        self.client.prefetch_metadata.return_value = [future]
        self.view.url_input.setPlainText(PUBLIC_URL)
        self.view.prefetch_metadata()
        ticks = []
        QTimer.singleShot(0, lambda: ticks.append(True))
        self.wait_for(lambda: bool(ticks))
        self.assertIn("prefetch", self.view._jobs)
        self.view.url_input.setPlainText(PUBLIC_URL.replace("/track/", "/album/"))
        future.set_result([self.track])
        self.wait_idle()
        self.assertEqual(self.view.metadata_table.rowCount(), 0)
        self.assertFalse(self.view.enqueue_button.isEnabled())
        self.client.close.assert_called_once_with()

    def test_metadata_input_edit_invalidates_enqueue_and_enqueue_error_preserves_preview(self):
        self.view.url_input.setPlainText(PUBLIC_URL)
        self.view.prefetch_metadata()
        self.wait_idle()
        self.queue.enqueue.side_effect = ValueError("Queue unavailable")
        self.view.enqueue_metadata()
        self.wait_idle()
        self.assertIn("failed", self.view.status_label.text())
        self.assertTrue(self.view.enqueue_button.isEnabled())
        self.view.url_input.setPlainText("")
        self.assertFalse(self.view.enqueue_button.isEnabled())

    def test_retag_requires_preview_uses_archive_metadata_and_explicit_apply(self):
        self.view.apply_repair("retag")
        self.repair.apply_retag.assert_not_called()
        self.preview_retag()
        self.assertTrue(self.view.retag_apply_button.isEnabled())
        self.repair.apply_retag.assert_not_called()
        path, metadata = self.repair.preview_retag.call_args.args
        self.assertEqual(path, self.path)
        self.assertEqual(metadata.artists, ["Artist", "Guest"])
        self.assertEqual(metadata.track_number, 2)
        self.assertEqual(metadata.genres, ["Rock", "Pop"])
        self.view.apply_repair("retag")
        self.wait_idle()
        self.repair.apply_retag.assert_called_once_with(self.path, metadata)
        self.assertFalse(self.view.retag_apply_button.isEnabled())
        self.assertIn("applied", self.view.status_label.text())

    def test_archive_missing_or_wrong_path_is_rejected(self):
        for record in (None, {"title": "Other", "artist": "Artist", "file_path": self.keeper}):
            self.archive.get_track_by_path.return_value = record
            self.preview_retag()
            self.assertFalse(self.view.retag_apply_button.isEnabled())
            self.assertIn("failed", self.view.status_label.text())
        self.repair.preview_retag.assert_not_called()

    def test_changed_input_and_changed_file_invalidate_apply(self):
        self.preview_retag()
        self.view.retag_path.setText(self.keeper)
        self.view.retag_path.setText(self.path)
        self.assertFalse(self.view.retag_apply_button.isEnabled())
        self.view.apply_repair("retag")
        self.repair.apply_retag.assert_not_called()
        self.preview_retag()
        self.repair.preview_retag.return_value = {"can_apply": True, "original_hash": "changed"}
        self.view.apply_repair("retag")
        self.wait_idle()
        self.repair.apply_retag.assert_not_called()
        self.assertIn("changed since preview", self.view.status_label.text())
        self.assertFalse(self.view.retag_apply_button.isEnabled())

    def test_stale_repair_preview_is_ignored_and_hashing_is_off_thread(self):
        started, release = threading.Event(), threading.Event()

        def preview(*args):
            self.assert_worker()
            started.set()
            if not release.wait(3):
                raise TimeoutError("Test preview not released")
            return {"can_apply": True}

        self.repair.preview_retag.side_effect = preview
        self.view.retag_path.setText(self.path)
        self.view.preview_repair("retag")
        self.wait_for(started.is_set)
        self.view.retag_path.setText(self.keeper)
        release.set()
        self.wait_idle()
        self.assertFalse(self.view.retag_apply_button.isEnabled())
        self.assertEqual(self.view.retag_preview.toPlainText(), "")

    def test_duplicate_preview_apply_and_keeper_change(self):
        self.preview_duplicate()
        self.assertTrue(self.view.duplicate_apply_button.isEnabled())
        self.repair.apply_duplicate.assert_not_called()
        self.view.keeper_path.setText(self.path)
        self.assertFalse(self.view.duplicate_apply_button.isEnabled())
        self.preview_duplicate()
        self.repair.apply_duplicate.side_effect = lambda *args: (self.assert_worker() or "repair-2")
        self.view.apply_repair("duplicate")
        self.wait_idle()
        self.repair.apply_duplicate.assert_called_once_with(self.path, self.keeper)
        self.assertFalse(self.view.duplicate_apply_button.isEnabled())

    def test_repair_preview_refusal_and_apply_error(self):
        self.repair.preview_duplicate.return_value = {"can_apply": False, "reason": "Different bytes"}
        self.preview_duplicate()
        self.assertFalse(self.view.duplicate_apply_button.isEnabled())
        self.view.apply_repair("duplicate")
        self.repair.apply_duplicate.assert_not_called()
        self.repair.preview_duplicate.side_effect = ValueError("Not byte-identical")
        self.preview_duplicate()
        self.assertIn("failed", self.view.status_label.text())
        self.preview_retag()
        self.repair.apply_retag.side_effect = OSError("Backup failed")
        self.view.apply_repair("retag")
        self.wait_idle()
        self.assertIn("failed", self.view.status_label.text())
        self.assertNotIn("applied", self.view.status_label.text())
        self.assertFalse(self.view.retag_apply_button.isEnabled())

    def test_history_and_undo_are_background_and_explicit(self):
        def history():
            self.assert_worker()
            return [{"id": "repair-1", "action": "retag", "file_path": self.path, "state": "applied"}]

        self.repair.list_history.side_effect = history
        self.repair.undo.side_effect = lambda *args: self.assert_worker()
        self.view.refresh_history()
        self.wait_idle()
        self.assertEqual(self.view.history_table.item(0, 2).text(), self.path)
        self.repair.undo.assert_not_called()
        self.view.history_table.selectRow(0)
        self.view.undo_selected()
        self.wait_idle()
        self.repair.undo.assert_called_once_with("repair-1")
        self.assertIn("undone", self.view.status_label.text())

    def test_history_and_undo_errors_do_not_claim_success(self):
        self.repair.list_history.return_value = [{"id": "repair-1", "state": "applied"}]
        self.view.refresh_history()
        self.wait_idle()
        self.view.history_table.selectRow(0)
        self.repair.undo.side_effect = ValueError("File changed")
        self.view.undo_selected()
        self.wait_idle()
        self.assertIn("failed", self.view.status_label.text())
        self.assertNotIn("undone", self.view.status_label.text())
        self.repair.list_history.side_effect = OSError("History unavailable")
        self.view.refresh_history()
        self.wait_idle()
        self.assertIn("History failed", self.view.status_label.text())

    def test_file_chooser_and_json_redaction(self):
        with patch.object(reliability_view.QFileDialog, "getOpenFileName", return_value=(self.path, "")):
            self.view._choose_file(self.view.retag_path)
        self.assertEqual(self.view.retag_path.text(), self.path)
        self.view._show_json(self.view.retag_preview, {
            "metadata": {"client_secret": "verysecret", "source_url": "https://private.test/token"},
            "note": "https://private.test/file?token=verysecret",
        })
        text = self.view.retag_preview.toPlainText()
        self.assertNotIn("verysecret", text)
        self.assertNotIn("private.test", text)

    def test_diagnostic_redaction_hides_entire_authorization_and_cookie_values(self):
        self.view._message("Request failed: Authorization: Bearer verysecret\nCookie: session=private; auth=hidden")
        text = self.view.status_label.text()
        self.assertNotIn("verysecret", text)
        self.assertNotIn("session=private", text)
        self.assertNotIn("auth=hidden", text)

    def test_history_refresh_requested_during_load_is_not_lost(self):
        started, release = threading.Event(), threading.Event()
        calls = []

        def history():
            calls.append(True)
            if len(calls) == 1:
                started.set()
                if not release.wait(3):
                    raise TimeoutError("Test history not released")
                return []
            return [{"id": "latest", "action": "duplicate", "state": "applied"}]

        self.repair.list_history.side_effect = history
        self.view.refresh_history()
        self.wait_for(started.is_set)
        self.view.refresh_history()
        release.set()
        self.wait_idle()
        self.assertEqual(len(calls), 2)
        self.assertEqual(self.view.history_table.item(0, 0).text(), "latest")

    def test_apply_invalidates_other_repair_preview_even_when_apply_fails(self):
        self.preview_retag()
        self.preview_duplicate()
        self.assertTrue(self.view.retag_apply_button.isEnabled())
        self.assertTrue(self.view.duplicate_apply_button.isEnabled())
        self.repair.apply_retag.side_effect = OSError("Publication failed")
        self.view.apply_repair("retag")
        self.wait_idle()
        self.assertFalse(self.view.retag_apply_button.isEnabled())
        self.assertFalse(self.view.duplicate_apply_button.isEnabled())

    def scan_and_select_staging(self):
        self.view.scan_staging()
        self.wait_idle()
        self.view.staging_table.selectRow(0)

    def test_staging_scan_is_manual_background_and_displays_module_candidates(self):
        self.staging_scan.assert_not_called()

        def scan(root):
            self.assert_worker()
            self.assertEqual(root, str(self.directory))
            return [self.candidate, {"directory": "partial", "track_id": "other", "state": "invalid",
                                     "error": "Bad manifest https://private.test/?token=secret"}]

        self.staging_scan.side_effect = scan
        self.view.scan_staging()
        self.wait_idle()
        self.assertEqual(self.view.staging_table.rowCount(), 2)
        self.assertEqual(self.view.staging_table.item(0, 0).text(), self.candidate["directory"])
        self.assertEqual(self.view.staging_table.item(0, 1).text(), "track-1")
        self.assertEqual(self.view.staging_table.item(0, 2).text(), "ready")
        self.assertNotIn("private.test", self.view.staging_table.item(1, 3).text())
        self.staging_recover.assert_not_called()
        self.staging_discard.assert_not_called()

    def test_recover_ready_registers_candidate_track_off_thread_without_starting(self):
        self.scan_and_select_staging()
        self.staging_recover.side_effect = lambda directory: (self.assert_worker() or self.path)
        self.queue.complete_recovered_track.side_effect = lambda *args: (self.assert_worker() or True)
        self.view.recover_selected_staging()
        self.wait_idle()
        self.staging_recover.assert_called_once_with(self.candidate["directory"])
        self.queue.complete_recovered_track.assert_called_once_with("track-1", self.path)
        self.assertIn("Queued track completed", self.view.status_label.text())
        self.assertEqual(self.staging_scan.call_count, 2)
        self.queue.start_all.assert_not_called()
        self.queue.retry_track.assert_not_called()

    def test_recover_unknown_track_reports_success_and_library_scan(self):
        self.scan_and_select_staging()
        self.queue.complete_recovered_track.return_value = False
        self.view.recover_selected_staging()
        self.wait_idle()
        self.assertIn("File recovered", self.view.status_label.text())
        self.assertIn("library scan can index it", self.view.status_label.text())
        self.assertNotIn("Queued track completed", self.view.status_label.text())

    def test_registration_error_does_not_hide_successful_file_recovery(self):
        self.scan_and_select_staging()
        self.queue.complete_recovered_track.side_effect = OSError("Archive unavailable")
        self.view.recover_selected_staging()
        self.wait_idle()
        self.assertIn("File recovered", self.view.status_label.text())
        self.assertIn("library scan can index it", self.view.status_label.text())
        self.assertIn("registration failed", self.view.status_label.text())

    def test_recover_requires_selection_and_ready_state(self):
        self.view.recover_selected_staging()
        self.assertIn("Select one", self.view.status_label.text())
        for state in ("incomplete", "invalid"):
            self.candidate["state"] = state
            self.scan_and_select_staging()
            self.view.recover_selected_staging()
            self.assertIn("Only ready", self.view.status_label.text())
        self.staging_recover.assert_not_called()

    def test_active_staging_recovery_refusal_does_not_register_or_claim_success(self):
        self.scan_and_select_staging()

        def refuse(directory):
            self.assert_worker()
            raise ValueError("Active leased directory refused")

        self.staging_recover.side_effect = refuse
        self.view.recover_selected_staging()
        self.wait_idle()
        self.assertIn("Active leased directory refused", self.view.status_label.text())
        self.assertNotIn("File recovered", self.view.status_label.text())
        self.queue.complete_recovered_track.assert_not_called()
        self.assertTrue(self.view.staging_recover_button.isEnabled())

    def test_discard_requires_confirmation_and_runs_off_thread(self):
        self.scan_and_select_staging()
        buttons = reliability_view.QMessageBox.StandardButton
        with patch.object(reliability_view.QMessageBox, "question", return_value=buttons.No) as question:
            self.view.discard_selected_staging()
            self.assertEqual(question.call_args.args[-1], buttons.No)
        self.staging_discard.assert_not_called()
        self.staging_discard.side_effect = lambda directory: self.assert_worker()
        with patch.object(reliability_view.QMessageBox, "question", return_value=buttons.Yes):
            self.view.discard_selected_staging()
            self.wait_idle()
        self.staging_discard.assert_called_once_with(self.candidate["directory"])
        self.assertIn("discarded", self.view.status_label.text())
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_active_discard_refusal_and_scan_errors_are_displayed(self):
        self.scan_and_select_staging()
        self.staging_discard.side_effect = ValueError("Active leased directory refused")
        with patch.object(reliability_view.QMessageBox, "question",
                          return_value=reliability_view.QMessageBox.StandardButton.Yes):
            self.view.discard_selected_staging()
            self.wait_idle()
        self.assertIn("refused", self.view.status_label.text())
        self.assertNotIn("discarded", self.view.status_label.text())
        self.staging_scan.side_effect = OSError("Scan unavailable")
        self.view.scan_staging()
        self.wait_idle()
        self.assertIn("Scan unavailable", self.view.status_label.text())
        self.assertTrue(self.view.staging_scan_button.isEnabled())

    def test_live_diagnostics_refresh_only_while_visible_without_heavy_scans(self):
        self.assertFalse(self.view._diagnostics_timer.isActive())
        self.assertEqual(self.view._diagnostics_timer.interval(), 1000)
        self.view.show()
        self.wait_idle()
        self.assertTrue(self.view._diagnostics_timer.isActive())
        self.view.queue_table.selectRow(0)
        self.item.stage = "publication"
        self.item.diagnostic_hint = "Check disk space https://private.test/?token=secret"
        calls = self.queue.get_items.call_count
        history_calls = self.repair.list_history.call_count
        self.wait_for(lambda: self.queue.get_items.call_count > calls)
        self.wait_idle()
        self.assertEqual(self.view.queue_table.item(0, 3).text(), "publication")
        self.assertIn("Check disk space", self.view.queue_table.item(0, 5).text())
        self.assertNotIn("private.test", self.view.queue_table.item(0, 5).text())
        self.assertEqual(self.view._selected_rows(self.view.queue_table), [0])
        self.view.hide()
        self.assertFalse(self.view._diagnostics_timer.isActive())
        self.assertEqual(self.repair.list_history.call_count, history_calls)
        self.staging_scan.assert_not_called()
        self.client.prefetch_metadata.assert_not_called()


if __name__ == "__main__":
    unittest.main()