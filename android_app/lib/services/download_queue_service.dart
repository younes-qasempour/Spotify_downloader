import 'dart:io';
import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';
import 'package:path/path.dart' as p;
import 'package:path_provider/path_provider.dart';
import '../models/queue_item.dart';
import 'audio_tagger.dart';
import 'local_database.dart';
import 'lrclib_service.dart';
import 'musilon_engine.dart';
import 'spotify_resolver.dart';

class DownloadQueueService extends ChangeNotifier {
  final List<QueueItem> _items = [];
  final SpotifyResolver _spotifyResolver = SpotifyResolver();
  final MusilonEngine _musilonEngine = MusilonEngine();
  final LrcLibService _lrcService = LrcLibService();
  final AudioTagger _tagger = AudioTagger();

  final int _concurrency = 2;
  int _activeCount = 0;
  final Map<String, CancelToken> _cancelTokens = {};

  List<QueueItem> get items => List.unmodifiable(_items);
  int get pendingCount => _items.where((i) => i.status == QueueStatus.pending).length;
  int get activeCount => _items.where((i) =>
      i.status == QueueStatus.downloading ||
      i.status == QueueStatus.resolving ||
      i.status == QueueStatus.tagging).length;
  int get completedCount => _items.where((i) => i.status == QueueStatus.completed).length;

  Future<void> addUrl(String url, {String format = 'flac'}) async {
    try {
      final tracks = await _spotifyResolver.resolveUrl(url);
      for (final t in tracks) {
        final item = QueueItem(
          id: '${t.id}_${DateTime.now().millisecondsSinceEpoch}',
          track: t,
          targetFormat: format,
        );
        _items.add(item);
      }
      notifyListeners();
      _triggerProcess();
    } catch (e) {
      rethrow;
    }
  }

  void _triggerProcess() {
    if (_activeCount < _concurrency) {
      _processNext();
    }
  }

  Future<void> _processNext() async {
    while (_activeCount < _concurrency) {
      final pendingIndex = _items.indexWhere((i) => i.status == QueueStatus.pending);
      if (pendingIndex == -1) break;

      final item = _items[pendingIndex];
      item.status = QueueStatus.resolving;
      _activeCount++;
      _downloadItem(item).whenComplete(() {
        _activeCount--;
        _processNext();
      });
    }
  }

  Future<void> _downloadItem(QueueItem item) async {
    final cancelToken = CancelToken();
    _cancelTokens[item.id] = cancelToken;
    String? savePath;

    void cleanupFile() {
      if (savePath != null) {
        try {
          final f = File(savePath);
          if (f.existsSync()) {
            f.deleteSync();
          }
        } catch (_) {}
      }
    }

    try {
      if (item.status == QueueStatus.cancelled) {
        cleanupFile();
        return;
      }
      item.statusMessage = 'Resolving lossless stream & lyrics...';
      notifyListeners();

      // 1. Fetch lyrics in parallel
      final lyricsFuture = _lrcService.fetchLyrics(item.track);

      // 2. Resolve audio source
      final source = await _musilonEngine.resolveTrack(item.track, preferredQuality: item.targetFormat);
      if (item.status == QueueStatus.cancelled) {
        cleanupFile();
        return;
      }
      if (source == null) {
        throw Exception('Audio stream unavailable for this track');
      }

      item.qualityBadge = source.qualityTier;
      item.status = QueueStatus.downloading;
      item.statusMessage = 'Downloading ${source.qualityTier}...';
      notifyListeners();

      // 3. Prepare target destination
      final musicDir = await _getMusicDirectory();
      if (item.status == QueueStatus.cancelled) {
        cleanupFile();
        return;
      }
      final ext = source.fileExtension;
      final filename = '${item.track.safeFilename}.$ext';
      savePath = p.join(musicDir.path, filename);

      await _musilonEngine.downloadStream(
        source,
        savePath,
        cancelToken: cancelToken,
        onProgress: (pVal) {
          item.progress = pVal;
          notifyListeners();
        },
      );
      if (item.status == QueueStatus.cancelled) {
        cleanupFile();
        return;
      }

      // 4. Tag audio file and embed lyrics
      item.status = QueueStatus.tagging;
      item.statusMessage = 'Embedding metadata & artwork...';
      notifyListeners();

      final lyrics = await lyricsFuture;
      if (item.status == QueueStatus.cancelled) {
        cleanupFile();
        return;
      }
      final audioFile = File(savePath);
      await _tagger.tagAudioFile(
        audioFile: audioFile,
        track: item.track,
        lyrics: lyrics,
        saveLrcFile: true,
      );
      if (item.status == QueueStatus.cancelled) {
        cleanupFile();
        return;
      }

      // 5. Save to local SQLite library
      final stat = await audioFile.stat();
      if (item.status == QueueStatus.cancelled) {
        cleanupFile();
        return;
      }
      await LocalDatabase.instance.insertTrack(
        item.track,
        savePath,
        stat.size,
        qualityBadge: source.qualityTier,
      );
      if (item.status == QueueStatus.cancelled) {
        cleanupFile();
        return;
      }

      item.status = QueueStatus.completed;
      item.statusMessage = 'Downloaded (${source.qualityTier})';
      item.progress = 1.0;
      item.downloadedPath = savePath;
      notifyListeners();
    } catch (e) {
      if ((e is DioException && e.type == DioExceptionType.cancel) || item.status == QueueStatus.cancelled) {
        item.status = QueueStatus.cancelled;
        item.statusMessage = 'Cancelled';
        cleanupFile();
      } else {
        item.status = QueueStatus.error;
        item.statusMessage = 'Error: $e';
      }
      notifyListeners();
    } finally {
      _cancelTokens.remove(item.id);
    }
  }

  Future<Directory> _getMusicDirectory() async {
    Directory? extDir;
    try {
      final dirs = await getExternalStorageDirectories(type: StorageDirectory.music);
      if (dirs != null && dirs.isNotEmpty) {
        extDir = dirs.first;
      }
    } catch (_) {}

    extDir ??= await getApplicationDocumentsDirectory();
    final flacifyDir = Directory(p.join(extDir.path, 'FlacifyMusic'));
    if (!await flacifyDir.exists()) {
      await flacifyDir.create(recursive: true);
    }
    return flacifyDir;
  }

  void retryItem(String id) {
    final index = _items.indexWhere((i) => i.id == id);
    if (index == -1) return;
    final item = _items[index];
    item.status = QueueStatus.pending;
    item.progress = 0.0;
    item.statusMessage = 'Queued for retry...';
    notifyListeners();
    _triggerProcess();
  }

  void cancelItem(String id) {
    final index = _items.indexWhere((i) => i.id == id);
    if (index == -1) return;
    final item = _items[index];
    item.status = QueueStatus.cancelled;
    item.statusMessage = 'Cancelled';
    _cancelTokens[id]?.cancel('Cancelled by user');
    notifyListeners();
  }

  void clearCompleted() {
    _items.removeWhere((i) => i.status == QueueStatus.completed);
    notifyListeners();
  }
}
