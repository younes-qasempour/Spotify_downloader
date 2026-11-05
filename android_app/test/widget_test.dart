import 'package:flutter_test/flutter_test.dart';
import 'package:flacify_mobile/models/lyrics_model.dart';
import 'package:flacify_mobile/models/sync_models.dart';
import 'package:flacify_mobile/models/track_metadata.dart';
import 'package:flacify_mobile/services/spotify_resolver.dart';
import 'package:flacify_mobile/services/wifi_sync_service.dart';

void main() {
  group('LyricsData.parseLrc', () {
    test('parses timestamps, trims text, ignores blank lines, and sorts lines', () {
      const lrc = '''
[01:15.50] Second line of lyrics
\t
[00:05.20] First line of lyrics

[02:00.00] Third line of lyrics
[invalid line without timestamp]
''';

      final lines = LyricsData.parseLrc(lrc);

      expect(lines.length, equals(3));
      // First line: 0*60 + 5.20 = 5.20s = 5200ms
      expect(lines[0].timestampMs, equals(5200));
      expect(lines[0].text, equals('First line of lyrics'));

      // Second line: 1*60 + 15.50 = 75.50s = 75500ms
      expect(lines[1].timestampMs, equals(75500));
      expect(lines[1].text, equals('Second line of lyrics'));

      // Third line: 2*60 + 0 = 120.00s = 120000ms
      expect(lines[2].timestampMs, equals(120000));
      expect(lines[2].text, equals('Third line of lyrics'));
    });

    test('handles empty or whitespace-only lrc text', () {
      final lines = LyricsData.parseLrc('   \n\n\t  ');
      expect(lines, isEmpty);
    });

    test('sorts lines that arrive out of order', () {
      const lrc = '''
[01:30.00] Line 2
[00:10.00] Line 1
[02:45.00] Line 3
''';
      final lines = LyricsData.parseLrc(lrc);
      expect(lines[0].text, equals('Line 1'));
      expect(lines[1].text, equals('Line 2'));
      expect(lines[2].text, equals('Line 3'));
    });
  });

  group('SpotifyResolver', () {
    final resolver = SpotifyResolver();

    test('parseUrl parses track, album, and playlist URLs and URIs', () {
      final trackUrl = resolver.parseUrl('https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT');
      expect(trackUrl, isNotNull);
      expect(trackUrl!['type'], equals('track'));
      expect(trackUrl['id'], equals('4cOdK2wGLETKBW3PvgPWqT'));

      final albumUrl = resolver.parseUrl('https://open.spotify.com/album/4LH4d3cOWNNXdsqFd4G7gv?si=xyz');
      expect(albumUrl, isNotNull);
      expect(albumUrl!['type'], equals('album'));
      expect(albumUrl['id'], equals('4LH4d3cOWNNXdsqFd4G7gv'));

      final playlistUri = resolver.parseUrl('spotify:playlist:37i9dQZF1DXcBWIGoYBM5M');
      expect(playlistUri, isNotNull);
      expect(playlistUri!['type'], equals('playlist'));
      expect(playlistUri['id'], equals('37i9dQZF1DXcBWIGoYBM5M'));

      final trackUri = resolver.parseUrl('spotify:track:4cOdK2wGLETKBW3PvgPWqT');
      expect(trackUri, isNotNull);
      expect(trackUri!['type'], equals('track'));
      expect(trackUri['id'], equals('4cOdK2wGLETKBW3PvgPWqT'));
    });

    test('parseUrl rejects invalid URLs and non-Spotify links', () {
      expect(resolver.parseUrl('https://youtube.com/watch?v=123'), isNull);
      expect(resolver.parseUrl('https://open.spotify.com/artist/short'), isNull);
      expect(resolver.parseUrl('not a valid link'), isNull);
      expect(resolver.parseUrl(''), isNull);
    });

    test('cleanWatermarks strips promotional watermarks and remaster suffixes', () {
      expect(
        resolver.cleanWatermarks('Bohemian Rhapsody [Musilon Official HQ]'),
        equals('Bohemian Rhapsody'),
      );
      expect(
        resolver.cleanWatermarks('Hotel California (Musilon Master FLAC)'),
        equals('Hotel California'),
      );
      expect(
        resolver.cleanWatermarks('Yesterday - Remastered 2009'),
        equals('Yesterday'),
      );
      expect(
        resolver.cleanWatermarks('Come Together - Remaster'),
        equals('Come Together'),
      );
      expect(
        resolver.cleanWatermarks('Stairway to Heaven'),
        equals('Stairway to Heaven'),
      );
    });
  });

  group('TrackMetadata', () {
    test('fromMap and toMap serialize correctly', () {
      final map = {
        'spotify_id': '4cOdK2wGLETKBW3PvgPWqT',
        'title': 'Never Gonna Give You Up',
        'artist': 'Rick Astley, Stock Aitken',
        'album': 'Whenever You Need Somebody',
        'duration_ms': 213000,
        'track_number': 1,
        'disc_number': 1,
        'isrc': 'GBARL8700041',
        'cover_url': 'https://example.com/cover.jpg',
        'collection_type': 'track',
        'collection_name': 'Singles',
        'collection_cover_url': '',
        'file_path': '/path/to/song.flac',
        'quality_badge': 'FLAC',
      };

      final track = TrackMetadata.fromMap(map);
      expect(track.id, equals('4cOdK2wGLETKBW3PvgPWqT'));
      expect(track.title, equals('Never Gonna Give You Up'));
      expect(track.artists, equals(['Rick Astley', 'Stock Aitken']));
      expect(track.primaryArtist, equals('Rick Astley'));
      expect(track.artistStr, equals('Rick Astley, Stock Aitken'));
      expect(track.album, equals('Whenever You Need Somebody'));
      expect(track.durationSec, equals(213.0));
      expect(track.localFilePath, equals('/path/to/song.flac'));
      expect(track.qualityBadge, equals('FLAC'));

      final outMap = track.toMap();
      expect(outMap['spotify_id'], equals(map['spotify_id']));
      expect(outMap['title'], equals(map['title']));
      expect(outMap['artist'], equals(map['artist']));
      expect(outMap['file_path'], equals(map['file_path']));
    });

    test('safeFilename sanitizes illegal characters and limits length', () {
      final track = TrackMetadata(
        id: 'test_id',
        title: 'Song: Title / With * Illegal ? Characters <And> More | Fun"',
        artists: ['Artist:Name'],
        album: 'Album',
      );

      final safe = track.safeFilename;
      expect(safe.contains(':'), isFalse);
      expect(safe.contains('/'), isFalse);
      expect(safe.contains('*'), isFalse);
      expect(safe.contains('?'), isFalse);
      expect(safe.contains('<'), isFalse);
      expect(safe.contains('>'), isFalse);
      expect(safe.contains('|'), isFalse);
      expect(safe.contains('"'), isFalse);

      final superLong = TrackMetadata(
        id: 'long_id',
        title: 'A' * 150,
        artists: ['B' * 50],
        album: 'Album',
      );
      expect(superLong.safeFilename.length, lessThanOrEqualTo(100));
    });
  });

  group('WifiSyncService.computeDelta', () {
    final syncService = WifiSyncService();

    final trackA = TrackManifestItem(
      trackId: 'id_a',
      filename: 'artist - song_a.flac',
      title: 'Song A',
      artist: 'Artist',
      album: 'Album',
      durationMs: 180000,
      fileSize: 10000000,
      fileHash: 'hash_a',
      hasLyrics: true,
      updatedAt: 1000,
    );

    final trackB = TrackManifestItem(
      trackId: 'id_b',
      filename: 'artist - song_b.flac',
      title: 'Song B',
      artist: 'Artist',
      album: 'Album',
      durationMs: 200000,
      fileSize: 12000000,
      fileHash: 'hash_b',
      hasLyrics: false,
      updatedAt: 1000,
    );

    test('detects tracks to download from PC when missing locally', () {
      final delta = syncService.computeDelta(
        remoteTracks: [trackA, trackB],
        localTracks: [trackA],
      );

      expect(delta.toDownloadFromPc.length, equals(1));
      expect(delta.toDownloadFromPc.first.trackId, equals('id_b'));
      expect(delta.toUploadToPc, isEmpty);
    });

    test('detects tracks to download when file size changed or lyrics added', () {
      // Local copy has different file size
      final localChangedSize = TrackManifestItem(
        trackId: 'id_a',
        filename: 'artist - song_a.flac',
        title: 'Song A',
        artist: 'Artist',
        album: 'Album',
        durationMs: 180000,
        fileSize: 9000000, // Different size
        fileHash: 'hash_old',
        hasLyrics: true,
        updatedAt: 900,
      );

      // Local copy missing lyrics while remote has lyrics
      final localMissingLyrics = TrackManifestItem(
        trackId: 'id_a',
        filename: 'artist - song_a.flac',
        title: 'Song A',
        artist: 'Artist',
        album: 'Album',
        durationMs: 180000,
        fileSize: 10000000,
        fileHash: 'hash_a',
        hasLyrics: false, // Missing lyrics
        updatedAt: 1000,
      );

      final deltaSize = syncService.computeDelta(
        remoteTracks: [trackA],
        localTracks: [localChangedSize],
      );
      expect(deltaSize.toDownloadFromPc.length, equals(1));

      final deltaLyrics = syncService.computeDelta(
        remoteTracks: [trackA],
        localTracks: [localMissingLyrics],
      );
      expect(deltaLyrics.toDownloadFromPc.length, equals(1));
    });

    test('detects tracks on phone missing on PC to upload', () {
      final phoneExclusiveTrack = TrackManifestItem(
        trackId: 'id_c',
        filename: 'artist - song_c.flac',
        title: 'Song C',
        artist: 'Artist',
        album: 'Album',
        durationMs: 150000,
        fileSize: 8000000,
        fileHash: 'hash_c',
        hasLyrics: false,
        updatedAt: 1000,
      );

      final delta = syncService.computeDelta(
        remoteTracks: [trackA],
        localTracks: [trackA, phoneExclusiveTrack],
      );

      expect(delta.toDownloadFromPc, isEmpty);
      expect(delta.toUploadToPc.length, equals(1));
      expect(delta.toUploadToPc.first.trackId, equals('id_c'));
    });

    test('returns empty lists when local and remote match exactly', () {
      final delta = syncService.computeDelta(
        remoteTracks: [trackA, trackB],
        localTracks: [trackA, trackB],
      );

      expect(delta.toDownloadFromPc, isEmpty);
      expect(delta.toUploadToPc, isEmpty);
    });
  });
}
