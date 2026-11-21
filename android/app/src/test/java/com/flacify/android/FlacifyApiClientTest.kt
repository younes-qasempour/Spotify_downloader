package com.flacify.android

import com.flacify.android.network.FlacifyApiClient
import com.flacify.android.network.FlacifyApiException
import kotlinx.coroutines.test.runTest
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okio.Buffer
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test
import java.io.ByteArrayOutputStream
import java.util.zip.GZIPOutputStream

class FlacifyApiClientTest {

    @Test
    fun fetchHealthAndSyncInfoWithMultiUrlFailover() = runTest {
        val server = MockWebServer()
        server.start()
        try {
            // Find an unused closed localhost port so candidate #1 fails fast and fails over to server
            val deadPort = findClosedLocalPort()
            val deadUrl = "http://127.0.0.1:$deadPort"
            val liveUrl = server.url("/").toString().trimEnd('/')

            server.enqueue(
                MockResponse()
                    .setResponseCode(200)
                    .setBody(
                        """{"status":"ok","version":"2.0.1","api_version":"2.0","device_name":"StudioRig","lan_enabled":true,"pair_required":true,"queue_count":3}"""
                    )
            )
            server.enqueue(
                MockResponse()
                    .setResponseCode(200)
                    .setBody(
                        """{
                            "lan_enabled":true,
                            "bind_host":"0.0.0.0",
                            "restart_required":false,
                            "device_name":"StudioRig",
                            "port":8765,
                            "server_version":"2.0.1",
                            "urls":["$liveUrl"],
                            "primary_url":"$liveUrl",
                            "library_stats":{"total_tracks":5574,"total_bytes":41049319103,"size_str":"38.23 GB"},
                            "saved_playlists_count":12,
                            "paired":true
                        }"""
                    )
            )

            val client = FlacifyApiClient()
            val healthRes = client.fetchHealth(listOf(deadUrl, liveUrl))
            assertEquals(liveUrl, healthRes.resolvedBaseUrl)
            assertEquals("StudioRig", healthRes.data.deviceName)
            assertEquals(3, healthRes.data.queueCount)

            val infoRes = client.fetchSyncInfo(listOf(deadUrl, liveUrl), token = "tok_123")
            assertEquals(liveUrl, infoRes.resolvedBaseUrl)
            assertEquals(5574, infoRes.data.libraryStats.totalTracks)
            assertEquals(12, infoRes.data.savedPlaylistsCount)

            // Verify Authorization Bearer header on /api/sync/info
            server.takeRequest() // /api/health
            val infoReq = server.takeRequest()
            assertEquals("/api/sync/info", infoReq.path)
            assertEquals("Bearer tok_123", infoReq.getHeader("Authorization"))
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun unauthorized401AndLanDisabled403DoNotFailOverToFallbackUrls() = runTest {
        val primary = MockWebServer()
        val fallback = MockWebServer()
        primary.start()
        fallback.start()
        try {
            val client = FlacifyApiClient()
            val pUrl = primary.url("/").toString().trimEnd('/')
            val fUrl = fallback.url("/").toString().trimEnd('/')

            primary.enqueue(MockResponse().setResponseCode(401).setBody("""{"detail":"Invalid token"}"""))
            try {
                client.fetchSyncInfo(listOf(pUrl, fUrl), token = "bad_tok")
                fail("Expected Unauthorized exception")
            } catch (ex: FlacifyApiException.Unauthorized) {
                assertTrue(ex.message.orEmpty().contains("Invalid token"))
            }
            assertEquals(0, fallback.requestCount)

            primary.enqueue(MockResponse().setResponseCode(403).setBody("""{"detail":"LAN disabled"}"""))
            try {
                client.fetchSyncInfo(listOf(pUrl, fUrl), token = "bad_tok")
                fail("Expected LanDisabled exception")
            } catch (ex: FlacifyApiException.LanDisabled) {
                assertTrue(ex.message.orEmpty().contains("LAN disabled"))
            }
            assertEquals(0, fallback.requestCount)
        } finally {
            primary.shutdown()
            fallback.shutdown()
        }
    }

    @Test
    fun fetchManifestDecompressesGzipAndShareUrlPostsJson() = runTest {
        val server = MockWebServer()
        server.start()
        try {
            val manifestJson = """{
                "server_version":"2.0.1",
                "device_name":"StudioRig",
                "generated_at":1700000000000,
                "total_unique_tracks":1,
                "total_bytes":30000000,
                "playlists":[{
                    "id":"pl1",
                    "name":"Favorites",
                    "total_tracks":1,
                    "downloaded_tracks":1,
                    "cover_url":"/api/media/cover/collection?playlist_id=pl1",
                    "remote_cover_url":"https://img.example/cover.jpg",
                    "tracks":[{
                        "spotify_id":"alt1",
                        "canonical_id":"canon1",
                        "title":"Song One",
                        "artist":"Artist One",
                        "album":"Album One",
                        "duration_ms":210000,
                        "downloaded":true
                    }]
                }],
                "tracks":[{
                    "id":"canon1",
                    "alias_ids":["alt1"],
                    "title":"Song One",
                    "artist":"Artist One",
                    "album":"Album One",
                    "duration_ms":210000,
                    "quality_badge":"FLAC 16",
                    "filename":"Artist One - Song One.flac",
                    "ext":".flac",
                    "file_size":30000000,
                    "mtime_ms":1700000000000,
                    "file_url":"/api/sync/tracks/canon1/file",
                    "has_lrc":true
                }]
            }"""

            val gzBytes = gzipCompress(manifestJson)
            server.enqueue(
                MockResponse()
                    .setResponseCode(200)
                    .addHeader("Content-Encoding", "gzip")
                    .addHeader("Content-Type", "application/json")
                    .setBody(Buffer().write(gzBytes))
            )
            server.enqueue(
                MockResponse()
                    .setResponseCode(200)
                    .setBody(
                        """{"accepted":true,"extracted_url":"https://open.spotify.com/track/4uLU6hMCjMI75M1A2tKUQC","entity_type":"track","queued_count":1,"saved_playlists_updated":false,"started":true,"errors":[]}"""
                    )
            )

            val client = FlacifyApiClient()
            val baseUrl = server.url("/").toString().trimEnd('/')

            val manifest = client.fetchManifest(listOf(baseUrl), token = "tok_gz", playlistId = "pl1").data
            assertEquals(1, manifest.totalUniqueTracks)
            assertEquals("canon1", manifest.tracks.first().id)
            assertEquals(listOf("alt1"), manifest.tracks.first().aliasIds)
            assertTrue(manifest.tracks.first().hasLrc)

            val manifestReq = server.takeRequest()
            assertEquals("/api/sync/manifest?include_tracks=true&playlist_id=pl1", manifestReq.path)
            assertEquals("gzip", manifestReq.getHeader("Accept-Encoding"))

            val shareRes = client.shareUrl(
                listOf(baseUrl),
                token = "tok_gz",
                sharedText = "Check this https://open.spotify.com/track/4uLU6hMCjMI75M1A2tKUQC",
            ).data
            assertTrue(shareRes.accepted)
            assertEquals("track", shareRes.entityType)
            assertEquals(1, shareRes.queuedCount)

            val shareReq = server.takeRequest()
            assertEquals("POST", shareReq.method)
            assertEquals("/api/sync/share", shareReq.path)
            assertEquals("Bearer tok_gz", shareReq.getHeader("Authorization"))
            assertTrue(shareReq.body.readUtf8().contains("open.spotify.com/track"))
        } finally {
            server.shutdown()
        }
    }

    private fun gzipCompress(text: String): ByteArray {
        val baos = ByteArrayOutputStream()
        GZIPOutputStream(baos).use { gz ->
            gz.write(text.toByteArray(Charsets.UTF_8))
        }
        return baos.toByteArray()
    }

    private fun findClosedLocalPort(): Int {
        val socket = java.net.ServerSocket(0)
        val port = socket.localPort
        socket.close()
        return port
    }
}
