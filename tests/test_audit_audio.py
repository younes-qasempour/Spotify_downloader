import io
import gzip
import os
import shutil
import subprocess
import sys
import tempfile
import time
import typing
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from PIL import Image
from mutagen.flac import FLAC
from mutagen.id3 import ID3, TIT2

from core import utils, transcoder
from core.exceptions import TranscodeError
from core.ytdlp_engine import YtdlpEngine, YtdlpSource


class AudioFixtures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixtures = tempfile.TemporaryDirectory(dir=os.path.dirname(__file__))
        cls.addClassCleanup(cls.fixtures.cleanup)
        cls.ffmpeg = utils.ensure_ffmpeg()
        if not cls.ffmpeg:
            raise RuntimeError("Offline audio audit requires the bundled FFmpeg")
        cls.wav = Path(cls.fixtures.name) / "fixture.wav"
        with wave.open(str(cls.wav), "wb") as audio:
            audio.setparams((1, 2, 44100, 0, "NONE", "not compressed"))
            audio.writeframes(bytes(range(256)) * 700)
        for ext in ("mp3", "flac"):
            proc = subprocess.run(
                [cls.ffmpeg, "-nostdin", "-y", "-i", str(cls.wav),
                 str(cls.wav.with_suffix("." + ext))],
                capture_output=True, timeout=20
            )
            if proc.returncode:
                raise RuntimeError(proc.stderr.decode("utf-8", errors="replace"))

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=os.path.dirname(__file__))
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def audio(self, ext="mp3", name="song"):
        dest = self.root / (name + "." + ext)
        shutil.copy2(self.wav.with_suffix("." + ext), dest)
        return dest


class TestAudioPaths(unittest.TestCase):
    def test_reserved_windows_names(self):
        for name in ("CON", "con.mp3", "NUL", "AUX.flac", "COM1", "LPT9.wav", "COM\u00b9.mp3", "CON .txt"):
            with self.subTest(name=name):
                self.assertNotEqual(utils.sanitize_filename(name).upper(), name.upper())

    def test_reserved_name_created_by_truncation(self):
        self.assertNotEqual(utils.sanitize_filename("CONcert", 3).upper(), "CON")
        self.assertTrue(utils.sanitize_filename(". . .", 1))

    def test_riff_is_not_necessarily_wave(self):
        self.assertIsNone(utils.detect_audio_header(b"RIFF\x00\x10\x00\x00WEBP"))
        self.assertIsNone(utils.detect_audio_header(b"RIFF\x00\x10\x00\x00AVI "))
        self.assertEqual(utils.detect_audio_header(b"RIFF\x00\x10\x00\x00WAVE"), "wav")

    def test_template_stays_relative(self):
        path = utils.sanitize_path_template(r"C:\..\CON\song")
        self.assertFalse(os.path.isabs(path))
        self.assertNotIn("..", Path(path).parts)
        self.assertNotIn("CON", Path(path).parts)


class TestAudioProcesses(unittest.TestCase):
    def test_helper_precancel_does_not_spawn(self):
        with patch("core.utils.subprocess.Popen") as popen:
            with self.assertRaises(utils.AudioProcessingCancelled):
                utils.run_ffmpeg([sys.executable, "-c", "pass"], cancel_check=lambda: True)
            popen.assert_not_called()

    def test_helper_cancels_and_reaps_real_child(self):
        real_popen = subprocess.Popen
        children = []

        def spawn(*args, **kwargs):
            child = real_popen(*args, **kwargs)
            children.append(child)
            return child

        started = time.monotonic()
        with patch("core.utils.subprocess.Popen", side_effect=spawn):
            with self.assertRaises(utils.AudioProcessingCancelled):
                utils.run_ffmpeg(
                    [sys.executable, "-c", "import time; time.sleep(30)"],
                    cancel_check=lambda: time.monotonic() - started > 0.3
                )
        self.assertTrue(children)
        self.assertIsNotNone(children[0].poll())
        self.assertLess(time.monotonic() - started, 5)

    def test_helper_timeout_and_pipe_drain(self):
        with self.assertRaises(subprocess.TimeoutExpired):
            utils.run_ffmpeg([sys.executable, "-c", "import time; time.sleep(30)"], timeout=0.2)
        result = utils.run_ffmpeg([
            sys.executable, "-c", "import sys; sys.stderr.write('x' * 200000); print('ok')"
        ], timeout=5)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "ok")
        self.assertEqual(len(result.stderr), 200000)

    def test_cancellation_callback_error_reaps_child(self):
        children = []
        real_popen = subprocess.Popen

        def spawn(*args, **kwargs):
            child = real_popen(*args, **kwargs)
            children.append(child)
            return child

        check = MagicMock(side_effect=[False, ValueError("callback failed")])
        with patch("core.utils.subprocess.Popen", side_effect=spawn):
            with self.assertRaisesRegex(ValueError, "callback failed"):
                utils.run_ffmpeg([sys.executable, "-c", "import time; time.sleep(30)"], cancel_check=check)
        self.assertIsNotNone(children[0].poll())


class TestAudioInstaller(unittest.TestCase):
    def test_bad_download_preserves_existing_executable_and_archive(self):
        with tempfile.TemporaryDirectory(dir=os.path.dirname(__file__)) as directory:
            exe = Path(directory) / "ffmpeg.exe"
            archive = Path(directory) / "ffmpeg.exe.gz"
            exe.write_bytes(b"protected executable")
            archive.write_bytes(b"protected archive")
            response = io.BytesIO(gzip.compress(b"invalid executable"))
            response.headers = {}
            failed = SimpleNamespace(returncode=1, stderr="invalid executable")
            with patch("core.utils.urllib.request.urlopen", return_value=response), \
                    patch("core.utils.subprocess.run", return_value=failed), \
                    patch("core.utils.run_ffmpeg", return_value=failed):
                self.assertIsNone(utils.download_ffmpeg(directory))
            self.assertEqual(exe.read_bytes(), b"protected executable")
            self.assertEqual(archive.read_bytes(), b"protected archive")
            self.assertEqual(sorted(p.name for p in Path(directory).iterdir()), ["ffmpeg.exe", "ffmpeg.exe.gz"])


class TestAudioTranscoder(AudioFixtures):
    def test_failure_preserves_existing_destination_and_source(self):
        source = self.root / "broken.wav"
        source.write_bytes(b"not audio")
        dest = self.root / "existing.mp3"
        dest.write_bytes(b"protected destination")
        with self.assertRaises(TranscodeError):
            transcoder.transcode_audio(str(source), "mp3", output_file=str(dest))
        self.assertEqual(source.read_bytes(), b"not audio")
        self.assertEqual(dest.read_bytes(), b"protected destination")
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ["broken.wav", "existing.mp3"])

    def test_missing_ffmpeg_does_not_mislabel_copy(self):
        source = self.audio("wav")
        dest = self.root / "converted.mp3"
        with patch("core.transcoder.ensure_ffmpeg", return_value=None):
            result = transcoder.transcode_audio(str(source), "mp3", output_file=str(dest))
        self.assertEqual(result, str(source))
        self.assertFalse(dest.exists())

    def test_transcode_precancel_preserves_source(self):
        source = self.audio("wav")
        before = source.read_bytes()
        with self.assertRaises(utils.AudioProcessingCancelled):
            transcoder.transcode_audio(str(source), "mp3", cancel_check=lambda: True)
        self.assertEqual(source.read_bytes(), before)
        self.assertEqual(list(self.root.iterdir()), [source])

    def test_real_transcode_success(self):
        source = self.audio("wav")
        result = transcoder.transcode_audio(str(source), "mp3", delete_source=False)
        self.assertTrue(source.exists())
        self.assertTrue(utils.is_valid_audio_file(result, min_size=1024)[0])

    def test_transcode_preserves_embedded_artwork(self):
        from core.tagger import AudioTagger
        source = self.audio("flac")
        image = io.BytesIO()
        Image.new("RGB", (8, 8), "red").save(image, format="PNG")
        self.assertTrue(AudioTagger(session=MagicMock()).tag_metadata_in_place(
            str(source), title="Keep", cover_bytes=image.getvalue()
        ))
        result = transcoder.transcode_audio(str(source), "mp3", delete_source=False)
        self.assertEqual(str(ID3(result)["TIT2"]), "Keep")
        self.assertTrue(ID3(result).getall("APIC"))
        with Image.open(io.BytesIO(utils.extract_embedded_cover(result))) as cover:
            self.assertEqual(cover.size, (8, 8))

    def test_cancel_and_timeout_clean_only_owned_partial_output(self):
        for error in (utils.AudioProcessingCancelled("cancelled"), subprocess.TimeoutExpired("ffmpeg", 120)):
            with self.subTest(error=type(error).__name__):
                source = self.audio("wav")
                dest = self.root / "song.mp3"
                dest.write_bytes(b"protected audio")

                def interrupt(cmd, **kwargs):
                    Path(cmd[-1]).write_bytes(b"partial")
                    raise error

                with patch("core.transcoder.run_ffmpeg", side_effect=interrupt):
                    with self.assertRaises(utils.AudioProcessingCancelled if isinstance(error, utils.AudioProcessingCancelled) else TranscodeError):
                        transcoder.transcode_audio(str(source), "mp3", output_file=str(dest))
                self.assertTrue(source.exists())
                self.assertEqual(dest.read_bytes(), b"protected audio")
                self.assertEqual(len(list(self.root.iterdir())), 2)

    def test_explicit_in_place_transcode_is_staged(self):
        source = self.audio("wav")
        result = transcoder.transcode_audio(str(source), "mp3", output_file=str(source))
        self.assertEqual(result, str(source))
        self.assertEqual(utils.detect_audio_header(str(source)), "mp3")


class AudioDownloadFixtures(AudioFixtures):
    def setUp(self):
        super().setUp()
        self.engine = YtdlpEngine()
        self.source = YtdlpSource("offline", "Song", 2, "https://invalid.test/audio", "mp3")
        self.base = str(self.root / "song")

    def download(self, behavior, **kwargs):
        def factory(opts):
            ydl = MagicMock()
            ydl.__enter__.return_value = ydl
            ydl.download.side_effect = lambda urls: behavior(opts, urls)
            return ydl

        with patch("core.ytdlp_engine.yt_dlp.YoutubeDL", side_effect=factory), \
                patch.object(self.engine, "_get_ydl_auth_opts", return_value={}), \
                patch("core.ytdlp_engine.time.sleep"):
            return self.engine.download_track(self.source, self.base, **kwargs)

    def write_download(self, opts, urls):
        dest = Path(opts["outtmpl"].replace("%(ext)s", "mp3").replace("%%", "%"))
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(self.wav.with_suffix(".mp3"), dest)
        opts["progress_hooks"][0]({"status": "finished", "filename": str(dest)})
        return 0


class TestAudioDownload(AudioDownloadFixtures):
    def test_precancel_does_not_delete_other_partial_files(self):
        partial = self.root / "song-other.mp3.part"
        partial.write_bytes(b"protected partial")
        self.assertIsNone(self.download(self.write_download, cancel_check=lambda: True))
        self.assertEqual(partial.read_bytes(), b"protected partial")

    def test_success_preserves_alternate_existing_format(self):
        existing = self.audio("flac")
        before = existing.read_bytes()
        result = self.download(self.write_download)
        self.assertTrue(Path(result).exists())
        self.assertEqual(existing.read_bytes(), before)

    def test_failed_exit_does_not_return_stale_file(self):
        existing = self.audio("mp3")
        before = existing.read_bytes()
        self.assertIsNone(self.download(lambda opts, urls: 1))
        self.assertEqual(existing.read_bytes(), before)

    def test_corrupt_download_is_rejected_and_cleaned(self):
        def corrupt(opts, urls):
            dest = Path(opts["outtmpl"].replace("%(ext)s", "mp3"))
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(b"<html>error</html>" * 10000)
            opts["progress_hooks"][0]({"status": "finished", "filename": str(dest)})
            return 0

        self.assertIsNone(self.download(corrupt))
        self.assertEqual(list(self.root.iterdir()), [])

    def test_cancel_after_download_does_not_publish(self):
        cancelled = [False]

        def complete(opts, urls):
            self.write_download(opts, urls)
            cancelled[0] = True
            return 0

        self.assertIsNone(self.download(complete, cancel_check=lambda: cancelled[0]))
        self.assertEqual(list(self.root.iterdir()), [])

    def test_cancel_after_pause_does_not_report_progress(self):
        cancelled = [False]
        callback = MagicMock()
        result = self.download(
            self.write_download, cancel_check=lambda: cancelled[0],
            pause_wait=lambda: cancelled.__setitem__(0, True), progress_callback=callback
        )
        self.assertIsNone(result)
        callback.assert_not_called()
        self.assertEqual(list(self.root.iterdir()), [])

    def test_retry_does_not_reuse_failed_postprocessor_output(self):
        attempts = []

        def fail_then_empty(opts, urls):
            attempts.append(opts["outtmpl"])
            if len(attempts) == 1:
                self.write_download(opts, urls)
                raise RuntimeError("postprocessing failed")
            return 0

        self.assertIsNone(self.download(fail_then_empty))
        self.assertEqual(len(set(attempts)), 3)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_literal_percent_in_destination(self):
        self.base = str(self.root / "100% (live)")
        result = self.download(self.write_download)
        self.assertEqual(result, self.base + ".mp3")

    def test_postprocessor_hook_checks_cancellation(self):
        cancelled = [False]

        def postprocess(opts, urls):
            self.write_download(opts, urls)
            cancelled[0] = True
            opts["postprocessor_hooks"][0]({"status": "started"})
            self.fail("postprocessing continued despite cancellation")

        self.assertIsNone(self.download(postprocess, cancel_check=lambda: cancelled[0]))
        self.assertEqual(list(self.root.iterdir()), [])


class TestAudioDownloadExtraction(AudioDownloadFixtures):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        for name, codec, extra in (
            ("opus.webm", "libopus", []),
            ("vorbis.webm", "libvorbis", []),
            ("aac.mp4", "aac", []),
            ("dash.m4a", "aac", ["-movflags", "+frag_keyframe+empty_moov"]),
            ("hls.m4a", "aac", ["-f", "mpegts"]),
            ("pcm.mkv", "pcm_s16le", []),
        ):
            result = utils.run_ffmpeg([
                cls.ffmpeg, "-nostdin", "-y", "-i", str(cls.wav),
                "-c:a", codec, "-metadata", "title=Keep title",
                "-metadata", "artist=Keep artist", *extra,
                str(Path(cls.fixtures.name) / name)
            ], timeout=20)
            if result.returncode:
                raise RuntimeError(result.stderr)

    def write_container(self, opts, urls, name="opus.webm", info=None):
        fixture = Path(self.fixtures.name) / name
        dest = Path(opts["outtmpl"].replace("%(ext)s", fixture.suffix[1:]).replace("%%", "%"))
        shutil.copy2(fixture, dest)
        opts["progress_hooks"][0]({
            "status": "finished", "filename": str(dest), "info_dict": info or {}
        })
        return 0

    def test_library_ffmpeg_postprocessing_is_disabled(self):
        options = []

        def complete(opts, urls):
            options.append(opts.copy())
            return self.write_download(opts, urls)

        self.assertIsNotNone(self.download(complete))
        self.assertEqual(options[0].get("postprocessors"), [])
        self.assertEqual(options[0].get("fixup"), "never")

    def test_native_extraction_preserves_audio_and_metadata(self):
        import mutagen

        for name, ext, title_key, artist_key in (
            ("opus.webm", ".opus", "title", "artist"),
            ("vorbis.webm", ".ogg", "title", "artist"),
            ("aac.mp4", ".m4a", "\u00a9nam", "\u00a9ART"),
        ):
            with self.subTest(name=name):
                self.base = str(self.root / name)
                with patch("core.ytdlp_engine.run_ffmpeg", wraps=utils.run_ffmpeg, create=True) as run:
                    result = self.download(lambda opts, urls: self.write_container(opts, urls, name))
                self.assertEqual(result, self.base + ext)
                tags = mutagen.File(result)
                self.assertEqual(tags[title_key], ["Keep title"])
                self.assertEqual(tags[artist_key], ["Keep artist"])
                self.assertEqual(run.call_args_list[0].kwargs["timeout"], 30)
                extraction = run.call_args_list[-1]
                self.assertIn("copy", extraction.args[0])
                self.assertGreater(extraction.kwargs["timeout"], 0)
                self.assertLessEqual(extraction.kwargs["timeout"], 120)
                hashes = []
                for path in (str(Path(self.fixtures.name) / name), result):
                    audio_hash = utils.run_ffmpeg([
                        self.ffmpeg, "-nostdin", "-i", path, "-map", "0:a:0",
                        "-c:a", "copy", "-f", "hash", "-hash", "sha256", "-"
                    ], timeout=20)
                    self.assertEqual(audio_hash.returncode, 0, audio_hash.stderr)
                    hashes.append(audio_hash.stdout.strip())
                self.assertEqual(hashes[0], hashes[1])

    def test_common_audio_is_not_reencoded(self):
        for ext in ("mp3", "flac", "m4a"):
            with self.subTest(ext=ext):
                fixture = self.wav.with_suffix("." + ext) if ext != "m4a" else Path(self.fixtures.name) / "aac.mp4"

                def complete(opts, urls):
                    dest = Path(opts["outtmpl"].replace("%(ext)s", ext))
                    shutil.copy2(fixture, dest)
                    opts["progress_hooks"][0]({"status": "finished", "filename": str(dest)})
                    return 0

                with patch("core.ytdlp_engine.run_ffmpeg", wraps=utils.run_ffmpeg, create=True) as run:
                    result = self.download(complete)
                self.assertEqual(result, self.base + "." + ext)
                self.assertEqual(Path(result).read_bytes(), fixture.read_bytes())
                run.assert_not_called()

    def test_dash_m4a_fixup_uses_bounded_helper(self):
        from mutagen.mp4 import MP4

        with patch("core.ytdlp_engine.run_ffmpeg", wraps=utils.run_ffmpeg, create=True) as run:
            result = self.download(lambda opts, urls: self.write_container(
                opts, urls, "dash.m4a", {"container": "m4a_dash"}
            ))
        self.assertEqual(result, self.base + ".m4a")
        self.assertEqual(MP4(result)["\u00a9nam"], ["Keep title"])
        self.assertTrue(run.called)
        self.assertNotIn(b"moof", Path(result).read_bytes())

    def test_real_ytdlp_local_download_avoids_library_ffmpeg(self):
        import yt_dlp

        real_ydl = yt_dlp.YoutubeDL
        for name, ext, container in (("opus.webm", ".opus", "webm"), ("dash.m4a", ".m4a", "m4a_dash")):
            with self.subTest(name=name):
                fixture = Path(self.fixtures.name) / name

                def factory(opts):
                    ydl = real_ydl({**opts, "enable_file_urls": True, "noprogress": True})
                    urlopen = ydl.urlopen
                    responses = []

                    def open_file(*args, **kwargs):
                        response = urlopen(*args, **kwargs)
                        responses.append(response)
                        return response

                    ydl.urlopen = open_file

                    def download(urls):
                        try:
                            ydl.process_ie_result({
                                "id": "offline", "title": "Offline fixture", "url": fixture.as_uri(),
                                "ext": fixture.suffix[1:], "container": container,
                                "vcodec": "none", "acodec": "opus" if ext == ".opus" else "aac",
                                "extractor": "generic", "extractor_key": "Generic",
                                "webpage_url": fixture.as_uri(),
                            }, download=True)
                        finally:
                            for response in responses:
                                response.close()
                        return 0

                    ydl.download = download
                    return ydl

                with patch("core.ytdlp_engine.yt_dlp.YoutubeDL", side_effect=factory), \
                        patch.object(self.engine, "_get_ydl_auth_opts", return_value={}), \
                        patch("yt_dlp.postprocessor.ffmpeg.Popen.run", side_effect=AssertionError("Unbounded yt-dlp FFmpeg call")), \
                        patch("core.ytdlp_engine.time.sleep"):
                    result = self.engine.download_track(self.source, self.base)
                self.assertEqual(result, self.base + ext)
                self.assertTrue(utils.is_valid_audio_file(result, min_size=1024)[0])
                if ext == ".m4a":
                    self.assertNotIn(b"moof", Path(result).read_bytes())

    def test_hls_transport_stream_in_m4a_is_repaired(self):
        from mutagen.mp4 import MP4

        result = self.download(lambda opts, urls: self.write_container(
            opts, urls, "hls.m4a", {"protocol": "m3u8_native"}
        ))
        self.assertEqual(result, self.base + ".m4a")
        audio = MP4(result)
        self.assertTrue(audio.info.codec.startswith("mp4a"))
        self.assertGreater(audio.info.length, 1)

    def test_unmapped_codec_retains_best_audio_mp3_fallback(self):
        result = self.download(lambda opts, urls: self.write_container(opts, urls, "pcm.mkv"))
        self.assertEqual(result, self.base + ".mp3")
        self.assertEqual(str(ID3(result)["TIT2"]), "Keep title")
        self.assertTrue(utils.is_valid_audio_file(result, min_size=1024)[0])

    def test_missing_ffmpeg_preserves_original_container(self):
        self.engine.ffmpeg_path = None
        with patch("core.ytdlp_engine.ensure_ffmpeg", return_value=None), \
                patch("core.ytdlp_engine.run_ffmpeg", create=True) as run:
            result = self.download(self.write_container)
        self.assertEqual(result, self.base + ".webm")
        self.assertEqual(Path(result).read_bytes(), (Path(self.fixtures.name) / "opus.webm").read_bytes())
        run.assert_not_called()

    def test_processing_cancellation_does_not_retry(self):
        existing = self.root / "song.opus"
        existing.write_bytes(b"protected output")
        with patch("core.ytdlp_engine.run_ffmpeg", side_effect=utils.AudioProcessingCancelled("cancelled"), create=True) as run:
            self.assertIsNone(self.download(self.write_container))
        self.assertEqual(run.call_count, 1)
        self.assertEqual(existing.read_bytes(), b"protected output")
        self.assertEqual(list(self.root.iterdir()), [existing])

    def test_failed_extraction_preserves_existing_output(self):
        existing = self.root / "song.opus"
        existing.write_bytes(b"protected output")
        neighbor = self.root / "song-other.webm.part"
        neighbor.write_bytes(b"protected partial")
        attempts = []

        def fail(cmd, **kwargs):
            if cmd[-1].endswith(".webm"):
                return utils.run_ffmpeg(cmd, **kwargs)
            attempts.append(cmd[-1])
            Path(cmd[-1]).write_bytes(b"partial")
            return SimpleNamespace(returncode=1, stderr="extraction failed")

        with patch("core.ytdlp_engine.run_ffmpeg", side_effect=fail, create=True):
            self.assertIsNone(self.download(self.write_container))
        self.assertEqual(len(set(attempts)), 3)
        self.assertEqual(existing.read_bytes(), b"protected output")
        self.assertEqual(neighbor.read_bytes(), b"protected partial")
        self.assertEqual(set(self.root.iterdir()), {existing, neighbor})

    def test_failed_probe_cannot_publish_download(self):
        with patch("core.ytdlp_engine.run_ffmpeg", return_value=SimpleNamespace(
            returncode=2, stderr="Stream #0:0: Audio: opus"
        ), create=True) as run:
            self.assertIsNone(self.download(self.write_container))
        self.assertEqual(run.call_count, 3)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_success_exit_with_corrupt_extraction_is_rejected(self):
        def corrupt(cmd, **kwargs):
            if cmd[-1].endswith(".webm"):
                return utils.run_ffmpeg(cmd, **kwargs)
            Path(cmd[-1]).write_bytes(b"<html>error</html>" * 1000)
            return SimpleNamespace(returncode=0, stderr="")

        with patch("core.ytdlp_engine.run_ffmpeg", side_effect=corrupt, create=True):
            self.assertIsNone(self.download(self.write_container))
        self.assertEqual(list(self.root.iterdir()), [])

    def test_cancel_during_probe_or_extraction_reaps_real_ffmpeg(self):
        for phase in ("probe", "extract"):
            with self.subTest(phase=phase):
                existing = self.root / "song.opus"
                existing.write_bytes(b"protected output")
                children = []
                real_popen = subprocess.Popen
                started = [None]
                attempts = []

                def spawn(cmd, **kwargs):
                    child = real_popen(cmd, **kwargs)
                    children.append(child)
                    return child

                def blocking(cmd, **kwargs):
                    is_probe = cmd[-1].endswith(".webm")
                    if is_probe and phase == "extract":
                        return utils.run_ffmpeg(cmd, **kwargs)
                    attempts.append(cmd)
                    started[0] = time.monotonic()
                    command = [self.ffmpeg, "-nostdin", "-y", "-re", "-stream_loop", "-1", "-i", str(self.wav)]
                    command += ["-f", "null", "-"] if is_probe else ["-c:a", "libopus", cmd[-1]]
                    with patch("core.utils.subprocess.Popen", side_effect=spawn):
                        return utils.run_ffmpeg(command, **kwargs)

                check = lambda: started[0] is not None and time.monotonic() - started[0] >= 0.3
                with patch("core.ytdlp_engine.run_ffmpeg", side_effect=blocking, create=True):
                    self.assertIsNone(self.download(self.write_container, cancel_check=check))
                self.assertEqual(len(attempts), 1)
                self.assertEqual(len(children), 1)
                self.assertIsNotNone(children[0].poll())
                self.assertLess(time.monotonic() - started[0], 5)
                self.assertEqual(existing.read_bytes(), b"protected output")
                self.assertEqual(list(self.root.iterdir()), [existing])

    def test_extraction_timeout_reaps_child_and_preserves_output(self):
        existing = self.root / "song.opus"
        existing.write_bytes(b"protected output")
        children = []
        real_popen = subprocess.Popen

        def spawn(cmd, **kwargs):
            child = real_popen(cmd, **kwargs)
            children.append(child)
            return child

        def timeout(cmd, **kwargs):
            if cmd[-1].endswith(".webm"):
                return utils.run_ffmpeg(cmd, **kwargs)
            self.assertGreater(kwargs["timeout"], 0)
            self.assertLessEqual(kwargs["timeout"], 120)
            command = [self.ffmpeg, "-nostdin", "-y", "-re", "-stream_loop", "-1",
                       "-i", str(self.wav), "-c:a", "libopus", cmd[-1]]
            with patch("core.utils.subprocess.Popen", side_effect=spawn):
                return utils.run_ffmpeg(command, timeout=0.2, cancel_check=kwargs["cancel_check"])

        with patch("core.ytdlp_engine.run_ffmpeg", side_effect=timeout, create=True):
            self.assertIsNone(self.download(self.write_container))
        self.assertEqual(len(children), 3)
        self.assertTrue(all(child.poll() is not None for child in children))
        self.assertEqual(existing.read_bytes(), b"protected output")
        self.assertEqual(list(self.root.iterdir()), [existing])

    def test_cancel_after_extraction_does_not_publish(self):
        cancelled = [False]
        existing = self.root / "song.opus"
        existing.write_bytes(b"protected output")

        def complete(cmd, **kwargs):
            result = utils.run_ffmpeg(cmd, **kwargs)
            if not cmd[-1].endswith(".webm"):
                cancelled[0] = True
            return result

        with patch("core.ytdlp_engine.run_ffmpeg", side_effect=complete, create=True):
            self.assertIsNone(self.download(self.write_container, cancel_check=lambda: cancelled[0]))
        self.assertEqual(existing.read_bytes(), b"protected output")
        self.assertEqual(list(self.root.iterdir()), [existing])


class TestAudioTagging(AudioFixtures):
    def setUp(self):
        super().setUp()
        from core.tagger import AudioTagger
        self.tagger = AudioTagger(session=MagicMock())
        self.track = SimpleNamespace(
            id="yt_offline", title="Title", artists=["Artist"], artist_str="Artist",
            primary_artist="Artist", album="Album", genres=["Rock"], cover_url="",
            release_date="2026", isrc="", collection_type="album", track_number=1, disc_number=1
        )
        buf = io.BytesIO()
        Image.new("RGB", (8, 8), "red").save(buf, format="PNG")
        self.cover = buf.getvalue()

    def test_annotations_resolve(self):
        typing.get_type_hints(self.tagger.tag_genre_only)
        typing.get_type_hints(self.tagger.embed_lyrics_only)

    def test_synced_lyrics_string(self):
        path = self.audio()
        self.assertTrue(self.tagger.embed_lyrics_only(str(path), "[00:01.00] first\n[00:02.00] next"))
        self.assertIn("\r\n", ID3(path).getall("USLT")[0].text)

    def test_png_cover_mime_roundtrip(self):
        for ext in ("mp3", "flac"):
            with self.subTest(ext=ext):
                path = self.audio(ext)
                self.assertTrue(self.tagger.tag_metadata_in_place(str(path), title="New", cover_bytes=self.cover))
                picture = ID3(path).getall("APIC")[0] if ext == "mp3" else FLAC(path).pictures[0]
                self.assertEqual(picture.mime, "image/png")
                self.assertEqual(utils.extract_embedded_cover(str(path)), self.cover)

    def test_webp_cover_is_converted_not_mislabeled_as_png(self):
        buf = io.BytesIO()
        Image.new("RGB", (8, 8), "blue").save(buf, format="WEBP")
        path = self.audio()
        self.assertTrue(self.tagger.tag_metadata_in_place(str(path), cover_bytes=buf.getvalue()))
        pic = ID3(path).getall("APIC")[0]
        with Image.open(io.BytesIO(pic.data)) as image:
            self.assertIn(image.format, ("JPEG", "PNG"))
            self.assertEqual(pic.mime, Image.MIME[image.format])

    def test_invalid_cover_does_not_replace_existing_art(self):
        path = self.audio()
        self.assertTrue(self.tagger.tag_metadata_in_place(str(path), cover_bytes=self.cover))
        before = path.read_bytes()
        self.assertFalse(self.tagger.tag_metadata_in_place(str(path), cover_bytes=b"<html>error</html>"))
        self.assertEqual(path.read_bytes(), before)

    def test_mp3_failed_save_does_not_predelete_tags(self):
        path = self.audio()
        tags = ID3(path)
        tags.add(TIT2(encoding=3, text="Original"))
        tags.save(path)
        before = path.read_bytes()
        with patch("core.tagger.ID3.save", side_effect=OSError("disk full")):
            self.assertFalse(self.tagger.tag_file(str(path), self.track, embed_art=False))
        self.assertEqual(path.read_bytes(), before)

    def test_mp3_and_flac_preserve_art_and_lyrics_when_not_replaced(self):
        for ext in ("mp3", "flac"):
            with self.subTest(ext=ext):
                path = self.audio(ext)
                self.assertTrue(self.tagger.tag_metadata_in_place(str(path), cover_bytes=self.cover))
                self.assertTrue(self.tagger.embed_lyrics_only(str(path), "existing lyrics"))
                self.assertTrue(self.tagger.tag_file(str(path), self.track, embed_art=False, embed_lyrics=False))
                self.assertEqual(utils.extract_embedded_cover(str(path)), self.cover)
                if ext == "mp3":
                    self.assertEqual(ID3(path).getall("USLT")[0].text, "existing lyrics")
                else:
                    self.assertEqual(FLAC(path)["LYRICS"], ["existing lyrics"])

    def test_unsupported_wav_does_not_modify_or_fetch(self):
        path = self.audio("wav")
        before = path.read_bytes()
        with patch.object(self.tagger, "_resolve_cover_bytes") as cover:
            self.assertFalse(self.tagger.tag_file(str(path), self.track))
            cover.assert_not_called()
        self.assertEqual(path.read_bytes(), before)

    def test_webm_boolean_tagger_does_not_delete_or_remux_source(self):
        path = self.root / "song.webm"
        path.write_bytes(b"protected WebM")
        def remux(cmd, **kwargs):
            Path(cmd[-1]).write_bytes(b"remux" * 1000)
            return SimpleNamespace(returncode=0)
        with patch("subprocess.run", side_effect=remux), \
                patch.object(self.tagger, "_tag_opus", return_value=True):
            self.assertFalse(self.tagger.tag_file(str(path), self.track, embed_art=False))
        self.assertEqual(path.read_bytes(), b"protected WebM")
        self.assertEqual(list(self.root.iterdir()), [path])


class TestAudioNormalization(AudioFixtures):
    def test_precancel_does_not_measure_or_modify(self):
        path = self.audio("flac")
        before = path.read_bytes()
        with patch("core.utils.measure_audio_loudness") as measure:
            with self.assertRaises(utils.AudioProcessingCancelled):
                utils.normalize_audio_loudness(str(path), cancel_check=lambda: True)
            measure.assert_not_called()
        self.assertEqual(path.read_bytes(), before)

    def test_restore_failure_preserves_original(self):
        path = self.audio("flac")
        before = path.read_bytes()

        def convert(cmd, **kwargs):
            shutil.copy2(path, cmd[-1])
            return SimpleNamespace(returncode=0, stderr="")

        with patch("core.utils.measure_audio_loudness", return_value=(-20.0, -2.0)), \
                patch("core.utils.subprocess.run", side_effect=convert), \
                patch("core.utils.run_ffmpeg", side_effect=convert, create=True), \
                patch("mutagen.flac.FLAC.save", side_effect=OSError("disk full")):
            self.assertIsNone(utils.normalize_audio_loudness(str(path), force=True))
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(list(self.root.iterdir()), [path])

    def test_failed_measurement_not_parsed_as_success(self):
        path = self.audio("flac")
        failed = SimpleNamespace(returncode=1, stderr="Integrated loudness:\n I: -18.0 LUFS\nTrue peak:\n Peak: -1.0 dBFS")
        with patch("core.utils.subprocess.run", return_value=failed), \
                patch("core.utils.run_ffmpeg", return_value=failed, create=True):
            self.assertIsNone(utils.measure_audio_loudness(str(path)))

    def test_no_gain_metadata_failure_is_atomic(self):
        path = self.audio("flac")
        before = path.read_bytes()

        def fail_save(audio, *args, **kwargs):
            Path(audio.filename).write_bytes(b"damaged during save")
            raise OSError("disk full")

        with patch("core.utils.measure_audio_loudness", return_value=(-9.0, -1.0)), \
                patch("mutagen.flac.FLAC.save", autospec=True, side_effect=fail_save):
            self.assertIsNone(utils.normalize_audio_loudness(str(path)))
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(list(self.root.iterdir()), [path])

    def test_cancelled_normalization_preserves_legacy_temp_and_original(self):
        path = self.audio("flac")
        before = path.read_bytes()
        legacy_temp = Path(str(path) + ".norm_tmp.flac")
        legacy_temp.write_bytes(b"protected unrelated file")

        def interrupt(cmd, **kwargs):
            Path(cmd[-1]).write_bytes(b"partial")
            raise utils.AudioProcessingCancelled("cancelled")

        with patch("core.utils.measure_audio_loudness", return_value=(-20.0, -2.0)), \
                patch("core.utils.run_ffmpeg", side_effect=interrupt):
            with self.assertRaises(utils.AudioProcessingCancelled):
                utils.normalize_audio_loudness(str(path), force=True)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(legacy_temp.read_bytes(), b"protected unrelated file")
        self.assertEqual(len(list(self.root.iterdir())), 2)

    def test_real_normalization_preserves_mp3_and_flac_metadata(self):
        from core.tagger import AudioTagger
        tagger = AudioTagger(session=MagicMock())
        image = io.BytesIO()
        Image.new("RGB", (8, 8), "red").save(image, format="PNG")
        for ext in ("mp3", "flac"):
            with self.subTest(ext=ext):
                path = self.audio(ext)
                self.assertTrue(tagger.tag_metadata_in_place(str(path), title="Keep", cover_bytes=image.getvalue()))
                self.assertTrue(tagger.embed_lyrics_only(str(path), "Keep lyrics"))
                with patch("core.utils.measure_audio_loudness", return_value=(-20.0, -2.0)):
                    self.assertIsNotNone(utils.normalize_audio_loudness(str(path), force=True))
                self.assertEqual(utils.extract_embedded_cover(str(path)), image.getvalue())
                if ext == "mp3":
                    self.assertEqual(str(ID3(path)["TIT2"]), "Keep")
                    self.assertEqual(ID3(path).getall("USLT")[0].text, "Keep lyrics")
                else:
                    self.assertEqual(FLAC(path)["TITLE"], ["Keep"])
                    self.assertEqual(FLAC(path)["LYRICS"], ["Keep lyrics"])


if __name__ == "__main__":
    unittest.main()