package com.flacify.android.ui.playlists

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.ArrowBack
import androidx.compose.material.icons.automirrored.rounded.QueueMusic
import androidx.compose.material.icons.rounded.Close
import androidx.compose.material.icons.rounded.DeleteOutline
import androidx.compose.material.icons.rounded.Download
import androidx.compose.material.icons.rounded.Search
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.flacify.android.data.db.TrackEntity
import com.flacify.android.ui.components.ArtworkImage
import com.flacify.android.ui.components.TrackRowItem
import com.flacify.android.ui.library.FormatUtils
import com.flacify.android.ui.theme.FlacifyBorder
import com.flacify.android.ui.theme.FlacifyCanvas
import com.flacify.android.ui.theme.FlacifyCardSurface
import com.flacify.android.ui.theme.FlacifyElevatedSurface
import com.flacify.android.ui.theme.FlacifyEmerald
import com.flacify.android.ui.theme.FlacifyEmeraldBright
import com.flacify.android.ui.theme.FlacifySkyAccent
import com.flacify.android.ui.theme.FlacifyTextMuted
import com.flacify.android.ui.theme.FlacifyTextPrimary

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun PlaylistDetailScreen(
    viewModel: PlaylistDetailViewModel,
    onBack: () -> Unit,
    onTrackSelected: (queue: List<TrackEntity>, startIndex: Int, title: String, isOffline: Boolean) -> Unit,
    modifier: Modifier = Modifier,
) {
    val state by viewModel.uiState.collectAsStateWithLifecycle()
    val pl = state.playlist

    Column(
        modifier = modifier
            .fillMaxSize()
            .background(FlacifyCanvas),
    ) {
        TopAppBar(
            title = {
                Text(
                    text = pl?.name ?: "Playlist",
                    style = MaterialTheme.typography.titleMedium,
                    color = FlacifyTextPrimary,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            },
            navigationIcon = {
                IconButton(onClick = onBack) {
                    Icon(
                        imageVector = Icons.AutoMirrored.Rounded.ArrowBack,
                        contentDescription = "Back",
                        tint = FlacifyTextPrimary,
                    )
                }
            },
            actions = {
                if (state.syncedOnPhoneCount > 0 && !state.syncProgress.isRunning) {
                    IconButton(onClick = { viewModel.offloadPlaylist() }) {
                        Icon(
                            imageVector = Icons.Rounded.DeleteOutline,
                            contentDescription = "Remove from phone",
                            tint = FlacifyTextMuted,
                        )
                    }
                }
            },
            colors = TopAppBarDefaults.topAppBarColors(containerColor = FlacifyCanvas),
        )

        if (pl == null) {
            Box(
                modifier = Modifier.fillMaxSize(),
                contentAlignment = Alignment.Center,
            ) {
                Text(
                    text = "Playlist not found in offline catalog.",
                    style = MaterialTheme.typography.bodyMedium,
                    color = FlacifyTextMuted,
                )
            }
            return
        }

        // Header summary card
        Card(
            colors = CardDefaults.cardColors(containerColor = FlacifyCardSurface),
            border = BorderStroke(1.dp, FlacifyBorder),
            shape = RoundedCornerShape(18.dp),
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 16.dp, vertical = 8.dp),
        ) {
            Column(
                modifier = Modifier.padding(14.dp),
                verticalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(14.dp),
                ) {
                    ArtworkImage(
                        localPath = pl.localCoverPath,
                        remoteOrRelativeUrl = pl.coverUrl.ifBlank { pl.remoteCoverUrl },
                        activeBaseUrl = state.activeBaseUrl,
                        contentDescription = pl.name,
                        cornerRadius = 14.dp,
                        fallbackIcon = Icons.AutoMirrored.Rounded.QueueMusic,
                        modifier = Modifier.size(72.dp),
                    )
                    Column(modifier = Modifier.weight(1f)) {
                        Text(
                            text = pl.name,
                            style = MaterialTheme.typography.titleMedium,
                            color = FlacifyTextPrimary,
                            maxLines = 2,
                            overflow = TextOverflow.Ellipsis,
                        )
                        Text(
                            text = "${state.syncedOnPhoneCount}/${pl.pcDownloadedTracks} tracks offline (${state.totalItemCount} total)",
                            style = MaterialTheme.typography.bodySmall,
                            color = if (state.syncedOnPhoneCount >= pl.pcDownloadedTracks && pl.pcDownloadedTracks > 0) {
                                FlacifyEmeraldBright
                            } else {
                                FlacifyTextMuted
                            },
                        )
                        if (state.totalNeededBytes > 0L) {
                            Text(
                                text = "Lossless size: ${FormatUtils.formatBytes(state.totalNeededBytes)}",
                                style = MaterialTheme.typography.bodySmall,
                                fontFamily = FontFamily.Monospace,
                                color = FlacifySkyAccent,
                            )
                        }
                    }
                }

                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text(
                        text = "Keep playlist offline",
                        style = MaterialTheme.typography.bodyMedium,
                        color = FlacifyTextPrimary,
                    )
                    Switch(
                        checked = pl.syncEnabled,
                        onCheckedChange = { viewModel.toggleSyncEnabled(it) },
                        colors = SwitchDefaults.colors(
                            checkedThumbColor = Color(0xFF032219),
                            checkedTrackColor = FlacifyEmerald,
                            uncheckedThumbColor = FlacifyTextMuted,
                            uncheckedTrackColor = FlacifyElevatedSurface,
                        ),
                    )
                }

                if (state.isPaired && state.syncedOnPhoneCount < pl.pcDownloadedTracks && !state.syncProgress.isRunning) {
                    Button(
                        onClick = { viewModel.syncPlaylistNow() },
                        colors = ButtonDefaults.buttonColors(
                            containerColor = FlacifyEmerald,
                            contentColor = Color(0xFF032219),
                        ),
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Icon(
                            imageVector = Icons.Rounded.Download,
                            contentDescription = null,
                            modifier = Modifier.size(16.dp),
                        )
                        Spacer(modifier = Modifier.width(6.dp))
                        Text("Sync Missing Tracks (FLAC)")
                    }
                }

                state.feedbackMessage?.let { msg ->
                    Text(
                        text = msg,
                        style = MaterialTheme.typography.bodySmall,
                        color = FlacifyEmeraldBright,
                    )
                }
            }
        }

        // In-playlist search
        OutlinedTextField(
            value = state.searchQuery,
            onValueChange = viewModel::updateSearch,
            placeholder = { Text("Filter tracks in playlist...", color = FlacifyTextMuted) },
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
                .padding(horizontal = 16.dp, vertical = 4.dp),
        )

        val offlineQueue = state.items.filter { it.isOfflineReady }.mapNotNull { it.track }

        LazyColumn(
            contentPadding = PaddingValues(bottom = 20.dp),
            modifier = Modifier.fillMaxSize(),
        ) {
            itemsIndexed(
                items = state.items,
                key = { _, item -> "${item.entry.playlistId}_${item.entry.position}" },
                contentType = { _, _ -> "playlist_track" },
            ) { idx, item ->
                val tr = item.track
                val title = tr?.title?.ifBlank { item.entry.title } ?: item.entry.title
                val artist = tr?.artist?.ifBlank { item.entry.artist } ?: item.entry.artist
                val album = tr?.album?.ifBlank { item.entry.album } ?: item.entry.album
                val duration = tr?.durationMs?.takeIf { it > 0L } ?: item.entry.durationMs
                val badge = tr?.qualityBadge?.ifBlank { "FLAC" }
                    ?: if (item.entry.pcDownloaded) "PC" else "PENDING"
                val sizeBytes = tr?.let { it.localFileSize.takeIf { s -> s > 0L } ?: it.remoteFileSize } ?: 0L

                TrackRowItem(
                    title = title,
                    artist = artist,
                    album = album,
                    qualityBadge = badge,
                    durationMs = duration,
                    fileSizeBytes = sizeBytes,
                    isOfflineReady = item.isOfflineReady,
                    localCoverPath = tr?.localCoverPath,
                    remoteCoverUrl = tr?.coverUrl,
                    activeBaseUrl = state.activeBaseUrl,
                    trackIndexLabel = "${idx + 1}",
                    onClick = {
                        val queueIdx = if (tr != null) {
                            offlineQueue.indexOfFirst { it.id == tr.id }.coerceAtLeast(0)
                        } else {
                            0
                        }
                        onTrackSelected(offlineQueue, queueIdx, title, item.isOfflineReady)
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
