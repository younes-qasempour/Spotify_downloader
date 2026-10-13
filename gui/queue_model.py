from typing import List, Dict, Optional, Tuple, Any
from PyQt6.QtCore import QAbstractTableModel, QModelIndex, Qt

from core.queue_manager import QueueItem


class TrackQueueModel(QAbstractTableModel):
    """
    High-capacity virtualized data model for the download queue.
    Supports thousands of rows with fast lookup, in-memory filtering,
    batch additions, and zero UI lockup.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._all_items: List[QueueItem] = []
        self._items_by_id: Dict[str, QueueItem] = {}
        self.items: List[QueueItem] = []
        self._id_to_row: Dict[str, int] = {}
        self.filter_query: str = ""
        self.status_filter: str = "All"

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self.items)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 1

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid() or index.row() >= len(self.items):
            return None

        item = self.items[index.row()]
        if role == Qt.ItemDataRole.UserRole:
            return item
        elif role == Qt.ItemDataRole.DisplayRole:
            return item.track.title

        return None

    def set_filter(self, query: str = "", status: str = "All"):
        self.filter_query = query
        self.status_filter = status
        self._apply_filter()

    def _apply_filter(self):
        query = self.filter_query.strip().lower()
        status_f = self.status_filter.strip().lower()

        filtered: List[QueueItem] = []
        for it in self._all_items:
            # 1. Status filter
            if status_f != "all":
                s = it.status.lower()
                if status_f in ("active", "downloading") and s not in ("resolving", "downloading", "tagging", "fetching lyrics"):
                    continue
                elif status_f in ("queued", "pending") and s not in ("queued", "paused"):
                    continue
                elif status_f == "completed" and s != "completed":
                    continue
                elif status_f in ("failed", "stopped") and s not in ("failed", "cancelled", "stopped"):
                    continue

            # 2. Text query search
            if query:
                title = (it.track.title or "").lower()
                artist = (it.track.artist_str or "").lower()
                album = (it.track.album or "").lower()
                if query not in title and query not in artist and query not in album:
                    continue

            filtered.append(it)

        self.beginResetModel()
        self.items = filtered
        self._id_to_row = {it.track.id: idx for idx, it in enumerate(self.items)}
        self.endResetModel()

    def add_item(self, item: QueueItem):
        existing_idx = next((i for i, it in enumerate(self._all_items) if it.track.id == item.track.id), -1)
        if existing_idx >= 0:
            self._all_items[existing_idx] = item
        else:
            self._all_items.append(item)
        self._items_by_id[item.track.id] = item
        self._apply_filter()

    def add_items(self, new_items: List[QueueItem]):
        """Vectorized batch insertion minimizing layout recalculations for large playlists."""
        if not new_items:
            return

        existing_ids = {it.track.id: i for i, it in enumerate(self._all_items)}
        for item in new_items:
            if item.track.id in existing_ids:
                self._all_items[existing_ids[item.track.id]] = item
            else:
                self._all_items.append(item)
                existing_ids[item.track.id] = len(self._all_items) - 1
            self._items_by_id[item.track.id] = item

        self._apply_filter()

    def set_items(self, items: List[QueueItem]):
        """Replaces all items in a single atomic batch with exactly one model reset."""
        self._all_items = list(items)
        self._items_by_id = {it.track.id: it for it in self._all_items}
        self._apply_filter()

    def remove_items(self, track_ids: List[str]):
        """Removes a list of items by track ID from the model and rebuilds row index."""
        if not track_ids:
            return
        id_set = set(track_ids)
        self._all_items = [it for it in self._all_items if it.track.id not in id_set]
        for tid in track_ids:
            self._items_by_id.pop(tid, None)
        self._apply_filter()

    def remove_item(self, track_id: str):
        self.remove_items([track_id])

    def update_source(self, track_id: str, source_type: str, quality_badge: str):
        it = self._items_by_id.get(track_id)
        if it:
            it.source_type = source_type
            it.quality_badge = quality_badge
        if track_id in self._id_to_row:
            row = self._id_to_row[track_id]
            self.dataChanged.emit(self.index(row, 0), self.index(row, 0))

    def update_progress(self, track_id: str, percent: float, speed_str: str, eta_str: str):
        it = self._items_by_id.get(track_id)
        if it:
            it.progress_percent = percent
            it.speed_str = speed_str
            it.eta_str = eta_str
        if track_id in self._id_to_row:
            row = self._id_to_row[track_id]
            self.dataChanged.emit(self.index(row, 0), self.index(row, 0))

    def update_status(self, track_id: str, status: str):
        it = self._items_by_id.get(track_id)
        if it:
            it.status = status
        if self.status_filter != "All":
            self._apply_filter()
        elif track_id in self._id_to_row:
            row = self._id_to_row[track_id]
            self.dataChanged.emit(self.index(row, 0), self.index(row, 0))

    def mark_completed(self, track_id: str, path: str):
        it = self._items_by_id.get(track_id)
        if it:
            it.status = "Completed"
            it.output_path = path
            it.progress_percent = 100.0
        if self.status_filter != "All":
            self._apply_filter()
        elif track_id in self._id_to_row:
            row = self._id_to_row[track_id]
            self.dataChanged.emit(self.index(row, 0), self.index(row, 0))

    def mark_failed(self, track_id: str, err: str):
        it = self._items_by_id.get(track_id)
        if it:
            it.status = "Failed"
            it.error_message = err
        if self.status_filter != "All":
            self._apply_filter()
        elif track_id in self._id_to_row:
            row = self._id_to_row[track_id]
            self.dataChanged.emit(self.index(row, 0), self.index(row, 0))

    def get_item(self, row: int) -> Optional[QueueItem]:
        if 0 <= row < len(self.items):
            return self.items[row]
        return None

    def clear(self):
        self._all_items.clear()
        self._items_by_id.clear()
        self._apply_filter()

    def clear_completed(self):
        self._all_items = [it for it in self._all_items if it.status != "Completed"]
        self._items_by_id = {it.track.id: it for it in self._all_items}
        self._apply_filter()

    def get_stats(self) -> Tuple[int, int, int, int]:
        total = len(self._all_items)
        active = sum(1 for it in self._all_items if it.status in ("Resolving", "Downloading", "Tagging", "Fetching Lyrics"))
        completed = sum(1 for it in self._all_items if it.status == "Completed")
        failed = sum(1 for it in self._all_items if it.status in ("Failed", "Cancelled", "Stopped"))
        return total, active, completed, failed
