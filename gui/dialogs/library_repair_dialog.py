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
    PushButton, CardWidget, SmoothScrollArea,
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

        self.history_entries: list[dict] = []
        self._refresh_history()

    def _refresh_history(self):
        while self.list_lay.count():
            item = self.list_lay.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        try:
            self.history_entries = self.repair_manager.list_history()
        except Exception as e:
            self.history_entries = []
            logger.error("Failed to load repair history: %s", e)

        if not self.history_entries:
            empty_lbl = CaptionLabel("No repair history entries found.", self.list_container)
            empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty_lbl.setTextColor(TEXT_MUTED, TEXT_MUTED)
            self.list_lay.addWidget(empty_lbl)
            self.list_lay.addStretch(1)
            return

        for entry in self.history_entries:
            card = self._create_history_card(entry)
            self.list_lay.addWidget(card)

        self.list_lay.addStretch(1)

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
        path_label = BodyLabel(entry.get("file_path", ""), card)
        path_label.setWordWrap(True)
        card_layout.addWidget(path_label)

        # Hashes and Undo button row
        bottom_row = QHBoxLayout()
        orig_h = str(entry.get("original_hash", ""))[:8]
        rep_h = str(entry.get("repaired_hash", ""))[:8]
        hash_text = (
            f"SHA-256: {orig_h}... \u2192 {rep_h}..."
            if orig_h and rep_h
            else f"SHA-256: {orig_h or rep_h}..."
        )
        hash_label = CaptionLabel(hash_text, card)
        hash_label.setTextColor(TEXT_MUTED, TEXT_MUTED)
        bottom_row.addWidget(hash_label, 1)

        undo_btn = PushButton(FluentIcon.HISTORY, "Undo Repair", card)
        undo_btn.setFixedHeight(30)
        is_applied = (state == "applied")
        undo_btn.setEnabled(is_applied)
        if is_applied:
            entry_id = entry.get("id")
            undo_btn.clicked.connect(lambda _, eid=entry_id: self._trigger_undo(eid))
        else:
            undo_btn.setToolTip("Repair already undone or not in applied state")

        bottom_row.addWidget(undo_btn)
        card_layout.addLayout(bottom_row)

        return card

    def _trigger_undo(self, entry_id: str):
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

    def _on_undo_result(self, success: bool, message: str):
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

    def done(self, code):
        super().done(code)
        if self._fallback_parent is not None:
            self._fallback_parent.deleteLater()
            self._fallback_parent = None

