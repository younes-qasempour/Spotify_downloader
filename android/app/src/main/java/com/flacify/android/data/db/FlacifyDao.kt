package com.flacify.android.data.db

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import kotlinx.coroutines.flow.Flow

@Dao
interface FlacifyDao {

    @Query("SELECT * FROM playlists ORDER BY name COLLATE NOCASE ASC")
    fun observeAllPlaylists(): Flow<List<PlaylistEntity>>

    @Query("SELECT * FROM tracks ORDER BY artist COLLATE NOCASE ASC, title COLLATE NOCASE ASC")
    fun observeAllTracks(): Flow<List<TrackEntity>>

    @Query("SELECT * FROM tracks WHERE syncStatus = 'SYNCED' AND localFilePath IS NOT NULL ORDER BY artist COLLATE NOCASE ASC, title COLLATE NOCASE ASC")
    fun observeSyncedTracks(): Flow<List<TrackEntity>>

    @Query("SELECT * FROM playlist_tracks ORDER BY playlistId ASC, position ASC")
    fun observeAllPlaylistTracks(): Flow<List<PlaylistTrackEntity>>

    @Query("SELECT COUNT(*) FROM tracks WHERE syncStatus = 'SYNCED' AND localFilePath IS NOT NULL")
    fun observeSyncedTrackCount(): Flow<Int>

    @Query("SELECT COALESCE(SUM(localFileSize), 0) FROM tracks WHERE syncStatus = 'SYNCED' AND localFilePath IS NOT NULL")
    fun observeSyncedAudioBytes(): Flow<Long>

    @Query("SELECT * FROM playlist_tracks WHERE playlistId = :playlistId ORDER BY position ASC")
    fun observePlaylistTracks(playlistId: String): Flow<List<PlaylistTrackEntity>>

    @Query("SELECT * FROM playlists")
    suspend fun getAllPlaylists(): List<PlaylistEntity>

    @Query("SELECT * FROM tracks")
    suspend fun getAllTracks(): List<TrackEntity>

    @Query("SELECT * FROM playlist_tracks ORDER BY playlistId ASC, position ASC")
    suspend fun getAllPlaylistTracks(): List<PlaylistTrackEntity>

    @Query("SELECT * FROM tracks WHERE id = :id LIMIT 1")
    suspend fun getTrackById(id: String): TrackEntity?

    @Query("SELECT canonicalTrackId FROM track_aliases WHERE aliasId = :aliasId LIMIT 1")
    suspend fun getCanonicalIdForAlias(aliasId: String): String?

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsertTracks(tracks: List<TrackEntity>)

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsertPlaylists(playlists: List<PlaylistEntity>)

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertPlaylistTracks(items: List<PlaylistTrackEntity>)

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertAliases(aliases: List<TrackAliasEntity>)

    @Query("DELETE FROM playlist_tracks")
    suspend fun clearAllPlaylistTracks()

    @Query("DELETE FROM track_aliases")
    suspend fun clearAllAliases()

    @Query("DELETE FROM playlists WHERE id IN (:ids)")
    suspend fun deletePlaylistsByIds(ids: List<String>)

    @Query("DELETE FROM playlists")
    suspend fun deleteAllPlaylists()

    @Query("DELETE FROM tracks WHERE id IN (:ids)")
    suspend fun deleteTracksByIds(ids: List<String>)

    @Query("DELETE FROM tracks")
    suspend fun deleteAllTracks()

    @Query("UPDATE playlists SET syncEnabled = :enabled WHERE id = :playlistId")
    suspend fun setPlaylistSyncEnabled(playlistId: String, enabled: Boolean)

    @Query("UPDATE playlists SET localCoverPath = :localCoverPath WHERE id = :playlistId")
    suspend fun updatePlaylistCover(playlistId: String, localCoverPath: String)

    @Query("UPDATE playlists SET lastSyncedAt = :timestamp WHERE id = :playlistId")
    suspend fun markPlaylistSynced(playlistId: String, timestamp: Long)

    @Query("UPDATE tracks SET syncStatus = 'SYNCING', lastError = NULL WHERE id = :trackId")
    suspend fun markTrackSyncing(trackId: String)

    @Query(
        """
        UPDATE tracks
        SET localFilePath = :localFilePath,
            localFileSize = :localFileSize,
            localMtimeMs = :localMtimeMs,
            localEtag = :localEtag,
            localCoverPath = COALESCE(:localCoverPath, localCoverPath),
            lyricsText = COALESCE(:lyricsText, lyricsText),
            lyricsIsSynced = :lyricsIsSynced,
            lyricsSynced = :lyricsSynced,
            syncStatus = 'SYNCED',
            lastError = NULL,
            updatedAt = :updatedAt
        WHERE id = :trackId
        """
    )
    suspend fun markTrackSynced(
        trackId: String,
        localFilePath: String,
        localFileSize: Long,
        localMtimeMs: Long,
        localEtag: String?,
        localCoverPath: String?,
        lyricsText: String?,
        lyricsIsSynced: Boolean,
        lyricsSynced: Boolean,
        updatedAt: Long,
    )

    @Query("UPDATE tracks SET syncStatus = 'ERROR', lastError = :error, updatedAt = :updatedAt WHERE id = :trackId")
    suspend fun markTrackError(trackId: String, error: String, updatedAt: Long)

    @Query(
        """
        UPDATE tracks
        SET localFilePath = NULL,
            localFileSize = 0,
            localMtimeMs = 0,
            localEtag = NULL,
            localCoverPath = NULL,
            syncStatus = 'NOT_SYNCED',
            lastError = NULL,
            updatedAt = :updatedAt
        WHERE id = :trackId
        """
    )
    suspend fun clearTrackLocalFile(trackId: String, updatedAt: Long)

    @Query("UPDATE tracks SET syncStatus = 'NOT_SYNCED' WHERE syncStatus = 'SYNCING'")
    suspend fun resetStaleSyncingTracks()
}
