package com.flacify.android.data.db

import androidx.room.Entity
import androidx.room.Index
import androidx.room.PrimaryKey

object TrackSyncStatus {
    const val NOT_SYNCED = "NOT_SYNCED"
    const val SYNCING = "SYNCING"
    const val SYNCED = "SYNCED"
    const val ERROR = "ERROR"
}

@Entity(tableName = "tracks")
data class TrackEntity(
    @PrimaryKey val id: String,
    val title: String,
    val artist: String,
    val album: String,
    val durationMs: Long,
    val trackNumber: Int,
    val discNumber: Int,
    val genre: String,
    val qualityBadge: String,
    val sourceType: String,
    val filename: String,
    val ext: String,
    val remoteFileSize: Long,
    val remoteMtimeMs: Long,
    val fileUrl: String,
    val coverUrl: String,
    val lyricsUrl: String,
    val hasRemoteLrc: Boolean,
    val localFilePath: String? = null,
    val localFileSize: Long = 0L,
    val localMtimeMs: Long = 0L,
    val localEtag: String? = null,
    val localCoverPath: String? = null,
    val lyricsText: String? = null,
    val lyricsIsSynced: Boolean = false,
    val lyricsSynced: Boolean = false,
    val syncStatus: String = TrackSyncStatus.NOT_SYNCED,
    val lastError: String? = null,
    val updatedAt: Long = 0L,
)

@Entity(tableName = "playlists")
data class PlaylistEntity(
    @PrimaryKey val id: String,
    val name: String,
    val totalTracks: Int,
    val pcDownloadedTracks: Int,
    val coverUrl: String,
    val remoteCoverUrl: String,
    val localCoverPath: String? = null,
    val syncEnabled: Boolean = false,
    val lastSyncedAt: Long = 0L,
)

@Entity(
    tableName = "playlist_tracks",
    primaryKeys = ["playlistId", "position"],
    indices = [
        Index(value = ["playlistId"]),
        Index(value = ["canonicalTrackId"]),
    ],
)
data class PlaylistTrackEntity(
    val playlistId: String,
    val position: Int,
    val spotifyId: String,
    val canonicalTrackId: String,
    val title: String,
    val artist: String,
    val album: String,
    val durationMs: Long,
    val pcDownloaded: Boolean,
)

@Entity(
    tableName = "track_aliases",
    indices = [Index(value = ["canonicalTrackId"])],
)
data class TrackAliasEntity(
    @PrimaryKey val aliasId: String,
    val canonicalTrackId: String,
)

object PendingShareStatus {
    const val PENDING = "PENDING"
    const val SENDING = "SENDING"
    const val SENT = "SENT"
    const val FAILED = "FAILED"
}

@Entity(tableName = "pending_shares")
data class PendingShareEntity(
    @PrimaryKey(autoGenerate = true) val id: Long = 0L,
    val rawUrl: String,
    val displayKind: String,
    val autoDownload: Boolean = true,
    val status: String = PendingShareStatus.PENDING,
    val queuedCount: Int = 0,
    val lastError: String? = null,
    val createdAt: Long,
    val updatedAt: Long,
)
