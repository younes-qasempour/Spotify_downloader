package com.flacify.android.player

import java.io.ByteArrayInputStream
import java.io.EOFException
import java.io.File
import java.io.FileInputStream
import java.io.InputStream
import java.nio.charset.StandardCharsets

/**
 * Lightweight zero-dependency reader for Vorbis Comment embedded lyrics
 * (`SYNCEDLYRICS`, `LYRICS`, `UNSYNCEDLYRICS`) stored inside lossless `.flac` files.
 */
object FlacLyricsExtractor {
    private const val BLOCK_TYPE_VORBIS_COMMENT = 4
    private const val MAX_VORBIS_BLOCK_BYTES = 4 * 1024 * 1024
    private const val MAX_COMMENTS_COUNT = 4096

    fun extractFromFile(file: File): String? {
        if (!file.isFile || file.length() < 8L) return null
        return try {
            FileInputStream(file).buffered(16 * 1024).use { stream ->
                extractFromStream(stream)
            }
        } catch (_: Exception) {
            null
        }
    }

    fun extractFromBytes(bytes: ByteArray): String? {
        if (bytes.size < 8) return null
        return extractFromStream(ByteArrayInputStream(bytes))
    }

    fun extractFromStream(input: InputStream): String? {
        return try {
            val magic = ByteArray(4)
            if (!readFully(input, magic)) return null
            if (magic[0] != 'f'.code.toByte() ||
                magic[1] != 'L'.code.toByte() ||
                magic[2] != 'a'.code.toByte() ||
                magic[3] != 'C'.code.toByte()
            ) {
                return null
            }

            val header = ByteArray(4)
            while (readFully(input, header)) {
                val first = header[0].toInt() and 0xFF
                val isLast = (first and 0x80) != 0
                val blockType = first and 0x7F
                val blockLen = ((header[1].toInt() and 0xFF) shl 16) or
                    ((header[2].toInt() and 0xFF) shl 8) or
                    (header[3].toInt() and 0xFF)

                if (blockType == BLOCK_TYPE_VORBIS_COMMENT) {
                    if (blockLen <= 0 || blockLen > MAX_VORBIS_BLOCK_BYTES) return null
                    val payload = ByteArray(blockLen)
                    if (!readFully(input, payload)) return null
                    val found = parseVorbisCommentPayload(payload)
                    if (!found.isNullOrBlank()) return found
                } else if (blockLen > 0) {
                    skipFully(input, blockLen.toLong())
                }

                if (isLast) break
            }
            null
        } catch (_: Exception) {
            null
        }
    }

    private fun parseVorbisCommentPayload(payload: ByteArray): String? {
        var pos = 0
        if (pos + 4 > payload.size) return null
        val vendorLen = readLeUInt32(payload, pos)
        pos += 4
        if (vendorLen < 0L || vendorLen > (payload.size - pos).toLong()) return null
        pos += vendorLen.toInt()

        if (pos + 4 > payload.size) return null
        val count = readLeUInt32(payload, pos).coerceAtMost(MAX_COMMENTS_COUNT.toLong()).toInt()
        pos += 4

        var syncedCandidate: String? = null
        var generalCandidate: String? = null
        var unsyncedCandidate: String? = null

        for (i in 0 until count) {
            if (pos + 4 > payload.size) break
            val commentLen = readLeUInt32(payload, pos)
            pos += 4
            if (commentLen < 0L || commentLen > (payload.size - pos).toLong()) break
            val len = commentLen.toInt()
            val entry = String(payload, pos, len, StandardCharsets.UTF_8)
            pos += len

            val eqIdx = entry.indexOf('=')
            if (eqIdx <= 0) continue
            val key = entry.substring(0, eqIdx).trim().uppercase()
            val value = entry.substring(eqIdx + 1).trim()
            if (value.isEmpty()) continue

            when {
                key == "SYNCEDLYRICS" || key == "SYNCED_LYRICS" ->
                    if (syncedCandidate == null) syncedCandidate = value
                key == "LYRICS" ->
                    if (generalCandidate == null) generalCandidate = value
                key == "UNSYNCEDLYRICS" || key == "UNSYNCED_LYRICS" ->
                    if (unsyncedCandidate == null) unsyncedCandidate = value
            }
        }

        return syncedCandidate ?: generalCandidate ?: unsyncedCandidate
    }

    private fun readLeUInt32(buf: ByteArray, offset: Int): Long {
        return (buf[offset].toLong() and 0xFFL) or
            ((buf[offset + 1].toLong() and 0xFFL) shl 8) or
            ((buf[offset + 2].toLong() and 0xFFL) shl 16) or
            ((buf[offset + 3].toLong() and 0xFFL) shl 24)
    }

    private fun readFully(input: InputStream, dest: ByteArray): Boolean {
        var off = 0
        while (off < dest.size) {
            val n = input.read(dest, off, dest.size - off)
            if (n < 0) return false
            off += n
        }
        return true
    }

    private fun skipFully(input: InputStream, totalBytes: Long) {
        var remaining = totalBytes
        val scratch = ByteArray(4096)
        while (remaining > 0L) {
            val skipped = input.skip(remaining)
            if (skipped > 0L) {
                remaining -= skipped
            } else {
                val read = input.read(scratch, 0, minOf(scratch.size.toLong(), remaining).toInt())
                if (read < 0) throw EOFException("Unexpected EOF skipping FLAC metadata block")
                remaining -= read
            }
        }
    }
}
