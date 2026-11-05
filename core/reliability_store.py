"""Small durable stores for recoverable jobs and bounded public metadata caching."""
import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.paths import get_app_data_dir


class ReliabilityStore:
    def __init__(self, path: Optional[str | Path] = None):
        self.path = Path(path) if path else get_app_data_dir() / "reliability.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("""CREATE TABLE IF NOT EXISTS queue_jobs (
                track_id TEXT PRIMARY KEY, track_json TEXT NOT NULL, status TEXT NOT NULL,
                preferred_engine TEXT, updated_at REAL NOT NULL
            )""")
            conn.execute("""CREATE TABLE IF NOT EXISTS metadata_cache (
                cache_key TEXT PRIMARY KEY, payload TEXT NOT NULL, expires_at REAL NOT NULL,
                accessed_at REAL NOT NULL
            )""")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_metadata_cache_expires ON metadata_cache(expires_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_metadata_cache_accessed ON metadata_cache(accessed_at DESC)")
            conn.commit()

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(str(self.path), timeout=10)
        try:
            conn.execute("PRAGMA busy_timeout=10000")
            yield conn
        finally:
            conn.close()

    def save_queue(self, records: List[Dict[str, Any]]) -> None:
        now = time.time()
        rows = [
            (
                r["track_id"],
                json.dumps(r["track"], ensure_ascii=False),
                r["status"],
                r.get("preferred_engine"),
                now + (idx * 1e-6),
            )
            for idx, r in enumerate(records)
        ]
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("DELETE FROM queue_jobs")
            conn.executemany(
                "INSERT INTO queue_jobs(track_id, track_json, status, preferred_engine, updated_at) VALUES (?, ?, ?, ?, ?)",
                rows,
            )
            conn.commit()

    def load_queue(self) -> List[Dict[str, Any]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute("SELECT track_id, track_json, status, preferred_engine FROM queue_jobs ORDER BY updated_at ASC, rowid ASC").fetchall()
        records = []
        for track_id, track_json, status, preferred_engine in rows:
            try:
                track = json.loads(track_json)
                if isinstance(track, dict) and track.get("id") == track_id:
                    records.append({"track": track, "status": status, "preferred_engine": preferred_engine})
            except (TypeError, ValueError):
                continue
        return records

    def get_metadata(self, cache_key: str) -> Optional[Any]:
        now = time.time()
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT payload, expires_at FROM metadata_cache WHERE cache_key = ?", (cache_key,)).fetchone()
            if not row:
                return None
            if row[1] <= now:
                conn.execute("DELETE FROM metadata_cache WHERE cache_key = ?", (cache_key,))
                conn.commit()
                return None
            conn.execute("UPDATE metadata_cache SET accessed_at = ? WHERE cache_key = ?", (now, cache_key))
            conn.commit()
        try:
            return json.loads(row[0])
        except (TypeError, ValueError):
            return None

    def set_metadata(self, cache_key: str, payload: Any, ttl_seconds: int = 900, max_entries: int = 1000) -> None:
        now = time.time()
        serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO metadata_cache(cache_key, payload, expires_at, accessed_at) VALUES (?, ?, ?, ?)",
                (cache_key, serialized, now + max(1, ttl_seconds), now)
            )
            conn.execute("DELETE FROM metadata_cache WHERE expires_at <= ?", (now,))
            conn.execute("""DELETE FROM metadata_cache WHERE cache_key IN (
                SELECT cache_key FROM metadata_cache ORDER BY accessed_at DESC LIMIT -1 OFFSET ?
            )""", (max(1, max_entries),))
            conn.commit()