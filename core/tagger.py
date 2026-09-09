import os
import io
import logging
from typing import Optional
import requests
from PIL import Image
import mutagen
from mutagen.flac import FLAC, Picture
from mutagen.id3 import ID3, TIT2, TPE1, TALB, TDRC, TRCK, TPOS, TSRC, USLT, APIC, COMM, TCON
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4, MP4Cover
from mutagen.oggopus import OggOpus

from core.spotify_client import TrackMetadata
from core.lyrics import LyricsData
from core.utils import clean_watermarks

logger = logging.getLogger("core.tagger")


class AudioTagger:
    """
    Pristine Metadata Tagger and Watermark Scrubber using mutagen.
    Embeds:
    - Title, Artists, Album, Release Date, Track/Disc numbers, ISRC
    - Front cover album artwork (PictureType.COVER_FRONT)
    - Synchronized/Unsynchronized lyrics
    - Overwrites any [Musilon] or promotional comments completely
    """

    def __init__(self, session: Optional[requests.Session] = None):
        self.session = session or requests.Session()

    def tag_file(
        self,
        file_path: str,
        track: TrackMetadata,
        lyrics_data: Optional[LyricsData] = None,
        embed_art: bool = True,
        embed_lyrics: bool = True
    ) -> bool:
        if not os.path.isfile(file_path):
            logger.error(f"File not found to tag: {file_path}")
            return False

        ext = os.path.splitext(file_path)[1].lower()
        logger.info(f"Tagging {ext} file: {file_path}")

        # Download cover art bytes if requested
        cover_bytes = None
        if embed_art and track.cover_url:
            cover_bytes = self._download_image(track.cover_url)

        plain_lyrics = lyrics_data.plain_lyrics if (embed_lyrics and lyrics_data) else ""

        try:
            if ext == ".flac":
                return self._tag_flac(file_path, track, cover_bytes, plain_lyrics)
            elif ext == ".mp3":
                return self._tag_mp3(file_path, track, cover_bytes, plain_lyrics)
            elif ext == ".m4a":
                return self._tag_m4a(file_path, track, cover_bytes, plain_lyrics)
            elif ext in (".opus", ".ogg"):
                return self._tag_opus(file_path, track, cover_bytes, plain_lyrics)
            else:
                logger.warning(f"Unsupported extension for tagging: {ext}")
                return False
        except Exception as e:
            logger.error(f"Failed to tag {file_path}: {e}")
            return False

    def _download_image(self, url: str) -> Optional[bytes]:
        try:
            resp = self.session.get(url, timeout=10)
            if resp.status_code == 200:
                # Validate image data with PIL
                img = Image.open(io.BytesIO(resp.content))
                img.verify()
                return resp.content
        except Exception as e:
            logger.warning(f"Could not download or verify album art from {url}: {e}")
        return None

    # -------------------------------------------------------------------------
    # FLAC Vorbis Tagging
    # -------------------------------------------------------------------------
    def _tag_flac(self, file_path: str, track: TrackMetadata, cover_bytes: Optional[bytes], lyrics: str) -> bool:
        audio = FLAC(file_path)
        # Clear existing comments and tags (scrub watermarks)
        audio.clear()

        clean_title = clean_watermarks(track.title)
        clean_album = clean_watermarks(track.album)

        audio["TITLE"] = clean_title
        audio["ARTIST"] = track.artists
        audio["ALBUMARTIST"] = track.primary_artist
        audio["ALBUM"] = clean_album
        if track.release_date:
            audio["DATE"] = str(track.release_date)
        audio["TRACKNUMBER"] = str(track.track_number)
        audio["DISCNUMBER"] = str(track.disc_number)
        audio["COMMENT"] = "Spotify Downloader High-Fidelity Engine"

        if track.isrc:
            audio["ISRC"] = track.isrc
        if lyrics:
            audio["LYRICS"] = lyrics

        if cover_bytes:
            audio.clear_pictures()
            pic = Picture()
            pic.type = 3  # Cover (front)
            pic.mime = "image/jpeg" if cover_bytes[:2] == b'\xff\xd8' else "image/png"
            pic.desc = "Front Cover"
            pic.data = cover_bytes
            audio.add_picture(pic)

        audio.save()
        logger.info(f"Successfully tagged FLAC: {file_path}")
        return True

    # -------------------------------------------------------------------------
    # MP3 ID3v2.4 Tagging
    # -------------------------------------------------------------------------
    def _tag_mp3(self, file_path: str, track: TrackMetadata, cover_bytes: Optional[bytes], lyrics: str) -> bool:
        audio = ID3()
        try:
            audio.delete(file_path)
        except Exception:
            pass

        clean_title = clean_watermarks(track.title)
        clean_album = clean_watermarks(track.album)
        rel_date_str = str(track.release_date) if track.release_date else ""

        audio.add(TIT2(encoding=3, text=clean_title))
        audio.add(TPE1(encoding=3, text=track.artist_str))
        audio.add(TALB(encoding=3, text=clean_album))
        if rel_date_str:
            audio.add(TDRC(encoding=3, text=rel_date_str))
        audio.add(TRCK(encoding=3, text=str(track.track_number)))
        audio.add(TPOS(encoding=3, text=str(track.disc_number)))
        audio.add(COMM(encoding=3, lang='eng', desc='', text='Spotify Downloader High-Fidelity Engine'))

        if track.isrc:
            audio.add(TSRC(encoding=3, text=track.isrc))
        if lyrics:
            audio.add(USLT(encoding=3, lang='eng', desc='', text=lyrics))

        if cover_bytes:
            mime = "image/jpeg" if cover_bytes[:2] == b'\xff\xd8' else "image/png"
            audio.add(APIC(
                encoding=3,
                mime=mime,
                type=3,  # Front cover
                desc='Cover',
                data=cover_bytes
            ))

        audio.save(file_path, v2_version=4)
        logger.info(f"Successfully tagged MP3: {file_path}")
        return True

    # -------------------------------------------------------------------------
    # M4A MP4 Tagging
    # -------------------------------------------------------------------------
    def _tag_m4a(self, file_path: str, track: TrackMetadata, cover_bytes: Optional[bytes], lyrics: str) -> bool:
        audio = MP4(file_path)
        audio.clear()

        clean_title = clean_watermarks(track.title)
        clean_album = clean_watermarks(track.album)

        audio["\xa9nam"] = clean_title
        audio["\xa9ART"] = track.artist_str
        audio["aART"] = track.primary_artist
        audio["\xa9alb"] = clean_album
        if track.release_date:
            audio["\xa9day"] = [str(track.release_date)]
        audio["trkn"] = [(int(track.track_number or 1), 0)]
        audio["disk"] = [(int(track.disc_number or 1), 0)]
        audio["\xa9cmt"] = "Spotify Downloader High-Fidelity Engine"

        if lyrics:
            audio["\xa9lyr"] = lyrics

        if cover_bytes:
            img_format = MP4Cover.FORMAT_JPEG if cover_bytes[:2] == b'\xff\xd8' else MP4Cover.FORMAT_PNG
            audio["covr"] = [MP4Cover(cover_bytes, imageformat=img_format)]

        audio.save()
        logger.info(f"Successfully tagged M4A: {file_path}")
        return True

    # -------------------------------------------------------------------------
    # Opus / Ogg Tagging
    # -------------------------------------------------------------------------
    def _tag_opus(self, file_path: str, track: TrackMetadata, cover_bytes: Optional[bytes], lyrics: str) -> bool:
        audio = OggOpus(file_path)
        audio.clear()

        clean_title = clean_watermarks(track.title)
        clean_album = clean_watermarks(track.album)

        audio["TITLE"] = clean_title
        audio["ARTIST"] = track.artists
        audio["ALBUMARTIST"] = track.primary_artist
        audio["ALBUM"] = clean_album
        if track.release_date:
            audio["DATE"] = str(track.release_date)
        audio["TRACKNUMBER"] = str(track.track_number)
        audio["DISCNUMBER"] = str(track.disc_number)
        audio["COMMENT"] = "Spotify Downloader High-Fidelity Engine"

        if track.isrc:
            audio["ISRC"] = track.isrc
        if lyrics:
            audio["LYRICS"] = lyrics

        if cover_bytes:
            import base64
            pic = Picture()
            pic.type = 3
            pic.mime = "image/jpeg" if cover_bytes[:2] == b'\xff\xd8' else "image/png"
            pic.desc = "Front Cover"
            pic.data = cover_bytes
            audio["METADATA_BLOCK_PICTURE"] = [base64.b64encode(pic.write()).decode("ascii")]

        audio.save()
        logger.info(f"Successfully tagged Opus: {file_path}")
        return True
