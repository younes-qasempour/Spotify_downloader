package com.flacify.android.sync

import com.flacify.android.network.FlacifyApiException
import com.flacify.android.network.PairingUriParser
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.withContext
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import java.io.File
import java.io.FileOutputStream
import java.io.IOException
import java.io.InputStream
import java.io.RandomAccessFile
import java.nio.charset.StandardCharsets

data class DownloadedFileResult(
    val file: File,
    val bytesWrittenTotal: Long,
    val etag: String?,
    val resumedFromBytes: Long,
)

class ResumableFileDownloader(
    private val httpClient: OkHttpClient,
) {
    private val json = Json { ignoreUnknownKeys = true }

    @Serializable
    private data class ErrorBody(val detail: String = "")

    suspend fun downloadTrackFile(
        candidateUrls: List<String>,
        token: String,
        relativeFileUrl: String,
        destFile: File,
        expectedSize: Long = -1L,
        onProgress: (bytesDone: Long, totalBytes: Long) -> Unit = { _, _ -> },
    ): DownloadedFileResult = withContext(Dispatchers.IO) {
        val normalizedUrls = candidateUrls.mapNotNull { PairingUriParser.normalizeBaseUrl(it) }.distinct()
        if (normalizedUrls.isEmpty()) {
            throw FlacifyApiException.Unreachable("No valid PC server URL configured.")
        }

        val cleanPath = if (relativeFileUrl.startsWith("/")) relativeFileUrl else "/$relativeFileUrl"
        val parent = destFile.parentFile
        if (parent != null && !parent.exists()) {
            parent.mkdirs()
        }

        val partFile = File(parent ?: File("."), "${destFile.name}.part")
        val etagFile = File(parent ?: File("."), "${destFile.name}.part.etag")

        // Validate any pre-existing partial transfer before attempting resume.
        val existingLen = if (partFile.isFile) partFile.length() else 0L
        val existingEtag = if (etagFile.isFile) {
            runCatching { etagFile.readText(StandardCharsets.UTF_8).trim().ifBlank { null } }.getOrNull()
        } else {
            null
        }
        if (existingLen > 0L && (existingEtag.isNullOrBlank() || (expectedSize > 0L && existingLen >= expectedSize))) {
            runCatching { partFile.delete() }
            runCatching { etagFile.delete() }
        }

        var lastNetworkError: IOException? = null
        var lastUrlTried = normalizedUrls.first()

        for (baseUrl in normalizedUrls) {
            lastUrlTried = baseUrl
            var retriedAfter416 = false

            while (true) {
                currentCoroutineContext().ensureActive()

                val resumeOffset = if (partFile.isFile) partFile.length() else 0L
                val savedEtag = if (etagFile.isFile) {
                    runCatching { etagFile.readText(StandardCharsets.UTF_8).trim().ifBlank { null } }.getOrNull()
                } else {
                    null
                }
                val attemptResume = resumeOffset > 0L &&
                    !savedEtag.isNullOrBlank() &&
                    (expectedSize <= 0L || resumeOffset < expectedSize)

                val reqBuilder = Request.Builder()
                    .url("$baseUrl$cleanPath")
                    .header("Authorization", "Bearer ${token.trim()}")
                    .header("Accept-Encoding", "identity")
                    .get()

                if (attemptResume) {
                    reqBuilder.header("Range", "bytes=$resumeOffset-")
                    reqBuilder.header("If-Range", savedEtag!!)
                }

                try {
                    httpClient.newCall(reqBuilder.build()).execute().use { response ->
                        when (response.code) {
                            401 -> throw FlacifyApiException.Unauthorized(extractDetail(response))
                            403 -> throw FlacifyApiException.LanDisabled(extractDetail(response))
                            404 -> throw FlacifyApiException.HttpError(404, extractDetail(response))
                            416 -> {
                                runCatching { partFile.delete() }
                                runCatching { etagFile.delete() }
                                if (!retriedAfter416 && attemptResume) {
                                    retriedAfter416 = true
                                    continue
                                }
                                throw FlacifyApiException.HttpError(
                                    416,
                                    "Server rejected byte range for ${destFile.name}.",
                                )
                            }
                        }

                        if (!response.isSuccessful) {
                            throw FlacifyApiException.HttpError(response.code, extractDetail(response))
                        }

                        val body = response.body
                            ?: throw IOException("Empty response body from $baseUrl$cleanPath")
                        val responseEtag = response.header("ETag")
                            ?.trim()
                            ?.takeIf { it.isNotEmpty() }
                            ?: if (response.code == 206) savedEtag else null

                        if (responseEtag != null) {
                            etagFile.writeText(responseEtag, StandardCharsets.UTF_8)
                        } else {
                            runCatching { etagFile.delete() }
                        }

                        val contentLen = body.contentLength()
                        val isPartialAppend = response.code == 206 && attemptResume
                        val startOffset = if (isPartialAppend) resumeOffset else 0L
                        val expectedCompleteBytes = when {
                            contentLen > 0L -> startOffset + contentLen
                            expectedSize > 0L -> expectedSize
                            else -> -1L
                        }

                        onProgress(startOffset, expectedCompleteBytes)

                        body.byteStream().use { input ->
                            if (isPartialAppend) {
                                appendFromOffset(input, partFile, startOffset, expectedCompleteBytes, onProgress)
                            } else {
                                writeFresh(input, partFile, expectedCompleteBytes, onProgress)
                            }
                        }

                        val actualPartSize = partFile.length()
                        if (expectedCompleteBytes > 0L && actualPartSize < expectedCompleteBytes) {
                            throw IOException(
                                "Incomplete transfer for ${destFile.name}: got $actualPartSize of $expectedCompleteBytes bytes."
                            )
                        }

                        if (destFile.exists() && !destFile.delete()) {
                            throw IOException("Could not replace existing file ${destFile.absolutePath}")
                        }
                        if (!partFile.renameTo(destFile)) {
                            partFile.copyTo(destFile, overwrite = true)
                            runCatching { partFile.delete() }
                        }
                        runCatching { etagFile.delete() }

                        return@withContext DownloadedFileResult(
                            file = destFile,
                            bytesWrittenTotal = destFile.length(),
                            etag = responseEtag,
                            resumedFromBytes = startOffset,
                        )
                    }
                } catch (apiEx: FlacifyApiException) {
                    throw apiEx
                } catch (ioEx: IOException) {
                    lastNetworkError = ioEx
                    break
                }
            }
        }

        val reason = lastNetworkError?.message ?: "Connection failed"
        throw FlacifyApiException.Unreachable(
            message = "Could not download track from $lastUrlTried: $reason",
            cause = lastNetworkError,
        )
    }

    private suspend fun writeFresh(
        input: InputStream,
        partFile: File,
        totalBytes: Long,
        onProgress: (Long, Long) -> Unit,
    ) {
        FileOutputStream(partFile, false).use { out ->
            val buffer = ByteArray(DEFAULT_CHUNK_SIZE)
            var written = 0L
            while (true) {
                currentCoroutineContext().ensureActive()
                val read = input.read(buffer)
                if (read < 0) break
                if (read > 0) {
                    out.write(buffer, 0, read)
                    written += read
                    onProgress(written, totalBytes)
                }
            }
            out.flush()
        }
    }

    private suspend fun appendFromOffset(
        input: InputStream,
        partFile: File,
        offset: Long,
        totalBytes: Long,
        onProgress: (Long, Long) -> Unit,
    ) {
        RandomAccessFile(partFile, "rw").use { raf ->
            raf.setLength(offset)
            raf.seek(offset)
            val buffer = ByteArray(DEFAULT_CHUNK_SIZE)
            var written = offset
            while (true) {
                currentCoroutineContext().ensureActive()
                val read = input.read(buffer)
                if (read < 0) break
                if (read > 0) {
                    raf.write(buffer, 0, read)
                    written += read
                    onProgress(written, totalBytes)
                }
            }
        }
    }

    private fun extractDetail(response: Response): String {
        val raw = runCatching { response.body?.string().orEmpty() }.getOrDefault("")
        if (raw.isBlank()) return ""
        return try {
            json.decodeFromString<ErrorBody>(raw).detail
        } catch (_: Exception) {
            raw.take(240)
        }
    }

    private companion object {
        const val DEFAULT_CHUNK_SIZE = 64 * 1024
    }
}
