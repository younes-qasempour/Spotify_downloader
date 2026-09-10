import os
import logging
from dataclasses import dataclass
from typing import Optional, Callable, Tuple, Any

from core.spotify_client import TrackMetadata
from core.musilon import MusilonEngine, MusilonSource
from core.ytdlp_engine import YtdlpEngine, YtdlpSource
from core.lyrics import LyricsEngine
from core.tagger import AudioTagger
from core.utils import sanitize_filename, is_valid_audio_file
from core.config import config

logger = logging.getLogger("core.resolver")


@dataclass
class ResolvedTrackSource:
    source_type: str  # "Musilon" or "YouTube Music"
    quality_badge: str  # e.g. "Musilon FLAC 16", "Musilon FLAC 24", "Musilon 320k", "YTM Opus"
    source_obj: Any  # MusilonSource or YtdlpSource
    file_extension: str  # "flac", "mp3", "opus", "m4a"


class CascadingAudioEngine:
    """
    High-Fidelity Cascading Audio Engine:
    1. Tier 1: Musilon Lossless FLAC 16-bit (CD Quality)
    2. Tier 2: Musilon Hi-Res FLAC 24-bit (Studio Master)
    3. Tier 3: Musilon Studio MP3 320 kbps (CBR)
    4. Tier 4: YouTube Music native high-bitrate Opus (Safety Net strictly when Musilon catalog is completely exhausted)
    """

    def __init__(
        self,
        musilon_engine: Optional[MusilonEngine] = None,
        ytdlp_engine: Optional[YtdlpEngine] = None,
        lyrics_engine: Optional[LyricsEngine] = None,
        tagger: Optional[AudioTagger] = None
    ):
        self.musilon = musilon_engine or MusilonEngine()
        self.ytdlp = ytdlp_engine or YtdlpEngine()
        self.lyrics = lyrics_engine or LyricsEngine()
        self.tagger = tagger or AudioTagger()

    def resolve_source(self, track: TrackMetadata, musilon_only: bool = False) -> Optional[ResolvedTrackSource]:
        """
        Executes cascading resolution ladder for a track.
        Prioritizes Musilon across all 4 search vectors and strict anti-false-positive scoring.
        Only falls back to YouTube Music if Musilon catalog is completely exhausted and fallback is enabled.
        """
        # 1. Try Musilon Tiers 1-3 across all multi-vector search stages
        if self.musilon.enabled:
            try:
                m_src = self.musilon.resolve_track(track)
                if m_src:
                    valid_tier = any(q in m_src.quality_tier.lower() for q in ("flac", "320", "studio"))
                    if valid_tier:
                        logger.info(f"Resolved via Musilon ({m_src.quality_tier}): {track.title}")
                        return ResolvedTrackSource(
                            source_type="Musilon",
                            quality_badge=m_src.quality_tier,
                            source_obj=m_src,
                            file_extension=m_src.file_extension
                        )
                    else:
                        logger.info(f"Musilon tier '{m_src.quality_tier}' rejected to satisfy FLAC/320k priority.")
            except Exception as e:
                logger.warning(f"Musilon resolution failed for {track.title}: {e}")

        # Check if fallback is disabled globally or explicitly requested
        allow_fallback = config.get("download.allow_fallback", True) and not musilon_only
        if not allow_fallback:
            logger.info(f"Strict Musilon mode / Fallback disabled: skipping YouTube Music for '{track.title}'")
            return None

        # 2. Safety-Net Fallback to Tier 4: YouTube Music
        logger.info(f"Musilon catalog completely exhausted for '{track.title}'; activating YouTube Music fallback...")
        try:
            yt_src = self.ytdlp.resolve_track(track)
            if yt_src:
                logger.info(f"Resolved via YouTube Music fallback: {track.title}")
                return ResolvedTrackSource(
                    source_type="YouTube Music",
                    quality_badge="YTM Opus",
                    source_obj=yt_src,
                    file_extension="opus"
                )
        except Exception as e:
            logger.error(f"YouTube Music fallback failed for {track.title}: {e}")

        return None

    def download_and_tag(
        self,
        track: TrackMetadata,
        resolved: ResolvedTrackSource,
        output_dir: str,
        naming_template: str = "{artist} - {title}",
        save_lrc: bool = True,
        embed_lyrics: bool = True,
        embed_art: bool = True,
        progress_callback: Optional[Callable[[float, str, str], None]] = None,
        status_callback: Optional[Callable[[str], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
        pause_wait: Optional[Callable[[], None]] = None,
        musilon_only: bool = False
    ) -> Optional[str]:
        """
        Downloads audio stream, queries lyrics, embeds metadata and saves companion .lrc.
        Returns final destination file path.
        """
        # Automatically organize into subfolder based on collection type:
        # - Playlists: folder named after the playlist
        # - Albums: folder named after the album
        # - Singles/Tracks: folder named "Singles"
        subfolder = getattr(track, "target_folder", "")
        if subfolder:
            norm_output = os.path.normpath(output_dir)
            if os.path.basename(norm_output).lower() != subfolder.lower():
                output_dir = os.path.join(output_dir, subfolder)

        os.makedirs(output_dir, exist_ok=True)

        # Build clean filename
        artist_clean = sanitize_filename(track.primary_artist, max_length=40)
        title_clean = sanitize_filename(track.title, max_length=40)
        album_clean = sanitize_filename(track.album, max_length=40)
        track_num_str = f"{track.track_number:02d}"

        try:
            base_name = naming_template.format(
                artist=artist_clean,
                title=title_clean,
                album=album_clean,
                track_num=track_num_str,
                track_number=track_num_str,
                track=track_num_str
            )
        except Exception:
            base_name = f"{artist_clean} - {title_clean}"
        base_name = sanitize_filename(base_name, max_length=120)
        base_dest_without_ext = os.path.join(output_dir, base_name)

        # Download based on source type
        final_file_path: Optional[str] = None

        if resolved.source_type == "Musilon":
            if status_callback:
                status_callback("Downloading (Musilon VIP)")
            m_src: MusilonSource = resolved.source_obj
            dest_file = f"{base_dest_without_ext}.{m_src.file_extension}"
            retries = config.get("download.musilon_max_retries", 5)
            try:
                success = self.musilon.download_track_with_retry(
                    track=track,
                    source=m_src,
                    dest_path=dest_file,
                    progress_callback=progress_callback,
                    cancel_check=cancel_check,
                    pause_wait=pause_wait,
                    max_retries=retries
                )
                if success and os.path.isfile(dest_file):
                    is_valid, reason = is_valid_audio_file(dest_file)
                    if is_valid:
                        final_file_path = dest_file
                    else:
                        logger.warning(f"Musilon download produced an invalid audio file ({reason}) for '{track.title}'.")
                        try:
                            os.remove(dest_file)
                        except Exception:
                            pass
                else:
                    logger.warning(f"Musilon download failed after {retries} attempts for '{track.title}'.")
            except Exception as e:
                logger.warning(f"Musilon stream download failed ({e}).")

            # Fallback to YouTube Music ONLY as last resort after all Musilon retries fail
            allow_fallback = config.get("download.allow_fallback", True) and not musilon_only
            if not final_file_path and allow_fallback:
                logger.info(f"Musilon exhausted. Initiating last-resort safety-net fallback to YouTube Music for '{track.title}'...")
                if status_callback:
                    status_callback("Falling back to YTM (Last Resort)")
                yt_fallback = self.ytdlp.resolve_track(track)
                if yt_fallback:
                    resolved = ResolvedTrackSource(
                        source_type="YouTube Music",
                        quality_badge="YTM Opus",
                        source_obj=yt_fallback,
                        file_extension=yt_fallback.audio_format or "opus"
                    )

        if not final_file_path and resolved.source_type == "YouTube Music":
            if status_callback:
                status_callback("Downloading (YTM)")
            yt_src: YtdlpSource = resolved.source_obj
            final_file_path = self.ytdlp.download_track(
                source=yt_src,
                output_template_without_ext=base_dest_without_ext,
                progress_callback=progress_callback,
                cancel_check=cancel_check,
                pause_wait=pause_wait
            )

        if not final_file_path or not os.path.isfile(final_file_path):
            raise RuntimeError(f"Audio download failed to produce a valid file for '{track.title}'.")

        # Strict integrity check on downloaded audio
        is_valid, reason = is_valid_audio_file(final_file_path)
        if not is_valid:
            if os.path.exists(final_file_path):
                try:
                    os.remove(final_file_path)
                except Exception:
                    pass
            raise RuntimeError(f"Downloaded audio file failed integrity verification ({reason}) for '{track.title}'.")

        # Lyrics Processing
        lyrics_mode = config.get("download.lyrics_mode", "embedded_only")
        save_companion = config.get("download.save_lrc", False) or lyrics_mode in ("separate_folder", "same_folder")
        if lyrics_mode == "embedded_only":
            save_companion = False

        if status_callback:
            status_callback("Fetching Lyrics")
        lyrics_data = None
        try:
            lyrics_data = self.lyrics.fetch_lyrics(track)
            if lyrics_data and save_companion:
                target_dir = None
                if lyrics_mode == "separate_folder":
                    target_dir = os.path.join(output_dir, "lyrics")
                self.lyrics.save_companion_lrc(final_file_path, lyrics_data, target_dir=target_dir)
        except Exception as e:
            logger.warning(f"Failed to fetch lyrics: {e}")

        # Metadata & Cover Art Tagging
        if status_callback:
            status_callback("Tagging Metadata")
        try:
            self.tagger.tag_file(
                file_path=final_file_path,
                track=track,
                lyrics_data=lyrics_data,
                embed_art=embed_art,
                embed_lyrics=embed_lyrics
            )
        except Exception as e:
            logger.error(f"Error tagging audio file: {e}")

        # Post-tagging Verification & Auto-Repair Safety Net
        try:
            from core.utils import extract_embedded_cover
            if embed_art:
                cov = extract_embedded_cover(final_file_path)
                if not cov or len(cov) < 500:
                    logger.warning(f"Cover art missing after tagging for '{track.title}'. Triggering emergency oEmbed auto-heal...")
                    self.tagger.tag_file(
                        file_path=final_file_path,
                        track=track,
                        lyrics_data=lyrics_data,
                        embed_art=True,
                        embed_lyrics=embed_lyrics
                    )
        except Exception as e_verify:
            logger.debug(f"Post-tag verification check: {e_verify}")

        if status_callback:
            status_callback("Completed")

        return final_file_path
