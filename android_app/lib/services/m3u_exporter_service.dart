import 'dart:io';
import 'package:path/path.dart' as p;
import '../models/track_metadata.dart';

class M3uExporterService {
  Future<File> exportPlaylistToM3u8({
    required String playlistName,
    required List<TrackMetadata> tracks,
    required Directory outputDir,
    bool useRelativePaths = true,
  }) async {
    if (!await outputDir.exists()) {
      await outputDir.create(recursive: true);
    }

    final sanitizedName = playlistName
        .replaceAll(RegExp(r'[\x00-\x1f\\/:*?"<>|]'), '_')
        .replaceAll(RegExp(r'\s+'), ' ')
        .trim();
    final fileName =
        sanitizedName.isEmpty ? 'playlist.m3u8' : '$sanitizedName.m3u8';

    final targetFile = File(p.join(outputDir.path, fileName));
    final tmpFile = File(p.join(outputDir.path, '.$fileName.tmp'));

    final buffer = StringBuffer();
    buffer.writeln('#EXTM3U');
    buffer.writeln('#PLAYLIST:$playlistName');

    for (final track in tracks) {
      final localPath = track.localFilePath;
      if (localPath == null || localPath.trim().isEmpty) continue;

      final duration = track.durationSec.round();
      buffer.writeln('#EXTINF:$duration,${track.artistStr} - ${track.title}');

      if (useRelativePaths) {
        try {
          final relPath = p.relative(localPath, from: outputDir.path);
          buffer.writeln(relPath);
        } catch (_) {
          buffer.writeln(localPath);
        }
      } else {
        buffer.writeln(localPath);
      }
    }

    await tmpFile.writeAsString(buffer.toString(), flush: true);
    if (await targetFile.exists()) {
      await targetFile.delete();
    }
    return await tmpFile.rename(targetFile.path);
  }
}

