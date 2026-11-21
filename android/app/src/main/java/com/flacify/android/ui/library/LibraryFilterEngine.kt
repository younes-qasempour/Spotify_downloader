package com.flacify.android.ui.library

import com.flacify.android.data.db.TrackEntity
import com.flacify.android.data.db.TrackSyncStatus
import java.util.Locale

enum class TrackSortOption(val label: String) {
    ARTIST_ASC("Artist"),
    TITLE_ASC("Title"),
    ALBUM_ASC("Album"),
    QUALITY_DESC("Quality"),
    SIZE_DESC("Size"),
}

enum class TrackSyncFilter(val label: String) {
    ALL("All"),
    OFFLINE_ONLY("Offline"),
    NOT_SYNCED("PC Only"),
}

object LibraryFilterEngine {

    fun filterAndSort(
        tracks: List<TrackEntity>,
        query: String = "",
        syncFilter: TrackSyncFilter = TrackSyncFilter.ALL,
        genreFilter: String? = null,
        sortOption: TrackSortOption = TrackSortOption.ARTIST_ASC,
    ): List<TrackEntity> {
        val tokens = query.trim().lowercase(Locale.ROOT)
            .split(WHITESPACE_REGEX)
            .filter { it.isNotEmpty() }
        val cleanGenre = genreFilter?.trim()?.takeIf { it.isNotEmpty() }?.lowercase(Locale.ROOT)

        val filtered = tracks.filter { track ->
            val isOffline = track.syncStatus == TrackSyncStatus.SYNCED &&
                !track.localFilePath.isNullOrBlank()

            val syncMatches = when (syncFilter) {
                TrackSyncFilter.ALL -> true
                TrackSyncFilter.OFFLINE_ONLY -> isOffline
                TrackSyncFilter.NOT_SYNCED -> !isOffline
            }
            if (!syncMatches) return@filter false

            if (cleanGenre != null) {
                val trackGenres = track.genre.lowercase(Locale.ROOT)
                if (!trackGenres.contains(cleanGenre)) return@filter false
            }

            if (tokens.isNotEmpty()) {
                val haystack = buildString {
                    append(track.title)
                    append(' ')
                    append(track.artist)
                    append(' ')
                    append(track.album)
                    append(' ')
                    append(track.genre)
                    append(' ')
                    append(track.qualityBadge)
                }.lowercase(Locale.ROOT)
                if (!tokens.all { haystack.contains(it) }) return@filter false
            }

            true
        }

        return when (sortOption) {
            TrackSortOption.ARTIST_ASC -> filtered.sortedWith(
                compareBy<TrackEntity> { it.artist.lowercase(Locale.ROOT) }
                    .thenBy { it.album.lowercase(Locale.ROOT) }
                    .thenBy { it.trackNumber }
                    .thenBy { it.title.lowercase(Locale.ROOT) }
            )
            TrackSortOption.TITLE_ASC -> filtered.sortedWith(
                compareBy<TrackEntity> { it.title.lowercase(Locale.ROOT) }
                    .thenBy { it.artist.lowercase(Locale.ROOT) }
            )
            TrackSortOption.ALBUM_ASC -> filtered.sortedWith(
                compareBy<TrackEntity> { it.album.lowercase(Locale.ROOT) }
                    .thenBy { it.discNumber }
                    .thenBy { it.trackNumber }
                    .thenBy { it.title.lowercase(Locale.ROOT) }
            )
            TrackSortOption.QUALITY_DESC -> filtered.sortedWith(
                compareByDescending<TrackEntity> { qualityRank(it.qualityBadge, it.ext) }
                    .thenByDescending { it.remoteFileSize.coerceAtLeast(it.localFileSize) }
                    .thenBy { it.artist.lowercase(Locale.ROOT) }
                    .thenBy { it.title.lowercase(Locale.ROOT) }
            )
            TrackSortOption.SIZE_DESC -> filtered.sortedWith(
                compareByDescending<TrackEntity> { it.remoteFileSize.coerceAtLeast(it.localFileSize) }
                    .thenBy { it.title.lowercase(Locale.ROOT) }
            )
        }
    }

    fun extractGenres(tracks: List<TrackEntity>): List<String> =
        tracks.asSequence()
            .flatMap { it.genre.split(',').asSequence() }
            .map { it.trim() }
            .filter { it.isNotEmpty() }
            .distinctBy { it.lowercase(Locale.ROOT) }
            .sortedWith(String.CASE_INSENSITIVE_ORDER)
            .toList()

    fun qualityRank(badge: String, ext: String = ""): Int {
        val upper = badge.uppercase(Locale.ROOT)
        val lowerExt = ext.lowercase(Locale.ROOT)
        return when {
            upper.contains("24") -> 6
            upper.contains("FLAC") || lowerExt == ".flac" -> 5
            upper.contains("WAV") || lowerExt == ".wav" -> 4
            upper.contains("320") || upper.contains("MP3") || lowerExt == ".mp3" -> 3
            upper.contains("OPUS") || upper.contains("M4A") || lowerExt == ".opus" || lowerExt == ".m4a" -> 2
            upper.isNotBlank() -> 1
            else -> 0
        }
    }

    private val WHITESPACE_REGEX = Regex("\\s+")
}

object FormatUtils {
    fun formatDuration(durationMs: Long): String {
        if (durationMs <= 0L) return "0:00"
        val totalSeconds = durationMs / 1000L
        val hours = totalSeconds / 3600L
        val minutes = (totalSeconds % 3600L) / 60L
        val seconds = totalSeconds % 60L
        return if (hours > 0L) {
            String.format(Locale.US, "%d:%02d:%02d", hours, minutes, seconds)
        } else {
            String.format(Locale.US, "%d:%02d", minutes, seconds)
        }
    }

    fun formatBytes(bytes: Long): String {
        if (bytes <= 0L) return "0 MB"
        val gb = 1024.0 * 1024.0 * 1024.0
        val mb = 1024.0 * 1024.0
        return when {
            bytes >= gb -> String.format(Locale.US, "%.2f GB", bytes / gb)
            else -> String.format(Locale.US, "%.1f MB", bytes / mb)
        }
    }
}
