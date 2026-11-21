package com.flacify.android.ui.player

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Album
import androidx.compose.material.icons.rounded.Pause
import androidx.compose.material.icons.rounded.PlayArrow
import androidx.compose.material.icons.rounded.SkipNext
import androidx.compose.material.icons.rounded.SkipPrevious
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.flacify.android.player.PlayerUiState
import com.flacify.android.ui.components.ArtworkImage
import com.flacify.android.ui.components.QualityBadgePill
import com.flacify.android.ui.theme.FlacifyBorder
import com.flacify.android.ui.theme.FlacifyCardSurface
import com.flacify.android.ui.theme.FlacifyElevatedSurface
import com.flacify.android.ui.theme.FlacifyEmeraldBright
import com.flacify.android.ui.theme.FlacifyTextMuted
import com.flacify.android.ui.theme.FlacifyTextPrimary

@Composable
fun MiniPlayerBar(
    playerState: PlayerUiState,
    activeBaseUrl: String,
    onExpand: () -> Unit,
    onTogglePlayPause: () -> Unit,
    onPrevious: () -> Unit,
    onNext: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val track = playerState.currentTrack ?: return
    val fraction = if (playerState.durationMs > 0L) {
        (playerState.positionMs.toFloat() / playerState.durationMs.toFloat()).coerceIn(0f, 1f)
    } else {
        0f
    }

    Surface(
        color = FlacifyElevatedSurface,
        border = BorderStroke(1.dp, FlacifyBorder),
        shape = RoundedCornerShape(topStart = 16.dp, topEnd = 16.dp),
        modifier = modifier
            .fillMaxWidth()
            .clickable(onClick = onExpand),
    ) {
        Column(modifier = Modifier.fillMaxWidth()) {
            LinearProgressIndicator(
                progress = { fraction },
                color = FlacifyEmeraldBright,
                trackColor = FlacifyCardSurface,
                modifier = Modifier
                    .fillMaxWidth()
                    .height(2.5.dp),
            )

            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 12.dp, vertical = 8.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                ArtworkImage(
                    localPath = track.localCoverPath,
                    remoteOrRelativeUrl = track.coverUrl,
                    activeBaseUrl = activeBaseUrl,
                    contentDescription = track.title,
                    cornerRadius = 10.dp,
                    fallbackIcon = Icons.Rounded.Album,
                    modifier = Modifier.size(44.dp),
                )

                Spacer(modifier = Modifier.width(10.dp))

                Column(
                    modifier = Modifier.weight(1f),
                    verticalArrangement = Arrangement.spacedBy(2.dp),
                ) {
                    Text(
                        text = track.title.ifBlank { "Untitled Track" },
                        style = MaterialTheme.typography.titleMedium,
                        color = FlacifyTextPrimary,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(6.dp),
                    ) {
                        Text(
                            text = track.artist.ifBlank { "Unknown Artist" },
                            style = MaterialTheme.typography.bodySmall,
                            color = FlacifyTextMuted,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                            modifier = Modifier.weight(1f, fill = false),
                        )
                        QualityBadgePill(badge = track.qualityBadge)
                    }
                }

                IconButton(onClick = onPrevious) {
                    Icon(
                        imageVector = Icons.Rounded.SkipPrevious,
                        contentDescription = "Previous",
                        tint = FlacifyTextPrimary,
                    )
                }

                IconButton(onClick = onTogglePlayPause) {
                    if (playerState.isBuffering) {
                        CircularProgressIndicator(
                            strokeWidth = 2.dp,
                            color = FlacifyEmeraldBright,
                            modifier = Modifier.size(20.dp),
                        )
                    } else {
                        Icon(
                            imageVector = if (playerState.isPlaying) {
                                Icons.Rounded.Pause
                            } else {
                                Icons.Rounded.PlayArrow
                            },
                            contentDescription = if (playerState.isPlaying) "Pause" else "Play",
                            tint = FlacifyEmeraldBright,
                            modifier = Modifier.size(28.dp),
                        )
                    }
                }

                IconButton(onClick = onNext) {
                    Icon(
                        imageVector = Icons.Rounded.SkipNext,
                        contentDescription = "Next",
                        tint = FlacifyTextPrimary,
                    )
                }
            }
        }
    }
}
