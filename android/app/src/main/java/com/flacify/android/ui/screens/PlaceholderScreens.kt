package com.flacify.android.ui.screens

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.QueueMusic
import androidx.compose.material.icons.rounded.GraphicEq
import androidx.compose.material.icons.rounded.LibraryMusic
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.unit.dp
import com.flacify.android.ui.sync.SyncUiState
import com.flacify.android.ui.theme.FlacifyBorder
import com.flacify.android.ui.theme.FlacifyCardSurface
import com.flacify.android.ui.theme.FlacifyElevatedSurface
import com.flacify.android.ui.theme.FlacifyEmerald
import com.flacify.android.ui.theme.FlacifyEmeraldBright
import com.flacify.android.ui.theme.FlacifySkyAccent
import com.flacify.android.ui.theme.FlacifyTextMuted
import com.flacify.android.ui.theme.FlacifyTextPrimary

@Composable
fun PlaylistsScreen(
    syncState: SyncUiState,
    onOpenSyncTab: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val paired = syncState.connectionConfig.isPaired
    val pcName = syncState.syncInfo?.deviceName?.ifBlank { syncState.connectionConfig.deviceName }
        ?: syncState.connectionConfig.deviceName.ifBlank { "Flacify PC" }
    val plCount = syncState.syncInfo?.savedPlaylistsCount ?: 0

    StarterSectionLayout(
        title = "Offline Playlists",
        subtitle = "Keep selected Spotify & PC playlists downloaded on your phone in original bit-perfect FLAC.",
        badgeText = if (paired) "NEXT: STEP 2.3" else "PAIR FIRST",
        icon = Icons.AutoMirrored.Rounded.QueueMusic,
        detailsTitle = if (paired) "Paired with $pcName" else "Connect to Your PC First",
        detailsBody = if (paired) {
            "$plCount playlists available on $pcName. Offline Room database & resumable FLAC sync engine arrive in Step 2.3."
        } else {
            "Pair with Flacify Desktop in the Sync tab so we can load your playlists and sync original lossless FLAC tracks."
        },
        showSyncAction = !paired,
        onOpenSyncTab = onOpenSyncTab,
        modifier = modifier,
    )
}

@Composable
fun LibraryScreen(
    syncState: SyncUiState,
    onOpenSyncTab: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val paired = syncState.connectionConfig.isPaired
    val trackCount = syncState.syncInfo?.libraryStats?.totalTracks ?: 0
    val sizeStr = syncState.syncInfo?.libraryStats?.sizeStr ?: ""

    StarterSectionLayout(
        title = "Offline Library",
        subtitle = "Browse thousands of lossless tracks by title, artist, album, or genre without touching mobile data.",
        badgeText = "FLAC 16 / 24-BIT",
        icon = Icons.Rounded.LibraryMusic,
        detailsTitle = if (paired && trackCount > 0) {
            "$trackCount Lossless Tracks on PC ($sizeStr)"
        } else {
            "Media3 Lossless Playback Ready"
        },
        detailsBody = if (paired) {
            "Deduplicated Room storage + instant offline search & Media3 player arrive in Steps 2.3–2.5."
        } else {
            "Pair with your PC in the Sync tab to browse and download your lossless library."
        },
        showSyncAction = !paired,
        onOpenSyncTab = onOpenSyncTab,
        modifier = modifier,
    )
}

@Composable
private fun StarterSectionLayout(
    title: String,
    subtitle: String,
    badgeText: String,
    icon: ImageVector,
    detailsTitle: String,
    detailsBody: String,
    showSyncAction: Boolean,
    onOpenSyncTab: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Column(
        modifier = modifier
            .fillMaxSize()
            .padding(horizontal = 20.dp, vertical = 16.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                text = title,
                style = MaterialTheme.typography.headlineSmall,
                color = FlacifyTextPrimary,
            )
            Surface(
                color = FlacifyEmerald.copy(alpha = 0.14f),
                shape = RoundedCornerShape(999.dp),
                border = BorderStroke(1.dp, FlacifyEmerald.copy(alpha = 0.35f)),
            ) {
                Text(
                    text = badgeText,
                    style = MaterialTheme.typography.labelSmall,
                    color = FlacifyEmeraldBright,
                    modifier = Modifier.padding(horizontal = 10.dp, vertical = 4.dp),
                )
            }
        }

        Text(
            text = subtitle,
            style = MaterialTheme.typography.bodyMedium,
            color = FlacifyTextMuted,
        )

        Card(
            colors = CardDefaults.cardColors(containerColor = FlacifyCardSurface),
            border = BorderStroke(1.dp, FlacifyBorder),
            shape = RoundedCornerShape(20.dp),
            modifier = Modifier.fillMaxWidth(),
        ) {
            Column(
                modifier = Modifier.padding(20.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(12.dp),
                ) {
                    Box(
                        modifier = Modifier
                            .size(44.dp)
                            .background(FlacifyElevatedSurface, RoundedCornerShape(12.dp)),
                        contentAlignment = Alignment.Center,
                    ) {
                        Icon(
                            imageVector = icon,
                            contentDescription = null,
                            tint = FlacifySkyAccent,
                            modifier = Modifier.size(22.dp),
                        )
                    }
                    Column {
                        Text(
                            text = detailsTitle,
                            style = MaterialTheme.typography.titleMedium,
                            color = FlacifyTextPrimary,
                        )
                        Row(
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.spacedBy(6.dp),
                        ) {
                            Icon(
                                imageVector = Icons.Rounded.GraphicEq,
                                contentDescription = null,
                                tint = FlacifyEmeraldBright,
                                modifier = Modifier.size(14.dp),
                            )
                            Text(
                                text = "Original FLAC preserved on device",
                                style = MaterialTheme.typography.bodySmall,
                                color = FlacifyEmeraldBright,
                            )
                        }
                    }
                }

                Spacer(modifier = Modifier.height(2.dp))

                Text(
                    text = detailsBody,
                    style = MaterialTheme.typography.bodyMedium,
                    color = FlacifyTextMuted,
                )

                if (showSyncAction) {
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
    }
}
