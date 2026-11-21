package com.flacify.android

import com.flacify.android.data.db.TrackEntity
import com.flacify.android.data.db.TrackSyncStatus
import com.flacify.android.ui.library.FormatUtils
import com.flacify.android.ui.library.LibraryFilterEngine
import com.flacify.android.ui.library.TrackSortOption
import com.flacify.android.ui.library.TrackSyncFilter
import org.junit.Assert.assertEquals
import org.junit.Test

class LibraryFilterEngineTest {

    private fun track(
        id: String,
        title: String,
        artist: String,
        album: String,
        genre: String = "",
        quality: String = "FLAC 16",
        ext: String = ".flac",
        size: Long = 30_000_000L,
        offline: Boolean = true,
    ) = TrackEntity(
        id = id,
        title = title,
        artist = artist,
        album = album,
        durationMs = 210_000L,
        trackNumber = 1,
        discNumber = 1,
        genre = genre,
        qualityBadge = quality,
        sourceType = "Musilon",
        filename = "$id$ext",
        ext = ext,
        remoteFileSize = size,
        remoteMtimeMs = 1000L,
        fileUrl = "/api/sync/tracks/$id/file",
        coverUrl = "/api/media/cover/track/$id",
        lyricsUrl = "/api/lyrics/$id",
        hasRemoteLrc = true,
        localFilePath = if (offline) "/music/$id$ext" else null,
        localFileSize = if (offline) size else 0L,
        syncStatus = if (offline) TrackSyncStatus.SYNCED else TrackSyncStatus.NOT_SYNCED,
    )

    @Test
    fun filtersByMultiTokenQuerySyncStateAndGenre() {
        val sample = listOf(
            track("1", "Usseewa", "Ado", "Kyogen", genre = "J-Pop, Rock", quality = "FLAC 24", offline = true),
            track("2", "505", "Arctic Monkeys", "Favourite Worst Nightmare", genre = "Indie Rock", quality = "FLAC 16", offline = false),
            track("3", "Dream On", "Aerosmith", "Aerosmith", genre = "Classic Rock", quality = "YTM OPUS", ext = ".opus", offline = true),
        )

        val multiToken = LibraryFilterEngine.filterAndSort(
            tracks = sample,
            query = "ado 24 kyogen",
        )
        assertEquals(listOf("1"), multiToken.map { it.id })

        val offlineOnly = LibraryFilterEngine.filterAndSort(
            tracks = sample,
            syncFilter = TrackSyncFilter.OFFLINE_ONLY,
        )
        assertEquals(listOf("1", "3"), offlineOnly.map { it.id })

        val pcOnly = LibraryFilterEngine.filterAndSort(
            tracks = sample,
            syncFilter = TrackSyncFilter.NOT_SYNCED,
        )
        assertEquals(listOf("2"), pcOnly.map { it.id })

        val genreFiltered = LibraryFilterEngine.filterAndSort(
            tracks = sample,
            genreFilter = "Indie Rock",
        )
        assertEquals(listOf("2"), genreFiltered.map { it.id })

        assertEquals(
            listOf("Classic Rock", "Indie Rock", "J-Pop", "Rock"),
            LibraryFilterEngine.extractGenres(sample),
        )
    }

    @Test
    fun sortsByQualityTitleArtistAlbumAndSize() {
        val sample = listOf(
            track("opus", "Zebra Song", "Beta", "Album B", quality = "YTM OPUS", ext = ".opus", size = 5_000_000L),
            track("mp3", "Middle Song", "Alpha", "Album C", quality = "320K", ext = ".mp3", size = 10_000_000L),
            track("flac16", "Alpha Song", "Gamma", "Album A", quality = "FLAC 16", ext = ".flac", size = 28_000_000L),
            track("flac24", "HiRes Song", "Delta", "Album D", quality = "FLAC 24", ext = ".flac", size = 62_000_000L),
        )

        assertEquals(
            listOf("flac24", "flac16", "mp3", "opus"),
            LibraryFilterEngine.filterAndSort(sample, sortOption = TrackSortOption.QUALITY_DESC).map { it.id },
        )
        assertEquals(
            listOf("flac24", "flac16", "mp3", "opus"),
            LibraryFilterEngine.filterAndSort(sample, sortOption = TrackSortOption.SIZE_DESC).map { it.id },
        )
        assertEquals(
            listOf("flac16", "flac24", "mp3", "opus"),
            LibraryFilterEngine.filterAndSort(sample, sortOption = TrackSortOption.TITLE_ASC).map { it.id },
        )
        assertEquals(
            listOf("mp3", "opus", "flac24", "flac16"),
            LibraryFilterEngine.filterAndSort(sample, sortOption = TrackSortOption.ARTIST_ASC).map { it.id },
        )
        assertEquals(
            listOf("flac16", "opus", "mp3", "flac24"),
            LibraryFilterEngine.filterAndSort(sample, sortOption = TrackSortOption.ALBUM_ASC).map { it.id },
        )
    }

    @Test
    fun formatsDurationAndBytesCleanly() {
        assertEquals("0:00", FormatUtils.formatDuration(0L))
        assertEquals("4:13", FormatUtils.formatDuration(253_000L))
        assertEquals("1:02:05", FormatUtils.formatDuration(3_725_000L))

        assertEquals("0 MB", FormatUtils.formatBytes(0L))
        assertEquals("1.0 MB", FormatUtils.formatBytes(1024L * 1024L))
        assertEquals("2.00 GB", FormatUtils.formatBytes(2L * 1024L * 1024L * 1024L))
    }
}
