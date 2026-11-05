import 'package:audio_service/audio_service.dart';
import 'package:flutter/material.dart';
import '../../models/track_metadata.dart';
import '../../services/audio_player_service.dart';
import '../theme.dart';
import '../views/player_view.dart';

class MiniPlayerBar extends StatelessWidget {
  final AudioPlayerHandler audioHandler;

  const MiniPlayerBar({super.key, required this.audioHandler});

  @override
  Widget build(BuildContext context) {
    return StreamBuilder<MediaItem?>(
      stream: audioHandler.mediaItem,
      builder: (context, snapshot) {
        final track = audioHandler.currentTrack;
        if (track == null) return const SizedBox.shrink();

        return GestureDetector(
          onTap: () {
            Navigator.of(context).push(
              MaterialPageRoute(
                builder: (_) => PlayerView(audioHandler: audioHandler),
              ),
            );
          },
          child: Container(
            height: 64,
            margin: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
            decoration: BoxDecoration(
              color: FlacifyTheme.elevatedDark,
              borderRadius: BorderRadius.circular(10),
              boxShadow: [
                BoxShadow(
                  color: Colors.black.withOpacity(0.4),
                  blurRadius: 8,
                  offset: const Offset(0, 4),
                ),
              ],
            ),
            child: Column(
              children: [
                // Real-time progress bar slider line
                StreamBuilder<Duration>(
                  stream: audioHandler.player.positionStream,
                  builder: (context, posSnap) {
                    final pos = posSnap.data ?? Duration.zero;
                    final total = audioHandler.player.duration ?? Duration(milliseconds: track.durationMs);
                    final progress = total.inMilliseconds > 0
                        ? (pos.inMilliseconds / total.inMilliseconds).clamp(0.0, 1.0)
                        : 0.0;

                    return LinearProgressIndicator(
                      value: progress,
                      backgroundColor: Colors.transparent,
                      valueColor: const AlwaysStoppedAnimation<Color>(FlacifyTheme.spotifyEmerald),
                      minHeight: 2.5,
                    );
                  },
                ),
                Expanded(
                  child: Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 10),
                    child: Row(
                      children: [
                        // Cover art
                        ClipRRect(
                          borderRadius: BorderRadius.circular(6),
                          child: track.coverUrl.isNotEmpty
                              ? Image.network(
                                  track.coverUrl,
                                  width: 44,
                                  height: 44,
                                  fit: BoxFit.cover,
                                  errorBuilder: (_, __, ___) => _fallbackCover(),
                                )
                              : _fallbackCover(),
                        ),
                        const SizedBox(width: 12),
                        // Title & Artist
                        Expanded(
                          child: Column(
                            mainAxisAlignment: MainAxisAlignment.center,
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                track.title,
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                                style: const TextStyle(
                                  color: FlacifyTheme.textPrimary,
                                  fontWeight: FontWeight.bold,
                                  fontSize: 14,
                                ),
                              ),
                              Text(
                                track.artistStr,
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                                style: const TextStyle(
                                  color: FlacifyTheme.textSecondary,
                                  fontSize: 12,
                                ),
                              ),
                            ],
                          ),
                        ),
                        // Play / Pause Button
                        StreamBuilder<bool>(
                          stream: audioHandler.player.playingStream,
                          builder: (context, playSnap) {
                            final playing = playSnap.data ?? false;
                            return IconButton(
                              icon: Icon(
                                playing ? Icons.pause_circle_filled : Icons.play_circle_filled,
                                color: FlacifyTheme.textPrimary,
                                size: 36,
                              ),
                              onPressed: () {
                                if (playing) {
                                  audioHandler.pause();
                                } else {
                                  audioHandler.play();
                                }
                              },
                            );
                          },
                        ),
                        // Skip Next
                        IconButton(
                          icon: const Icon(
                            Icons.skip_next,
                            color: FlacifyTheme.textSecondary,
                            size: 28,
                          ),
                          onPressed: () => audioHandler.skipToNext(),
                        ),
                      ],
                    ),
                  ),
                ),
              ],
            ),
          ),
        );
      },
    );
  }

  Widget _fallbackCover() {
    return Container(
      width: 44,
      height: 44,
      color: Colors.grey[850],
      child: const Icon(Icons.music_note, color: FlacifyTheme.textSecondary),
    );
  }
}
