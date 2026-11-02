import errno
import hashlib
import os
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
import wave
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from unittest.mock import Mock, patch

import mutagen
from mutagen.flac import Picture
from mutagen.id3 import APIC, USLT

from core import library_repair
from core.library_repair import LibraryRepairManager, RepairConflictError
from core.spotify_client import TrackMetadata


class Interrupted(BaseException):
    pass


class TestLibraryRepair(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixtures = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        cls.addClassCleanup(cls.fixtures.cleanup)
        cls.fixture_dir = Path(cls.fixtures.name)
        bundled = Path(__file__).resolve().parents[1] / "bin" / "ffmpeg.exe"
        cls.ffmpeg = str(bundled) if bundled.is_file() else shutil.which("ffmpeg")
        if not cls.ffmpeg:
            raise RuntimeError("Library repair tests require bundled or installed FFmpeg")
        wav = cls.fixture_dir / "source.wav"
        with wave.open(str(wav), "wb") as audio:
            audio.setparams((1, 2, 44100, 0, "NONE", "not compressed"))
            audio.writeframes(bytes(range(256)) * 100)
        for extension in ("flac", "mp3", "m4a", "opus", "ogg"):
            result = subprocess.run(
                [cls.ffmpeg, "-nostdin", "-y", "-i", str(wav),
                 str(wav.with_suffix("." + extension))],
                capture_output=True, timeout=20
            )
            if result.returncode:
                raise RuntimeError(result.stderr.decode("utf-8", errors="replace"))

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.storage = self.root / "repair_backups"
        self.manager = LibraryRepairManager(storage_dir=self.storage)
        self.track = TrackMetadata("offline", "Repaired title", ["Artist A", "Artist B"],
                                   "Album", release_date="2024-02-03", track_number=3,
                                   disc_number=2, isrc="USAAA2400001")

    def audio(self, name="song", extension="flac"):
        destination = self.root / (name + "." + extension)
        shutil.copy2(self.fixture_dir / ("source." + extension), destination)
        return destination

    def pair(self):
        keeper = self.audio("keeper")
        duplicate = self.root / "duplicate.flac"
        shutil.copy2(keeper, duplicate)
        return duplicate, keeper

    def history(self, journal_id):
        return next(item for item in self.manager.list_history() if item["id"] == journal_id)

    def assert_no_stages(self):
        self.assertEqual(list(self.root.glob(".library-repair-*")), [])

    def test_retag_roundtrip_all_formats_and_offline(self):
        for extension in ("flac", "mp3", "m4a", "opus", "ogg"):
            with self.subTest(extension=extension):
                target = self.audio(extension=extension)
                before = target.read_bytes()
                with patch("requests.sessions.Session.request", side_effect=AssertionError("network")):
                    journal_id = self.manager.apply_retag(target, self.track)
                entry = self.history(journal_id)
                self.assertEqual(entry["state"], "applied")
                self.assertEqual(Path(entry["backup_path"]).read_bytes(), before)
                self.assertFalse(os.path.samefile(target, entry["backup_path"]))
                self.assertEqual(mutagen.File(target, easy=True)["title"], [self.track.title])
                self.assertEqual(entry["repaired_hash"], hashlib.sha256(target.read_bytes()).hexdigest())
                self.manager.undo(journal_id)
                self.assertEqual(target.read_bytes(), before)
                self.assertEqual(self.history(journal_id)["state"], "undone")
                self.manager.undo(journal_id)
                self.assertTrue(Path(entry["backup_path"]).exists())
        self.assertEqual(self.track.genres, [])
        self.assert_no_stages()

    def test_retag_preserves_artwork_lyrics_and_audio(self):
        for extension in ("flac", "mp3", "m4a", "opus", "ogg"):
            with self.subTest(extension=extension):
                target = self.audio(extension=extension)
                audio = mutagen.File(target)
                if audio.tags is None:
                    audio.add_tags()
                if extension == "flac":
                    picture = Picture()
                    picture.type = 3
                    picture.mime = "image/png"
                    picture.data = b"offline-cover"
                    audio.add_picture(picture)
                    audio["lyrics"] = ["Original lyrics"]
                elif extension == "mp3":
                    audio.tags.add(APIC(encoding=3, mime="image/png", type=3, data=b"offline-cover"))
                    audio.tags.add(USLT(encoding=3, lang="eng", text="Original lyrics"))
                elif extension == "m4a":
                    from mutagen.mp4 import MP4Cover
                    audio["covr"] = [MP4Cover(b"offline-cover", imageformat=MP4Cover.FORMAT_PNG)]
                    audio["\xa9lyr"] = ["Original lyrics"]
                else:
                    audio["metadata_block_picture"] = ["offline-cover"]
                    audio["lyrics"] = ["Original lyrics"]
                audio.save()
                decoded_before = subprocess.run(
                    [self.ffmpeg, "-nostdin", "-i", str(target), "-f", "s16le", "-"],
                    capture_output=True, timeout=20, check=True
                ).stdout
                self.manager.apply_retag(target, self.track)
                repaired = mutagen.File(target)
                if extension == "flac":
                    self.assertEqual(repaired.pictures[0].data, b"offline-cover")
                    self.assertEqual(repaired["lyrics"], ["Original lyrics"])
                elif extension == "mp3":
                    self.assertEqual(repaired.tags.getall("APIC")[0].data, b"offline-cover")
                    self.assertEqual(repaired.tags.getall("USLT")[0].text, "Original lyrics")
                elif extension == "m4a":
                    self.assertEqual(bytes(repaired["covr"][0]), b"offline-cover")
                    self.assertEqual(repaired["\xa9lyr"], ["Original lyrics"])
                else:
                    self.assertEqual(repaired["metadata_block_picture"], ["offline-cover"])
                    self.assertEqual(repaired["lyrics"], ["Original lyrics"])
                decoded_after = subprocess.run(
                    [self.ffmpeg, "-nostdin", "-i", str(target), "-f", "s16le", "-"],
                    capture_output=True, timeout=20, check=True
                ).stdout
                self.assertEqual(decoded_before, decoded_after)

    def test_preview_does_not_change_library_or_create_backups(self):
        duplicate, keeper = self.pair()
        before = duplicate.read_bytes()
        identity = library_repair._snapshot(duplicate)
        files = set(self.storage.iterdir())
        self.assertEqual(self.manager.preview_retag(duplicate, self.track)["metadata"]["title"], self.track.title)
        self.assertTrue(self.manager.preview_duplicate(duplicate, keeper)["can_apply"])
        self.assertEqual(duplicate.read_bytes(), before)
        self.assertEqual(library_repair._snapshot(duplicate), identity)
        self.assertFalse(os.path.samefile(duplicate, keeper))
        self.assertEqual(set(self.storage.iterdir()), files)
        self.assertEqual(self.manager.list_history(), [])

    def test_tagger_failure_preserves_original_and_removes_stage(self):
        target = self.audio()
        before = target.read_bytes()

        def fail(path, track, **options):
            self.assertEqual(options, {"embed_art": False, "embed_lyrics": False})
            self.assertNotEqual(Path(path), target)
            Path(path).write_bytes(b"damaged staging file")
            return False

        manager = LibraryRepairManager(tagger=Mock(tag_file=fail), storage_dir=self.storage)
        with self.assertRaisesRegex(ValueError, "tagging failed"):
            manager.apply_retag(target, self.track)
        self.assertEqual(target.read_bytes(), before)
        self.assert_no_stages()

    def test_download_tagger_uses_offline_metadata_adapter(self):
        from core.tagger import AudioTagger
        tagger = AudioTagger.__new__(AudioTagger)
        tagger.tag_file = Mock(side_effect=AssertionError("Download tagging is not safe for repair"))
        manager = LibraryRepairManager(tagger=tagger, storage_dir=self.storage)
        target = self.audio()
        with patch("requests.sessions.Session.request", side_effect=AssertionError("network")):
            manager.apply_retag(target, self.track)
        tagger.tag_file.assert_not_called()
        self.assertEqual(mutagen.File(target, easy=True)["title"], [self.track.title])

    def test_publication_failure_preserves_original_and_journals_abort(self):
        target = self.audio()
        before = target.read_bytes()
        with patch.object(library_repair.os, "replace", side_effect=PermissionError("locked")):
            with self.assertRaises(PermissionError):
                self.manager.apply_retag(target, self.track)
        entry = self.manager.list_history()[0]
        self.assertEqual(entry["state"], "aborted")
        self.assertEqual(target.read_bytes(), before)
        self.assertEqual(Path(entry["backup_path"]).read_bytes(), before)
        self.assert_no_stages()

    def test_duplicate_hardlink_and_independent_backup_undo(self):
        duplicate, keeper = self.pair()
        before = duplicate.read_bytes()
        journal_id = self.manager.apply_duplicate(duplicate, keeper)
        entry = self.history(journal_id)
        self.assertTrue(os.path.samefile(duplicate, keeper))
        self.assertFalse(os.path.samefile(duplicate, entry["backup_path"]))
        self.assertEqual(Path(entry["backup_path"]).read_bytes(), before)
        self.manager.undo(journal_id)
        self.assertFalse(os.path.samefile(duplicate, keeper))
        self.assertEqual(duplicate.read_bytes(), before)
        self.assertEqual(keeper.read_bytes(), before)
        self.assert_no_stages()

    def test_duplicate_refuses_unequal_samepath_and_existing_hardlink(self):
        duplicate, keeper = self.pair()
        duplicate.write_bytes(b"different")
        with self.assertRaises(RepairConflictError):
            self.manager.apply_duplicate(duplicate, keeper)
        with self.assertRaises(RepairConflictError):
            self.manager.preview_duplicate(keeper, keeper)
        duplicate.unlink()
        os.link(keeper, duplicate)
        with self.assertRaises(RepairConflictError):
            self.manager.apply_duplicate(duplicate, keeper)
        self.assertEqual(self.manager.list_history(), [])

    def test_duplicate_cross_device_link_error_is_nondestructive(self):
        duplicate, keeper = self.pair()
        original = library_repair._snapshot(duplicate)
        with patch.object(library_repair.os, "link", side_effect=OSError(errno.EXDEV, "cross device")):
            with self.assertRaises(OSError):
                self.manager.apply_duplicate(duplicate, keeper)
        self.assertEqual(library_repair._snapshot(duplicate), original)
        self.assertFalse(os.path.samefile(duplicate, keeper))
        self.assert_no_stages()

    def test_retag_hardlink_is_staged_not_in_place(self):
        target, alias = self.pair()
        target.unlink()
        os.link(alias, target)
        before = alias.read_bytes()
        self.assertTrue(self.manager.preview_retag(target, self.track)["hardlinked"])
        journal_id = self.manager.apply_retag(target, self.track)
        self.assertEqual(alias.read_bytes(), before)
        self.assertFalse(os.path.samefile(alias, target))
        self.manager.undo(journal_id)
        self.assertEqual(target.read_bytes(), before)

    def test_undo_refuses_external_edits_and_same_bytes_replacement(self):
        for replacement in (False, True):
            with self.subTest(replacement=replacement):
                target = self.audio(name=str(replacement))
                journal_id = self.manager.apply_retag(target, self.track)
                if replacement:
                    other = self.root / "replacement.flac"
                    shutil.copy2(target, other)
                    os.replace(other, target)
                else:
                    target.write_bytes(b"external edits")
                before = target.read_bytes()
                with self.assertRaises(RepairConflictError):
                    self.manager.undo(journal_id)
                self.assertEqual(target.read_bytes(), before)
                self.assertEqual(self.history(journal_id)["state"], "applied")

    def test_undo_refuses_invalid_or_missing_backup(self):
        for missing in (False, True):
            with self.subTest(missing=missing):
                target = self.audio(name=str(missing))
                journal_id = self.manager.apply_retag(target, self.track)
                backup = Path(self.history(journal_id)["backup_path"])
                if missing:
                    backup.unlink()
                else:
                    backup.write_bytes(b"corrupt")
                before = target.read_bytes()
                with self.assertRaises((RepairConflictError, FileNotFoundError)):
                    self.manager.undo(journal_id)
                self.assertEqual(target.read_bytes(), before)

    def test_undo_refuses_backup_that_is_no_longer_independent(self):
        target = self.audio()
        journal_id = self.manager.apply_retag(target, self.track)
        backup = Path(self.history(journal_id)["backup_path"])
        os.link(backup, self.root / "backup-alias")
        with self.assertRaisesRegex(RepairConflictError, "independent"):
            self.manager.undo(journal_id)

    def test_repair_storage_cannot_be_deduplicated(self):
        target = self.audio()
        journal_id = self.manager.apply_retag(target, self.track)
        backup = Path(self.history(journal_id)["backup_path"])
        with self.assertRaises(RepairConflictError):
            self.manager.apply_duplicate(target, backup)
        with self.assertRaises(RepairConflictError):
            self.manager.apply_duplicate(backup, target)

    def test_undo_publication_failure_keeps_repaired_target_and_is_retryable(self):
        target = self.audio()
        before = target.read_bytes()
        journal_id = self.manager.apply_retag(target, self.track)
        repaired = target.read_bytes()
        with patch.object(library_repair.os, "replace", side_effect=PermissionError("locked")):
            with self.assertRaises(PermissionError):
                self.manager.undo(journal_id)
        self.assertEqual(target.read_bytes(), repaired)
        self.assertEqual(self.history(journal_id)["state"], "applied")
        self.assert_no_stages()
        self.manager.undo(journal_id)
        self.assertEqual(target.read_bytes(), before)

    def test_keeper_change_during_link_is_not_published(self):
        duplicate, keeper = self.pair()
        before = duplicate.read_bytes()
        link = os.link

        def modify_and_link(source, destination):
            keeper.write_bytes(b"keeper externally changed")
            link(source, destination)

        with patch.object(library_repair.os, "link", side_effect=modify_and_link):
            with self.assertRaises(RepairConflictError):
                self.manager.apply_duplicate(duplicate, keeper)
        self.assertEqual(duplicate.read_bytes(), before)
        self.assertFalse(os.path.samefile(duplicate, keeper))
        self.assert_no_stages()

    def test_external_change_during_staging_is_not_overwritten(self):
        target = self.audio()

        def tag(path, track, **options):
            target.write_bytes(b"external change")
            return True

        manager = LibraryRepairManager(tagger=Mock(tag_file=tag), storage_dir=self.storage)
        with self.assertRaises(RepairConflictError):
            manager.apply_retag(target, self.track)
        self.assertEqual(target.read_bytes(), b"external change")
        self.assert_no_stages()

    def test_backup_and_prepared_journal_exist_before_publication(self):
        target = self.audio()
        before = target.read_bytes()
        replace = os.replace

        def inspect(stage, destination):
            with closing(sqlite3.connect(self.manager.journal_path)) as database:
                state, = database.execute("SELECT state FROM repairs").fetchone()
            self.assertEqual(state, "prepared")
            entry = self.manager._entries()[0]
            self.assertEqual(Path(entry["backup_path"]).read_bytes(), before)
            self.assertEqual(target.read_bytes(), before)
            replace(stage, destination)

        with patch.object(library_repair.os, "replace", side_effect=inspect):
            self.manager.apply_retag(target, self.track)

    def test_reopen_after_interruption_before_publication(self):
        target = self.audio()
        before = target.read_bytes()
        with patch.object(library_repair.os, "replace", side_effect=Interrupted()):
            with self.assertRaises(Interrupted):
                self.manager.apply_retag(target, self.track)
        reopened = LibraryRepairManager(storage_dir=self.storage)
        entry = reopened.list_history()[0]
        self.assertEqual(entry["state"], "aborted")
        self.assertEqual(target.read_bytes(), before)
        reopened.undo(entry["id"])
        self.assertEqual(reopened.list_history()[0]["state"], "undone")
        self.assert_no_stages()

    def test_abrupt_process_exit_before_and_after_publication(self):
        script = """
import os
import socket
import sys
from pathlib import Path
from core import paths

sandbox = Path(sys.argv[2]).parent
paths.get_app_data_dir = lambda: sandbox
paths.get_config_path = lambda: sandbox / 'child-config.json'
paths.get_archive_db_path = lambda: sandbox / 'child-archive.sqlite3'
paths.get_default_download_dir = lambda: sandbox

def offline(*args, **kwargs):
    raise AssertionError('Network is forbidden')

socket.socket.connect = offline
socket.getaddrinfo = offline
from core import library_repair
from core.spotify_client import TrackMetadata
manager = library_repair.LibraryRepairManager(storage_dir=sys.argv[2])
replace = os.replace

def crash(stage, destination):
    if sys.argv[3] == 'after':
        replace(stage, destination)
    os._exit(23)

library_repair.os.replace = crash
manager.apply_retag(sys.argv[1], TrackMetadata('offline', 'After crash', ['Artist'], 'Album'))
"""
        for when in ("before", "after"):
            with self.subTest(when=when):
                target = self.audio(name=when)
                before = target.read_bytes()
                result = subprocess.run(
                    [sys.executable, "-c", script, str(target), str(self.storage), when],
                    cwd=Path(__file__).resolve().parents[1], capture_output=True, timeout=20
                )
                self.assertEqual(result.returncode, 23, result.stderr.decode(errors="replace"))
                if when == "before":
                    self.assertTrue(list(self.root.glob(".library-repair-*")))
                reopened = LibraryRepairManager(storage_dir=self.storage)
                entry = reopened.list_history()[0]
                self.assertEqual(entry["state"], "aborted" if when == "before" else "applied")
                reopened.undo(entry["id"])
                self.assertEqual(target.read_bytes(), before)
                self.assert_no_stages()

    def test_reopen_after_interrupted_apply_and_undo_publication(self):
        target = self.audio()
        before = target.read_bytes()
        replace = os.replace

        def interrupt_after_replace(stage, destination):
            replace(stage, destination)
            raise Interrupted()

        with patch.object(library_repair.os, "replace", side_effect=interrupt_after_replace):
            with self.assertRaises(Interrupted):
                self.manager.apply_retag(target, self.track)
        reopened = LibraryRepairManager(storage_dir=self.storage)
        entry = reopened.list_history()[0]
        self.assertEqual(entry["state"], "applied")
        self.assertNotEqual(target.read_bytes(), before)
        with patch.object(library_repair.os, "replace", side_effect=interrupt_after_replace):
            with self.assertRaises(Interrupted):
                reopened.undo(entry["id"])
        reopened = LibraryRepairManager(storage_dir=self.storage)
        self.assertEqual(reopened.list_history()[0]["state"], "undone")
        self.assertEqual(target.read_bytes(), before)
        self.assert_no_stages()

    def test_reopen_after_interrupted_duplicate_publication(self):
        duplicate, keeper = self.pair()
        before = duplicate.read_bytes()
        replace = os.replace

        def interrupt_after_replace(stage, destination):
            replace(stage, destination)
            raise Interrupted()

        with patch.object(library_repair.os, "replace", side_effect=interrupt_after_replace):
            with self.assertRaises(Interrupted):
                self.manager.apply_duplicate(duplicate, keeper)
        reopened = LibraryRepairManager(storage_dir=self.storage)
        entry = reopened.list_history()[0]
        self.assertEqual(entry["state"], "applied")
        self.assertTrue(os.path.samefile(duplicate, keeper))
        reopened.undo(entry["id"])
        self.assertEqual(duplicate.read_bytes(), before)
        self.assertFalse(os.path.samefile(duplicate, keeper))

    def test_reopen_after_interruption_before_undo_publication(self):
        target = self.audio()
        before = target.read_bytes()
        journal_id = self.manager.apply_retag(target, self.track)
        repaired = target.read_bytes()
        with patch.object(library_repair.os, "replace", side_effect=Interrupted()):
            with self.assertRaises(Interrupted):
                self.manager.undo(journal_id)
        reopened = LibraryRepairManager(storage_dir=self.storage)
        self.assertEqual(reopened.list_history()[0]["state"], "applied")
        self.assertEqual(target.read_bytes(), repaired)
        reopened.undo(journal_id)
        self.assertEqual(target.read_bytes(), before)

    def test_reopen_does_not_accept_interrupted_target_conflict(self):
        target = self.audio()
        with patch.object(library_repair.os, "replace", side_effect=Interrupted()):
            with self.assertRaises(Interrupted):
                self.manager.apply_retag(target, self.track)
        target.write_bytes(b"external edits after interruption")
        reopened = LibraryRepairManager(storage_dir=self.storage)
        entry = reopened.list_history()[0]
        self.assertEqual(entry["state"], "prepared")
        with self.assertRaises(RepairConflictError):
            reopened.undo(entry["id"])
        self.assertEqual(target.read_bytes(), b"external edits after interruption")

    def test_reopen_history_and_undo(self):
        target = self.audio()
        before = target.read_bytes()
        journal_id = self.manager.apply_retag(target, self.track)
        reopened = LibraryRepairManager(storage_dir=self.storage)
        self.assertEqual(reopened.list_history()[0]["id"], journal_id)
        reopened.undo(journal_id)
        self.assertEqual(target.read_bytes(), before)

    def test_postpublication_journal_failure_recovers_from_prepared_record(self):
        target = self.audio()
        before = target.read_bytes()
        write = self.manager._write

        def fail_final_commit(entry, new=False):
            if entry["state"] in ("applied", "undone"):
                raise sqlite3.OperationalError("simulated final commit failure")
            write(entry, new=new)

        with patch.object(self.manager, "_write", side_effect=fail_final_commit):
            journal_id = self.manager.apply_retag(target, self.track)
        reopened = LibraryRepairManager(storage_dir=self.storage)
        self.assertEqual(reopened.list_history()[0]["state"], "applied")
        with patch.object(reopened, "_write", side_effect=fail_final_commit):
            reopened.undo(journal_id)
        reopened = LibraryRepairManager(storage_dir=self.storage)
        self.assertEqual(reopened.list_history()[0]["state"], "undone")
        self.assertEqual(target.read_bytes(), before)

    def test_threads_and_manager_instances_serialize(self):
        target = self.audio()
        barrier = threading.Barrier(2)

        def repair(index):
            manager = LibraryRepairManager(storage_dir=self.storage)
            barrier.wait(timeout=10)
            track = TrackMetadata(str(index), str(index), ["Artist"], "Album")
            return manager.apply_retag(target, track)

        with ThreadPoolExecutor(max_workers=2) as executor:
            ids = list(executor.map(repair, (1, 2)))
        entries = self.manager.list_history()
        self.assertEqual({entry["id"] for entry in entries}, set(ids))
        self.assertTrue(all(entry["state"] == "applied" for entry in entries))
        self.manager.undo(entries[0]["id"])
        self.assert_no_stages()

    def test_symlink_and_parent_symlink_are_refused(self):
        target = self.audio()
        link = self.root / "link.flac"
        parent_link = self.root / "linked_directory"
        try:
            link.symlink_to(target)
            parent_link.symlink_to(self.root, target_is_directory=True)
        except OSError as error:
            # Windows developer-mode privileges are not always available.
            self.assertIn(getattr(error, "winerror", None), (1314, 5))
            with patch.object(Path, "lstat", return_value=Mock(st_mode=stat.S_IFLNK, st_file_attributes=0)):
                with self.assertRaises(RepairConflictError):
                    self.manager.preview_retag(target, self.track)
            return
        with self.assertRaises(RepairConflictError):
            self.manager.apply_retag(link, self.track)
        with self.assertRaises(RepairConflictError):
            self.manager.preview_retag(parent_link / target.name, self.track)

    def test_windows_reparse_attribute_is_refused(self):
        target = self.audio()
        with patch.object(Path, "lstat", return_value=Mock(st_mode=stat.S_IFREG, st_file_attributes=0x400)):
            with self.assertRaises(RepairConflictError):
                self.manager.preview_retag(target, self.track)


if __name__ == "__main__":
    unittest.main()