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
import androidx.compose.material.icons.rounded.Sync
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.unit.dp
import com.flacify.android.ui.theme.FlacifyBorder
import com.flacify.android.ui.theme.FlacifyCardSurface
import com.flacify.android.ui.theme.FlacifyElevatedSurface
import com.flacify.android.ui.theme.FlacifyEmerald
import com.flacify.android.ui.theme.FlacifyEmeraldBright
import com.flacify.android.ui.theme.FlacifySkyAccent
import com.flacify.android.ui.theme.FlacifyTextMuted
import com.flacify.android.ui.theme.FlacifyTextPrimary

@Composable
fun PlaylistsScreen(modifier: Modifier = Modifier) {
    StarterSectionLayout(
        title = "Offline Playlists",
        subtitle = "Keep selected Spotify & PC playlists downloaded on your phone in original bit-perfect FLAC.",
        badgeText = "STEP 2.3–2.4",
        icon = Icons.AutoMirrored.Rounded.QueueMusic,
        detailsTitle = "Zero-Duplicate Offline Sync",
        detailsBody = "Shared songs across playlists are stored once by canonical ID and indexed locally in Room for instant 100% offline playback.",
        modifier = modifier,
    )
}

@Composable
fun LibraryScreen(modifier: Modifier = Modifier) {
    StarterSectionLayout(
        title = "Offline Library",
        subtitle = "Browse thousands of lossless tracks by title, artist, album, or genre without touching mobile data.",
        badgeText = "FLAC 16 / 24-BIT",
        icon = Icons.Rounded.LibraryMusic,
        detailsTitle = "Media3 Lossless Playback Ready",
        detailsBody = "Background ExoPlayer service, mini player, and offline .lrc synced lyrics will light up here once paired.",
        modifier = modifier,
    )
}

@Composable
fun SyncScreen(modifier: Modifier = Modifier) {
    StarterSectionLayout(
        title = "Connect to Flacify PC",
        subtitle = "Pair with your PC over Wi-Fi, Tailscale, or Android Emulator (10.0.2.2:8765) via QR scan or mDNS.",
        badgeText = "NEXT: STEP 2.2",
        icon = Icons.Rounded.Sync,
        detailsTitle = "Wi-Fi Sync & Android Share Ready",
        detailsBody = "Open Flacify Settings -> Mobile Sync on your PC to view your pairing QR code. QR pairing, _flacify._tcp discovery, and resumable transfers arrive next.",
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
            }
        }
    }
}
