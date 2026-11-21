package com.flacify.android

import android.app.Application
import com.flacify.android.data.ConnectionSettingsStore
import com.flacify.android.data.FlacifyRepository
import com.flacify.android.data.db.FlacifyDatabase
import com.flacify.android.data.storage.LocalMediaStorage
import com.flacify.android.network.FlacifyApiClient
import com.flacify.android.network.MdnsDiscoveryManager
import com.flacify.android.sync.FlacifySyncManager
import com.flacify.android.sync.ResumableFileDownloader

class FlacifyApplication : Application() {
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
    }
}
