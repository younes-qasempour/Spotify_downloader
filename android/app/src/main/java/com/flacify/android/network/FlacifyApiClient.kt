package com.flacify.android.network

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import okhttp3.ConnectionPool
import okhttp3.Dispatcher
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.IOException
import java.net.URLEncoder
import java.nio.charset.StandardCharsets
import java.util.concurrent.TimeUnit

sealed class FlacifyApiException(
    message: String,
    cause: Throwable? = null,
) : Exception(message, cause) {
    class Unauthorized(detail: String) : FlacifyApiException(
        detail.ifBlank { "Invalid or expired pairing token (HTTP 401)." }
    )

    class LanDisabled(detail: String) : FlacifyApiException(
        detail.ifBlank { "LAN / mobile access is disabled on your Flacify PC (HTTP 403)." }
    )

    class HttpError(val code: Int, detail: String) : FlacifyApiException(
        detail.ifBlank { "PC backend returned HTTP $code." }
    )

    class Unreachable(message: String, cause: Throwable? = null) : FlacifyApiException(message, cause)
}

data class ApiCallResult<T>(
    val data: T,
    val resolvedBaseUrl: String,
)

class FlacifyApiClient(
    baseClient: OkHttpClient = defaultOkHttpClient(),
) {
    private val shortClient: OkHttpClient = baseClient.newBuilder()
        .connectTimeout(4, TimeUnit.SECONDS)
        .readTimeout(12, TimeUnit.SECONDS)
        .writeTimeout(12, TimeUnit.SECONDS)
        .build()

    private val usbShortClient: OkHttpClient = baseClient.newBuilder()
        .connectTimeout(1500, TimeUnit.MILLISECONDS)
        .readTimeout(12, TimeUnit.SECONDS)
        .writeTimeout(12, TimeUnit.SECONDS)
        .build()

    private val manifestClient: OkHttpClient = baseClient.newBuilder()
        .connectTimeout(4, TimeUnit.SECONDS)
        .readTimeout(45, TimeUnit.SECONDS)
        .build()

    private val usbManifestClient: OkHttpClient = baseClient.newBuilder()
        .connectTimeout(1500, TimeUnit.MILLISECONDS)
        .readTimeout(45, TimeUnit.SECONDS)
        .build()

    val rawHttpClient: OkHttpClient = baseClient.newBuilder()
        .connectTimeout(4, TimeUnit.SECONDS)
        .readTimeout(60, TimeUnit.SECONDS)
        .writeTimeout(15, TimeUnit.SECONDS)
        .build()

    private val json = Json {
        ignoreUnknownKeys = true
        coerceInputValues = true
    }

    suspend fun fetchHealth(candidateUrls: List<String>): ApiCallResult<HealthResponse> =
        executeWithFailover(
            client = shortClient,
            usbClient = usbShortClient,
            candidateUrls = candidateUrls,
            token = null,
            path = "/api/health",
        ) { bodyText ->
            json.decodeFromString<HealthResponse>(bodyText)
        }

    suspend fun fetchSyncInfo(
        candidateUrls: List<String>,
        token: String,
    ): ApiCallResult<SyncInfoResponse> =
        executeWithFailover(
            client = shortClient,
            usbClient = usbShortClient,
            candidateUrls = candidateUrls,
            token = token,
            path = "/api/sync/info",
        ) { bodyText ->
            json.decodeFromString<SyncInfoResponse>(bodyText)
        }

    suspend fun fetchManifest(
        candidateUrls: List<String>,
        token: String,
        playlistId: String? = null,
        includeTracks: Boolean = true,
    ): ApiCallResult<SyncManifestResponse> {
        val query = buildString {
            append("include_tracks=")
            append(includeTracks)
            if (!playlistId.isNullOrBlank()) {
                append("&playlist_id=")
                append(URLEncoder.encode(playlistId, StandardCharsets.UTF_8.name()))
            }
        }
        return executeWithFailover(
            client = manifestClient,
            usbClient = usbManifestClient,
            candidateUrls = candidateUrls,
            token = token,
            path = "/api/sync/manifest?$query",
        ) { bodyText ->
            json.decodeFromString<SyncManifestResponse>(bodyText)
        }
    }

    suspend fun shareUrl(
        candidateUrls: List<String>,
        token: String,
        sharedText: String,
        autoDownload: Boolean = true,
    ): ApiCallResult<ShareResponse> {
        val payloadJson = json.encodeToString(
            ShareRequest(
                url = sharedText,
                autoDownload = autoDownload,
            )
        )
        return executeWithFailover(
            client = shortClient,
            usbClient = usbShortClient,
            candidateUrls = candidateUrls,
            token = token,
            path = "/api/sync/share",
            method = "POST",
            jsonBody = payloadJson,
        ) { bodyText ->
            json.decodeFromString<ShareResponse>(bodyText)
        }
    }

    suspend fun fetchLyrics(
        candidateUrls: List<String>,
        token: String,
        trackId: String,
    ): ApiCallResult<LyricsResponse> {
        val encodedId = URLEncoder.encode(trackId, StandardCharsets.UTF_8.name())
            .replace("+", "%20")
        return executeWithFailover(
            client = shortClient,
            usbClient = usbShortClient,
            candidateUrls = candidateUrls,
            token = token,
            path = "/api/lyrics/$encodedId",
        ) { bodyText ->
            json.decodeFromString<LyricsResponse>(bodyText)
        }
    }

    suspend fun downloadBytesOrNull(
        candidateUrls: List<String>,
        token: String,
        relativePath: String,
    ): ByteArray? = withContext(Dispatchers.IO) {
        val cleanPath = if (relativePath.startsWith("/")) relativePath else "/$relativePath"
        val normalized = candidateUrls.mapNotNull { PairingUriParser.normalizeBaseUrl(it) }.distinct()
        if (normalized.isEmpty()) return@withContext null

        for (baseUrl in normalized) {
            val activeClient = if (PairingUriParser.isUsbLoopbackUrl(baseUrl)) usbShortClient else shortClient
            val req = Request.Builder()
                .url("$baseUrl$cleanPath")
                .header("Authorization", "Bearer ${token.trim()}")
                .get()
                .build()
            try {
                activeClient.newCall(req).execute().use { resp ->
                    when {
                        resp.code == 401 -> throw FlacifyApiException.Unauthorized(
                            extractErrorDetail(resp.body?.string().orEmpty())
                        )
                        resp.code == 403 -> throw FlacifyApiException.LanDisabled(
                            extractErrorDetail(resp.body?.string().orEmpty())
                        )
                        resp.code == 404 -> return@withContext null
                        !resp.isSuccessful -> return@withContext null
                        else -> {
                            val bytes = resp.body?.bytes()
                            return@withContext if (bytes != null && bytes.isNotEmpty()) bytes else null
                        }
                    }
                }
            } catch (apiEx: FlacifyApiException) {
                throw apiEx
            } catch (_: IOException) {
                // Fail over to next URL on unreachable host
            }
        }
        null
    }

    private suspend fun <T> executeWithFailover(
        client: OkHttpClient,
        usbClient: OkHttpClient? = null,
        candidateUrls: List<String>,
        token: String?,
        path: String,
        method: String = "GET",
        jsonBody: String? = null,
        decode: (String) -> T,
    ): ApiCallResult<T> = withContext(Dispatchers.IO) {
        val normalized = candidateUrls.mapNotNull { PairingUriParser.normalizeBaseUrl(it) }.distinct()
        if (normalized.isEmpty()) {
            throw FlacifyApiException.Unreachable("No valid PC server address configured.")
        }

        var lastNetworkError: IOException? = null
        var lastUrlTried = normalized.first()

        for (baseUrl in normalized) {
            lastUrlTried = baseUrl
            val activeClient = if (usbClient != null && PairingUriParser.isUsbLoopbackUrl(baseUrl)) {
                usbClient
            } else {
                client
            }
            val requestBuilder = Request.Builder().url("$baseUrl$path")
            if (!token.isNullOrBlank()) {
                requestBuilder.header("Authorization", "Bearer ${token.trim()}")
            }
            if (method == "POST") {
                val body = (jsonBody ?: "{}").toRequestBody(JSON_MEDIA_TYPE)
                requestBuilder.post(body)
            } else {
                requestBuilder.get()
            }

            try {
                activeClient.newCall(requestBuilder.build()).execute().use { response ->
                    val rawBody = response.body?.string().orEmpty()
                    if (!response.isSuccessful) {
                        val detail = extractErrorDetail(rawBody)
                        when (response.code) {
                            401 -> throw FlacifyApiException.Unauthorized(detail)
                            403 -> throw FlacifyApiException.LanDisabled(detail)
                            else -> throw FlacifyApiException.HttpError(response.code, detail)
                        }
                    }
                    return@withContext ApiCallResult(
                        data = decode(rawBody),
                        resolvedBaseUrl = baseUrl,
                    )
                }
            } catch (apiEx: FlacifyApiException) {
                throw apiEx
            } catch (ioEx: IOException) {
                lastNetworkError = ioEx
            }
        }

        val reason = lastNetworkError?.message ?: "Connection failed"
        throw FlacifyApiException.Unreachable(
            message = "Could not reach Flacify PC (last tried $lastUrlTried: $reason)",
            cause = lastNetworkError,
        )
    }

    private fun extractErrorDetail(rawBody: String): String {
        if (rawBody.isBlank()) return ""
        return try {
            json.decodeFromString<FastApiErrorResponse>(rawBody).detail
        } catch (_: Exception) {
            rawBody.take(240)
        }
    }

    companion object {
        private val JSON_MEDIA_TYPE = "application/json; charset=utf-8".toMediaType()

        fun defaultOkHttpClient(): OkHttpClient {
            val dispatcher = Dispatcher().apply {
                maxRequests = 32
                maxRequestsPerHost = 8
            }
            return OkHttpClient.Builder()
                .dispatcher(dispatcher)
                .connectionPool(ConnectionPool(8, 2, TimeUnit.MINUTES))
                .retryOnConnectionFailure(true)
                .build()
        }
    }
}
