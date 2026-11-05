import errno
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import wave

from core import staging_recovery as recovery


class TestStagingRecovery(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def stage(self, name=".flacify-test", root=None):
        directory = (root or self.root) / name
        directory.mkdir()
        return directory

    def audio(self, directory):
        audio = directory / "song.wav"
        with wave.open(str(audio), "wb") as output:
            output.setparams((1, 2, 44100, 0, "NONE", "not compressed"))
            output.writeframes(b"\x00\x01" * 100000)
        return audio

    def ready(self, name=".flacify-test", lyrics=None):
        directory = self.stage(name)
        with recovery.staging_lease(directory, "track-123"):
            audio = self.audio(directory)
            if lyrics:
                folder = directory / "lyrics" if lyrics == "nested" else directory
                folder.mkdir(exist_ok=True)
                (folder / "song.lrc").write_text("[00:00.00] Offline lyrics", encoding="utf-8")
            recovery.mark_ready(directory, audio)
        return directory, audio

    def mutate(self, path, change):
        data = json.loads(path.read_text(encoding="utf-8"))
        change(data)
        path.write_text(json.dumps(data), encoding="utf-8")

    def test_live_lease_excluded_and_actions_refused(self):
        directory = self.stage()
        with recovery.staging_lease(directory, "track-123"):
            audio = self.audio(directory)
            recovery.mark_ready(directory, audio)
            self.assertEqual(recovery.scan_abandoned_staging(self.root), [])
            for action in (recovery.recover_staging, recovery.discard_staging):
                with self.assertRaises((ValueError, OSError)):
                    action(directory)
            self.assertTrue(audio.is_file())
        self.assertEqual(recovery.scan_abandoned_staging(self.root)[0]["state"], "ready")

    def test_orphan_ready_recovery_preserves_audio_collision_and_lyrics(self):
        directory, audio = self.ready(lyrics="adjacent")
        original = audio.read_bytes()
        existing = self.root / audio.name
        existing.write_bytes(b"existing user file")
        result = Path(recovery.recover_staging(directory))
        self.assertEqual(result.name, "song (1).wav")
        self.assertEqual(result.read_bytes(), original)
        self.assertEqual(existing.read_bytes(), b"existing user file")
        self.assertEqual((self.root / "song (1).lrc").read_text(),
                         "[00:00.00] Offline lyrics")
        self.assertFalse(directory.exists())

    def test_nested_lyrics_collision_selects_new_audio_basename(self):
        directory, _ = self.ready(lyrics="nested")
        (self.root / "lyrics").mkdir()
        existing = self.root / "lyrics" / "song.lrc"
        existing.write_text("keep", encoding="utf-8")
        result = Path(recovery.recover_staging(directory))
        self.assertEqual(result.name, "song (1).wav")
        self.assertEqual(existing.read_text(), "keep")
        self.assertTrue((self.root / "lyrics" / "song (1).lrc").is_file())

    def test_adjacent_lease_publication_preserves_layout(self):
        directory = self.stage()
        (self.root / "lyrics").write_bytes(b"unrelated file")
        with recovery.staging_lease(directory, "track") as lease:
            audio = self.audio(directory)
            (directory / "song.lrc").write_bytes(b"lyrics")
            recovery.mark_ready(directory, audio)
            result = Path(lease.publish())
            self.assertEqual(result.read_bytes(), audio.read_bytes())
            self.assertEqual((self.root / "song.lrc").read_bytes(), b"lyrics")
            self.assertEqual((self.root / "lyrics").read_bytes(), b"unrelated file")
            self.assertTrue((directory / "song.lrc").exists())
        recovery.discard_staging(directory)

    def test_adjacent_lyrics_collision_selects_new_audio_basename(self):
        directory, audio = self.ready(lyrics="adjacent")
        original = audio.read_bytes()
        existing = self.root / "song.lrc"
        existing.write_bytes(b"existing lyrics")
        result = Path(recovery.recover_staging(directory))
        self.assertEqual(result.name, "song (1).wav")
        self.assertEqual(result.read_bytes(), original)
        self.assertEqual(existing.read_bytes(), b"existing lyrics")
        self.assertEqual((self.root / "song (1).lrc").read_text(), "[00:00.00] Offline lyrics")

    def test_adjacent_lyrics_ignore_unrelated_nested_collision(self):
        directory, _ = self.ready(lyrics="adjacent")
        nested = self.root / "lyrics"
        nested.mkdir()
        (nested / "song.lrc").write_bytes(b"unrelated lyrics")
        result = Path(recovery.recover_staging(directory))
        self.assertEqual(result.name, "song.wav")
        self.assertEqual((self.root / "song.lrc").read_text(), "[00:00.00] Offline lyrics")
        self.assertEqual((nested / "song.lrc").read_bytes(), b"unrelated lyrics")

    def test_legacy_adjacent_lyrics_link_is_reconciled_without_removing_output(self):
        directory, audio = self.ready(lyrics="adjacent")
        original = audio.read_bytes()
        owner = json.loads((directory / recovery.OWNER_MARKER).read_text())
        (directory / recovery.PUBLICATION_MARKER).write_text(json.dumps({
            "token": owner["token"], "basename": audio.name}), encoding="utf-8")
        (self.root / audio.name).write_bytes(original)
        legacy_folder = self.root / "lyrics"
        legacy_folder.mkdir()
        legacy_output = legacy_folder / "song.lrc"
        temporary = directory / ".publish-legacy"
        temporary.write_bytes(b"legacy published lyrics")
        os.link(temporary, legacy_output)
        self.assertEqual(recovery.scan_abandoned_staging(self.root)[0]["state"], "ready")
        result = Path(recovery.recover_staging(directory))
        self.assertEqual(result.name, "song (1).wav")
        self.assertEqual(result.read_bytes(), original)
        self.assertEqual(legacy_output.read_bytes(), b"legacy published lyrics")
        self.assertEqual((self.root / "song (1).lrc").read_text(), "[00:00.00] Offline lyrics")

    def test_hash_and_size_corruption_refused_without_cleanup(self):
        for same_size in (True, False):
            with self.subTest(same_size=same_size):
                directory, audio = self.ready(".flacify-" + str(same_size))
                data = audio.read_bytes()
                audio.write_bytes(b"x" * len(data) if same_size else b"short")
                with self.assertRaises(ValueError):
                    recovery.recover_staging(directory)
                self.assertTrue(audio.is_file())
        self.assertEqual({item["state"] for item in recovery.scan_abandoned_staging(self.root)}, {"invalid"})

    def test_validation_boundary_failure_refused(self):
        directory, audio = self.ready()
        with patch.object(recovery.utils, "is_valid_audio_file", return_value=(False, "invalid container")) as validate:
            with self.assertRaisesRegex(ValueError, "invalid container"):
                recovery.recover_staging(directory)
        validate.assert_called_once_with(str(audio))
        self.assertTrue(audio.exists())

    def test_unmarked_scan_does_not_create_lock_or_change_files(self):
        directory = self.stage()
        payload = directory / "legacy.wav"
        payload.write_bytes(b"legacy")
        before = sorted(directory.iterdir())
        self.assertEqual(recovery.scan_abandoned_staging(self.root), [])
        self.assertEqual(sorted(directory.iterdir()), before)
        for action in (recovery.recover_staging, recovery.discard_staging):
            with self.assertRaises((ValueError, OSError)):
                action(directory)
        self.assertEqual(payload.read_bytes(), b"legacy")

    def test_incomplete_owned_stage_can_only_be_discarded_explicitly(self):
        directory = self.stage()
        with recovery.staging_lease(directory, "incomplete"):
            (directory / "part.bin").write_bytes(b"partial")
        item, = recovery.scan_abandoned_staging(self.root)
        self.assertEqual(item["track_id"], "incomplete")
        self.assertEqual(item["state"], "incomplete")
        with self.assertRaises((ValueError, OSError)):
            recovery.recover_staging(directory)
        self.assertTrue(directory.exists())
        recovery.discard_staging(directory)
        self.assertFalse(directory.exists())

    def test_foreign_marker_and_renamed_directory_refused(self):
        directory, _ = self.ready()
        foreign = self.stage(".flacify-foreign")
        for child in directory.iterdir():
            shutil.copy2(child, foreign / child.name)
        for target in (foreign, directory.rename(self.root / "not-staging")):
            for action in (recovery.recover_staging, recovery.discard_staging):
                with self.assertRaises(ValueError):
                    action(target)
        self.assertEqual(recovery.scan_abandoned_staging(self.root), [])

    def test_tampered_ready_paths_and_token_refused(self):
        for index, value in enumerate(("../outside.wav", "..\\outside.wav", "C:\\outside.wav", "song.wav:stream", "/outside", "NUL.wav")):
            directory, audio = self.ready(".flacify-path-" + str(index))
            self.mutate(directory / recovery.READY_MARKER,
                        lambda data: data["audio"].update(basename=value))
            with self.assertRaises(ValueError):
                recovery.recover_staging(directory)
            self.assertTrue(audio.exists())
        directory, _ = self.ready(".flacify-token")
        self.mutate(directory / recovery.READY_MARKER, lambda data: data.update(token="0" * 32))
        with self.assertRaises(ValueError):
            recovery.recover_staging(directory)

    def test_oversized_and_malformed_owner_refused(self):
        directory, _ = self.ready()
        marker = directory / recovery.OWNER_MARKER
        for value in (b"x" * 20000, b"[]", b"{", b"\xff"):
            marker.write_bytes(value)
            self.assertEqual(recovery.scan_abandoned_staging(self.root), [])
            for action in (recovery.recover_staging, recovery.discard_staging):
                with self.assertRaises((ValueError, OSError)):
                    action(directory)

    def test_interrupted_publication_preserves_originals_and_evidence(self):
        directory, audio = self.ready(lyrics="adjacent")
        original = recovery._publish
        calls = []

        def interrupted(source, destination, expected):
            calls.append(destination)
            if len(calls) == 2:
                raise OSError("simulated interruption")
            original(source, destination, expected)

        with patch.object(recovery, "_publish", side_effect=interrupted):
            with self.assertRaisesRegex(OSError, "simulated interruption"):
                recovery.recover_staging(directory)
        self.assertTrue(audio.exists())
        self.assertTrue((directory / "song.lrc").exists())
        self.assertTrue((directory / recovery.READY_MARKER).exists())
        self.assertTrue((directory / recovery.PUBLICATION_MARKER).exists())
        self.assertTrue(recovery.scan_abandoned_staging(self.root)[0]["publication_interrupted"])
        published = self.root / "song.wav"
        self.assertEqual(published.read_bytes(), audio.read_bytes())
        result = Path(recovery.recover_staging(directory))
        self.assertEqual(result.name, "song (1).wav")
        self.assertTrue(published.exists())

    def crash_after_link(self, directory, link_number):
        script = (
            "import os, sys; from core import staging_recovery as r\n"
            "link = os.link\n"
            "count = 0\n"
            "def crash(source, destination):\n"
            "    global count\n"
            "    link(source, destination)\n"
            "    count += 1\n"
            "    if count == int(sys.argv[2]): os._exit(42)\n"
            "r.os.link = crash\n"
            "r.recover_staging(sys.argv[1])\n"
        )
        result = subprocess.run([sys.executable, "-c", script, str(directory), str(link_number)],
                                cwd=Path(__file__).resolve().parents[1], capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 42, result.stderr)

    def test_crash_after_audio_or_lyrics_link_is_retryable(self):
        for number, location in ((1, "adjacent"), (2, "adjacent"), (1, "nested"), (2, "nested")):
            with self.subTest(number=number, location=location):
                output = self.root / f"retry-{number}-{location}"
                output.mkdir()
                directory = self.stage(root=output)
                with recovery.staging_lease(directory, "track"):
                    audio = self.audio(directory)
                    folder = directory / "lyrics" if location == "nested" else directory
                    folder.mkdir(exist_ok=True)
                    (folder / "song.lrc").write_bytes(b"lyrics")
                    recovery.mark_ready(directory, audio)
                original = audio.read_bytes()
                self.crash_after_link(directory, number)
                item, = recovery.scan_abandoned_staging(output)
                self.assertEqual(item["state"], "ready")
                self.assertTrue(item["publication_interrupted"])
                self.assertTrue(list(directory.rglob(".publish-*")))
                result = Path(recovery.recover_staging(directory))
                self.assertEqual(result.name, "song (1).wav")
                self.assertEqual(result.read_bytes(), original)
                self.assertEqual((output / "song.wav").read_bytes(), original)
                lyrics_output = output / "lyrics" if location == "nested" else output
                self.assertEqual((lyrics_output / "song (1).lrc").read_bytes(), b"lyrics")
                if number == 2:
                    self.assertEqual((lyrics_output / "song.lrc").read_bytes(), b"lyrics")
                self.assertFalse(directory.exists())

    def test_crash_after_link_can_be_discarded_without_removing_output(self):
        directory, audio = self.ready(lyrics="nested")
        original = audio.read_bytes()
        self.crash_after_link(directory, 2)
        recovery.discard_staging(directory)
        self.assertFalse(directory.exists())
        self.assertEqual((self.root / "song.wav").read_bytes(), original)
        self.assertEqual((self.root / "lyrics" / "song.lrc").read_text(),
                         "[00:00.00] Offline lyrics")

    def test_unrelated_publish_hardlink_is_not_accepted(self):
        directory, audio = self.ready()
        owner = json.loads((directory / recovery.OWNER_MARKER).read_text())
        (directory / recovery.PUBLICATION_MARKER).write_text(json.dumps({
            "token": owner["token"], "basename": audio.name}), encoding="utf-8")
        outside = self.root / "outside"
        outside.write_bytes(b"user data")
        os.link(outside, directory / ".publish-unrelated")
        self.assertEqual(recovery.scan_abandoned_staging(self.root)[0]["state"], "invalid")
        for action in (recovery.recover_staging, recovery.discard_staging):
            with self.assertRaises(ValueError):
                action(directory)
        self.assertEqual(outside.read_bytes(), b"user data")

    def test_crashed_link_requires_journal_and_no_extra_links(self):
        directory, _ = self.ready()
        self.crash_after_link(directory, 1)
        temporary, = directory.glob(".publish-*")
        extra = self.root / "extra"
        os.link(temporary, extra)
        for action in (recovery.recover_staging, recovery.discard_staging):
            with self.assertRaises(ValueError):
                action(directory)
        self.assertTrue(extra.exists())
        extra.unlink()
        journal = directory / recovery.PUBLICATION_MARKER
        marker = journal.read_bytes()
        journal.unlink()
        for action in (recovery.recover_staging, recovery.discard_staging):
            with self.assertRaises(ValueError):
                action(directory)
        journal.write_bytes(marker)
        recovery.discard_staging(directory)
        self.assertTrue((self.root / "song.wav").exists())

    def test_replaced_destination_is_preserved_on_retry(self):
        directory, audio = self.ready()
        original = audio.read_bytes()
        self.crash_after_link(directory, 1)
        destination = self.root / "song.wav"
        destination.unlink()
        destination.write_bytes(b"replacement user data")
        result = Path(recovery.recover_staging(directory))
        self.assertEqual(result.name, "song (1).wav")
        self.assertEqual(result.read_bytes(), original)
        self.assertEqual(destination.read_bytes(), b"replacement user data")

    def test_lease_publish_preserves_ready_payload_and_refuses_expired_lease(self):
        directory = self.stage()
        with recovery.staging_lease(directory, "track") as lease:
            audio = self.audio(directory)
            (directory / "song.lrc").write_bytes(b"lyrics")
            recovery.mark_ready(directory, audio)
            result = Path(lease.publish())
            self.assertTrue(audio.exists())
            self.assertTrue((directory / "song.lrc").exists())
            self.assertEqual(recovery.scan_abandoned_staging(self.root), [])
            self.assertEqual(result.read_bytes(), audio.read_bytes())
            self.assertEqual((self.root / "song.lrc").read_bytes(), b"lyrics")
            with self.assertRaisesRegex(ValueError, "already published"):
                lease.publish()
        with self.assertRaises(ValueError):
            lease.publish()
        self.assertEqual(recovery.scan_abandoned_staging(self.root)[0]["state"], "ready")
        recovery.discard_staging(directory)
        self.assertTrue(result.exists())

    @unittest.skipUnless(os.name == "nt", "Windows rename semantics required")
    def test_lease_publish_without_hardlinks_preserves_originals(self):
        directory = self.stage()
        with recovery.staging_lease(directory, "track") as lease:
            audio = self.audio(directory)
            lyrics = directory / "song.lrc"
            lyrics.write_bytes(b"lyrics")
            recovery.mark_ready(directory, audio)
            original = audio.read_bytes()
            with patch.object(recovery.os, "link", side_effect=OSError("hardlinks unavailable")) as link:
                result = Path(lease.publish())
            self.assertEqual(link.call_count, 2)
            self.assertEqual(result.read_bytes(), original)
            self.assertEqual(audio.read_bytes(), original)
            self.assertEqual(lyrics.read_bytes(), b"lyrics")
            self.assertEqual((self.root / "song.lrc").read_bytes(), b"lyrics")
            self.assertEqual(list(directory.glob(".publish-*")), [])
        recovery.discard_staging(directory)

    @unittest.skipUnless(os.name == "nt", "Windows rename semantics required")
    def test_rename_fallback_collision_never_overwrites(self):
        for suffix in (".wav", ".lrc"):
            with self.subTest(suffix=suffix):
                output = self.root / suffix[1:]
                output.mkdir()
                directory = self.stage(root=output)
                rename = os.rename
                collided = []

                def race(source, destination):
                    if Path(destination).suffix == suffix and not collided:
                        collided.append(destination)
                        Path(destination).write_bytes(b"concurrent user file")
                    return rename(source, destination)

                with recovery.staging_lease(directory, "track") as lease:
                    audio = self.audio(directory)
                    (directory / "song.lrc").write_bytes(b"lyrics")
                    recovery.mark_ready(directory, audio)
                    original = audio.read_bytes()
                    with patch.object(recovery.os, "link", side_effect=OSError("hardlinks unavailable")):
                        with patch.object(recovery.os, "rename", side_effect=race):
                            if suffix == ".lrc":
                                with self.assertRaises(FileExistsError):
                                    lease.publish()
                            else:
                                result = Path(lease.publish())
                                self.assertEqual(result.name, "song (1).wav")
                    self.assertEqual(Path(collided[0]).read_bytes(), b"concurrent user file")
                    self.assertEqual(audio.read_bytes(), original)
                    self.assertEqual((directory / "song.lrc").read_bytes(), b"lyrics")
                if suffix == ".lrc":
                    result = Path(recovery.recover_staging(directory))
                    self.assertEqual(result.name, "song (1).wav")
                self.assertEqual(result.read_bytes(), original)
                self.assertEqual((output / "song (1).lrc").read_bytes(), b"lyrics")

    @unittest.skipUnless(os.name == "nt", "Windows rename semantics required")
    def test_nested_rename_fallback_lyrics_race_preserves_output(self):
        directory, audio = self.ready(lyrics="nested")
        original = audio.read_bytes()
        rename = os.rename
        collided = []

        def race(source, destination):
            if Path(destination).suffix == ".lrc" and not collided:
                collided.append(destination)
                Path(destination).write_bytes(b"concurrent user lyrics")
            return rename(source, destination)

        with patch.object(recovery.os, "link", side_effect=OSError("hardlinks unavailable")):
            with patch.object(recovery.os, "rename", side_effect=race):
                with self.assertRaises(FileExistsError):
                    recovery.recover_staging(directory)
            self.assertEqual(audio.read_bytes(), original)
            result = Path(recovery.recover_staging(directory))
        self.assertEqual(result.name, "song (1).wav")
        self.assertEqual(result.read_bytes(), original)
        self.assertEqual(Path(collided[0]).read_bytes(), b"concurrent user lyrics")
        self.assertEqual((self.root / "lyrics" / "song (1).lrc").read_text(),
                         "[00:00.00] Offline lyrics")

    @unittest.skipUnless(os.name == "nt", "Windows rename semantics required")
    def test_crashed_lease_rename_fallback_preserves_originals(self):
        for number, location in ((1, "adjacent"), (2, "adjacent"), (1, "nested"), (2, "nested")):
            with self.subTest(number=number, location=location):
                output = self.root / f"{number}-{location}"
                output.mkdir()
                directory = self.stage(root=output)
                script = (
                    "import os, sys, wave; from pathlib import Path; from core import staging_recovery as r\n"
                    "directory = Path(sys.argv[1]); crash_at = int(sys.argv[2]); location = sys.argv[3]\n"
                    "with r.staging_lease(directory, 'track') as lease:\n"
                    "    audio = directory / 'song.wav'\n"
                    "    with wave.open(str(audio), 'wb') as out:\n"
                    "        out.setparams((1, 2, 44100, 0, 'NONE', 'not compressed'))\n"
                    "        out.writeframes(b'\\x00\\x01' * 100000)\n"
                    "    folder = directory / 'lyrics' if location == 'nested' else directory\n"
                    "    folder.mkdir(exist_ok=True)\n"
                    "    (folder / 'song.lrc').write_bytes(b'lyrics')\n"
                    "    r.mark_ready(directory, audio)\n"
                    "    rename = os.rename; count = [0]\n"
                    "    def unsupported(source, destination):\n"
                    "        raise OSError('hardlinks unavailable')\n"
                    "    def crash(source, destination):\n"
                    "        rename(source, destination)\n"
                    "        count[0] += 1\n"
                    "        if count[0] == crash_at: os._exit(42)\n"
                    "    r.os.link = unsupported; r.os.rename = crash\n"
                    "    lease.publish()\n"
                )
                process = subprocess.run([sys.executable, "-B", "-c", script, str(directory), str(number), location],
                                         cwd=Path(__file__).resolve().parents[1], capture_output=True, timeout=30)
                self.assertEqual(process.returncode, 42, process.stderr)
                original = (directory / "song.wav").read_bytes()
                staged_lyrics = directory / "lyrics" if location == "nested" else directory
                lyrics_output = output / "lyrics" if location == "nested" else output
                self.assertEqual((staged_lyrics / "song.lrc").read_bytes(), b"lyrics")
                self.assertEqual((output / "song.wav").read_bytes(), original)
                if number == 2:
                    self.assertEqual((lyrics_output / "song.lrc").read_bytes(), b"lyrics")
                item, = recovery.scan_abandoned_staging(output)
                self.assertEqual(item["state"], "ready")
                self.assertTrue(item["publication_interrupted"])
                with patch.object(recovery.os, "link", side_effect=OSError("hardlinks unavailable")):
                    result = Path(recovery.recover_staging(directory))
                self.assertEqual(result.name, "song (1).wav")
                self.assertEqual(result.read_bytes(), original)
                self.assertEqual((output / "song.wav").read_bytes(), original)
                self.assertEqual((lyrics_output / "song (1).lrc").read_bytes(), b"lyrics")
                self.assertFalse(directory.exists())

    def test_lease_publish_failure_can_be_recovered_after_release(self):
        directory = self.stage()
        with recovery.staging_lease(directory, "track") as lease:
            audio = self.audio(directory)
            (directory / "song.lrc").write_bytes(b"lyrics")
            recovery.mark_ready(directory, audio)
            original = recovery._publish
            def interrupted(source, destination, expected):
                if destination.suffix == ".lrc":
                    raise OSError("interrupted")
                original(source, destination, expected)
            with patch.object(recovery, "_publish", side_effect=interrupted):
                with self.assertRaisesRegex(OSError, "interrupted"):
                    lease.publish()
            self.assertTrue(audio.exists())
        result = Path(recovery.recover_staging(directory))
        self.assertEqual(result.name, "song (1).wav")
        self.assertEqual((self.root / "song (1).lrc").read_bytes(), b"lyrics")

    def test_crashed_lease_publisher_leaves_ready_originals(self):
        directory = self.stage()
        script = (
            "import os, sys, wave; from pathlib import Path; from core import staging_recovery as r\n"
            "directory = Path(sys.argv[1])\n"
            "with r.staging_lease(directory, 'track') as lease:\n"
            "    audio = directory / 'song.wav'\n"
            "    with wave.open(str(audio), 'wb') as out:\n"
            "        out.setparams((1, 2, 44100, 0, 'NONE', 'not compressed'))\n"
            "        out.writeframes(b'\\x00\\x01' * 100000)\n"
            "    (directory / 'song.lrc').write_bytes(b'lyrics')\n"
            "    r.mark_ready(directory, audio)\n"
            "    link = os.link\n"
            "    def crash(source, destination):\n"
            "        link(source, destination)\n"
            "        os._exit(42)\n"
            "    r.os.link = crash\n"
            "    lease.publish()\n"
        )
        result = subprocess.run([sys.executable, "-c", script, str(directory)],
                                cwd=Path(__file__).resolve().parents[1], capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 42, result.stderr)
        self.assertTrue((directory / "song.wav").exists())
        self.assertTrue((directory / "song.lrc").exists())
        self.assertEqual(recovery.scan_abandoned_staging(self.root)[0]["state"], "ready")
        recovered = Path(recovery.recover_staging(directory))
        self.assertEqual(recovered.name, "song (1).wav")
        self.assertEqual((self.root / "song (1).lrc").read_bytes(), b"lyrics")

    def test_lyrics_collision_during_publication_is_preserved_on_retry(self):
        directory, audio = self.ready(lyrics="adjacent")
        original = audio.read_bytes()
        link = os.link

        def race(source, destination):
            if Path(destination).suffix == ".lrc":
                Path(destination).write_bytes(b"concurrent user lyrics")
            return link(source, destination)

        with patch.object(recovery.os, "link", side_effect=race):
            with self.assertRaises(FileExistsError):
                recovery.recover_staging(directory)
        self.assertEqual(audio.read_bytes(), original)
        result = Path(recovery.recover_staging(directory))
        self.assertEqual(result.name, "song (1).wav")
        self.assertEqual((self.root / "song.wav").read_bytes(), original)
        self.assertEqual((self.root / "song.lrc").read_bytes(), b"concurrent user lyrics")
        self.assertEqual((self.root / "song (1).lrc").read_text(),
                         "[00:00.00] Offline lyrics")

    def test_failed_publication_does_not_leave_partial_destination(self):
        directory, audio = self.ready()
        original = audio.read_bytes()
        with patch.object(recovery.os, "link", side_effect=OSError("unavailable")):
            with patch.object(recovery.os, "rename", side_effect=OSError("unavailable")) as rename:
                with self.assertRaisesRegex(OSError, "unavailable"):
                    recovery.recover_staging(directory)
        self.assertEqual(rename.call_count, int(os.name == "nt"))
        self.assertEqual(audio.read_bytes(), original)
        self.assertTrue((directory / recovery.PUBLICATION_MARKER).exists())
        self.assertFalse((self.root / audio.name).exists())
        self.assertEqual(list(directory.glob(".publish-*")), [])

    def test_link_collision_does_not_use_rename_fallback(self):
        directory, audio = self.ready()
        link = os.link
        collided = []

        def race(source, destination):
            if not collided:
                collided.append(destination)
                Path(destination).write_bytes(b"concurrent user file")
            return link(source, destination)

        with patch.object(recovery.os, "link", side_effect=race):
            with patch.object(recovery.os, "rename") as rename:
                result = Path(recovery.recover_staging(directory))
        rename.assert_not_called()
        self.assertEqual(result.name, "song (1).wav")
        self.assertEqual(Path(collided[0]).read_bytes(), b"concurrent user file")

    def test_scan_nested_output_folder(self):
        output = self.root / "album"
        output.mkdir()
        directory = self.stage(root=output)
        with recovery.staging_lease(directory, "nested"):
            audio = self.audio(directory)
            recovery.mark_ready(directory, audio)
        item, = recovery.scan_abandoned_staging(self.root)
        self.assertEqual(item["directory"], str(directory))
        self.assertEqual(Path(recovery.recover_staging(directory)).parent, output)

    def test_tampered_markers_refuse_discard_and_recovery(self):
        for marker_name in (recovery.READY_MARKER, recovery.PUBLICATION_MARKER):
            with self.subTest(marker=marker_name):
                directory, audio = self.ready(".flacify-" + marker_name[1:])
                if marker_name == recovery.READY_MARKER:
                    self.mutate(directory / marker_name,
                                lambda data: data["audio"].update(basename="../escape.wav"))
                else:
                    owner = json.loads((directory / recovery.OWNER_MARKER).read_text())
                    (directory / marker_name).write_text(json.dumps({
                        "token": owner["token"], "basename": "../escape.wav"}), encoding="utf-8")
                for action in (recovery.recover_staging, recovery.discard_staging):
                    with self.assertRaises(ValueError):
                        action(directory)
                self.assertTrue(audio.exists())

    def test_corrupt_payload_still_allows_explicit_discard(self):
        directory, audio = self.ready()
        audio.write_bytes(b"corrupted")
        recovery.discard_staging(directory)
        self.assertFalse(directory.exists())

    def test_discard_after_nested_payload_was_removed_during_cleanup(self):
        directory, _ = self.ready(lyrics="nested")
        shutil.rmtree(directory / "lyrics")
        self.assertEqual(recovery.scan_abandoned_staging(self.root)[0]["state"], "invalid")
        recovery.discard_staging(directory)
        self.assertFalse(directory.exists())

    def test_recovery_rechecks_integrity_after_scan(self):
        directory, audio = self.ready()
        self.assertEqual(recovery.scan_abandoned_staging(self.root)[0]["state"], "ready")
        audio.write_bytes(b"changed after scan")
        with self.assertRaises(ValueError):
            recovery.recover_staging(directory)
        self.assertTrue(audio.exists())

    def test_publication_checks_copied_bytes(self):
        directory, audio = self.ready()
        with patch.object(recovery.shutil, "copyfileobj", side_effect=lambda incoming, output: output.write(b"corrupt copy")):
            with self.assertRaisesRegex(ValueError, "changed during publication"):
                recovery.recover_staging(directory)
        self.assertTrue(audio.exists())
        self.assertFalse((self.root / audio.name).exists())

    def test_collision_created_during_publication_is_not_overwritten(self):
        directory, _ = self.ready()
        link = os.link
        collided = []

        def race(source, destination):
            if not collided:
                collided.append(destination)
                Path(destination).write_bytes(b"concurrent user file")
            return link(source, destination)

        with patch.object(recovery.os, "link", side_effect=race):
            result = Path(recovery.recover_staging(directory))
        self.assertEqual(result.name, "song (1).wav")
        self.assertEqual((self.root / "song.wav").read_bytes(), b"concurrent user file")

    def directory_link(self, link, target):
        if os.name == "nt":
            result = subprocess.run(["cmd.exe", "/c", "mklink", "/J", str(link), str(target)],
                                    capture_output=True, timeout=10)
            if result.returncode:
                self.fail(result.stderr.decode(errors="replace"))
            self.addCleanup(lambda: os.rmdir(link) if os.path.lexists(link) else None)
        else:
            link.symlink_to(target, target_is_directory=True)

    def test_junction_or_symlink_escape_is_not_scanned_or_deleted(self):
        outside = self.root / "outside"
        outside.mkdir()
        directory = self.stage(root=outside)
        with recovery.staging_lease(directory, "outside"):
            self.audio(directory)
        output = self.root / "output"
        output.mkdir()
        link = output / ".flacify-escape"
        self.directory_link(link, directory)
        self.assertEqual(recovery.scan_abandoned_staging(output), [])
        for action in (recovery.recover_staging, recovery.discard_staging):
            with self.assertRaises(ValueError):
                action(link)
        self.assertTrue((directory / "song.wav").exists())

    def test_adjacent_publication_ignores_unrelated_lyrics_junction(self):
        directory, _ = self.ready(lyrics="adjacent")
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "keep").write_bytes(b"untouched")
        self.directory_link(self.root / "lyrics", outside)
        result = Path(recovery.recover_staging(directory))
        self.assertEqual(result.name, "song.wav")
        self.assertEqual((self.root / "song.lrc").read_text(), "[00:00.00] Offline lyrics")
        self.assertEqual((outside / "keep").read_bytes(), b"untouched")
        self.assertFalse((outside / "song.lrc").exists())

    def test_link_inside_stage_or_lyrics_output_is_refused(self):
        directory, audio = self.ready(lyrics="nested")
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "keep").write_bytes(b"untouched")
        link = directory / "escape"
        self.directory_link(link, outside)
        for action in (recovery.recover_staging, recovery.discard_staging):
            with self.assertRaises(ValueError):
                action(directory)
        os.rmdir(link) if os.name == "nt" else link.unlink()
        self.directory_link(self.root / "lyrics", outside)
        with self.assertRaises(ValueError):
            recovery.recover_staging(directory)
        self.assertTrue(audio.exists())
        self.assertEqual((outside / "keep").read_bytes(), b"untouched")

    def test_hardlinked_payload_is_refused(self):
        directory, audio = self.ready()
        outside = self.root / "outside.wav"
        os.link(audio, outside)
        for action in (recovery.recover_staging, recovery.discard_staging):
            with self.assertRaises(ValueError):
                action(directory)
        self.assertTrue(outside.exists())

    def test_crashed_subprocess_lease_is_abandoned(self):
        directory = self.stage()
        script = (
            "import os, sys; from core.staging_recovery import staging_lease; "
            "lease = staging_lease(sys.argv[1], 'crashed'); lease.__enter__(); os._exit(0)"
        )
        result = subprocess.run([sys.executable, "-c", script, str(directory)],
                                cwd=Path(__file__).resolve().parents[1], capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        item, = recovery.scan_abandoned_staging(self.root)
        self.assertEqual(item["state"], "incomplete")
        self.assertEqual(item["track_id"], "crashed")
        recovery.discard_staging(directory)

    def test_scan_abandoned_staging_resilient_to_unreadable_directory(self):
        directory, _ = self.ready(".flacify-valid")
        unreadable = self.root / "unreadable_dir"
        unreadable.mkdir()

        orig_iterdir = Path.iterdir

        def mock_iterdir(self_path, *args, **kwargs):
            if unreadable.name in str(self_path):
                raise PermissionError("Access denied")
            return orig_iterdir(self_path, *args, **kwargs)

        with patch.object(Path, "iterdir", mock_iterdir):
            items = recovery.scan_abandoned_staging(self.root)
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["state"], "ready")

    def test_scan_abandoned_staging_recursion_depth_limit(self):
        curr = self.root
        for i in range(12):
            curr = curr / f"level_{i}"
            curr.mkdir()
        deep_stage = curr / ".flacify-deep"
        deep_stage.mkdir()
        with recovery.staging_lease(deep_stage, "deep"):
            audio = self.audio(deep_stage)
            recovery.mark_ready(deep_stage, audio)
        items = recovery.scan_abandoned_staging(self.root)
        self.assertEqual(items, [])

    def test_sync_dir_tolerates_expected_fsync_errors(self):
        with patch("os.name", "posix"), \
             patch("os.open", return_value=42), \
             patch("os.close") as mock_close:
            for code in (errno.EINVAL, errno.EBADF, errno.ENOTSUP, errno.EACCES, errno.EPERM):
                with patch("os.fsync", side_effect=OSError(code, "ignored")):
                    recovery._sync_dir(self.root)
                mock_close.assert_called_with(42)

            with patch("os.fsync", side_effect=OSError(errno.EIO, "io error")):
                with self.assertRaises(OSError):
                    recovery._sync_dir(self.root)


if __name__ == "__main__":
    unittest.main()