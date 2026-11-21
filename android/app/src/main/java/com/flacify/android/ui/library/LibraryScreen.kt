package com.flacify.android.ui.library

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.Sort
import androidx.compose.material.icons.rounded.ArrowDropDown
import androidx.compose.material.icons.rounded.Close
import androidx.compose.material.icons.rounded.LibraryMusic
import androidx.compose.material.icons.rounded.Search
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.flacify.android.data.db.TrackEntity
import com.flacify.android.data.db.TrackSyncStatus
import com.flacify.android.ui.components.TrackRowItem
import com.flacify.android.ui.theme.FlacifyBorder
import com.flacify.android.ui.theme.FlacifyCardSurface
import com.flacify.android.ui.theme.FlacifyElevatedSurface
import com.flacify.android.ui.theme.FlacifyEmerald
import com.flacify.android.ui.theme.FlacifyEmeraldBright
import com.flacify.android.ui.theme.FlacifySkyAccent
import com.flacify.android.ui.theme.FlacifyTextMuted
import com.flacify.android.ui.theme.FlacifyTextPrimary

@Composable
fun LibraryScreen(
    viewModel: LibraryViewModel,
    onTrackSelected: (queue: List<TrackEntity>, startIndex: Int, title: String, isOffline: Boolean) -> Unit,
    onOpenSyncTab: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val state by viewModel.uiState.collectAsStateWithLifecycle()
    var showSortMenu by remember { mutableStateOf(false) }
    var showGenreMenu by remember { mutableStateOf(false) }

    Column(modifier = modifier.fillMaxSize()) {
        // Header & summary
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 20.dp, vertical = 12.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    text = "Library",
                    style = MaterialTheme.typography.headlineSmall,
                    color = FlacifyTextPrimary,
                )
                Surface(
                    color = FlacifyEmerald.copy(alpha = 0.14f),
                    shape = RoundedCornerShape(999.dp),
                    border = BorderStroke(1.dp, FlacifyEmerald.copy(alpha = 0.35f)),
                ) {
                    Text(
                        text = "${state.offlineTrackCount} / ${state.totalCatalogCount} OFFLINE",
                        style = MaterialTheme.typography.labelSmall,
                        color = FlacifyEmeraldBright,
                        modifier = Modifier.padding(horizontal = 10.dp, vertical = 4.dp),
                    )
                }
            }

            if (state.totalCatalogCount > 0) {
                val usedBytes = state.storageSummary.audioBytes + state.storageSummary.coverBytes
                Text(
                    text = "${state.tracks.size} shown · ${FormatUtils.formatBytes(usedBytes)} used · ${FormatUtils.formatBytes(state.storageSummary.availableBytes)} free",
                    style = MaterialTheme.typography.bodySmall,
                    fontFamily = FontFamily.Monospace,
                    color = FlacifyTextMuted,
                )
            }
        }

        if (state.totalCatalogCount == 0) {
            Box(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(24.dp),
                contentAlignment = Alignment.Center,
            ) {
                Card(
                    colors = CardDefaults.cardColors(containerColor = FlacifyCardSurface),
                    border = BorderStroke(1.dp, FlacifyBorder),
                    shape = RoundedCornerShape(20.dp),
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Column(
                        modifier = Modifier.padding(22.dp),
                        horizontalAlignment = Alignment.CenterHorizontally,
                        verticalArrangement = Arrangement.spacedBy(12.dp),
                    ) {
                        Icon(
                            imageVector = Icons.Rounded.LibraryMusic,
                            contentDescription = null,
                            tint = FlacifySkyAccent,
                            modifier = Modifier.size(40.dp),
                        )
                        Text(
                            text = "No Tracks Cached Yet",
                            style = MaterialTheme.typography.titleMedium,
                            color = FlacifyTextPrimary,
                        )
                        Text(
                            text = "Pair with your Flacify PC in the Sync tab and refresh your catalog to browse all lossless tracks offline.",
                            style = MaterialTheme.typography.bodySmall,
                            color = FlacifyTextMuted,
                        )
                        Button(
                            onClick = onOpenSyncTab,
                            colors = ButtonDefaults.buttonColors(
                                containerColor = FlacifyEmerald,
                                contentColor = Color(0xFF032219),
                            ),
                        ) {
                            Text("Open PC Sync & Pair")
                        }
                    }
                }
            }
            return
        }

        // Instant Search Box
        OutlinedTextField(
            value = state.searchQuery,
            onValueChange = viewModel::updateSearch,
            placeholder = { Text("Search tracks, artists, albums, genre...", color = FlacifyTextMuted) },
            leadingIcon = {
                Icon(
                    imageVector = Icons.Rounded.Search,
                    contentDescription = null,
                    tint = FlacifyTextMuted,
                )
            },
            trailingIcon = {
                if (state.searchQuery.isNotEmpty()) {
                    IconButton(onClick = { viewModel.updateSearch("") }) {
                        Icon(
                            imageVector = Icons.Rounded.Close,
                            contentDescription = "Clear search",
                            tint = FlacifyTextMuted,
                        )
                    }
                }
            },
            singleLine = true,
            colors = OutlinedTextFieldDefaults.colors(
                focusedBorderColor = FlacifyEmerald,
                unfocusedBorderColor = FlacifyBorder,
                focusedTextColor = FlacifyTextPrimary,
                unfocusedTextColor = FlacifyTextPrimary,
                cursorColor = FlacifyEmeraldBright,
            ),
            shape = RoundedCornerShape(14.dp),
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 20.dp),
        )

        // Filter & Sort Strip
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .horizontalScroll(rememberScrollState())
                .padding(horizontal = 20.dp, vertical = 8.dp),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            TrackSyncFilter.entries.forEach { filter ->
                val selected = state.syncFilter == filter
                FilterChip(
                    selected = selected,
                    onClick = { viewModel.setSyncFilter(filter) },
                    label = { Text(filter.label) },
                    colors = FilterChipDefaults.filterChipColors(
                        selectedContainerColor = FlacifyEmerald.copy(alpha = 0.2f),
                        selectedLabelColor = FlacifyEmeraldBright,
                        containerColor = FlacifyCardSurface,
                        labelColor = FlacifyTextMuted,
                    ),
                    border = FilterChipDefaults.filterChipBorder(
                        enabled = true,
                        selected = selected,
                        borderColor = FlacifyBorder,
                        selectedBorderColor = FlacifyEmerald.copy(alpha = 0.45f),
                    ),
                )
            }

            // Sort dropdown chip
            Box {
                FilterChip(
                    selected = false,
                    onClick = { showSortMenu = true },
                    label = { Text("Sort: ${state.sortOption.label}") },
                    leadingIcon = {
                        Icon(
                            imageVector = Icons.AutoMirrored.Rounded.Sort,
                            contentDescription = null,
                            modifier = Modifier.size(16.dp),
                        )
                    },
                    colors = FilterChipDefaults.filterChipColors(
                        containerColor = FlacifyCardSurface,
                        labelColor = FlacifySkyAccent,
                        iconColor = FlacifySkyAccent,
                    ),
                    border = FilterChipDefaults.filterChipBorder(
                        enabled = true,
                        selected = false,
                        borderColor = FlacifyBorder,
                    ),
                )
                DropdownMenu(
                    expanded = showSortMenu,
                    onDismissRequest = { showSortMenu = false },
                    containerColor = FlacifyElevatedSurface,
                ) {
                    TrackSortOption.entries.forEach { opt ->
                        DropdownMenuItem(
                            text = {
                                Text(
                                    text = opt.label,
                                    color = if (opt == state.sortOption) FlacifyEmeraldBright else FlacifyTextPrimary,
                                )
                            },
                            onClick = {
                                showSortMenu = false
                                viewModel.setSortOption(opt)
                            },
                        )
                    }
                }
            }

            // Genre dropdown chip
            if (state.availableGenres.isNotEmpty()) {
                Box {
                    val genreSelected = state.selectedGenre != null
                    FilterChip(
                        selected = genreSelected,
                        onClick = { showGenreMenu = true },
                        label = { Text(state.selectedGenre ?: "All Genres") },
                        trailingIcon = {
                            Icon(
                                imageVector = Icons.Rounded.ArrowDropDown,
                                contentDescription = null,
                                modifier = Modifier.size(16.dp),
                            )
                        },
                        colors = FilterChipDefaults.filterChipColors(
                            selectedContainerColor = FlacifyEmerald.copy(alpha = 0.2f),
                            selectedLabelColor = FlacifyEmeraldBright,
                            containerColor = FlacifyCardSurface,
                            labelColor = FlacifyTextMuted,
                        ),
                        border = FilterChipDefaults.filterChipBorder(
                            enabled = true,
                            selected = genreSelected,
                            borderColor = FlacifyBorder,
                            selectedBorderColor = FlacifyEmerald.copy(alpha = 0.45f),
                        ),
                    )
                    DropdownMenu(
                        expanded = showGenreMenu,
                        onDismissRequest = { showGenreMenu = false },
                        containerColor = FlacifyElevatedSurface,
                    ) {
                        DropdownMenuItem(
                            text = { Text("All Genres", color = FlacifyTextPrimary) },
                            onClick = {
                                showGenreMenu = false
                                viewModel.setSelectedGenre(null)
                            },
                        )
                        state.availableGenres.forEach { genre ->
                            DropdownMenuItem(
                                text = {
                                    Text(
                                        text = genre,
                                        color = if (genre == state.selectedGenre) FlacifyEmeraldBright else FlacifyTextPrimary,
                                    )
                                },
                                onClick = {
                                    showGenreMenu = false
                                    viewModel.setSelectedGenre(genre)
                                },
                            )
                        }
                    }
                }
            }
        }

        if (state.tracks.isEmpty()) {
            Box(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(24.dp),
                contentAlignment = Alignment.Center,
            ) {
                Text(
                    text = "No matching tracks for current filters.",
                    style = MaterialTheme.typography.bodyMedium,
                    color = FlacifyTextMuted,
                )
            }
            return
        }

        val offlineQueue = remember(state.tracks) {
            state.tracks.filter {
                it.syncStatus == TrackSyncStatus.SYNCED && !it.localFilePath.isNullOrBlank()
            }
        }

        LazyColumn(
            contentPadding = PaddingValues(bottom = 20.dp),
            modifier = Modifier.fillMaxSize(),
        ) {
            itemsIndexed(
                items = state.tracks,
                key = { _, track -> track.id },
                contentType = { _, _ -> "library_track" },
            ) { _, track ->
                val isOffline = track.syncStatus == TrackSyncStatus.SYNCED &&
                    !track.localFilePath.isNullOrBlank()
                TrackRowItem(
                    title = track.title,
                    artist = track.artist,
                    album = track.album,
                    qualityBadge = track.qualityBadge,
                    durationMs = track.durationMs,
                    fileSizeBytes = track.localFileSize.takeIf { it > 0L } ?: track.remoteFileSize,
                    isOfflineReady = isOffline,
                    localCoverPath = track.localCoverPath,
                    remoteCoverUrl = track.coverUrl,
                    activeBaseUrl = state.activeBaseUrl,
                    onClick = {
                        val queueIdx = offlineQueue.indexOfFirst { it.id == track.id }.coerceAtLeast(0)
                        onTrackSelected(offlineQueue, queueIdx, track.title, isOffline)
                    },
                )
                HorizontalDivider(
                    color = FlacifyBorder.copy(alpha = 0.5f),
                    thickness = 0.5.dp,
                    modifier = Modifier.padding(horizontal = 16.dp),
                )
            }
        }
    }
}
