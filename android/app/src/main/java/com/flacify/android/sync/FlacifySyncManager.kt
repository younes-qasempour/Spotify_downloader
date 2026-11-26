package com.flacify.android.sync

import android.content.Context
import androidx.work.Constraints
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.OutOfQuotaPolicy
import androidx.work.WorkInfo
import androidx.work.WorkManager
import androidx.work.workDataOf
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map

data class SyncProgressState(
    val isRunning: Boolean = false,
    val currentTitle: String = "",
    val completedTracks: Int = 0,
    val totalTracks: Int = 0,
    val bytesDone: Long = 0L,
    val totalBytes: Long = 0L,
    val speedBytesPerSec: Long = 0L,
    val transport: String = "",
    val errorCount: Int = 0,
    val terminalMessage: String? = null,
    val errorMessage: String? = null,
) {
    val isUsb: Boolean
        get() = transport == FlacifySyncWorker.TRANSPORT_USB

    val fraction: Float
        get() = when {
            totalBytes > 0L -> (bytesDone.toDouble() / totalBytes.toDouble()).toFloat().coerceIn(0f, 1f)
            totalTracks > 0 -> (completedTracks.toFloat() / totalTracks.toFloat()).coerceIn(0f, 1f)
            else -> 0f
        }
}

class FlacifySyncManager(context: Context) {
    private val workManager = WorkManager.getInstance(context.applicationContext)

    val progressFlow: Flow<SyncProgressState> =
        workManager.getWorkInfosForUniqueWorkFlow(FlacifySyncWorker.UNIQUE_WORK_NAME)
            .map { infos -> mapWorkInfos(infos) }

    fun startSync(
        syncAllLibrary: Boolean = false,
        allowUsbWithoutNetwork: Boolean = true,
    ) {
        val constraints = Constraints.Builder()
            .setRequiredNetworkType(
                if (allowUsbWithoutNetwork) NetworkType.NOT_REQUIRED else NetworkType.CONNECTED
            )
            .build()

        val request = OneTimeWorkRequestBuilder<FlacifySyncWorker>()
            .setConstraints(constraints)
            .setExpedited(OutOfQuotaPolicy.RUN_AS_NON_EXPEDITED_WORK_REQUEST)
            .setInputData(
                workDataOf(FlacifySyncWorker.KEY_SYNC_ALL_LIBRARY to syncAllLibrary)
            )
            .build()

        workManager.enqueueUniqueWork(
            FlacifySyncWorker.UNIQUE_WORK_NAME,
            ExistingWorkPolicy.KEEP,
            request,
        )
    }

    fun cancelSync() {
        workManager.cancelUniqueWork(FlacifySyncWorker.UNIQUE_WORK_NAME)
    }

    private fun mapWorkInfos(infos: List<WorkInfo>): SyncProgressState {
        val info = infos.firstOrNull() ?: return SyncProgressState()
        val data = if (info.state == WorkInfo.State.RUNNING) info.progress else info.outputData

        val completed = data.getInt(FlacifySyncWorker.KEY_COMPLETED_TRACKS, 0)
        val total = data.getInt(FlacifySyncWorker.KEY_TOTAL_TRACKS, 0)
        val bytesDone = data.getLong(FlacifySyncWorker.KEY_BYTES_DONE, 0L)
        val totalBytes = data.getLong(FlacifySyncWorker.KEY_TOTAL_BYTES, 0L)
        val speedBytesPerSec = data.getLong(FlacifySyncWorker.KEY_SPEED_BYTES_PER_SEC, 0L)
        val transport = data.getString(FlacifySyncWorker.KEY_TRANSPORT).orEmpty()
        val currentTitle = data.getString(FlacifySyncWorker.KEY_CURRENT_TITLE).orEmpty()
        val errorCount = data.getInt(FlacifySyncWorker.KEY_ERROR_COUNT, 0)
        val failError = data.getString(FlacifySyncWorker.KEY_ERROR)

        return when (info.state) {
            WorkInfo.State.ENQUEUED,
            WorkInfo.State.BLOCKED,
            WorkInfo.State.RUNNING -> SyncProgressState(
                isRunning = true,
                currentTitle = if (info.state == WorkInfo.State.ENQUEUED) {
                    "Preparing sync..."
                } else {
                    currentTitle
                },
                completedTracks = completed,
                totalTracks = total,
                bytesDone = bytesDone,
                totalBytes = totalBytes,
                speedBytesPerSec = speedBytesPerSec,
                transport = transport,
            )

            WorkInfo.State.SUCCEEDED -> {
                val msg = if (total == 0) {
                    "All enabled playlists are up to date."
                } else if (errorCount > 0) {
                    "Synced ${total - errorCount} / $total tracks ($errorCount skipped)."
                } else {
                    "Synced $total lossless tracks for offline playback."
                }
                SyncProgressState(
                    isRunning = false,
                    completedTracks = completed,
                    totalTracks = total,
                    bytesDone = bytesDone,
                    totalBytes = totalBytes,
                    speedBytesPerSec = speedBytesPerSec,
                    transport = transport,
                    errorCount = errorCount,
                    terminalMessage = msg,
                )
            }

            WorkInfo.State.FAILED -> SyncProgressState(
                isRunning = false,
                errorMessage = failError ?: "Sync failed.",
            )

            WorkInfo.State.CANCELLED -> SyncProgressState(
                isRunning = false,
                terminalMessage = "Sync paused. Next sync will resume from where you left off.",
            )
        }
    }
}
