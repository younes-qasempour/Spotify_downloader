import os
import sys
import tempfile

# Add project root to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.archive import ArchiveManager
from core.spotify_client import TrackMetadata

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

    # 6. Test delete playlist
    archive.delete_saved_playlist("test12345")
    print("Step 9: Deleted playlist.", flush=True)
    assert archive.get_saved_playlist("test12345") is None
    assert len(archive.get_saved_playlist_tracks("test12345")) == 0

    if os.path.exists(db_path):
        try: os.remove(db_path)
        except: pass

    print("ALL ARCHIVE SAVED PLAYLIST TESTS PASSED SUCCESSFULLY!", flush=True)

if __name__ == "__main__":
    run_tests()
