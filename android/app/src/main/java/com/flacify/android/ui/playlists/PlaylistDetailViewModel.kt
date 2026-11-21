package com.flacify.android.ui.playlists

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import com.flacify.android.FlacifyApplication
import com.flacify.android.data.FlacifyRepository
import com.flacify.android.data.PlaylistTrackItem
import com.flacify.android.data.db.PlaylistEntity
import com.flacify.android.sync.FlacifySyncManager
import com.flacify.android.sync.SyncProgressState
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.flowOn
import kotlinx.coroutines.launch
import java.util.Locale

data class PlaylistDetailUiState(
    val playlist: PlaylistEntity? = null,
    val items: List<PlaylistTrackItem> = emptyList(),
    val totalItemCount: Int = 0,
    val syncedOnPhoneCount: Int = 0,
    val totalNeededBytes: Long = 0L,
    val searchQuery: String = "",
    val isPaired: Boolean = false,
    val activeBaseUrl: String = "",
    val syncProgress: SyncProgressState = SyncProgressState(),
    val feedbackMessage: String? = null,
)

class PlaylistDetailViewModel(
    private val playlistId: String,
    private val repository: FlacifyRepository,
    private val syncManager: FlacifySyncManager,
) : ViewModel() {

    private val searchQueryFlow = MutableStateFlow("")
    private val feedbackFlow = MutableStateFlow<String?>(null)

    private val _uiState = MutableStateFlow(PlaylistDetailUiState())
    val uiState: StateFlow<PlaylistDetailUiState> = _uiState.asStateFlow()

    init {
        val itemsAndStatsFlow = combine(
            repository.observePlaylistTrackItems(playlistId),
            searchQueryFlow,
        ) { allItems, query ->
            val cleanQuery = query.trim().lowercase(Locale.ROOT)
            val filtered = if (cleanQuery.isEmpty()) {
                allItems
            } else {
                allItems.filter { item ->
                    val title = item.track?.title ?: item.entry.title
                    val artist = item.track?.artist ?: item.entry.artist
                    val album = item.track?.album ?: item.entry.album
                    "$title $artist $album".lowercase(Locale.ROOT).contains(cleanQuery)
                }
            }
            val syncedCount = allItems.count { it.isOfflineReady }
            val totalBytes = allItems
                .asSequence()
                .mapNotNull { it.track }
                .distinctBy { it.id }
                .sumOf { it.remoteFileSize.coerceAtLeast(it.localFileSize) }
            Triple(filtered, allItems.size, syncedCount to totalBytes)
        }.flowOn(Dispatchers.Default)

        viewModelScope.launch {
            combine(
                repository.observePlaylist(playlistId),
                itemsAndStatsFlow,
                repository.connectionStore.configFlow,
                syncManager.progressFlow,
                feedbackFlow,
            ) { playlist, stats, cfg, progress, feedback ->
                PlaylistDetailUiState(
                    playlist = playlist,
                    items = stats.first,
                    totalItemCount = stats.second,
                    syncedOnPhoneCount = stats.third.first,
                    totalNeededBytes = stats.third.second,
                    searchQuery = searchQueryFlow.value,
                    isPaired = cfg.isPaired,
                    activeBaseUrl = cfg.activeUrl,
                    syncProgress = progress,
                    feedbackMessage = feedback,
                )
            }.collect { state ->
                _uiState.value = state
            }
        }
    }

    fun updateSearch(query: String) {
        searchQueryFlow.value = query
    }

    fun toggleSyncEnabled(enabled: Boolean) {
        viewModelScope.launch {
            repository.setPlaylistSyncEnabled(playlistId, enabled)
        }
    }

    fun syncPlaylistNow() {
        viewModelScope.launch {
            repository.setPlaylistSyncEnabled(playlistId, true)
            feedbackFlow.value = "Syncing lossless FLAC tracks for this playlist..."
            syncManager.startSync(syncAllLibrary = false)
        }
    }

    fun offloadPlaylist() {
        viewModelScope.launch {
            val removed = repository.offloadPlaylist(playlistId)
            feedbackFlow.value = "Removed $removed unshared track(s) off this phone."
        }
    }

    class Factory(
        private val app: FlacifyApplication,
        private val playlistId: String,
    ) : ViewModelProvider.Factory {
        @Suppress("UNCHECKED_CAST")
        override fun <T : ViewModel> create(modelClass: Class<T>): T =
            PlaylistDetailViewModel(
                playlistId = playlistId,
                repository = app.repository,
                syncManager = app.syncManager,
            ) as T
    }
}
