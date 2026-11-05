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

  double get safeProgress =>
      (progress.isNaN || progress.isInfinite) ? 0.0 : progress.clamp(0.0, 1.0);

  bool get isActive =>
      status == QueueStatus.resolving ||
      status == QueueStatus.downloading ||
      status == QueueStatus.tagging;

  bool get isTerminal =>
      status == QueueStatus.completed ||
      status == QueueStatus.error ||
      status == QueueStatus.cancelled;

  bool get canRetry =>
      status == QueueStatus.error || status == QueueStatus.cancelled;

  bool get canCancel => status == QueueStatus.pending || isActive;

  QueueItem copyWith({
    String? id,
    TrackMetadata? track,
    QueueStatus? status,
    double? progress,
    String? statusMessage,
    String? targetFormat,
    String? qualityBadge,
    String? downloadedPath,
    DateTime? addedTime,
  }) {
    return QueueItem(
      id: id ?? this.id,
      track: track ?? this.track,
      status: status ?? this.status,
      progress: progress ?? this.progress,
      statusMessage: statusMessage ?? this.statusMessage,
      targetFormat: targetFormat ?? this.targetFormat,
      qualityBadge: qualityBadge ?? this.qualityBadge,
      downloadedPath: downloadedPath ?? this.downloadedPath,
      addedTime: addedTime ?? this.addedTime,
    );
  }
}

