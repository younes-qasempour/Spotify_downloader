package com.flacify.android.network

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

@Serializable
data class HealthResponse(
    val status: String = "ok",
    val version: String = "",
    @SerialName("api_version") val apiVersion: String = "2.0",
    @SerialName("device_name") val deviceName: String = "",
    @SerialName("lan_enabled") val lanEnabled: Boolean = true,
    @SerialName("pair_required") val pairRequired: Boolean = true,
    @SerialName("queue_paused") val queuePaused: Boolean = false,
    @SerialName("queue_count") val queueCount: Int = 0,
    @SerialName("ws_clients") val wsClients: Int = 0,
    @SerialName("pending_prompts") val pendingPrompts: Int = 0,
    @SerialName("web_ui_enabled") val webUiEnabled: Boolean = false,
)

@Serializable
data class LibraryStatsDto(
    @SerialName("total_tracks") val totalTracks: Int = 0,
    @SerialName("total_playlists") val totalPlaylists: Int = 0,
    @SerialName("total_albums") val totalAlbums: Int = 0,
    @SerialName("total_bytes") val totalBytes: Long = 0L,
    @SerialName("size_str") val sizeStr: String = "0.0 MB",
)

@Serializable
data class SyncInfoResponse(
    @SerialName("lan_enabled") val lanEnabled: Boolean = true,
    @SerialName("bind_host") val bindHost: String = "",
    @SerialName("restart_required") val restartRequired: Boolean = false,
    @SerialName("device_name") val deviceName: String = "",
    val port: Int = 8765,
    @SerialName("server_version") val serverVersion: String = "",
    val ips: List<String> = emptyList(),
    val urls: List<String> = emptyList(),
    @SerialName("primary_url") val primaryUrl: String = "",
    @SerialName("library_stats") val libraryStats: LibraryStatsDto = LibraryStatsDto(),
    @SerialName("saved_playlists_count") val savedPlaylistsCount: Int = 0,
    val paired: Boolean = true,
    @SerialName("pair_token") val pairToken: String? = null,
    @SerialName("pair_uri") val pairUri: String? = null,
    @SerialName("qr_svg_url") val qrSvgUrl: String? = null,
)

@Serializable
data class SyncManifestResponse(
    @SerialName("server_version") val serverVersion: String = "",
    @SerialName("device_name") val deviceName: String = "",
    @SerialName("generated_at") val generatedAt: Long = 0L,
    @SerialName("total_unique_tracks") val totalUniqueTracks: Int = 0,
    @SerialName("total_bytes") val totalBytes: Long = 0L,
    val playlists: List<SyncPlaylistDto> = emptyList(),
    val tracks: List<SyncTrackDto> = emptyList(),
)

@Serializable
data class SyncPlaylistDto(
    val id: String,
    val name: String = "Playlist",
    @SerialName("total_tracks") val totalTracks: Int = 0,
    @SerialName("downloaded_tracks") val downloadedTracks: Int = 0,
    @SerialName("cover_url") val coverUrl: String = "",
    @SerialName("remote_cover_url") val remoteCoverUrl: String = "",
    val tracks: List<SyncPlaylistTrackDto> = emptyList(),
)

@Serializable
data class SyncPlaylistTrackDto(
    @SerialName("spotify_id") val spotifyId: String,
    @SerialName("canonical_id") val canonicalId: String,
    val title: String = "",
    val artist: String = "",
    val album: String = "",
    @SerialName("duration_ms") val durationMs: Long = 0L,
    val downloaded: Boolean = false,
)

@Serializable
data class SyncTrackDto(
    val id: String,
    @SerialName("alias_ids") val aliasIds: List<String> = emptyList(),
    val title: String = "",
    val artist: String = "Unknown Artist",
    val album: String = "",
    @SerialName("duration_ms") val durationMs: Long = 0L,
    @SerialName("track_number") val trackNumber: Int = 1,
    @SerialName("disc_number") val discNumber: Int = 1,
    val genre: String = "",
    @SerialName("quality_badge") val qualityBadge: String = "FLAC 16",
    @SerialName("source_type") val sourceType: String = "Musilon",
    val filename: String = "",
    val ext: String = "",
    @SerialName("file_size") val fileSize: Long = 0L,
    @SerialName("mtime_ms") val mtimeMs: Long = 0L,
    @SerialName("file_url") val fileUrl: String = "",
    @SerialName("stream_url") val streamUrl: String = "",
    @SerialName("cover_url") val coverUrl: String = "",
    @SerialName("lyrics_url") val lyricsUrl: String = "",
    @SerialName("has_lrc") val hasLrc: Boolean = false,
)

@Serializable
data class ShareRequest(
    val url: String,
    @SerialName("auto_download") val autoDownload: Boolean = true,
    @SerialName("preferred_engine") val preferredEngine: String? = null,
)

@Serializable
data class ShareResponse(
    val accepted: Boolean = false,
    @SerialName("extracted_url") val extractedUrl: String = "",
    @SerialName("entity_type") val entityType: String = "",
    @SerialName("queued_count") val queuedCount: Int = 0,
    @SerialName("saved_playlists_updated") val savedPlaylistsUpdated: Boolean = false,
    val started: Boolean = false,
    val errors: List<String> = emptyList(),
)

@Serializable
internal data class FastApiErrorResponse(
    val detail: String = "",
)
