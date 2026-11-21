package com.flacify.android.ui

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.GraphicEq
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationBarItemDefaults
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation.NavGraph.Companion.findStartDestination
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import com.flacify.android.FlacifyApplication
import com.flacify.android.data.db.TrackEntity
import com.flacify.android.ui.library.LibraryScreen
import com.flacify.android.ui.library.LibraryViewModel
import com.flacify.android.ui.navigation.FlacifyDestination
import com.flacify.android.ui.player.MiniPlayerBar
import com.flacify.android.ui.player.NowPlayingSheet
import com.flacify.android.ui.playlists.PlaylistDetailScreen
import com.flacify.android.ui.playlists.PlaylistDetailViewModel
import com.flacify.android.ui.playlists.PlaylistsScreen
import com.flacify.android.ui.playlists.PlaylistsViewModel
import com.flacify.android.ui.sync.SyncScreen
import com.flacify.android.ui.sync.SyncViewModel
import com.flacify.android.ui.theme.FlacifyBorder
import com.flacify.android.ui.theme.FlacifyCanvas
import com.flacify.android.ui.theme.FlacifyCardSurface
import com.flacify.android.ui.theme.FlacifyEmerald
import com.flacify.android.ui.theme.FlacifyEmeraldBright
import com.flacify.android.ui.theme.FlacifyTextMuted
import com.flacify.android.ui.theme.FlacifyTextPrimary
import kotlinx.coroutines.launch
import java.util.Base64

private const val ROUTE_PLAYLIST_DETAIL = "playlist_detail/{encodedId}"

private fun encodeRouteId(rawId: String): String =
    Base64.getUrlEncoder().withoutPadding().encodeToString(rawId.toByteArray(Charsets.UTF_8))

private fun decodeRouteId(encoded: String): String =
    try {
        String(Base64.getUrlDecoder().decode(encoded), Charsets.UTF_8)
    } catch (_: Exception) {
        encoded
    }

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun FlacifyApp(
    incomingPairingUri: String? = null,
    onPairingUriConsumed: () -> Unit = {},
) {
    val app = LocalContext.current.applicationContext as FlacifyApplication
    val syncViewModel: SyncViewModel = viewModel(factory = SyncViewModel.Factory(app))
    val playlistsViewModel: PlaylistsViewModel = viewModel(factory = PlaylistsViewModel.Factory(app))
    val libraryViewModel: LibraryViewModel = viewModel(factory = LibraryViewModel.Factory(app))

    val syncState by syncViewModel.uiState.collectAsStateWithLifecycle()
    val playerState by app.playerController.uiState.collectAsStateWithLifecycle()
    var showNowPlaying by remember { mutableStateOf(false) }

    val navController = rememberNavController()
    val backStackEntry by navController.currentBackStackEntryAsState()
    val currentRoute = backStackEntry?.destination?.route
    val isDetailRoute = currentRoute?.startsWith("playlist_detail/") == true

    val snackbarHostState = remember { SnackbarHostState() }
    val coroutineScope = rememberCoroutineScope()

    fun navigateToTab(destination: FlacifyDestination) {
        navController.navigate(destination.route) {
            popUpTo(navController.graph.findStartDestination().id) {
                saveState = true
            }
            launchSingleTop = true
            restoreState = true
        }
    }

    fun handleTrackSelected(
        queue: List<TrackEntity>,
        startIndex: Int,
        title: String,
        isOffline: Boolean,
    ) {
        if (isOffline && queue.isNotEmpty()) {
            app.playerController.playQueue(queue, startIndex)
        } else {
            coroutineScope.launch {
                snackbarHostState.currentSnackbarData?.dismiss()
                snackbarHostState.showSnackbar(
                    "'$title' is PC-only — enable its playlist in Sync to download offline FLAC."
                )
            }
        }
    }

    LaunchedEffect(incomingPairingUri) {
        if (!incomingPairingUri.isNullOrBlank()) {
            navigateToTab(FlacifyDestination.SYNC)
            syncViewModel.applyPairingUri(incomingPairingUri, autoConnect = true)
            onPairingUriConsumed()
        }
    }

    if (showNowPlaying && playerState.hasTrack) {
        NowPlayingSheet(
            playerState = playerState,
            activeBaseUrl = syncState.connectionConfig.activeUrl,
            onDismiss = { showNowPlaying = false },
            onTogglePlayPause = { app.playerController.togglePlayPause() },
            onPrevious = { app.playerController.skipPrevious() },
            onNext = { app.playerController.skipNext() },
            onSeek = { pos -> app.playerController.seekTo(pos) },
            onToggleShuffle = { app.playerController.toggleShuffle() },
            onCycleRepeat = { app.playerController.cycleRepeatMode() },
            onSkipToQueueIndex = { idx -> app.playerController.skipToQueueIndex(idx) },
            onRemoveFromQueue = { idx -> app.playerController.removeFromQueue(idx) },
        )
    }

    Scaffold(
        modifier = Modifier.fillMaxSize(),
        containerColor = FlacifyCanvas,
        snackbarHost = { SnackbarHost(hostState = snackbarHostState) },
        topBar = {
            if (!isDetailRoute) {
                TopAppBar(
                    title = {
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
                                text = "Flacify",
                                style = MaterialTheme.typography.titleMedium,
                                color = FlacifyTextPrimary,
                            )
                            Surface(
                                color = FlacifyEmerald.copy(alpha = 0.14f),
                                shape = RoundedCornerShape(999.dp),
                                border = BorderStroke(1.dp, FlacifyEmerald.copy(alpha = 0.35f)),
                            ) {
                                Text(
                                    text = "FLAC",
                                    style = MaterialTheme.typography.labelSmall,
                                    color = FlacifyEmeraldBright,
                                    modifier = Modifier.padding(horizontal = 8.dp, vertical = 2.dp),
                                )
                            }
                        }
                    },
                    colors = TopAppBarDefaults.topAppBarColors(
                        containerColor = FlacifyCanvas,
                        titleContentColor = FlacifyTextPrimary,
                    ),
                )
            }
        },
        bottomBar = {
            Column {
                if (playerState.hasTrack) {
                    MiniPlayerBar(
                        playerState = playerState,
                        activeBaseUrl = syncState.connectionConfig.activeUrl,
                        onExpand = { showNowPlaying = true },
                        onTogglePlayPause = { app.playerController.togglePlayPause() },
                        onPrevious = { app.playerController.skipPrevious() },
                        onNext = { app.playerController.skipNext() },
                    )
                }
                HorizontalDivider(color = FlacifyBorder, thickness = 1.dp)
                NavigationBar(
                    containerColor = FlacifyCardSurface,
                    tonalElevation = 0.dp,
                ) {
                    FlacifyDestination.entries.forEach { destination ->
                        val selected = currentRoute == destination.route ||
                            (isDetailRoute && destination == FlacifyDestination.PLAYLISTS)
                        NavigationBarItem(
                            selected = selected,
                            onClick = { navigateToTab(destination) },
                            icon = {
                                Icon(
                                    imageVector = destination.icon,
                                    contentDescription = destination.label,
                                )
                            },
                            label = {
                                Text(
                                    text = destination.label,
                                    style = MaterialTheme.typography.labelMedium,
                                )
                            },
                            colors = NavigationBarItemDefaults.colors(
                                selectedIconColor = FlacifyEmeraldBright,
                                selectedTextColor = FlacifyEmeraldBright,
                                indicatorColor = FlacifyEmerald.copy(alpha = 0.16f),
                                unselectedIconColor = FlacifyTextMuted,
                                unselectedTextColor = FlacifyTextMuted,
                            ),
                        )
                    }
                }
            }
        },
    ) { innerPadding ->
        NavHost(
            navController = navController,
            startDestination = FlacifyDestination.START_DESTINATION.route,
            modifier = Modifier
                .fillMaxSize()
                .padding(innerPadding),
        ) {
            composable(FlacifyDestination.PLAYLISTS.route) {
                PlaylistsScreen(
                    viewModel = playlistsViewModel,
                    onPlaylistClick = { plId ->
                        navController.navigate("playlist_detail/${encodeRouteId(plId)}")
                    },
                    onOpenSyncTab = { navigateToTab(FlacifyDestination.SYNC) },
                )
            }
            composable(
                route = ROUTE_PLAYLIST_DETAIL,
                arguments = listOf(navArgument("encodedId") { type = NavType.StringType }),
            ) { entry ->
                val rawEncoded = entry.arguments?.getString("encodedId").orEmpty()
                val playlistId = remember(rawEncoded) { decodeRouteId(rawEncoded) }
                val detailViewModel: PlaylistDetailViewModel = viewModel(
                    key = "playlist_detail_$playlistId",
                    factory = PlaylistDetailViewModel.Factory(app, playlistId),
                )
                PlaylistDetailScreen(
                    viewModel = detailViewModel,
                    onBack = { navController.popBackStack() },
                    onTrackSelected = { queue, idx, title, isOffline ->
                        handleTrackSelected(queue, idx, title, isOffline)
                    },
                )
            }
            composable(FlacifyDestination.LIBRARY.route) {
                LibraryScreen(
                    viewModel = libraryViewModel,
                    onTrackSelected = { queue, idx, title, isOffline ->
                        handleTrackSelected(queue, idx, title, isOffline)
                    },
                    onOpenSyncTab = { navigateToTab(FlacifyDestination.SYNC) },
                )
            }
            composable(FlacifyDestination.SYNC.route) {
                SyncScreen(viewModel = syncViewModel)
            }
        }
    }
}
