import 'dart:async';
import 'package:flutter/material.dart' hide RepeatMode;
import '../../models/lyrics_model.dart';
import '../../services/audio_player_service.dart';
import '../theme.dart';

class PlayerView extends StatefulWidget {
  final AudioPlayerHandler audioHandler;

  const PlayerView({super.key, required this.audioHandler});

  @override
  State<PlayerView> createState() => _PlayerViewState();
}

class _PlayerViewState extends State<PlayerView> {
  bool _showLyrics = false;
  LyricsData? _lyrics;
  final ScrollController _scrollController = ScrollController();
  int _activeLyricIndex = -1;
  StreamSubscription? _mediaItemSub;

  @override
  void initState() {
    super.initState();
    _loadLyrics();
    _mediaItemSub = widget.audioHandler.mediaItem.listen((_) {
      _loadLyrics();
      if (mounted) setState(() {});
    });
  }

  @override
  void dispose() {
    _mediaItemSub?.cancel();
    _scrollController.dispose();
    super.dispose();
  }

  Future<void> _loadLyrics() async {
    final lrc = await widget.audioHandler.loadCurrentLyrics();
    if (mounted) {
      setState(() {
        _lyrics = lrc;
      });
    }
  }

  void _scrollToActiveLyric(int index) {
    if (_activeLyricIndex == index) return;
    _activeLyricIndex = index;
    if (_scrollController.hasClients && index >= 0) {
      final targetOffset = (index * 48.0) - 150.0;
      _scrollController.animateTo(
        targetOffset.clamp(0.0, _scrollController.position.maxScrollExtent),
        duration: const Duration(milliseconds: 300),
        curve: Curves.easeInOut,
      );
    }
  }

  String _formatDuration(Duration d) {
    final minutes = d.inMinutes;
    final seconds = d.inSeconds % 60;
    return '$minutes:${seconds.toString().padLeft(2, '0')}';
  }

  @override
  Widget build(BuildContext context) {
    final track = widget.audioHandler.currentTrack;
    if (track == null) {
      return Scaffold(
        appBar: AppBar(),
        body: const Center(child: Text('No track loaded')),
      );
    }

    return Scaffold(
      backgroundColor: FlacifyTheme.spotifyBlack,
      appBar: AppBar(
        leading: IconButton(
          icon: const Icon(Icons.keyboard_arrow_down, size: 32),
          onPressed: () => Navigator.of(context).pop(),
        ),
        title: Column(
          children: [
            const Text(
              'PLAYING FROM LIBRARY',
              style: TextStyle(fontSize: 11, letterSpacing: 1.2, color: FlacifyTheme.textSecondary),
            ),
            Text(
              track.album,
              style: const TextStyle(fontSize: 13, fontWeight: FontWeight.bold),
            ),
          ],
        ),
        centerTitle: true,
        actions: [
          IconButton(
            icon: Icon(
              _showLyrics ? Icons.music_note : Icons.lyrics,
              color: _showLyrics ? FlacifyTheme.spotifyEmerald : FlacifyTheme.textSecondary,
            ),
            onPressed: () {
              setState(() {
                _showLyrics = !_showLyrics;
              });
            },
          ),
        ],
      ),
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 12),
          child: Column(
            children: [
              // Cover Art or Synchronized Lyrics View
              Expanded(
                child: _showLyrics ? _buildLyricsView() : _buildCoverView(track.coverUrl),
              ),
              const SizedBox(height: 20),

              // Title & Artist Header
              Row(
                children: [
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          track.title,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(
                            fontSize: 22,
                            fontWeight: FontWeight.bold,
                            color: FlacifyTheme.textPrimary,
                          ),
                        ),
                        const SizedBox(height: 4),
                        Text(
                          track.artistStr,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(
                            fontSize: 16,
                            color: FlacifyTheme.textSecondary,
                          ),
                        ),
                      ],
                    ),
                  ),
                  if (track.qualityBadge != null)
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                      decoration: BoxDecoration(
                        color: FlacifyTheme.elevatedDark,
                        borderRadius: BorderRadius.circular(4),
                        border: Border.all(color: FlacifyTheme.spotifyEmerald.withValues(alpha: 0.4)),
                      ),
                      child: Text(
                        track.qualityBadge!,
                        style: const TextStyle(
                          color: FlacifyTheme.spotifyEmerald,
                          fontSize: 11,
                          fontWeight: FontWeight.bold,
                        ),
                      ),
                    ),
                ],
              ),
              const SizedBox(height: 16),

              // Seek Slider & Timestamps
              StreamBuilder<Duration>(
                stream: widget.audioHandler.player.positionStream,
                builder: (context, snap) {
                  final pos = snap.data ?? Duration.zero;
                  final total = widget.audioHandler.player.duration ?? Duration(milliseconds: track.durationMs);

                  return Column(
                    children: [
                      SliderTheme(
                        data: SliderTheme.of(context).copyWith(
                          trackHeight: 3,
                          thumbShape: const RoundSliderThumbShape(enabledThumbRadius: 6),
                          overlayShape: const RoundSliderOverlayShape(overlayRadius: 14),
                          activeTrackColor: FlacifyTheme.textPrimary,
                          inactiveTrackColor: Colors.white24,
                          thumbColor: FlacifyTheme.textPrimary,
                        ),
                        child: Slider(
                          value: pos.inMilliseconds.toDouble().clamp(0.0, total.inMilliseconds.toDouble()),
                          max: total.inMilliseconds > 0 ? total.inMilliseconds.toDouble() : 1.0,
                          onChanged: (val) {
                            widget.audioHandler.seek(Duration(milliseconds: val.toInt()));
                          },
                        ),
                      ),
                      Padding(
                        padding: const EdgeInsets.symmetric(horizontal: 16),
                        child: Row(
                          mainAxisAlignment: MainAxisAlignment.spaceBetween,
                          children: [
                            Text(
                              _formatDuration(pos),
                              style: const TextStyle(color: FlacifyTheme.textSecondary, fontSize: 12),
                            ),
                            Text(
                              _formatDuration(total),
                              style: const TextStyle(color: FlacifyTheme.textSecondary, fontSize: 12),
                            ),
                          ],
                        ),
                      ),
                    ],
                  );
                },
              ),
              const SizedBox(height: 12),

              // Playback Controls Row
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceEvenly,
                children: [
                  ValueListenableBuilder<bool>(
                    valueListenable: widget.audioHandler.shuffleNotifier,
                    builder: (context, shuffleEnabled, _) {
                      return IconButton(
                        icon: Icon(
                          Icons.shuffle,
                          color: shuffleEnabled ? FlacifyTheme.spotifyEmerald : FlacifyTheme.textSecondary,
                          size: 24,
                        ),
                        onPressed: () {
                          widget.audioHandler.toggleShuffle();
                        },
                      );
                    },
                  ),
                  IconButton(
                    icon: const Icon(Icons.skip_previous, color: FlacifyTheme.textPrimary, size: 40),
                    onPressed: () async {
                      await widget.audioHandler.skipToPrevious();
                      _loadLyrics();
                    },
                  ),
                  StreamBuilder<bool>(
                    stream: widget.audioHandler.player.playingStream,
                    builder: (context, playSnap) {
                      final playing = playSnap.data ?? false;
                      return Container(
                        decoration: const BoxDecoration(
                          shape: BoxShape.circle,
                          color: FlacifyTheme.textPrimary,
                        ),
                        child: IconButton(
                          icon: Icon(
                            playing ? Icons.pause : Icons.play_arrow,
                            color: Colors.black,
                            size: 38,
                          ),
                          onPressed: () {
                            if (playing) {
                              widget.audioHandler.pause();
                            } else {
                              widget.audioHandler.play();
                            }
                          },
                        ),
                      );
                    },
                  ),
                  IconButton(
                    icon: const Icon(Icons.skip_next, color: FlacifyTheme.textPrimary, size: 40),
                    onPressed: () async {
                      await widget.audioHandler.skipToNext();
                      _loadLyrics();
                    },
                  ),
                  ValueListenableBuilder<RepeatMode>(
                    valueListenable: widget.audioHandler.repeatNotifier,
                    builder: (context, repeatMode, _) {
                      final isActive = repeatMode != RepeatMode.off;
                      final isOne = repeatMode == RepeatMode.one;
                      return IconButton(
                        icon: Icon(
                          isOne ? Icons.repeat_one : Icons.repeat,
                          color: isActive ? FlacifyTheme.spotifyEmerald : FlacifyTheme.textSecondary,
                          size: 24,
                        ),
                        onPressed: () {
                          widget.audioHandler.cycleRepeatMode();
                        },
                      );
                    },
                  ),
                ],
              ),
              const SizedBox(height: 16),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildCoverView(String coverUrl) {
    return Center(
      child: AspectRatio(
        aspectRatio: 1.0,
        child: Container(
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(16),
            boxShadow: [
              BoxShadow(
                color: Colors.black.withValues(alpha: 0.6),
                blurRadius: 20,
                offset: const Offset(0, 10),
              ),
            ],
          ),
          child: ClipRRect(
            borderRadius: BorderRadius.circular(16),
            child: coverUrl.isNotEmpty
                ? Image.network(
                    coverUrl,
                    fit: BoxFit.cover,
                    errorBuilder: (_, __, ___) => _fallbackCover(),
                  )
                : _fallbackCover(),
          ),
        ),
      ),
    );
  }

  Widget _buildLyricsView() {
    if (_lyrics == null || _lyrics!.lines.isEmpty) {
      return const Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(Icons.lyrics_outlined, size: 48, color: FlacifyTheme.textSecondary),
            SizedBox(height: 12),
            Text(
              'No synchronized lyrics available for this track',
              style: TextStyle(color: FlacifyTheme.textSecondary, fontSize: 14),
            ),
          ],
        ),
      );
    }

    return StreamBuilder<Duration>(
      stream: widget.audioHandler.player.positionStream,
      builder: (context, posSnap) {
        final currentMs = (posSnap.data ?? Duration.zero).inMilliseconds;

        // Find current lyric line using binary search
        final activeIdx = _lyrics!.activeLineIndexAt(currentMs);
        final activeIndex = activeIdx >= 0 ? activeIdx : 0;

        WidgetsBinding.instance.addPostFrameCallback((_) {
          if (mounted) _scrollToActiveLyric(activeIndex);
        });

        return ListView.builder(
          controller: _scrollController,
          itemCount: _lyrics!.lines.length,
          itemBuilder: (context, i) {
            final line = _lyrics!.lines[i];
            final isActive = i == activeIndex;

            return GestureDetector(
              onTap: () {
                widget.audioHandler.seek(Duration(milliseconds: line.timestampMs));
              },
              child: AnimatedDefaultTextStyle(
                duration: const Duration(milliseconds: 200),
                style: TextStyle(
                  fontSize: isActive ? 24 : 17,
                  fontWeight: isActive ? FontWeight.bold : FontWeight.normal,
                  color: isActive ? FlacifyTheme.spotifyEmerald : FlacifyTheme.textSecondary.withValues(alpha: 0.5),
                  height: 1.6,
                ),
                child: Padding(
                  padding: const EdgeInsets.symmetric(vertical: 8),
                  child: Text(line.text),
                ),
              ),
            );
          },
        );
      },
    );
  }

  Widget _fallbackCover() {
    return Container(
      color: FlacifyTheme.elevatedDark,
      child: const Center(
        child: Icon(Icons.music_note, size: 80, color: FlacifyTheme.textSecondary),
      ),
    );
  }
}

