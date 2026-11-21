package com.flacify.android

import com.flacify.android.share.ShareUrlExtractor
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Test

class ShareUrlExtractorTest {

    @Test
    fun extractsRegionalSpotifyUrlsShortLinksUrisAndYoutubeUrls() {
        val regional = ShareUrlExtractor.extract(
            "Listen to this! https://open.spotify.com/intl-es/track/58ge6dfP91o9oXMzq3XkIS?si=abc123!"
        )
        assertNotNull(regional)
        assertEquals(
            "https://open.spotify.com/intl-es/track/58ge6dfP91o9oXMzq3XkIS?si=abc123",
            regional?.url,
        )
        assertEquals("Spotify Track", regional?.displayKind)

        val shortLink = ShareUrlExtractor.extract("https://spotify.link/abcXYZ123")
        assertNotNull(shortLink)
        assertEquals("Spotify Short Link", shortLink?.displayKind)

        val playlist = ShareUrlExtractor.extract("https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M.")
        assertEquals("Spotify Playlist", playlist?.displayKind)
        assertEquals("https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M", playlist?.url)

        val uri = ShareUrlExtractor.extract("Play spotify:album:1ATL5GLyefJaxhQzSPVrLX, thanks")
        assertNotNull(uri)
        assertEquals("spotify:album:1ATL5GLyefJaxhQzSPVrLX", uri?.url)
        assertEquals("Spotify Album", uri?.displayKind)

        val yt = ShareUrlExtractor.extract("https://music.youtube.com/watch?v=dQw4w9WgXcQ")
        assertNotNull(yt)
        assertEquals("YouTube / Audio Link", yt?.displayKind)
    }

    @Test
    fun returnsNullForPlainTextWithoutLinks() {
        assertNull(ShareUrlExtractor.extract("Just chatting without links"))
        assertNull(ShareUrlExtractor.extract("   "))
        assertNull(ShareUrlExtractor.extract(null))
    }
}
