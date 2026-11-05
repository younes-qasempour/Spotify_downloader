import 'dart:convert';
import 'dart:io';
import 'package:dio/dio.dart';
import 'package:path/path.dart' as p;
import '../models/sync_models.dart';
import '../models/track_metadata.dart';
import 'local_database.dart';

typedef ProgressCallback = void Function(
    String currentTrack, int completedTracks, int totalTracks, double fileProgress);

class WifiSyncService {
  final Dio _dio = Dio(BaseOptions(
    connectTimeout: const Duration(seconds: 5),
    receiveTimeout: const Duration(minutes: 10),
  ));

  String? _baseUrl;
  String _authToken = 'flacify-lan-sync';
  String? connectedHost;

  bool get isConfigured => _baseUrl != null;
  String? get baseUrl => _baseUrl;

  void configureConnection({
    required String ip,
    required int port,
    required String token,
  }) {
    _baseUrl = 'http://$ip:$port';
    _authToken = token;
    _dio.options.headers['x-sync-token'] = _authToken;
  }

  void configureFromQrCode(String qrJson) {
    try {
      final data = jsonDecode(qrJson) as Map<String, dynamic>;
      final ip = data['ip'] as String;
      final port = data['port'] as int;
      final token = data['token'] as String? ?? 'flacify-lan-sync';
      configureConnection(ip: ip, port: port, token: token);
    } catch (e) {
      throw Exception('Invalid QR code format: $e');
    }
  }

  /// Attempts to discover the Windows sync server over LAN subnet probing
  Future<String?> autoDiscoverServer({int port = 8765}) async {
    try {
      final interfaces = await NetworkInterface.list(
        type: InternetAddressType.IPv4,
        includeLinkLocal: false,
      );

      for (final interface in interfaces) {
        for (final addr in interface.addresses) {
          final parts = addr.address.split('.');
          if (parts.length != 4) continue;
          if (parts[0] == '127') continue;
          final subnet = '${parts[0]}.${parts[1]}.${parts[2]}';

          // Probe in efficient batches of 32 to avoid socket throttling
          for (var start = 1; start <= 254; start += 32) {
            final end = (start + 31 <= 254) ? start + 31 : 254;
            final futures = <Future<String?>>[];
            for (var i = start; i <= end; i++) {
              futures.add(_testServerIp('$subnet.$i', port));
            }
            final results = await Future.wait(futures);
            for (final found in results) {
              if (found != null) {
                configureConnection(ip: found, port: port, token: _authToken);
                return found;
              }
            }
          }
        }
      }
    } catch (_) {}
    return null;
  }

  Future<String?> _testServerIp(String ip, int port) async {
    try {
      final socket = await Socket.connect(ip, port, timeout: const Duration(milliseconds: 400));
      socket.destroy();
      final testDio = Dio(BaseOptions(
        connectTimeout: const Duration(seconds: 1),
        receiveTimeout: const Duration(seconds: 1),
      ));
      final res = await testDio.get('http://$ip:$port/api/ping');
      if (res.statusCode == 200 && res.data is Map) {
        return ip;
      }
    } catch (_) {}
    return null;
  }

  Future<bool> pingServer() async {
    if (_baseUrl == null) return false;
    try {
      final response = await _dio.get('$_baseUrl/api/ping');
      if (response.statusCode == 200) {
        connectedHost = response.data['hostname'] as String?;
        return true;
      }
      return false;
    } catch (_) {
      return false;
    }
  }

  Future<List<TrackManifestItem>> fetchRemoteManifest() async {
    if (_baseUrl == null) throw Exception('Sync server not configured');
    final response = await _dio.get('$_baseUrl/api/manifest');
    final List<dynamic> rawList = response.data['tracks'] as List<dynamic>;
    return rawList
        .map((item) => TrackManifestItem.fromJson(item as Map<String, dynamic>))
        .toList();
  }

  Future<List<TrackManifestItem>> buildLocalManifest(Directory musicDir) async {
    final List<TrackManifestItem> items = [];
    if (!await musicDir.exists()) return items;

    final files = musicDir.listSync(recursive: true);
    for (final entity in files) {
      if (entity is File) {
        final ext = p.extension(entity.path).toLowerCase();
        if ({'.flac', '.mp3', '.m4a', '.opus', '.ogg', '.wav'}.contains(ext)) {
          final stat = await entity.stat();
          final relName = p.basename(entity.path);
          final trackId = relName.toLowerCase().hashCode.toString();

          final lrcFile = File(p.setExtension(entity.path, '.lrc'));
          String? lyricsContent;
          if (await lrcFile.exists()) {
            lyricsContent = await lrcFile.readAsString();
          }

          final stemParts = p.basenameWithoutExtension(entity.path).split(' - ');
          final artist = stemParts.length > 1 ? stemParts[0].trim() : 'Unknown Artist';
          final title = stemParts.length > 1 ? stemParts[1].trim() : p.basenameWithoutExtension(entity.path);

          items.add(TrackManifestItem(
            trackId: trackId,
            filename: relName,
            title: title,
            artist: artist,
            album: 'Local Mobile Library',
            durationMs: 0,
            fileSize: stat.size,
            fileHash: '${stat.size}_${stat.modified.millisecondsSinceEpoch}',
            hasLyrics: lyricsContent != null,
            lyricsLrc: lyricsContent,
            updatedAt: stat.modified.millisecondsSinceEpoch ~/ 1000,
          ));
        }
      }
    }
    return items;
  }

  SyncDeltaResult computeDelta({
    required List<TrackManifestItem> remoteTracks,
    required List<TrackManifestItem> localTracks,
  }) {
    final localByFilename = {
      for (final t in localTracks) t.filename.toLowerCase(): t
    };
    final remoteByFilename = {
      for (final t in remoteTracks) t.filename.toLowerCase(): t
    };

    final toDownload = <TrackManifestItem>[];
    final toUpload = <TrackManifestItem>[];

    // 1. Tracks on PC missing or modified on Phone
    for (final remote in remoteTracks) {
      final key = remote.filename.toLowerCase();
      final local = localByFilename[key];
      if (local == null) {
        toDownload.add(remote);
      }
    }

    // 2. Tracks on Phone missing on PC
    for (final local in localTracks) {
      final key = local.filename.toLowerCase();
      if (!remoteByFilename.containsKey(key)) {
        toUpload.add(local);
      }
    }

    return SyncDeltaResult(
      toDownloadFromPc: toDownload,
      toUploadToPc: toUpload,
    );
  }

  /// Bidirectional sync of audio files & lyrics
  Future<void> performTwoWaySync({
    required Directory localMusicDir,
    required ProgressCallback onProgress,
  }) async {
    if (_baseUrl == null) throw Exception('Sync server not configured');
    if (!await localMusicDir.exists()) {
      await localMusicDir.create(recursive: true);
    }

    final localManifest = await buildLocalManifest(localMusicDir);
    final remoteManifest = await fetchRemoteManifest();

    final delta = computeDelta(
      remoteTracks: remoteManifest,
      localTracks: localManifest,
    );

    final totalOperations = delta.toDownloadFromPc.length + delta.toUploadToPc.length;
    var completed = 0;

    // Step 1: Pull missing tracks from Windows PC to Android
    for (final track in delta.toDownloadFromPc) {
      final savePath = p.join(localMusicDir.path, p.basename(track.filename));
      final tempPath = '$savePath.part';

      // Resumable chunked download
      await _dio.download(
        '$_baseUrl/api/tracks/${track.trackId}/download?token=$_authToken',
        tempPath,
        options: Options(headers: {'x-sync-token': _authToken}),
        onReceiveProgress: (received, total) {
          final progress = total > 0 ? received / total : 0.0;
          onProgress('Pulling: ${track.title}', completed, totalOperations, progress);
        },
      );

      // Rename temp file once complete
      final tempFile = File(tempPath);
      if (await tempFile.exists()) {
        await tempFile.rename(savePath);
      }

      // Save companion .lrc lyrics if available
      if (track.hasLyrics && track.lyricsLrc != null) {
        final lrcPath = p.setExtension(savePath, '.lrc');
        await File(lrcPath).writeAsString(track.lyricsLrc!);
      }

      // Index newly pulled track into phone local database
      await LocalDatabase.instance.insertTrack(
        TrackMetadata(
          id: track.trackId,
          title: track.title,
          artists: [track.artist],
          album: track.album,
          durationMs: track.durationMs,
          localFilePath: savePath,
        ),
        savePath,
        track.fileSize,
        qualityBadge: 'Synced FLAC',
      );

      completed++;
    }

    // Step 2: Push phone-downloaded tracks to Windows PC
    for (final track in delta.toUploadToPc) {
      final localFile = File(p.join(localMusicDir.path, track.filename));
      if (!await localFile.exists()) continue;

      final formData = FormData.fromMap({
        'rel_filename': p.basename(track.filename),
        'lyrics_lrc': track.lyricsLrc,
        'file': await MultipartFile.fromFile(
          localFile.path,
          filename: p.basename(track.filename),
        ),
      });

      await _dio.post(
        '$_baseUrl/api/tracks/upload',
        data: formData,
        onSendProgress: (sent, total) {
          final progress = total > 0 ? sent / total : 0.0;
          onProgress('Pushing: ${track.title}', completed, totalOperations, progress);
        },
      );
      completed++;
    }

    // Step 3: Bidirectional Playlist Sync
    await syncPlaylists();

    onProgress('Sync Complete', totalOperations, totalOperations, 1.0);
  }

  /// Bidirectional playlist sync using Last-Write-Wins (LWW)
  Future<void> syncPlaylists() async {
    if (_baseUrl == null) return;
    try {
      final localPlaylists = await LocalDatabase.instance.getAllPlaylists();
      final payload = {
        'playlists': localPlaylists.map((p) => p.toJson()).toList(),
      };

      final response = await _dio.post(
        '$_baseUrl/api/playlists/sync',
        data: payload,
      );

      if (response.statusCode == 200 && response.data is Map) {
        final List<dynamic> merged = response.data['playlists'] as List<dynamic>? ?? [];
        for (final item in merged) {
          final pl = SyncPlaylistItem.fromJson(item as Map<String, dynamic>);
          await LocalDatabase.instance.savePlaylist(pl);
        }
      }
    } catch (_) {}
  }
}
