import 'dart:convert';
import 'dart:io';
import 'package:path/path.dart' as p;
import 'package:path_provider/path_provider.dart';
import 'package:sqflite/sqflite.dart';
import '../models/track_metadata.dart';
import '../models/sync_models.dart';

class LocalDatabase {
  static final LocalDatabase instance = LocalDatabase._init();
  static Database? _database;

  LocalDatabase._init();

  Future<Database> get database async {
    if (_database != null) return _database!;
    _database = await _initDB('flacify_library.db');
    return _database!;
  }

  Future<Database> _initDB(String filePath) async {
    final docsDir = await getApplicationDocumentsDirectory();
    final path = p.join(docsDir.path, filePath);

    return await openDatabase(
      path,
      version: 2,
      onCreate: _createDB,
      onUpgrade: (db, oldVersion, newVersion) async {
        if (oldVersion < 2) {
          await db.execute("ALTER TABLE downloaded_tracks ADD COLUMN cover_url TEXT DEFAULT '';");
          await db.execute("ALTER TABLE downloaded_tracks ADD COLUMN release_date TEXT DEFAULT '';");
        }
      },
    );
  }

  Future<void> _createDB(Database db, int version) async {
    await db.execute('''
      CREATE TABLE downloaded_tracks (
        spotify_id TEXT PRIMARY KEY,
        isrc TEXT,
        title TEXT NOT NULL,
        artist TEXT NOT NULL,
        album TEXT,
        release_date TEXT DEFAULT '',
        duration_ms INTEGER,
        track_number INTEGER DEFAULT 1,
        disc_number INTEGER DEFAULT 1,
        cover_url TEXT DEFAULT '',
        file_path TEXT NOT NULL,
        file_size INTEGER DEFAULT 0,
        quality_badge TEXT DEFAULT 'FLAC',
        source_type TEXT DEFAULT 'Direct',
        collection_name TEXT,
        collection_type TEXT,
        genre TEXT DEFAULT '',
        downloaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
      );
    ''');

    await db.execute('''
      CREATE TABLE saved_playlists (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        spotify_url TEXT,
        cover_url TEXT,
        total_tracks INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
      );
    ''');

    await db.execute('''
      CREATE TABLE saved_playlist_tracks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        playlist_id TEXT NOT NULL,
        spotify_id TEXT NOT NULL,
        title TEXT NOT NULL,
        artist TEXT NOT NULL,
        album TEXT,
        duration_ms INTEGER DEFAULT 0,
        track_number INTEGER DEFAULT 1,
        disc_number INTEGER DEFAULT 1,
        isrc TEXT,
        cover_url TEXT,
        status TEXT DEFAULT 'pending',
        file_path TEXT DEFAULT '',
        quality_badge TEXT DEFAULT '',
        source_type TEXT DEFAULT '',
        added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(playlist_id, spotify_id)
      );
    ''');
  }

  Future<void> insertTrack(
    TrackMetadata track,
    String filePath,
    int fileSize, {
    String qualityBadge = 'FLAC',
    String sourceType = 'Musilon',
  }) async {
    final db = await database;
    await db.insert(
      'downloaded_tracks',
      {
        'spotify_id': track.id,
        'isrc': track.isrc,
        'title': track.title,
        'artist': track.artistStr,
        'album': track.album,
        'release_date': track.releaseDate,
        'duration_ms': track.durationMs,
        'track_number': track.trackNumber,
        'disc_number': track.discNumber,
        'cover_url': track.coverUrl,
        'file_path': filePath,
        'file_size': fileSize,
        'quality_badge': qualityBadge,
        'source_type': sourceType,
        'collection_name': track.collectionName,
        'collection_type': track.collectionType,
      },
      conflictAlgorithm: ConflictAlgorithm.replace,
    );
  }

  Future<List<TrackMetadata>> getAllTracks() async {
    final db = await database;
    final rows = await db.query('downloaded_tracks', orderBy: 'downloaded_at DESC');
    return rows.map((r) => TrackMetadata.fromMap(r)).toList();
  }

  Future<List<SyncPlaylistItem>> getAllPlaylists() async {
    final db = await database;
    final plRows = await db.query('saved_playlists', orderBy: 'updated_at DESC');
    final List<SyncPlaylistItem> playlists = [];

    for (final pl in plRows) {
      final pid = pl['id'] as String;
      final trkRows = await db.query(
        'saved_playlist_tracks',
        where: 'playlist_id = ?',
        whereArgs: [pid],
        orderBy: 'track_number ASC',
      );

      final tracks = trkRows.map((t) => SyncPlaylistTrack.fromJson(t)).toList();
      final rawUpdated = pl['updated_at'];
      int updatedAt = 0;
      if (rawUpdated is int) {
        updatedAt = rawUpdated;
      } else if (rawUpdated is String) {
        final parsedInt = int.tryParse(rawUpdated);
        if (parsedInt != null) {
          updatedAt = parsedInt;
        } else {
          final parsedDt = DateTime.tryParse(rawUpdated);
          updatedAt = (parsedDt?.millisecondsSinceEpoch ?? 0) ~/ 1000;
        }
      }

      playlists.add(SyncPlaylistItem(
        id: pid,
        name: pl['name'] as String,
        spotifyUrl: pl['spotify_url'] as String? ?? '',
        coverUrl: pl['cover_url'] as String? ?? '',
        totalTracks: pl['total_tracks'] as int? ?? tracks.length,
        updatedAt: updatedAt,
        tracks: tracks,
      ));
    }
    return playlists;
  }

  Future<void> savePlaylist(SyncPlaylistItem playlist) async {
    final db = await database;
    await db.transaction((txn) async {
      await txn.insert(
        'saved_playlists',
        {
          'id': playlist.id,
          'name': playlist.name,
          'spotify_url': playlist.spotifyUrl,
          'cover_url': playlist.coverUrl,
          'total_tracks': playlist.tracks.length,
          'updated_at': playlist.updatedAt > 0 ? playlist.updatedAt : (DateTime.now().millisecondsSinceEpoch ~/ 1000),
        },
        conflictAlgorithm: ConflictAlgorithm.replace,
      );

      await txn.delete('saved_playlist_tracks', where: 'playlist_id = ?', whereArgs: [playlist.id]);

      for (final t in playlist.tracks) {
        await txn.insert(
          'saved_playlist_tracks',
          {
            'playlist_id': playlist.id,
            'spotify_id': t.spotifyId,
            'title': t.title,
            'artist': t.artist,
            'album': t.album,
            'duration_ms': t.durationMs,
            'track_number': t.trackNumber,
            'cover_url': t.coverUrl,
          },
          conflictAlgorithm: ConflictAlgorithm.replace,
        );
      }
    });
  }

  Future<String> exportM3u8Playlist({
    required String name,
    required List<TrackMetadata> tracks,
    required String targetDirPath,
  }) async {
    final dir = Directory(targetDirPath);
    if (!await dir.exists()) {
      await dir.create(recursive: true);
    }

    final sanitizedName = name.replaceAll(RegExp(r'[\\/:*?"<>|]'), '_').trim();
    final fileName = sanitizedName.isEmpty ? 'playlist.m3u8' : '$sanitizedName.m3u8';
    final filePath = p.join(targetDirPath, fileName);

    final buffer = StringBuffer();
    buffer.writeln('#EXTM3U');
    buffer.writeln('#PLAYLIST:$name');

    for (final t in tracks) {
      if (t.localFilePath != null && t.localFilePath!.isNotEmpty) {
        final secs = (t.durationMs / 1000).round();
        buffer.writeln('#EXTINF:$secs,${t.artistStr} - ${t.title}');
        String relPath;
        try {
          relPath = p.relative(t.localFilePath!, from: targetDirPath).replaceAll('\\', '/');
        } catch (_) {
          relPath = p.basename(t.localFilePath!);
        }
        buffer.writeln(relPath);
      }
    }

    final file = File(filePath);
    await file.writeAsString(buffer.toString(), encoding: utf8);
    return filePath;
  }

  Future<void> deleteTrack(String spotifyId) async {
    final db = await database;
    await db.delete('downloaded_tracks', where: 'spotify_id = ?', whereArgs: [spotifyId]);
  }
}
