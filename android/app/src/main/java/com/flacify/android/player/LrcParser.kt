package com.flacify.android.player

data class LyricLine(
    val timestampMs: Long,
    val text: String,
)

data class ParsedLyrics(
    val lines: List<LyricLine> = emptyList(),
    val isSynced: Boolean = false,
)

object LrcParser {
    private val LINE_PREFIX_REGEX = Regex("""^((?:\[\d{1,3}:\d{2}(?:\.\d{1,3})?])+)(.*)$""")
    private val TIME_TAG_REGEX = Regex("""\[(\d{1,3}):(\d{2})(?:\.(\d{1,3}))?]""")
    private val OFFSET_TAG_REGEX = Regex("""^\[offset:([+-]?\d+)]$""", RegexOption.IGNORE_CASE)
    private val METADATA_TAG_REGEX = Regex("""^\[[a-z]{1,10}:.*]$""", RegexOption.IGNORE_CASE)

    fun parse(rawText: String?): ParsedLyrics {
        val text = rawText?.trim().orEmpty()
        if (text.isEmpty()) return ParsedLyrics()

        var offsetMs = 0L
        val timedEntries = mutableListOf<LyricLine>()
        val plainLines = mutableListOf<LyricLine>()

        for (rawLine in text.lineSequence()) {
            val line = rawLine.trim()
            if (line.isEmpty()) continue

            val offsetMatch = OFFSET_TAG_REGEX.matchEntire(line)
            if (offsetMatch != null) {
                offsetMs = offsetMatch.groupValues[1].toLongOrNull() ?: 0L
                continue
            }

            val lineMatch = LINE_PREFIX_REGEX.matchEntire(line)
            if (lineMatch != null) {
                val tagsPart = lineMatch.groupValues[1]
                val lyric = lineMatch.groupValues[2].trim()
                if (lyric.isEmpty()) continue

                for (tm in TIME_TAG_REGEX.findAll(tagsPart)) {
                    val mins = tm.groupValues[1].toLongOrNull() ?: continue
                    val secs = tm.groupValues[2].toLongOrNull() ?: continue
                    val frac = tm.groupValues[3]
                    val ms = if (frac.isEmpty()) {
                        0L
                    } else {
                        frac.padEnd(3, '0').take(3).toLongOrNull() ?: 0L
                    }
                    val totalMs = ((mins * 60L + secs) * 1000L + ms + offsetMs).coerceAtLeast(0L)
                    timedEntries.add(LyricLine(timestampMs = totalMs, text = lyric))
                }
            } else if (!METADATA_TAG_REGEX.matches(line)) {
                plainLines.add(LyricLine(timestampMs = 0L, text = line))
            }
        }

        if (timedEntries.isNotEmpty()) {
            timedEntries.sortBy { it.timestampMs }
            return ParsedLyrics(lines = timedEntries, isSynced = true)
        }

        if (plainLines.isNotEmpty()) {
            return ParsedLyrics(lines = plainLines, isSynced = false)
        }

        return ParsedLyrics()
    }

    fun findActiveLineIndex(lines: List<LyricLine>, positionMs: Long): Int {
        if (lines.isEmpty() || positionMs < lines.first().timestampMs) return -1
        var low = 0
        var high = lines.lastIndex
        var answer = -1
        while (low <= high) {
            val mid = (low + high) ushr 1
            if (lines[mid].timestampMs <= positionMs) {
                answer = mid
                low = mid + 1
            } else {
                high = mid - 1
            }
        }
        return answer
    }
}
