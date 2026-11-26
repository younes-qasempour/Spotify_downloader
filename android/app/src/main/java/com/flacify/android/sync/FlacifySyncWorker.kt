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
import com.flacify.android.network.PairingUriParser
import com.flacify.android.ui.library.FormatUtils
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.cancel
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Semaphore
import kotlinx.coroutines.sync.withPermit
import kotlinx.coroutines.withContext
import java.io.File
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicLong
import java.util.concurrent.atomic.AtomicReference

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

        val refresh = try {
            repo.refreshManifestFromPcWithTransport()
        } catch (ex: FlacifyApiException) {
            return Result.failure(workDataOf(KEY_ERROR to (ex.message ?: "Sync failed.")))
        } catch (ex: Exception) {
            return Result.failure(workDataOf(KEY_ERROR to (ex.message ?: "Could not refresh catalog.")))
        }

        val initialBaseUrl = refresh.resolvedBaseUrl
        val initialIsUsb = PairingUriParser.isUsbLoopbackUrl(initialBaseUrl)
        val effectiveCandidateUrls = PairingUriParser.mergeCandidateUrls(initialBaseUrl, candidateUrls)
        val initialTransport = if (initialIsUsb) TRANSPORT_USB else TRANSPORT_WIFI

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
                    val bytes = apiClient.downloadBytesOrNull(effectiveCandidateUrls, cfg.pairToken, pl.coverUrl)
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
                    KEY_SPEED_BYTES_PER_SEC to 0L,
                    KEY_TRANSPORT to initialTransport,
                )
            )
        }

        val maxConcurrency = if (initialIsUsb) USB_MAX_CONCURRENCY else 1
        val completedTracks = AtomicInteger(0)
        val errorCount = AtomicInteger(0)
        val completedBytes = AtomicLong(0L)
        val inFlightBytes = ConcurrentHashMap<String, Long>()
        val activeTitle = AtomicReference(plan.tracksToDownload.first().title)
        val activeTransport = AtomicReference(initialTransport)
        val fatalError = AtomicReference<String?>(null)

        val syncStartMs = System.currentTimeMillis()
        val lastSampleMs = AtomicLong(syncStartMs)
        val lastSampleBytes = AtomicLong(0L)
        val smoothedSpeedBps = AtomicLong(0L)
        val lastProgressEmitMs = AtomicLong(0L)
        val speedLock = Any()

        fun sampleSpeedBps(nowMs: Long, nowBytes: Long): Long = synchronized(speedLock) {
            val prevMs = lastSampleMs.get()
            val dtMs = nowMs - prevMs
            if (dtMs >= 500L) {
                val deltaBytes = (nowBytes - lastSampleBytes.get()).coerceAtLeast(0L)
                val instantBps = (deltaBytes * 1000L) / dtMs
                val prevSpeed = smoothedSpeedBps.get()
                val nextSpeed = if (prevSpeed <= 0L) {
                    instantBps
                } else {
                    (prevSpeed * 6L + instantBps * 4L) / 10L
                }
                smoothedSpeedBps.set(nextSpeed)
                lastSampleMs.set(nowMs)
                lastSampleBytes.set(nowBytes)
            }
            smoothedSpeedBps.get()
        }

        suspend fun emitProgress(force: Boolean, updateNotification: Boolean) {
            val nowMs = System.currentTimeMillis()
            val prevEmit = lastProgressEmitMs.get()
            if (!force && nowMs - prevEmit < 350L) return
            if (!force && !lastProgressEmitMs.compareAndSet(prevEmit, nowMs)) return
            if (force) {
                lastProgressEmitMs.set(nowMs)
            }

            val bytesNow = completedBytes.get() + inFlightBytes.values.sum()
            val speedNow = sampleSpeedBps(nowMs, bytesNow)
            val titleNow = activeTitle.get()
            val doneNow = completedTracks.get()
            val transportNow = activeTransport.get()

            setProgressAsync(
                workDataOf(
                    KEY_CURRENT_TITLE to titleNow,
                    KEY_COMPLETED_TRACKS to doneNow,
                    KEY_TOTAL_TRACKS to totalTracks,
                    KEY_BYTES_DONE to bytesNow,
                    KEY_TOTAL_BYTES to totalBytes,
                    KEY_SPEED_BYTES_PER_SEC to speedNow,
                    KEY_TRANSPORT to transportNow,
                )
            )
            if (updateNotification) {
                try {
                    setForeground(
                        createForegroundInfo(
                            title = titleNow,
                            completed = doneNow,
                            total = totalTracks,
                            transport = transportNow,
                            speedBps = speedNow,
                        )
                    )
                } catch (_: Exception) {
                }
            }
        }

        emitProgress(force = true, updateNotification = true)

        val semaphore = Semaphore(maxConcurrency)
        try {
            coroutineScope {
                for (track in plan.tracksToDownload) {
                    launch(Dispatchers.IO) {
                        semaphore.withPermit {
                            if (isStopped) {
                                throw CancellationException("Sync cancelled by user.")
                            }
                            if (fatalError.get() != null) {
                                return@withPermit
                            }

                            activeTitle.set(track.title)
                            dao.markTrackSyncing(track.id)

                            try {
                                val destFile = storage.trackFile(track.id, track.ext)
                                val dl = downloader.downloadTrackFile(
                                    candidateUrls = effectiveCandidateUrls,
                                    token = cfg.pairToken,
                                    relativeFileUrl = track.fileUrl,
                                    destFile = destFile,
                                    expectedSize = track.remoteFileSize,
                                    onProgress = { trackDone, _ ->
                                        inFlightBytes[track.id] = trackDone
                                        activeTitle.set(track.title)
                                        val nowMs = System.currentTimeMillis()
                                        val prevEmit = lastProgressEmitMs.get()
                                        if (nowMs - prevEmit >= 350L && lastProgressEmitMs.compareAndSet(prevEmit, nowMs)) {
                                            val bytesNow = completedBytes.get() + inFlightBytes.values.sum()
                                            val speedNow = sampleSpeedBps(nowMs, bytesNow)
                                            setProgressAsync(
                                                workDataOf(
                                                    KEY_CURRENT_TITLE to track.title,
                                                    KEY_COMPLETED_TRACKS to completedTracks.get(),
                                                    KEY_TOTAL_TRACKS to totalTracks,
                                                    KEY_BYTES_DONE to bytesNow,
                                                    KEY_TOTAL_BYTES to totalBytes,
                                                    KEY_SPEED_BYTES_PER_SEC to speedNow,
                                                    KEY_TRANSPORT to activeTransport.get(),
                                                )
                                            )
                                        }
                                    },
                                )

                                val dlTransport = if (PairingUriParser.isUsbLoopbackUrl(dl.resolvedBaseUrl)) {
                                    TRANSPORT_USB
                                } else {
                                    TRANSPORT_WIFI
                                }
                                activeTransport.set(dlTransport)

                                val metadataUrls = PairingUriParser.mergeCandidateUrls(
                                    dl.resolvedBaseUrl,
                                    effectiveCandidateUrls,
                                )

                                val coverPath = cacheTrackCover(
                                    candidateUrls = metadataUrls,
                                    token = cfg.pairToken,
                                    trackId = track.id,
                                    coverUrl = track.coverUrl,
                                    existingCoverPath = track.localCoverPath,
                                    targetFile = storage.trackCoverFile(track.id),
                                    apiClient = apiClient,
                                    storage = storage,
                                )

                                val (lyricsText, lyricsIsSynced, lyricsFetched) = cacheTrackLyrics(
                                    candidateUrls = metadataUrls,
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

                                completedBytes.addAndGet(track.remoteFileSize.coerceAtLeast(dl.bytesWrittenTotal))
                            } catch (cancel: CancellationException) {
                                throw cancel
                            } catch (authEx: FlacifyApiException.Unauthorized) {
                                val msg = authEx.message ?: "Unauthorized"
                                dao.markTrackError(track.id, msg, System.currentTimeMillis())
                                fatalError.compareAndSet(null, msg)
                                this@coroutineScope.cancel(CancellationException(msg))
                                return@withPermit
                            } catch (lanEx: FlacifyApiException.LanDisabled) {
                                val msg = lanEx.message ?: "LAN disabled"
                                dao.markTrackError(track.id, msg, System.currentTimeMillis())
                                fatalError.compareAndSet(null, msg)
                                this@coroutineScope.cancel(CancellationException(msg))
                                return@withPermit
                            } catch (ex: Exception) {
                                errorCount.incrementAndGet()
                                dao.markTrackError(
                                    track.id,
                                    ex.message ?: "Download failed",
                                    System.currentTimeMillis(),
                                )
                            } finally {
                                inFlightBytes.remove(track.id)
                            }

                            completedTracks.incrementAndGet()
                            emitProgress(force = true, updateNotification = true)
                        }
                    }
                }
            }
        } catch (cancel: CancellationException) {
            withContext(NonCancellable) {
                dao.resetStaleSyncingTracks()
            }
            val fatal = fatalError.get()
            if (fatal != null) {
                return Result.failure(workDataOf(KEY_ERROR to fatal))
            }
            throw cancel
        }

        fatalError.get()?.let { fatal ->
            dao.resetStaleSyncingTracks()
            return Result.failure(workDataOf(KEY_ERROR to fatal))
        }

        val finalErrors = errorCount.get()
        if (finalErrors == 0) {
            val doneTime = System.currentTimeMillis()
            for (pl in playlists) {
                if (syncAllLibrary || pl.syncEnabled) {
                    dao.markPlaylistSynced(pl.id, doneTime)
                }
            }
        }

        val elapsedMs = (System.currentTimeMillis() - syncStartMs).coerceAtLeast(1L)
        val finalBytes = completedBytes.get()
        val avgSpeedBps = (finalBytes * 1000L) / elapsedMs

        return Result.success(
            workDataOf(
                KEY_COMPLETED_TRACKS to completedTracks.get(),
                KEY_TOTAL_TRACKS to totalTracks,
                KEY_BYTES_DONE to finalBytes,
                KEY_TOTAL_BYTES to totalBytes,
                KEY_SPEED_BYTES_PER_SEC to avgSpeedBps,
                KEY_TRANSPORT to activeTransport.get(),
                KEY_ERROR_COUNT to finalErrors,
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
        transport: String = "",
        speedBps: Long = 0L,
    ): ForegroundInfo {
        val speedText = FormatUtils.formatSpeed(speedBps)
        val text = buildString {
            if (total > 0) {
                append("$completed / $total")
                if (speedText.isNotBlank()) {
                    append(" · $speedText")
                }
                append(" · $title")
            } else {
                append(title)
            }
        }
        val notifTitle = if (transport == TRANSPORT_USB) {
            "Syncing via USB Cable"
        } else {
            "Syncing Lossless FLAC"
        }
        val notification: Notification = NotificationCompat.Builder(applicationContext, CHANNEL_ID)
            .setSmallIcon(android.R.drawable.stat_sys_download)
            .setContentTitle(notifTitle)
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
        private const val USB_MAX_CONCURRENCY = 3

        const val KEY_SYNC_ALL_LIBRARY = "sync_all_library"
        const val KEY_CURRENT_TITLE = "current_title"
        const val KEY_COMPLETED_TRACKS = "completed_tracks"
        const val KEY_TOTAL_TRACKS = "total_tracks"
        const val KEY_BYTES_DONE = "bytes_done"
        const val KEY_TOTAL_BYTES = "total_bytes"
        const val KEY_SPEED_BYTES_PER_SEC = "speed_bytes_per_sec"
        const val KEY_TRANSPORT = "transport"
        const val KEY_ERROR_COUNT = "error_count"
        const val KEY_ERROR = "error"

        const val TRANSPORT_USB = "usb"
        const val TRANSPORT_WIFI = "wifi"
    }
}
