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

  String get formattedDuration {
    final totalSec = (durationMs / 1000).floor();
    final mins = totalSec ~/ 60;
    final secs = totalSec % 60;
    return '${mins.toString().padLeft(2, '0')}:${secs.toString().padLeft(2, '0')}';
  }

  String get highResCoverUrl {
    if (coverUrl.isEmpty) return '';
    return coverUrl
        .replaceAll('ab67616d00001e02', 'ab67616d0000b273')
        .replaceAll('ab67616d00004851', 'ab67616d0000b273');
  }

  String get safeFilename {
    var clean = '$artistStr - $title'
        .replaceAll(RegExp(r'[\x00-\x1f\\/:*?"<>|]'), '_')
        .replaceAll(RegExp(r'\s+'), ' ')
        .trim();
    clean = clean.replaceAll(RegExp(r'[.\s]+$'), '');
    if (clean.isEmpty) {
      clean = 'track';
    }
    return clean.runes.length > 100
        ? String.fromCharCodes(clean.runes.take(100)).trimRight()
        : clean;
  }

  factory TrackMetadata.fromMap(Map<String, dynamic> map) {
    List<String> artistsList = [];
    if (map['artist'] is String) {
      artistsList = (map['artist'] as String)
          .split(', ')
          .map((e) => e.trim())
          .where((e) => e.isNotEmpty)
          .toList();
    } else if (map['artists'] is List) {
      artistsList = (map['artists'] as List)
          .map((e) => e.toString().trim())
          .where((e) => e.isNotEmpty)
          .toList();
    }

    return TrackMetadata(
      id: map['spotify_id']?.toString() ?? map['id']?.toString() ?? '',
      title: map['title']?.toString() ?? 'Unknown Title',
      artists: artistsList.isNotEmpty ? artistsList : ['Unknown Artist'],
      album: map['album']?.toString() ?? 'Unknown Album',
      releaseDate: map['release_date']?.toString() ?? '',
      durationMs: (map['duration_ms'] as num?)?.toInt() ?? 0,
      trackNumber: (map['track_number'] as num?)?.toInt() ?? 1,
      discNumber: (map['disc_number'] as num?)?.toInt() ?? 1,
      isrc: map['isrc']?.toString() ?? '',
      coverUrl: map['cover_url']?.toString() ?? '',
      collectionType: map['collection_type']?.toString() ?? 'track',
      collectionName: map['collection_name']?.toString() ?? 'Singles',
      collectionCoverUrl: map['collection_cover_url']?.toString() ?? '',
      localFilePath: map['file_path']?.toString(),
      qualityBadge: map['quality_badge']?.toString(),
    );
  }

  Map<String, dynamic> toMap() {
    return {
      'spotify_id': id,
      'title': title,
      'artist': artistStr,
      'album': album,
      'release_date': releaseDate,
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

  TrackMetadata copyWith({
    String? id,
    String? title,
    List<String>? artists,
    String? album,
    String? releaseDate,
    int? durationMs,
    int? trackNumber,
    int? discNumber,
    String? isrc,
    String? coverUrl,
    String? collectionType,
    String? collectionName,
    String? collectionCoverUrl,
    String? localFilePath,
    String? qualityBadge,
  }) {
    return TrackMetadata(
      id: id ?? this.id,
      title: title ?? this.title,
      artists: artists ?? this.artists,
      album: album ?? this.album,
      releaseDate: releaseDate ?? this.releaseDate,
      durationMs: durationMs ?? this.durationMs,
      trackNumber: trackNumber ?? this.trackNumber,
      discNumber: discNumber ?? this.discNumber,
      isrc: isrc ?? this.isrc,
      coverUrl: coverUrl ?? this.coverUrl,
      collectionType: collectionType ?? this.collectionType,
      collectionName: collectionName ?? this.collectionName,
      collectionCoverUrl: collectionCoverUrl ?? this.collectionCoverUrl,
      localFilePath: localFilePath ?? this.localFilePath,
      qualityBadge: qualityBadge ?? this.qualityBadge,
    );
  }

  @override
  bool operator ==(Object other) {
    if (identical(this, other)) return true;
    return other is TrackMetadata &&
        other.id == id &&
        other.title == title &&
        other.artistStr == artistStr &&
        other.album == album &&
        other.durationMs == durationMs &&
        other.localFilePath == localFilePath &&
        other.qualityBadge == qualityBadge;
  }

  @override
  int get hashCode => Object.hash(
        id,
        title,
        artistStr,
        album,
        durationMs,
        localFilePath,
        qualityBadge,
      );
}

