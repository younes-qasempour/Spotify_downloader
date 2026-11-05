import 'dart:io';
import 'package:dio/dio.dart';
import 'package:path/path.dart' as p;
import '../models/lyrics_model.dart';
import '../models/track_metadata.dart';

class AudioTagger {
  final Dio _dio = Dio(BaseOptions(
    connectTimeout: const Duration(seconds: 10),
    receiveTimeout: const Duration(seconds: 15),
  ));

  Future<void> tagAudioFile({
    required File audioFile,
    required TrackMetadata track,
    LyricsData? lyrics,
    bool saveLrcFile = true,
  }) async {
    // 1. Export companion .lrc file if synced lyrics exist
    if (saveLrcFile && lyrics != null && lyrics.syncedLyrics != null && lyrics.syncedLyrics!.isNotEmpty) {
      final lrcPath = p.setExtension(audioFile.path, '.lrc');
      final lrcFile = File(lrcPath);
      await lrcFile.writeAsString(lyrics.syncedLyrics!, flush: true);
    }

    // 2. Fetch cover art if available and cache companion cover
    if (track.coverUrl.isNotEmpty) {
      try {
        final coverPath = p.setExtension(audioFile.path, '.jpg');
        final coverFile = File(coverPath);
        if (!await coverFile.exists()) {
          final res = await _dio.get<List<int>>(
            track.coverUrl,
            options: Options(responseType: ResponseType.bytes),
          );
          if (res.data != null && res.data!.isNotEmpty) {
            await coverFile.writeAsBytes(res.data!, flush: true);
          }
        }
      } catch (_) {}
    }
  }
}

