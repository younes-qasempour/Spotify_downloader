package com.flacify.android

import android.content.Intent
import android.graphics.Color
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.SystemBarStyle
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import com.flacify.android.ui.FlacifyApp
import com.flacify.android.ui.theme.FlacifyTheme

class MainActivity : ComponentActivity() {
    private var incomingPairingUri by mutableStateOf<String?>(null)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        handleIncomingIntent(intent)

        enableEdgeToEdge(
            statusBarStyle = SystemBarStyle.dark(Color.TRANSPARENT),
            navigationBarStyle = SystemBarStyle.dark(Color.TRANSPARENT),
        )
        setContent {
            FlacifyTheme {
                FlacifyApp(
                    incomingPairingUri = incomingPairingUri,
                    onPairingUriConsumed = { incomingPairingUri = null },
                )
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        handleIncomingIntent(intent)
    }

    private fun handleIncomingIntent(intent: Intent?) {
        val dataUri = intent?.data ?: return
        if (dataUri.scheme.equals("flacify", ignoreCase = true) &&
            dataUri.host.equals("pair", ignoreCase = true)
        ) {
            incomingPairingUri = dataUri.toString()
        }
    }
}
