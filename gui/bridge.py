from PyQt6.QtCore import QObject, pyqtSignal

class EngineSignalBridge(QObject):
    """
    Thread-safe bridge connecting core multimedia engine callbacks to PyQt6 signals.
    """
    sig_track_enqueued = pyqtSignal(object)              # QueueItem
    sig_source_resolved = pyqtSignal(str, str, str)       # track_id, source_type, quality_badge
    sig_progress = pyqtSignal(str, float, str, str)       # track_id, percent, speed_str, eta_str
    sig_status_changed = pyqtSignal(str, str)             # track_id, status_string
    sig_completed = pyqtSignal(str, str)                  # track_id, output_path
    sig_failed = pyqtSignal(str, str)                     # track_id, error_message

    def bind_queue_manager(self, qm):
        """Binds queue manager callback hooks to emit these Qt signals."""
        qm.on_track_enqueued = lambda item: self.sig_track_enqueued.emit(item)
        qm.on_track_source_resolved = lambda tid, st, qb: self.sig_source_resolved.emit(tid, st, qb)
        qm.on_track_progress = lambda tid, pct, spd, eta: self.sig_progress.emit(tid, pct, spd, eta)
        qm.on_track_status_changed = lambda tid, st: self.sig_status_changed.emit(tid, st)
        qm.on_track_completed = lambda tid, path: self.sig_completed.emit(tid, path)
        qm.on_track_failed = lambda tid, err: self.sig_failed.emit(tid, err)
