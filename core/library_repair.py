"""Explicit, reversible library repairs. Nothing here updates the download archive.

``storage_dir`` overrides the AppData ``repair_backups`` directory, including its
journal. Backups are independent copies and are never automatically removed.
An injected tagger must implement the offline ``tag_file`` contract; the default
writer changes only supplied metadata and leaves artwork and lyrics alone.
The download AudioTagger is adapted to this writer rather than invoking its
network-enabled, destructive download tagging pipeline.
"""
import copy
import hashlib
import json
import os
import shutil
import sqlite3
import stat
import tempfile
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path

import mutagen
from mutagen.id3 import TALB, TCON, TDRC, TIT2, TPE1, TPOS, TRCK, TSRC
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4

from core.paths import get_app_data_dir
from core.spotify_client import TrackMetadata


_LOCK = threading.RLock()
_EXTENSIONS = (".flac", ".mp3", ".m4a", ".opus", ".ogg")


class RepairConflictError(ValueError):
    """A path, its contents, or a backup no longer matches the journal."""


def _regular_path(value):
    path = Path(os.path.abspath(os.fspath(value)))
    for component in (path, *path.parents):
        info = component.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise RepairConflictError(f"Symlinks and reparse points are not supported: {component}")
    if not stat.S_ISREG(path.stat().st_mode):
        raise RepairConflictError(f"Not a regular file: {path}")
    return path


def _signature(info):
    return [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns]


def _snapshot(path):
    path = _regular_path(path)
    before = path.stat()
    digest = hashlib.sha256()
    with path.open("rb") as source:
        opened = os.fstat(source.fileno())
        # Windows stat and fstat can expose different ctime semantics.
        if _signature(before)[:4] != _signature(opened)[:4]:
            raise RepairConflictError(f"File replaced while opening: {path}")
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
        after = os.fstat(source.fileno())
    if _signature(opened) != _signature(after) or _signature(before) != _signature(path.stat()):
        raise RepairConflictError(f"File changed while reading: {path}")
    return {"stat": _signature(before), "sha256": digest.hexdigest()}


def _expect(path, expected):
    if _snapshot(path) != expected:
        raise RepairConflictError(f"File changed since repair was prepared: {path}")


def _published(path, expected):
    """Rename can change ctime, but must preserve inode, size, mtime and bytes."""
    actual = _snapshot(path)
    return actual["sha256"] == expected["sha256"] and actual["stat"][:4] == expected["stat"][:4]


def _sync_file(path):
    with Path(path).open("r+b") as source:
        os.fsync(source.fileno())


def _sync_directory(path):
    # Windows does not expose directory fsync through Python's os.open.
    if os.name != "nt":
        descriptor = os.open(str(path), os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


class _MetadataTagger:
    def tag_file(self, file_path, track, **kwargs):
        audio = mutagen.File(file_path)
        if audio is None:
            raise ValueError("Unrecognized audio file")
        if audio.tags is None:
            audio.add_tags()
        if isinstance(audio, MP3):
            fields = [("TIT2", TIT2, track.title), ("TPE1", TPE1, track.artists),
                      ("TALB", TALB, track.album), ("TDRC", TDRC, track.release_date),
                      ("TRCK", TRCK, str(track.track_number)),
                      ("TPOS", TPOS, str(track.disc_number)), ("TSRC", TSRC, track.isrc)]
            if track.genres:
                fields.append(("TCON", TCON, track.genres))
            for name, frame, value in fields:
                audio.tags.delall(name)
                if value:
                    audio.tags.add(frame(encoding=3, text=value))
        elif isinstance(audio, MP4):
            fields = {"\xa9nam": [track.title], "\xa9ART": track.artists,
                      "\xa9alb": [track.album], "\xa9day": [track.release_date],
                      "trkn": [(track.track_number, 0)], "disk": [(track.disc_number, 0)],
                      "----:com.apple.iTunes:ISRC": [track.isrc.encode("utf-8")]}
            if track.genres:
                fields["\xa9gen"] = track.genres
            audio.tags.update(fields)
        else:
            fields = {"title": [track.title], "artist": track.artists,
                      "album": [track.album], "date": [track.release_date],
                      "tracknumber": [str(track.track_number)],
                      "discnumber": [str(track.disc_number)], "isrc": [track.isrc]}
            if track.genres:
                fields["genre"] = track.genres
            audio.tags.update(fields)
        audio.save()
        return True


class LibraryRepairManager:
    """Serialize repairs across threads and processes sharing a storage directory.

    Previews read library files only. Apply always revalidates rather than trusting
    a previous preview. Exceptions signal refusal/failure; prepared journal entries
    allow reopening after a crash, without automatically rewriting library files.
    """

    def __init__(self, tagger=None, storage_dir=None):
        if tagger is not None:
            from core.tagger import AudioTagger
            if isinstance(tagger, AudioTagger):
                tagger = None
        self.tagger = tagger if tagger is not None else _MetadataTagger()
        self.storage_dir = Path(storage_dir) if storage_dir is not None else get_app_data_dir() / "repair_backups"
        self.storage_dir = Path(os.path.abspath(self.storage_dir))
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.journal_path = self.storage_dir / "repair_journal.sqlite3"
        with self._locked():
            with self._database() as database:
                database.execute("""CREATE TABLE IF NOT EXISTS repairs (
                    id TEXT PRIMARY KEY, state TEXT NOT NULL, created_at REAL NOT NULL,
                    updated_at REAL NOT NULL, payload TEXT NOT NULL)""")
            self._recover()

    @contextmanager
    def _database(self):
        database = sqlite3.connect(str(self.journal_path), timeout=30)
        database.row_factory = sqlite3.Row
        database.execute("PRAGMA synchronous=FULL")
        try:
            with database:
                yield database
        finally:
            database.close()

    @contextmanager
    def _locked(self):
        with _LOCK:
            with (self.storage_dir / "repair.lock").open("a+b") as lock:
                lock.seek(0, os.SEEK_END)
                if not lock.tell():
                    lock.write(b"\0")
                    lock.flush()
                lock.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
                else:
                    import fcntl
                    fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    lock.seek(0)
                    if os.name == "nt":
                        msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def _write(self, entry, new=False):
        entry["updated_at"] = time.time()
        with self._database() as database:
            if new:
                database.execute("INSERT INTO repairs VALUES (?, ?, ?, ?, ?)",
                                 (entry["id"], entry["state"], entry["created_at"],
                                  entry["updated_at"], json.dumps(entry)))
            else:
                database.execute("UPDATE repairs SET state=?, updated_at=?, payload=? WHERE id=?",
                                 (entry["state"], entry["updated_at"], json.dumps(entry), entry["id"]))
        _sync_directory(self.storage_dir)

    def _entries(self):
        with self._database() as database:
            return [json.loads(row["payload"]) for row in database.execute(
                "SELECT payload FROM repairs ORDER BY created_at DESC, id")]

    def _clean_stage(self, path, expected):
        try:
            if _published(path, expected):
                Path(path).unlink()
        except (OSError, ValueError):
            pass

    def _recover(self):
        for entry in self._entries():
            if entry["state"] not in ("prepared", "undo_prepared"):
                continue
            undoing = entry["state"] == "undo_prepared"
            staged = entry["undo_staged"] if undoing else entry["staged"]
            stage_path = entry["undo_stage_path"] if undoing else entry["stage_path"]
            previous = entry["undo_previous"] if undoing else entry["original"]
            try:
                if _published(entry["file_path"], staged):
                    entry["state"] = "undone" if undoing else "applied"
                    entry["current"] = _snapshot(entry["file_path"])
                elif _snapshot(entry["file_path"]) == previous:
                    entry["state"] = "applied" if undoing else "aborted"
                else:
                    continue
            except (OSError, ValueError):
                continue
            self._write(entry)
            self._clean_stage(stage_path, staged)

    def _library_path(self, value):
        path = _regular_path(value)
        if self.storage_dir in path.parents:
            raise RepairConflictError("Repair storage cannot be used as a library file")
        return path

    def preview_retag(self, file_path, track: TrackMetadata) -> dict:
        path = self._library_path(file_path)
        if path.suffix.lower() not in _EXTENSIONS:
            raise ValueError(f"Unsupported audio extension: {path.suffix}")
        original = _snapshot(path)
        return {"action": "retag", "file_path": str(path), "original_hash": original["sha256"],
                "metadata": asdict(track), "size": original["stat"][2],
                "hardlinked": path.stat().st_nlink > 1, "can_apply": True}

    def preview_duplicate(self, duplicate_path, keeper_path) -> dict:
        duplicate = self._library_path(duplicate_path)
        keeper = self._library_path(keeper_path)
        if os.path.samefile(duplicate, keeper):
            raise RepairConflictError("Duplicate and keeper are already the same file")
        original = _snapshot(duplicate)
        kept = _snapshot(keeper)
        if original["stat"][0] != kept["stat"][0]:
            raise RepairConflictError("Hardlinks require files on the same device")
        if original["sha256"] != kept["sha256"] or original["stat"][2] != kept["stat"][2]:
            raise RepairConflictError("Duplicate and keeper are not byte-identical")
        return {"action": "duplicate", "file_path": str(duplicate), "duplicate_path": str(duplicate),
                "keeper_path": str(keeper), "original_hash": original["sha256"],
                "repaired_hash": kept["sha256"], "size": original["stat"][2],
                "can_apply": True, "warning": "Future in-place edits affect both hardlinked paths"}

    def _stage_name(self, target):
        descriptor, name = tempfile.mkstemp(prefix=".library-repair-", suffix=target.suffix, dir=target.parent)
        os.close(descriptor)
        return Path(name)

    def _backup(self, target, backup, original):
        with target.open("rb") as source, backup.open("xb") as destination:
            shutil.copyfileobj(source, destination, 1024 * 1024)
            destination.flush()
            os.fsync(destination.fileno())
        _expect(target, original)
        if _snapshot(backup)["sha256"] != original["sha256"]:
            raise RepairConflictError("Backup does not match original")
        _sync_directory(backup.parent)

    def apply_retag(self, file_path, track: TrackMetadata) -> str:
        return self._apply("retag", file_path, track=copy.deepcopy(track))

    def apply_duplicate(self, duplicate_path, keeper_path) -> str:
        return self._apply("duplicate", duplicate_path, keeper_path=keeper_path)

    def _apply(self, action, file_path, track=None, keeper_path=None):
        with self._locked():
            self._recover()
            preview = (self.preview_retag(file_path, track) if action == "retag"
                       else self.preview_duplicate(file_path, keeper_path))
            target = Path(preview["file_path"])
            original = _snapshot(target)
            keeper = Path(preview["keeper_path"]) if action == "duplicate" else None
            kept = _snapshot(keeper) if keeper is not None else None
            journal_id = uuid.uuid4().hex
            backup = self.storage_dir / (journal_id + ".original")
            stage = None
            entry = None
            published = False
            try:
                self._backup(target, backup, original)
                stage = self._stage_name(target)
                if action == "retag":
                    shutil.copy2(backup, stage)
                    if not self.tagger.tag_file(str(stage), track, embed_art=False, embed_lyrics=False):
                        raise ValueError("Metadata tagging failed")
                else:
                    _expect(keeper, kept)
                    stage.unlink()
                    os.link(keeper, stage)
                    # Creating a hardlink changes the keeper's ctime, not its bytes.
                    if not _published(keeper, kept):
                        raise RepairConflictError("Keeper changed while linking")
                    kept = _snapshot(keeper)
                _sync_file(stage)
                _sync_directory(target.parent)
                staged = _snapshot(stage)
                if action == "duplicate" and staged["sha256"] != original["sha256"]:
                    raise RepairConflictError("Keeper changed while linking")
                entry = {"id": journal_id, "action": action, "state": "prepared",
                         "created_at": time.time(), "file_path": str(target),
                         "backup_path": str(backup), "stage_path": str(stage),
                         "keeper_path": str(keeper) if keeper is not None else None,
                         "original_hash": original["sha256"], "repaired_hash": staged["sha256"],
                         "original": original, "staged": staged}
                self._write(entry, new=True)
                _expect(target, original)
                self._valid_backup(entry)
                if keeper is not None:
                    _expect(keeper, kept)
                _expect(stage, staged)
                os.replace(stage, target)
                published = True
                _sync_directory(target.parent)
                entry["state"] = "applied"
                entry["current"] = _snapshot(target)
                self._write(entry)
                return journal_id
            except Exception:
                if published:
                    # Publication succeeded: leave the durable prepared record recoverable.
                    return journal_id
                if entry is not None:
                    entry["state"] = "aborted"
                    self._write(entry)
                raise
            finally:
                if stage is not None and stage.exists():
                    stage.unlink()

    def _valid_backup(self, entry):
        backup = _regular_path(entry["backup_path"])
        if backup.parent != self.storage_dir:
            raise RepairConflictError("Backup is outside repair storage")
        if backup.stat().st_nlink != 1:
            raise RepairConflictError("Backup is no longer an independent copy")
        snapshot = _snapshot(backup)
        if (snapshot["sha256"] != entry["original_hash"] or
                snapshot["stat"][2] != entry["original"]["stat"][2]):
            raise RepairConflictError("Original backup is invalid")
        return backup

    def list_history(self) -> list[dict]:
        with self._locked():
            self._recover()
            return self._entries()

    def undo(self, journal_id) -> None:
        with self._locked():
            self._recover()
            entry = next((item for item in self._entries() if item["id"] == journal_id), None)
            if entry is None:
                raise KeyError(journal_id)
            if entry["state"] == "undone":
                _expect(entry["file_path"], entry["current"])
                self._valid_backup(entry)
                return
            if entry["state"] not in ("applied", "aborted"):
                raise RepairConflictError("Unresolved interrupted repair; target has changed")
            target = _regular_path(entry["file_path"])
            previous = entry["current"] if entry["state"] == "applied" else entry["original"]
            _expect(target, previous)
            backup = self._valid_backup(entry)
            if entry["state"] == "aborted":
                entry["state"] = "undone"
                entry["current"] = previous
                self._write(entry)
                return
            stage = self._stage_name(target)
            published = False
            try:
                shutil.copy2(backup, stage)
                _sync_file(stage)
                _sync_directory(target.parent)
                staged = _snapshot(stage)
                if staged["sha256"] != entry["original_hash"]:
                    raise RepairConflictError("Backup changed while restoring")
                entry.update(state="undo_prepared", undo_previous=previous,
                             undo_stage_path=str(stage), undo_staged=staged)
                self._write(entry)
                _expect(target, previous)
                self._valid_backup(entry)
                _expect(stage, staged)
                os.replace(stage, target)
                published = True
                _sync_directory(target.parent)
                entry["state"] = "undone"
                entry["current"] = _snapshot(target)
                self._write(entry)
            except Exception:
                if not published:
                    entry["state"] = "applied"
                    self._write(entry)
                    raise
            finally:
                if stage.exists():
                    stage.unlink()