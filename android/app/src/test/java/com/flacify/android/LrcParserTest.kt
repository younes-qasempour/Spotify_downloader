package com.flacify.android

import com.flacify.android.player.LrcParser
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class LrcParserTest {

    @Test
    fun parsesSyncedMultiTimestampsOffsetAndChronologicalOrder() {
        val raw = """
            [ar:Arctic Monkeys]
            [ti:505]
            [offset:250]
            [00:10.00][00:45.50]Chorus line
            [00:05.12]Intro line
            [00:08.5]Mid line
        """.trimIndent()

        val parsed = LrcParser.parse(raw)
        assertTrue(parsed.isSynced)
        assertEquals(4, parsed.lines.size)

        assertEquals(5370L, parsed.lines[0].timestampMs)
        assertEquals("Intro line", parsed.lines[0].text)

        assertEquals(8750L, parsed.lines[1].timestampMs)
        assertEquals("Mid line", parsed.lines[1].text)

        assertEquals(10250L, parsed.lines[2].timestampMs)
        assertEquals("Chorus line", parsed.lines[2].text)

        assertEquals(45750L, parsed.lines[3].timestampMs)
        assertEquals("Chorus line", parsed.lines[3].text)

        assertEquals(-1, LrcParser.findActiveLineIndex(parsed.lines, 1000L))
        assertEquals(0, LrcParser.findActiveLineIndex(parsed.lines, 5370L))
        assertEquals(1, LrcParser.findActiveLineIndex(parsed.lines, 9999L))
        assertEquals(2, LrcParser.findActiveLineIndex(parsed.lines, 20000L))
        assertEquals(3, LrcParser.findActiveLineIndex(parsed.lines, 90000L))
    }

    @Test
    fun fallsBackToPlainTextAndHandlesBlankInput() {
        val plain = """
            [ti:No Timestamps]
            First verse line
            Second verse line
        """.trimIndent()

        val parsed = LrcParser.parse(plain)
        assertFalse(parsed.isSynced)
        assertEquals(listOf("First verse line", "Second verse line"), parsed.lines.map { it.text })

        val empty = LrcParser.parse("   ")
        assertFalse(empty.isSynced)
        assertTrue(empty.lines.isEmpty())
        assertEquals(-1, LrcParser.findActiveLineIndex(empty.lines, 1000L))
    }
}
