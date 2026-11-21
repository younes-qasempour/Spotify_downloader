package com.flacify.android.ui.playlists

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.QueueMusic
import androidx.compose.material.icons.rounded.Close
import androidx.compose.material.icons.rounded.Download
import androidx.compose.material.icons.rounded.Refresh
import androidx.compose.material.icons.rounded.Search
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.scale
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.flacify.android.sync.PlaylistSyncSummary
import com.flacify.android.ui.components.ArtworkImage
import com.flacify.android.ui.library.FormatUtils
import com.flacify.android.ui.theme.FlacifyBorder
import com.flacify.android.ui.theme.FlacifyCardSurface
import com.flacify.android.ui.theme.FlacifyDanger
import com.flacify.android.ui.theme.FlacifyElevatedSurface
import com.flacify.android.ui.theme.FlacifyEmerald
import com.flacify.android.ui.theme.FlacifyEmeraldBright
import com.flacify.android.ui.theme.FlacifySkyAccent
import com.flacify.android.ui.theme.FlacifyTextMuted
import com.flacify.android.ui.theme.FlacifyTextPrimary

@Composable
fun PlaylistsScreen(
    viewModel: PlaylistsViewModel,
    onPlaylistClick: (String) -> Unit,
    onOpenSyncTab: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val state by viewModel.uiState.collectAsStateWithLifecycle()

    Column(
        modifier = modifier.fillMaxSize(),
    ) {
        // Header row
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 20.dp, vertical = 12.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = "Playlists",
                    style = MaterialTheme.typography.headlineSmall,
                    color = FlacifyTextPrimary,
                )
                Text(
                    text = if (state.totalCatalogCount > 0) {
                        "${state.totalCatalogCount} synced/PC playlists"
                    } else {
                        "100% offline lossless FLAC collections"
                    },
                    style = MaterialTheme.typography.bodySmall,
                    color = FlacifyTextMuted,
                )
            }

            if (state.isPaired) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    val enabledCount = state.playlists.count { it.playlist.syncEnabled }
                    if (enabledCount > 0 && !state.syncProgress.isRunning) {
                        IconButton(onClick = { viewModel.startSync() }) {
                            Icon(
                                imageVector = Icons.Rounded.Download,
                                contentDescription = "Sync enabled playlists",
                                tint = FlacifyEmeraldBright,
                            )
                        }
                    }
                    IconButton(
                        onClick = { viewModel.refreshCatalog() },
                        enabled = !state.isRefreshing,
                    ) {
                        if (state.isRefreshing) {
                            CircularProgressIndicator(
                                strokeWidth = 2.dp,
                                color = FlacifySkyAccent,
                                modifier = Modifier.size(18.dp),
                            )
                        } else {
                            Icon(
                                imageVector = Icons.Rounded.Refresh,
                                contentDescription = "Refresh playlists",
                                tint = FlacifySkyAccent,
                            )
                        }
                    }
                }
            }
        }

        state.errorMessage?.let { err ->
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 20.dp, vertical = 4.dp)
                    .background(FlacifyDanger.copy(alpha = 0.12f), RoundedCornerShape(12.dp))
                    .padding(horizontal = 12.dp, vertical = 8.dp),
            ) {
                Text(
                    text = err,
                    style = MaterialTheme.typography.bodySmall,
                    color = FlacifyDanger,
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
                            imageVector = Icons.AutoMirrored.Rounded.QueueMusic,
                            contentDescription = null,
                            tint = FlacifySkyAccent,
                            modifier = Modifier.size(40.dp),
                        )
                        Text(
                            text = if (state.isPaired) {
                                "No Playlists Cached Yet"
                            } else {
                                "Pair with Flacify PC First"
                            },
                            style = MaterialTheme.typography.titleMedium,
                            color = FlacifyTextPrimary,
                        )
                        Text(
                            text = if (state.isPaired) {
                                "Tap Refresh above or Sync to pull your playlists and FLAC tracks."
                            } else {
                                "Connect to your PC in the Sync tab to view playlists and download original FLAC tracks for offline playback."
                            },
                            style = MaterialTheme.typography.bodySmall,
                            color = FlacifyTextMuted,
                        )
                        Button(
                            onClick = if (state.isPaired) {
                                { viewModel.refreshCatalog() }
                            } else {
                                onOpenSyncTab
                            },
                            colors = ButtonDefaults.buttonColors(
                                containerColor = FlacifyEmerald,
                                contentColor = Color(0xFF032219),
                            ),
                        ) {
                            Text(if (state.isPaired) "Refresh Catalog Now" else "Open PC Sync & Pair")
                        }
                    }
                }
            }
            return
        }

        // Search & Keep-Offline chip
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 20.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            OutlinedTextField(
                value = state.searchQuery,
                onValueChange = viewModel::updateSearch,
                placeholder = { Text("Search playlists...", color = FlacifyTextMuted) },
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
                modifier = Modifier.weight(1f),
            )
        }

        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 20.dp, vertical = 6.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            FilterChip(
                selected = state.onlyKeepOffline,
                onClick = { viewModel.toggleOnlyKeepOffline() },
                label = { Text("Keep Offline Only") },
                colors = FilterChipDefaults.filterChipColors(
                    selectedContainerColor = FlacifyEmerald.copy(alpha = 0.2f),
                    selectedLabelColor = FlacifyEmeraldBright,
                    containerColor = FlacifyCardSurface,
                    labelColor = FlacifyTextMuted,
                ),
                border = FilterChipDefaults.filterChipBorder(
                    enabled = true,
                    selected = state.onlyKeepOffline,
                    borderColor = FlacifyBorder,
                    selectedBorderColor = FlacifyEmerald.copy(alpha = 0.45f),
                ),
            )
            Text(
                text = "${state.playlists.size} shown",
                style = MaterialTheme.typography.bodySmall,
                color = FlacifyTextMuted,
            )
        }

        LazyVerticalGrid(
            columns = GridCells.Adaptive(minSize = 158.dp),
            contentPadding = PaddingValues(start = 20.dp, end = 20.dp, top = 6.dp, bottom = 20.dp),
            horizontalArrangement = Arrangement.spacedBy(12.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
            modifier = Modifier.fillMaxSize(),
        ) {
            items(
                items = state.playlists,
                key = { it.playlist.id },
            ) { summary ->
                PlaylistGridCard(
                    summary = summary,
                    activeBaseUrl = state.activeBaseUrl,
                    onClick = { onPlaylistClick(summary.playlist.id) },
                    onToggleSync = { enabled ->
                        viewModel.togglePlaylistSync(summary.playlist.id, enabled)
                    },
                )
            }
        }
    }
}

@Composable
private fun PlaylistGridCard(
    summary: PlaylistSyncSummary,
    activeBaseUrl: String,
    onClick: () -> Unit,
    onToggleSync: (Boolean) -> Unit,
) {
    val pl = summary.playlist
    val allOffline = pl.pcDownloadedTracks > 0 && summary.syncedOnPhoneCount >= pl.pcDownloadedTracks

    Card(
        colors = CardDefaults.cardColors(containerColor = FlacifyCardSurface),
        border = BorderStroke(
            1.dp,
            if (pl.syncEnabled) FlacifyEmerald.copy(alpha = 0.4f) else FlacifyBorder,
        ),
        shape = RoundedCornerShape(18.dp),
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick),
    ) {
        Column(modifier = Modifier.padding(12.dp)) {
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .aspectRatio(1f),
            ) {
                ArtworkImage(
                    localPath = pl.localCoverPath,
                    remoteOrRelativeUrl = pl.coverUrl.ifBlank { pl.remoteCoverUrl },
                    activeBaseUrl = activeBaseUrl,
                    contentDescription = pl.name,
                    cornerRadius = 14.dp,
                    fallbackIcon = Icons.AutoMirrored.Rounded.QueueMusic,
                    modifier = Modifier.fillMaxSize(),
                )

                Surface(
                    color = if (allOffline) FlacifyEmerald.copy(alpha = 0.88f) else Color.Black.copy(alpha = 0.72f),
                    shape = RoundedCornerShape(999.dp),
                    modifier = Modifier
                        .align(Alignment.TopEnd)
                        .padding(8.dp),
                ) {
                    Text(
                        text = if (allOffline) "OFFLINE" else "${summary.syncedOnPhoneCount}/${pl.pcDownloadedTracks}",
                        style = MaterialTheme.typography.labelSmall,
                        color = if (allOffline) Color(0xFF032219) else FlacifyTextPrimary,
                        modifier = Modifier.padding(horizontal = 8.dp, vertical = 3.dp),
                    )
                }
            }

            Spacer(modifier = Modifier.height(10.dp))

            Text(
                text = pl.name,
                style = MaterialTheme.typography.titleMedium,
                color = FlacifyTextPrimary,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )

            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.SpaceBetween,
            ) {
                Column(modifier = Modifier.weight(1f)) {
                    Text(
                        text = "${pl.totalTracks} tracks",
                        style = MaterialTheme.typography.bodySmall,
                        color = FlacifyTextMuted,
                    )
                    Text(
                        text = FormatUtils.formatBytes(summary.totalNeededBytes),
                        style = MaterialTheme.typography.bodySmall,
                        fontFamily = FontFamily.Monospace,
                        color = FlacifySkyAccent,
                    )
                }
                Switch(
                    checked = pl.syncEnabled,
                    onCheckedChange = onToggleSync,
                    colors = SwitchDefaults.colors(
                        checkedThumbColor = Color(0xFF032219),
                        checkedTrackColor = FlacifyEmerald,
                        uncheckedThumbColor = FlacifyTextMuted,
                        uncheckedTrackColor = FlacifyElevatedSurface,
                    ),
                    modifier = Modifier.scale(0.8f),
                )
            }
        }
    }
}
