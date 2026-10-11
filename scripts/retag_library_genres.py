import os
import sys
import glob
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

# Ensure repository root is on sys.path
repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

import mutagen
from mutagen.flac import FLAC
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4
from mutagen.oggopus import OggOpus

from core.paths import get_default_download_dir
from core.genre import get_genre_resolver
from core.tagger import AudioTagger
from core.archive import ArchiveManager, normalize_path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("retagger")


def get_existing_genre(fpath: str) -> list:
    ext = os.path.splitext(fpath)[1].lower()
    try:
        if ext == ".flac":
            aud = FLAC(fpath)
            g = aud.get("GENRE") or aud.get("genre")
            if g and any(x.strip() for x in g):
                return [x.strip() for x in g if x.strip()]
        elif ext in (".opus", ".ogg"):
            try:
                aud = OggOpus(fpath)
            except Exception:
                from mutagen.oggvorbis import OggVorbis
                aud = OggVorbis(fpath)
            g = aud.get("GENRE") or aud.get("genre")
            if g and any(x.strip() for x in g):
                return [x.strip() for x in g if x.strip()]
        elif ext == ".mp3":
            aud = MP3(fpath)
            for k in aud.keys():
                if k.startswith("TCON"):
                    t = aud[k]
                    if t and getattr(t, "text", None):
                        genres = [str(x).strip() for x in t.text if str(x).strip()]
                        if genres:
                            return genres
        elif ext == ".m4a":
            aud = MP4(fpath)
            g = aud.get("\xa9gen")
            if g and any(str(x).strip() for x in g):
                return [str(x).strip() for x in g if str(x).strip()]
    except Exception as e:
        logger.debug(f"Error reading genre from {fpath}: {e}")
    return []


def retag_library(root_dir: str = "", max_workers: int = 12):
    if not root_dir:
        root_dir = os.path.join(repo_root, "downloads")

    logger.info(f"Scanning library directory for audio files: {root_dir}")
    audio_files = []
    for ext in ("*.flac", "*.mp3", "*.opus", "*.m4a", "*.ogg"):
        audio_files.extend(glob.glob(os.path.join(root_dir, "**", ext), recursive=True))

    total = len(audio_files)
    logger.info(f"Found {total} audio files on disk.")

    archive = ArchiveManager()
    genre_resolver = get_genre_resolver()
    tagger = AudioTagger()

    # Preload archive db mappings
    conn = archive._get_connection()
    c = conn.cursor()
    c.execute("SELECT file_path, artist, title, album, spotify_id, genre FROM downloaded_tracks")
    db_records = {}
    for r in c.fetchall():
        db_records[normalize_path(r["file_path"])] = {
            "artist": r["artist"],
            "title": r["title"],
            "album": r["album"] or "",
            "spotify_id": r["spotify_id"] or "",
            "genre": r["genre"] or ""
        }
    conn.close()
    logger.info(f"Loaded {len(db_records)} records from archive.db.")

    tasks = []
    already_tagged_count = 0
    needs_tagging = []

    for fpath in audio_files:
        norm_p = normalize_path(fpath)
        existing_g = get_existing_genre(fpath)
        if existing_g:
            already_tagged_count += 1
            # Ensure DB has genre recorded as well
            if norm_p in db_records and not db_records[norm_p]["genre"]:
                archive.update_track_genre(file_path=norm_p, genre="; ".join(existing_g))
        else:
            needs_tagging.append(fpath)

    logger.info(f"Analysis: {already_tagged_count} already have genre tags, {len(needs_tagging)} need genre tagging.")

    if not needs_tagging:
        logger.info("All files already have genre tags! No retagging needed.")
        return

    processed = 0
    tagged_count = 0
    error_count = 0

    def process_file(fpath):
        norm_p = normalize_path(fpath)
        rec = db_records.get(norm_p)
        bname = os.path.basename(fpath)
        artist = ""
        title = ""
        album = ""

        if rec:
            artist = rec.get("artist", "")
            title = rec.get("title", "")
            album = rec.get("album", "")
        else:
            raw_name = os.path.splitext(bname)[0]
            import re
            m_num = re.match(r"^(\d{1,3})[\s.\-_]+(.*)$", raw_name)
            if m_num:
                raw_name = m_num.group(2).strip()
            if " - " in raw_name:
                artist, title = raw_name.split(" - ", 1)
            else:
                title = raw_name
            album = os.path.basename(os.path.dirname(fpath))

        resolved = genre_resolver.resolve(artist, title, album)
        if not resolved:
            resolved = genre_resolver.resolve(artist, "", album)
        if not resolved:
            resolved = ["Pop"]

        ok = tagger.tag_genre_only(fpath, resolved)
        if ok:
            genre_str = "; ".join(resolved)
            archive.update_track_genre(file_path=norm_p, genre=genre_str)
            return True, fpath, resolved
        return False, fpath, []

    logger.info(f"Starting concurrent retagging with {max_workers} worker threads...")
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(process_file, fp): fp for fp in needs_tagging}
        for fut in as_completed(futures):
            processed += 1
            ok, fp, genres = fut.result()
            if ok:
                tagged_count += 1
                if processed % 50 == 0 or processed == len(needs_tagging):
                    logger.info(f"Progress: [{processed}/{len(needs_tagging)}] tagged {os.path.basename(fp)} -> {genres}")
            else:
                error_count += 1
                logger.warning(f"Failed to retag: {fp}")

    genre_resolver._save_cache()
    logger.info("=" * 60)
    logger.info(f"RETAG SUMMARY:")
    logger.info(f"  Total audio files scanned: {total}")
    logger.info(f"  Previously tagged:         {already_tagged_count}")
    logger.info(f"  Newly tagged:              {tagged_count}")
    logger.info(f"  Errors:                    {error_count}")
    logger.info("=" * 60)


if __name__ == "__main__":
    retag_library()
