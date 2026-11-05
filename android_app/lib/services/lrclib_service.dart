import 'dart:io';
import 'package:dio/dio.dart';
import 'package:path/path.dart' as p;
import '../models/lyrics_model.dart';
import '../models/track_metadata.dart';

class LrcLibService {
  final Dio _dio;

  LrcLibService({Dio? dio})
      : _dio = dio ??
            Dio(BaseOptions(
              connectTimeout: const Duration(seconds: 8),
              receiveTimeout: const Duration(seconds: 10),
              headers: {
                'User-Agent':
                    'FlacifyMobile/1.0 (https://github.com/younes-qasempour/Spotify_downloader)',
                'Accept': 'application/json',
              },
            ));

  static const String apiUrl = 'https://lrclib.net/api/get';
  static const String searchUrl = 'https://lrclib.net/api/search';

  Future<LyricsData?> loadSidecarLrc(TrackMetadata track) async {
    final path = track.localFilePath;
    if (path == null || path.isEmpty) return null;
    try {
      final audioFile = File(path);
      final dir = audioFile.parent.path;
      final stem = p.basenameWithoutExtension(path);

      final candidate1 = File(p.join(dir, '$stem.lrc'));
      if (await candidate1.exists()) {
        final content = await candidate1.readAsString();
        if (content.trim().isNotEmpty) {
          return LyricsData(syncedLyrics: content);
        }
      }

      final candidate2 = File(p.join(dir, 'lyrics', '$stem.lrc'));
      if (await candidate2.exists()) {
        final content = await candidate2.readAsString();
        if (content.trim().isNotEmpty) {
          return LyricsData(syncedLyrics: content);
        }
      }
    } catch (_) {}
    return null;
  }

  Future<File?> saveSidecarLrc(TrackMetadata track, LyricsData lyrics) async {
    final path = track.localFilePath;
    if (path == null || path.isEmpty) return null;
    final lrcString = lyrics.toLrcString();
    if (lrcString.trim().isEmpty) return null;

    try {
      final audioFile = File(path);
      final dir = audioFile.parent;
      if (!await dir.exists()) {
        await dir.create(recursive: true);
      }
      final stem = p.basenameWithoutExtension(path);
      final target = File(p.join(dir.path, '$stem.lrc'));
      final tmp = File(p.join(dir.path, '.$stem.lrc.tmp'));

      await tmp.writeAsString(lrcString);
      if (await target.exists()) {
        await target.delete();
      }
      return await tmp.rename(target.path);
    } catch (_) {
      return null;
    }
  }

  Future<LyricsData?> fetchLyrics(TrackMetadata track) async {
    final sidecar = await loadSidecarLrc(track);
    if (sidecar != null) {
      return sidecar;
    }

    try {
      // 1. Try exact lookup with album name
      final params = <String, dynamic>{
        'track_name': track.title,
        'artist_name': track.primaryArtist,
        'album_name': track.album,
      };
      if (track.durationSec > 0) {
        params['duration'] = track.durationSec.round();
      }

      Response response;
      try {
        response = await _dio.get(apiUrl, queryParameters: params);
      } on DioException catch (e) {
        final statusCode = e.response?.statusCode;
        if (statusCode == 404) {
          // 2. Retry without album name
          params.remove('album_name');
          response = await _dio.get(apiUrl, queryParameters: params);
        } else if (statusCode == 429 ||
            (statusCode != null && statusCode >= 500) ||
            e.type == DioExceptionType.connectionTimeout ||
            e.type == DioExceptionType.receiveTimeout) {
          return null;
        } else {
          rethrow;
        }
      }

      if (response.statusCode == 200 && response.data is Map) {
        final data = response.data as Map<String, dynamic>;
        final synced = data['syncedLyrics'] as String?;
        final plain = data['plainLyrics'] as String?;
        final instrumental = data['instrumental'] == true;

        if (synced != null || plain != null || instrumental) {
          final result = LyricsData(
            syncedLyrics: synced,
            plainLyrics: plain,
            instrumental: instrumental,
          );
          if (synced != null &&
              track.localFilePath != null &&
              track.localFilePath!.isNotEmpty) {
            await saveSidecarLrc(track, result);
          }
          return result;
        }
      }
    } on DioException catch (e) {
      final statusCode = e.response?.statusCode;
      if (statusCode == 429 ||
          (statusCode != null && statusCode >= 500) ||
          e.type == DioExceptionType.connectionTimeout ||
          e.type == DioExceptionType.receiveTimeout) {
        return null;
      }
    } catch (_) {}

    // 3. Fallback to fuzzy search
    try {
      final searchRes = await _dio.get(searchUrl, queryParameters: {
        'q': '${track.primaryArtist} ${track.title}',
      });

      if (searchRes.statusCode == 200 && searchRes.data is List) {
        final list = searchRes.data as List<dynamic>;
        for (final item in list) {
          if (item is! Map) continue;
          final itemMap = Map<String, dynamic>.from(item);
          if (track.durationSec > 0 && itemMap['duration'] is num) {
            final candDuration = (itemMap['duration'] as num).toDouble();
            if ((candDuration - track.durationSec).abs() > 5.0) {
              continue;
            }
          }
          final synced = itemMap['syncedLyrics'] as String?;
          final plain = itemMap['plainLyrics'] as String?;
          final instrumental = itemMap['instrumental'] == true;

          if (synced != null || plain != null || instrumental) {
            final result = LyricsData(
              syncedLyrics: synced,
              plainLyrics: plain,
              instrumental: instrumental,
            );
            if (synced != null &&
                track.localFilePath != null &&
                track.localFilePath!.isNotEmpty) {
              await saveSidecarLrc(track, result);
            }
            return result;
          }
        }
      }
    } catch (_) {}

    return null;
  }
}

