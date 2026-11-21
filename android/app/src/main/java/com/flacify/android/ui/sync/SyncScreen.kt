package com.flacify.android.ui.sync

import android.Manifest
import android.content.pm.PackageManager
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
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
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.CheckCircle
import androidx.compose.material.icons.rounded.Computer
import androidx.compose.material.icons.rounded.LinkOff
import androidx.compose.material.icons.rounded.QrCodeScanner
import androidx.compose.material.icons.rounded.Refresh
import androidx.compose.material.icons.rounded.Visibility
import androidx.compose.material.icons.rounded.VisibilityOff
import androidx.compose.material.icons.rounded.WifiFind
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import androidx.lifecycle.compose.collectAsStateWithLifecycle
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

@Composable
fun SyncScreen(
    viewModel: SyncViewModel,
    modifier: Modifier = Modifier,
) {
    val state by viewModel.uiState.collectAsStateWithLifecycle()
    val context = LocalContext.current
    var showQrScanner by remember { mutableStateOf(false) }
    var cameraNotice by remember { mutableStateOf<String?>(null) }

    val cameraPermissionLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.RequestPermission(),
    ) { granted ->
        if (granted) {
            cameraNotice = null
            showQrScanner = true
        } else {
            cameraNotice = "Camera permission denied — paste your Pairing URI below instead."
        }
    }

    DisposableEffect(Unit) {
        onDispose {
            viewModel.stopMdnsScan()
        }
    }

    if (showQrScanner) {
        QrScannerDialog(
            onQrScanned = { raw ->
                showQrScanner = false
                viewModel.applyPairingUri(raw, autoConnect = true)
            },
            onDismiss = { showQrScanner = false },
        )
    }

    val fieldColors = OutlinedTextFieldDefaults.colors(
        focusedBorderColor = FlacifyEmerald,
        unfocusedBorderColor = FlacifyBorder,
        focusedLabelColor = FlacifyEmeraldBright,
        unfocusedLabelColor = FlacifyTextMuted,
        focusedTextColor = FlacifyTextPrimary,
        unfocusedTextColor = FlacifyTextPrimary,
        cursorColor = FlacifyEmeraldBright,
    )

    Column(
        modifier = modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 20.dp, vertical = 16.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        // Header + Status Badge
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = "PC Connection & Sync",
                    style = MaterialTheme.typography.headlineSmall,
                    color = FlacifyTextPrimary,
                )
                Text(
                    text = "Pair over Wi-Fi, Tailscale, or Android Emulator (10.0.2.2)",
                    style = MaterialTheme.typography.bodySmall,
                    color = FlacifyTextMuted,
                )
            }
            Spacer(modifier = Modifier.width(8.dp))
            StatusBadge(
                isConnected = state.isConnected,
                isPaired = state.connectionConfig.isPaired,
                restartRequired = state.syncInfo?.restartRequired == true,
            )
        }

        // Feedback banners
        state.errorMessage?.let { err ->
            BannerCard(text = err, tint = FlacifyDanger)
        }
        cameraNotice?.let { note ->
            BannerCard(text = note, tint = FlacifyAmberAccent)
        }
        state.statusMessage?.let { msg ->
            if (state.errorMessage == null) {
                BannerCard(text = msg, tint = FlacifyEmerald)
            }
        }

        // 1. Saved / Live Connection Status Card
        if (state.connectionConfig.isPaired) {
            val cfg = state.connectionConfig
            val info = state.syncInfo
            Card(
                colors = CardDefaults.cardColors(containerColor = FlacifyCardSurface),
                border = BorderStroke(
                    1.dp,
                    if (state.isConnected) FlacifyEmerald.copy(alpha = 0.45f) else FlacifyBorder,
                ),
                shape = RoundedCornerShape(20.dp),
                modifier = Modifier.fillMaxWidth(),
            ) {
                Column(
                    modifier = Modifier.padding(18.dp),
                    verticalArrangement = Arrangement.spacedBy(12.dp),
                ) {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Row(
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.spacedBy(10.dp),
                        ) {
                            Icon(
                                imageVector = Icons.Rounded.Computer,
                                contentDescription = null,
                                tint = if (state.isConnected) FlacifyEmeraldBright else FlacifyTextMuted,
                            )
                            Column {
                                Text(
                                    text = info?.deviceName?.ifBlank { cfg.deviceName }
                                        ?: cfg.deviceName.ifBlank { "Flacify PC" },
                                    style = MaterialTheme.typography.titleMedium,
                                    color = FlacifyTextPrimary,
                                )
                                Text(
                                    text = cfg.activeUrl,
                                    style = MaterialTheme.typography.bodySmall,
                                    fontFamily = FontFamily.Monospace,
                                    color = FlacifySkyAccent,
                                )
                            }
                        }
                        if (info?.serverVersion?.isNotBlank() == true || cfg.serverVersion.isNotBlank()) {
                            Text(
                                text = "v${info?.serverVersion?.ifBlank { cfg.serverVersion } ?: cfg.serverVersion}",
                                style = MaterialTheme.typography.labelSmall,
                                color = FlacifyTextMuted,
                            )
                        }
                    }

                    if (info != null) {
                        Surface(
                            color = FlacifyElevatedSurface,
                            shape = RoundedCornerShape(12.dp),
                            modifier = Modifier.fillMaxWidth(),
                        ) {
                            Text(
                                text = "${info.libraryStats.totalTracks} unique tracks · ${info.libraryStats.sizeStr} · ${info.savedPlaylistsCount} playlists",
                                style = MaterialTheme.typography.bodySmall,
                                fontFamily = FontFamily.Monospace,
                                color = FlacifyEmeraldBright,
                                modifier = Modifier.padding(horizontal = 12.dp, vertical = 10.dp),
                            )
                        }
                    }

                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(10.dp),
                    ) {
                        OutlinedButton(
                            onClick = { viewModel.testSavedConnection() },
                            enabled = !state.isTesting,
                            modifier = Modifier.weight(1f),
                            border = BorderStroke(1.dp, FlacifyBorder),
                        ) {
                            Icon(
                                imageVector = Icons.Rounded.Refresh,
                                contentDescription = null,
                                modifier = Modifier.size(16.dp),
                            )
                            Spacer(modifier = Modifier.width(6.dp))
                            Text("Test")
                        }
                        OutlinedButton(
                            onClick = { viewModel.disconnect() },
                            enabled = !state.isTesting,
                            modifier = Modifier.weight(1f),
                            border = BorderStroke(1.dp, FlacifyDanger.copy(alpha = 0.5f)),
                            colors = ButtonDefaults.outlinedButtonColors(contentColor = FlacifyDanger),
                        ) {
                            Icon(
                                imageVector = Icons.Rounded.LinkOff,
                                contentDescription = null,
                                modifier = Modifier.size(16.dp),
                            )
                            Spacer(modifier = Modifier.width(6.dp))
                            Text("Unpair")
                        }
                    }
                }
            }
        }

        // 2. Quick Pair via QR Code or Pairing URI
        Card(
            colors = CardDefaults.cardColors(containerColor = FlacifyCardSurface),
            border = BorderStroke(1.dp, FlacifyBorder),
            shape = RoundedCornerShape(20.dp),
            modifier = Modifier.fillMaxWidth(),
        ) {
            Column(
                modifier = Modifier.padding(18.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                Text(
                    text = "Quick Pair",
                    style = MaterialTheme.typography.titleMedium,
                    color = FlacifyTextPrimary,
                )
                Text(
                    text = "Scan the QR code shown in Desktop Settings -> Mobile Sync, or paste the flacify://pair URI (handy on Android Emulator).",
                    style = MaterialTheme.typography.bodySmall,
                    color = FlacifyTextMuted,
                )

                Button(
                    onClick = {
                        val granted = ContextCompat.checkSelfPermission(
                            context,
                            Manifest.permission.CAMERA,
                        ) == PackageManager.PERMISSION_GRANTED
                        if (granted) {
                            cameraNotice = null
                            showQrScanner = true
                        } else {
                            cameraPermissionLauncher.launch(Manifest.permission.CAMERA)
                        }
                    },
                    enabled = !state.isTesting,
                    colors = ButtonDefaults.buttonColors(
                        containerColor = FlacifyEmerald,
                        contentColor = Color(0xFF032219),
                    ),
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Icon(
                        imageVector = Icons.Rounded.QrCodeScanner,
                        contentDescription = null,
                        modifier = Modifier.size(18.dp),
                    )
                    Spacer(modifier = Modifier.width(8.dp))
                    Text("Scan Desktop QR Code")
                }

                OutlinedTextField(
                    value = state.pairingUriInput,
                    onValueChange = viewModel::updatePairingUriInput,
                    label = { Text("Paste Pairing URI (flacify://pair?...)") },
                    singleLine = true,
                    colors = fieldColors,
                    modifier = Modifier.fillMaxWidth(),
                )

                OutlinedButton(
                    onClick = { viewModel.applyPairingUri(state.pairingUriInput, autoConnect = true) },
                    enabled = state.pairingUriInput.isNotBlank() && !state.isTesting,
                    border = BorderStroke(1.dp, FlacifyBorder),
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Text("Connect Using Pairing URI")
                }
            }
        }

        // 3. Auto-Discover PC on Wi-Fi (NSD / _flacify._tcp)
        Card(
            colors = CardDefaults.cardColors(containerColor = FlacifyCardSurface),
            border = BorderStroke(1.dp, FlacifyBorder),
            shape = RoundedCornerShape(20.dp),
            modifier = Modifier.fillMaxWidth(),
        ) {
            Column(
                modifier = Modifier.padding(18.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Column(modifier = Modifier.weight(1f)) {
                        Text(
                            text = "Nearby PCs on Wi-Fi",
                            style = MaterialTheme.typography.titleMedium,
                            color = FlacifyTextPrimary,
                        )
                        Text(
                            text = "_flacify._tcp.local. auto-discovery",
                            style = MaterialTheme.typography.bodySmall,
                            color = FlacifyTextMuted,
                        )
                    }
                    OutlinedButton(
                        onClick = {
                            if (state.isScanningMdns) viewModel.stopMdnsScan() else viewModel.startMdnsScan()
                        },
                        border = BorderStroke(1.dp, FlacifyBorder),
                    ) {
                        if (state.isScanningMdns) {
                            CircularProgressIndicator(
                                strokeWidth = 2.dp,
                                color = FlacifyEmeraldBright,
                                modifier = Modifier.size(14.dp),
                            )
                            Spacer(modifier = Modifier.width(6.dp))
                            Text("Stop")
                        } else {
                            Icon(
                                imageVector = Icons.Rounded.WifiFind,
                                contentDescription = null,
                                modifier = Modifier.size(16.dp),
                            )
                            Spacer(modifier = Modifier.width(6.dp))
                            Text("Scan")
                        }
                    }
                }

                state.mdnsError?.let { err ->
                    Text(
                        text = err,
                        style = MaterialTheme.typography.bodySmall,
                        color = FlacifyAmberAccent,
                    )
                }

                if (state.discoveredPcs.isEmpty()) {
                    Text(
                        text = if (state.isScanningMdns) {
                            "Listening for Flacify PC broadcasts on Wi-Fi..."
                        } else {
                            "Tap Scan on physical Wi-Fi, or use Emulator (10.0.2.2:8765) below."
                        },
                        style = MaterialTheme.typography.bodySmall,
                        color = FlacifyTextMuted,
                    )
                } else {
                    state.discoveredPcs.forEach { pc ->
                        Surface(
                            color = FlacifyElevatedSurface,
                            shape = RoundedCornerShape(14.dp),
                            border = BorderStroke(1.dp, FlacifyBorder),
                            modifier = Modifier
                                .fillMaxWidth()
                                .clickable { viewModel.selectDiscoveredPc(pc) },
                        ) {
                            Row(
                                modifier = Modifier.padding(12.dp),
                                horizontalArrangement = Arrangement.SpaceBetween,
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                Column(modifier = Modifier.weight(1f)) {
                                    Text(
                                        text = pc.displayName,
                                        style = MaterialTheme.typography.titleMedium,
                                        color = FlacifyTextPrimary,
                                    )
                                    Text(
                                        text = pc.baseUrl,
                                        style = MaterialTheme.typography.bodySmall,
                                        fontFamily = FontFamily.Monospace,
                                        color = FlacifySkyAccent,
                                    )
                                }
                                if (pc.version.isNotBlank()) {
                                    Text(
                                        text = "v${pc.version}",
                                        style = MaterialTheme.typography.labelSmall,
                                        color = FlacifyEmeraldBright,
                                    )
                                }
                            }
                        }
                    }
                }
            }
        }

        // 4. Manual Server & Token
        Card(
            colors = CardDefaults.cardColors(containerColor = FlacifyCardSurface),
            border = BorderStroke(1.dp, FlacifyBorder),
            shape = RoundedCornerShape(20.dp),
            modifier = Modifier.fillMaxWidth(),
        ) {
            Column(
                modifier = Modifier.padding(18.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text(
                        text = "Manual Setup",
                        style = MaterialTheme.typography.titleMedium,
                        color = FlacifyTextPrimary,
                    )
                    TextButton(onClick = { viewModel.useEmulatorHost() }) {
                        Text(
                            text = "Use Emulator (10.0.2.2)",
                            style = MaterialTheme.typography.labelMedium,
                            color = FlacifySkyAccent,
                        )
                    }
                }

                OutlinedTextField(
                    value = state.manualUrl,
                    onValueChange = viewModel::updateManualUrl,
                    label = { Text("PC Server URL") },
                    placeholder = { Text("http://192.168.1.50:8765") },
                    singleLine = true,
                    colors = fieldColors,
                    keyboardOptions = KeyboardOptions(imeAction = ImeAction.Next),
                    modifier = Modifier.fillMaxWidth(),
                )

                OutlinedTextField(
                    value = state.manualToken,
                    onValueChange = viewModel::updateManualToken,
                    label = { Text("Pairing Token") },
                    singleLine = true,
                    colors = fieldColors,
                    visualTransformation = if (state.showToken) {
                        VisualTransformation.None
                    } else {
                        PasswordVisualTransformation()
                    },
                    trailingIcon = {
                        IconButton(onClick = { viewModel.toggleShowToken() }) {
                            Icon(
                                imageVector = if (state.showToken) {
                                    Icons.Rounded.VisibilityOff
                                } else {
                                    Icons.Rounded.Visibility
                                },
                                contentDescription = if (state.showToken) "Hide token" else "Reveal token",
                                tint = FlacifyTextMuted,
                            )
                        }
                    },
                    modifier = Modifier.fillMaxWidth(),
                )

                Button(
                    onClick = { viewModel.connectManual() },
                    enabled = !state.isTesting,
                    colors = ButtonDefaults.buttonColors(
                        containerColor = FlacifyElevatedSurface,
                        contentColor = FlacifyEmeraldBright,
                    ),
                    border = BorderStroke(1.dp, FlacifyEmerald.copy(alpha = 0.5f)),
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    if (state.isTesting) {
                        CircularProgressIndicator(
                            strokeWidth = 2.dp,
                            color = FlacifyEmeraldBright,
                            modifier = Modifier.size(16.dp),
                        )
                        Spacer(modifier = Modifier.width(8.dp))
                        Text("Verifying...")
                    } else {
                        Icon(
                            imageVector = Icons.Rounded.CheckCircle,
                            contentDescription = null,
                            modifier = Modifier.size(16.dp),
                        )
                        Spacer(modifier = Modifier.width(8.dp))
                        Text("Connect & Verify")
                    }
                }
            }
        }

        Spacer(modifier = Modifier.height(8.dp))
    }
}

@Composable
private fun StatusBadge(
    isConnected: Boolean,
    isPaired: Boolean,
    restartRequired: Boolean,
) {
    val (label, color) = when {
        isConnected && restartRequired -> "PC Restart Needed" to FlacifyAmberAccent
        isConnected -> "Connected" to FlacifyEmeraldBright
        isPaired -> "Saved (Offline)" to FlacifyAmberAccent
        else -> "Not Paired" to FlacifyTextMuted
    }
    Surface(
        color = color.copy(alpha = 0.14f),
        shape = RoundedCornerShape(999.dp),
        border = BorderStroke(1.dp, color.copy(alpha = 0.35f)),
    ) {
        Text(
            text = label,
            style = MaterialTheme.typography.labelSmall,
            color = color,
            modifier = Modifier.padding(horizontal = 10.dp, vertical = 4.dp),
        )
    }
}

@Composable
private fun BannerCard(text: String, tint: Color) {
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .background(tint.copy(alpha = 0.12f), RoundedCornerShape(14.dp))
            .padding(horizontal = 14.dp, vertical = 10.dp),
    ) {
        Text(
            text = text,
            style = MaterialTheme.typography.bodySmall,
            color = tint,
        )
    }
}
