package com.flacify.android.ui.library

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import com.flacify.android.FlacifyApplication
import com.flacify.android.data.ConnectionConfig
import com.flacify.android.data.FlacifyRepository
import com.flacify.android.data.db.TrackEntity
import com.flacify.android.data.db.TrackSyncStatus
import com.flacify.android.data.storage.StorageSummary
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.flowOn
import kotlinx.coroutines.launch

data class LibraryUiState(
    val tracks: List<TrackEntity> = emptyList(),
    val totalCatalogCount: Int = 0,
    val offlineTrackCount: Int = 0,
    val availableGenres: List<String> = emptyList(),
    val searchQuery: String = "",
    val syncFilter: TrackSyncFilter = TrackSyncFilter.ALL,
    val selectedGenre: String? = null,
    val sortOption: TrackSortOption = TrackSortOption.ARTIST_ASC,
    val storageSummary: StorageSummary = StorageSummary(),
    val isPaired: Boolean = false,
    val activeBaseUrl: String = "",
)

class LibraryViewModel(
    repository: FlacifyRepository,
) : ViewModel() {

    private val searchQueryFlow = MutableStateFlow("")
    private val syncFilterFlow = MutableStateFlow(TrackSyncFilter.ALL)
    private val selectedGenreFlow = MutableStateFlow<String?>(null)
    private val sortOptionFlow = MutableStateFlow(TrackSortOption.ARTIST_ASC)

    private val _uiState = MutableStateFlow(LibraryUiState())
    val uiState: StateFlow<LibraryUiState> = _uiState.asStateFlow()

    init {
        val computedTracksFlow = combine(
            repository.observeAllTracks(),
            searchQueryFlow,
            syncFilterFlow,
            selectedGenreFlow,
            sortOptionFlow,
        ) { allTracks, query, syncFilter, genre, sortOption ->
            val filtered = LibraryFilterEngine.filterAndSort(
                tracks = allTracks,
                query = query,
                syncFilter = syncFilter,
                genreFilter = genre,
                sortOption = sortOption,
            )
            val genres = LibraryFilterEngine.extractGenres(allTracks)
            val offlineCount = allTracks.count {
                it.syncStatus == TrackSyncStatus.SYNCED && !it.localFilePath.isNullOrBlank()
            }
            ComputedLibrary(
                filtered = filtered,
                totalCatalogCount = allTracks.size,
                offlineCount = offlineCount,
                genres = genres,
                query = query,
                syncFilter = syncFilter,
                selectedGenre = genre,
                sortOption = sortOption,
            )
        }.flowOn(Dispatchers.Default)

        viewModelScope.launch {
            combine(
                computedTracksFlow,
                repository.observeStorageSummary(),
                repository.connectionStore.configFlow,
            ) { computed, storage, cfg ->
                LibraryUiState(
                    tracks = computed.filtered,
                    totalCatalogCount = computed.totalCatalogCount,
                    offlineTrackCount = computed.offlineCount,
                    availableGenres = computed.genres,
                    searchQuery = computed.query,
                    syncFilter = computed.syncFilter,
                    selectedGenre = computed.selectedGenre,
                    sortOption = computed.sortOption,
                    storageSummary = storage,
                    isPaired = cfg.isPaired,
                    activeBaseUrl = cfg.activeUrl,
                )
            }.collect { state ->
                _uiState.value = state
            }
        }
    }

    fun updateSearch(query: String) {
        searchQueryFlow.value = query
    }

    fun setSyncFilter(filter: TrackSyncFilter) {
        syncFilterFlow.value = filter
    }

    fun setSelectedGenre(genre: String?) {
        selectedGenreFlow.value = genre
    }

    fun setSortOption(option: TrackSortOption) {
        sortOptionFlow.value = option
    }

    private data class ComputedLibrary(
        val filtered: List<TrackEntity>,
        val totalCatalogCount: Int,
        val offlineCount: Int,
        val genres: List<String>,
        val query: String,
        val syncFilter: TrackSyncFilter,
        val selectedGenre: String?,
        val sortOption: TrackSortOption,
    )

    class Factory(private val app: FlacifyApplication) : ViewModelProvider.Factory {
        @Suppress("UNCHECKED_CAST")
        override fun <T : ViewModel> create(modelClass: Class<T>): T =
            LibraryViewModel(repository = app.repository) as T
    }
}
