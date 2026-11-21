package com.flacify.android.ui.sync

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import com.flacify.android.FlacifyApplication
import com.flacify.android.data.ConnectionConfig
import com.flacify.android.data.ConnectionSettingsStore
import com.flacify.android.data.FlacifyRepository
import com.flacify.android.data.storage.StorageSummary
import com.flacify.android.network.DiscoveredPc
import com.flacify.android.network.FlacifyApiClient
import com.flacify.android.network.MdnsDiscoveryManager
import com.flacify.android.network.PairingUriParser
import com.flacify.android.network.SyncInfoResponse
import com.flacify.android.sync.FlacifySyncManager
import com.flacify.android.sync.PlaylistSyncSummary
import com.flacify.android.sync.SyncProgressState
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class SyncUiState(
    val connectionConfig: ConnectionConfig = ConnectionConfig(),
    val manualUrl: String = "",
    val manualToken: String = "",
    val pairingUriInput: String = "",
    val showToken: Boolean = false,
    val isTesting: Boolean = false,
    val isConnected: Boolean = false,
    val syncInfo: SyncInfoResponse? = null,
    val statusMessage: String? = null,
    val errorMessage: String? = null,
    val discoveredPcs: List<DiscoveredPc> = emptyList(),
    val isScanningMdns: Boolean = false,
    val mdnsError: String? = null,
    val playlistSummaries: List<PlaylistSyncSummary> = emptyList(),
    val storageSummary: StorageSummary = StorageSummary(),
    val syncedTrackCount: Int = 0,
    val isRefreshingCatalog: Boolean = false,
    val syncProgress: SyncProgressState = SyncProgressState(),
)

class SyncViewModel(
    private val connectionStore: ConnectionSettingsStore,
    private val apiClient: FlacifyApiClient,
    private val mdnsDiscovery: MdnsDiscoveryManager,
    private val repository: FlacifyRepository,
    private val syncManager: FlacifySyncManager,
) : ViewModel() {

    private val _uiState = MutableStateFlow(SyncUiState())
    val uiState: StateFlow<SyncUiState> = _uiState.asStateFlow()

    private var formSeededFromStore = false
    private var initialCheckDone = false

    init {
        viewModelScope.launch {
            connectionStore.configFlow.collect { cfg ->
                _uiState.update { cur ->
                    val shouldSeed = !formSeededFromStore || (!cfg.isPaired && !cur.isPairedEdited)
                    if (cfg.isPaired) {
                        formSeededFromStore = true
                    }
                    cur.copy(
                        connectionConfig = cfg,
                        manualUrl = if (shouldSeed) cfg.activeUrl else cur.manualUrl,
                        manualToken = if (shouldSeed) cfg.pairToken else cur.manualToken,
                    )
                }
                if (cfg.isPaired && !initialCheckDone) {
                    initialCheckDone = true
                    testSavedConnection()
                }
            }
        }

        viewModelScope.launch {
            repository.observePlaylistSummaries().collect { list ->
                _uiState.update { it.copy(playlistSummaries = list) }
            }
        }
        viewModelScope.launch {
            repository.observeStorageSummary().collect { summary ->
                _uiState.update { it.copy(storageSummary = summary) }
            }
        }
        viewModelScope.launch {
            repository.observeSyncedTrackCount().collect { count ->
                _uiState.update { it.copy(syncedTrackCount = count) }
            }
        }
        viewModelScope.launch {
            syncManager.progressFlow.collect { prog ->
                _uiState.update { cur ->
                    cur.copy(
                        syncProgress = prog,
                        statusMessage = prog.terminalMessage ?: cur.statusMessage,
                        errorMessage = prog.errorMessage ?: cur.errorMessage,
                    )
                }
            }
        }

        viewModelScope.launch {
            mdnsDiscovery.discoveredPcs.collect { pcs ->
                _uiState.update { it.copy(discoveredPcs = pcs) }
            }
        }
        viewModelScope.launch {
            mdnsDiscovery.isScanning.collect { scanning ->
                _uiState.update { it.copy(isScanningMdns = scanning) }
            }
        }
        viewModelScope.launch {
            mdnsDiscovery.errorMessage.collect { err ->
                _uiState.update { it.copy(mdnsError = err) }
            }
        }
    }

    private val SyncUiState.isPairedEdited: Boolean
        get() = manualUrl.isNotBlank() || manualToken.isNotBlank()

    fun updateManualUrl(value: String) {
        formSeededFromStore = true
        _uiState.update { it.copy(manualUrl = value, errorMessage = null) }
    }

    fun updateManualToken(value: String) {
        formSeededFromStore = true
        _uiState.update { it.copy(manualToken = value, errorMessage = null) }
    }

    fun updatePairingUriInput(value: String) {
        _uiState.update { it.copy(pairingUriInput = value, errorMessage = null) }
    }

    fun toggleShowToken() {
        _uiState.update { it.copy(showToken = !it.showToken) }
    }

    fun useEmulatorHost() {
        formSeededFromStore = true
        _uiState.update {
            it.copy(
                manualUrl = EMULATOR_HOST_URL,
                errorMessage = null,
                statusMessage = "Filled Android Emulator host address (10.0.2.2:8765).",
            )
        }
    }

    fun selectDiscoveredPc(pc: DiscoveredPc) {
        formSeededFromStore = true
        _uiState.update {
            it.copy(
                manualUrl = pc.baseUrl,
                errorMessage = null,
                statusMessage = "Selected '${pc.displayName}' at ${pc.baseUrl}. Paste your token or scan the QR code.",
            )
        }
        if (_uiState.value.manualToken.isNotBlank()) {
            connectManual()
        }
    }

    fun applyPairingUri(rawUri: String, autoConnect: Boolean = true) {
        val parsed = PairingUriParser.parse(rawUri)
        if (parsed == null) {
            _uiState.update {
                it.copy(
                    errorMessage = "Invalid Flacify pairing URI/QR code. Expected flacify://pair?host=...&token=...",
                    statusMessage = null,
                )
            }
            return
        }

        formSeededFromStore = true
        _uiState.update {
            it.copy(
                manualUrl = parsed.candidateUrls.first(),
                manualToken = parsed.token,
                pairingUriInput = rawUri.trim(),
                errorMessage = null,
                statusMessage = "Parsed pairing details for ${parsed.deviceName.ifBlank { parsed.host }}.",
            )
        }

        if (autoConnect) {
            connectAndVerify(
                candidateUrls = parsed.candidateUrls,
                token = parsed.token,
                fallbackName = parsed.deviceName,
            )
        }
    }

    fun connectManual() {
        val state = _uiState.value
        val normalizedUrl = PairingUriParser.normalizeBaseUrl(state.manualUrl)
        val token = state.manualToken.trim()

        if (normalizedUrl == null) {
            _uiState.update {
                it.copy(errorMessage = "Enter a valid PC server address, e.g. http://192.168.1.50:8765 or http://10.0.2.2:8765")
            }
            return
        }
        if (token.isEmpty()) {
            _uiState.update {
                it.copy(errorMessage = "Enter or scan your PC Pairing Token.")
            }
            return
        }

        val extras = if (normalizedUrl == state.connectionConfig.activeUrl) {
            state.connectionConfig.candidateUrls
        } else {
            emptyList()
        }
        connectAndVerify(
            candidateUrls = PairingUriParser.mergeCandidateUrls(normalizedUrl, extras),
            token = token,
        )
    }

    fun testSavedConnection() {
        val cfg = _uiState.value.connectionConfig
        if (!cfg.isPaired) return
        connectAndVerify(
            candidateUrls = cfg.orderedCandidateUrls(),
            token = cfg.pairToken,
            fallbackName = cfg.deviceName,
        )
    }

    private fun connectAndVerify(
        candidateUrls: List<String>,
        token: String,
        fallbackName: String = "",
    ) {
        if (_uiState.value.isTesting) return
        viewModelScope.launch {
            _uiState.update {
                it.copy(
                    isTesting = true,
                    errorMessage = null,
                    statusMessage = "Connecting to Flacify PC...",
                )
            }

            try {
                val result = apiClient.fetchSyncInfo(candidateUrls, token)
                val info = result.data
                val mergedUrls = PairingUriParser.mergeCandidateUrls(
                    result.resolvedBaseUrl,
                    candidateUrls + info.urls,
                )
                val resolvedName = info.deviceName.ifBlank { fallbackName.ifBlank { "Flacify PC" } }

                connectionStore.saveConnection(
                    activeUrl = result.resolvedBaseUrl,
                    candidateUrls = mergedUrls,
                    pairToken = token,
                    deviceName = resolvedName,
                    serverVersion = info.serverVersion,
                )

                _uiState.update {
                    it.copy(
                        isTesting = false,
                        isConnected = true,
                        syncInfo = info,
                        manualUrl = result.resolvedBaseUrl,
                        manualToken = token,
                        errorMessage = null,
                        statusMessage = "Connected to $resolvedName (${result.resolvedBaseUrl})",
                    )
                }

                if (_uiState.value.playlistSummaries.isEmpty()) {
                    refreshCatalog()
                }
            } catch (ex: Exception) {
                _uiState.update {
                    it.copy(
                        isTesting = false,
                        isConnected = false,
                        statusMessage = null,
                        errorMessage = ex.message ?: "Failed to connect to Flacify PC.",
                    )
                }
            }
        }
    }

    fun refreshCatalog() {
        if (_uiState.value.isRefreshingCatalog) return
        viewModelScope.launch {
            _uiState.update { it.copy(isRefreshingCatalog = true, errorMessage = null) }
            try {
                val manifest = repository.refreshManifestFromPc()
                _uiState.update {
                    it.copy(
                        isRefreshingCatalog = false,
                        statusMessage = "Catalog refreshed: ${manifest.playlists.size} playlists · ${manifest.totalUniqueTracks} unique lossless tracks on PC.",
                    )
                }
            } catch (ex: Exception) {
                _uiState.update {
                    it.copy(
                        isRefreshingCatalog = false,
                        errorMessage = ex.message ?: "Failed to refresh catalog from PC.",
                    )
                }
            }
        }
    }

    fun togglePlaylistSync(playlistId: String, enabled: Boolean) {
        viewModelScope.launch {
            repository.setPlaylistSyncEnabled(playlistId, enabled)
        }
    }

    fun startOfflineSync(syncAllLibrary: Boolean = false) {
        _uiState.update { it.copy(errorMessage = null, statusMessage = "Starting lossless FLAC sync...") }
        syncManager.startSync(syncAllLibrary = syncAllLibrary)
    }

    fun cancelOfflineSync() {
        syncManager.cancelSync()
    }

    fun offloadPlaylist(playlistId: String, playlistName: String) {
        viewModelScope.launch {
            val removed = repository.offloadPlaylist(playlistId)
            _uiState.update {
                it.copy(
                    errorMessage = null,
                    statusMessage = "Removed $removed unshared track(s) from '$playlistName' off this phone.",
                )
            }
        }
    }

    fun cleanOrphanFiles() {
        viewModelScope.launch {
            val removed = repository.cleanOrphanFiles()
            _uiState.update {
                it.copy(
                    errorMessage = null,
                    statusMessage = if (removed > 0) {
                        "Cleaned $removed unused audio file(s) from phone storage."
                    } else {
                        "No unused audio files to clean."
                    },
                )
            }
        }
    }

    fun disconnect() {
        viewModelScope.launch {
            syncManager.cancelSync()
            connectionStore.clearConnection()
            formSeededFromStore = true
            _uiState.update {
                it.copy(
                    isConnected = false,
                    syncInfo = null,
                    manualUrl = "",
                    manualToken = "",
                    pairingUriInput = "",
                    errorMessage = null,
                    statusMessage = "Disconnected from PC. Downloaded offline FLAC files remain on phone.",
                )
            }
        }
    }

    fun startMdnsScan() {
        mdnsDiscovery.startDiscovery()
    }

    fun stopMdnsScan() {
        mdnsDiscovery.stopDiscovery()
    }

    override fun onCleared() {
        super.onCleared()
        mdnsDiscovery.stopDiscovery()
    }

    class Factory(private val app: FlacifyApplication) : ViewModelProvider.Factory {
        @Suppress("UNCHECKED_CAST")
        override fun <T : ViewModel> create(modelClass: Class<T>): T =
            SyncViewModel(
                connectionStore = app.connectionStore,
                apiClient = app.apiClient,
                mdnsDiscovery = app.mdnsDiscovery,
                repository = app.repository,
                syncManager = app.syncManager,
            ) as T
    }

    private companion object {
        const val EMULATOR_HOST_URL = "http://10.0.2.2:8765"
    }
}
