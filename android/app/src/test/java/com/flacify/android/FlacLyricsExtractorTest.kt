package com.flacify.android

import com.flacify.android.player.FlacLyricsExtractor
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test
import java.io.ByteArrayOutputStream
import java.nio.charset.StandardCharsets

class FlacLyricsExtractorTest {

    private fun buildSyntheticFlac(comments: List<String>): ByteArray {
        val out = ByteArrayOutputStream()
        // "fLaC" magic
        out.write("fLaC".toByteArray(StandardCharsets.US_ASCII))

        // Block 0: STREAMINFO (type=0, not last, 34 bytes)
        out.write(0x00)
        out.write(0x00)
        out.write(0x00)
        out.write(34)
        out.write(ByteArray(34))

        // Build Vorbis Comment payload (little-endian sizes)
        val vorbis = ByteArrayOutputStream()
        val vendor = "Flacify".toByteArray(StandardCharsets.UTF_8)
        writeLeInt32(vorbis, vendor.size)
        vorbis.write(vendor)
        writeLeInt32(vorbis, comments.size)
        for (c in comments) {
            val utf = c.toByteArray(StandardCharsets.UTF_8)
            writeLeInt32(vorbis, utf.size)
            vorbis.write(utf)
        }
        val vBytes = vorbis.toByteArray()

        // Block 1: VORBIS_COMMENT (type=4, isLast=1 -> 0x84)
        out.write(0x84)
        out.write((vBytes.size ushr 16) and 0xFF)
        out.write((vBytes.size ushr 8) and 0xFF)
        out.write(vBytes.size and 0xFF)
        out.write(vBytes)

        return out.toByteArray()
    }

    private fun writeLeInt32(out: ByteArrayOutputStream, value: Int) {
        out.write(value and 0xFF)
        out.write((value ushr 8) and 0xFF)
        out.write((value ushr 16) and 0xFF)
        out.write((value ushr 24) and 0xFF)
    }

    @Test
    fun extractsUtf8SyncedAndGeneralLyricsFromVorbisComment() {
        val lrc = "[00:01.25] Hello Lossless\n[00:04.00] Line Two"
        val flac = buildSyntheticFlac(
            listOf(
                "TITLE=Test Track",
                "UNSYNCEDLYRICS=Plain fallback",
                "LYRICS=$lrc",
            )
        )
        assertEquals(lrc, FlacLyricsExtractor.extractFromBytes(flac))

        val syncedPreferred = buildSyntheticFlac(
            listOf(
                "UNSYNCEDLYRICS=Plain fallback",
                "SYNCEDLYRICS=[00:02.00] Synced beats plain",
            )
        )
        assertEquals(
            "[00:02.00] Synced beats plain",
            FlacLyricsExtractor.extractFromBytes(syncedPreferred),
        )
    }

    @Test
    fun returnsNullOnMissingLyricsNonFlacOrCorruptedData() {
        val noLyrics = buildSyntheticFlac(listOf("ARTIST=Only Artist"))
        assertNull(FlacLyricsExtractor.extractFromBytes(noLyrics))

        assertNull(FlacLyricsExtractor.extractFromBytes("ID3fake".toByteArray()))
        assertNull(FlacLyricsExtractor.extractFromBytes(byteArrayOf(0x66, 0x4C, 0x61)))
        assertNull(FlacLyricsExtractor.extractFromBytes(byteArrayOf()))
    }
}
