package com.flacify.android.sync

import com.flacify.android.data.db.PlaylistEntity
import com.flacify.android.data.db.PlaylistTrackEntity
import com.flacify.android.data.db.TrackEntity
import com.flacify.android.data.db.TrackSyncStatus

data class PlaylistSyncSummary(
    val playlist: PlaylistEntity,
    val syncedOnPhoneCount: Int,
    val syncedOnPhoneBytes: Long,
    val totalNeededBytes: Long,
)

data class SyncPlan(
    val neededTrackIds: Set<String>,
    val tracksToDownload: List<TrackEntity>,
    val orphanTracks: List<TrackEntity>,
    val totalBytesToDownload: Long,
)

object SyncPlanner {

    fun needsDownload(track: TrackEntity, fileExistsOnDisk: Boolean): Boolean {
        if (!fileExistsOnDisk) return true
        if (track.localFilePath.isNullOrBlank()) return true
        if (track.syncStatus != TrackSyncStatus.SYNCED) return true
        if (track.remoteFileSize > 0L && track.localFileSize != track.remoteFileSize) return true
        if (track.remoteMtimeMs > 0L && track.localMtimeMs != track.remoteMtimeMs) return true
        return false
    }

    fun plan(
        playlists: List<PlaylistEntity>,
        playlistTracks: List<PlaylistTrackEntity>,
        tracks: List<TrackEntity>,
        syncAllLibrary: Boolean = false,
        fileExists: (String) -> Boolean = { true },
    ): SyncPlan {
        val tracksById = tracks.associateBy { it.id }

        val neededIds: Set<String> = if (syncAllLibrary) {
            tracks.mapTo(linkedSetOf()) { it.id }
        } else {
            val enabledPlaylistIds = playlists
                .asSequence()
                .filter { it.syncEnabled }
                .map { it.id }
                .toHashSet()

            playlistTracks
                .asSequence()
                .filter { it.playlistId in enabledPlaylistIds }
                .map { it.canonicalTrackId }
                .filter { it in tracksById }
                .toCollection(linkedSetOf())
        }

        val toDownload = mutableListOf<TrackEntity>()
        var bytesToDownload = 0L
        for (id in neededIds) {
            val track = tracksById[id] ?: continue
            val exists = !track.localFilePath.isNullOrBlank() && fileExists(track.localFilePath)
            if (needsDownload(track, exists)) {
                toDownload.add(track)
                bytesToDownload += track.remoteFileSize.coerceAtLeast(0L)
            }
        }

        val orphans = tracks.filter { track ->
            if (track.id in neededIds) return@filter false
            val path = track.localFilePath
            !path.isNullOrBlank() && fileExists(path)
        }

        return SyncPlan(
            neededTrackIds = neededIds,
            tracksToDownload = toDownload,
            orphanTracks = orphans,
            totalBytesToDownload = bytesToDownload,
        )
    }

    fun summarizePlaylists(
        playlists: List<PlaylistEntity>,
        playlistTracks: List<PlaylistTrackEntity>,
        tracksById: Map<String, TrackEntity>,
    ): List<PlaylistSyncSummary> {
        val grouped = playlistTracks.groupBy { it.playlistId }
        return playlists.map { playlist ->
            val rows = grouped[playlist.id].orEmpty()
            var syncedCount = 0
            var syncedBytes = 0L
            var totalBytes = 0L
            val seenCanonical = hashSetOf<String>()

            for (row in rows) {
                val track = tracksById[row.canonicalTrackId]
                val isSynced = track != null &&
                    track.syncStatus == TrackSyncStatus.SYNCED &&
                    !track.localFilePath.isNullOrBlank()
                if (isSynced) {
                    syncedCount++
                }
                if (track != null && seenCanonical.add(track.id)) {
                    totalBytes += track.remoteFileSize.coerceAtLeast(0L)
                    if (isSynced) {
                        syncedBytes += track.localFileSize.coerceAtLeast(0L)
                    }
                }
            }

            PlaylistSyncSummary(
                playlist = playlist,
                syncedOnPhoneCount = syncedCount,
                syncedOnPhoneBytes = syncedBytes,
                totalNeededBytes = totalBytes,
            )
        }
    }
}
