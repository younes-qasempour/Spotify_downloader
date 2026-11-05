import 'track_metadata.dart';

enum QueueStatus {
  pending,
  resolving,
  downloading,
  tagging,
  completed,
  error,
  cancelled,
}

class QueueItem {
  final String id;
  final TrackMetadata track;
  QueueStatus status;
  double progress; // 0.0 to 1.0
  String statusMessage;
  String targetFormat; // 'flac' or 'mp3'
  String? qualityBadge;
  String? downloadedPath;
  DateTime addedTime;

  QueueItem({
    required this.id,
    required this.track,
    this.status = QueueStatus.pending,
    this.progress = 0.0,
    this.statusMessage = 'Waiting in queue...',
    this.targetFormat = 'flac',
    this.qualityBadge,
    this.downloadedPath,
    DateTime? addedTime,
  }) : addedTime = addedTime ?? DateTime.now();
}

