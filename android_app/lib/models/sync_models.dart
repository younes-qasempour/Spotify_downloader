class TrackManifestItem {
  final String trackId;
  final String filename;
  final String title;
  final String artist;
  final String album;
  final int durationMs;
  final int fileSize;
  final String fileHash;
  final bool hasLyrics;
  final String? lyricsLrc;
  final String? coverHash;
  final int updatedAt;

  TrackManifestItem({
    required this.trackId,
    required this.filename,
    required this.title,
    required this.artist,
    required this.album,
    required this.durationMs,
    required this.fileSize,
    required this.fileHash,
    required this.hasLyrics,
    this.lyricsLrc,
    this.coverHash,
    required this.updatedAt,
  });

  factory TrackManifestItem.fromJson(Map<String, dynamic> json) {
    return TrackManifestItem(
      trackId: json['track_id'] as String,
      filename: json['filename'] as String,
      title: json['title'] as String,
      artist: json['artist'] as String,
      album: json['album'] as String? ?? 'Synced Library',
      durationMs: json['duration_ms'] as int? ?? 0,
      fileSize: json['file_size'] as int,
      fileHash: json['file_hash'] as String,
      hasLyrics: json['has_lyrics'] as bool? ?? false,
      lyricsLrc: json['lyrics_lrc'] as String?,
      coverHash: json['cover_hash'] as String?,
      updatedAt: json['updated_at'] as int? ?? 0,
    );
  }

  Map<String, dynamic> toJson() => {
        'track_id': trackId,
        'filename': filename,
        'title': title,
        'artist': artist,
        'album': album,
        'duration_ms': durationMs,
        'file_size': fileSize,
        'file_hash': fileHash,
        'has_lyrics': hasLyrics,
        'lyrics_lrc': lyricsLrc,
        'cover_hash': coverHash,
        'updated_at': updatedAt,
      };
}

class SyncPlaylistTrack {
  final String spotifyId;
  final String title;
  final String artist;
  final String album;
  final int durationMs;
  final int trackNumber;
  final String coverUrl;

  SyncPlaylistTrack({
    required this.spotifyId,
    required this.title,
    required this.artist,
    this.album = '',
    this.durationMs = 0,
    this.trackNumber = 1,
    this.coverUrl = '',
  });

  factory SyncPlaylistTrack.fromJson(Map<String, dynamic> json) {
    return SyncPlaylistTrack(
      spotifyId: json['spotify_id'] as String? ?? '',
      title: json['title'] as String? ?? 'Unknown',
      artist: json['artist'] as String? ?? 'Unknown',
      album: json['album'] as String? ?? '',
      durationMs: json['duration_ms'] as int? ?? 0,
      trackNumber: json['track_number'] as int? ?? 1,
      coverUrl: json['cover_url'] as String? ?? '',
    );
  }

  Map<String, dynamic> toJson() => {
        'spotify_id': spotifyId,
        'title': title,
        'artist': artist,
        'album': album,
        'duration_ms': durationMs,
        'track_number': trackNumber,
        'cover_url': coverUrl,
      };
}

class SyncPlaylistItem {
  final String id;
  final String name;
  final String spotifyUrl;
  final String coverUrl;
  final int totalTracks;
  final int updatedAt; // Unix timestamp
  final List<SyncPlaylistTrack> tracks;

  SyncPlaylistItem({
    required this.id,
    required this.name,
    this.spotifyUrl = '',
    this.coverUrl = '',
    required this.totalTracks,
    required this.updatedAt,
    this.tracks = const [],
  });

  factory SyncPlaylistItem.fromJson(Map<String, dynamic> json) {
    final rawTracks = json['tracks'] as List<dynamic>? ?? [];
    return SyncPlaylistItem(
      id: json['id'] as String,
      name: json['name'] as String,
      spotifyUrl: json['spotify_url'] as String? ?? '',
      coverUrl: json['cover_url'] as String? ?? '',
      totalTracks: json['total_tracks'] as int? ?? rawTracks.length,
      updatedAt: json['updated_at'] as int? ?? 0,
      tracks: rawTracks
          .map((t) => SyncPlaylistTrack.fromJson(t as Map<String, dynamic>))
          .toList(),
    );
  }

  Map<String, dynamic> toJson() => {
        'id': id,
        'name': name,
        'spotify_url': spotifyUrl,
        'cover_url': coverUrl,
        'total_tracks': totalTracks,
        'updated_at': updatedAt,
        'tracks': tracks.map((t) => t.toJson()).toList(),
      };
}

class SyncDeltaResult {
  final List<TrackManifestItem> toDownloadFromPc;
  final List<TrackManifestItem> toUploadToPc;

  SyncDeltaResult({
    required this.toDownloadFromPc,
    required this.toUploadToPc,
  });
}
