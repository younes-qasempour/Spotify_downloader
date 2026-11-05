import 'dart:io';
import 'package:dio/dio.dart';
import '../models/track_metadata.dart';

class MusilonSource {
  final String trackId;
  final String title;
  final String artist;
  final String qualityTier;
  final String downloadUrl;
  final String fileExtension;

  MusilonSource({
    required this.trackId,
    required this.title,
    required this.artist,
    required this.qualityTier,
    required this.downloadUrl,
    required this.fileExtension,
  });
}

class MusilonEngine {
  final Dio _dio = Dio(BaseOptions(
    connectTimeout: const Duration(seconds: 15),
    receiveTimeout: const Duration(minutes: 5),
    headers: {
      'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36',
    },
  ));

  static const String baseApi = 'https://open.musilon.com/api';

  Future<MusilonSource?> resolveTrack(TrackMetadata track, {String preferredQuality = 'flac'}) async {
    try {
      final query = '${track.primaryArtist} ${track.title}';
      final searchRes = await _dio.get(
        '$baseApi/search',
        queryParameters: {'q': query, 'limit': 5},
      );

      if (searchRes.statusCode == 200 && searchRes.data is Map) {
        final items = searchRes.data['items'] as List<dynamic>? ?? [];
        if (items.isNotEmpty) {
          final first = items.first;
          final trackId = first['id']?.toString() ?? '';
          final tier = preferredQuality.toLowerCase() == 'flac' ? 'Musilon FLAC 16' : 'Musilon 320k';
          final ext = preferredQuality.toLowerCase() == 'flac' ? 'flac' : 'mp3';

          // Get direct stream token
          final streamRes = await _dio.post(
            '$baseApi/stream',
            data: {'track_id': trackId, 'quality': preferredQuality},
          );

          if (streamRes.statusCode == 200 && streamRes.data is Map) {
            final streamUrl = streamRes.data['stream_url'] as String?;
            if (streamUrl != null && streamUrl.isNotEmpty) {
              return MusilonSource(
                trackId: trackId,
                title: track.title,
                artist: track.primaryArtist,
                qualityTier: tier,
                downloadUrl: streamUrl,
                fileExtension: ext,
              );
            }
          }
        }
      }
    } catch (_) {}
    return null;
  }

  Future<File> downloadStream(
    MusilonSource source,
    String savePath, {
    void Function(double progress)? onProgress,
  }) async {
    final file = File(savePath);
    await _dio.download(
      source.downloadUrl,
      savePath,
      onReceiveProgress: (received, total) {
        if (total > 0 && onProgress != null) {
          onProgress(received / total);
        }
      },
    );
    return file;
  }
}

