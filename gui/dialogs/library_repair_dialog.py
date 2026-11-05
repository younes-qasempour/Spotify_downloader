import os
import threading
import logging
from typing import Optional, Callable, Dict, Any

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel
)
from qfluentwidgets import (
    MessageBoxBase, SubtitleLabel, StrongBodyLabel, CaptionLabel, BodyLabel,
    PushButton, CardWidget, SmoothScrollArea, SearchLineEdit, ComboBox,
    FluentIcon, InfoBar, InfoBarPosition
)

from core.library_repair import LibraryRepairManager
from gui.styles import TEXT_MUTED

logger = logging.getLogger("gui.dialogs.library_repair")


class LibraryRepairDialog(MessageBoxBase):
    """
    Library Repair History & One-Click Undo Dialog.
    Displays journaled repair operations (re-tagging, duplicate hardlinking)
    and allows safe atomic rollback of applied repairs.
    """

    sig_undo_result = pyqtSignal(bool, str)

    def __init__(
        self,
        repair_manager: Optional[LibraryRepairManager] = None,
        on_undone_callback: Optional[Callable[[], None]] = None,
        parent=None,
    ):
        self._fallback_parent = None
        if parent is None:
            from PyQt6.QtWidgets import QApplication
            app = QApplication.instance()
            parent = app.activeWindow() if app else None
            if parent is None:
                self._fallback_parent = QWidget()
                parent = self._fallback_parent

        super().__init__(parent)
        self.repair_manager = repair_manager or LibraryRepairManager()
        self.on_undone_callback = on_undone_callback
        self._last_undo_thread: Optional[threading.Thread] = None
        self._undo_in_progress = False
        self._is_closed = False
        self._undo_buttons: list[PushButton] = []

        self.widget.setMinimumWidth(720)
        self.widget.setMinimumHeight(520)

        self.titleLabel = SubtitleLabel("Library Repair History & Undo", self)
        self.viewLayout.addWidget(self.titleLabel)

        self.subtitleLabel = CaptionLabel(
            "View past repairs (metadata updates, deduplication) and roll back any change safely.",
            self
        )
        self.subtitleLabel.setTextColor(TEXT_MUTED, TEXT_MUTED)
        self.viewLayout.addWidget(self.subtitleLabel)

        # Filter bar: Search, State filter, Undo All
        self.filter_bar = QHBoxLayout()
        self.filter_bar.setSpacing(8)

        self.search_input = SearchLineEdit(self)
        self.search_input.setPlaceholderText("Search by file path, action, or hash...")
        self.search_input.setClearButtonEnabled(True)
        self.filter_bar.addWidget(self.search_input, 1)

        self.state_filter = ComboBox(self)
        self.state_filter.addItems(["All States", "Applied", "Undone", "Aborted"])
        self.filter_bar.addWidget(self.state_filter)

        self.undo_all_btn = PushButton(FluentIcon.HISTORY, "Undo All Applied", self)
        self.filter_bar.addWidget(self.undo_all_btn)

        self.viewLayout.addLayout(self.filter_bar)

        # Scrollable History List
        self.scroll_area = SmoothScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setMinimumHeight(340)
        self.scroll_area.setStyleSheet("""
            QScrollArea, SmoothScrollArea {
                background-color: #161616;
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 8px;
            }
        """)
        self.scroll_area.viewport().setStyleSheet("background-color: #161616;")

        self.list_container = QWidget()
        self.list_container.setStyleSheet("background: transparent;")
        self.list_lay = QVBoxLayout(self.list_container)
        self.list_lay.setContentsMargins(10, 10, 10, 10)
        self.list_lay.setSpacing(8)
        self.scroll_area.setWidget(self.list_container)
        self.viewLayout.addWidget(self.scroll_area, 1)

        self.yesButton.setText("Close")
        self.cancelButton.setVisible(False)

        self.sig_undo_result.connect(self._on_undo_result)
        self.search_input.textChanged.connect(self._render_filtered_history)
        self.state_filter.currentIndexChanged.connect(self._render_filtered_history)
        self.undo_all_btn.clicked.connect(self._trigger_undo_all)

        self.history_entries: list[dict] = []
        self._refresh_history()

    def _refresh_history(self):
        try:
            self.history_entries = self.repair_manager.list_history()
        except Exception as e:
            self.history_entries = []
            logger.error("Failed to load repair history: %s", e)
        self._render_filtered_history()

    def _render_filtered_history(self):
        self._undo_buttons = []
        self.list_container.setUpdatesEnabled(False)
        try:
            while self.list_lay.count():
                item = self.list_lay.takeAt(0)
                widget = item.widget()
                if widget:
                    widget.deleteLater()

            query = self.search_input.text().strip().lower()
            selected_state = self.state_filter.currentText().strip().lower()

            filtered = []
            for entry in self.history_entries:
                entry_state = str(entry.get("state", "applied")).strip().lower()
                if selected_state not in ("", "all states") and entry_state != selected_state:
                    continue
                if query:
                    searchable = (
                        str(entry.get("file_path", "")).lower() + " " +
                        str(entry.get("action", "")).lower() + " " +
                        str(entry.get("original_hash", "")).lower() + " " +
                        str(entry.get("repaired_hash", "")).lower() + " " +
                        str(entry.get("id", "")).lower()
                    )
                    if query not in searchable:
                        continue
                filtered.append(entry)

            if not filtered:
                msg = "No matching repair history entries." if self.history_entries else "No repair history entries found."
                empty_lbl = CaptionLabel(msg, self.list_container)
                empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                empty_lbl.setTextColor(TEXT_MUTED, TEXT_MUTED)
                self.list_lay.addWidget(empty_lbl)
                self.list_lay.addStretch(1)
            else:
                for entry in filtered:
                    card = self._create_history_card(entry)
                    self.list_lay.addWidget(card)
                self.list_lay.addStretch(1)

            has_applied = any(str(e.get("state", "")).lower() == "applied" and e.get("id") for e in self.history_entries)
            self.undo_all_btn.setEnabled(not self._undo_in_progress and has_applied)
        finally:
            self.list_container.setUpdatesEnabled(True)

    def _create_history_card(self, entry: Dict[str, Any]) -> CardWidget:
        card = CardWidget(self.list_container)
        card.setStyleSheet(
            "CardWidget { background-color: #1e1e1e; border: 1px solid rgba(255,255,255,0.08); border-radius: 8px; }"
        )
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(14, 12, 14, 12)
        card_layout.setSpacing(8)

        # Header: Action Type & State Badge
        header_row = QHBoxLayout()
        header_row.setSpacing(8)

        action = str(entry.get("action", "")).lower()
        action_text = "DUPLICATE HARDLINK" if action == "duplicate" else "RETAG"
        action_label = StrongBodyLabel(action_text, card)
        header_row.addWidget(action_label)

        # State badge
        state = str(entry.get("state", "applied")).lower()
        badge = QLabel(state.upper(), card)
        if state == "applied":
            badge_style = "color: #1db954; background-color: rgba(29, 185, 84, 0.15); border: 1px solid #1db954;"
        elif state == "undone":
            badge_style = "color: #e6a23c; background-color: rgba(230, 162, 60, 0.15); border: 1px solid #e6a23c;"
        elif state == "aborted":
            badge_style = "color: #f56c6c; background-color: rgba(245, 108, 108, 0.15); border: 1px solid #f56c6c;"
        else:
            badge_style = "color: #999999; background-color: rgba(153, 153, 153, 0.15); border: 1px solid #999999;"
        badge.setStyleSheet(f"QLabel {{ {badge_style} border-radius: 4px; padding: 2px 8px; font-size: 11px; font-weight: bold; }}")
        header_row.addWidget(badge)
        header_row.addStretch(1)

        card_layout.addLayout(header_row)

        # Target file path
        file_path_str = str(entry.get("file_path", "") or "")
        path_label = BodyLabel(file_path_str, card)
        path_label.setToolTip(file_path_str)
        path_label.setWordWrap(True)
        card_layout.addWidget(path_label)

        # Hashes and Undo button row
        bottom_row = QHBoxLayout()
        orig_h = str(entry.get("original_hash", "") or "")[:8]
        rep_h = str(entry.get("repaired_hash", "") or "")[:8]
        if orig_h and rep_h:
            hash_text = f"SHA-256: {orig_h}... \u2192 {rep_h}..."
        elif orig_h or rep_h:
            hash_text = f"SHA-256: {orig_h or rep_h}..."
        else:
            hash_text = "SHA-256: N/A"

        hash_label = CaptionLabel(hash_text, card)
        hash_label.setTextColor(TEXT_MUTED, TEXT_MUTED)
        bottom_row.addWidget(hash_label, 1)

        undo_btn = PushButton(FluentIcon.HISTORY, "Undo Repair", card)
        undo_btn.setFixedHeight(30)
        entry_id = str(entry.get("id") or "")
        is_applied = (state == "applied")
        can_undo = is_applied and bool(entry_id) and not self._undo_in_progress
        undo_btn.setEnabled(can_undo)
        if is_applied and bool(entry_id):
            undo_btn.clicked.connect(lambda _, eid=entry_id: self._trigger_undo(eid))
        else:
            undo_btn.setToolTip("Repair already undone or not in applied state")

        self._undo_buttons.append(undo_btn)
        bottom_row.addWidget(undo_btn)
        card_layout.addLayout(bottom_row)

        return card

    def _trigger_undo(self, entry_id: str):
        entry_id = str(entry_id or "")
        if self._undo_in_progress or not entry_id or self._is_closed:
            return
        self._undo_in_progress = True
        for btn in self._undo_buttons:
            btn.setEnabled(False)
        if hasattr(self, "undo_all_btn"):
            self.undo_all_btn.setEnabled(False)

        def worker():
            try:
                self.repair_manager.undo(entry_id)
                self.sig_undo_result.emit(True, f"Successfully rolled back repair {entry_id[:8]}...")
            except Exception as e:
                logger.exception("Failed to undo repair %s: %s", entry_id, e)
                self.sig_undo_result.emit(False, str(e))

        t = threading.Thread(target=worker, daemon=True, name=f"RepairUndoWorker-{entry_id[:8]}")
        self._last_undo_thread = t
        t.start()

    def _trigger_undo_all(self):
        if self._undo_in_progress or self._is_closed:
            return
        applied_ids = [
            str(e.get("id") or "")
            for e in self.history_entries
            if str(e.get("state", "")).lower() == "applied" and e.get("id")
        ]
        if not applied_ids:
            return
        self._undo_in_progress = True
        for btn in self._undo_buttons:
            btn.setEnabled(False)
        if hasattr(self, "undo_all_btn"):
            self.undo_all_btn.setEnabled(False)

        def worker():
            success_count = 0
            errors = []
            for eid in applied_ids:
                try:
                    self.repair_manager.undo(eid)
                    success_count += 1
                except Exception as e:
                    logger.exception("Failed to undo repair %s: %s", eid, e)
                    errors.append(f"{eid[:8]}: {e}")
            ok = len(errors) == 0
            if ok:
                msg = f"Successfully rolled back {success_count} repair(s)."
            else:
                msg = f"Rolled back {success_count} repair(s); {len(errors)} failed: {'; '.join(errors)}"
            self.sig_undo_result.emit(ok, msg)

        t = threading.Thread(target=worker, daemon=True, name="RepairUndoAllWorker")
        self._last_undo_thread = t
        t.start()

    def _on_undo_result(self, success: bool, message: str):
        self._undo_in_progress = False
        if self._is_closed:
            return
        if success:
            InfoBar.success(
                title="Repair Undone",
                content=message,
                orient=Qt.Orientation.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=3000,
                parent=self
            )
            if callable(self.on_undone_callback):
                try:
                    self.on_undone_callback()
                except Exception as e:
                    logger.error("Error in on_undone_callback: %s", e)
        else:
            InfoBar.error(
                title="Undo Failed",
                content=message,
                orient=Qt.Orientation.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=4000,
                parent=self
            )
        self._refresh_history()

    def closeEvent(self, event):
        self._is_closed = True
        super().closeEvent(event)

    def done(self, code):
        self._is_closed = True
        super().done(code)
        if self._fallback_parent is not None:
            self._fallback_parent.deleteLater()
            self._fallback_parent = None

