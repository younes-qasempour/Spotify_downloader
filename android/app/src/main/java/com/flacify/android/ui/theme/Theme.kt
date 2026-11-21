package com.flacify.android.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

private val FlacifyDarkColorScheme = darkColorScheme(
    primary = FlacifyEmerald,
    onPrimary = Color(0xFF032219),
    primaryContainer = Color(0xFF064E3B),
    onPrimaryContainer = FlacifyEmeraldBright,
    secondary = FlacifySkyAccent,
    onSecondary = Color(0xFF082F49),
    secondaryContainer = Color(0xFF0C4A6E),
    onSecondaryContainer = Color(0xFFBAE6FD),
    tertiary = FlacifyAmberAccent,
    onTertiary = Color(0xFF451A03),
    background = FlacifyCanvas,
    onBackground = FlacifyTextPrimary,
    surface = FlacifyCardSurface,
    onSurface = FlacifyTextPrimary,
    surfaceVariant = FlacifyElevatedSurface,
    onSurfaceVariant = FlacifyTextMuted,
    outline = FlacifyBorder,
    outlineVariant = FlacifyBorder,
    error = FlacifyDanger,
    onError = Color.White,
)

@Composable
fun FlacifyTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = FlacifyDarkColorScheme,
        typography = FlacifyTypography,
        content = content,
    )
}
