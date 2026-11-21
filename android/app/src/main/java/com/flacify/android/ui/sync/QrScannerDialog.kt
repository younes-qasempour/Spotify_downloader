package com.flacify.android.ui.sync

import android.view.ViewGroup
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageProxy
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Close
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import androidx.core.content.ContextCompat
import androidx.lifecycle.compose.LocalLifecycleOwner
import com.flacify.android.ui.theme.FlacifyCanvas
import com.flacify.android.ui.theme.FlacifyEmeraldBright
import com.flacify.android.ui.theme.FlacifyTextMuted
import com.flacify.android.ui.theme.FlacifyTextPrimary
import com.google.zxing.BarcodeFormat
import com.google.zxing.BinaryBitmap
import com.google.zxing.DecodeHintType
import com.google.zxing.MultiFormatReader
import com.google.zxing.NotFoundException
import com.google.zxing.PlanarYUVLuminanceSource
import com.google.zxing.common.HybridBinarizer
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean

@Composable
fun QrScannerDialog(
    onQrScanned: (String) -> Unit,
    onDismiss: () -> Unit,
) {
    val context = LocalContext.current
    val lifecycleOwner = LocalLifecycleOwner.current
    val currentOnScanned = rememberUpdatedState(onQrScanned)

    val handled = remember { AtomicBoolean(false) }
    val analysisExecutor = remember { Executors.newSingleThreadExecutor() }
    val previewView = remember {
        PreviewView(context).apply {
            layoutParams = ViewGroup.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT,
            )
            scaleType = PreviewView.ScaleType.FILL_CENTER
        }
    }

    val qrReader = remember {
        MultiFormatReader().apply {
            setHints(
                mapOf(
                    DecodeHintType.POSSIBLE_FORMATS to listOf(BarcodeFormat.QR_CODE),
                    DecodeHintType.TRY_HARDER to true,
                )
            )
        }
    }

    DisposableEffect(lifecycleOwner, previewView) {
        val cameraProviderFuture = ProcessCameraProvider.getInstance(context)
        val mainExecutor = ContextCompat.getMainExecutor(context)
        var boundProvider: ProcessCameraProvider? = null

        val listener = Runnable {
            try {
                val provider = cameraProviderFuture.get()
                boundProvider = provider

                val preview = Preview.Builder().build().apply {
                    surfaceProvider = previewView.surfaceProvider
                }

                val analysis = ImageAnalysis.Builder()
                    .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                    .build()

                analysis.setAnalyzer(analysisExecutor) { imageProxy ->
                    try {
                        if (handled.get()) return@setAnalyzer
                        val decoded = decodeQrFromImageProxy(imageProxy, qrReader)
                        if (!decoded.isNullOrBlank() && handled.compareAndSet(false, true)) {
                            mainExecutor.execute {
                                currentOnScanned.value(decoded)
                            }
                        }
                    } finally {
                        imageProxy.close()
                    }
                }

                provider.unbindAll()
                provider.bindToLifecycle(
                    lifecycleOwner,
                    CameraSelector.DEFAULT_BACK_CAMERA,
                    preview,
                    analysis,
                )
            } catch (_: Exception) {
            }
        }

        cameraProviderFuture.addListener(listener, mainExecutor)

        onDispose {
            try {
                boundProvider?.unbindAll()
            } catch (_: Exception) {
            }
            analysisExecutor.shutdown()
        }
    }

    Dialog(
        onDismissRequest = onDismiss,
        properties = DialogProperties(usePlatformDefaultWidth = false),
    ) {
        Box(
            modifier = Modifier
                .fillMaxSize()
                .background(FlacifyCanvas),
        ) {
            AndroidView(
                factory = { previewView },
                modifier = Modifier.fillMaxSize(),
            )

            // Dark scrim top/bottom + centered emerald viewfinder
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(20.dp),
                verticalArrangement = Arrangement.SpaceBetween,
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Surface(
                        color = Color.Black.copy(alpha = 0.65f),
                        shape = RoundedCornerShape(999.dp),
                    ) {
                        Text(
                            text = "Scan Flacify PC Pairing QR",
                            style = MaterialTheme.typography.titleMedium,
                            color = FlacifyTextPrimary,
                            modifier = Modifier.padding(horizontal = 14.dp, vertical = 8.dp),
                        )
                    }
                    Surface(
                        color = Color.Black.copy(alpha = 0.65f),
                        shape = RoundedCornerShape(999.dp),
                    ) {
                        IconButton(onClick = onDismiss) {
                            Icon(
                                imageVector = Icons.Rounded.Close,
                                contentDescription = "Close scanner",
                                tint = FlacifyTextPrimary,
                            )
                        }
                    }
                }

                Box(
                    modifier = Modifier
                        .size(240.dp)
                        .border(
                            BorderStroke(2.5.dp, FlacifyEmeraldBright),
                            RoundedCornerShape(24.dp),
                        ),
                )

                Surface(
                    color = Color.Black.copy(alpha = 0.7f),
                    shape = RoundedCornerShape(14.dp),
                ) {
                    Text(
                        text = "Desktop -> Settings -> Mobile Sync -> QR Code",
                        style = MaterialTheme.typography.bodySmall,
                        color = FlacifyTextMuted,
                        modifier = Modifier.padding(horizontal = 16.dp, vertical = 10.dp),
                    )
                }
            }
        }
    }
}

private fun decodeQrFromImageProxy(
    imageProxy: ImageProxy,
    reader: MultiFormatReader,
): String? {
    val yPlane = imageProxy.planes.firstOrNull() ?: return null
    val width = imageProxy.width
    val height = imageProxy.height
    if (width <= 0 || height <= 0) return null

    val rowStride = yPlane.rowStride
    val buffer = yPlane.buffer
    val data = ByteArray(width * height)

    if (rowStride == width && buffer.remaining() >= width * height) {
        buffer.get(data, 0, width * height)
    } else {
        val rowBuffer = ByteArray(rowStride)
        for (row in 0 until height) {
            val bytesToRead = minOf(rowStride, buffer.remaining())
            if (bytesToRead <= 0) break
            buffer.get(rowBuffer, 0, bytesToRead)
            System.arraycopy(rowBuffer, 0, data, row * width, minOf(width, bytesToRead))
        }
    }

    val source = PlanarYUVLuminanceSource(
        data,
        width,
        height,
        0,
        0,
        width,
        height,
        false,
    )
    return try {
        reader.decodeWithState(BinaryBitmap(HybridBinarizer(source))).text
    } catch (_: NotFoundException) {
        null
    } catch (_: Exception) {
        null
    } finally {
        reader.reset()
    }
}
