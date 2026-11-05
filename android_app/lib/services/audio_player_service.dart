import 'dart:io';
import 'package:audio_service/audio_service.dart';
import 'package:just_audio/just_audio.dart';
import 'package:path/path.dart' as p;
import '../models/lyrics_model.dart';
import '../models/track_metadata.dart';

class AudioPlayerHandler extends BaseAudioHandler with SeekHandler {
  final AudioPlayer _player = AudioPlayer();
  List<TrackMetadata> _playlist = [];
  int _currentIndex = -1;

  AudioPlayer get player => _player;
  List<TrackMetadata> get playlist => _playlist;
  int get currentIndex => _currentIndex;
  TrackMetadata? get currentTrack =>
      (_currentIndex >= 0 && _currentIndex < _playlist.length)
          ? _playlist[_currentIndex]
          : null;

  AudioPlayerHandler() {
    _initPlayer();
  }

  void _initPlayer() {
    _player.playbackEventStream.listen((PlaybackEvent event) {
      final playing = _player.playing;
      playbackState.add(playbackState.value.copyWith(
        controls: [
          MediaControl.skipToPrevious,
          if (playing) MediaControl.pause else MediaControl.play,
          MediaControl.skipToNext,
        ],
        systemActions: const {
          MediaAction.seek,
          MediaAction.seekForward,
          MediaAction.seekBackward,
        },
        androidCompactActionIndices: const [0, 1, 2],
        processingState: const {
          ProcessingState.idle: AudioProcessingState.idle,
          ProcessingState.loading: AudioProcessingState.loading,
          ProcessingState.buffering: AudioProcessingState.buffering,
          ProcessingState.ready: AudioProcessingState.ready,
          ProcessingState.completed: AudioProcessingState.completed,
        }[_player.processingState]!,
        playing: playing,
        updatePosition: _player.position,
        bufferedPosition: _player.bufferedPosition,
        speed: _player.speed,
        queueIndex: event.currentIndex,
      ));
    });

    _player.playerStateStream.listen((state) {
      if (state.processingState == ProcessingState.completed) {
        skipToNext();
      }
    });
  }

  Future<void> loadPlaylist(List<TrackMetadata> tracks, {int startIndex = 0}) async {
    _playlist = List.from(tracks);
    _currentIndex = startIndex;
    if (_playlist.isNotEmpty && startIndex >= 0 && startIndex < _playlist.length) {
      await _playCurrentTrack();
    }
  }

  Future<void> _playCurrentTrack() async {
    final track = currentTrack;
    if (track == null || track.localFilePath == null) return;

    final file = File(track.localFilePath!);
    if (!await file.exists()) return;

    mediaItem.add(MediaItem(
      id: track.id,
      album: track.album,
      title: track.title,
      artist: track.artistStr,
      duration: Duration(milliseconds: track.durationMs),
      artUri: track.coverUrl.isNotEmpty ? Uri.parse(track.coverUrl) : null,
    ));

    try {
      await _player.setFilePath(file.path);
      _player.play();
    } catch (_) {}
  }

  @override
  Future<void> play() => _player.play();

  @override
  Future<void> pause() => _player.pause();

  @override
  Future<void> seek(Duration position) => _player.seek(position);

  @override
  Future<void> skipToNext() async {
    if (_playlist.isEmpty) return;
    _currentIndex = (_currentIndex + 1) % _playlist.length;
    await _playCurrentTrack();
  }

  @override
  Future<void> skipToPrevious() async {
    if (_playlist.isEmpty) return;
    _currentIndex = (_currentIndex - 1 + _playlist.length) % _playlist.length;
    await _playCurrentTrack();
  }

  @override
  Future<void> stop() async {
    await _player.stop();
    await super.stop();
  }

  Future<LyricsData?> loadCurrentLyrics() async {
    final track = currentTrack;
    if (track == null || track.localFilePath == null) return null;

    final lrcPath = p.setExtension(track.localFilePath!, '.lrc');
    final lrcFile = File(lrcPath);
    if (await lrcFile.exists()) {
      try {
        final text = await lrcFile.readAsString();
        return LyricsData(syncedLyrics: text);
      } catch (_) {}
    }
    return null;
  }
}
