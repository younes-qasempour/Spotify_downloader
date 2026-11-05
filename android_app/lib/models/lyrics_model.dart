class LyricsLine {
  final int timestampMs;
  final String text;

  LyricsLine({required this.timestampMs, required this.text});
}

class LyricsData {
  final String? syncedLyrics;
  final String? plainLyrics;
  final bool instrumental;
  final List<LyricsLine> lines;

  LyricsData({
    this.syncedLyrics,
    this.plainLyrics,
    this.instrumental = false,
    List<LyricsLine>? lines,
  }) : lines = lines ?? (syncedLyrics != null ? parseLrc(syncedLyrics) : []);

  bool get hasLyrics =>
      (syncedLyrics != null && syncedLyrics!.trim().isNotEmpty) ||
      (plainLyrics != null && plainLyrics!.trim().isNotEmpty) ||
      lines.isNotEmpty;

  static List<LyricsLine> parseLrc(String lrcText) {
    final List<LyricsLine> result = [];
    final tagRegExp = RegExp(r'\[(\d+):(\d+(?:\.\d+)?)\]');

    for (final rawLine in lrcText.split('\n')) {
      final line = rawLine.trim();
      if (line.isEmpty) continue;
      final matches = tagRegExp.allMatches(line).toList();
      if (matches.isEmpty) continue;

      final text = line.replaceAll(tagRegExp, '').trim();

      for (final match in matches) {
        final minutes = int.tryParse(match.group(1) ?? '0') ?? 0;
        final seconds = double.tryParse(match.group(2) ?? '0') ?? 0.0;
        final timestampMs = ((minutes * 60 + seconds) * 1000).round();
        result.add(LyricsLine(timestampMs: timestampMs, text: text));
      }
    }

    result.sort((a, b) => a.timestampMs.compareTo(b.timestampMs));
    return result;
  }

  int activeLineIndexAt(int positionMs) {
    if (lines.isEmpty || positionMs < lines.first.timestampMs) {
      return -1;
    }
    int low = 0;
    int high = lines.length - 1;
    int candidate = -1;

    while (low <= high) {
      final mid = low + ((high - low) >> 1);
      if (lines[mid].timestampMs <= positionMs) {
        candidate = mid;
        low = mid + 1;
      } else {
        high = mid - 1;
      }
    }
    return candidate;
  }

  LyricsLine? activeLineAt(int positionMs) {
    final idx = activeLineIndexAt(positionMs);
    return idx >= 0 && idx < lines.length ? lines[idx] : null;
  }

  String toLrcString() {
    if (syncedLyrics != null && syncedLyrics!.trim().isNotEmpty) {
      return syncedLyrics!;
    }
    if (lines.isNotEmpty) {
      final buffer = StringBuffer();
      for (final line in lines) {
        final totalSec = line.timestampMs / 1000.0;
        final mins = (totalSec / 60).floor();
        final remSec = totalSec - (mins * 60);
        final minStr = mins.toString().padLeft(2, '0');
        final secStr = remSec.toStringAsFixed(2).padLeft(5, '0');
        buffer.writeln('[$minStr:$secStr]${line.text}');
      }
      return buffer.toString().trimRight();
    }
    return plainLyrics ?? '';
  }
}

