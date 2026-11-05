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

  static List<LyricsLine> parseLrc(String lrcText) {
    final List<LyricsLine> result = [];
    final regExp = RegExp(r'\[(\d+):(\d+(?:\.\d+)?)\](.*)');

    for (final rawLine in lrcText.split('\n')) {
      final line = rawLine.trim();
      if (line.isEmpty) continue;
      final match = regExp.firstMatch(line);
      if (match != null) {
        final minutes = int.tryParse(match.group(1) ?? '0') ?? 0;
        final seconds = double.tryParse(match.group(2) ?? '0') ?? 0.0;
        final text = (match.group(3) ?? '').trim();
        final timestampMs = ((minutes * 60 + seconds) * 1000).toInt();
        result.add(LyricsLine(timestampMs: timestampMs, text: text));
      }
    }

    result.sort((a, b) => a.timestampMs.compareTo(b.timestampMs));
    return result;
  }
}

