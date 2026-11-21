package com.flacify.android.ui.navigation

import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.QueueMusic
import androidx.compose.material.icons.rounded.LibraryMusic
import androidx.compose.material.icons.rounded.Sync
import androidx.compose.ui.graphics.vector.ImageVector

enum class FlacifyDestination(
    val route: String,
    val label: String,
    val icon: ImageVector,
) {
    PLAYLISTS(
        route = "playlists",
        label = "Playlists",
        icon = Icons.AutoMirrored.Rounded.QueueMusic,
    ),
    LIBRARY(
        route = "library",
        label = "Library",
        icon = Icons.Rounded.LibraryMusic,
    ),
    SYNC(
        route = "sync",
        label = "Sync",
        icon = Icons.Rounded.Sync,
    );

    companion object {
        val START_DESTINATION = PLAYLISTS

        fun fromRoute(route: String?): FlacifyDestination =
            entries.firstOrNull { it.route == route } ?: START_DESTINATION
    }
}
