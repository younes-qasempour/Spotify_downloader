import os
import sys
import tempfile
import shutil

# Add project root to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.archive import ArchiveManager, normalize_path
from core.spotify_client import TrackMetadata
from core.config import config
from core.utils import sanitize_filename

def run_tests():
    print("Step 1: Starting test...", flush=True)
    db_path = os.path.join(os.path.dirname(__file__), "test_temp.db")
    if os.path.exists(db_path):
        try: os.remove(db_path)
        except: pass

    # Reset singleton if needed
    ArchiveManager._instance = None
    archive = ArchiveManager(db_path=db_path)
    print("Step 2: Archive initialized.", flush=True)

    tracks = [
        TrackMetadata(
            id=f"tr_{i}",
            title=f"Song {i}",
            artists=["Artist A"],
            album="Album X",
            duration_ms=210000,
            track_number=i,
            disc_number=1,
            isrc=f"ISRC{i}",
            cover_url="",
            collection_name="My Chill Playlist",
            collection_type="playlist"
        )
        for i in range(1, 101)
    ]
    print(f"Step 3: Created {len(tracks)} mock tracks.", flush=True)

    # 1. Save playlist
    res = archive.save_playlist(
        name="My Chill Playlist",
        spotify_url="https://open.spotify.com/playlist/test12345",
        cover_url="",
        tracks=tracks,
        playlist_id="test12345"
    )
    print("Step 4: Playlist saved, res:", res.get("total_tracks"), flush=True)
    assert res["total_tracks"] == 100, f"Expected 100 tracks, got {res['total_tracks']}"
    assert res["pending_count"] == 100, f"Expected 100 pending, got {res['pending_count']}"
    assert res["downloaded_count"] == 0

    # 2. Test batch query
    batch_50 = archive.get_saved_playlist_tracks("test12345", status="pending", limit=50)
    print("Step 5: Got batch 50:", len(batch_50), flush=True)
    assert len(batch_50) == 50
    assert batch_50[0]["spotify_id"] == "tr_1"
    assert batch_50[49]["spotify_id"] == "tr_50"

    # 3. Mark queued
    ids_to_queue = [t["spotify_id"] for t in batch_50[:25]]
    archive.mark_saved_tracks_queued("test12345", ids_to_queue)
    queued_tracks = archive.get_saved_playlist_tracks("test12345", status="queued")
    print("Step 6: Queued tracks count:", len(queued_tracks), flush=True)
    assert len(queued_tracks) == 25

    # 4. Mark downloaded with specific quality badges
    archive.mark_saved_track_downloaded("tr_1", "C:/music/song1.flac", "FLAC 16", "Musilon")
    archive.mark_saved_track_downloaded("tr_2", "C:/music/song2.opus", "YTM Opus", "YouTube Music")
    
    downloaded_tracks = archive.get_saved_playlist_tracks("test12345", status="downloaded")
    assert len(downloaded_tracks) == 2
    assert downloaded_tracks[0]["quality_badge"] == "FLAC 16"
    assert downloaded_tracks[0]["source_type"] == "Musilon"
    assert downloaded_tracks[1]["quality_badge"] == "YTM Opus"
    assert downloaded_tracks[1]["source_type"] == "YouTube Music"

    pl = archive.get_saved_playlist("test12345")
    print("Step 7: Downloaded count:", pl["downloaded_count"], flush=True)
    assert pl["downloaded_count"] == 2
    assert pl["pending_count"] == 98
    assert pl["progress_percent"] == 2.0

    # 5. Test search filter
    search_res = archive.get_saved_playlist_tracks("test12345", search_query="Song 42")
    print("Step 8: Search res:", len(search_res), flush=True)
    assert len(search_res) == 1
    assert search_res[0]["title"] == "Song 42"

    # 5b. Test manual rename and edit playlist data
    ok_edit = archive.update_saved_playlist(
        "test12345",
        name="Renamed Chill Playlist",
        spotify_url="https://open.spotify.com/playlist/custom_link",
        cover_url="https://example.com/cover.jpg"
    )
    assert ok_edit is True
    edited_pl = archive.get_saved_playlist("test12345")
    assert edited_pl is not None
    assert edited_pl["name"] == "Renamed Chill Playlist"
    assert edited_pl["spotify_url"] == "https://open.spotify.com/playlist/custom_link"
    assert edited_pl["cover_url"] == "https://example.com/cover.jpg"
    print("Step 8b: Playlist renamed and metadata edited successfully.", flush=True)

    # 5c. Test edit track metadata
    ok_track_edit = archive.update_saved_playlist_track(
        "test12345",
        "tr_1",
        title="Custom Song Title 1",
        artist="Custom Artist A",
        album="Custom Album Z"
    )
    assert ok_track_edit is True
    tr_after = [t for t in archive.get_saved_playlist_tracks("test12345") if t["spotify_id"] == "tr_1"][0]
    assert tr_after["title"] == "Custom Song Title 1"
    assert tr_after["artist"] == "Custom Artist A"
    assert tr_after["album"] == "Custom Album Z"
    print("Step 8c: Track metadata edited successfully.", flush=True)

    # 5d. Test rename collection with physical directory on disk and DB sync
    temp_dir = tempfile.mkdtemp()
    orig_out_dir = config.get("download.output_dir", "")
    config.set("download.output_dir", temp_dir)
    try:
        old_folder_name = sanitize_filename("Renamed Chill Playlist", max_length=50)
        old_dir_path = os.path.join(temp_dir, old_folder_name)
        os.makedirs(old_dir_path, exist_ok=True)

        mock_audio_file = os.path.join(old_dir_path, "song1.flac")
        with open(mock_audio_file, "wb") as f:
            f.write(b"fLaCmockdata")

        norm_audio_path = normalize_path(mock_audio_file)

        # Associate track tr_1 in downloaded_tracks and saved_playlist_tracks with this real file on disk
        tracks[0].collection_name = "Renamed Chill Playlist"
        tracks[0].collection_type = "playlist"
        archive.add_track(tracks[0], norm_audio_path, "FLAC 16", "Musilon")
        archive.mark_saved_track_downloaded("tr_1", norm_audio_path, "FLAC 16", "Musilon")

        # Execute rename collection
        ok_col = archive.rename_collection("Renamed Chill Playlist", "Brand New Collection Name")
        assert ok_col is True

        new_folder_name = sanitize_filename("Brand New Collection Name", max_length=50)
        new_dir_path = os.path.join(temp_dir, new_folder_name)

        # Verify disk directory movement
        assert not os.path.exists(old_dir_path), "Old collection directory should no longer exist"
        assert os.path.isdir(new_dir_path), "New collection directory should exist on disk"
        assert os.path.isfile(os.path.join(new_dir_path, "song1.flac")), "Track file should have moved into new directory"

        # Verify database playlist name updated
        pl_renamed = archive.get_saved_playlist("test12345")
        assert pl_renamed["name"] == "Brand New Collection Name"

        # Verify file_path in saved_playlist_tracks updated to new directory
        tr_after_rename = [t for t in archive.get_saved_playlist_tracks("test12345") if t["spotify_id"] == "tr_1"][0]
        expected_new_file = normalize_path(os.path.join(new_dir_path, "song1.flac"))
        assert tr_after_rename["file_path"] == expected_new_file, f"Expected {expected_new_file}, got {tr_after_rename['file_path']}"

        # Verify file_path in downloaded_tracks updated to new directory
        dt_track = archive.get_track_by_path(expected_new_file)
        assert dt_track is not None
        assert dt_track["spotify_id"] == "tr_1"
        assert dt_track["collection_name"] == "Brand New Collection Name"

        print("Step 8d: Collection renamed successfully with physical disk directory move and database path sync verified.", flush=True)
    finally:
        config.set("download.output_dir", orig_out_dir)
        shutil.rmtree(temp_dir, ignore_errors=True)

    # 6. Test delete playlist
    archive.delete_saved_playlist("test12345")
    print("Step 9: Deleted playlist.", flush=True)
    assert archive.get_saved_playlist("test12345") is None
    assert len(archive.get_saved_playlist_tracks("test12345")) == 0

    if os.path.exists(db_path):
        try: os.remove(db_path)
        except: pass

    print("ALL ARCHIVE SAVED PLAYLIST TESTS PASSED SUCCESSFULLY!", flush=True)

import unittest

class TestSavedPlaylists(unittest.TestCase):
    def test_saved_playlists_lifecycle(self):
        run_tests()

if __name__ == "__main__":
    unittest.main()
