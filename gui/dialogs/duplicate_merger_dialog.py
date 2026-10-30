import os
import threading
import logging
from typing import List, Dict, Any

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout
)
from qfluentwidgets import (
    MessageBoxBase, SubtitleLabel, StrongBodyLabel, CaptionLabel,
    PushButton, PrimaryPushButton, ProgressBar, CardWidget, SmoothScrollArea,
    FluentIcon, InfoBar
)

from gui.styles import TEXT_MUTED

logger = logging.getLogger("gui.dialogs.duplicate_merger")


class DuplicateMergerDialog(MessageBoxBase):
    """
    Smart Duplicate & Acoustic Fingerprint Merger Dialog.
    Finds duplicate tracks across playlists, singles, and albums using ISRC,
    canonical metadata, and 64-bit acoustic envelope fingerprinting.
    Supports both NTFS Hard-Linking (zero extra disk space, all files stay in place)
    and Clean Merge (deletes lower-quality copies and updates all .m3u8 playlists).
    """

    sig_progress = pyqtSignal(int, int, str)
    sig_scan_done = pyqtSignal(list)
    sig_merge_done = pyqtSignal(dict)

    def __init__(self, archive_manager, on_completed_callback=None, on_merged_callback=None, parent=None):
        super().__init__(parent)
        self.archive = archive_manager
        self.on_completed_callback = on_completed_callback or on_merged_callback
        self.duplicate_groups: List[Dict[str, Any]] = []

        self.widget.setMinimumWidth(720)
        self.widget.setMinimumHeight(540)

        self.titleLabel = SubtitleLabel("Smart Duplicate & Acoustic Fingerprint Merger", self)
        self.viewLayout.addWidget(self.titleLabel)

        self.status_lbl = CaptionLabel(
            "Scanning library & computing acoustic fingerprints to detect duplicate recordings...",
            self
        )
        self.status_lbl.setTextColor(TEXT_MUTED, TEXT_MUTED)
        self.viewLayout.addWidget(self.status_lbl)

        self.prog_bar = ProgressBar(self)
        self.prog_bar.setRange(0, 100)
        self.prog_bar.setValue(10)
        self.viewLayout.addWidget(self.prog_bar)

        # Summary Metrics Row
        metrics_row = QHBoxLayout()
        metrics_row.setSpacing(10)
        self.card_groups = self._make_stat_card("Duplicate Groups", "0")
        self.card_files = self._make_stat_card("Redundant Files", "0")
        self.card_space = self._make_stat_card("Reclaimable Space", "0.0 MB")
        metrics_row.addWidget(self.card_groups[0], 1)
        metrics_row.addWidget(self.card_files[0], 1)
        metrics_row.addWidget(self.card_space[0], 1)
        self.viewLayout.addLayout(metrics_row)

        # Scrollable Duplicate Groups List
        self.scroll_area = SmoothScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setMinimumHeight(290)
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
        self.list_lay.addStretch(1)
        self.scroll_area.setWidget(self.list_container)
        self.viewLayout.addWidget(self.scroll_area, 1)

        # Action Buttons Row
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        self.hardlink_btn = PrimaryPushButton(
            FluentIcon.LINK,
            "Hard-Link Duplicates (Keep All Paths, Save Space)",
            self
        )
        self.hardlink_btn.setFixedHeight(34)
        self.hardlink_btn.setEnabled(False)
        self.hardlink_btn.setToolTip(
            "Replaces redundant files of the same format with OS-level NTFS hard links to the highest-quality Master file.\n"
            "All playlist folders keep their files, while reclaiming 100% of duplicate disk space!"
        )
        self.hardlink_btn.clicked.connect(lambda: self._run_merge("hardlink"))

        self.merge_btn = PushButton(
            FluentIcon.DELETE,
            "Clean Merge & Update .m3u8 Playlists",
            self
        )
        self.merge_btn.setFixedHeight(34)
        self.merge_btn.setEnabled(False)
        self.merge_btn.setToolTip(
            "Deletes redundant duplicate copies from disk, updates all SQLite archive & playlist records to point to the Master file,\n"
            "and automatically regenerates all .m3u8 playlist files."
        )
        self.merge_btn.clicked.connect(lambda: self._run_merge("merge"))

        btn_row.addWidget(self.hardlink_btn, 1)
        btn_row.addWidget(self.merge_btn, 1)
        self.viewLayout.addLayout(btn_row)

        self.yesButton.setText("Close")
        self.cancelButton.setVisible(False)

        self.sig_progress.connect(self._on_progress)
        self.sig_scan_done.connect(self._on_scan_done)
        self.sig_merge_done.connect(self._on_merge_done)

        threading.Thread(target=self._scan_worker, daemon=True, name="DuplicateScanWorker").start()

    def _make_stat_card(self, label: str, value: str):
        card = CardWidget(self)
        card.setStyleSheet("CardWidget { background-color: #1e1e1e; border: 1px solid rgba(255,255,255,0.07); border-radius: 6px; }")
        lay = QHBoxLayout(card)
        lay.setContentsMargins(12, 8, 12, 8)
        t_lbl = CaptionLabel(label, card)
        t_lbl.setTextColor(TEXT_MUTED, TEXT_MUTED)
        v_lbl = StrongBodyLabel(value, card)
        v_lbl.setStyleSheet("font-size: 14px; font-weight: 700; color: #1ED760;")
        lay.addWidget(t_lbl)
        lay.addStretch(1)
        lay.addWidget(v_lbl)
        return card, v_lbl

    def _scan_worker(self):
        groups = self.archive.find_library_duplicates(
            use_acoustic_fingerprint=True,
            progress_callback=lambda c, t, m: self.sig_progress.emit(c, t, m)
        )
        self.sig_scan_done.emit(groups)

    def _on_progress(self, cur: int, tot: int, msg: str):
        self.prog_bar.setValue(min(95, int(cur / max(1, tot) * 100)))
        self.status_lbl.setText(msg)

    def _on_scan_done(self, groups: List[Dict[str, Any]]):
        self.prog_bar.setValue(100)
        self.duplicate_groups = groups

        while self.list_lay.count() > 1:
            child = self.list_lay.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        tot_groups = len(groups)
        tot_dups = sum(len(g.get("duplicates", [])) for g in groups)
        reclaim_bytes = sum(g.get("reclaimable_bytes", 0) for g in groups)
        reclaim_mb = reclaim_bytes / (1024 * 1024)

        self.card_groups[1].setText(str(tot_groups))
        self.card_files[1].setText(str(tot_dups))
        self.card_space[1].setText(f"{reclaim_mb:.1f} MB")

        if not groups:
            self.status_lbl.setText("Scan complete! Your library has zero duplicate audio tracks.")
            empty_lbl = StrongBodyLabel("✓ No Duplicate Tracks Found in Library", self.list_container)
            empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty_lbl.setStyleSheet("color: #4ADE80; font-size: 14px; padding: 48px 16px;")
            self.list_lay.insertWidget(0, empty_lbl)
            return

        self.status_lbl.setText(
            f"Found {tot_groups} duplicate song group(s) ({tot_dups} redundant file(s), {reclaim_mb:.1f} MB reclaimable)."
        )
        has_actionable = reclaim_bytes > 0
        self.hardlink_btn.setEnabled(has_actionable)
        self.merge_btn.setEnabled(has_actionable)

        for grp in groups:
            card = CardWidget(self.list_container)
            card.setStyleSheet("""
                CardWidget {
                    background-color: #1f1f1f;
                    border: 1px solid rgba(255, 255, 255, 0.08);
                    border-radius: 8px;
                }
            """)
            c_lay = QVBoxLayout(card)
            c_lay.setContentsMargins(12, 8, 12, 8)
            c_lay.setSpacing(4)

            head_row = QHBoxLayout()
            title_lbl = StrongBodyLabel(f"{grp['title']} — {grp['artist']}", card)
            title_lbl.setStyleSheet("color: #FFFFFF; font-size: 13px; font-weight: 700;")
            reason_lbl = CaptionLabel(grp.get("match_reason", "Match"), card)
            reason_lbl.setStyleSheet(
                "background-color: rgba(29, 185, 84, 0.16); color: #1ED760; padding: 2px 6px; border-radius: 4px; font-weight: 600;"
            )
            head_row.addWidget(title_lbl, 1)
            head_row.addWidget(reason_lbl)
            c_lay.addLayout(head_row)

            master = grp["master"]
            m_mb = master.get("size_bytes", 0) / (1024 * 1024)
            m_lbl = CaptionLabel(
                f"  ★ [KEEP MASTER]  {os.path.basename(master['file_path'])}  ({master.get('quality_badge') or 'Audio'}, {m_mb:.1f} MB)  —  {master['file_path']}",
                card
            )
            m_lbl.setStyleSheet("color: #4ADE80; font-size: 11px;")
            c_lay.addWidget(m_lbl)

            for d in grp.get("duplicates", []):
                d_mb = d.get("size_bytes", 0) / (1024 * 1024)
                status_tag = "[ALREADY HARD-LINKED]" if d.get("is_hardlinked") else "[DUPLICATE]"
                d_color = "#888888" if d.get("is_hardlinked") else "#FBBF24"
                d_lbl = CaptionLabel(
                    f"  ↳ {status_tag}  {os.path.basename(d['file_path'])}  ({d.get('quality_badge') or 'Audio'}, {d_mb:.1f} MB)  —  {d['file_path']}",
                    card
                )
                d_lbl.setStyleSheet(f"color: {d_color}; font-size: 11px;")
                c_lay.addWidget(d_lbl)

            self.list_lay.insertWidget(self.list_lay.count() - 1, card)

    def _run_merge(self, mode: str):
        if not self.duplicate_groups:
            return
        self.hardlink_btn.setEnabled(False)
        self.merge_btn.setEnabled(False)
        self.status_lbl.setText("Consolidating duplicate tracks and updating playlists...")

        def worker():
            stats = self.archive.merge_library_duplicates(self.duplicate_groups, mode=mode)
            self.sig_merge_done.emit(stats)

        threading.Thread(target=worker, daemon=True, name="DuplicateMergeWorker").start()

    def _on_merge_done(self, stats: Dict[str, Any]):
        reclaimed_mb = stats.get("reclaimed_bytes", 0) / (1024 * 1024)
        merged = stats.get("files_merged", 0)
        hl = stats.get("hardlinked", 0)
        msg = f"Consolidated {merged} duplicate file(s) ({hl} hard-linked) and reclaimed {reclaimed_mb:.1f} MB! All .m3u8 playlists updated."
        InfoBar.success("Deduplication Complete", msg, duration=5000, parent=self.window() or self)
        if self.on_completed_callback:
            try:
                self.on_completed_callback()
            except Exception:
                pass
        # Re-scan to refresh UI state
        threading.Thread(target=self._scan_worker, daemon=True, name="DuplicateRescanWorker").start()
