package com.flacify.android.ui.player

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
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.QueueMusic
import androidx.compose.material.icons.rounded.Album
import androidx.compose.material.icons.rounded.Close
import androidx.compose.material.icons.rounded.GraphicEq
import androidx.compose.material.icons.rounded.KeyboardArrowDown
import androidx.compose.material.icons.rounded.Lyrics
import androidx.compose.material.icons.rounded.MusicNote
import androidx.compose.material.icons.rounded.Pause
import androidx.compose.material.icons.rounded.PlayArrow
import androidx.compose.material.icons.rounded.Repeat
import androidx.compose.material.icons.rounded.RepeatOne
import androidx.compose.material.icons.rounded.Shuffle
import androidx.compose.material.icons.rounded.SkipNext
import androidx.compose.material.icons.rounded.SkipPrevious
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Slider
import androidx.compose.material3.SliderDefaults
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import com.flacify.android.data.db.TrackEntity
import com.flacify.android.player.LrcParser
import com.flacify.android.player.ParsedLyrics
import com.flacify.android.player.PlayerUiState
import com.flacify.android.player.RepeatModeState
import com.flacify.android.ui.components.ArtworkImage
import com.flacify.android.ui.components.QualityBadgePill
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

private enum class NowPlayingTab(val label: String) {
    PLAYER("Player"),
    LYRICS("Lyrics"),
    QUEUE("Queue"),
}

@Composable
fun NowPlayingSheet(
    playerState: PlayerUiState,
    activeBaseUrl: String,
    onDismiss: () -> Unit,
    onTogglePlayPause: () -> Unit,
    onPrevious: () -> Unit,
    onNext: () -> Unit,
    onSeek: (Long) -> Unit,
    onToggleShuffle: () -> Unit,
    onCycleRepeat: () -> Unit,
    onSkipToQueueIndex: (Int) -> Unit,
    onRemoveFromQueue: (Int) -> Unit,
) {
    val track = playerState.currentTrack ?: return
    var activeTab by remember { mutableStateOf(NowPlayingTab.PLAYER) }

    Dialog(
        onDismissRequest = onDismiss,
        properties = DialogProperties(usePlatformDefaultWidth = false),
    ) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .background(FlacifyCanvas)
                .padding(horizontal = 20.dp, vertical = 14.dp),
        ) {
            // Top bar
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.SpaceBetween,
            ) {
                IconButton(onClick = onDismiss) {
                    Icon(
                        imageVector = Icons.Rounded.KeyboardArrowDown,
                        contentDescription = "Minimize player",
                        tint = FlacifyTextPrimary,
                        modifier = Modifier.size(28.dp),
                    )
                }

                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    NowPlayingTab.entries.forEach { tab ->
                        val selected = activeTab == tab
                        FilterChip(
                            selected = selected,
                            onClick = { activeTab = tab },
                            label = {
                                val text = if (tab == NowPlayingTab.QUEUE && playerState.queue.isNotEmpty()) {
                                    "Queue (${playerState.queue.size})"
                                } else {
                                    tab.label
                                }
                                Text(text)
                            },
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
                }
            }

            Spacer(modifier = Modifier.height(10.dp))

            when (activeTab) {
                NowPlayingTab.PLAYER -> PlayerMainBody(
                    track = track,
                    playerState = playerState,
                    activeBaseUrl = activeBaseUrl,
                    onTogglePlayPause = onTogglePlayPause,
                    onPrevious = onPrevious,
                    onNext = onNext,
                    onSeek = onSeek,
                    onToggleShuffle = onToggleShuffle,
                    onCycleRepeat = onCycleRepeat,
                    onOpenLyrics = { activeTab = NowPlayingTab.LYRICS },
                    modifier = Modifier.weight(1f),
                )

                NowPlayingTab.LYRICS -> LyricsBody(
                    parsedLyrics = playerState.parsedLyrics,
                    positionMs = playerState.positionMs,
                    onSeekToLine = onSeek,
                    modifier = Modifier.weight(1f),
                )

                NowPlayingTab.QUEUE -> QueueBody(
                    queue = playerState.queue,
                    currentIndex = playerState.currentIndex,
                    activeBaseUrl = activeBaseUrl,
                    onSelectIndex = onSkipToQueueIndex,
                    onRemoveIndex = onRemoveFromQueue,
                    modifier = Modifier.weight(1f),
                )
            }
        }
    }
}

@Composable
private fun PlayerMainBody(
    track: TrackEntity,
    playerState: PlayerUiState,
    activeBaseUrl: String,
    onTogglePlayPause: () -> Unit,
    onPrevious: () -> Unit,
    onNext: () -> Unit,
    onSeek: (Long) -> Unit,
    onToggleShuffle: () -> Unit,
    onCycleRepeat: () -> Unit,
    onOpenLyrics: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val duration = playerState.durationMs.coerceAtLeast(1L)
    val liveFraction = (playerState.positionMs.toFloat() / duration.toFloat()).coerceIn(0f, 1f)
    var isScrubbing by remember(track.id) { mutableStateOf(false) }
    var scrubFraction by remember(track.id) { mutableFloatStateOf(0f) }

    val displayedFraction = if (isScrubbing) scrubFraction else liveFraction
    val displayedPositionMs = if (isScrubbing) {
        (scrubFraction * duration).toLong()
    } else {
        playerState.positionMs
    }

    Column(
        modifier = modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.SpaceBetween,
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Box(
            modifier = Modifier
                .weight(1f, fill = false)
                .fillMaxWidth(0.84f)
                .aspectRatio(1f),
            contentAlignment = Alignment.Center,
        ) {
            ArtworkImage(
                localPath = track.localCoverPath,
                remoteOrRelativeUrl = track.coverUrl,
                activeBaseUrl = activeBaseUrl,
                contentDescription = track.title,
                cornerRadius = 24.dp,
                fallbackIcon = Icons.Rounded.Album,
                modifier = Modifier.fillMaxSize(),
            )
        }

        Column(
            modifier = Modifier.fillMaxWidth(),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Column(modifier = Modifier.weight(1f)) {
                    Text(
                        text = track.title.ifBlank { "Untitled Track" },
                        style = MaterialTheme.typography.headlineSmall,
                        color = FlacifyTextPrimary,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                    val subtitle = buildString {
                        append(track.artist.ifBlank { "Unknown Artist" })
                        if (track.album.isNotBlank()) {
                            append(" · ")
                            append(track.album)
                        }
                    }
                    Text(
                        text = subtitle,
                        style = MaterialTheme.typography.bodyMedium,
                        color = FlacifyTextMuted,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                }

                IconButton(onClick = onOpenLyrics) {
                    Icon(
                        imageVector = Icons.Rounded.Lyrics,
                        contentDescription = "Open Lyrics",
                        tint = if (playerState.parsedLyrics.lines.isNotEmpty()) {
                            FlacifyEmeraldBright
                        } else {
                            FlacifyTextMuted
                        },
                    )
                }
            }

            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                QualityBadgePill(badge = track.qualityBadge)
                val bytes = track.localFileSize.takeIf { it > 0L } ?: track.remoteFileSize
                if (bytes > 0L) {
                    Text(
                        text = "${FormatUtils.formatBytes(bytes)} offline",
                        style = MaterialTheme.typography.bodySmall,
                        fontFamily = FontFamily.Monospace,
                        color = FlacifySkyAccent,
                    )
                }
            }

            Column(modifier = Modifier.fillMaxWidth()) {
                Slider(
                    value = displayedFraction,
                    onValueChange = { frac ->
                        isScrubbing = true
                        scrubFraction = frac.coerceIn(0f, 1f)
                    },
                    onValueChangeFinished = {
                        val target = (scrubFraction * duration).toLong()
                        isScrubbing = false
                        onSeek(target)
                    },
                    colors = SliderDefaults.colors(
                        thumbColor = FlacifyEmeraldBright,
                        activeTrackColor = FlacifyEmeraldBright,
                        inactiveTrackColor = FlacifyBorder,
                    ),
                    modifier = Modifier.fillMaxWidth(),
                )
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                ) {
                    Text(
                        text = FormatUtils.formatDuration(displayedPositionMs),
                        style = MaterialTheme.typography.bodySmall,
                        fontFamily = FontFamily.Monospace,
                        color = FlacifyTextMuted,
                    )
                    Text(
                        text = FormatUtils.formatDuration(playerState.durationMs),
                        style = MaterialTheme.typography.bodySmall,
                        fontFamily = FontFamily.Monospace,
                        color = FlacifyTextMuted,
                    )
                }
            }

            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(bottom = 12.dp),
                horizontalArrangement = Arrangement.SpaceEvenly,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                IconButton(onClick = onToggleShuffle) {
                    Icon(
                        imageVector = Icons.Rounded.Shuffle,
                        contentDescription = "Shuffle",
                        tint = if (playerState.shuffleEnabled) FlacifyEmeraldBright else FlacifyTextMuted,
                    )
                }

                IconButton(onClick = onPrevious) {
                    Icon(
                        imageVector = Icons.Rounded.SkipPrevious,
                        contentDescription = "Previous",
                        tint = FlacifyTextPrimary,
                        modifier = Modifier.size(34.dp),
                    )
                }

                Surface(
                    shape = CircleShape,
                    color = FlacifyEmerald,
                    modifier = Modifier
                        .size(66.dp)
                        .clickable(onClick = onTogglePlayPause),
                ) {
                    Box(contentAlignment = Alignment.Center) {
                        Icon(
                            imageVector = if (playerState.isPlaying) {
                                Icons.Rounded.Pause
                            } else {
                                Icons.Rounded.PlayArrow
                            },
                            contentDescription = if (playerState.isPlaying) "Pause" else "Play",
                            tint = Color(0xFF032219),
                            modifier = Modifier.size(36.dp),
                        )
                    }
                }

                IconButton(onClick = onNext) {
                    Icon(
                        imageVector = Icons.Rounded.SkipNext,
                        contentDescription = "Next",
                        tint = FlacifyTextPrimary,
                        modifier = Modifier.size(34.dp),
                    )
                }

                IconButton(onClick = onCycleRepeat) {
                    Icon(
                        imageVector = when (playerState.repeatMode) {
                            RepeatModeState.ONE -> Icons.Rounded.RepeatOne
                            else -> Icons.Rounded.Repeat
                        },
                        contentDescription = "Repeat",
                        tint = if (playerState.repeatMode == RepeatModeState.OFF) {
                            FlacifyTextMuted
                        } else {
                            FlacifyEmeraldBright
                        },
                    )
                }
            }
        }
    }
}

@Composable
private fun LyricsBody(
    parsedLyrics: ParsedLyrics,
    positionMs: Long,
    onSeekToLine: (Long) -> Unit,
    modifier: Modifier = Modifier,
) {
    if (parsedLyrics.lines.isEmpty()) {
        Box(
            modifier = modifier.fillMaxWidth(),
            contentAlignment = Alignment.Center,
        ) {
            Column(
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                Icon(
                    imageVector = Icons.Rounded.Lyrics,
                    contentDescription = null,
                    tint = FlacifyTextMuted,
                    modifier = Modifier.size(40.dp),
                )
                Text(
                    text = "No Offline Lyrics Found",
                    style = MaterialTheme.typography.titleMedium,
                    color = FlacifyTextPrimary,
                )
                Text(
                    text = "Synced .lrc and embedded FLAC Vorbis lyrics are loaded automatically when available.",
                    style = MaterialTheme.typography.bodySmall,
                    color = FlacifyTextMuted,
                    textAlign = TextAlign.Center,
                )
            }
        }
        return
    }

    val listState = rememberLazyListState()
    val activeIdx = remember(parsedLyrics, positionMs) {
        if (parsedLyrics.isSynced) {
            LrcParser.findActiveLineIndex(parsedLyrics.lines, positionMs)
        } else {
            -1
        }
    }

    LaunchedEffect(activeIdx) {
        if (parsedLyrics.isSynced && activeIdx >= 0 && activeIdx < parsedLyrics.lines.size) {
            listState.animateScrollToItem((activeIdx - 2).coerceAtLeast(0))
        }
    }

    LazyColumn(
        state = listState,
        contentPadding = PaddingValues(vertical = 24.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
        modifier = modifier.fillMaxWidth(),
    ) {
        itemsIndexed(
            items = parsedLyrics.lines,
            key = { idx, line -> "${idx}_${line.timestampMs}" },
        ) { idx, line ->
            val isActive = parsedLyrics.isSynced && idx == activeIdx
            val lineColor = when {
                !parsedLyrics.isSynced -> FlacifyTextPrimary
                isActive -> FlacifyEmeraldBright
                idx < activeIdx -> FlacifyTextMuted.copy(alpha = 0.55f)
                else -> FlacifyTextMuted
            }

            Text(
                text = line.text,
                fontSize = if (isActive) 21.sp else 17.sp,
                lineHeight = if (isActive) 28.sp else 24.sp,
                fontWeight = if (isActive) FontWeight.Bold else FontWeight.Medium,
                color = lineColor,
                modifier = Modifier
                    .fillMaxWidth()
                    .clickable(enabled = parsedLyrics.isSynced) {
                        onSeekToLine(line.timestampMs)
                    }
                    .padding(vertical = 4.dp),
            )
        }
    }
}

@Composable
private fun QueueBody(
    queue: List<TrackEntity>,
    currentIndex: Int,
    activeBaseUrl: String,
    onSelectIndex: (Int) -> Unit,
    onRemoveIndex: (Int) -> Unit,
    modifier: Modifier = Modifier,
) {
    if (queue.isEmpty()) {
        Box(
            modifier = modifier.fillMaxWidth(),
            contentAlignment = Alignment.Center,
        ) {
            Text(
                text = "Playback queue is empty.",
                style = MaterialTheme.typography.bodyMedium,
                color = FlacifyTextMuted,
            )
        }
        return
    }

    LazyColumn(
        contentPadding = PaddingValues(vertical = 8.dp),
        modifier = modifier.fillMaxWidth(),
    ) {
        itemsIndexed(
            items = queue,
            key = { idx, track -> "${idx}_${track.id}" },
        ) { idx, track ->
            val isCurrent = idx == currentIndex
            Surface(
                color = if (isCurrent) FlacifyElevatedSurface else Color.Transparent,
                shape = RoundedCornerShape(14.dp),
                modifier = Modifier
                    .fillMaxWidth()
                    .clickable { onSelectIndex(idx) },
            ) {
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 10.dp, vertical = 8.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    ArtworkImage(
                        localPath = track.localCoverPath,
                        remoteOrRelativeUrl = track.coverUrl,
                        activeBaseUrl = activeBaseUrl,
                        contentDescription = track.title,
                        cornerRadius = 8.dp,
                        fallbackIcon = Icons.Rounded.MusicNote,
                        modifier = Modifier.size(42.dp),
                    )
                    Spacer(modifier = Modifier.width(10.dp))
                    Column(modifier = Modifier.weight(1f)) {
                        Text(
                            text = track.title,
                            style = MaterialTheme.typography.titleMedium,
                            color = if (isCurrent) FlacifyEmeraldBright else FlacifyTextPrimary,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                        )
                        Text(
                            text = track.artist,
                            style = MaterialTheme.typography.bodySmall,
                            color = FlacifyTextMuted,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                        )
                    }
                    if (isCurrent) {
                        Icon(
                            imageVector = Icons.Rounded.GraphicEq,
                            contentDescription = "Now playing",
                            tint = FlacifyEmeraldBright,
                            modifier = Modifier.size(18.dp),
                        )
                    } else {
                        IconButton(onClick = { onRemoveIndex(idx) }) {
                            Icon(
                                imageVector = Icons.Rounded.Close,
                                contentDescription = "Remove from queue",
                                tint = FlacifyTextMuted,
                                modifier = Modifier.size(18.dp),
                            )
                        }
                    }
                }
            }
            HorizontalDivider(color = FlacifyBorder.copy(alpha = 0.35f), thickness = 0.5.dp)
        }
    }
}
