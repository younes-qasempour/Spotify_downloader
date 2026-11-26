package com.flacify.android.share

import android.content.Context
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import com.flacify.android.FlacifyApplication
import com.flacify.android.data.db.PendingShareStatus
import com.flacify.android.network.FlacifyApiException
import com.flacify.android.network.PairingUriParser

class PendingShareWorker(
    appContext: Context,
    params: WorkerParameters,
) : CoroutineWorker(appContext, params) {

    override suspend fun doWork(): Result {
        val app = applicationContext as FlacifyApplication
        val dao = app.database.dao()
        val repo = app.repository
        val cfg = repo.currentConnection()
        if (!cfg.isPaired) {
            return Result.success()
        }

        val unsent = dao.getUnsentShares().filter { it.status == PendingShareStatus.PENDING }
        if (unsent.isEmpty()) {
            return Result.success()
        }

        val candidateUrls = cfg.orderedCandidateUrls()
        var needsRetry = false

        for (share in unsent) {
            if (isStopped) {
                needsRetry = true
                break
            }

            try {
                val res = app.apiClient.shareUrl(
                    candidateUrls = candidateUrls,
                    token = cfg.pairToken,
                    sharedText = share.rawUrl,
                    autoDownload = share.autoDownload,
                )
                if (res.resolvedBaseUrl != cfg.activeUrl &&
                    !PairingUriParser.isUsbLoopbackUrl(res.resolvedBaseUrl)
                ) {
                    app.connectionStore.updateActiveUrl(res.resolvedBaseUrl)
                }
                dao.updatePendingShareStatus(
                    id = share.id,
                    status = PendingShareStatus.SENT,
                    queuedCount = res.data.queuedCount,
                    lastError = null,
                    updatedAt = System.currentTimeMillis(),
                )
            } catch (ex: FlacifyApiException.Unreachable) {
                needsRetry = true
                dao.updatePendingShareStatus(
                    id = share.id,
                    status = PendingShareStatus.PENDING,
                    queuedCount = 0,
                    lastError = "PC offline — waiting for Wi-Fi / Tailscale",
                    updatedAt = System.currentTimeMillis(),
                )
            } catch (ex: FlacifyApiException) {
                dao.updatePendingShareStatus(
                    id = share.id,
                    status = PendingShareStatus.FAILED,
                    queuedCount = 0,
                    lastError = ex.message ?: "Rejected by PC",
                    updatedAt = System.currentTimeMillis(),
                )
            } catch (ex: Exception) {
                needsRetry = true
                dao.updatePendingShareStatus(
                    id = share.id,
                    status = PendingShareStatus.PENDING,
                    queuedCount = 0,
                    lastError = ex.message ?: "Network error",
                    updatedAt = System.currentTimeMillis(),
                )
            }
        }

        return if (needsRetry) Result.retry() else Result.success()
    }

    companion object {
        const val UNIQUE_WORK_NAME = "flacify_pending_shares"
    }
}
