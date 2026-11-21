package com.flacify.android

import com.flacify.android.ui.navigation.FlacifyDestination
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class FlacifyDestinationTest {
    @Test
    fun destinationsHaveUniqueNonBlankRoutesAndLabels() {
        val entries = FlacifyDestination.entries
        assertEquals(3, entries.size)
        assertTrue(entries.all { it.route.isNotBlank() && it.label.isNotBlank() })
        assertEquals(entries.size, entries.map { it.route }.distinct().size)
        assertEquals(entries.size, entries.map { it.label }.distinct().size)
    }

    @Test
    fun startDestinationIsPlaylistsAndFromRouteFallsBackCleanly() {
        assertEquals(FlacifyDestination.PLAYLISTS, FlacifyDestination.START_DESTINATION)
        assertEquals(FlacifyDestination.LIBRARY, FlacifyDestination.fromRoute("library"))
        assertEquals(FlacifyDestination.SYNC, FlacifyDestination.fromRoute("sync"))
        assertEquals(FlacifyDestination.PLAYLISTS, FlacifyDestination.fromRoute("unknown"))
        assertEquals(FlacifyDestination.PLAYLISTS, FlacifyDestination.fromRoute(null))
    }
}
