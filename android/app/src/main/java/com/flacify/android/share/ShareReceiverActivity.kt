package com.flacify.android.share

import android.content.Intent
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
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
import androidx.compose.material.icons.rounded.CheckCircle
import androidx.compose.material.icons.rounded.ErrorOutline
import androidx.compose.material.icons.rounded.GraphicEq
import androidx.compose.material.icons.rounded.Schedule
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.flacify.android.FlacifyApplication
import com.flacify.android.MainActivity
import com.flacify.android.ui.theme.FlacifyAmberAccent
import com.flacify.android.ui.theme.FlacifyBorder
import com.flacify.android.ui.theme.FlacifyCardSurface
import com.flacify.android.ui.theme.FlacifyDanger
import com.flacify.android.ui.theme.FlacifyElevatedSurface
import com.flacify.android.ui.theme.FlacifyEmerald
import com.flacify.android.ui.theme.FlacifyEmeraldBright
import com.flacify.android.ui.theme.FlacifySkyAccent
import com.flacify.android.ui.theme.FlacifyTextMuted
import com.flacify.android.ui.theme.FlacifyTextPrimary
import com.flacify.android.ui.theme.FlacifyTheme

class ShareReceiverActivity : ComponentActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        val sharedText = buildString {
            intent?.getStringExtra(Intent.EXTRA_TEXT)?.let { append(it).append(' ') }
            intent?.getStringExtra(Intent.EXTRA_SUBJECT)?.let { append(it) }
        }.trim()

        val app = applicationContext as FlacifyApplication

        setContent {
            FlacifyTheme {
                ShareReceiverDialog(
                    rawSharedText = sharedText,
                    shareManager = app.shareManager,
                    onOpenFlacify = {
                        startActivity(
                            Intent(this, MainActivity::class.java).apply {
                                flags = Intent.FLAG_ACTIVITY_SINGLE_TOP or Intent.FLAG_ACTIVITY_CLEAR_TOP
                            }
                        )
                        finish()
                    },
                    onDone = { finish() },
                )
            }
        }
    }
}

@Composable
private fun ShareReceiverDialog(
    rawSharedText: String,
    shareManager: ShareToPcManager,
    onOpenFlacify: () -> Unit,
    onDone: () -> Unit,
) {
    var result by remember { mutableStateOf<ShareSubmissionResult?>(null) }

    LaunchedEffect(rawSharedText) {
        result = shareManager.sendOrQueue(rawSharedText, autoDownload = true)
    }

    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(Color.Black.copy(alpha = 0.55f))
            .padding(24.dp),
        contentAlignment = Alignment.Center,
    ) {
        Card(
            colors = CardDefaults.cardColors(containerColor = FlacifyCardSurface),
            border = BorderStroke(1.dp, FlacifyBorder),
            shape = RoundedCornerShape(22.dp),
            modifier = Modifier.fillMaxWidth(),
        ) {
            Column(
                modifier = Modifier.padding(20.dp),
                verticalArrangement = Arrangement.spacedBy(14.dp),
            ) {
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    Icon(
                        imageVector = Icons.Rounded.GraphicEq,
                        contentDescription = null,
                        tint = FlacifyEmeraldBright,
                        modifier = Modifier.size(22.dp),
                    )
                    Text(
                        text = "Send to Flacify PC",
                        style = MaterialTheme.typography.titleMedium,
                        color = FlacifyTextPrimary,
                    )
                }

                val current = result
                when (current) {
                    null -> {
                        Row(
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.spacedBy(12.dp),
                        ) {
                            CircularProgressIndicator(
                                strokeWidth = 2.5.dp,
                                color = FlacifyEmeraldBright,
                                modifier = Modifier.size(22.dp),
                            )
                            Text(
                                text = "Sending shared link to your Flacify PC queue...",
                                style = MaterialTheme.typography.bodyMedium,
                                color = FlacifyTextMuted,
                            )
                        }
                    }

                    ShareSubmissionResult.InvalidUrl -> {
                        StatusDetail(
                            icon = Icons.Rounded.ErrorOutline,
                            tint = FlacifyDanger,
                            heading = "No Supported Audio Link Found",
                            body = "Expected a Spotify, spotify.link, or YouTube Music URL in the shared text.",
                            urlPreview = rawSharedText.take(120),
                        )
                        Button(
                            onClick = onDone,
                            colors = ButtonDefaults.buttonColors(
                                containerColor = FlacifyElevatedSurface,
                                contentColor = FlacifyTextPrimary,
                            ),
                            modifier = Modifier.fillMaxWidth(),
                        ) {
                            Text("Close")
                        }
                    }

                    is ShareSubmissionResult.NotPaired -> {
                        StatusDetail(
                            icon = Icons.Rounded.ErrorOutline,
                            tint = FlacifyAmberAccent,
                            heading = "Pair Your PC First",
                            body = "Open Flacify and connect to your PC once in the Sync tab, then share any Spotify track/playlist directly.",
                            urlPreview = current.extracted.url,
                        )
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.spacedBy(10.dp),
                        ) {
                            OutlinedButton(
                                onClick = onDone,
                                border = BorderStroke(1.dp, FlacifyBorder),
                                modifier = Modifier.weight(1f),
                            ) {
                                Text("Close")
                            }
                            Button(
                                onClick = onOpenFlacify,
                                colors = ButtonDefaults.buttonColors(
                                    containerColor = FlacifyEmerald,
                                    contentColor = Color(0xFF032219),
                                ),
                                modifier = Modifier.weight(1f),
                            ) {
                                Text("Open Flacify")
                            }
                        }
                    }

                    is ShareSubmissionResult.SentNow -> {
                        val count = current.response.queuedCount
                        val label = current.extracted.displayKind
                        StatusDetail(
                            icon = Icons.Rounded.CheckCircle,
                            tint = FlacifyEmeraldBright,
                            heading = "Queued on Flacify PC!",
                            body = "$label accepted — $count track(s) added to your PC download queue.",
                            urlPreview = current.response.extractedUrl.ifBlank { current.extracted.url },
                        )
                        Button(
                            onClick = onDone,
                            colors = ButtonDefaults.buttonColors(
                                containerColor = FlacifyEmerald,
                                contentColor = Color(0xFF032219),
                            ),
                            modifier = Modifier.fillMaxWidth(),
                        ) {
                            Text("Done")
                        }
                    }

                    is ShareSubmissionResult.QueuedOffline -> {
                        StatusDetail(
                            icon = Icons.Rounded.Schedule,
                            tint = FlacifyAmberAccent,
                            heading = "Saved for Auto-Send",
                            body = current.reason,
                            urlPreview = current.extracted.url,
                        )
                        Button(
                            onClick = onDone,
                            colors = ButtonDefaults.buttonColors(
                                containerColor = FlacifyElevatedSurface,
                                contentColor = FlacifyAmberAccent,
                            ),
                            border = BorderStroke(1.dp, FlacifyAmberAccent.copy(alpha = 0.5f)),
                            modifier = Modifier.fillMaxWidth(),
                        ) {
                            Text("Done")
                        }
                    }

                    is ShareSubmissionResult.Failed -> {
                        StatusDetail(
                            icon = Icons.Rounded.ErrorOutline,
                            tint = FlacifyDanger,
                            heading = "PC Rejected Share",
                            body = current.message,
                            urlPreview = current.extracted.url,
                        )
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.spacedBy(10.dp),
                        ) {
                            OutlinedButton(
                                onClick = onDone,
                                border = BorderStroke(1.dp, FlacifyBorder),
                                modifier = Modifier.weight(1f),
                            ) {
                                Text("Close")
                            }
                            Button(
                                onClick = onOpenFlacify,
                                colors = ButtonDefaults.buttonColors(
                                    containerColor = FlacifyElevatedSurface,
                                    contentColor = FlacifyTextPrimary,
                                ),
                                modifier = Modifier.weight(1f),
                            ) {
                                Text("Open Flacify")
                            }
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun StatusDetail(
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    tint: Color,
    heading: String,
    body: String,
    urlPreview: String,
) {
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Row(
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Icon(
                imageVector = icon,
                contentDescription = null,
                tint = tint,
                modifier = Modifier.size(22.dp),
            )
            Text(
                text = heading,
                style = MaterialTheme.typography.titleMedium,
                color = tint,
            )
        }
        Text(
            text = body,
            style = MaterialTheme.typography.bodySmall,
            color = FlacifyTextMuted,
        )
        if (urlPreview.isNotBlank()) {
            Surface(
                color = FlacifyElevatedSurface,
                shape = RoundedCornerShape(10.dp),
                modifier = Modifier.fillMaxWidth(),
            ) {
                Text(
                    text = urlPreview,
                    style = MaterialTheme.typography.bodySmall,
                    fontFamily = FontFamily.Monospace,
                    color = FlacifySkyAccent,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.padding(10.dp),
                )
            }
        }
    }
}
