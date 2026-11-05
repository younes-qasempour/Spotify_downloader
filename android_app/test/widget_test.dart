import 'dart:io';
import 'package:flutter_test/flutter_test.dart';
import 'package:flacify_mobile/models/lyrics_model.dart';
import 'package:flacify_mobile/models/queue_item.dart';
import 'package:flacify_mobile/models/sync_models.dart';
import 'package:flacify_mobile/models/track_metadata.dart';
import 'package:flacify_mobile/services/m3u_exporter_service.dart';
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

    test('handles multi-timestamp lines and millisecond round', () {
      const lrc = '''
[00:10.00][00:20.00]Chorus line
[00:01.235]Intro
''';
      final lines = LyricsData.parseLrc(lrc);
      expect(lines.length, equals(3));
      expect(lines[0].timestampMs, equals(1235));
      expect(lines[0].text, equals('Intro'));
      expect(lines[1].timestampMs, equals(10000));
      expect(lines[1].text, equals('Chorus line'));
      expect(lines[2].timestampMs, equals(20000));
      expect(lines[2].text, equals('Chorus line'));
    });

    test('activeLineIndexAt and activeLineAt use binary search correctly', () {
      const lrc = '''
[00:05.00] Line 1
[00:15.00] Line 2
[00:30.00] Line 3
''';
      final data = LyricsData(syncedLyrics: lrc);
      expect(data.activeLineIndexAt(2000), equals(-1));
      expect(data.activeLineAt(2000), isNull);

      expect(data.activeLineIndexAt(5000), equals(0));
      expect(data.activeLineAt(5000)?.text, equals('Line 1'));

      expect(data.activeLineIndexAt(10000), equals(0));
      expect(data.activeLineIndexAt(15000), equals(1));
      expect(data.activeLineIndexAt(25000), equals(1));
      expect(data.activeLineIndexAt(30000), equals(2));
      expect(data.activeLineIndexAt(60000), equals(2));
    });

    test('toLrcString outputs formatted or raw lrc text', () {
      const lrc = '[00:05.00]Line 1\n[00:15.00]Line 2';
      final data = LyricsData(syncedLyrics: lrc);
      expect(data.toLrcString(), equals(lrc));

      final plain = LyricsData(plainLyrics: 'Plain lyrics text');
      expect(plain.toLrcString(), equals('Plain lyrics text'));
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

    test('parseUrl supports regional intl-xx and embed links', () {
      final intlUrl = resolver.parseUrl('https://open.spotify.com/intl-es/track/4cOdK2wGLETKBW3PvgPWqT?si=123');
      expect(intlUrl, isNotNull);
      expect(intlUrl!['type'], equals('track'));
      expect(intlUrl['id'], equals('4cOdK2wGLETKBW3PvgPWqT'));

      final embedAlbum = resolver.parseUrl('https://open.spotify.com/embed/album/4LH4d3cOWNNXdsqFd4G7gv');
      expect(embedAlbum, isNotNull);
      expect(embedAlbum!['type'], equals('album'));
      expect(embedAlbum['id'], equals('4LH4d3cOWNNXdsqFd4G7gv'));

      final intlEmbedPlaylist = resolver.parseUrl('https://open.spotify.com/intl-pt/embed/playlist/37i9dQZF1DXcBWIGoYBM5M');
      expect(intlEmbedPlaylist, isNotNull);
      expect(intlEmbedPlaylist!['type'], equals('playlist'));
      expect(intlEmbedPlaylist['id'], equals('37i9dQZF1DXcBWIGoYBM5M'));
    });

    test('extractUrlsFromText extracts valid links from share text blocks', () {
      const shareText = '''
Check out this song: https://open.spotify.com/intl-fr/track/4cOdK2wGLETKBW3PvgPWqT?si=abc
And also this album: https://open.spotify.com/album/4LH4d3cOWNNXdsqFd4G7gv
Random text in between with https://google.com
Or spotify:playlist:37i9dQZF1DXcBWIGoYBM5M on Spotify!
''';

      final urls = resolver.extractUrlsFromText(shareText);
      expect(urls.length, equals(3));
      expect(urls[0], contains('/intl-fr/track/4cOdK2wGLETKBW3PvgPWqT'));
      expect(urls[1], contains('/album/4LH4d3cOWNNXdsqFd4G7gv'));
      expect(urls[2], equals('spotify:playlist:37i9dQZF1DXcBWIGoYBM5M'));
    });

    test('parseUrl rejects invalid URLs and non-Spotify links', () {
      expect(resolver.parseUrl('https://youtube.com/watch?v=123'), isNull);
      expect(resolver.parseUrl('https://open.spotify.com/artist/short'), isNull);
      expect(resolver.parseUrl('not a valid link'), isNull);
      expect(resolver.parseUrl(''), isNull);
    });

    test('cleanWatermarks strips promotional watermarks, non-breaking spaces and remaster suffixes', () {
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
        resolver.cleanWatermarks('Track\u00a0Name\u00a0With\u00a0NBSP'),
        equals('Track Name With NBSP'),
      );
      expect(
        resolver.cleanWatermarks('Stairway to Heaven'),
        equals('Stairway to Heaven'),
      );
    });
  });

  group('TrackMetadata', () {
    test('fromMap and toMap serialize correctly with release_date', () {
      final map = {
        'spotify_id': '4cOdK2wGLETKBW3PvgPWqT',
        'title': 'Never Gonna Give You Up',
        'artist': 'Rick Astley, Stock Aitken',
        'album': 'Whenever You Need Somebody',
        'release_date': '1987-11-12',
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
      expect(track.releaseDate, equals('1987-11-12'));
      expect(track.durationSec, equals(213.0));
      expect(track.localFilePath, equals('/path/to/song.flac'));
      expect(track.qualityBadge, equals('FLAC'));

      final outMap = track.toMap();
      expect(outMap['spotify_id'], equals(map['spotify_id']));
      expect(outMap['title'], equals(map['title']));
      expect(outMap['artist'], equals(map['artist']));
      expect(outMap['release_date'], equals('1987-11-12'));
      expect(outMap['file_path'], equals(map['file_path']));
    });

    test('filters empty artists and parses numeric fields safely', () {
      final map = {
        'id': 'abc123',
        'title': 'Test Song',
        'artists': ['   ', 'Actual Artist', ''],
        'duration_ms': 185500.0,
        'track_number': 3.0,
        'disc_number': 2.0,
      };

      final track = TrackMetadata.fromMap(map);
      expect(track.artists, equals(['Actual Artist']));
      expect(track.durationMs, equals(185500));
      expect(track.trackNumber, equals(3));
      expect(track.discNumber, equals(2));
    });

    test('formattedDuration formats mm:ss correctly', () {
      final track1 = TrackMetadata(
        id: '1',
        title: 'Song 1',
        artists: ['Artist'],
        album: 'Album',
        durationMs: 185000, // 3 mins 5 secs
      );
      expect(track1.formattedDuration, equals('03:05'));

      final track2 = TrackMetadata(
        id: '2',
        title: 'Song 2',
        artists: ['Artist'],
        album: 'Album',
        durationMs: 0,
      );
      expect(track2.formattedDuration, equals('00:00'));
    });

    test('highResCoverUrl upgrades low-res Spotify cover URLs', () {
      const lowRes1 = 'https://i.scdn.co/image/ab67616d00001e021234567890abcdef';
      const lowRes2 = 'https://i.scdn.co/image/ab67616d000048511234567890abcdef';

      final t1 = TrackMetadata(id: '1', title: 'A', artists: ['B'], album: 'C', coverUrl: lowRes1);
      final t2 = TrackMetadata(id: '2', title: 'A', artists: ['B'], album: 'C', coverUrl: lowRes2);

      expect(t1.highResCoverUrl, equals('https://i.scdn.co/image/ab67616d0000b2731234567890abcdef'));
      expect(t2.highResCoverUrl, equals('https://i.scdn.co/image/ab67616d0000b2731234567890abcdef'));
    });

    test('safeFilename sanitizes illegal characters and does not split emoji surrogate pairs', () {
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

      // Emoji surrogate pair test: 98 ASCII characters + emoji 🎶 (2 code units, 1 rune)
      final emojiTrack = TrackMetadata(
        id: 'emoji_id',
        title: '${'A' * 90} 🎶 🎵 🎧 Extra Extra',
        artists: ['Artist'],
        album: 'Album',
      );
      final emojiFilename = emojiTrack.safeFilename;
      expect(emojiFilename.runes.length, lessThanOrEqualTo(100));
      // Verify no broken surrogate character at the boundary
      expect(() => emojiFilename.codeUnits, returnsNormally);
      expect(emojiFilename.contains('\uFFFD'), isFalse);

      final superLong = TrackMetadata(
        id: 'long_id',
        title: 'A' * 150,
        artists: ['B' * 50],
        album: 'Album',
      );
      expect(superLong.safeFilename.runes.length, lessThanOrEqualTo(100));
    });

    test('copyWith, equality and hashCode work as expected', () {
      final t1 = TrackMetadata(
        id: '1',
        title: 'Song',
        artists: ['Artist'],
        album: 'Album',
        durationMs: 120000,
      );
      final t2 = t1.copyWith(title: 'Updated Song');
      expect(t2.id, equals('1'));
      expect(t2.title, equals('Updated Song'));
      expect(t2.durationMs, equals(120000));

      final t3 = TrackMetadata(
        id: '1',
        title: 'Song',
        artists: ['Artist'],
        album: 'Album',
        durationMs: 120000,
      );
      expect(t1 == t3, isTrue);
      expect(t1.hashCode, equals(t3.hashCode));
    });
  });

  group('QueueItem', () {
    final track = TrackMetadata(
      id: '1',
      title: 'Queue Song',
      artists: ['Artist'],
      album: 'Album',
    );

    test('safeProgress clamps invalid and out-of-range progress values', () {
      final itemNeg = QueueItem(id: '1', track: track, progress: -0.5);
      expect(itemNeg.safeProgress, equals(0.0));

      final itemOver = QueueItem(id: '2', track: track, progress: 1.5);
      expect(itemOver.safeProgress, equals(1.0));

      final itemNan = QueueItem(id: '3', track: track, progress: double.nan);
      expect(itemNan.safeProgress, equals(0.0));

      final itemInf = QueueItem(id: '4', track: track, progress: double.infinity);
      expect(itemInf.safeProgress, equals(0.0));

      final itemValid = QueueItem(id: '5', track: track, progress: 0.65);
      expect(itemValid.safeProgress, equals(0.65));
    });

    test('convenience status getters and copyWith function as expected', () {
      final item = QueueItem(id: '1', track: track, status: QueueStatus.pending);
      expect(item.isActive, isFalse);
      expect(item.isTerminal, isFalse);
      expect(item.canCancel, isTrue);
      expect(item.canRetry, isFalse);

      final downloadingItem = item.copyWith(status: QueueStatus.downloading);
      expect(downloadingItem.isActive, isTrue);
      expect(downloadingItem.isTerminal, isFalse);
      expect(downloadingItem.canCancel, isTrue);
      expect(downloadingItem.canRetry, isFalse);

      final errorItem = item.copyWith(status: QueueStatus.error);
      expect(errorItem.isActive, isFalse);
      expect(errorItem.isTerminal, isTrue);
      expect(errorItem.canCancel, isFalse);
      expect(errorItem.canRetry, isTrue);

      final completedItem = item.copyWith(status: QueueStatus.completed);
      expect(completedItem.isTerminal, isTrue);
      expect(completedItem.canRetry, isFalse);
    });
  });

  group('SyncModels', () {
    test('TrackManifestItem and SyncPlaylistItem parse float numbers and nulls safely', () {
      final manifestJson = {
        'track_id': 't1',
        'filename': 't1.flac',
        'title': 'Track 1',
        'artist': 'Artist 1',
        'album': 'Album 1',
        'duration_ms': 180000.0,
        'file_size': 10485760.0,
        'file_hash': 'sha256_hash',
        'has_lyrics': true,
        'updated_at': 1700000000.0,
      };

      final manifestItem = TrackManifestItem.fromJson(manifestJson);
      expect(manifestItem.durationMs, equals(180000));
      expect(manifestItem.fileSize, equals(10485760));
      expect(manifestItem.updatedAt, equals(1700000000));
      expect(manifestItem.hasLyrics, isTrue);

      final playlistJson = {
        'id': 'p1',
        'name': 'My Playlist',
        'total_tracks': 5.0,
        'updated_at': 1700000050.0,
        'tracks': [
          {
            'spotify_id': 'sp1',
            'title': 'Track A',
            'artist': 'Artist A',
            'duration_ms': 200000.0,
            'track_number': 1.0,
          }
        ],
      };

      final playlistItem = SyncPlaylistItem.fromJson(playlistJson);
      expect(playlistItem.totalTracks, equals(5));
      expect(playlistItem.updatedAt, equals(1700000050));
      expect(playlistItem.tracks.length, equals(1));
      expect(playlistItem.tracks.first.durationMs, equals(200000));
      expect(playlistItem.tracks.first.trackNumber, equals(1));
    });

    test('SyncDeltaResult totalDownloadBytes, totalUploadBytes, totalItems, isEmpty', () {
      final track1 = TrackManifestItem(
        trackId: '1',
        filename: '1.flac',
        title: 'T1',
        artist: 'A1',
        album: 'Alb1',
        durationMs: 100000,
        fileSize: 5000,
        fileHash: 'h1',
        hasLyrics: false,
        updatedAt: 1,
      );
      final track2 = TrackManifestItem(
        trackId: '2',
        filename: '2.flac',
        title: 'T2',
        artist: 'A2',
        album: 'Alb2',
        durationMs: 120000,
        fileSize: 8000,
        fileHash: 'h2',
        hasLyrics: true,
        updatedAt: 2,
      );

      final delta = SyncDeltaResult(
        toDownloadFromPc: [track1],
        toUploadToPc: [track2],
      );

      expect(delta.totalDownloadBytes, equals(5000));
      expect(delta.totalUploadBytes, equals(8000));
      expect(delta.totalItems, equals(2));
      expect(delta.isEmpty, isFalse);

      final emptyDelta = SyncDeltaResult(
        toDownloadFromPc: [],
        toUploadToPc: [],
      );
      expect(emptyDelta.isEmpty, isTrue);
      expect(emptyDelta.totalItems, equals(0));
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
      final localChangedSize = TrackManifestItem(
        trackId: 'id_a',
        filename: 'artist - song_a.flac',
        title: 'Song A',
        artist: 'Artist',
        album: 'Album',
        durationMs: 180000,
        fileSize: 9000000,
        fileHash: 'hash_old',
        hasLyrics: true,
        updatedAt: 900,
      );

      final localMissingLyrics = TrackManifestItem(
        trackId: 'id_a',
        filename: 'artist - song_a.flac',
        title: 'Song A',
        artist: 'Artist',
        album: 'Album',
        durationMs: 180000,
        fileSize: 10000000,
        fileHash: 'hash_a',
        hasLyrics: false,
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

  group('M3uExporterService', () {
    late Directory tempDir;
    final exporter = M3uExporterService();

    setUp(() async {
      tempDir = await Directory.systemTemp.createTemp('flacify_m3u_test_');
    });

    tearDown(() async {
      if (await tempDir.exists()) {
        await tempDir.delete(recursive: true);
      }
    });

    test('exportPlaylistToM3u8 writes atomic and valid m3u8 playlist file', () async {
      final track1 = TrackMetadata(
        id: 't1',
        title: 'Song One',
        artists: ['Artist A'],
        album: 'Album A',
        durationMs: 180000,
        localFilePath: '${tempDir.path}${Platform.pathSeparator}Song One.flac',
      );
      final track2 = TrackMetadata(
        id: 't2',
        title: 'Song Two',
        artists: ['Artist B'],
        album: 'Album B',
        durationMs: 240000,
        localFilePath: '${tempDir.path}${Platform.pathSeparator}Song Two.flac',
      );
      // Track without local file path should be skipped
      final trackWithoutPath = TrackMetadata(
        id: 't3',
        title: 'Online Song',
        artists: ['Artist C'],
        album: 'Album C',
      );

      final exportedFile = await exporter.exportPlaylistToM3u8(
        playlistName: 'My Awesome Playlist / 2026!',
        tracks: [track1, track2, trackWithoutPath],
        outputDir: tempDir,
        useRelativePaths: true,
      );

      expect(await exportedFile.exists(), isTrue);
      // Cleaned filename replaces / with _
      expect(exportedFile.path.endsWith('My Awesome Playlist _ 2026!.m3u8'), isTrue);

      final content = await exportedFile.readAsString();
      expect(content.contains('#EXTM3U'), isTrue);
      expect(content.contains('#PLAYLIST:My Awesome Playlist / 2026!'), isTrue);
      expect(content.contains('#EXTINF:180,Artist A - Song One'), isTrue);
      expect(content.contains('Song One.flac'), isTrue);
      expect(content.contains('#EXTINF:240,Artist B - Song Two'), isTrue);
      expect(content.contains('Song Two.flac'), isTrue);
      expect(content.contains('Online Song'), isFalse);
    });

    test('exportPlaylistToM3u8 supports absolute paths', () async {
      final track = TrackMetadata(
        id: 't1',
        title: 'Song Absolute',
        artists: ['Artist A'],
        album: 'Album A',
        durationMs: 120000,
        localFilePath: '/storage/emulated/0/Music/Song Absolute.flac',
      );

      final exportedFile = await exporter.exportPlaylistToM3u8(
        playlistName: 'Absolute Playlist',
        tracks: [track],
        outputDir: tempDir,
        useRelativePaths: false,
      );

      final content = await exportedFile.readAsString();
      expect(content.contains('/storage/emulated/0/Music/Song Absolute.flac'), isTrue);
    });
  });
}
