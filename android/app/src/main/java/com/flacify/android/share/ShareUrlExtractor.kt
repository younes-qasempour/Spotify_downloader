package com.flacify.android.share

import java.net.URI
import java.util.Locale

data class ExtractedShare(
    val url: String,
    val displayKind: String,
)

object ShareUrlExtractor {
    private val HTTP_URL_REGEX = Regex("""https?://[^\s<>\"']+""")
    private val SPOTIFY_URI_REGEX = Regex(
        """spotify:(?:user:[^:\s]+:)?(?:track|album|playlist|artist|collection)(?::[a-zA-Z0-9]+)?""",
        RegexOption.IGNORE_CASE,
    )
    private val TRAILING_PUNCT_CHARS = charArrayOf('.', ',', ';', '!', '>', '"', '\'', ')')

    fun extract(rawText: String?): ExtractedShare? {
        val text = rawText?.trim().orEmpty()
        if (text.isEmpty()) return null

        val httpMatch = HTTP_URL_REGEX.find(text)?.value?.trimEnd(*TRAILING_PUNCT_CHARS)
        if (!httpMatch.isNullOrBlank()) {
            return ExtractedShare(
                url = httpMatch,
                displayKind = classifyUrl(httpMatch),
            )
        }

        val uriMatch = SPOTIFY_URI_REGEX.find(text)?.value?.trimEnd(*TRAILING_PUNCT_CHARS)
        if (!uriMatch.isNullOrBlank()) {
            return ExtractedShare(
                url = uriMatch,
                displayKind = classifySpotifyUri(uriMatch),
            )
        }

        return null
    }

    private fun classifyUrl(url: String): String {
        val parsed = runCatching { URI(url) }.getOrNull()
        val host = parsed?.host?.lowercase(Locale.ROOT).orEmpty()
        val path = parsed?.path?.lowercase(Locale.ROOT).orEmpty()

        return when {
            host in SHORT_LINK_HOSTS -> "Spotify Short Link"
            host.endsWith("spotify.com") -> when {
                path.contains("/track/") -> "Spotify Track"
                path.contains("/playlist/") -> "Spotify Playlist"
                path.contains("/album/") -> "Spotify Album"
                path.contains("/artist/") -> "Spotify Artist"
                path.contains("/collection") -> "Spotify Liked Songs"
                else -> "Spotify Link"
            }
            host.endsWith("youtube.com") || host == "youtu.be" -> "YouTube / Audio Link"
            else -> "Audio Link"
        }
    }

    private fun classifySpotifyUri(uri: String): String {
        val lower = uri.lowercase(Locale.ROOT)
        return when {
            lower.contains(":track:") -> "Spotify Track"
            lower.contains(":playlist:") -> "Spotify Playlist"
            lower.contains(":album:") -> "Spotify Album"
            lower.contains(":artist:") -> "Spotify Artist"
            lower.contains(":collection") -> "Spotify Liked Songs"
            else -> "Spotify Link"
        }
    }

    private val SHORT_LINK_HOSTS = setOf("spotify.link", "spotify.app.link", "spoti.fi")
}
