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
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation.NavGraph.Companion.findStartDestination
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import com.flacify.android.FlacifyApplication
import com.flacify.android.ui.navigation.FlacifyDestination
import com.flacify.android.ui.screens.LibraryScreen
import com.flacify.android.ui.screens.PlaylistsScreen
import com.flacify.android.ui.sync.SyncScreen
import com.flacify.android.ui.sync.SyncViewModel
import com.flacify.android.ui.theme.FlacifyBorder
import com.flacify.android.ui.theme.FlacifyCanvas
import com.flacify.android.ui.theme.FlacifyCardSurface
import com.flacify.android.ui.theme.FlacifyEmerald
import com.flacify.android.ui.theme.FlacifyEmeraldBright
import com.flacify.android.ui.theme.FlacifyTextMuted
import com.flacify.android.ui.theme.FlacifyTextPrimary

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun FlacifyApp(
    incomingPairingUri: String? = null,
    onPairingUriConsumed: () -> Unit = {},
) {
    val app = LocalContext.current.applicationContext as FlacifyApplication
    val syncViewModel: SyncViewModel = viewModel(factory = SyncViewModel.Factory(app))
    val syncState by syncViewModel.uiState.collectAsStateWithLifecycle()

    val navController = rememberNavController()
    val backStackEntry by navController.currentBackStackEntryAsState()
    val currentRoute = backStackEntry?.destination?.route

    fun navigateToTab(destination: FlacifyDestination) {
        navController.navigate(destination.route) {
            popUpTo(navController.graph.findStartDestination().id) {
                saveState = true
            }
            launchSingleTop = true
            restoreState = true
        }
    }

    LaunchedEffect(incomingPairingUri) {
        if (!incomingPairingUri.isNullOrBlank()) {
            navigateToTab(FlacifyDestination.SYNC)
            syncViewModel.applyPairingUri(incomingPairingUri, autoConnect = true)
            onPairingUriConsumed()
        }
    }

    Scaffold(
        modifier = Modifier.fillMaxSize(),
        containerColor = FlacifyCanvas,
        topBar = {
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
        },
        bottomBar = {
            Column {
                HorizontalDivider(color = FlacifyBorder, thickness = 1.dp)
                NavigationBar(
                    containerColor = FlacifyCardSurface,
                    tonalElevation = 0.dp,
                ) {
                    FlacifyDestination.entries.forEach { destination ->
                        val selected = currentRoute == destination.route
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
                    syncState = syncState,
                    onOpenSyncTab = { navigateToTab(FlacifyDestination.SYNC) },
                )
            }
            composable(FlacifyDestination.LIBRARY.route) {
                LibraryScreen(
                    syncState = syncState,
                    onOpenSyncTab = { navigateToTab(FlacifyDestination.SYNC) },
                )
            }
            composable(FlacifyDestination.SYNC.route) {
                SyncScreen(viewModel = syncViewModel)
            }
        }
    }
}
