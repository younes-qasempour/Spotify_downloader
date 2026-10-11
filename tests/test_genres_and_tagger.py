import os
import tempfile
import unittest

from core.genre import GenreResolver, format_genre_token
from core.archive import ArchiveManager
from core.tagger import AudioTagger
from core.spotify_client import TrackMetadata


class TestGenreAndArchive(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.cache_path = os.path.join(self.temp_dir.name, "genre_cache.json")
        self.db_path = os.path.join(self.temp_dir.name, "test_archive.db")
        # Reset singletons for testing
        GenreResolver._instance = None
        ArchiveManager._instance = None

    def tearDown(self):
        GenreResolver._instance = None
        ArchiveManager._instance = None
        self.temp_dir.cleanup()

    def test_format_genre_token(self):
        self.assertEqual(format_genre_token("pop"), "Pop")
        self.assertEqual(format_genre_token("j-pop"), "J-Pop")
        self.assertEqual(format_genre_token("synth-pop"), "Synthpop")
        self.assertEqual(format_genre_token("hip-hop/rap"), "Hip-Hop/Rap")

    def test_genre_resolver_caching_and_atomic_save(self):
        resolver = GenreResolver()
        resolver._cache_file = self.cache_path

        # Seed in-memory track cache
        resolver._track_cache["test_artist - test_song"] = ["Alternative Rock", "Grunge"]
        resolver._dirty = True
        resolver.save_cache()

        self.assertTrue(os.path.exists(self.cache_path))
        self.assertFalse(os.path.exists(self.cache_path + ".tmp"))

        # Reload in a new resolver instance
        GenreResolver._instance = None
        resolver2 = GenreResolver()
        resolver2._cache_file = self.cache_path
        resolver2._load_cache()

        res = resolver2.resolve(artist="test_artist", title="test_song")
        self.assertEqual(res, ["Alternative Rock", "Grunge"])

    def test_archive_wal_mode_and_genre_filtering(self):
        archive = ArchiveManager(db_path=self.db_path)

        # Check PRAGMA journal_mode is WAL
        conn = archive._get_connection()
        c = conn.cursor()
        c.execute("PRAGMA journal_mode;")
        mode = c.fetchone()[0]
        self.assertEqual(mode.lower(), "wal")
        conn.close()

        # Create dummy files on disk
        f1 = os.path.join(self.temp_dir.name, "dummy1.flac")
        f2 = os.path.join(self.temp_dir.name, "dummy2.flac")
        with open(f1, "wb") as f:
            f.write(b"FLAC_DATA_1")
        with open(f2, "wb") as f:
            f.write(b"FLAC_DATA_2")

        t1 = TrackMetadata(id="s1", title="Song 1", artists=["Artist 1"], album="Album 1")
        t2 = TrackMetadata(id="s2", title="Song 2", artists=["Artist 2"], album="Album 2")

        # Add tracks with genres
        ok1 = archive.add_track(
            track=t1,
            file_path=f1,
            quality_badge="FLAC 16",
            source_type="Musilon",
            genre="Classic Rock; Hard Rock"
        )
        self.assertTrue(ok1)

        ok2 = archive.add_track(
            track=t2,
            file_path=f2,
            quality_badge="FLAC 16",
            source_type="Musilon",
            genre="Pop; Dance Pop"
        )
        self.assertTrue(ok2)

        genres = archive.get_all_genres()
        self.assertIn("Classic Rock", genres)
        self.assertIn("Hard Rock", genres)
        self.assertIn("Pop", genres)
        self.assertIn("Dance Pop", genres)

        # Filter by genre
        rock_tracks = archive.get_all_tracks(genre_filter="Classic Rock")
        self.assertEqual(len(rock_tracks), 1)
        self.assertEqual(rock_tracks[0]["title"], "Song 1")

        pop_tracks = archive.get_all_tracks(genre_filter="Pop")
        self.assertEqual(len(pop_tracks), 1)
        self.assertEqual(pop_tracks[0]["title"], "Song 2")

    def test_collection_and_playlist_genre_filtering(self):
        archive = ArchiveManager(db_path=self.db_path)
        f1 = os.path.join(self.temp_dir.name, "song1.flac")
        f2 = os.path.join(self.temp_dir.name, "song2.flac")
        with open(f1, "wb") as f:
            f.write(b"DATA1")
        with open(f2, "wb") as f:
            f.write(b"DATA2")

        t1 = TrackMetadata(id="t1", title="Rock Song", artists=["Rocker"], album="Rock Album", collection_name="Rock Album", collection_type="album")
        t2 = TrackMetadata(id="t2", title="Pop Song", artists=["Popper"], album="Pop Album", collection_name="Pop Album", collection_type="album")

        archive.add_track(t1, f1, "FLAC 16", "Musilon", genre="Alternative Rock")
        archive.add_track(t2, f2, "FLAC 16", "Musilon", genre="Synthpop")

        # Test get_albums with genre_filter
        rock_albums = archive.get_albums(genre_filter="Rock")
        self.assertEqual(len(rock_albums), 1)
        self.assertEqual(rock_albums[0]["name"], "Rock Album")
        self.assertEqual(rock_albums[0]["genre"], "Alternative Rock")

        pop_albums = archive.get_albums(genre_filter="Synthpop")
        self.assertEqual(len(pop_albums), 1)
        self.assertEqual(pop_albums[0]["name"], "Pop Album")

        # Test get_collection_tracks with genre_filter
        col_tracks = archive.get_collection_tracks("Rock Album", "album", genre_filter="Rock")
        self.assertEqual(len(col_tracks), 1)
        self.assertEqual(col_tracks[0]["title"], "Rock Song")

        empty_col = archive.get_collection_tracks("Rock Album", "album", genre_filter="Pop")
        self.assertEqual(len(empty_col), 0)


if __name__ == "__main__":
    unittest.main()

