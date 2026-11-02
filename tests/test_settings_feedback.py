import copy
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from core.config import ConfigManager
from gui.views import settings_view


class TestSettingsFeedback(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir="scratch")
        self.addCleanup(self.temporary.cleanup)
        self.config = object.__new__(ConfigManager)
        self.config.__init__(Path(self.temporary.name) / "config.json")
        self.old_data = copy.deepcopy(self.config.data)
        self.old_disk = self.config.config_path.read_bytes()
        self.engine = MagicMock()
        self.engine.enabled = True
        self.engine.username = ""
        self.engine.password = ""
        self.engine.session_cookie = ""
        self.qm = MagicMock()
        for patcher in (
            patch.object(settings_view, "config", self.config),
            patch.object(settings_view, "InfoBar"),
            patch.object(settings_view.QTimer, "singleShot"),
            patch.object(settings_view.SettingsView, "_update_ffmpeg_badge"),
            patch.object(settings_view.SettingsView, "_update_spotify_badge"),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.view = settings_view.SettingsView(self.engine, MagicMock(), self.qm)
        self.addCleanup(self.view.deleteLater)

    def assert_unchanged(self):
        self.assertEqual(self.config.data, self.old_data)
        self.assertEqual(self.config.config_path.read_bytes(), self.old_disk)
        settings_view.InfoBar.success.assert_not_called()
        settings_view.InfoBar.info.assert_not_called()
        settings_view.InfoBar.warning.assert_not_called()
        settings_view.InfoBar.error.assert_called()
        self.assertIn("Previous settings are still active", self.view.save_status_label.text())

    def test_concurrency_save_failure_keeps_runtime(self):
        with patch.object(self.config, "save", side_effect=OSError("disk full")):
            self.view._on_concurrency_changed(7)
        self.qm.update_concurrency.assert_not_called()
        self.assert_unchanged()

    def test_cookie_validation_failure_keeps_runtime(self):
        with patch.object(self.config, "set_many", side_effect=ValueError("invalid credentials")):
            self.view._on_cookie_changed("new cookie")
        self.engine.set_credentials.assert_not_called()
        self.assert_unchanged()

    def test_source_selection_is_one_atomic_save(self):
        with patch.object(self.config, "save", wraps=self.config.save) as save:
            self.view._on_source_engine_changed(1)
        self.assertEqual(save.call_count, 1)
        self.assertEqual(self.config.get("source_engine"), "melobot")
        self.assertFalse(self.config.get("musilon.enabled"))
        self.assertTrue(self.config.get("telegram.enabled"))
        self.assertFalse(self.engine.enabled)
        self.assertTrue(self.view.melobot_switch.isChecked())
        self.qm.update_concurrency.assert_called_once_with(1)

    def test_source_failure_is_atomic(self):
        with patch.object(self.config, "save", side_effect=OSError("read only")):
            self.view._on_source_engine_changed(1)
        self.assertTrue(self.engine.enabled)
        self.qm.update_concurrency.assert_not_called()
        self.assert_unchanged()

    def test_lyrics_batch_failure(self):
        with patch.object(self.config, "save", side_effect=OSError("read only")):
            self.view._on_lyrics_mode_changed(2)
        self.assert_unchanged()

    def test_widget_signal_failures_restore_controls_without_recursion(self):
        changes = (
            (self.view.source_combo, "setCurrentIndex", 1, "currentIndex", 0),
            (self.view.melobot_switch, "setChecked", True, "isChecked", False),
            (self.view.musilon_switch, "setChecked", False, "isChecked", True),
            (self.view.safe_mode_switch, "setChecked", False, "isChecked", True),
            (self.view.subfolder_switch, "setChecked", True, "isChecked", False),
            (self.view.fallback_switch, "setChecked", False, "isChecked", True),
            (self.view.embed_switch, "setChecked", False, "isChecked", True),
            (self.view.art_switch, "setChecked", False, "isChecked", True),
            (self.view.m3u_switch, "setChecked", False, "isChecked", True),
            (self.view.norm_vol_switch, "setChecked", False, "isChecked", True),
            (self.view.rg_switch, "setChecked", True, "isChecked", False),
            (self.view.concurrency_spin, "setValue", 7, "value", 5),
            (self.view.cooldown_min_spin, "setValue", 20, "value", 15),
            (self.view.cooldown_max_spin, "setValue", 40, "value", 35),
            (self.view.tg_delay_spin, "setValue", 3, "value", 0),
            (self.view.quality_combo, "setCurrentIndex", 1, "currentIndex", 0),
            (self.view.target_fmt_combo, "setCurrentIndex", 3, "currentIndex", 0),
            (self.view.lyrics_combo, "setCurrentIndex", 2, "currentIndex", 0),
        )
        for widget, setter, value, getter, previous in changes:
            with self.subTest(widget=widget, value=value):
                settings_view.InfoBar.reset_mock()
                with patch.object(self.config, "save", side_effect=OSError("disk full")) as save:
                    getattr(widget, setter)(value)
                save.assert_called_once()
                self.assertEqual(getattr(widget, getter)(), previous)
                self.assert_unchanged()
        self.qm.update_concurrency.assert_not_called()
        self.assertTrue(self.engine.enabled)

    def test_text_fields_save_only_complete_edits(self):
        fields = (
            (self.view.folder_input, "download.output_dir", str(Path(self.temporary.name).resolve())),
            (self.view.naming_input, "download.naming_template", "{album} - {title}"),
            (self.view.album_naming_input, "download.album_naming_template", "{title}"),
            (self.view.proxy_input, "download.proxy", "http://127.0.0.1:1080"),
            (self.view.yt_cookie_input, "download.cookies_file", "test-cookies.txt"),
        )
        for widget, key, value in fields:
            with self.subTest(key=key):
                with patch.object(self.config, "save", wraps=self.config.save) as save:
                    widget.setText(value)
                    save.assert_not_called()
                    widget.editingFinished.emit()
                save.assert_called_once()
                self.assertEqual(self.config.get(key), value)
                self.assertIn("Saved:", self.view.save_status_label.text())

    def test_text_validation_errors_restore_previous_values(self):
        fields = (
            (self.view.folder_input, "download.output_dir", ""),
            (self.view.naming_input, "download.naming_template", "{unfinished"),
            (self.view.album_naming_input, "download.album_naming_template", "{unknown}"),
            (self.view.proxy_input, "download.proxy", "not a proxy"),
        )
        for widget, key, invalid in fields:
            with self.subTest(key=key):
                settings_view.InfoBar.reset_mock()
                previous = self.config.get(key)
                widget.setText(invalid)
                widget.editingFinished.emit()
                self.assertEqual(widget.text(), previous)
                self.assertIn("Correct the value", self.view.save_status_label.text())
                self.assert_unchanged()

    def test_numeric_validation_does_not_mutate_queue(self):
        self.view._on_concurrency_changed(0)
        self.qm.update_concurrency.assert_not_called()
        self.assert_unchanged()

    def test_credential_edits_are_atomic(self):
        self.view.user_input.setText("person@example.test")
        self.view.pwd_input.setText("test password")
        self.view.cookie_input.setText("test cookie")
        with patch.object(self.config, "save", wraps=self.config.save) as save:
            self.view.user_input.editingFinished.emit()
        save.assert_called_once()
        self.engine.set_credentials.assert_called_once_with(
            session_cookie="test cookie", username="person@example.test",
            password="test password", enabled=True,
        )
        self.assertEqual(self.config.get("musilon.password"), "test password")
        self.assertNotIn("test password", self.view.save_status_label.text())

    def test_spotify_credentials_failure_aborts_authorization(self):
        self.view.spotify_id.setText("test id")
        self.view.spotify_secret.setText("test secret")
        with patch.object(self.config, "save", side_effect=OSError("disk full")) as save:
            with patch.object(settings_view, "SpotifyClient") as client:
                self.view._authorize_spotify()
        save.assert_called_once()
        client.assert_not_called()
        self.assertEqual(self.view.spotify_id.text(), "")
        self.assertEqual(self.view.spotify_secret.text(), "")
        self.assert_unchanged()

    def test_browse_failure_has_no_success_feedback(self):
        for action, dialog, result in (
            (self.view._browse_folder, "getExistingDirectory", str(Path(self.temporary.name).resolve())),
            (self.view._browse_cookies_file, "getOpenFileName", ("test-cookies.txt", "")),
        ):
            with self.subTest(action=action):
                settings_view.InfoBar.reset_mock()
                with patch.object(settings_view.QFileDialog, dialog, return_value=result):
                    with patch.object(self.config, "save", side_effect=OSError("read only")) as save:
                        action()
                save.assert_called_once()
                self.assert_unchanged()

    def test_login_failure_aborts_before_runtime_or_worker_changes(self):
        self.view.user_input.setText("person@example.test")
        self.view.pwd_input.setText("test password")
        with patch.object(self.config, "save", side_effect=OSError("disk full")):
            with patch.object(settings_view.threading, "Thread") as thread:
                self.view._login_musilon()
        thread.assert_not_called()
        self.engine.set_credentials.assert_not_called()
        self.assert_unchanged()

    def test_login_result_save_failure_restores_runtime(self):
        self.view._login_runtime_state = {
            "session_cookie": "old runtime cookie", "username": "old runtime user",
            "password": "old runtime password", "enabled": True, "cookies": "old cookie jar",
        }
        self.engine.session.cookies.get_dict.return_value = {"session": "new token"}
        with patch.object(self.config, "save", side_effect=OSError("disk full")):
            with patch.object(self.view, "_test_musilon") as test_connection:
                self.view.sig_login_result.emit(True, "Authenticated")
        test_connection.assert_not_called()
        self.engine.set_credentials.assert_not_called()
        self.assertEqual(self.engine.session_cookie, "old runtime cookie")
        self.assertEqual(self.engine.username, "old runtime user")
        self.assertEqual(self.engine.password, "old runtime password")
        self.assertEqual(self.engine.session.cookies, "old cookie jar")
        self.assertIn("not saved", self.view.result_label.text())
        self.assert_unchanged()

    def test_batch_actions_save_once(self):
        for action in (
            lambda: self.view._on_melobot_switch_changed(True),
            lambda: self.view._on_musilon_switch_changed(True),
            lambda: self.view._on_quality_changed(1),
            lambda: self.view._on_lyrics_mode_changed(2),
        ):
            with self.subTest(action=action):
                with patch.object(self.config, "save", wraps=self.config.save) as save:
                    action()
                save.assert_called_once()

    def test_credential_signal_validation_failures_do_not_update_badges(self):
        for field in (self.view.user_input, self.view.pwd_input, self.view.cookie_input,
                      self.view.spotify_id, self.view.spotify_secret):
            with self.subTest(field=field):
                settings_view.InfoBar.reset_mock()
                field.setText("test credential")
                with patch.object(self.config, "set_many", side_effect=ValueError("invalid credentials")):
                    with patch.object(self.view, "_update_status_badge") as musilon_badge:
                        with patch.object(self.view, "_update_spotify_badge") as spotify_badge:
                            field.editingFinished.emit()
                musilon_badge.assert_not_called()
                spotify_badge.assert_not_called()
                self.engine.set_credentials.assert_not_called()
                self.assertEqual(field.text(), "")
                self.assert_unchanged()

    def test_telegram_logout_failure_has_no_false_success(self):
        for raises in (False, True):
            with self.subTest(raises=raises):
                settings_view.InfoBar.reset_mock()
                self.view.tg_status_badge.setText("Connected")
                self.view.melobot_engine.log_out.side_effect = OSError("disk full") if raises else None
                self.view.melobot_engine.log_out.return_value = False
                with patch.object(settings_view.threading, "Thread") as thread:
                    thread.return_value.start.side_effect = lambda: thread.call_args.kwargs["target"]()
                    self.view._logout_telegram()
                self.assertEqual(self.view.tg_status_badge.text(), "Connected")
                settings_view.InfoBar.info.assert_not_called()
                settings_view.InfoBar.success.assert_not_called()
                settings_view.InfoBar.error.assert_called_once()
                self.assertIn("permissions", self.view.save_status_label.text())


if __name__ == "__main__":
    unittest.main()