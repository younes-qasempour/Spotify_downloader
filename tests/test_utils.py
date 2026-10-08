import unittest
from core.utils import (
    sanitize_filename,
    clean_watermarks,
    format_duration,
    format_bytes,
    ensure_ffmpeg
)


class TestUtils(unittest.TestCase):
    def test_clean_watermarks(self):
        self.assertEqual(clean_watermarks("Song Title [Musilon]"), "Song Title")
        self.assertEqual(clean_watermarks("Artist - (musilon.com)"), "Artist -")
        self.assertEqual(clean_watermarks("Pristine Song"), "Pristine Song")

    def test_sanitize_filename(self):
        self.assertEqual(sanitize_filename("Artist / Title *?"), "Artist  Title")
        self.assertEqual(sanitize_filename("...Leading and Trailing Dots..."), "Leading and Trailing Dots")
        self.assertEqual(sanitize_filename("A" * 120, max_length=50), "A" * 50)
        self.assertEqual(sanitize_filename(""), "unnamed_track")

    def test_format_duration(self):
        self.assertEqual(format_duration(0), "00:00")
        self.assertEqual(format_duration(65000), "01:05")
        self.assertEqual(format_duration(215000), "03:35")

    def test_format_bytes(self):
        self.assertEqual(format_bytes(0), "0.0 B")
        self.assertEqual(format_bytes(1024), "1.0 KB")
        self.assertEqual(format_bytes(1048576), "1.0 MB")
        self.assertEqual(format_bytes(1073741824), "1.0 GB")

    def test_ensure_ffmpeg(self):
        ff = ensure_ffmpeg()
        # Ensure it returns a string if ffmpeg exists in PATH or bin
        if ff:
            self.assertTrue(isinstance(ff, str))


if __name__ == "__main__":
    unittest.main()
