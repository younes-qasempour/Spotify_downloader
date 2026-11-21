package com.flacify.android.ui.components

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Album
import androidx.compose.material.icons.rounded.CheckCircle
import androidx.compose.material.icons.rounded.CloudQueue
import androidx.compose.material.icons.rounded.MusicNote
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import coil.compose.AsyncImage
import coil.request.ImageRequest
import com.flacify.android.ui.library.FormatUtils
import com.flacify.android.ui.theme.FlacifyAmberAccent
import com.flacify.android.ui.theme.FlacifyBorder
import com.flacify.android.ui.theme.FlacifyElevatedSurface
import com.flacify.android.ui.theme.FlacifyEmerald
import com.flacify.android.ui.theme.FlacifyEmeraldBright
import com.flacify.android.ui.theme.FlacifySkyAccent
import com.flacify.android.ui.theme.FlacifyTextMuted
import com.flacify.android.ui.theme.FlacifyTextPrimary
import java.io.File
import java.util.Locale

private val FlacifyVioletAccent = Color(0xFFA78BFA)

@Composable
fun ArtworkImage(
    localPath: String?,
    remoteOrRelativeUrl: String?,
    activeBaseUrl: String,
    contentDescription: String?,
    modifier: Modifier = Modifier,
    cornerRadius: Dp = 12.dp,
    fallbackIcon: ImageVector = Icons.Rounded.MusicNote,
) {
    val context = LocalContext.current
    val resolvedModel: Any? = remember(localPath, remoteOrRelativeUrl, activeBaseUrl) {
        val local = localPath?.trim()
        val localFile = if (!local.isNullOrEmpty()) File(local) else null
        if (localFile != null && localFile.isFile && localFile.length() > 0L) {
            localFile
        } else {
            val remote = remoteOrRelativeUrl?.trim().orEmpty()
            when {
                remote.startsWith("http://", ignoreCase = true) ||
                    remote.startsWith("https://", ignoreCase = true) -> remote
                remote.startsWith("/") && activeBaseUrl.isNotBlank() ->
                    activeBaseUrl.trimEnd('/') + remote
                else -> null
            }
        }
    }

    Box(
        modifier = modifier
            .clip(RoundedCornerShape(cornerRadius))
            .background(FlacifyElevatedSurface)
            .border(1.dp, FlacifyBorder, RoundedCornerShape(cornerRadius)),
        contentAlignment = Alignment.Center,
    ) {
        Icon(
            imageVector = fallbackIcon,
            contentDescription = null,
            tint = FlacifyTextMuted.copy(alpha = 0.65f),
            modifier = Modifier.size(22.dp),
        )
        if (resolvedModel != null) {
            AsyncImage(
                model = ImageRequest.Builder(context)
                    .data(resolvedModel)
                    .crossfade(true)
                    .build(),
                contentDescription = contentDescription,
                contentScale = ContentScale.Crop,
                modifier = Modifier.fillMaxSize(),
            )
        }
    }
}

@Composable
fun QualityBadgePill(
    badge: String,
    modifier: Modifier = Modifier,
) {
    val label = badge.trim().ifBlank { "AUDIO" }.uppercase(Locale.ROOT)
    val tint = when {
        label.contains("24") -> FlacifyAmberAccent
        label.contains("FLAC") || label.contains("WAV") -> FlacifyEmeraldBright
        label.contains("320") || label.contains("MP3") -> FlacifySkyAccent
        label.contains("OPUS") || label.contains("YTM") -> FlacifyVioletAccent
        else -> FlacifyTextMuted
    }

    Surface(
        color = tint.copy(alpha = 0.14f),
        shape = RoundedCornerShape(999.dp),
        border = BorderStroke(1.dp, tint.copy(alpha = 0.35f)),
        modifier = modifier,
    ) {
        Text(
            text = label,
            style = MaterialTheme.typography.labelSmall,
            color = tint,
            maxLines = 1,
            modifier = Modifier.padding(horizontal = 7.dp, vertical = 2.dp),
        )
    }
}

@Composable
fun TrackRowItem(
    title: String,
    artist: String,
    album: String,
    qualityBadge: String,
    durationMs: Long,
    fileSizeBytes: Long,
    isOfflineReady: Boolean,
    localCoverPath: String?,
    remoteCoverUrl: String?,
    activeBaseUrl: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    trackIndexLabel: String? = null,
) {
    Row(
        modifier = modifier
            .fillMaxWidth()
            .clickable(onClick = onClick)
            .padding(horizontal = 16.dp, vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (trackIndexLabel != null) {
            Text(
                text = trackIndexLabel,
                style = MaterialTheme.typography.labelSmall,
                color = FlacifyTextMuted,
                modifier = Modifier.width(28.dp),
            )
        }

        ArtworkImage(
            localPath = localCoverPath,
            remoteOrRelativeUrl = remoteCoverUrl,
            activeBaseUrl = activeBaseUrl,
            contentDescription = title,
            cornerRadius = 10.dp,
            fallbackIcon = Icons.Rounded.Album,
            modifier = Modifier.size(48.dp),
        )

        Spacer(modifier = Modifier.width(12.dp))

        Column(
            modifier = Modifier.weight(1f),
            verticalArrangement = Arrangement.spacedBy(3.dp),
        ) {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                Text(
                    text = title.ifBlank { "Untitled Track" },
                    style = MaterialTheme.typography.titleMedium,
                    color = FlacifyTextPrimary,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.weight(1f, fill = false),
                )
                Icon(
                    imageVector = if (isOfflineReady) {
                        Icons.Rounded.CheckCircle
                    } else {
                        Icons.Rounded.CloudQueue
                    },
                    contentDescription = if (isOfflineReady) "Synced offline" else "PC only",
                    tint = if (isOfflineReady) FlacifyEmeraldBright else FlacifyTextMuted.copy(alpha = 0.6f),
                    modifier = Modifier.size(14.dp),
                )
            }

            val sub = buildString {
                append(artist.ifBlank { "Unknown Artist" })
                if (album.isNotBlank()) {
                    append(" · ")
                    append(album)
                }
            }
            Text(
                text = sub,
                style = MaterialTheme.typography.bodySmall,
                color = FlacifyTextMuted,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )

            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                QualityBadgePill(badge = qualityBadge)
                if (fileSizeBytes > 0L) {
                    Text(
                        text = FormatUtils.formatBytes(fileSizeBytes),
                        style = MaterialTheme.typography.bodySmall,
                        fontFamily = FontFamily.Monospace,
                        color = FlacifyTextMuted,
                    )
                }
                if (durationMs > 0L) {
                    Text(
                        text = FormatUtils.formatDuration(durationMs),
                        style = MaterialTheme.typography.bodySmall,
                        fontFamily = FontFamily.Monospace,
                        color = FlacifyTextMuted,
                    )
                }
            }
        }
    }
}
