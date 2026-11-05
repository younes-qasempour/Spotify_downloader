import 'package:dio/dio.dart';
import '../models/lyrics_model.dart';
import '../models/track_metadata.dart';

class LrcLibService {
  final Dio _dio = Dio(BaseOptions(
    connectTimeout: const Duration(seconds: 8),
    receiveTimeout: const Duration(seconds: 10),
    headers: {
      'User-Agent': 'FlacifyMobile/1.0 (https://github.com/younes-qasempour/Spotify_downloader)',
      'Accept': 'application/json',
    },
  ));

  static const String apiUrl = 'https://lrclib.net/api/get';
  static const String searchUrl = 'https://lrclib.net/api/search';

  Future<LyricsData?> fetchLyrics(TrackMetadata track) async {
    try {
      // 1. Try exact lookup with album name
      final params = <String, dynamic>{
        'track_name': track.title,
        'artist_name': track.primaryArtist,
        'album_name': track.album,
        'duration': track.durationSec.round(),
      };

      Response response;
      try {
        response = await _dio.get(apiUrl, queryParameters: params);
      } on DioException catch (e) {
        if (e.response?.statusCode == 404) {
          // 2. Retry without album name
          params.remove('album_name');
          response = await _dio.get(apiUrl, queryParameters: params);
        } else {
          rethrow;
        }
      }

      if (response.statusCode == 200 && response.data is Map) {
        final data = response.data as Map<String, dynamic>;
        final synced = data['syncedLyrics'] as String?;
        final plain = data['plainLyrics'] as String?;
        final instrumental = data['instrumental'] == true;

        if (synced != null || plain != null) {
          return LyricsData(
            syncedLyrics: synced,
            plainLyrics: plain,
            instrumental: instrumental,
          );
        }
      }
    } catch (_) {}

    // 3. Fallback to fuzzy search
    try {
      final searchRes = await _dio.get(searchUrl, queryParameters: {
        'q': '${track.primaryArtist} ${track.title}',
      });

      if (searchRes.statusCode == 200 && searchRes.data is List) {
        final list = searchRes.data as List<dynamic>;
        if (list.isNotEmpty && list.first is Map) {
          final firstMatch = list.first as Map<String, dynamic>;
          final synced = firstMatch['syncedLyrics'] as String?;
          final plain = firstMatch['plainLyrics'] as String?;
          if (synced != null || plain != null) {
            return LyricsData(
              syncedLyrics: synced,
              plainLyrics: plain,
              instrumental: firstMatch['instrumental'] == true,
            );
          }
        }
      }
    } catch (_) {}

    return null;
  }
}

