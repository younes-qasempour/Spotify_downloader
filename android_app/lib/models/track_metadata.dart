class TrackMetadata {
  final String id;
  final String title;
  final List<String> artists;
  final String album;
  final String releaseDate;
  final int durationMs;
  final int trackNumber;
  final int discNumber;
  final String isrc;
  final String coverUrl;
  final String collectionType; // "track", "album", "playlist"
  final String collectionName;
  final String collectionCoverUrl;
  final String? localFilePath;
  final String? qualityBadge;

  TrackMetadata({
    required this.id,
    required this.title,
    required this.artists,
    required this.album,
    this.releaseDate = '',
    this.durationMs = 0,
    this.trackNumber = 1,
    this.discNumber = 1,
    this.isrc = '',
    this.coverUrl = '',
    this.collectionType = 'track',
    this.collectionName = 'Singles',
    this.collectionCoverUrl = '',
    this.localFilePath,
    this.qualityBadge,
  });

  String get primaryArtist => artists.isNotEmpty ? artists.first : 'Unknown Artist';
  String get artistStr => artists.isNotEmpty ? artists.join(', ') : 'Unknown Artist';
  double get durationSec => durationMs / 1000.0;

  String get safeFilename {
    final clean = '$artistStr - $title'
        .replaceAll(RegExp(r'[\\/:*?"<>|]'), '_')
        .trim();
    return clean.length > 100 ? clean.substring(0, 100) : clean;
  }

  factory TrackMetadata.fromMap(Map<String, dynamic> map) {
    List<String> artistsList = [];
    if (map['artist'] is String) {
      artistsList = (map['artist'] as String).split(', ').map((e) => e.trim()).toList();
    } else if (map['artists'] is List) {
      artistsList = (map['artists'] as List).map((e) => e.toString()).toList();
    }

    return TrackMetadata(
      id: map['spotify_id'] ?? map['id'] ?? '',
      title: map['title'] ?? 'Unknown Title',
      artists: artistsList.isNotEmpty ? artistsList : ['Unknown Artist'],
      album: map['album'] ?? 'Unknown Album',
      releaseDate: map['release_date'] ?? '',
      durationMs: map['duration_ms'] ?? 0,
      trackNumber: map['track_number'] ?? 1,
      discNumber: map['disc_number'] ?? 1,
      isrc: map['isrc'] ?? '',
      coverUrl: map['cover_url'] ?? '',
      collectionType: map['collection_type'] ?? 'track',
      collectionName: map['collection_name'] ?? 'Singles',
      collectionCoverUrl: map['collection_cover_url'] ?? '',
      localFilePath: map['file_path'],
      qualityBadge: map['quality_badge'],
    );
  }

  Map<String, dynamic> toMap() {
    return {
      'spotify_id': id,
      'title': title,
      'artist': artistStr,
      'album': album,
      'duration_ms': durationMs,
      'track_number': trackNumber,
      'disc_number': discNumber,
      'isrc': isrc,
      'cover_url': coverUrl,
      'collection_type': collectionType,
      'collection_name': collectionName,
      'collection_cover_url': collectionCoverUrl,
      'file_path': localFilePath,
      'quality_badge': qualityBadge,
    };
  }
}

