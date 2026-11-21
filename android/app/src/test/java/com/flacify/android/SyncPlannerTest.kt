package com.flacify.android

import com.flacify.android.data.db.PlaylistEntity
import com.flacify.android.data.db.PlaylistTrackEntity
import com.flacify.android.data.db.TrackEntity
import com.flacify.android.data.db.TrackSyncStatus
import com.flacify.android.sync.SyncPlanner
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class SyncPlannerTest {

    private fun sampleTrack(
        id: String,
        size: Long = 30_000_000L,
        mtime: Long = 1000L,
        syncStatus: String = TrackSyncStatus.NOT_SYNCED,
        localPath: String? = null,
        localSize: Long = 0L,
        localMtime: Long = 0L,
    ) = TrackEntity(
        id = id,
        title = "Title $id",
        artist = "Artist",
        album = "Album",
        durationMs = 200_000L,
        trackNumber = 1,
        discNumber = 1,
        genre = "Rock",
        qualityBadge = "FLAC 16",
        sourceType = "Musilon",
        filename = "$id.flac",
        ext = ".flac",
        remoteFileSize = size,
        remoteMtimeMs = mtime,
        fileUrl = "/api/sync/tracks/$id/file",
        coverUrl = "/api/media/cover/track/$id",
        lyricsUrl = "/api/lyrics/$id",
        hasRemoteLrc = true,
        localFilePath = localPath,
        localFileSize = localSize,
        localMtimeMs = localMtime,
        syncStatus = syncStatus,
    )

    @Test
    fun deduplicatesSharedTracksAndProtectsSharedFilesDuringOrphanCleanup() {
        val playlists = listOf(
            PlaylistEntity("pl1", "Workout", 2, 2, "", "", syncEnabled = true),
            PlaylistEntity("pl2", "Chill", 2, 2, "", "", syncEnabled = false),
        )
        val plTracks = listOf(
            PlaylistTrackEntity("pl1", 0, "sp_shared", "canon_shared", "Shared", "Art", "Alb", 180_000L, true),
            PlaylistTrackEntity("pl1", 1, "sp_t1", "canon_1", "One", "Art", "Alb", 180_000L, true),
            PlaylistTrackEntity("pl2", 0, "sp_shared_alias", "canon_shared", "Shared", "Art", "Alb", 180_000L, true),
            PlaylistTrackEntity("pl2", 1, "sp_t2", "canon_2", "Two", "Art", "Alb", 180_000L, true),
        )
        val tracks = listOf(
            sampleTrack("canon_shared", size = 100L),
            sampleTrack("canon_1", size = 200L),
            sampleTrack(
                id = "canon_2",
                size = 300L,
                syncStatus = TrackSyncStatus.SYNCED,
                localPath = "/music/canon_2.flac",
                localSize = 300L,
                localMtime = 1000L,
            ),
        )

        val plan = SyncPlanner.plan(playlists, plTracks, tracks, fileExists = { true })

        assertEquals(setOf("canon_shared", "canon_1"), plan.neededTrackIds)
        assertEquals(listOf("canon_shared", "canon_1"), plan.tracksToDownload.map { it.id })
        assertEquals(300L, plan.totalBytesToDownload)
        // Only canon_2 (unique to disabled pl2) is orphaned; canon_shared is protected by pl1
        assertEquals(listOf("canon_2"), plan.orphanTracks.map { it.id })
    }

    @Test
    fun detectsStaleMtimeOrSizeAndMissingDiskFiles() {
        val unchanged = sampleTrack(
            id = "ok",
            size = 500L,
            mtime = 2000L,
            syncStatus = TrackSyncStatus.SYNCED,
            localPath = "/music/ok.flac",
            localSize = 500L,
            localMtime = 2000L,
        )
        val upgradedOnPc = sampleTrack(
            id = "upgraded",
            size = 600L,
            mtime = 3000L,
            syncStatus = TrackSyncStatus.SYNCED,
            localPath = "/music/upgraded.flac",
            localSize = 500L,
            localMtime = 2000L,
        )
        val missingOnDisk = sampleTrack(
            id = "missing",
            size = 500L,
            mtime = 2000L,
            syncStatus = TrackSyncStatus.SYNCED,
            localPath = "/music/missing.flac",
            localSize = 500L,
            localMtime = 2000L,
        )

        assertFalse(SyncPlanner.needsDownload(unchanged, fileExistsOnDisk = true))
        assertTrue(SyncPlanner.needsDownload(upgradedOnPc, fileExistsOnDisk = true))
        assertTrue(SyncPlanner.needsDownload(missingOnDisk, fileExistsOnDisk = false))

        val plan = SyncPlanner.plan(
            playlists = emptyList(),
            playlistTracks = emptyList(),
            tracks = listOf(unchanged, upgradedOnPc, missingOnDisk),
            syncAllLibrary = true,
            fileExists = { p -> p != "/music/missing.flac" },
        )
        assertEquals(listOf("upgraded", "missing"), plan.tracksToDownload.map { it.id })
    }

    @Test
    fun summarizePlaylistsDeduplicatesByteCountWithoutDoubleCountingRepeats() {
        val playlists = listOf(
            PlaylistEntity("pl1", "Repeat Mix", 2, 2, "", "", syncEnabled = true),
        )
        val plTracks = listOf(
            PlaylistTrackEntity("pl1", 0, "s1", "c1", "Track", "A", "Alb", 1000L, true),
            PlaylistTrackEntity("pl1", 1, "s1_dup", "c1", "Track", "A", "Alb", 1000L, true),
        )
        val tracksById = mapOf(
            "c1" to sampleTrack(
                id = "c1",
                size = 25_000_000L,
                syncStatus = TrackSyncStatus.SYNCED,
                localPath = "/music/c1.flac",
                localSize = 25_000_000L,
            )
        )

        val summaries = SyncPlanner.summarizePlaylists(playlists, plTracks, tracksById)
        assertEquals(1, summaries.size)
        assertEquals(2, summaries[0].syncedOnPhoneCount)
        assertEquals(25_000_000L, summaries[0].syncedOnPhoneBytes)
        assertEquals(25_000_000L, summaries[0].totalNeededBytes)
    }
}
