package com.flacify.android.ui.playlists

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import com.flacify.android.FlacifyApplication
import com.flacify.android.data.FlacifyRepository
import com.flacify.android.sync.FlacifySyncManager
import com.flacify.android.sync.PlaylistSyncSummary
import com.flacify.android.sync.SyncProgressState
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.flowOn
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import java.util.Locale

data class PlaylistsUiState(
    val playlists: List<PlaylistSyncSummary> = emptyList(),
    val totalCatalogCount: Int = 0,
    val searchQuery: String = "",
    val onlyKeepOffline: Boolean = false,
    val isPaired: Boolean = false,
    val activeBaseUrl: String = "",
    val isRefreshing: Boolean = false,
    val syncProgress: SyncProgressState = SyncProgressState(),
    val errorMessage: String? = null,
)

class PlaylistsViewModel(
    private val repository: FlacifyRepository,
    private val syncManager: FlacifySyncManager,
) : ViewModel() {

    private val searchQueryFlow = MutableStateFlow("")
    private val onlyKeepOfflineFlow = MutableStateFlow(false)
    private val isRefreshingFlow = MutableStateFlow(false)
    private val errorMessageFlow = MutableStateFlow<String?>(null)

    private val _uiState = MutableStateFlow(PlaylistsUiState())
    val uiState: StateFlow<PlaylistsUiState> = _uiState.asStateFlow()

    init {
        val baseFlow = combine(
            repository.observePlaylistSummaries(),
            searchQueryFlow,
            onlyKeepOfflineFlow,
            repository.connectionStore.configFlow,
        ) { allSummaries, query, onlyOffline, cfg ->
            val cleanQuery = query.trim().lowercase(Locale.ROOT)
            val filtered = allSummaries.filter { summary ->
                if (onlyOffline && !summary.playlist.syncEnabled) return@filter false
                if (cleanQuery.isNotEmpty() &&
                    !summary.playlist.name.lowercase(Locale.ROOT).contains(cleanQuery)
                ) {
                    return@filter false
                }
                true
            }
            Quad(filtered, allSummaries.size, cfg, query to onlyOffline)
        }.flowOn(Dispatchers.Default)

        viewModelScope.launch {
            combine(
                baseFlow,
                isRefreshingFlow,
                syncManager.progressFlow,
                errorMessageFlow,
            ) { base, refreshing, progress, err ->
                PlaylistsUiState(
                    playlists = base.filtered,
                    totalCatalogCount = base.totalCount,
                    searchQuery = base.filters.first,
                    onlyKeepOffline = base.filters.second,
                    isPaired = base.cfg.isPaired,
                    activeBaseUrl = base.cfg.activeUrl,
                    isRefreshing = refreshing,
                    syncProgress = progress,
                    errorMessage = err ?: progress.errorMessage,
                )
            }.collect { state ->
                _uiState.value = state
            }
        }
    }

    fun updateSearch(query: String) {
        searchQueryFlow.value = query
        errorMessageFlow.value = null
    }

    fun toggleOnlyKeepOffline() {
        onlyKeepOfflineFlow.update { !it }
    }

    fun togglePlaylistSync(playlistId: String, enabled: Boolean) {
        viewModelScope.launch {
            repository.setPlaylistSyncEnabled(playlistId, enabled)
        }
    }

    fun refreshCatalog() {
        if (isRefreshingFlow.value) return
        viewModelScope.launch {
            isRefreshingFlow.value = true
            errorMessageFlow.value = null
            try {
                repository.refreshManifestFromPc()
            } catch (ex: Exception) {
                errorMessageFlow.value = ex.message ?: "Could not refresh playlists from PC."
            } finally {
                isRefreshingFlow.value = false
            }
        }
    }

    fun startSync() {
        errorMessageFlow.value = null
        syncManager.startSync(syncAllLibrary = false)
    }

    private data class Quad(
        val filtered: List<PlaylistSyncSummary>,
        val totalCount: Int,
        val cfg: com.flacify.android.data.ConnectionConfig,
        val filters: Pair<String, Boolean>,
    )

    class Factory(private val app: FlacifyApplication) : ViewModelProvider.Factory {
        @Suppress("UNCHECKED_CAST")
        override fun <T : ViewModel> create(modelClass: Class<T>): T =
            PlaylistsViewModel(
                repository = app.repository,
                syncManager = app.syncManager,
            ) as T
    }
}
