from PyQt6.QtCore import QObject, pyqtSignal


def safe_emit(signal, *args):
    """Safely emits a PyQt signal, guarding against deleted underlying C++ QObjects."""
    try:
        signal.emit(*args)
    except (RuntimeError, AttributeError):
        pass


def safe_invoke(fn, *args, **kwargs):
    """Safely invokes a UI callback or method, suppressing RuntimeError if the widget is deleted."""
    try:
        fn(*args, **kwargs)
    except (RuntimeError, AttributeError):
        pass


class EngineSignalBridge(QObject):
    """
    Thread-safe bridge connecting core multimedia engine callbacks to PyQt6 signals.
    """
    sig_track_enqueued = pyqtSignal(object)              # QueueItem
    sig_tracks_enqueued = pyqtSignal(list)               # List[QueueItem] (batched)
    sig_source_resolved = pyqtSignal(str, str, str)       # track_id, source_type, quality_badge
    sig_progress = pyqtSignal(str, float, str, str)       # track_id, percent, speed_str, eta_str
    sig_status_changed = pyqtSignal(str, str)             # track_id, status_string
    sig_completed = pyqtSignal(str, str)                  # track_id, output_path
    sig_failed = pyqtSignal(str, str)                     # track_id, error_message
    sig_musilon_limit_reached = pyqtSignal(object, object, object, object)  # track, item, reason, decision_callback
    sig_config_changed = pyqtSignal(str, object)          # key_path, new_value

    def bind_queue_manager(self, qm):
        """Binds queue manager callback hooks to emit these Qt signals."""
        qm.on_track_enqueued = lambda item: safe_emit(self.sig_track_enqueued, item)
        qm.on_tracks_enqueued = lambda items: safe_emit(self.sig_tracks_enqueued, items)
        qm.on_track_source_resolved = lambda tid, st, qb: safe_emit(self.sig_source_resolved, tid, st, qb)
        qm.on_track_progress = lambda tid, pct, spd, eta: safe_emit(self.sig_progress, tid, pct, spd, eta)
        qm.on_track_status_changed = lambda tid, st: safe_emit(self.sig_status_changed, tid, st)
        qm.on_track_completed = lambda tid, path: safe_emit(self.sig_completed, tid, path)
        qm.on_track_failed = lambda tid, err: safe_emit(self.sig_failed, tid, err)
        qm.on_musilon_limit_reached = lambda trk, itm, rsn, cb: safe_emit(self.sig_musilon_limit_reached, trk, itm, rsn, cb)

    def bind_config(self, cfg):
        """Binds core configuration manager changes to Qt signals."""
        cfg.add_listener(lambda key, val: safe_emit(self.sig_config_changed, key, val))
