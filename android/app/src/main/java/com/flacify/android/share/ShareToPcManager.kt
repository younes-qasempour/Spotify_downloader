package com.flacify.android.share

import android.content.Context
import androidx.work.BackoffPolicy
import androidx.work.Constraints
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import com.flacify.android.data.ConnectionSettingsStore
import com.flacify.android.data.db.FlacifyDao
import com.flacify.android.data.db.PendingShareEntity
import com.flacify.android.data.db.PendingShareStatus
import com.flacify.android.network.FlacifyApiClient
import com.flacify.android.network.FlacifyApiException
import com.flacify.android.network.ShareResponse
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import java.util.concurrent.TimeUnit

sealed class ShareSubmissionResult {
    data object InvalidUrl : ShareSubmissionResult()
    data class NotPaired(val extracted: ExtractedShare) : ShareSubmissionResult()
    data class SentNow(val extracted: ExtractedShare, val response: ShareResponse) : ShareSubmissionResult()
    data class QueuedOffline(val extracted: ExtractedShare, val reason: String) : ShareSubmissionResult()
    data class Failed(val extracted: ExtractedShare, val message: String) : ShareSubmissionResult()
}

class ShareToPcManager(
    context: Context,
    private val dao: FlacifyDao,
    private val connectionStore: ConnectionSettingsStore,
    private val apiClient: FlacifyApiClient,
) {
    private val workManager = WorkManager.getInstance(context.applicationContext)

    fun observePendingShares(): Flow<List<PendingShareEntity>> = dao.observePendingShares()

    suspend fun sendOrQueue(
        rawText: String,
        autoDownload: Boolean = true,
    ): ShareSubmissionResult {
        val extracted = ShareUrlExtractor.extract(rawText) ?: return ShareSubmissionResult.InvalidUrl
        val cfg = connectionStore.configFlow.first()
        if (!cfg.isPaired) {
            return ShareSubmissionResult.NotPaired(extracted)
        }

        val now = System.currentTimeMillis()
        return try {
            val res = apiClient.shareUrl(
                candidateUrls = cfg.orderedCandidateUrls(),
                token = cfg.pairToken,
                sharedText = extracted.url,
                autoDownload = autoDownload,
            )
            if (res.resolvedBaseUrl != cfg.activeUrl) {
                connectionStore.updateActiveUrl(res.resolvedBaseUrl)
            }
            dao.insertPendingShare(
                PendingShareEntity(
                    rawUrl = extracted.url,
                    displayKind = extracted.displayKind,
                    autoDownload = autoDownload,
                    status = PendingShareStatus.SENT,
                    queuedCount = res.data.queuedCount,
                    lastError = null,
                    createdAt = now,
                    updatedAt = now,
                )
            )
            ShareSubmissionResult.SentNow(extracted, res.data)
        } catch (ex: FlacifyApiException.Unreachable) {
            val reason = "PC unreachable right now — saved to retry automatically when back on Wi-Fi / Tailscale."
            dao.insertPendingShare(
                PendingShareEntity(
                    rawUrl = extracted.url,
                    displayKind = extracted.displayKind,
                    autoDownload = autoDownload,
                    status = PendingShareStatus.PENDING,
                    queuedCount = 0,
                    lastError = "Waiting for Wi-Fi / Tailscale",
                    createdAt = now,
                    updatedAt = now,
                )
            )
            enqueueRetryWorker()
            ShareSubmissionResult.QueuedOffline(extracted, reason)
        } catch (ex: FlacifyApiException) {
            val msg = ex.message ?: "Rejected by Flacify PC."
            dao.insertPendingShare(
                PendingShareEntity(
                    rawUrl = extracted.url,
                    displayKind = extracted.displayKind,
                    autoDownload = autoDownload,
                    status = PendingShareStatus.FAILED,
                    queuedCount = 0,
                    lastError = msg,
                    createdAt = now,
                    updatedAt = now,
                )
            )
            ShareSubmissionResult.Failed(extracted, msg)
        } catch (ex: Exception) {
            val reason = "PC connection interrupted — saved to retry automatically."
            dao.insertPendingShare(
                PendingShareEntity(
                    rawUrl = extracted.url,
                    displayKind = extracted.displayKind,
                    autoDownload = autoDownload,
                    status = PendingShareStatus.PENDING,
                    queuedCount = 0,
                    lastError = ex.message ?: "Interrupted",
                    createdAt = now,
                    updatedAt = now,
                )
            )
            enqueueRetryWorker()
            ShareSubmissionResult.QueuedOffline(extracted, reason)
        }
    }

    fun enqueueRetryWorker() {
        val constraints = Constraints.Builder()
            .setRequiredNetworkType(NetworkType.CONNECTED)
            .build()
        val req = OneTimeWorkRequestBuilder<PendingShareWorker>()
            .setConstraints(constraints)
            .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 15, TimeUnit.SECONDS)
            .build()
        workManager.enqueueUniqueWork(
            PendingShareWorker.UNIQUE_WORK_NAME,
            ExistingWorkPolicy.REPLACE,
            req,
        )
    }

    suspend fun flushPendingSharesNow() {
        dao.resetFailedSharesToPending(System.currentTimeMillis())
        val hasPending = dao.getUnsentShares().isNotEmpty()
        if (hasPending) {
            enqueueRetryWorker()
        }
    }

    suspend fun deleteShare(id: Long) {
        dao.deletePendingShare(id)
    }

    suspend fun clearSentShares() {
        dao.clearSentShares()
    }
}
