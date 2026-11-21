package com.flacify.android

import android.app.Application
import coil.ImageLoader
import coil.ImageLoaderFactory
import coil.disk.DiskCache
import coil.memory.MemoryCache
import com.flacify.android.data.ConnectionConfig
import com.flacify.android.data.ConnectionSettingsStore
import com.flacify.android.data.FlacifyRepository
import com.flacify.android.data.db.FlacifyDatabase
import com.flacify.android.data.storage.LocalMediaStorage
import com.flacify.android.network.FlacifyApiClient
import com.flacify.android.network.MdnsDiscoveryManager
import com.flacify.android.player.FlacifyPlayerController
import com.flacify.android.sync.FlacifySyncManager
import com.flacify.android.sync.ResumableFileDownloader
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull
import java.io.File
import java.util.concurrent.atomic.AtomicReference

class FlacifyApplication : Application(), ImageLoaderFactory {
    lateinit var connectionStore: ConnectionSettingsStore
        private set
    lateinit var apiClient: FlacifyApiClient
        private set
    lateinit var mdnsDiscovery: MdnsDiscoveryManager
        private set
    lateinit var database: FlacifyDatabase
        private set
    lateinit var storage: LocalMediaStorage
        private set
    lateinit var fileDownloader: ResumableFileDownloader
        private set
    lateinit var repository: FlacifyRepository
        private set
    lateinit var syncManager: FlacifySyncManager
        private set
    lateinit var playerController: FlacifyPlayerController
        private set

    private val appScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val latestConnection = AtomicReference(ConnectionConfig())

    override fun onCreate() {
        super.onCreate()
        connectionStore = ConnectionSettingsStore(this)
        apiClient = FlacifyApiClient()
        mdnsDiscovery = MdnsDiscoveryManager(this)
        database = FlacifyDatabase.getInstance(this)
        storage = LocalMediaStorage(this)
        fileDownloader = ResumableFileDownloader(apiClient.rawHttpClient)
        repository = FlacifyRepository(
            database = database,
            storage = storage,
            connectionStore = connectionStore,
            apiClient = apiClient,
        )
        syncManager = FlacifySyncManager(this)
        playerController = FlacifyPlayerController(this)

        appScope.launch {
            connectionStore.configFlow.collect { cfg ->
                latestConnection.set(cfg)
            }
        }
    }

    override fun newImageLoader(): ImageLoader {
        val imageHttpClient = apiClient.rawHttpClient.newBuilder()
            .addInterceptor { chain ->
                val request = chain.request()
                val cfg = latestConnection.get()
                val reqUrl = request.url
                val matchesPcHost = cfg.pairToken.isNotBlank() &&
                    cfg.orderedCandidateUrls().any { candidate ->
                        val candUrl = candidate.toHttpUrlOrNull()
                        candUrl != null &&
                            candUrl.scheme == reqUrl.scheme &&
                            candUrl.host.equals(reqUrl.host, ignoreCase = true) &&
                            candUrl.port == reqUrl.port
                    }
                val finalReq = if (matchesPcHost && request.header("Authorization") == null) {
                    request.newBuilder()
                        .header("Authorization", "Bearer ${cfg.pairToken.trim()}")
                        .build()
                } else {
                    request
                }
                chain.proceed(finalReq)
            }
            .build()

        return ImageLoader.Builder(this)
            .okHttpClient(imageHttpClient)
            .memoryCache {
                MemoryCache.Builder(this)
                    .maxSizePercent(0.20)
                    .build()
            }
            .diskCache {
                DiskCache.Builder()
                    .directory(File(cacheDir, "image_cache"))
                    .maxSizeBytes(64L * 1024L * 1024L)
                    .build()
            }
            .crossfade(true)
            .build()
    }
}
