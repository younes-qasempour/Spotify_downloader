import os
import io
import logging
from typing import Optional
import requests
from PIL import Image
import mutagen
from mutagen.flac import FLAC, Picture
from mutagen.id3 import ID3, TIT2, TPE1, TALB, TDRC, TRCK, TPOS, TSRC, USLT, APIC, COMM, TCON, TXXX
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
        try:
            from core.config import config
            proxy = config.get("download.proxy", "").strip()
            if proxy:
                self.session.proxies = {"http": proxy, "https": proxy}
        except Exception:
            pass

    @staticmethod
    def _normalize_crlf(text: Optional[str]) -> str:
        """
        Ensures all lyrics strings use Windows standard CRLF (\r\n) line endings.
        Windows media players (including PotPlayer and rich text subtitle renderers)
        require \r\n to parse synchronized timestamp lines correctly.
        """
        if not text:
            return ""
        unified = text.replace("\r\n", "\n").replace("\r", "\n").strip()
        return unified.replace("\n", "\r\n")

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

        # Ensure genres are populated via multi-source engine if not already set
        if not getattr(track, "genres", None):
            try:
                from core.genre import get_genre_resolver
                track.genres = get_genre_resolver().resolve(track.primary_artist, track.title, track.album)
            except Exception as e_gen:
                logger.debug(f"Genre resolution skipped for '{track.title}': {e_gen}")

        # Download or resolve cover art bytes across 5-tier cascade if requested
        cover_bytes = self._resolve_cover_bytes(track, file_path, embed_art=embed_art)

        plain_lyrics = ""
        synced_lyrics = ""
        if embed_lyrics and lyrics_data:
            import re
            plain_lyrics = lyrics_data.plain_lyrics or ""
            synced_lyrics = lyrics_data.synced_lyrics or ""
            if not plain_lyrics and synced_lyrics:
                plain_lyrics = re.sub(r'\[\d+:\d+\.\d+\]\s*', '', synced_lyrics).strip()

        plain_lyrics = self._normalize_crlf(plain_lyrics)
        synced_lyrics = self._normalize_crlf(synced_lyrics)

        try:
            success = False
            if ext == ".flac":
                success = self._tag_flac(file_path, track, cover_bytes, plain_lyrics, synced_lyrics)
            elif ext == ".mp3":
                success = self._tag_mp3(file_path, track, cover_bytes, plain_lyrics, synced_lyrics)
            elif ext == ".m4a":
                success = self._tag_m4a(file_path, track, cover_bytes, plain_lyrics, synced_lyrics)
            elif ext in (".opus", ".ogg", ".webm"):
                success = self._tag_opus(file_path, track, cover_bytes, plain_lyrics, synced_lyrics)
            else:
                logger.warning(f"Unsupported extension for tagging: {ext}")
                return False

            if success:
                try:
                    from core.config import config
                    if config.get("download.replaygain_tagging", False):
                        from core.utils import calculate_replaygain
                        rg = calculate_replaygain(file_path)
                        if rg:
                            self.tag_replaygain(file_path, rg[0], rg[1])
                except Exception as e_rg:
                    logger.debug(f"ReplayGain tagging note: {e_rg}")

            return success
        except Exception as e:
            logger.error(f"Failed to tag {file_path}: {e}")
            return False

    def _resolve_cover_bytes(
        self,
        track: TrackMetadata,
        file_path: str,
        embed_art: bool = True
    ) -> Optional[bytes]:
        """
        Multi-tier cover art resolution cascade:
        1. Direct track.cover_url (if provided)
        2. Spotify official oEmbed API (returns pristine 640x640 JPEG album art)
        3. track.collection_cover_url (playlist or album artwork)
        4. App collection cover cache (cache/covers/{collection}.jpg)
        5. Existing embedded cover already inside the audio container
        """
        if not embed_art:
            return None

        # Tier 1: Direct track cover URL
        if track.cover_url:
            b = self._download_image(track.cover_url)
            if b:
                return b

        # Tier 2: Spotify official oEmbed API (returns pristine 640x640 JPEG)
        if track.id and not track.id.startswith("yt_"):
            try:
                oembed_url = f"https://open.spotify.com/oembed?url=https://open.spotify.com/track/{track.id}"
                resp = self.session.get(oembed_url, timeout=6)
                if resp.status_code == 200:
                    thumb_url = resp.json().get("thumbnail_url", "")
                    if thumb_url:
                        # Upgrade standard 300x300 thumbnail to pristine 640x640 square cover art
                        highres_url = thumb_url.replace("ab67616d00001e02", "ab67616d0000b273")
                        b = self._download_image(highres_url) or self._download_image(thumb_url)
                        if b:
                            logger.info(f"Resolved 640x640 cover art via Spotify oEmbed for '{track.title}'")
                            return b
            except Exception as e:
                logger.debug(f"Spotify oEmbed resolution failed for {track.id}: {e}")

        # Tier 3: Collection cover URL (playlist or album cover art)
        coll_url = getattr(track, "collection_cover_url", "")
        if coll_url:
            b = self._download_image(coll_url)
            if b:
                return b

        # Tier 4: App collection cover cache
        try:
            from core.archive import resolve_collection_cover
            cached_path = resolve_collection_cover(os.path.dirname(file_path))
            if cached_path and os.path.isfile(cached_path):
                with open(cached_path, "rb") as f:
                    return f.read()
        except Exception:
            pass

        # Tier 5: Preserve existing embedded cover in file if present
        try:
            from core.utils import extract_embedded_cover
            existing = extract_embedded_cover(file_path)
            if existing and len(existing) > 500:
                return existing
        except Exception:
            pass

        return None

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

    @staticmethod
    def _resolve_clean_album(track: TrackMetadata, clean_title: str) -> str:
        raw_album = clean_watermarks(track.album)
        if not raw_album or raw_album.lower() in ("spotify playlist", "unknown album", "singles", "downloads"):
            return clean_title or "Single"
        return raw_album

    # -------------------------------------------------------------------------
    # FLAC Vorbis Tagging
    # -------------------------------------------------------------------------
    def _tag_flac(
        self,
        file_path: str,
        track: TrackMetadata,
        cover_bytes: Optional[bytes],
        plain_lyrics: str,
        synced_lyrics: str = ""
    ) -> bool:
        audio = FLAC(file_path)
        # Preserve existing lyrics if new ones are not provided
        existing_lyrics = audio.get("LYRICS", [""])[0] or audio.get("lyrics", [""])[0] or audio.get("SYNCEDLYRICS", [""])[0] or audio.get("UNSYNCEDLYRICS", [""])[0]
        if existing_lyrics:
            existing_lyrics = self._normalize_crlf(existing_lyrics)

        # Clear existing comments (scrub watermarks)
        audio.clear()

        clean_title = clean_watermarks(track.title)
        clean_album = self._resolve_clean_album(track, clean_title)

        audio["TITLE"] = clean_title
        audio["ARTIST"] = track.artists
        audio["ALBUMARTIST"] = track.primary_artist
        audio["ALBUM"] = clean_album
        if track.release_date:
            r_date_str = str(track.release_date).strip()
            if r_date_str:
                audio["DATE"] = r_date_str
                if len(r_date_str) >= 4:
                    audio["YEAR"] = r_date_str[:4]
        if getattr(track, "collection_type", "track") == "album" and getattr(track, "track_number", 0) > 0:
            audio["TRACKNUMBER"] = str(track.track_number)
            audio["DISCNUMBER"] = str(getattr(track, "disc_number", 1) or 1)
        audio["COMMENT"] = "Spotify Downloader High-Fidelity Engine"

        if track.isrc:
            audio["ISRC"] = track.isrc

        genres = [g.strip() for g in getattr(track, "genres", []) if g and g.strip()]
        if genres:
            comb = "; ".join(genres)
            tag_list = [comb] + [g for g in genres if g != comb]
            audio["GENRE"] = tag_list
            audio["genre"] = tag_list

        # Populate all standard Vorbis comment lyrics keys so any player finds them
        lyr_to_use = synced_lyrics or plain_lyrics or existing_lyrics
        if lyr_to_use:
            audio["LYRICS"] = lyr_to_use
            audio["lyrics"] = lyr_to_use

        if synced_lyrics:
            audio["SYNCEDLYRICS"] = synced_lyrics
            audio["SYNCED LYRICS"] = synced_lyrics
        elif existing_lyrics and ("[" in existing_lyrics and "]" in existing_lyrics):
            audio["SYNCEDLYRICS"] = existing_lyrics
            audio["SYNCED LYRICS"] = existing_lyrics

        unsynced_to_use = plain_lyrics or (existing_lyrics if not ("[" in existing_lyrics and "]" in existing_lyrics) else "")
        if not unsynced_to_use and lyr_to_use:
            import re
            unsynced_to_use = self._normalize_crlf(re.sub(r'\[\d+:\d+\.\d+\]\s*', '', lyr_to_use).strip())

        if unsynced_to_use:
            audio["UNSYNCEDLYRICS"] = unsynced_to_use
            audio["UNSYNCED LYRICS"] = unsynced_to_use
            audio["DESCRIPTION"] = unsynced_to_use

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
    def _tag_mp3(
        self,
        file_path: str,
        track: TrackMetadata,
        cover_bytes: Optional[bytes],
        plain_lyrics: str,
        synced_lyrics: str = ""
    ) -> bool:
        # Preserve existing APIC cover and USLT lyrics if not being updated
        existing_apic = []
        existing_uslt = []
        try:
            existing_id3 = ID3(file_path)
            existing_apic = existing_id3.getall("APIC")
            existing_uslt = existing_id3.getall("USLT")
        except Exception:
            pass

        import mutagen.id3
        try:
            mutagen.id3.delete(file_path)
        except Exception:
            pass

        audio = ID3()

        clean_title = clean_watermarks(track.title)
        clean_album = self._resolve_clean_album(track, clean_title)

        audio.add(TIT2(encoding=3, text=clean_title))
        audio.add(TPE1(encoding=3, text=track.artist_str))
        audio.add(TALB(encoding=3, text=clean_album))
        if track.release_date:
            r_date_str = str(track.release_date).strip()
            if r_date_str:
                audio.add(TDRC(encoding=3, text=r_date_str))
        if getattr(track, "collection_type", "track") == "album" and getattr(track, "track_number", 0) > 0:
            audio.add(TRCK(encoding=3, text=str(track.track_number)))
            audio.add(TPOS(encoding=3, text=str(getattr(track, "disc_number", 1) or 1)))
        audio.add(COMM(encoding=3, lang='eng', desc='', text='Spotify Downloader High-Fidelity Engine'))

        if track.isrc:
            audio.add(TSRC(encoding=3, text=track.isrc))

        genres = [g.strip() for g in getattr(track, "genres", []) if g and g.strip()]
        if genres:
            comb = "; ".join(genres)
            audio.delall("TCON")
            audio.add(TCON(encoding=3, text=[comb] + [g for g in genres if g != comb]))

        main_lyr = synced_lyrics or plain_lyrics
        if main_lyr:
            main_lyr = self._normalize_crlf(main_lyr)
            # Language-independent 'XXX' and standard 'eng'
            audio.add(USLT(encoding=3, lang='XXX', desc='', text=main_lyr))
            audio.add(USLT(encoding=3, lang='eng', desc='', text=main_lyr))
        elif existing_uslt:
            for u in existing_uslt:
                audio.add(u)

        if cover_bytes:
            mime = "image/jpeg" if cover_bytes[:2] == b'\xff\xd8' else "image/png"
            audio.add(APIC(
                encoding=3,
                mime=mime,
                type=3,  # Front cover
                desc='Cover',
                data=cover_bytes
            ))
        elif existing_apic:
            for ap in existing_apic:
                audio.add(ap)

        audio.save(file_path, v2_version=4)
        logger.info(f"Successfully tagged MP3: {file_path}")
        return True

    # -------------------------------------------------------------------------
    # M4A MP4 Tagging
    # -------------------------------------------------------------------------
    def _tag_m4a(
        self,
        file_path: str,
        track: TrackMetadata,
        cover_bytes: Optional[bytes],
        plain_lyrics: str,
        synced_lyrics: str = ""
    ) -> bool:
        audio = MP4(file_path)
        existing_covr = audio.get("covr")
        existing_lyr = audio.get("\xa9lyr")
        audio.clear()

        clean_title = clean_watermarks(track.title)
        clean_album = self._resolve_clean_album(track, clean_title)

        audio["\xa9nam"] = clean_title
        audio["\xa9ART"] = track.artist_str
        audio["aART"] = track.primary_artist
        audio["\xa9alb"] = clean_album
        if track.release_date:
            r_date_str = str(track.release_date).strip()
            if r_date_str:
                audio["\xa9day"] = r_date_str
        if getattr(track, "collection_type", "track") == "album" and getattr(track, "track_number", 0) > 0:
            audio["trkn"] = [(int(track.track_number), 0)]
            audio["disk"] = [(int(getattr(track, "disc_number", 1) or 1), 0)]
        audio["\xa9cmt"] = "Spotify Downloader High-Fidelity Engine"

        genres = [g.strip() for g in getattr(track, "genres", []) if g and g.strip()]
        if genres:
            audio["\xa9gen"] = "; ".join(genres)

        main_lyr = synced_lyrics or plain_lyrics
        if main_lyr:
            main_lyr = self._normalize_crlf(main_lyr)
            audio["\xa9lyr"] = main_lyr
        elif existing_lyr:
            audio["\xa9lyr"] = existing_lyr

        if cover_bytes:
            img_format = MP4Cover.FORMAT_JPEG if cover_bytes[:2] == b'\xff\xd8' else MP4Cover.FORMAT_PNG
            audio["covr"] = [MP4Cover(cover_bytes, imageformat=img_format)]
        elif existing_covr:
            audio["covr"] = existing_covr

        audio.save()
        logger.info(f"Successfully tagged M4A: {file_path}")
        return True

    # -------------------------------------------------------------------------
    # Opus / Ogg Tagging
    # -------------------------------------------------------------------------
    def _tag_opus(
        self,
        file_path: str,
        track: TrackMetadata,
        cover_bytes: Optional[bytes],
        plain_lyrics: str,
        synced_lyrics: str = ""
    ) -> bool:
        try:
            audio = OggOpus(file_path)
            is_opus = True
        except Exception:
            from mutagen.oggvorbis import OggVorbis
            audio = OggVorbis(file_path)
            is_opus = False

        # In OggOpus / OggVorbis, METADATA_BLOCK_PICTURE is stored as a Vorbis comment.
        # Preserve existing picture and lyrics before audio.clear()
        existing_pic = audio.get("METADATA_BLOCK_PICTURE") or audio.get("metadata_block_picture")
        existing_lyr = audio.get("LYRICS", [""])[0] or audio.get("lyrics", [""])[0] or audio.get("SYNCEDLYRICS", [""])[0] or audio.get("UNSYNCEDLYRICS", [""])[0]
        if existing_lyr:
            existing_lyr = self._normalize_crlf(existing_lyr)
        audio.clear()

        clean_title = clean_watermarks(track.title)
        clean_album = self._resolve_clean_album(track, clean_title)

        audio["TITLE"] = clean_title
        audio["ARTIST"] = track.artists
        audio["ALBUMARTIST"] = track.primary_artist
        audio["ALBUM"] = clean_album
        if track.release_date:
            r_date_str = str(track.release_date).strip()
            if r_date_str:
                audio["DATE"] = r_date_str
                if len(r_date_str) >= 4:
                    audio["YEAR"] = r_date_str[:4]
        if getattr(track, "collection_type", "track") == "album" and getattr(track, "track_number", 0) > 0:
            audio["TRACKNUMBER"] = str(track.track_number)
            audio["DISCNUMBER"] = str(getattr(track, "disc_number", 1) or 1)
        audio["COMMENT"] = "Spotify Downloader High-Fidelity Engine"

        if track.isrc:
            audio["ISRC"] = track.isrc

        genres = [g.strip() for g in getattr(track, "genres", []) if g and g.strip()]
        if genres:
            comb = "; ".join(genres)
            tag_list = [comb] + [g for g in genres if g != comb]
            audio["GENRE"] = tag_list
            audio["genre"] = tag_list

        # Populate all standard Vorbis comment lyrics keys
        lyr_to_use = synced_lyrics or plain_lyrics or existing_lyr
        if lyr_to_use:
            audio["LYRICS"] = lyr_to_use
            audio["lyrics"] = lyr_to_use

        if synced_lyrics:
            audio["SYNCEDLYRICS"] = synced_lyrics
            audio["SYNCED LYRICS"] = synced_lyrics
        elif existing_lyr and ("[" in existing_lyr and "]" in existing_lyr):
            audio["SYNCEDLYRICS"] = existing_lyr
            audio["SYNCED LYRICS"] = existing_lyr

        unsynced_to_use = plain_lyrics or (existing_lyr if not ("[" in existing_lyr and "]" in existing_lyr) else "")
        if not unsynced_to_use and lyr_to_use:
            import re
            unsynced_to_use = self._normalize_crlf(re.sub(r'\[\d+:\d+\.\d+\]\s*', '', lyr_to_use).strip())

        if unsynced_to_use:
            audio["UNSYNCEDLYRICS"] = unsynced_to_use
            audio["UNSYNCED LYRICS"] = unsynced_to_use
            audio["DESCRIPTION"] = unsynced_to_use

        if cover_bytes:
            import base64
            pic = Picture()
            pic.type = 3
            pic.mime = "image/jpeg" if cover_bytes[:2] == b'\xff\xd8' else "image/png"
            pic.desc = "Front Cover"
            pic.data = cover_bytes
            b64_pic = base64.b64encode(pic.write()).decode("ascii")
            if is_opus:
                audio["METADATA_BLOCK_PICTURE"] = [b64_pic]
            else:
                audio["metadata_block_picture"] = [b64_pic]
                audio["METADATA_BLOCK_PICTURE"] = [b64_pic]
        elif existing_pic:
            if is_opus:
                audio["METADATA_BLOCK_PICTURE"] = existing_pic
            else:
                audio["metadata_block_picture"] = existing_pic

        audio.save()
        logger.info(f"Successfully tagged {'Opus' if is_opus else 'Ogg Vorbis'}: {file_path}")
        return True

    def tag_genre_only(self, file_path: str, genres: List[str]) -> bool:
        """
        Fast, lightweight, in-place genre tagger for an existing audio file on disk.
        Preserves all existing tags, lyrics, track numbers, and embedded cover art.
        """
        clean_genres = [g.strip() for g in genres if g and g.strip()]
        if not clean_genres:
            return False
        comb = "; ".join(clean_genres)
        tag_list = [comb] + [g for g in clean_genres if g != comb]

        ext = os.path.splitext(file_path)[1].lower()
        try:
            if ext == ".flac":
                audio = FLAC(file_path)
                audio["GENRE"] = tag_list
                audio["genre"] = tag_list
                audio.save()
                return True
            elif ext == ".mp3":
                try:
                    audio = ID3(file_path)
                except Exception:
                    audio = ID3()
                audio.delall("TCON")
                audio.add(TCON(encoding=3, text=tag_list))
                audio.save(file_path, v2_version=4)
                return True
            elif ext == ".m4a":
                audio = MP4(file_path)
                audio["\xa9gen"] = comb
                audio.save()
                return True
            elif ext in (".opus", ".ogg"):
                try:
                    audio = OggOpus(file_path)
                except Exception:
                    from mutagen.oggvorbis import OggVorbis
                    audio = OggVorbis(file_path)
                audio["GENRE"] = tag_list
                audio["genre"] = tag_list
                audio.save()
                return True
        except Exception as e:
            logger.error(f"Error tagging genre only on {file_path}: {e}")
        return False

    tag_genre_in_place = tag_genre_only

    def tag_replaygain(self, file_path: str, gain_str: str, peak_str: str) -> bool:
        """
        Embeds ReplayGain 2.0 loudness normalization tags into audio container.
        Compatible with foobar2000, MusicBee, Poweramp, and VLC.
        """
        if not file_path or not os.path.isfile(file_path):
            return False

        ext = os.path.splitext(file_path)[1].lower()
        try:
            if ext == ".flac":
                audio = FLAC(file_path)
                audio["REPLAYGAIN_TRACK_GAIN"] = gain_str
                audio["REPLAYGAIN_TRACK_PEAK"] = peak_str
                audio.save()
                logger.info(f"Embedded ReplayGain tags in FLAC: {gain_str}, peak {peak_str}")
                return True
            elif ext == ".mp3":
                try:
                    audio = ID3(file_path)
                except Exception:
                    audio = ID3()
                audio.delall("TXXX:replaygain_track_gain")
                audio.delall("TXXX:replaygain_track_peak")
                audio.add(TXXX(encoding=3, desc='replaygain_track_gain', text=gain_str))
                audio.add(TXXX(encoding=3, desc='replaygain_track_peak', text=peak_str))
                audio.save(file_path, v2_version=4)
                logger.info(f"Embedded ReplayGain tags in MP3: {gain_str}, peak {peak_str}")
                return True
            elif ext == ".m4a":
                audio = MP4(file_path)
                audio["----:com.apple.iTunes:replaygain_track_gain"] = gain_str.encode("utf-8")
                audio["----:com.apple.iTunes:replaygain_track_peak"] = peak_str.encode("utf-8")
                audio.save()
                logger.info(f"Embedded ReplayGain tags in M4A: {gain_str}, peak {peak_str}")
                return True
            elif ext in (".opus", ".ogg", ".webm"):
                try:
                    audio = OggOpus(file_path)
                except Exception:
                    from mutagen.oggvorbis import OggVorbis
                    audio = OggVorbis(file_path)
                audio["REPLAYGAIN_TRACK_GAIN"] = gain_str
                audio["REPLAYGAIN_TRACK_PEAK"] = peak_str
                audio.save()
                logger.info(f"Embedded ReplayGain tags in Opus/OGG: {gain_str}, peak {peak_str}")
                return True
        except Exception as e:
            logger.debug(f"Error embedding ReplayGain tags in {file_path}: {e}")
        return False


