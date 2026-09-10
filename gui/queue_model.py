from typing import List, Dict, Optional, Tuple, Any
from PyQt6.QtCore import QAbstractTableModel, QModelIndex, Qt

from core.queue_manager import QueueItem


class TrackQueueModel(QAbstractTableModel):
    """
    High-capacity virtualized data model for the download queue.
    Supports thousands of rows with fast lookup and minimal memory overhead.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.items: List[QueueItem] = []
        self._id_to_row: Dict[str, int] = {}

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

    def add_item(self, item: QueueItem):
        if item.track.id in self._id_to_row:
            # Update existing row
            row = self._id_to_row[item.track.id]
            self.items[row] = item
            self.dataChanged.emit(self.index(row, 0), self.index(row, 0))
            return

        row = len(self.items)
        self.beginInsertRows(QModelIndex(), row, row)
        self.items.append(item)
        self._id_to_row[item.track.id] = row
        self.endInsertRows()

    def update_source(self, track_id: str, source_type: str, quality_badge: str):
        if track_id in self._id_to_row:
            row = self._id_to_row[track_id]
            item = self.items[row]
            item.source_type = source_type
            item.quality_badge = quality_badge
            self.dataChanged.emit(self.index(row, 0), self.index(row, 0))

    def update_progress(self, track_id: str, percent: float, speed_str: str, eta_str: str):
        if track_id in self._id_to_row:
            row = self._id_to_row[track_id]
            item = self.items[row]
            item.progress_percent = percent
            item.speed_str = speed_str
            item.eta_str = eta_str
            self.dataChanged.emit(self.index(row, 0), self.index(row, 0))

    def update_status(self, track_id: str, status: str):
        if track_id in self._id_to_row:
            row = self._id_to_row[track_id]
            item = self.items[row]
            item.status = status
            self.dataChanged.emit(self.index(row, 0), self.index(row, 0))

    def mark_completed(self, track_id: str, path: str):
        if track_id in self._id_to_row:
            row = self._id_to_row[track_id]
            item = self.items[row]
            item.status = "Completed"
            item.output_path = path
            item.progress_percent = 100.0
            self.dataChanged.emit(self.index(row, 0), self.index(row, 0))

    def mark_failed(self, track_id: str, err: str):
        if track_id in self._id_to_row:
            row = self._id_to_row[track_id]
            item = self.items[row]
            item.status = "Failed"
            item.error_message = err
            self.dataChanged.emit(self.index(row, 0), self.index(row, 0))

    def get_item(self, row: int) -> Optional[QueueItem]:
        if 0 <= row < len(self.items):
            return self.items[row]
        return None

    def clear(self):
        self.beginResetModel()
        self.items.clear()
        self._id_to_row.clear()
        self.endResetModel()

    def clear_completed(self):
        self.beginResetModel()
        self.items = [it for it in self.items if it.status != "Completed"]
        self._id_to_row = {it.track.id: idx for idx, it in enumerate(self.items)}
        self.endResetModel()

    def get_stats(self) -> Tuple[int, int, int, int]:
        total = len(self.items)
        active = sum(1 for it in self.items if it.status in ("Resolving", "Downloading", "Tagging", "Fetching Lyrics"))
        completed = sum(1 for it in self.items if it.status == "Completed")
        failed = sum(1 for it in self.items if it.status in ("Failed", "Cancelled"))
        return total, active, completed, failed
