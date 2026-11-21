package com.flacify.android.sync

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import android.content.pm.ServiceInfo
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.work.CoroutineWorker
import androidx.work.ForegroundInfo
import androidx.work.WorkerParameters
import androidx.work.workDataOf
import com.flacify.android.FlacifyApplication
import com.flacify.android.network.FlacifyApiClient
import com.flacify.android.network.FlacifyApiException
import kotlinx.coroutines.CancellationException
import java.io.File

class FlacifySyncWorker(
    appContext: Context,
    params: WorkerParameters,
) : CoroutineWorker(appContext, params) {

    override suspend fun doWork(): Result {
        val app = applicationContext as FlacifyApplication
        val repo = app.repository
        val dao = app.database.dao()
        val storage = app.storage
        val apiClient = app.apiClient
        val downloader = app.fileDownloader

        val syncAllLibrary = inputData.getBoolean(KEY_SYNC_ALL_LIBRARY, false)

        ensureNotificationChannel()
        try {
            setForeground(createForegroundInfo("Connecting to Flacify PC...", 0, 0))
        } catch (_: Exception) {
            // Non-fatal if background FGS restriction prevents immediate notification promote.
        }

        val cfg = repo.currentConnection()
        if (!cfg.isPaired) {
            return Result.failure(workDataOf(KEY_ERROR to "Not paired with a Flacify PC."))
        }
        val candidateUrls = cfg.orderedCandidateUrls()

        try {
            repo.refreshManifestFromPc()
        } catch (ex: FlacifyApiException) {
            return Result.failure(workDataOf(KEY_ERROR to (ex.message ?: "Sync failed.")))
        } catch (ex: Exception) {
            return Result.failure(workDataOf(KEY_ERROR to (ex.message ?: "Could not refresh catalog.")))
        }

        val playlists = dao.getAllPlaylists()
        val playlistTracks = dao.getAllPlaylistTracks()
        val tracks = dao.getAllTracks()

        // Cache covers for enabled playlists before downloading tracks.
        for (pl in playlists) {
            if (isStopped) break
            if ((syncAllLibrary || pl.syncEnabled) &&
                pl.coverUrl.isNotBlank() &&
                !storage.fileExistsNonEmpty(pl.localCoverPath)
            ) {
                try {
                    val bytes = apiClient.downloadBytesOrNull(candidateUrls, cfg.pairToken, pl.coverUrl)
                    if (bytes != null && bytes.isNotEmpty()) {
                        val dest = storage.playlistCoverFile(pl.id)
                        dest.writeBytes(bytes)
                        dao.updatePlaylistCover(pl.id, dest.absolutePath)
                    }
                } catch (_: FlacifyApiException.Unauthorized) {
                    return Result.failure(workDataOf(KEY_ERROR to "Pairing token rejected by PC (HTTP 401)."))
                } catch (_: FlacifyApiException.LanDisabled) {
                    return Result.failure(workDataOf(KEY_ERROR to "LAN sync disabled on PC (HTTP 403)."))
                } catch (_: Exception) {
                }
            }
        }

        val plan = SyncPlanner.plan(
            playlists = playlists,
            playlistTracks = playlistTracks,
            tracks = tracks,
            syncAllLibrary = syncAllLibrary,
            fileExists = { path -> storage.fileExistsNonEmpty(path) },
        )

        val totalTracks = plan.tracksToDownload.size
        val totalBytes = plan.totalBytesToDownload
        var completedTracks = 0
        var completedBytesBeforeCurrent = 0L
        var errorCount = 0

        if (totalTracks == 0) {
            val now = System.currentTimeMillis()
            for (pl in playlists) {
                if (syncAllLibrary || pl.syncEnabled) {
                    dao.markPlaylistSynced(pl.id, now)
                }
            }
            return Result.success(
                workDataOf(
                    KEY_COMPLETED_TRACKS to 0,
                    KEY_TOTAL_TRACKS to 0,
                    KEY_BYTES_DONE to 0L,
                    KEY_TOTAL_BYTES to 0L,
                )
            )
        }

        for (track in plan.tracksToDownload) {
            if (isStopped) {
                dao.resetStaleSyncingTracks()
                throw CancellationException("Sync cancelled by user.")
            }

            dao.markTrackSyncing(track.id)
            updateProgressState(
                title = track.title,
                completedTracks = completedTracks,
                totalTracks = totalTracks,
                bytesDone = completedBytesBeforeCurrent,
                totalBytes = totalBytes,
                updateNotification = true,
            )

            try {
                val destFile = storage.trackFile(track.id, track.ext)
                var lastUiUpdateMs = 0L
                val dl = downloader.downloadTrackFile(
                    candidateUrls = candidateUrls,
                    token = cfg.pairToken,
                    relativeFileUrl = track.fileUrl,
                    destFile = destFile,
                    expectedSize = track.remoteFileSize,
                    onProgress = { trackDone, _ ->
                        val nowMs = System.currentTimeMillis()
                        if (nowMs - lastUiUpdateMs >= 350L) {
                            lastUiUpdateMs = nowMs
                            setProgressAsync(
                                workDataOf(
                                    KEY_CURRENT_TITLE to track.title,
                                    KEY_COMPLETED_TRACKS to completedTracks,
                                    KEY_TOTAL_TRACKS to totalTracks,
                                    KEY_BYTES_DONE to (completedBytesBeforeCurrent + trackDone),
                                    KEY_TOTAL_BYTES to totalBytes,
                                )
                            )
                        }
                    },
                )

                val coverPath = cacheTrackCover(
                    candidateUrls = candidateUrls,
                    token = cfg.pairToken,
                    trackId = track.id,
                    coverUrl = track.coverUrl,
                    existingCoverPath = track.localCoverPath,
                    targetFile = storage.trackCoverFile(track.id),
                    apiClient = apiClient,
                    storage = storage,
                )

                val (lyricsText, lyricsIsSynced, lyricsFetched) = cacheTrackLyrics(
                    candidateUrls = candidateUrls,
                    token = cfg.pairToken,
                    trackId = track.id,
                    existingLyrics = track.lyricsText,
                    existingIsSynced = track.lyricsIsSynced,
                    existingFetched = track.lyricsSynced,
                    apiClient = apiClient,
                )

                dao.markTrackSynced(
                    trackId = track.id,
                    localFilePath = dl.file.absolutePath,
                    localFileSize = dl.bytesWrittenTotal,
                    localMtimeMs = track.remoteMtimeMs,
                    localEtag = dl.etag,
                    localCoverPath = coverPath,
                    lyricsText = lyricsText,
                    lyricsIsSynced = lyricsIsSynced,
                    lyricsSynced = lyricsFetched,
                    updatedAt = System.currentTimeMillis(),
                )

                completedBytesBeforeCurrent += track.remoteFileSize.coerceAtLeast(dl.bytesWrittenTotal)
            } catch (cancel: CancellationException) {
                dao.resetStaleSyncingTracks()
                throw cancel
            } catch (authEx: FlacifyApiException.Unauthorized) {
                dao.markTrackError(track.id, authEx.message ?: "Unauthorized", System.currentTimeMillis())
                return Result.failure(workDataOf(KEY_ERROR to (authEx.message ?: "Unauthorized")))
            } catch (lanEx: FlacifyApiException.LanDisabled) {
                dao.markTrackError(track.id, lanEx.message ?: "LAN disabled", System.currentTimeMillis())
                return Result.failure(workDataOf(KEY_ERROR to (lanEx.message ?: "LAN disabled")))
            } catch (ex: Exception) {
                errorCount++
                dao.markTrackError(
                    track.id,
                    ex.message ?: "Download failed",
                    System.currentTimeMillis(),
                )
            }

            completedTracks++
            updateProgressState(
                title = track.title,
                completedTracks = completedTracks,
                totalTracks = totalTracks,
                bytesDone = completedBytesBeforeCurrent,
                totalBytes = totalBytes,
                updateNotification = true,
            )
        }

        if (errorCount == 0) {
            val doneTime = System.currentTimeMillis()
            for (pl in playlists) {
                if (syncAllLibrary || pl.syncEnabled) {
                    dao.markPlaylistSynced(pl.id, doneTime)
                }
            }
        }

        return Result.success(
            workDataOf(
                KEY_COMPLETED_TRACKS to completedTracks,
                KEY_TOTAL_TRACKS to totalTracks,
                KEY_BYTES_DONE to completedBytesBeforeCurrent,
                KEY_TOTAL_BYTES to totalBytes,
                KEY_ERROR_COUNT to errorCount,
            )
        )
    }

    private suspend fun cacheTrackCover(
        candidateUrls: List<String>,
        token: String,
        trackId: String,
        coverUrl: String,
        existingCoverPath: String?,
        targetFile: File,
        apiClient: FlacifyApiClient,
        storage: com.flacify.android.data.storage.LocalMediaStorage,
    ): String? {
        if (storage.fileExistsNonEmpty(existingCoverPath)) return existingCoverPath
        if (coverUrl.isBlank()) return null
        return try {
            val bytes = apiClient.downloadBytesOrNull(candidateUrls, token, coverUrl)
            if (bytes != null && bytes.isNotEmpty()) {
                targetFile.writeBytes(bytes)
                targetFile.absolutePath
            } else {
                null
            }
        } catch (_: Exception) {
            null
        }
    }

    private suspend fun cacheTrackLyrics(
        candidateUrls: List<String>,
        token: String,
        trackId: String,
        existingLyrics: String?,
        existingIsSynced: Boolean,
        existingFetched: Boolean,
        apiClient: FlacifyApiClient,
    ): Triple<String?, Boolean, Boolean> {
        if (existingFetched && !existingLyrics.isNullOrBlank()) {
            return Triple(existingLyrics, existingIsSynced, true)
        }
        return try {
            val res = apiClient.fetchLyrics(candidateUrls, token, trackId).data
            if (res.hasLyrics && res.rawText.isNotBlank()) {
                Triple(res.rawText, res.isSynced, true)
            } else {
                Triple(existingLyrics, existingIsSynced, true)
            }
        } catch (_: Exception) {
            Triple(existingLyrics, existingIsSynced, existingFetched)
        }
    }

    private suspend fun updateProgressState(
        title: String,
        completedTracks: Int,
        totalTracks: Int,
        bytesDone: Long,
        totalBytes: Long,
        updateNotification: Boolean,
    ) {
        setProgress(
            workDataOf(
                KEY_CURRENT_TITLE to title,
                KEY_COMPLETED_TRACKS to completedTracks,
                KEY_TOTAL_TRACKS to totalTracks,
                KEY_BYTES_DONE to bytesDone,
                KEY_TOTAL_BYTES to totalBytes,
            )
        )
        if (updateNotification) {
            try {
                setForeground(createForegroundInfo(title, completedTracks, totalTracks))
            } catch (_: Exception) {
            }
        }
    }

    private fun ensureNotificationChannel() {
        val mgr = applicationContext.getSystemService(Context.NOTIFICATION_SERVICE) as? NotificationManager
            ?: return
        val existing = mgr.getNotificationChannel(CHANNEL_ID)
        if (existing == null) {
            val channel = NotificationChannel(
                CHANNEL_ID,
                "Flacify Offline Sync",
                NotificationManager.IMPORTANCE_LOW,
            ).apply {
                description = "Background lossless FLAC playlist synchronization progress"
            }
            mgr.createNotificationChannel(channel)
        }
    }

    private fun createForegroundInfo(
        title: String,
        completed: Int,
        total: Int,
    ): ForegroundInfo {
        val text = if (total > 0) {
            "$completed / $total · $title"
        } else {
            title
        }
        val notification: Notification = NotificationCompat.Builder(applicationContext, CHANNEL_ID)
            .setSmallIcon(android.R.drawable.stat_sys_download)
            .setContentTitle("Syncing Lossless FLAC")
            .setContentText(text)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .apply {
                if (total > 0) {
                    setProgress(total, completed.coerceIn(0, total), false)
                } else {
                    setProgress(0, 0, true)
                }
            }
            .build()

        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            ForegroundInfo(
                NOTIFICATION_ID,
                notification,
                ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC,
            )
        } else {
            ForegroundInfo(NOTIFICATION_ID, notification)
        }
    }

    companion object {
        const val UNIQUE_WORK_NAME = "flacify_offline_sync"
        private const val CHANNEL_ID = "flacify_sync_channel"
        private const val NOTIFICATION_ID = 2101

        const val KEY_SYNC_ALL_LIBRARY = "sync_all_library"
        const val KEY_CURRENT_TITLE = "current_title"
        const val KEY_COMPLETED_TRACKS = "completed_tracks"
        const val KEY_TOTAL_TRACKS = "total_tracks"
        const val KEY_BYTES_DONE = "bytes_done"
        const val KEY_TOTAL_BYTES = "total_bytes"
        const val KEY_ERROR_COUNT = "error_count"
        const val KEY_ERROR = "error"
    }
}
