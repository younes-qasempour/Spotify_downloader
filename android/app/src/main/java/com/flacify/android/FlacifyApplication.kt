package com.flacify.android

import android.app.Application
import com.flacify.android.data.ConnectionSettingsStore
import com.flacify.android.network.FlacifyApiClient
import com.flacify.android.network.MdnsDiscoveryManager

class FlacifyApplication : Application() {
    lateinit var connectionStore: ConnectionSettingsStore
        private set
    lateinit var apiClient: FlacifyApiClient
        private set
    lateinit var mdnsDiscovery: MdnsDiscoveryManager
        private set

    override fun onCreate() {
        super.onCreate()
        connectionStore = ConnectionSettingsStore(this)
        apiClient = FlacifyApiClient()
        mdnsDiscovery = MdnsDiscoveryManager(this)
    }
}
