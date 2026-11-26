package com.flacify.android

import com.flacify.android.network.PairingUriParser
import com.flacify.android.ui.library.FormatUtils
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class PairingUriParserTest {
    @Test
    fun parsesFullPairingUriWithMultipleCandidateUrls() {
        val uri =
            "flacify://pair?host=192.168.1.50&port=8765&token=secret_tok_123&name=My%20Desktop%20PC&urls=http%3A%2F%2F192.168.1.50%3A8765%2Chttp%3A%2F%2F100.80.1.2%3A8765"
        val parsed = PairingUriParser.parse(uri)
        assertNotNull(parsed)
        requireNotNull(parsed)
        assertEquals("192.168.1.50", parsed.host)
        assertEquals(8765, parsed.port)
        assertEquals("secret_tok_123", parsed.token)
        assertEquals("My Desktop PC", parsed.deviceName)
        assertEquals(
            listOf("http://192.168.1.50:8765", "http://100.80.1.2:8765"),
            parsed.candidateUrls,
        )
    }

    @Test
    fun parsesMinimalUriWithDefaultPort() {
        val parsed = PairingUriParser.parse("  flacify://pair?host=10.0.2.2&token=abc999  ")
        assertNotNull(parsed)
        requireNotNull(parsed)
        assertEquals(8765, parsed.port)
        assertEquals(listOf("http://10.0.2.2:8765"), parsed.candidateUrls)
    }

    @Test
    fun rejectsInvalidSchemeMissingTokenOrBadPort() {
        assertNull(PairingUriParser.parse("https://pair?host=1.2.3.4&token=abc"))
        assertNull(PairingUriParser.parse("flacify://other?host=1.2.3.4&token=abc"))
        assertNull(PairingUriParser.parse("flacify://pair?host=1.2.3.4"))
        assertNull(PairingUriParser.parse("flacify://pair?host=1.2.3.4&port=99999&token=abc"))
        assertNull(PairingUriParser.parse("flacify://pair?token=abc"))
    }

    @Test
    fun normalizesAndDeduplicatesBaseUrls() {
        assertEquals(
            "http://10.0.2.2:8765",
            PairingUriParser.normalizeBaseUrl("  10.0.2.2:8765/  "),
        )
        assertEquals(
            "https://pc.tail.ts.net:8765",
            PairingUriParser.normalizeBaseUrl("https://pc.tail.ts.net:8765///"),
        )
        assertNull(PairingUriParser.normalizeBaseUrl("ftp://192.168.1.1:8765"))
        assertNull(PairingUriParser.normalizeBaseUrl("   "))

        assertEquals(
            listOf("http://10.0.2.2:8765", "http://192.168.1.10:8765"),
            PairingUriParser.mergeCandidateUrls(
                "10.0.2.2:8765",
                listOf("http://10.0.2.2:8765/", "192.168.1.10:8765"),
            ),
        )
    }

    @Test
    fun detectsUsbLoopbackAndOrdersCandidates() {
        assertTrue(PairingUriParser.isUsbLoopbackUrl("http://127.0.0.1:8765"))
        assertTrue(PairingUriParser.isUsbLoopbackUrl("http://localhost:9000/"))
        assertTrue(PairingUriParser.isUsbLoopbackUrl("http://[::1]:8765"))
        assertFalse(PairingUriParser.isUsbLoopbackUrl("http://192.168.1.50:8765"))
        assertFalse(PairingUriParser.isUsbLoopbackUrl("not a url"))

        assertEquals("http://127.0.0.1:8765", PairingUriParser.usbLoopbackUrl())
        assertEquals("http://127.0.0.1:9123", PairingUriParser.usbLoopbackUrl(9123))
        assertEquals("http://127.0.0.1:8765", PairingUriParser.usbLoopbackUrl(0))

        assertEquals(9123, PairingUriParser.extractPort("http://192.168.1.20:9123"))
        assertNull(PairingUriParser.extractPort("http://192.168.1.20"))

        assertEquals(
            listOf(
                "http://127.0.0.1:9123",
                "http://192.168.1.20:9123",
                "http://100.80.1.2:9123",
            ),
            PairingUriParser.buildOrderedCandidates(
                activeUrl = "http://192.168.1.20:9123",
                candidateUrls = listOf("http://127.0.0.1:9123", "http://100.80.1.2:9123"),
                preferUsb = true,
            ),
        )

        assertEquals(
            listOf("http://192.168.1.20:9123", "http://100.80.1.2:9123"),
            PairingUriParser.buildOrderedCandidates(
                activeUrl = "http://192.168.1.20:9123",
                candidateUrls = listOf("http://100.80.1.2:9123"),
                preferUsb = false,
            ),
        )

        assertEquals("", FormatUtils.formatSpeed(0L))
        assertEquals("512 KB/s", FormatUtils.formatSpeed(512L * 1024L))
        assertEquals("24.5 MB/s", FormatUtils.formatSpeed((24.5 * 1024.0 * 1024.0).toLong()))
    }
}
