package com.flacify.android.data.storage

import android.content.Context
import android.os.Environment
import android.os.StatFs
import java.io.File

data class StorageSummary(
    val audioBytes: Long = 0L,
    val coverBytes: Long = 0L,
    val availableBytes: Long = 0L,
    val totalDeviceBytes: Long = 0L,
)

class LocalMediaStorage(context: Context) {
    private val rootDir: File =
        context.getExternalFilesDir(Environment.DIRECTORY_MUSIC)
            ?: File(context.filesDir, "music")

    val tracksDir: File = File(rootDir, "tracks").apply { mkdirs() }
    val trackCoversDir: File = File(rootDir, "covers/tracks").apply { mkdirs() }
    val playlistCoversDir: File = File(rootDir, "covers/playlists").apply { mkdirs() }

    fun trackFile(canonicalId: String, ext: String): File {
        tracksDir.mkdirs()
        val safeId = sanitizeId(canonicalId)
        val cleanExt = normalizeExtension(ext)
        return File(tracksDir, "$safeId$cleanExt")
    }

    fun partFile(destFile: File): File = File(destFile.parentFile ?: tracksDir, "${destFile.name}.part")

    fun etagFile(destFile: File): File = File(destFile.parentFile ?: tracksDir, "${destFile.name}.part.etag")

    fun trackCoverFile(canonicalId: String): File {
        trackCoversDir.mkdirs()
        return File(trackCoversDir, "${sanitizeId(canonicalId)}.img")
    }

    fun playlistCoverFile(playlistId: String): File {
        playlistCoversDir.mkdirs()
        return File(playlistCoversDir, "${sanitizeId(playlistId)}.img")
    }

    fun fileExistsNonEmpty(path: String?): Boolean {
        if (path.isNullOrBlank()) return false
        val f = File(path)
        return f.isFile && f.length() > 0L
    }

    fun deleteTrackArtifacts(localFilePath: String?, localCoverPath: String?) {
        if (!localFilePath.isNullOrBlank()) {
            val f = File(localFilePath)
            runCatching { if (f.exists()) f.delete() }
            runCatching {
                val p = partFile(f)
                if (p.exists()) p.delete()
            }
            runCatching {
                val e = etagFile(f)
                if (e.exists()) e.delete()
            }
        }
        if (!localCoverPath.isNullOrBlank()) {
            runCatching {
                val c = File(localCoverPath)
                if (c.exists()) c.delete()
            }
        }
    }

    fun computeStorageSummary(): StorageSummary {
        rootDir.mkdirs()
        val audio = sumDirectoryBytes(tracksDir)
        val covers = sumDirectoryBytes(trackCoversDir) + sumDirectoryBytes(playlistCoversDir)
        return try {
            val stat = StatFs(rootDir.absolutePath)
            StorageSummary(
                audioBytes = audio,
                coverBytes = covers,
                availableBytes = stat.availableBytes,
                totalDeviceBytes = stat.totalBytes,
            )
        } catch (_: Exception) {
            StorageSummary(audioBytes = audio, coverBytes = covers)
        }
    }

    private fun sumDirectoryBytes(dir: File): Long {
        if (!dir.exists() || !dir.isDirectory) return 0L
        return dir.listFiles()?.sumOf { child ->
            if (child.isFile) child.length() else 0L
        } ?: 0L
    }

    private fun sanitizeId(raw: String): String =
        raw.replace(SAFE_ID_REGEX, "_").take(96).ifBlank { "item" }

    private fun normalizeExtension(rawExt: String): String {
        val cleaned = rawExt.trim().lowercase()
        val dotted = if (cleaned.startsWith(".")) cleaned else ".$cleaned"
        return if (dotted.length in 2..8 && dotted.drop(1).all { it.isLetterOrDigit() }) {
            dotted
        } else {
            ".flac"
        }
    }

    private companion object {
        val SAFE_ID_REGEX = Regex("[^A-Za-z0-9._-]")
    }
}
