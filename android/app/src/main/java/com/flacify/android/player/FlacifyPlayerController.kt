package com.flacify.android.player

import android.content.ComponentName
import android.content.Context
import android.net.Uri
import androidx.core.content.ContextCompat
import androidx.media3.common.C
import androidx.media3.common.MediaItem
import androidx.media3.common.MediaMetadata
import androidx.media3.common.Player
import androidx.media3.session.MediaController
import androidx.media3.session.SessionToken
import com.flacify.android.data.db.TrackEntity
import com.google.common.util.concurrent.ListenableFuture
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File

enum class RepeatModeState {
    OFF,
    ALL,
    ONE,
}

data class PlayerUiState(
    val currentTrack: TrackEntity? = null,
    val queue: List<TrackEntity> = emptyList(),
    val currentIndex: Int = -1,
    val isPlaying: Boolean = false,
    val isBuffering: Boolean = false,
    val positionMs: Long = 0L,
    val durationMs: Long = 0L,
    val shuffleEnabled: Boolean = false,
    val repeatMode: RepeatModeState = RepeatModeState.OFF,
    val parsedLyrics: ParsedLyrics = ParsedLyrics(),
) {
    val hasTrack: Boolean
        get() = currentTrack != null
}

class FlacifyPlayerController(context: Context) {
    private val appContext = context.applicationContext
    private val mainScope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)

    private val _uiState = MutableStateFlow(PlayerUiState())
    val uiState: StateFlow<PlayerUiState> = _uiState.asStateFlow()

    private var controllerFuture: ListenableFuture<MediaController>? = null
    private var mediaController: MediaController? = null
    private var pendingPlayback: Pair<List<TrackEntity>, Int>? = null

    private var tickerJob: Job? = null
    private var lyricsJob: Job? = null
    private var loadedLyricsTrackId: String? = null

    private val playerListener = object : Player.Listener {
        override fun onIsPlayingChanged(isPlaying: Boolean) {
            syncFromController()
            if (isPlaying) startTicker() else stopTicker()
        }

        override fun onPlaybackStateChanged(playbackState: Int) {
            syncFromController()
        }

        override fun onMediaItemTransition(mediaItem: MediaItem?, reason: Int) {
            syncFromController()
        }

        override fun onShuffleModeEnabledChanged(shuffleModeEnabled: Boolean) {
            syncFromController()
        }

        override fun onRepeatModeChanged(repeatMode: Int) {
            syncFromController()
        }

        override fun onTimelineChanged(timeline: androidx.media3.common.Timeline, reason: Int) {
            syncFromController()
        }
    }

    fun playQueue(tracks: List<TrackEntity>, startIndex: Int) {
        val playable = tracks.filter { track ->
            val path = track.localFilePath
            !path.isNullOrBlank() && File(path).isFile
        }
        if (playable.isEmpty()) return

        val requestedTrackId = tracks.getOrNull(startIndex)?.id
        val safeIndex = requestedTrackId
            ?.let { id -> playable.indexOfFirst { it.id == id } }
            ?.takeIf { it >= 0 }
            ?: startIndex.coerceIn(0, playable.lastIndex)

        mainScope.launch {
            val active = mediaController
            if (active != null && active.isConnected) {
                applyQueue(active, playable, safeIndex)
            } else {
                pendingPlayback = playable to safeIndex
                connectControllerIfNeeded()
            }
        }
    }

    fun togglePlayPause() {
        mainScope.launch {
            val c = mediaController ?: return@launch
            if (c.isPlaying) {
                c.pause()
            } else {
                if (c.playbackState == Player.STATE_ENDED && c.mediaItemCount > 0) {
                    c.seekTo(0, 0L)
                }
                c.play()
            }
        }
    }

    fun skipNext() {
        mainScope.launch {
            val c = mediaController ?: return@launch
            if (c.hasNextMediaItem()) {
                c.seekToNextMediaItem()
            } else if (c.mediaItemCount > 0) {
                c.seekTo(0, 0L)
            }
        }
    }

    fun skipPrevious() {
        mainScope.launch {
            val c = mediaController ?: return@launch
            if (c.currentPosition > 3500L) {
                c.seekTo(0L)
            } else if (c.hasPreviousMediaItem()) {
                c.seekToPreviousMediaItem()
            } else {
                c.seekTo(0L)
            }
        }
    }

    fun seekTo(positionMs: Long) {
        mainScope.launch {
            val c = mediaController ?: return@launch
            val clamped = positionMs.coerceAtLeast(0L)
            c.seekTo(clamped)
            _uiState.update { it.copy(positionMs = clamped) }
        }
    }

    fun toggleShuffle() {
        mainScope.launch {
            val c = mediaController ?: return@launch
            c.shuffleModeEnabled = !c.shuffleModeEnabled
        }
    }

    fun cycleRepeatMode() {
        mainScope.launch {
            val c = mediaController ?: return@launch
            c.repeatMode = when (c.repeatMode) {
                Player.REPEAT_MODE_OFF -> Player.REPEAT_MODE_ALL
                Player.REPEAT_MODE_ALL -> Player.REPEAT_MODE_ONE
                else -> Player.REPEAT_MODE_OFF
            }
        }
    }

    fun skipToQueueIndex(index: Int) {
        mainScope.launch {
            val c = mediaController ?: return@launch
            if (index in 0 until c.mediaItemCount) {
                c.seekTo(index, 0L)
                c.play()
            }
        }
    }

    fun removeFromQueue(index: Int) {
        mainScope.launch {
            val c = mediaController ?: return@launch
            val curQueue = _uiState.value.queue
            if (index !in curQueue.indices) return@launch

            val updatedQueue = curQueue.toMutableList().apply { removeAt(index) }
            _uiState.update { it.copy(queue = updatedQueue) }
            c.removeMediaItem(index)
            syncFromController()
        }
    }

    private fun connectControllerIfNeeded() {
        if (controllerFuture != null) return
        val token = SessionToken(
            appContext,
            ComponentName(appContext, FlacifyPlaybackService::class.java),
        )
        val future = MediaController.Builder(appContext, token).buildAsync()
        controllerFuture = future

        future.addListener(
            {
                try {
                    val controller = future.get()
                    mediaController = controller
                    controller.addListener(playerListener)
                    val pending = pendingPlayback
                    pendingPlayback = null
                    if (pending != null) {
                        applyQueue(controller, pending.first, pending.second)
                    } else {
                        syncFromController()
                    }
                } catch (_: Exception) {
                    controllerFuture = null
                }
            },
            ContextCompat.getMainExecutor(appContext),
        )
    }

    private fun applyQueue(
        controller: MediaController,
        playable: List<TrackEntity>,
        startIndex: Int,
    ) {
        val mediaItems = playable.map { track -> buildMediaItem(track) }
        _uiState.update { cur ->
            val selected = playable.getOrNull(startIndex)
            cur.copy(
                queue = playable,
                currentTrack = selected,
                currentIndex = startIndex,
                durationMs = selected?.durationMs ?: 0L,
                positionMs = 0L,
            )
        }
        controller.setMediaItems(mediaItems, startIndex, 0L)
        controller.prepare()
        controller.play()
        syncFromController()
    }

    private fun buildMediaItem(track: TrackEntity): MediaItem {
        val fileUri = Uri.fromFile(File(track.localFilePath!!))
        val coverPath = track.localCoverPath?.takeIf { File(it).isFile }
        val metadataBuilder = MediaMetadata.Builder()
            .setTitle(track.title.ifBlank { "Untitled Track" })
            .setArtist(track.artist.ifBlank { "Unknown Artist" })
            .setAlbumTitle(track.album)
        if (coverPath != null) {
            metadataBuilder.setArtworkUri(Uri.fromFile(File(coverPath)))
        }
        return MediaItem.Builder()
            .setMediaId(track.id)
            .setUri(fileUri)
            .setMediaMetadata(metadataBuilder.build())
            .build()
    }

    private fun syncFromController() {
        val c = mediaController ?: return
        val curQueue = _uiState.value.queue
        val idx = c.currentMediaItemIndex
        val mediaId = c.currentMediaItem?.mediaId
        val resolvedTrack = when {
            mediaId != null -> curQueue.firstOrNull { it.id == mediaId } ?: curQueue.getOrNull(idx)
            idx in curQueue.indices -> curQueue[idx]
            else -> null
        }

        val controllerDur = c.duration
        val effectiveDuration = when {
            controllerDur != C.TIME_UNSET && controllerDur > 0L -> controllerDur
            else -> resolvedTrack?.durationMs ?: 0L
        }

        val repeatState = when (c.repeatMode) {
            Player.REPEAT_MODE_ALL -> RepeatModeState.ALL
            Player.REPEAT_MODE_ONE -> RepeatModeState.ONE
            else -> RepeatModeState.OFF
        }

        _uiState.update { cur ->
            cur.copy(
                currentTrack = resolvedTrack,
                currentIndex = if (idx in curQueue.indices) idx else cur.currentIndex,
                isPlaying = c.isPlaying,
                isBuffering = c.playbackState == Player.STATE_BUFFERING,
                positionMs = c.currentPosition.coerceAtLeast(0L),
                durationMs = effectiveDuration,
                shuffleEnabled = c.shuffleModeEnabled,
                repeatMode = repeatState,
            )
        }

        if (resolvedTrack != null && resolvedTrack.id != loadedLyricsTrackId) {
            loadLyricsForTrack(resolvedTrack)
        } else if (resolvedTrack == null) {
            loadedLyricsTrackId = null
            _uiState.update { it.copy(parsedLyrics = ParsedLyrics()) }
        }
    }

    private fun loadLyricsForTrack(track: TrackEntity) {
        loadedLyricsTrackId = track.id
        lyricsJob?.cancel()
        lyricsJob = mainScope.launch {
            val parsed = withContext(Dispatchers.IO) {
                val cached = track.lyricsText?.takeIf { it.isNotBlank() }
                val raw = cached ?: track.localFilePath
                    ?.takeIf { it.isNotBlank() }
                    ?.let { FlacLyricsExtractor.extractFromFile(File(it)) }
                LrcParser.parse(raw)
            }
            if (_uiState.value.currentTrack?.id == track.id) {
                _uiState.update { it.copy(parsedLyrics = parsed) }
            }
        }
    }

    private fun startTicker() {
        if (tickerJob?.isActive == true) return
        tickerJob = mainScope.launch {
            while (isActive) {
                val c = mediaController
                if (c != null && c.isPlaying) {
                    val dur = c.duration
                    _uiState.update { cur ->
                        cur.copy(
                            positionMs = c.currentPosition.coerceAtLeast(0L),
                            durationMs = if (dur != C.TIME_UNSET && dur > 0L) dur else cur.durationMs,
                        )
                    }
                }
                delay(250L)
            }
        }
    }

    private fun stopTicker() {
        tickerJob?.cancel()
        tickerJob = null
    }
}
