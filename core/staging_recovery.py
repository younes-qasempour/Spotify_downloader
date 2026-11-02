"""Publication and explicit recovery of owned download staging directories.

Invalid or active directories raise ValueError/OSError for explicit actions and
are omitted by scans. A publication journal and original payloads survive failed
publication; recovery never runs automatically.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile
import threading
from contextlib import contextmanager
import uuid

from core import utils


OWNER_MARKER = ".flacify-owner.json"
READY_MARKER = ".flacify-ready.json"
LOCK_FILE = ".flacify.lock"
PUBLICATION_MARKER = ".flacify-publication.json"
_MAX_MARKER = 16384
_FORMAT = "flacify-staging-v1"


def _plain(path):
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
        raise ValueError("Symlink or reparse point refused")
    return info


def _directory(directory):
    path = Path(os.path.abspath(directory))
    for component in (*reversed(path.parents), path):
        if not stat.S_ISDIR(_plain(component).st_mode):
            raise ValueError("Not a plain directory")
    if not path.name.startswith(".flacify-") or path.name == ".flacify-":
        raise ValueError("Not a staging directory")
    return path


def _basename(value):
    if (not isinstance(value, str) or not value or value in (".", "..")
            or re.search(r'[<>:"/\\|?*\x00-\x1f]', value)
            or value.endswith((".", " "))
            or re.fullmatch(r"CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9]", value.split(".")[0], re.I)):
        raise ValueError("Invalid basename")
    return value


def _identity(path):
    info = _plain(path)
    return [info.st_dev, info.st_ino]


def _read(path):
    info = _plain(path)
    if not stat.S_ISREG(info.st_mode) or info.st_size > _MAX_MARKER:
        raise ValueError("Invalid marker")
    with path.open("rb") as stream:
        content = stream.read(_MAX_MARKER + 1)
    if len(content) > _MAX_MARKER:
        raise ValueError("Marker too large")
    try:
        result = json.loads(content)
    except RecursionError as exc:
        raise ValueError("Marker nesting too deep") from exc
    if not isinstance(result, dict):
        raise ValueError("Invalid marker object")
    return result


def _sync_dir(path):
    if os.name != "nt":
        fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def _write(path, data):
    content = json.dumps(data, sort_keys=True).encode("utf-8")
    if len(content) > _MAX_MARKER:
        raise ValueError("Marker too large")
    if os.path.lexists(path):
        _plain(path)
    fd, temporary = tempfile.mkstemp(prefix=".marker-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        _sync_dir(path.parent)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _owner(path):
    data = _read(path / OWNER_MARKER)
    if (set(data) != {"format", "directory", "track_id", "token", "identity", "parent_identity"}
            or data.get("format") != _FORMAT or data.get("directory") != path.name
            or data.get("identity") != _identity(path)
            or data.get("parent_identity") != _identity(path.parent)
            or not isinstance(data.get("track_id"), str) or not data["track_id"]
            or not re.fullmatch(r"[0-9a-f]{32}", str(data.get("token", "")))):
        raise ValueError("Foreign or invalid ownership marker")
    _basename(data["directory"])
    return data


@contextmanager
def _lock(path, create=False):
    lock_path = path / LOCK_FILE
    if create:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
        os.write(fd, b"\0")
        os.fsync(fd)
    else:
        info = _plain(lock_path)
        if not stat.S_ISREG(info.st_mode) or info.st_size != 1 or info.st_nlink != 1:
            raise ValueError("Invalid lock file")
        fd = os.open(lock_path, os.O_RDWR | getattr(os, "O_NOFOLLOW", 0))
    locked = False
    try:
        if os.name == "nt":
            import msvcrt
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        locked = True
        yield
    finally:
        if locked:
            if os.name == "nt":
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


@contextmanager
def staging_lease(directory, track_id):
    """Create ownership and yield a publisher while holding the stage lock.

    Published originals remain in staging until explicitly discarded after the
    lease ends. Preserve the directory on publication errors for recovery.
    """
    path = _directory(directory)
    if not isinstance(track_id, str) or not track_id:
        raise ValueError("A nonempty track ID is required")
    if any(path.iterdir()):
        raise ValueError("A new lease requires an empty staging directory")
    with _lock(path, create=True):
        _write(path / OWNER_MARKER, {
            "format": _FORMAT, "directory": path.name, "track_id": track_id,
            "token": uuid.uuid4().hex, "identity": _identity(path),
            "parent_identity": _identity(path.parent),
        })
        lease = _StagingLease(path, _owner(path))
        try:
            yield lease
        finally:
            lease._close()


class _StagingLease:
    def __init__(self, path, owner):
        self._path = path
        self._owner = owner
        self._active = True
        self._published = False
        self._mutex = threading.Lock()

    def publish(self) -> str:
        """Publish a ready stage once while leased, retaining its originals.

        Audio goes to the stage's parent; lyrics retain their staged layout.
        Existing files are never overwritten; failed attempts retain originals
        and any journal for inspection or recovery.
        """
        with self._mutex:
            if not self._active:
                raise ValueError("Staging lease is no longer active")
            if self._published:
                raise ValueError("Staging lease has already published")
            destination = _publish_ready(self._path, self._owner)
            self._published = True
            return destination

    def _close(self):
        with self._mutex:
            self._active = False


def _fingerprint(path, durable=False):
    info = _plain(path)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError("Payload must be a plain, unshared file")
    digest = hashlib.sha256()
    with path.open("r+b" if durable else "rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
        if durable:
            os.fsync(stream.fileno())
    return {"basename": _basename(path.name), "size": info.st_size,
            "sha256": digest.hexdigest()}


def _tree(path, shared=None):
    matched = []
    for child in path.iterdir():
        info = _plain(child)
        if stat.S_ISDIR(info.st_mode):
            matched.extend(_tree(child, shared))
        elif not stat.S_ISREG(info.st_mode):
            raise ValueError("Unsafe staging contents")
        elif info.st_nlink != 1:
            destinations = (shared or {}).get(child.parent, ())
            if (info.st_nlink != 2 or not child.name.startswith(".publish-")
                    or not any(_same_published_file(info, target) for target in destinations)):
                raise ValueError("Unsafe staging contents")
            matched.append(child)
    return matched


def _same_published_file(info, destination):
    if not os.path.lexists(destination.parent):
        return False
    if not stat.S_ISDIR(_plain(destination.parent).st_mode):
        raise ValueError("Invalid publication output directory")
    if not os.path.lexists(destination):
        return False
    target = _plain(destination)
    return (stat.S_ISREG(target.st_mode) and target.st_nlink == 2
            and (target.st_dev, target.st_ino) == (info.st_dev, info.st_ino))


def mark_ready(directory, audio_path) -> None:
    """Record processed audio integrity and optional adjacent/nested LRC."""
    path = _directory(directory)
    owner = _owner(path)
    audio = Path(os.path.abspath(audio_path))
    if audio.parent != path or audio.name.startswith("."):
        raise ValueError("Audio must be directly inside staging")
    _tree(path)
    data = {"token": owner["token"], "audio": _fingerprint(audio, durable=True)}
    for location, folder in (("adjacent", path), ("nested", path / "lyrics")):
        companion = folder / (audio.stem + ".lrc")
        if os.path.lexists(companion):
            if "lyrics" in data:
                raise ValueError("Ambiguous lyrics companions")
            data["lyrics"] = dict(_fingerprint(companion, durable=True), location=location)
    _write(path / READY_MARKER, data)


def _ready(path, owner, verify=True):
    data = _read(path / READY_MARKER)
    if set(data) - {"token", "audio", "lyrics"} or data.get("token") != owner["token"]:
        raise ValueError("Invalid ready marker")
    for kind in ("audio", "lyrics"):
        if kind not in data and kind == "lyrics":
            continue
        record = data.get(kind)
        if not isinstance(record, dict):
            raise ValueError("Missing payload record")
        expected = {"basename", "size", "sha256"} | ({"location"} if kind == "lyrics" else set())
        if (set(record) != expected or type(record.get("size")) is not int
                or record["size"] < 0
                or not re.fullmatch(r"[0-9a-f]{64}", str(record.get("sha256", "")))):
            raise ValueError("Invalid payload record")
        name = _basename(record.get("basename"))
        if name.startswith("."):
            raise ValueError("Internal filename refused")
        folder = path
        if kind == "lyrics":
            if record.get("location") not in ("adjacent", "nested"):
                raise ValueError("Invalid lyrics location")
            if name != Path(data["audio"]["basename"]).stem + ".lrc":
                raise ValueError("Invalid lyrics basename")
            if record["location"] == "nested":
                folder = path / "lyrics"
                if verify or os.path.lexists(folder):
                    if not stat.S_ISDIR(_plain(folder).st_mode):
                        raise ValueError("Invalid staged lyrics directory")
        if verify:
            actual = _fingerprint(folder / name)
            if any(actual[key] != record[key] for key in actual):
                raise ValueError("Staged payload integrity check failed")
    return data


def _publication(path, owner):
    if os.path.lexists(path / PUBLICATION_MARKER):
        data = _read(path / PUBLICATION_MARKER)
        if set(data) != {"token", "basename"} or data.get("token") != owner["token"]:
            raise ValueError("Invalid publication marker")
        _basename(data.get("basename"))
        return data


def _stage_tree(path, owner):
    # Only a journal-matched temporary and its output may share an inode;
    # reconciliation unlinks the staging name, never the output name.
    publication = _publication(path, owner)
    ready = _ready(path, owner, verify=False) if os.path.lexists(path / READY_MARKER) else None
    shared = {}
    if publication and ready:
        destination = path.parent / publication["basename"]
        shared[path] = [destination]
        lyrics = ready.get("lyrics")
        if lyrics:
            folder = path / "lyrics" if lyrics["location"] == "nested" else path
            name = destination.stem + ".lrc"
            lyrics_root = path.parent / "lyrics" if lyrics["location"] == "nested" else path.parent
            targets = shared.setdefault(folder, [])
            targets.append(lyrics_root / name)
            if lyrics["location"] == "adjacent":
                targets.append(path.parent / "lyrics" / name)
    return _tree(path, shared), shared


def scan_abandoned_staging(root) -> list[dict]:
    """Return owned unlocked stages with state incomplete, ready, or invalid.

    A stage's output root is its immediate parent, including nested output
    folders. Scanning does not create locks, markers, or output files.
    """
    root = Path(os.path.abspath(root))
    for component in (*reversed(root.parents), root):
        if not stat.S_ISDIR(_plain(component).st_mode):
            raise ValueError("Invalid output root")
    found = []

    def visit(folder):
        for path in folder.iterdir():
            try:
                if not stat.S_ISDIR(_plain(path).st_mode):
                    continue
                if not path.name.startswith(".flacify-"):
                    visit(path)
                    continue
                path = _directory(path)
                owner = _owner(path)
                with _lock(path):
                    owner = _owner(path)
                    item = {"directory": str(path), "track_id": owner["track_id"],
                            "state": "incomplete"}
                    try:
                        _stage_tree(path, owner)
                        if os.path.lexists(path / READY_MARKER):
                            ready = _ready(path, owner)
                            item.update(state="ready", audio_path=str(path / ready["audio"]["basename"]))
                    except (ValueError, OSError, KeyError, TypeError) as exc:
                        item.update(state="invalid", error=str(exc))
                    item["publication_interrupted"] = os.path.lexists(path / PUBLICATION_MARKER)
                    found.append(item)
            except (ValueError, OSError, KeyError, TypeError):
                continue

    visit(root)
    return found


def _remove_contents(path, shared=None):
    _tree(path, shared)
    for child in path.iterdir():
        if child.name in (LOCK_FILE, OWNER_MARKER):
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()


def _finish_removal(path):
    (path / OWNER_MARKER).unlink()
    (path / LOCK_FILE).unlink()
    path.rmdir()
    _sync_dir(path.parent)


def _publish(source, destination, expected):
    # Publish a private, flushed copy without replacing an existing destination.
    _plain(source.parent)
    _plain(source)
    _plain(destination.parent)
    fd, temporary = tempfile.mkstemp(prefix=".publish-", dir=source.parent)
    try:
        with os.fdopen(fd, "wb") as output, source.open("rb") as incoming:
            shutil.copyfileobj(incoming, output)
            output.flush()
            os.fsync(output.fileno())
        actual = _fingerprint(Path(temporary))
        if any(actual[key] != expected[key] for key in ("size", "sha256")):
            raise ValueError("Payload changed during publication")
        try:
            os.link(temporary, destination)
        except FileExistsError:
            raise
        except OSError:
            if os.name != "nt":
                raise
            # Windows rename fails if the destination exists; both paths are
            # on the output filesystem, so the verified copy is moved atomically.
            os.rename(temporary, destination)
            temporary = None
        _sync_dir(destination.parent)
    finally:
        if temporary is not None:
            os.unlink(temporary)


def _publish_ready(path, owner):
    if _owner(path) != owner:
        raise ValueError("Ownership changed")
    matched, _ = _stage_tree(path, owner)
    ready = _ready(path, owner)
    audio = path / ready["audio"]["basename"]
    valid, reason = utils.is_valid_audio_file(str(audio))
    if not valid:
        raise ValueError("Invalid staged audio: " + str(reason))
    _ready(path, owner)
    for temporary in matched:
        temporary.unlink()
        _sync_dir(temporary.parent)
    lyrics = ready.get("lyrics")
    lyrics_root = path.parent / "lyrics" if lyrics and lyrics["location"] == "nested" else path.parent
    if lyrics and lyrics["location"] == "nested":
        if not os.path.lexists(lyrics_root):
            lyrics_root.mkdir()
        if not stat.S_ISDIR(_plain(lyrics_root).st_mode):
            raise ValueError("Invalid lyrics output directory")
    number = 0
    while True:
        name = audio.name if not number else f"{audio.stem} ({number}){audio.suffix}"
        destination = path.parent / name
        lrc_destination = lyrics_root / (destination.stem + ".lrc")
        if os.path.lexists(destination) or (lyrics and os.path.lexists(lrc_destination)):
            number += 1
            continue
        _write(path / PUBLICATION_MARKER, {"token": owner["token"], "basename": name})
        try:
            _publish(audio, destination, ready["audio"])
        except FileExistsError:
            number += 1
            continue
        break
    if lyrics:
        folder = path / "lyrics" if lyrics["location"] == "nested" else path
        _publish(folder / lyrics["basename"], lrc_destination, lyrics)
    return str(destination)


def recover_staging(directory) -> str:
    """Publish an abandoned ready stage without overwrite and remove it.

    Requires hard links on POSIX; Windows also supports no-overwrite rename.
    Failure preserves originals, and retry may use a new suffix.
    """
    path = _directory(directory)
    owner = _owner(path)
    with _lock(path):
        destination = _publish_ready(path, owner)
        _remove_contents(path)
    _finish_removal(path)
    return destination


def discard_staging(directory) -> None:
    """Remove an owned abandoned stage, retaining any published output."""
    path = _directory(directory)
    owner = _owner(path)
    with _lock(path):
        if _owner(path) != owner:
            raise ValueError("Ownership changed")
        _, shared = _stage_tree(path, owner)
        _remove_contents(path, shared)
    _finish_removal(path)