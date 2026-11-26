package com.flacify.android.network

import java.net.URI
import java.net.URLDecoder
import java.nio.charset.StandardCharsets

data class PairingPayload(
    val host: String,
    val port: Int,
    val token: String,
    val deviceName: String,
    val candidateUrls: List<String>,
)

object PairingUriParser {
    const val DEFAULT_PORT = 8765
    const val USB_LOOPBACK_HOST = "127.0.0.1"

    fun usbLoopbackUrl(port: Int = DEFAULT_PORT): String {
        val validPort = if (port in 1..65535) port else DEFAULT_PORT
        return "http://$USB_LOOPBACK_HOST:$validPort"
    }

    fun isUsbLoopbackUrl(rawUrl: String): Boolean {
        val normalized = normalizeBaseUrl(rawUrl) ?: return false
        val uri = try {
            URI(normalized)
        } catch (_: Exception) {
            return false
        }
        val host = uri.host
            ?.lowercase()
            ?.removePrefix("[")
            ?.removeSuffix("]")
            ?: return false
        return host == "127.0.0.1" || host == "localhost" || host == "::1"
    }

    fun extractPort(rawUrl: String): Int? {
        val normalized = normalizeBaseUrl(rawUrl) ?: return null
        val uri = try {
            URI(normalized)
        } catch (_: Exception) {
            return null
        }
        return uri.port.takeIf { it in 1..65535 }
    }

    fun buildOrderedCandidates(
        activeUrl: String,
        candidateUrls: List<String>,
        preferUsb: Boolean,
    ): List<String> {
        val saved = mergeCandidateUrls(activeUrl, candidateUrls)
        if (!preferUsb) return saved
        val port = extractPort(activeUrl)
            ?: candidateUrls.firstNotNullOfOrNull { extractPort(it) }
            ?: DEFAULT_PORT
        return (listOf(usbLoopbackUrl(port)) + saved).distinct()
    }

    fun parse(rawUri: String): PairingPayload? {
        val trimmed = rawUri.trim()
        if (trimmed.isEmpty()) return null

        val uri = try {
            URI(trimmed)
        } catch (_: Exception) {
            return null
        }

        if (!uri.scheme.equals("flacify", ignoreCase = true)) return null
        if (!uri.host.equals("pair", ignoreCase = true)) return null

        val params = parseQueryParams(uri.rawQuery)
        val token = params["token"].orEmpty().trim()
        if (token.isEmpty()) return null

        val host = params["host"].orEmpty().trim()
        val rawPort = params["port"].orEmpty().trim()
        val port = if (rawPort.isEmpty()) {
            DEFAULT_PORT
        } else {
            val parsedPort = rawPort.toIntOrNull() ?: return null
            if (parsedPort !in 1..65535) return null
            parsedPort
        }

        val deviceName = params["name"].orEmpty().trim()
        val explicitUrls = params["urls"]
            .orEmpty()
            .split(',')
            .mapNotNull { normalizeBaseUrl(it) }

        val hostUrl = if (host.isNotEmpty()) {
            val formattedHost = if (host.contains(':') && !host.startsWith("[")) "[$host]" else host
            normalizeBaseUrl("http://$formattedHost:$port")
        } else {
            null
        }

        val merged = buildList {
            if (hostUrl != null) add(hostUrl)
            addAll(explicitUrls)
        }.distinct()

        if (merged.isEmpty()) return null

        return PairingPayload(
            host = host,
            port = port,
            token = token,
            deviceName = deviceName,
            candidateUrls = merged,
        )
    }

    fun normalizeBaseUrl(rawUrl: String): String? {
        val trimmed = rawUrl.trim()
        if (trimmed.isEmpty()) return null

        val withScheme = if (trimmed.contains("://")) {
            trimmed
        } else {
            "http://$trimmed"
        }

        val uri = try {
            URI(withScheme)
        } catch (_: Exception) {
            return null
        }

        val scheme = uri.scheme?.lowercase() ?: return null
        if (scheme != "http" && scheme != "https") return null

        val host = uri.host ?: return null
        if (host.isBlank()) return null

        val formattedHost = if (host.contains(':') && !host.startsWith("[")) "[$host]" else host
        val port = uri.port
        if (port != -1 && port !in 1..65535) return null

        return buildString {
            append(scheme)
            append("://")
            append(formattedHost)
            if (port != -1) {
                append(':')
                append(port)
            }
        }
    }

    fun mergeCandidateUrls(primary: String, extras: List<String>): List<String> =
        buildList {
            normalizeBaseUrl(primary)?.let(::add)
            extras.mapNotNull(::normalizeBaseUrl).forEach(::add)
        }.distinct()

    private fun parseQueryParams(rawQuery: String?): Map<String, String> {
        if (rawQuery.isNullOrBlank()) return emptyMap()
        val result = linkedMapOf<String, String>()
        for (pair in rawQuery.split('&')) {
            if (pair.isBlank()) continue
            val idx = pair.indexOf('=')
            val rawKey = if (idx >= 0) pair.substring(0, idx) else pair
            val rawVal = if (idx >= 0) pair.substring(idx + 1) else ""
            val key = urlDecode(rawKey)
            val value = urlDecode(rawVal)
            if (key.isNotEmpty()) {
                result[key] = value
            }
        }
        return result
    }

    private fun urlDecode(value: String): String =
        try {
            URLDecoder.decode(value, StandardCharsets.UTF_8.name())
        } catch (_: Exception) {
            value
        }
}
