class FlacifyError(Exception):
    """Base exception for all domain errors within Flacify."""
    pass


class MetadataResolutionError(FlacifyError):
    """Raised when metadata cannot be retrieved or parsed from Spotify or scrapers."""
    pass


class AudioSourceNotFoundError(FlacifyError):
    """Raised when cascading audio engine fails to locate audio across all tiers."""
    pass


class AudioIntegrityError(FlacifyError):
    """Raised when a downloaded file fails magic audio header or minimum size verification."""
    pass


class TaggingError(FlacifyError):
    """Raised when metadata, lyrics, or cover art cannot be embedded into an audio file."""
    pass


class TranscodeError(FlacifyError):
    """Raised when FFmpeg fails to transcode an audio stream into a requested target format."""
    pass


class PlaylistSyncError(FlacifyError):
    """Raised when differential sync fails between remote Spotify playlist and local archive."""
    pass
