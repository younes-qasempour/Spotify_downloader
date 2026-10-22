import os
import logging
from dataclasses import dataclass
from typing import Optional, Callable, Tuple, Any

from core.spotify_client import TrackMetadata
from core.musilon import MusilonEngine, MusilonSource, MusilonError, MusilonVipError, MusilonRateLimitExceededError, MusilonDownloadError
from core.melobot import MeloBotEngine, MeloBotSource, MeloBotError, MeloBotDownloadError
from core.ytdlp_engine import YtdlpEngine, YtdlpSource
from core.lyrics import LyricsEngine
from core.tagger import AudioTagger
from core.utils import sanitize_filename, is_valid_audio_file
from core.config import config
from core.transcoder import transcode_audio
from core.exceptions import AudioSourceNotFoundError, AudioIntegrityError

logger = logging.getLogger("core.resolver")


@dataclass
class ResolvedTrackSource:
    source_type: str  # "Musilon", "MeloBot", or "YouTube Music"
    quality_badge: str  # e.g. "Musilon FLAC 16", "MeloBot FLAC", "MeloBot 320k", "YTM Opus"
    source_obj: Any  # MusilonSource, MeloBotSource, or YtdlpSource
    file_extension: str  # "flac", "mp3", "opus", "m4a"


class CascadingAudioEngine:
    """
    High-Fidelity Cascading Audio Engine:
    - Tier 1 (Option A): Musilon Lossless FLAC / Hi-Res / 320 kbps MP3
    - Tier 1 (Option B): MeloBot Premium FLAC / 320 kbps MP3 via Telegram
    - Tier 2: YouTube Music native high-bitrate Opus (Safety Net fallback)
    """

    def __init__(
        self,
        musilon_engine: Optional[MusilonEngine] = None,
        melobot_engine: Optional[MeloBotEngine] = None,
        ytdlp_engine: Optional[YtdlpEngine] = None,
        lyrics_engine: Optional[LyricsEngine] = None,
        tagger: Optional[AudioTagger] = None
    ):
        self.musilon = musilon_engine or MusilonEngine()
        self.melobot = melobot_engine or MeloBotEngine()
        self.ytdlp = ytdlp_engine or YtdlpEngine()
        self.lyrics = lyrics_engine or LyricsEngine()
        self.tagger = tagger or AudioTagger()

    def resolve_source(
        self,
        track: TrackMetadata,
        musilon_only: bool = False,
        skip_musilon: bool = False,
        cancel_check: Optional[Callable[[], bool]] = None
    ) -> Optional[ResolvedTrackSource]:
        """
        Executes cascading resolution ladder for a track.
        Prioritizes Musilon across all 4 search vectors and strict anti-false-positive scoring.
        Only falls back to YouTube Music if Musilon catalog is completely exhausted and fallback is enabled.
        Strictly respects cancel_check to abort immediately if the user stops the download.
        """
        if cancel_check and cancel_check():
            return None

        # 0. Check if direct YouTube video track
        if getattr(track, "id", "").startswith("yt_"):
            logger.info(f"Direct YouTube source detected for '{track.title}' (ID: {track.id}); bypassing Musilon.")
            yt_src = self.ytdlp.resolve_track(track, cancel_check=cancel_check)
            if yt_src:
                act_ext = yt_src.audio_format or "opus"
                badge = "YouTube M4A" if act_ext.lower() == "m4a" else "YouTube Opus"
                return ResolvedTrackSource(
                    source_type="YouTube",
                    quality_badge=badge,
                    source_obj=yt_src,
                    file_extension=act_ext
                )
            return None

        # Determine active engines and user preferences
        source_engine = str(config.get("source_engine", "musilon")).strip().lower()
        use_melobot_primary = (source_engine == "melobot" or (config.get("telegram.enabled", False) and not self.musilon.enabled))
        pref_q = str(config.get("telegram.preferred_quality", config.get("download.preferred_quality", "320"))).strip().lower()
        allow_128k = config.get("download.allow_128k", False) or pref_q in ("128", "standard", "low")

        melo_128k_candidate: Optional[MeloBotSource] = None

        def _try_melobot() -> Optional[ResolvedTrackSource]:
            nonlocal melo_128k_candidate
            if not self.melobot.enabled or skip_musilon:
                return None
            try:
                melo_src = self.melobot.resolve_track(track, cancel_check=cancel_check)
                if cancel_check and cancel_check():
                    return None
                if melo_src:
                    valid_tier = any(q in melo_src.quality_tier.lower() for q in ("flac", "320", "hires", "lossless"))
                    if valid_tier or allow_128k:
                        logger.info(f"Resolved via MeloBot ({melo_src.quality_tier}): {track.title}")
                        return ResolvedTrackSource(
                            source_type="MeloBot",
                            quality_badge=melo_src.quality_tier,
                            source_obj=melo_src,
                            file_extension=melo_src.file_extension
                        )
                    else:
                        logger.info(f"MeloBot returned standard tier '{melo_src.quality_tier}'; holding as safety-net candidate for '{track.title}'.")
                        melo_128k_candidate = melo_src
            except Exception as e_melo:
                if cancel_check and cancel_check():
                    return None
                logger.warning(f"MeloBot resolution failed for {track.title}: {e_melo}")
            return None

        def _try_musilon() -> Optional[ResolvedTrackSource]:
            if not self.musilon.enabled or skip_musilon:
                return None
            try:
                m_src = self.musilon.resolve_track(track, cancel_check=cancel_check)
                if cancel_check and cancel_check():
                    return None
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
            except (MusilonRateLimitExceededError, MusilonVipError) as e_mus:
                if cancel_check and cancel_check():
                    return None
                logger.warning(f"Musilon resolution encountered account/rate issue for '{track.title}': {e_mus}")
                raise e_mus
            except Exception as e:
                if cancel_check and cancel_check():
                    return None
                logger.warning(f"Musilon resolution failed for {track.title}: {e}")
            return None

        # 1. Primary Engine Attempt
        primary_res = _try_melobot() if use_melobot_primary else _try_musilon()
        if primary_res:
            return primary_res

        if cancel_check and cancel_check():
            return None

        # 2. Secondary Engine Attempt (Cascade between Musilon and MeloBot)
        secondary_res = _try_musilon() if use_melobot_primary else _try_melobot()
        if secondary_res:
            return secondary_res

        if cancel_check and cancel_check():
            return None

        # 3. Safety-Net Fallback: YouTube Music
        allow_fallback = config.get("download.allow_fallback", True) and not musilon_only
        if allow_fallback:
            logger.info(f"High-quality catalog exhausted for '{track.title}'; activating YouTube Music fallback...")
            try:
                yt_src = self.ytdlp.resolve_track(track, cancel_check=cancel_check)
                if cancel_check and cancel_check():
                    return None
                if yt_src:
                    logger.info(f"Resolved via YouTube Music fallback: {track.title}")
                    act_ext = yt_src.audio_format or "opus"
                    badge = "YTM M4A" if act_ext.lower() == "m4a" else "YTM Opus"
                    return ResolvedTrackSource(
                        source_type="YouTube Music",
                        quality_badge=badge,
                        source_obj=yt_src,
                        file_extension=act_ext
                    )
            except Exception as e:
                if cancel_check and cancel_check():
                    return None
                logger.error(f"YouTube Music fallback failed for {track.title}: {e}")

        # 4. Ultimate Safety Net: If YouTube Music failed or fallback disabled, use 128k MeloBot candidate if available
        if melo_128k_candidate:
            logger.info(f"Utilizing MeloBot 128k safety net as ultimate fallback for '{track.title}'")
            return ResolvedTrackSource(
                source_type="MeloBot",
                quality_badge=melo_128k_candidate.quality_tier,
                source_obj=melo_128k_candidate,
                file_extension=melo_128k_candidate.file_extension
            )

        if not allow_fallback:
            logger.info(f"Strict high-quality mode / Fallback disabled: skipping YouTube Music for '{track.title}'")

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
        if cancel_check and cancel_check():
            return None

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
        disc_num_str = f"{getattr(track, 'disc_number', 1) or 1:02d}"

        is_album = (getattr(track, "collection_type", "track") == "album")
        tmpl_to_use = naming_template
        if is_album and getattr(track, "track_number", 0) > 0 and tmpl_to_use == "{artist} - {title}":
            tmpl_to_use = config.get("download.album_naming_template", "{track_num}. {artist} - {title}")

        try:
            base_name = tmpl_to_use.format(
                artist=artist_clean,
                title=title_clean,
                album=album_clean,
                track_num=track_num_str,
                track_number=track_num_str,
                track=track_num_str,
                disc_num=disc_num_str,
                disc_number=disc_num_str
            )
        except Exception:
            if is_album and getattr(track, "track_number", 0) > 0:
                base_name = f"{track_num_str}. {artist_clean} - {title_clean}"
            else:
                base_name = f"{artist_clean} - {title_clean}"
        base_name = sanitize_filename(base_name, max_length=120)
        base_dest_without_ext = os.path.join(output_dir, base_name)

        # Download based on source type
        final_file_path: Optional[str] = None

        if cancel_check and cancel_check():
            return None

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
                if cancel_check and cancel_check():
                    if os.path.exists(dest_file):
                        try:
                            os.remove(dest_file)
                        except Exception:
                            pass
                    return None

                candidate_files = [
                    dest_file,
                    f"{base_dest_without_ext}.flac",
                    f"{base_dest_without_ext}.ogg",
                    f"{base_dest_without_ext}.mp3"
                ]
                actual_file = next((f for f in candidate_files if os.path.isfile(f) and os.path.getsize(f) > 1024), None)
                if success and actual_file:
                    is_valid, reason = is_valid_audio_file(actual_file)
                    if is_valid:
                        final_file_path = actual_file
                        # Synchronize resolved source details with actual audio file downloaded (handles quality stepdown)
                        act_ext = os.path.splitext(actual_file)[1].lstrip(".").lower()
                        resolved.file_extension = act_ext
                        if act_ext in ("ogg", "mp3"):
                            resolved.quality_badge = "Musilon 320k"
                        elif act_ext == "flac":
                            flac_quality = "Musilon FLAC 16"
                            try:
                                import mutagen
                                audio = mutagen.File(actual_file)
                                if audio and getattr(audio.info, "bits_per_sample", 16) == 24:
                                    flac_quality = "Musilon FLAC 24"
                            except Exception:
                                pass
                            resolved.quality_badge = flac_quality
                    else:
                        logger.warning(f"Musilon download produced an invalid audio file ({reason}) for '{track.title}'.")
                        try:
                            os.remove(actual_file)
                        except Exception:
                            pass
                        raise MusilonDownloadError(f"Musilon download produced an invalid audio file ({reason}) for '{track.title}'.")
                else:
                    logger.warning(f"Musilon download failed after {retries} attempts for '{track.title}'.")
                    raise MusilonDownloadError(f"Musilon download failed after {retries} attempts for '{track.title}'.")
            except (MusilonRateLimitExceededError, MusilonVipError, MusilonDownloadError) as e_mus:
                if cancel_check and cancel_check():
                    return None
                if os.path.exists(dest_file):
                    try:
                        os.remove(dest_file)
                    except Exception:
                        pass
                logger.warning(f"Musilon error for '{track.title}': {e_mus}. Raising for queue manager decision.")
                raise e_mus
            except Exception as e:
                if cancel_check and cancel_check():
                    return None
                if os.path.exists(dest_file):
                    try:
                        os.remove(dest_file)
                    except Exception:
                        pass
                logger.warning(f"Musilon stream download failed for '{track.title}': {e}")
                raise MusilonDownloadError(f"Musilon stream download failed for '{track.title}': {e}")
        if resolved.source_type == "MeloBot":
            if status_callback:
                status_callback("Downloading (MeloBot VIP)")
            melo_src: MeloBotSource = resolved.source_obj
            dest_file = f"{base_dest_without_ext}.{melo_src.file_extension}"
            try:
                success = self.melobot.download_track(
                    source=melo_src,
                    dest_path=dest_file,
                    progress_callback=progress_callback,
                    cancel_check=cancel_check,
                    pause_wait=pause_wait
                )
                if cancel_check and cancel_check():
                    if os.path.exists(dest_file):
                        try:
                            os.remove(dest_file)
                        except Exception:
                            pass
                    return None

                candidate_files = [
                    dest_file,
                    f"{base_dest_without_ext}.flac",
                    f"{base_dest_without_ext}.mp3",
                    f"{base_dest_without_ext}.m4a",
                    f"{base_dest_without_ext}.ogg"
                ]
                actual_file = next((f for f in candidate_files if os.path.isfile(f) and os.path.getsize(f) > 1024), None)
                if success and actual_file:
                    is_valid, reason = is_valid_audio_file(actual_file)
                    if is_valid:
                        final_file_path = actual_file
                        act_ext = os.path.splitext(actual_file)[1].lstrip(".").lower()
                        resolved.file_extension = act_ext
                        if act_ext == "flac":
                            resolved.quality_badge = "MeloBot FLAC"
                        elif act_ext == "mp3":
                            dur = track.duration_sec
                            sz = os.path.getsize(actual_file)
                            if dur > 0:
                                bitrate = (sz * 8) / (dur * 1000)
                                resolved.quality_badge = "MeloBot 320k" if bitrate >= 220 else "MeloBot 128k"
                            elif melo_src and getattr(melo_src, "quality_tier", None):
                                resolved.quality_badge = melo_src.quality_tier
                            else:
                                resolved.quality_badge = "MeloBot 320k" if sz > 6 * 1024 * 1024 else "MeloBot 128k"
                        elif melo_src and getattr(melo_src, "quality_tier", None):
                            resolved.quality_badge = melo_src.quality_tier
                        else:
                            resolved.quality_badge = f"MeloBot {act_ext.upper()}"
                    else:
                        logger.warning(f"MeloBot download produced an invalid audio file ({reason}) for '{track.title}'.")
                        if os.path.exists(actual_file):
                            try:
                                os.remove(actual_file)
                            except Exception:
                                pass
                        raise MeloBotDownloadError(f"MeloBot audio integrity check failed ({reason})")
                else:
                    raise MeloBotDownloadError(f"MeloBot download failed to write audio file for '{track.title}'.")
            except Exception as e_melo:
                if cancel_check and cancel_check():
                    return None
                if os.path.exists(dest_file):
                    try:
                        os.remove(dest_file)
                    except Exception:
                        pass
                logger.warning(f"MeloBot stream download failed for '{track.title}': {e_melo}")
                raise MeloBotDownloadError(f"MeloBot download error: {e_melo}")

        if cancel_check and cancel_check():
            return None

        if not final_file_path and resolved.source_type in ("YouTube Music", "YouTube"):
            is_yt_direct = (resolved.source_type == "YouTube")
            if status_callback:
                status_callback("Downloading (YouTube)" if is_yt_direct else "Downloading (YTM)")
            yt_src: YtdlpSource = resolved.source_obj
            final_file_path = self.ytdlp.download_track(
                source=yt_src,
                output_template_without_ext=base_dest_without_ext,
                progress_callback=progress_callback,
                cancel_check=cancel_check,
                pause_wait=pause_wait
            )
            if cancel_check and cancel_check():
                if final_file_path and os.path.exists(final_file_path):
                    try:
                        os.remove(final_file_path)
                    except Exception:
                        pass
                return None

            if final_file_path and os.path.isfile(final_file_path):
                act_ext = os.path.splitext(final_file_path)[1].lstrip(".").lower()
                resolved.file_extension = act_ext
                if is_yt_direct:
                    resolved.quality_badge = "YouTube M4A" if act_ext == "m4a" else "YouTube Opus"
                else:
                    resolved.quality_badge = "YTM M4A" if act_ext == "m4a" else "YTM Opus"

        if cancel_check and cancel_check():
            if final_file_path and os.path.exists(final_file_path):
                try:
                    os.remove(final_file_path)
                except Exception:
                    pass
            return None

        if not final_file_path or not os.path.isfile(final_file_path):
            if cancel_check and cancel_check():
                return None
            raise AudioSourceNotFoundError(f"Audio download failed to produce a valid file for '{track.title}'.")

        # Remux .webm container to .opus immediately via FFmpeg if necessary
        if final_file_path and final_file_path.lower().endswith(".webm") and os.path.isfile(final_file_path):
            from core.utils import ensure_ffmpeg
            import subprocess
            ffmpeg_bin = ensure_ffmpeg()
            if ffmpeg_bin:
                opus_cand = os.path.splitext(final_file_path)[0] + ".opus"
                cmd = [ffmpeg_bin, "-y", "-i", final_file_path, "-vn", "-c:a", "copy", opus_cand]
                flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
                try:
                    proc = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
                    if proc.returncode == 0 and os.path.isfile(opus_cand) and os.path.getsize(opus_cand) > 1000:
                        try:
                            os.remove(final_file_path)
                        except Exception:
                            pass
                        final_file_path = opus_cand
                        resolved.file_extension = "opus"
                        if resolved.source_type == "YouTube":
                            resolved.quality_badge = "YouTube Opus"
                        else:
                            resolved.quality_badge = "YTM Opus"
                except Exception as e_remux:
                    logger.warning(f"Failed to remux WebM to Opus: {e_remux}")

        # Strict integrity check on downloaded audio
        is_valid, reason = is_valid_audio_file(final_file_path)
        if not is_valid:
            if os.path.exists(final_file_path):
                try:
                    os.remove(final_file_path)
                except Exception:
                    pass
            raise AudioIntegrityError(f"Downloaded audio file failed integrity verification ({reason}) for '{track.title}'.")

        if cancel_check and cancel_check():
            if final_file_path and os.path.exists(final_file_path):
                try:
                    os.remove(final_file_path)
                except Exception:
                    pass
            return None

        # Optional audio format transcoding (e.g. ALAC for Apple Music, MP3 320k, FLAC, Opus)
        target_fmt = str(config.get("download.target_format", "original")).strip().lower()
        if target_fmt and target_fmt != "original":
            if status_callback:
                status_callback(f"Transcoding ({target_fmt.upper()})")
            try:
                transcoded_path = transcode_audio(final_file_path, target_format=target_fmt, delete_source=True)
                if (
                    transcoded_path
                    and os.path.isfile(transcoded_path)
                    and os.path.normpath(transcoded_path) != os.path.normpath(final_file_path)
                ):
                    final_file_path = transcoded_path
                    new_ext = os.path.splitext(transcoded_path)[1].lstrip(".").lower()
                    resolved.file_extension = new_ext
                    resolved.quality_badge = f"{resolved.quality_badge} [{target_fmt.upper()}]"
            except Exception as e_trans:
                logger.warning(f"Audio transcoding skipped or failed: {e_trans}")

        if cancel_check and cancel_check():
            if final_file_path and os.path.exists(final_file_path):
                try:
                    os.remove(final_file_path)
                except Exception:
                    pass
            return None

        # Lyrics Processing
        lyrics_mode = config.get("download.lyrics_mode", "embedded_only")
        save_companion = config.get("download.save_lrc", False) or lyrics_mode in ("separate_folder", "same_folder")
        if lyrics_mode == "embedded_only":
            save_companion = False

        if status_callback:
            status_callback("Fetching Lyrics")
        lyrics_data = None
        try:
            if not (cancel_check and cancel_check()):
                lyrics_data = self.lyrics.fetch_lyrics(track)
                if lyrics_data and save_companion:
                    target_dir = None
                    if lyrics_mode == "separate_folder":
                        target_dir = os.path.join(output_dir, "lyrics")
                    self.lyrics.save_companion_lrc(final_file_path, lyrics_data, target_dir=target_dir)
        except Exception as e:
            logger.warning(f"Failed to fetch lyrics: {e}")

        if cancel_check and cancel_check():
            if final_file_path and os.path.exists(final_file_path):
                try:
                    os.remove(final_file_path)
                except Exception:
                    pass
            return None

        # Metadata & Cover Art Tagging
        if status_callback:
            status_callback("Tagging Metadata")
        try:
            if not (cancel_check and cancel_check()):
                self.tagger.tag_file(
                    file_path=final_file_path,
                    track=track,
                    lyrics_data=lyrics_data,
                    embed_art=embed_art,
                    embed_lyrics=embed_lyrics
                )
        except Exception as e:
            logger.error(f"Error tagging audio file: {e}")

        # Check if file extension changed during tagging (e.g. remuxed to .opus)
        if final_file_path and not os.path.isfile(final_file_path):
            cand_opus = os.path.splitext(final_file_path)[0] + ".opus"
            if os.path.isfile(cand_opus):
                final_file_path = cand_opus
                resolved.file_extension = "opus"

        # Post-tagging Verification & Auto-Repair Safety Net
        try:
            from core.utils import extract_embedded_cover
            if embed_art and not (cancel_check and cancel_check()):
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
