package com.flacify.android

import com.flacify.android.network.FlacifyApiException
import com.flacify.android.sync.ResumableFileDownloader
import kotlinx.coroutines.test.runTest
import okhttp3.OkHttpClient
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okio.Buffer
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.fail
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File

class ResumableFileDownloaderTest {

    @get:Rule
    val tempFolder = TemporaryFolder()

    private fun flacLikeBytes(len: Int): ByteArray =
        ByteArray(len) { idx -> ((idx * 31 + 7) % 251).toByte() }

    @Test
    fun freshDownloadWritesExactFileAndCleansPartFiles() = runTest {
        val server = MockWebServer()
        server.start()
        try {
            val payload = flacLikeBytes(4096)
            server.enqueue(
                MockResponse()
                    .setResponseCode(200)
                    .addHeader("ETag", "\"1000-abc\"")
                    .setBody(Buffer().write(payload))
            )

            val downloader = ResumableFileDownloader(OkHttpClient())
            val dest = File(tempFolder.root, "fresh.flac")
            val baseUrl = server.url("/").toString().trimEnd('/')
            val result = downloader.downloadTrackFile(
                candidateUrls = listOf(baseUrl),
                token = "tok1",
                relativeFileUrl = "/api/sync/tracks/t1/file",
                destFile = dest,
                expectedSize = payload.size.toLong(),
            )

            assertEquals(payload.size.toLong(), result.bytesWrittenTotal)
            assertEquals(0L, result.resumedFromBytes)
            assertEquals("\"1000-abc\"", result.etag)
            assertEquals(baseUrl, result.resolvedBaseUrl)
            assertArrayEquals(payload, dest.readBytes())
            assertFalse(File(tempFolder.root, "fresh.flac.part").exists())
            assertFalse(File(tempFolder.root, "fresh.flac.part.etag").exists())
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun resumesMidTransferWithRangeAndIfRange206() = runTest {
        val server = MockWebServer()
        server.start()
        try {
            val payload = flacLikeBytes(2000)
            val dest = File(tempFolder.root, "resume.flac")
            val part = File(tempFolder.root, "resume.flac.part")
            val etag = File(tempFolder.root, "resume.flac.part.etag")
            part.writeBytes(payload.copyOfRange(0, 750))
            etag.writeText("\"etag-v1\"")

            server.enqueue(
                MockResponse()
                    .setResponseCode(206)
                    .addHeader("ETag", "\"etag-v1\"")
                    .addHeader("Content-Range", "bytes 750-1999/2000")
                    .setBody(Buffer().write(payload.copyOfRange(750, 2000)))
            )

            val downloader = ResumableFileDownloader(OkHttpClient())
            val result = downloader.downloadTrackFile(
                candidateUrls = listOf(server.url("/").toString().trimEnd('/')),
                token = "tok2",
                relativeFileUrl = "/api/sync/tracks/t2/file",
                destFile = dest,
                expectedSize = 2000L,
            )

            assertEquals(750L, result.resumedFromBytes)
            assertEquals(2000L, result.bytesWrittenTotal)
            assertArrayEquals(payload, dest.readBytes())

            val req = server.takeRequest()
            assertEquals("bytes=750-", req.getHeader("Range"))
            assertEquals("\"etag-v1\"", req.getHeader("If-Range"))
            assertEquals("Bearer tok2", req.getHeader("Authorization"))
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun staleIfRangeReturning200OverwritesPartAndRetries416Cleanly() = runTest {
        val server = MockWebServer()
        server.start()
        try {
            val newPayload = flacLikeBytes(1500)
            val dest = File(tempFolder.root, "stale.flac")
            File(tempFolder.root, "stale.flac.part").writeBytes(flacLikeBytes(500))
            File(tempFolder.root, "stale.flac.part.etag").writeText("\"old-etag\"")

            server.enqueue(
                MockResponse()
                    .setResponseCode(200)
                    .addHeader("ETag", "\"new-etag\"")
                    .setBody(Buffer().write(newPayload))
            )

            val downloader = ResumableFileDownloader(OkHttpClient())
            val res = downloader.downloadTrackFile(
                candidateUrls = listOf(server.url("/").toString().trimEnd('/')),
                token = "tok3",
                relativeFileUrl = "/api/sync/tracks/t3/file",
                destFile = dest,
                expectedSize = 1500L,
            )

            assertEquals(0L, res.resumedFromBytes)
            assertArrayEquals(newPayload, dest.readBytes())

            // Next check 416 recovery
            val dest416 = File(tempFolder.root, "r416.flac")
            File(tempFolder.root, "r416.flac.part").writeBytes(flacLikeBytes(400))
            File(tempFolder.root, "r416.flac.part.etag").writeText("\"bad\"")
            server.enqueue(MockResponse().setResponseCode(416))
            server.enqueue(
                MockResponse()
                    .setResponseCode(200)
                    .addHeader("ETag", "\"ok\"")
                    .setBody(Buffer().write(newPayload))
            )

            val res416 = downloader.downloadTrackFile(
                candidateUrls = listOf(server.url("/").toString().trimEnd('/')),
                token = "tok3",
                relativeFileUrl = "/api/sync/tracks/t4/file",
                destFile = dest416,
                expectedSize = 1500L,
            )
            assertArrayEquals(newPayload, dest416.readBytes())
            assertEquals(0L, res416.resumedFromBytes)
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun unauthorized401ThrowsWithoutSwallowing() = runTest {
        val server = MockWebServer()
        server.start()
        try {
            server.enqueue(MockResponse().setResponseCode(401).setBody("""{"detail":"Expired"}"""))
            val downloader = ResumableFileDownloader(OkHttpClient())
            try {
                downloader.downloadTrackFile(
                    candidateUrls = listOf(server.url("/").toString().trimEnd('/')),
                    token = "wrong",
                    relativeFileUrl = "/api/sync/tracks/t5/file",
                    destFile = File(tempFolder.root, "auth.flac"),
                    expectedSize = 1000L,
                )
                fail("Expected Unauthorized")
            } catch (_: FlacifyApiException.Unauthorized) {
                // expected
            }
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun failsOverFromUnreachableFirstCandidateAndReportsResolvedUrl() = runTest {
        val deadServer = MockWebServer()
        deadServer.start()
        val deadUrl = deadServer.url("/").toString().trimEnd('/')
        deadServer.shutdown()

        val liveServer = MockWebServer()
        liveServer.start()
        try {
            val payload = flacLikeBytes(2048)
            liveServer.enqueue(
                MockResponse()
                    .setResponseCode(200)
                    .addHeader("ETag", "\"live-etag\"")
                    .setBody(Buffer().write(payload))
            )

            val liveUrl = liveServer.url("/").toString().trimEnd('/')
            val downloader = ResumableFileDownloader(OkHttpClient())
            val dest = File(tempFolder.root, "failover.flac")
            val result = downloader.downloadTrackFile(
                candidateUrls = listOf(deadUrl, liveUrl),
                token = "tok-failover",
                relativeFileUrl = "/api/sync/tracks/t6/file",
                destFile = dest,
                expectedSize = payload.size.toLong(),
            )

            assertEquals(liveUrl, result.resolvedBaseUrl)
            assertEquals(payload.size.toLong(), result.bytesWrittenTotal)
            assertArrayEquals(payload, dest.readBytes())
        } finally {
            liveServer.shutdown()
        }
    }
}
