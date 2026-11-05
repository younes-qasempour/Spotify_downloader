import 'dart:convert';
import 'package:dio/dio.dart';
import '../models/track_metadata.dart';

class SpotifyResolver {
  final Dio _dio;

  SpotifyResolver({Dio? dio})
      : _dio = dio ??
            Dio(BaseOptions(
              connectTimeout: const Duration(seconds: 12),
              receiveTimeout: const Duration(seconds: 15),
              headers: {
                'User-Agent':
                    'Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Mobile Safari/537.36',
                'Accept-Language': 'en-US,en;q=0.9',
              },
            ));

  static final RegExp spotifyUrlPattern = RegExp(
    r'(?:https?:\/\/open\.spotify\.com\/(?:intl-[a-zA-Z0-9-]+\/)?(?:embed\/)?|spotify:)(track|album|playlist|artist)[/:]([a-zA-Z0-9]{22})',
  );

  Map<String, String>? parseUrl(String url) {
    final match = spotifyUrlPattern.firstMatch(url.trim());
    if (match != null) {
      return {
        'type': match.group(1)!,
        'id': match.group(2)!,
      };
    }
    return null;
  }

  List<String> extractUrlsFromText(String text) {
    if (text.isEmpty) return const [];
    final matches = spotifyUrlPattern.allMatches(text);
    final results = <String>[];
    for (final m in matches) {
      final matchedText = m.group(0);
      if (matchedText != null && matchedText.isNotEmpty) {
        results.add(matchedText);
      }
    }
    return results;
  }

  String cleanWatermarks(String text) {
    return text
        .replaceAll('\u00a0', ' ')
        .replaceAll(RegExp(r'\[Musilon.*?\]', caseSensitive: false), '')
        .replaceAll(RegExp(r'\(Musilon.*?\)', caseSensitive: false), '')
        .replaceAll(RegExp(r'\s*-\s*Remaster(?:ed)?(?:\s*\d{4})?', caseSensitive: false), '')
        .trim();
  }

  Future<String> fetchTrackHighResCover(String trackId) async {
    try {
      final oembedUrl = 'https://open.spotify.com/oembed?url=https://open.spotify.com/track/$trackId';
      final res = await _dio.get(oembedUrl);
      if (res.statusCode == 200 && res.data is Map) {
        final thumb = res.data['thumbnail_url'] as String?;
        if (thumb != null && thumb.isNotEmpty) {
          // Upgrade 300x300 thumbnail to pristine 640x640 square cover art
          return thumb.replaceAll('ab67616d00001e02', 'ab67616d0000b273');
        }
      }
    } catch (_) {}
    return '';
  }

  Future<List<TrackMetadata>> resolveUrl(String url) async {
    final parsed = parseUrl(url);
    if (parsed == null) {
      throw Exception('Invalid Spotify URL or URI');
    }

    final type = parsed['type']!;
    final id = parsed['id']!;

    final embedUrl = 'https://open.spotify.com/embed/$type/$id';
    final response = await _dio.get(embedUrl);
    final html = response.data.toString();

    final match = RegExp(r'<script id="__NEXT_DATA__"[^>]*>(.*?)<\/script>', dotAll: true).firstMatch(html);
    if (match == null) {
      throw Exception('Unable to extract Spotify metadata. The link may be private or invalid.');
    }

    final jsonData = jsonDecode(match.group(1)!);
    final rawEntity = jsonData['props']?['pageProps']?['state']?['data']?['entity'];
    if (rawEntity == null || rawEntity is! Map) {
      throw Exception('Could not parse Spotify entity details.');
    }
    final entity = Map<String, dynamic>.from(rawEntity);

    if (type == 'track') {
      return [_parseSingleTrack(entity)];
    } else if (type == 'album' ||
        type == 'playlist' ||
        (type == 'artist' && entity['trackList'] is List)) {
      return await _parseCollection(entity, type);
    }

    throw Exception('Unsupported entity type: $type');
  }

  TrackMetadata _parseSingleTrack(Map<String, dynamic> entity) {
    final title = cleanWatermarks(entity['title'] ?? entity['name'] ?? 'Unknown Title');
    final rawArtists = entity['artists'] as List<dynamic>? ?? [];
    List<String> artists = rawArtists
        .map((a) => a['name']?.toString() ?? '')
        .where((n) => n.isNotEmpty)
        .toList();

    if (artists.isEmpty && entity['subtitle'] != null) {
      artists = [entity['subtitle'].toString().trim()];
    }

    String coverUrl = '';
    final visual = entity['visualIdentity'];
    if (visual is Map && visual['image'] is List && (visual['image'] as List).isNotEmpty) {
      coverUrl = visual['image'][0]['url'] ?? '';
    }

    String albumName = 'Singles';
    final albumData = entity['album'];
    if (albumData is Map) {
      albumName = albumData['name'] ?? 'Singles';
    } else if (albumData is String) {
      albumName = albumData;
    }

    return TrackMetadata(
      id: entity['id']?.toString() ?? '',
      title: title,
      artists: artists.isNotEmpty ? artists : ['Unknown Artist'],
      album: cleanWatermarks(albumName),
      releaseDate: entity['releaseDate']?.toString() ?? '',
      durationMs: entity['duration'] is int ? entity['duration'] : 0,
      trackNumber: 1,
      discNumber: 1,
      coverUrl: coverUrl,
      collectionType: 'track',
      collectionName: 'Singles',
    );
  }

  Future<List<TrackMetadata>> _parseCollection(Map<String, dynamic> entity, String type) async {
    final collectionTitle = cleanWatermarks(
      entity['title']?.toString() ?? entity['name']?.toString() ?? 'Spotify Collection',
    );
    final trackList = entity['trackList'] as List<dynamic>? ?? [];

    String collectionCover = '';
    final visual = entity['visualIdentity'];
    if (visual is Map && visual['image'] is List && (visual['image'] as List).isNotEmpty) {
      collectionCover = visual['image'][0]['url'] ?? '';
    }

    final List<TrackMetadata> tracks = [];

    for (var i = 0; i < trackList.length; i++) {
      final t = trackList[i];
      if (t is! Map) continue;

      final uriSegment = t['uri']?.toString().split(':').last.trim();
      final rawId = t['id']?.toString().trim();
      final trackId = (uriSegment != null && uriSegment.isNotEmpty)
          ? uriSegment
          : ((rawId != null && rawId.isNotEmpty) ? rawId : 'track_$i');

      final title = cleanWatermarks(t['title']?.toString() ?? 'Unknown Track');
      final subtitle = t['subtitle']?.toString() ?? '';
      List<String> artists = subtitle.split(',').map((a) => a.trim()).where((a) => a.isNotEmpty).toList();
      if (artists.isEmpty) {
        artists = ['Unknown Artist'];
      }

      final fallbackAlbum = type == 'album'
          ? collectionTitle
          : (type == 'artist' ? 'Top Tracks' : 'Spotify Playlist');

      tracks.add(TrackMetadata(
        id: trackId,
        title: title,
        artists: artists,
        album: cleanWatermarks(fallbackAlbum),
        durationMs: t['duration'] is int ? t['duration'] : 0,
        trackNumber: i + 1,
        coverUrl: collectionCover,
        collectionType: type,
        collectionName: collectionTitle,
        collectionCoverUrl: collectionCover,
      ));
    }

    return tracks;
  }
}
