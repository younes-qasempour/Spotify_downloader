package com.flacify.android.data

import androidx.room.withTransaction
import com.flacify.android.data.db.FlacifyDatabase
import com.flacify.android.data.db.PlaylistEntity
import com.flacify.android.data.db.PlaylistTrackEntity
import com.flacify.android.data.db.TrackAliasEntity
import com.flacify.android.data.db.TrackEntity
import com.flacify.android.data.db.TrackSyncStatus
import com.flacify.android.data.storage.LocalMediaStorage
import com.flacify.android.data.storage.StorageSummary
import com.flacify.android.network.FlacifyApiClient
import com.flacify.android.network.FlacifyApiException
import com.flacify.android.network.SyncManifestResponse
import com.flacify.android.sync.PlaylistSyncSummary
import com.flacify.android.sync.SyncPlanner
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.withContext

data class PlaylistTrackItem(
    val entry: PlaylistTrackEntity,
    val track: TrackEntity?,
) {
    val isOfflineReady: Boolean
        get() = track != null &&
            track.syncStatus == TrackSyncStatus.SYNCED &&
            !track.localFilePath.isNullOrBlank()
}

class FlacifyRepository(
    val database: FlacifyDatabase,
    val storage: LocalMediaStorage,
    val connectionStore: ConnectionSettingsStore,
    val apiClient: FlacifyApiClient,
) {
    private val dao = database.dao()

    fun observePlaylist(playlistId: String): Flow<PlaylistEntity?> =
        dao.observePlaylist(playlistId)

    fun observePlaylistTrackItems(playlistId: String): Flow<List<PlaylistTrackItem>> =
        combine(
            dao.observePlaylistTracks(playlistId),
            dao.observeAllTracks(),
        ) { entries, tracks ->
            val tracksById = tracks.associateBy { it.id }
            entries.map { entry ->
                PlaylistTrackItem(
                    entry = entry,
                    track = tracksById[entry.canonicalTrackId],
                )
            }
        }

    fun observePlaylistSummaries(): Flow<List<PlaylistSyncSummary>> =
        combine(
            dao.observeAllPlaylists(),
            dao.observeAllPlaylistTracks(),
            dao.observeAllTracks(),
        ) { playlists, playlistTracks, tracks ->
            SyncPlanner.summarizePlaylists(
                playlists = playlists,
                playlistTracks = playlistTracks,
                tracksById = tracks.associateBy { it.id },
            )
        }

    fun observeStorageSummary(): Flow<StorageSummary> =
        combine(
            dao.observeSyncedTrackCount(),
            dao.observeSyncedAudioBytes(),
        ) { _, _ ->
            withContext(Dispatchers.IO) {
                storage.computeStorageSummary()
            }
        }

    fun observeSyncedTrackCount(): Flow<Int> = dao.observeSyncedTrackCount()

    fun observeAllTracks(): Flow<List<TrackEntity>> = dao.observeAllTracks()

    fun observeSyncedTracks(): Flow<List<TrackEntity>> = dao.observeSyncedTracks()

    suspend fun currentConnection(): ConnectionConfig = connectionStore.configFlow.first()

    suspend fun refreshManifestFromPc(): SyncManifestResponse {
        val cfg = currentConnection()
        if (!cfg.isPaired) {
            throw FlacifyApiException.Unreachable("Not paired with Flacify PC yet.")
        }

        val call = apiClient.fetchManifest(
            candidateUrls = cfg.orderedCandidateUrls(),
            token = cfg.pairToken,
            includeTracks = true,
        )
        if (call.resolvedBaseUrl != cfg.activeUrl) {
            connectionStore.updateActiveUrl(call.resolvedBaseUrl)
        }

        val manifest = call.data
        val now = System.currentTimeMillis()
        var deletedTrackArtifacts: List<Pair<String?, String?>> = emptyList()

        withContext(Dispatchers.IO) {
            val existingTracksById = dao.getAllTracks().associateBy { it.id }
            val existingPlaylistsById = dao.getAllPlaylists().associateBy { it.id }

            val newTrackIds = manifest.tracks.mapTo(hashSetOf()) { it.id }
            val newPlaylistIds = manifest.playlists.mapTo(hashSetOf()) { it.id }

            val removedTrackIds = existingTracksById.keys.filterNot { it in newTrackIds }
            val removedPlaylistIds = existingPlaylistsById.keys.filterNot { it in newPlaylistIds }

            deletedTrackArtifacts = removedTrackIds.mapNotNull { id ->
                existingTracksById[id]?.let { it.localFilePath to it.localCoverPath }
            }

            val updatedTracks = manifest.tracks.map { dto ->
                val prev = existingTracksById[dto.id]
                val fileExists = prev != null && storage.fileExistsNonEmpty(prev.localFilePath)
                val upToDate = prev != null &&
                    fileExists &&
                    prev.syncStatus == TrackSyncStatus.SYNCED &&
                    (dto.fileSize <= 0L || prev.localFileSize == dto.fileSize) &&
                    (dto.mtimeMs <= 0L || prev.localMtimeMs == dto.mtimeMs)

                val keptCoverPath = prev?.localCoverPath?.takeIf { storage.fileExistsNonEmpty(it) }
                val resolvedStatus = when {
                    upToDate -> TrackSyncStatus.SYNCED
                    prev?.syncStatus == TrackSyncStatus.SYNCING -> TrackSyncStatus.NOT_SYNCED
                    else -> TrackSyncStatus.NOT_SYNCED
                }

                TrackEntity(
                    id = dto.id,
                    title = dto.title,
                    artist = dto.artist,
                    album = dto.album,
                    durationMs = dto.durationMs,
                    trackNumber = dto.trackNumber,
                    discNumber = dto.discNumber,
                    genre = dto.genre,
                    qualityBadge = dto.qualityBadge,
                    sourceType = dto.sourceType,
                    filename = dto.filename,
                    ext = dto.ext,
                    remoteFileSize = dto.fileSize,
                    remoteMtimeMs = dto.mtimeMs,
                    fileUrl = dto.fileUrl,
                    coverUrl = dto.coverUrl,
                    lyricsUrl = dto.lyricsUrl,
                    hasRemoteLrc = dto.hasLrc,
                    localFilePath = if (fileExists) prev?.localFilePath else null,
                    localFileSize = if (fileExists) prev?.localFileSize ?: 0L else 0L,
                    localMtimeMs = if (fileExists) prev?.localMtimeMs ?: 0L else 0L,
                    localEtag = if (fileExists) prev?.localEtag else null,
                    localCoverPath = keptCoverPath,
                    lyricsText = prev?.lyricsText,
                    lyricsIsSynced = prev?.lyricsIsSynced ?: false,
                    lyricsSynced = prev?.lyricsSynced ?: false,
                    syncStatus = resolvedStatus,
                    lastError = if (upToDate) null else prev?.lastError,
                    updatedAt = prev?.updatedAt ?: now,
                )
            }

            val updatedPlaylists = manifest.playlists.map { plDto ->
                val prev = existingPlaylistsById[plDto.id]
                val keptCover = prev?.localCoverPath?.takeIf { storage.fileExistsNonEmpty(it) }
                PlaylistEntity(
                    id = plDto.id,
                    name = plDto.name,
                    totalTracks = plDto.totalTracks,
                    pcDownloadedTracks = plDto.downloadedTracks,
                    coverUrl = plDto.coverUrl,
                    remoteCoverUrl = plDto.remoteCoverUrl,
                    localCoverPath = keptCover,
                    syncEnabled = prev?.syncEnabled ?: false,
                    lastSyncedAt = prev?.lastSyncedAt ?: 0L,
                )
            }

            val playlistTracks = buildList {
                for (pl in manifest.playlists) {
                    pl.tracks.forEachIndexed { idx, item ->
                        add(
                            PlaylistTrackEntity(
                                playlistId = pl.id,
                                position = idx,
                                spotifyId = item.spotifyId,
                                canonicalTrackId = item.canonicalId,
                                title = item.title,
                                artist = item.artist,
                                album = item.album,
                                durationMs = item.durationMs,
                                pcDownloaded = item.downloaded,
                            )
                        )
                    }
                }
            }

            val aliases = buildList {
                for (t in manifest.tracks) {
                    for (alias in t.aliasIds) {
                        add(TrackAliasEntity(aliasId = alias, canonicalTrackId = t.id))
                    }
                }
            }

            database.withTransaction {
                if (removedPlaylistIds.isNotEmpty()) {
                    removedPlaylistIds.chunked(SQLITE_BIND_CHUNK).forEach { dao.deletePlaylistsByIds(it) }
                }
                if (removedTrackIds.isNotEmpty()) {
                    removedTrackIds.chunked(SQLITE_BIND_CHUNK).forEach { dao.deleteTracksByIds(it) }
                }
                if (updatedPlaylists.isNotEmpty()) {
                    dao.upsertPlaylists(updatedPlaylists)
                }
                if (updatedTracks.isNotEmpty()) {
                    dao.upsertTracks(updatedTracks)
                }
                dao.clearAllPlaylistTracks()
                if (playlistTracks.isNotEmpty()) {
                    dao.insertPlaylistTracks(playlistTracks)
                }
                dao.clearAllAliases()
                if (aliases.isNotEmpty()) {
                    dao.insertAliases(aliases)
                }
            }

            for ((localPath, coverPath) in deletedTrackArtifacts) {
                storage.deleteTrackArtifacts(localPath, coverPath)
            }
        }

        return manifest
    }

    suspend fun setPlaylistSyncEnabled(playlistId: String, enabled: Boolean) {
        dao.setPlaylistSyncEnabled(playlistId, enabled)
    }

    suspend fun offloadPlaylist(playlistId: String): Int {
        dao.setPlaylistSyncEnabled(playlistId, false)
        return cleanOrphanFiles()
    }

    suspend fun cleanOrphanFiles(): Int = withContext(Dispatchers.IO) {
        val playlists = dao.getAllPlaylists()
        val playlistTracks = dao.getAllPlaylistTracks()
        val tracks = dao.getAllTracks()

        val plan = SyncPlanner.plan(
            playlists = playlists,
            playlistTracks = playlistTracks,
            tracks = tracks,
            syncAllLibrary = false,
            fileExists = { path -> storage.fileExistsNonEmpty(path) },
        )

        val now = System.currentTimeMillis()
        for (orphan in plan.orphanTracks) {
            storage.deleteTrackArtifacts(orphan.localFilePath, orphan.localCoverPath)
            dao.clearTrackLocalFile(orphan.id, now)
        }
        plan.orphanTracks.size
    }

    private companion object {
        const val SQLITE_BIND_CHUNK = 500
    }
}
