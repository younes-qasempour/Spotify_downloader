"""Explicit recovery, metadata staging and reversible library repairs."""
import copy
import json
import os
import re
import threading
from urllib.parse import urlsplit

from PyQt6.QtCore import QObject, Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView, QFileDialog, QHBoxLayout, QHeaderView, QPlainTextEdit,
    QMessageBox, QTabWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)
from qfluentwidgets import (
    CheckBox, LineEdit, PrimaryPushButton, PushButton, SubtitleLabel, TableWidget,
    BodyLabel,
)

from core.config import config
from core.library_repair import LibraryRepairManager
from core.output_preview import preview_outputs
from core.spotify_client import SpotifyClient, TrackMetadata
from core.staging_recovery import scan_abandoned_staging, recover_staging, discard_staging


def _safe_text(value):
    text = str(value)
    text = re.sub(r"(?:https?://|spotify:)[^\s\"'<>]+", "[URL hidden]", text, flags=re.I)
    text = re.sub(
        r"\b(authorization|bearer|password|token|cookie|client_secret|api_hash)\b[\"']?[\t :=]+[^\r\n]*",
        r"\1 [hidden]", text, flags=re.I,
    )
    return text


def _safe_data(value):
    if isinstance(value, dict):
        return {
            key: "[hidden]" if any(part in str(key).lower() for part in (
                "secret", "token", "cookie", "password", "authorization", "api_hash", "url",
            )) else _safe_data(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_safe_data(item) for item in value]
    return _safe_text(value) if isinstance(value, str) else value


class _Results(QObject):
    finished = pyqtSignal(str, object, object)


class ReliabilityView(QWidget):
    """Stage metadata without calling Start; retries explicitly use the queue's retry API."""

    MAX_PREFETCH_ITEMS = 24

    def __init__(self, queue_manager, archive_manager, parent=None):
        super().__init__(parent)
        self.setObjectName("reliabilityView")
        self.queue_manager = queue_manager
        self.archive_manager = archive_manager
        self._signals = _Results(self)
        self._signals.finished.connect(self._finished)
        self._jobs = {}
        self._repair_lock = threading.Lock()
        self._repair_manager = None
        self._previews = {"retag": None, "duplicate": None}
        self._revision = {"retag": 0, "duplicate": 0, "metadata": 0}
        self._metadata = []
        self._queue_rows = []
        self._history_rows = []
        self._staging_rows = []
        self._history_refresh_pending = False
        self._review_saved = bool(config.get("download.review_uncertain_matches", True))
        self._build_ui()
        self._diagnostics_timer = QTimer(self)
        self._diagnostics_timer.setInterval(1000)
        self._diagnostics_timer.timeout.connect(self.refresh_queue)
        self.refresh()

    def _on_back_to_studio(self):
        win = self.window()
        if win and hasattr(win, "web_studio_view") and hasattr(win, "switchTo"):
            win.switchTo(win.web_studio_view)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)

        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 6)
        self.back_button = PrimaryPushButton("← Back to Studio", self)
        self.back_button.setObjectName("back_to_studio_button")
        self.back_button.clicked.connect(self._on_back_to_studio)
        header_row.addWidget(self.back_button)
        header_row.addSpacing(16)
        header_row.addWidget(SubtitleLabel("Reliability & Recovery Workspace", self))
        header_row.addStretch(1)
        layout.addLayout(header_row)
        self.status_label = BodyLabel("Recovered downloads stay stopped until you explicitly retry.", self)
        self.status_label.setWordWrap(True)
        self.status_label.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status_label)
        self.review_toggle = CheckBox("Review uncertain source matches before transfer", self)
        self.review_toggle.setChecked(self._review_saved)
        self.review_toggle.toggled.connect(self._save_review)
        layout.addWidget(self.review_toggle)
        tabs = QTabWidget(self)
        layout.addWidget(tabs)

        queue_page, queue_layout = self._page(tabs, "Recovery & output")
        self.queue_table = self._table(["Title", "Artist", "Status", "Stage", "Error", "Diagnostic hint"], queue_page)
        queue_layout.addWidget(self.queue_table)
        self.refresh_button = PushButton("Refresh diagnostics", queue_page)
        self.retry_button = PushButton("Retry selected (starts downloads)", queue_page)
        self.retry_failed_button = PushButton("Retry failed / stopped (starts downloads)", queue_page)
        self.output_button = PushButton("Preview queued output paths", queue_page)
        self._buttons(queue_layout, self.refresh_button, self.retry_button, self.retry_failed_button, self.output_button)
        self.output_preview = self._text(queue_page)
        queue_layout.addWidget(self.output_preview)
        self.refresh_button.clicked.connect(self.refresh_queue)
        self.retry_button.clicked.connect(self.retry_selected)
        self.retry_failed_button.clicked.connect(self.retry_failed)
        self.output_button.clicked.connect(self.preview_queue_outputs)

        staging_page, staging_layout = self._page(tabs, "Abandoned staging")
        staging_layout.addWidget(BodyLabel(
            "Scan manually for abandoned downloads. Recover verifies integrity; active downloads are refused.", staging_page))
        self.staging_table = self._table(["Directory", "Track ID", "State", "Error"], staging_page)
        staging_layout.addWidget(self.staging_table)
        self.staging_scan_button = PushButton("Scan abandoned staging", staging_page)
        self.staging_recover_button = PushButton("Recover ready", staging_page)
        self.staging_discard_button = PushButton("Discard selected…", staging_page)
        self._buttons(staging_layout, self.staging_scan_button, self.staging_recover_button,
                      self.staging_discard_button)
        self.staging_scan_button.clicked.connect(self.scan_staging)
        self.staging_recover_button.clicked.connect(self.recover_selected_staging)
        self.staging_discard_button.clicked.connect(self.discard_selected_staging)

        metadata_page, metadata_layout = self._page(tabs, "Metadata prefetch")
        metadata_layout.addWidget(BodyLabel(
            "Public Spotify track / album URLs only; up to 24 URLs and 24 preview tracks. No audio is fetched.", metadata_page))
        self.url_input = QPlainTextEdit(metadata_page)
        self.url_input.setPlaceholderText("One public Spotify track or album URL per line")
        self.url_input.setMaximumHeight(100)
        metadata_layout.addWidget(self.url_input)
        self.prefetch_button = PrimaryPushButton("Prefetch metadata", metadata_page)
        self.enqueue_button = PushButton("Enqueue previewed tracks (does not press Start)", metadata_page)
        self.enqueue_button.setEnabled(False)
        self._buttons(metadata_layout, self.prefetch_button, self.enqueue_button)
        self.metadata_table = self._table(["Title", "Artist", "Album"], metadata_page)
        metadata_layout.addWidget(self.metadata_table)
        self.url_input.textChanged.connect(self._invalidate_metadata)
        self.prefetch_button.clicked.connect(self.prefetch_metadata)
        self.enqueue_button.clicked.connect(self.enqueue_metadata)

        repair_page, repair_layout = self._page(tabs, "Reversible repairs")
        repair_layout.addWidget(BodyLabel(
            "Preview first. Originals are backed up; paths stay unchanged. Hardlinks share future in-place edits.", repair_page))
        self.retag_path = self._file_input(repair_layout, repair_page, "Archived audio file")
        self.retag_preview_button = PushButton("Preview archive metadata repair", repair_page)
        self.retag_apply_button = PrimaryPushButton("Apply metadata repair", repair_page)
        self._buttons(repair_layout, self.retag_preview_button, self.retag_apply_button)
        self.retag_preview = self._text(repair_page)
        repair_layout.addWidget(self.retag_preview)
        self.duplicate_path = self._file_input(repair_layout, repair_page, "Duplicate file")
        self.keeper_path = self._file_input(repair_layout, repair_page, "Keeper file (byte-identical)")
        self.duplicate_preview_button = PushButton("Preview hardlink replacement", repair_page)
        self.duplicate_apply_button = PrimaryPushButton("Apply hardlink replacement", repair_page)
        self._buttons(repair_layout, self.duplicate_preview_button, self.duplicate_apply_button)
        self.duplicate_preview = self._text(repair_page)
        repair_layout.addWidget(self.duplicate_preview)
        self.retag_path.textChanged.connect(lambda: self._invalidate("retag"))
        self.duplicate_path.textChanged.connect(lambda: self._invalidate("duplicate"))
        self.keeper_path.textChanged.connect(lambda: self._invalidate("duplicate"))
        self.retag_preview_button.clicked.connect(lambda: self.preview_repair("retag"))
        self.duplicate_preview_button.clicked.connect(lambda: self.preview_repair("duplicate"))
        self.retag_apply_button.clicked.connect(lambda: self.apply_repair("retag"))
        self.duplicate_apply_button.clicked.connect(lambda: self.apply_repair("duplicate"))

        history_page, history_layout = self._page(tabs, "Repair history")
        self.history_table = self._table(["ID", "Action", "Path", "State"], history_page)
        history_layout.addWidget(self.history_table)
        self.history_button = PushButton("Refresh history", history_page)
        self.undo_button = PushButton("Undo selected repair", history_page)
        self._buttons(history_layout, self.history_button, self.undo_button)
        self.history_button.clicked.connect(self.refresh_history)
        self.undo_button.clicked.connect(self.undo_selected)
        self._sync_apply()

    @staticmethod
    def _page(tabs, title):
        page = QWidget(tabs)
        layout = QVBoxLayout(page)
        tabs.addTab(page, title)
        return page, layout

    @staticmethod
    def _buttons(layout, *buttons):
        row = QHBoxLayout()
        for button in buttons:
            row.addWidget(button)
        row.addStretch()
        layout.addLayout(row)

    @staticmethod
    def _table(headers, parent):
        table = TableWidget(parent)
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        return table

    @staticmethod
    def _text(parent):
        text = QPlainTextEdit(parent)
        text.setReadOnly(True)
        return text

    def _file_input(self, layout, parent, placeholder):
        row = QHBoxLayout()
        field = LineEdit(parent)
        field.setPlaceholderText(placeholder)
        browse = PushButton("Choose file…", parent)
        browse.clicked.connect(lambda: self._choose_file(field))
        row.addWidget(field)
        row.addWidget(browse)
        layout.addLayout(row)
        return field

    def _choose_file(self, field):
        path, _ = QFileDialog.getOpenFileName(self, "Choose audio file", "", "Audio (*.flac *.mp3 *.m4a *.opus *.ogg);;All files (*)")
        if path:
            field.setText(path)

    def _message(self, text):
        self.status_label.setText(_safe_text(text))

    def _run(self, key, work, success, controls=(), failure=None):
        if key in self._jobs:
            return
        self._jobs[key] = (success, tuple(controls), failure)
        for control in controls:
            control.setEnabled(False)
        self._sync_apply()
        signals = self._signals

        def execute():
            result, error = None, None
            try:
                result = work()
            except Exception as exc:
                error = _safe_text(exc)
            try:
                signals.finished.emit(key, result, error)
            except RuntimeError:
                pass  # The workspace was destroyed while a background task finished.

        threading.Thread(target=execute, name=f"Reliability-{key}", daemon=True).start()

    def _finished(self, key, result, error):
        job = self._jobs.pop(key, None)
        if job is None:
            return
        success, controls, failure = job
        for control in controls:
            control.setEnabled(True)
        try:
            if error is not None:
                if failure:
                    failure()
                self._message(f"{key.capitalize()} failed: {error}")
            else:
                success(result)
        except Exception as exc:
            self._message(f"Could not display result: {exc}")
        self._sync_apply()
        self.enqueue_button.setEnabled(bool(self._metadata) and "enqueue" not in self._jobs)
        if key == "history" and self._history_refresh_pending:
            self._history_refresh_pending = False
            self.refresh_history()

    def _fill_table(self, table, rows):
        table.setRowCount(0)
        for row in rows:
            index = table.rowCount()
            table.insertRow(index)
            for column, value in enumerate(row):
                table.setItem(index, column, QTableWidgetItem(_safe_text(value or "")))

    @staticmethod
    def _selected_rows(table):
        return sorted({index.row() for index in table.selectionModel().selectedRows()})

    def refresh(self):
        self.refresh_queue()
        self.refresh_history()

    def showEvent(self, event):
        super().showEvent(event)
        self._diagnostics_timer.start()
        self.refresh_queue()

    def hideEvent(self, event):
        self._diagnostics_timer.stop()
        super().hideEvent(event)

    def refresh_queue(self):
        def load():
            return [{
                "id": item.track.id, "title": item.track.title,
                "artist": item.track.artist_str, "status": item.status,
                "stage": getattr(item, "stage", "") or item.status,
                "error": getattr(item, "error_message", ""),
                "hint": getattr(item, "diagnostic_hint", ""),
            } for item in self.queue_manager.get_items() if item.status != "Completed"]

        def show(rows):
            selected = {self._queue_rows[row]["id"] for row in self._selected_rows(self.queue_table)}
            self._queue_rows = rows
            self._fill_table(self.queue_table, [
                [row[key] for key in ("title", "artist", "status", "stage", "error", "hint")] for row in rows
            ])
            for index, row in enumerate(rows):
                if row["id"] in selected:
                    for column in range(self.queue_table.columnCount()):
                        self.queue_table.item(index, column).setSelected(True)

        self._run("queue", load, show, (self.refresh_button,))

    def _staging_controls(self):
        return (self.staging_scan_button, self.staging_recover_button, self.staging_discard_button)

    def scan_staging(self):
        def scan():
            return scan_abandoned_staging(config.get("download.output_dir", ""))

        def show(rows):
            self._staging_rows = rows
            self._fill_table(self.staging_table, [
                [row.get(key, "") for key in ("directory", "track_id", "state", "error")]
                for row in rows
            ])

        self._run("staging", scan, show, self._staging_controls())

    def _selected_staging(self):
        rows = self._selected_rows(self.staging_table)
        if len(rows) != 1:
            self._message("Select one staging directory.")
            return None
        return dict(self._staging_rows[rows[0]])

    def recover_selected_staging(self):
        if "staging" in self._jobs:
            return
        candidate = self._selected_staging()
        if candidate is None:
            return
        if candidate.get("state") != "ready":
            self._message("Only ready staging directories can be recovered.")
            return

        def recover():
            path = recover_staging(candidate["directory"])
            try:
                registered = self.queue_manager.complete_recovered_track(candidate.get("track_id"), path)
                return path, registered, None
            except Exception as exc:
                return path, False, _safe_text(exc)

        def done(result):
            path, registered, error = result
            message = f"File recovered: {path}. "
            message += "Queued track completed." if registered else "A library scan can index it."
            if error:
                message += f" Queue registration failed: {error}"
            self._message(message)
            self.refresh_queue()
            self.scan_staging()

        self._run("staging", recover, done, self._staging_controls())

    def discard_selected_staging(self):
        if "staging" in self._jobs:
            return
        candidate = self._selected_staging()
        if candidate is None:
            return
        answer = QMessageBox.question(
            self, "Discard abandoned staging?",
            _safe_text(f"Permanently discard this staging directory and its contents?\n{candidate['directory']}"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        def done(_):
            self._message("Staging directory discarded.")
            self.scan_staging()

        self._run("staging", lambda: discard_staging(candidate["directory"]), done, self._staging_controls())

    def retry_selected(self):
        ids = [self._queue_rows[row]["id"] for row in self._selected_rows(self.queue_table)
               if self._queue_rows[row]["status"] in ("Failed", "Stopped")]
        if not ids:
            self._message("Select failed or stopped tracks to retry.")
            return
        self._run("retry", lambda: sum(bool(self.queue_manager.retry_track(track_id)) for track_id in ids),
                  self._retried, (self.retry_button, self.retry_failed_button))

    def retry_failed(self):
        self._run("retry", self.queue_manager.retry_failed, self._retried,
                  (self.retry_button, self.retry_failed_button))

    def _retried(self, count):
        self._message(f"Retry requested for {count} tracks.")
        self.refresh_queue()

    def preview_queue_outputs(self):
        def preview():
            tracks = [copy.deepcopy(item.track) for item in self.queue_manager.get_items()
                      if item.status != "Completed"]
            return preview_outputs(tracks, config.get("download.output_dir", ""))

        self._run("output", preview, lambda rows: self._show_json(self.output_preview, rows), (self.output_button,))

    def _save_review(self, checked):
        previous = self._review_saved

        def saved(_):
            self._review_saved = checked
            self._message("Source review preference saved.")

        def failed():
            self.review_toggle.blockSignals(True)
            self.review_toggle.setChecked(previous)
            self.review_toggle.blockSignals(False)

        self._run("setting", lambda: config.set("download.review_uncertain_matches", bool(checked)),
                  saved, (self.review_toggle,), failed)

    def _invalidate_metadata(self):
        self._revision["metadata"] += 1
        self._metadata = []
        self.metadata_table.setRowCount(0)
        self.enqueue_button.setEnabled(False)

    @classmethod
    def _public_urls(cls, text):
        urls = text.split()
        if not urls or len(urls) > cls.MAX_PREFETCH_ITEMS:
            raise ValueError("Enter between 1 and 24 public Spotify track / album URLs.")
        canonical = []
        for url in urls:
            parsed = urlsplit(url)
            if (parsed.scheme != "https" or parsed.hostname != "open.spotify.com"
                    or parsed.username or parsed.password or parsed.port not in (None, 443)
                    or not re.fullmatch(r"/(?:intl-[a-zA-Z-]+/)?(?:track|album)/[A-Za-z0-9]{22}/?", parsed.path)):
                raise ValueError("Only public HTTPS Spotify track and album URLs are supported.")
            canonical.append("https://open.spotify.com" + parsed.path.rstrip("/"))
        return list(dict.fromkeys(canonical))

    def prefetch_metadata(self):
        try:
            urls = self._public_urls(self.url_input.toPlainText())
        except ValueError as exc:
            self._message(exc)
            return
        self._invalidate_metadata()
        revision = self._revision["metadata"]

        def fetch():
            client = SpotifyClient(
                client_id=config.get("spotify.client_id", ""),
                client_secret=config.get("spotify.client_secret", ""),
            )
            try:
                futures = client.prefetch_metadata(urls, max_items=self.MAX_PREFETCH_ITEMS)
                tracks = []
                seen = set()
                for future in futures:
                    for track in future.result():
                        if track.id not in seen and len(tracks) < self.MAX_PREFETCH_ITEMS:
                            tracks.append(track)
                            seen.add(track.id)
                return tracks
            finally:
                client.close()

        def show(tracks):
            if revision != self._revision["metadata"]:
                return
            self._metadata = tracks
            self._fill_table(self.metadata_table, [[t.title, t.artist_str, t.album] for t in tracks])
            self._message(f"Previewed {len(tracks)} tracks (limit 24). Nothing has been enqueued or started.")

        self._run("prefetch", fetch, show, (self.prefetch_button,))

    def enqueue_metadata(self):
        if not self._metadata:
            self._message("Prefetch metadata before enqueueing.")
            return
        tracks = copy.deepcopy(self._metadata)
        revision = self._revision["metadata"]

        def done(_):
            if revision == self._revision["metadata"]:
                self._invalidate_metadata()
            self._message(f"Submitted {len(tracks)} previewed tracks to the queue; Start was not requested.")
            self.refresh_queue()

        self._run("enqueue", lambda: self.queue_manager.enqueue(tracks), done, (self.enqueue_button,))

    def _invalidate(self, kind):
        self._revision[kind] += 1
        self._previews[kind] = None
        getattr(self, f"{kind}_preview").clear()
        self._sync_apply()

    def _sync_apply(self):
        if not hasattr(self, "retag_apply_button"):
            return
        busy = "repair" in self._jobs
        for kind in ("retag", "duplicate"):
            getattr(self, f"{kind}_apply_button").setEnabled(not busy and self._previews[kind] is not None)
            getattr(self, f"{kind}_preview_button").setEnabled(not busy)
        self.undo_button.setEnabled(not busy)

    def _manager(self):
        # Called only while holding _repair_lock, outside the GUI thread.
        if self._repair_manager is None:
            self._repair_manager = LibraryRepairManager()
        return self._repair_manager

    @staticmethod
    def _archive_metadata(record, path):
        if not record or not record.get("file_path"):
            raise ValueError("No archive metadata found for this file.")
        if os.path.normcase(os.path.abspath(record["file_path"])) != os.path.normcase(os.path.abspath(path)):
            raise ValueError("Archive lookup returned a different file; repair refused.")
        artists = record.get("artists") or record.get("artist")
        if isinstance(artists, str):
            artists = [artist.strip() for artist in artists.split(";") if artist.strip()]
        if not record.get("title") or not artists:
            raise ValueError("Archive metadata must include a title and artist.")
        return TrackMetadata(
            id=str(record.get("spotify_id") or record.get("id") or "archive"),
            title=record["title"], artists=list(artists), album=record.get("album") or "",
            release_date=record.get("release_date") or "", duration_ms=int(record.get("duration_ms") or 0),
            track_number=int(record.get("track_number") or 1), disc_number=int(record.get("disc_number") or 1),
            isrc=record.get("isrc") or "", genres=[genre.strip() for genre in (record.get("genre") or "").split(";") if genre.strip()],
        )

    def preview_repair(self, kind):
        if "repair" in self._jobs:
            return
        self._invalidate(kind)
        revision = self._revision[kind]
        path = (self.retag_path if kind == "retag" else self.duplicate_path).text().strip()
        keeper = self.keeper_path.text().strip()
        if not path or (kind == "duplicate" and not keeper):
            self._message("Choose the required files before previewing a repair.")
            return

        def preview():
            with self._repair_lock:
                manager = self._manager()
                if kind == "retag":
                    metadata = self._archive_metadata(self.archive_manager.get_track_by_path(path), path)
                    args = (path, metadata)
                    result = manager.preview_retag(*args)
                else:
                    args = (path, keeper)
                    result = manager.preview_duplicate(*args)
                return args, result

        def show(value):
            if revision != self._revision[kind]:
                return
            args, result = value
            self._show_json(getattr(self, f"{kind}_preview"), result)
            if result.get("can_apply", True):
                self._previews[kind] = (revision, args, copy.deepcopy(result))
            self._message("Repair preview ready. No files have been changed.")

        self._run("repair", preview, show)

    def apply_repair(self, kind):
        prepared = self._previews[kind]
        if prepared is None or "repair" in self._jobs:
            self._message("Create a matching repair preview before applying.")
            return
        revision, args, expected = prepared
        if revision != self._revision[kind]:
            return
        self._invalidate("retag")
        self._invalidate("duplicate")

        def apply():
            with self._repair_lock:
                manager = self._manager()
                current = getattr(manager, f"preview_{kind}")(*args)
                if current != expected:
                    raise ValueError("File or repair details changed since preview. Preview again.")
                return getattr(manager, f"apply_{kind}")(*args)

        def done(repair_id):
            self._invalidate("retag")
            self._invalidate("duplicate")
            self._message(f"Repair applied. History ID: {repair_id}")
            self.refresh_history()

        self._run("repair", apply, done)

    def refresh_history(self):
        if "history" in self._jobs:
            self._history_refresh_pending = True
            return

        def load():
            with self._repair_lock:
                return self._manager().list_history()

        def show(rows):
            self._history_rows = rows
            self._fill_table(self.history_table, [
                [row.get("id", ""), row.get("action", ""), row.get("file_path", row.get("path", "")), row.get("state", "")]
                for row in rows
            ])

        self._run("history", load, show, (self.history_button,))

    def undo_selected(self):
        rows = self._selected_rows(self.history_table)
        if len(rows) != 1:
            self._message("Select one applied repair to undo.")
            return
        entry = self._history_rows[rows[0]]
        if entry.get("state") != "applied" or not entry.get("id"):
            self._message("Only an applied repair can be undone.")
            return
        self._invalidate("retag")
        self._invalidate("duplicate")

        def undo():
            with self._repair_lock:
                self._manager().undo(entry["id"])

        def done(_):
            self._message("Repair undone.")
            self.refresh_history()

        self._run("repair", undo, done)

    @staticmethod
    def _show_json(widget, value):
        widget.setPlainText(json.dumps(_safe_data(value), indent=2, ensure_ascii=False, default=str))