import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';
import '../../models/queue_item.dart';
import '../../services/download_queue_service.dart';
import '../theme.dart';

class DownloaderView extends StatefulWidget {
  const DownloaderView({super.key});

  @override
  State<DownloaderView> createState() => _DownloaderViewState();
}

class _DownloaderViewState extends State<DownloaderView> {
  final TextEditingController _urlController = TextEditingController();
  String _selectedFormat = 'flac';
  bool _isLoading = false;

  Future<void> _handleDownload() async {
    final url = _urlController.text.trim();
    if (url.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Please paste a Spotify track, album, or playlist URL')),
      );
      return;
    }

    setState(() => _isLoading = true);
    try {
      final queueService = Provider.of<DownloadQueueService>(context, listen: false);
      await queueService.addUrl(url, format: _selectedFormat);
      _urlController.clear();
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Added to download queue')),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Failed to resolve link: $e'), backgroundColor: Colors.redAccent),
        );
      }
    } finally {
      if (mounted) setState(() => _isLoading = false);
    }
  }

  Future<void> _pasteClipboard() async {
    final data = await Clipboard.getData('text/plain');
    if (data != null && data.text != null) {
      _urlController.text = data.text!;
    }
  }

  @override
  Widget build(BuildContext context) {
    final queue = Provider.of<DownloadQueueService>(context);

    return Scaffold(
      appBar: AppBar(
        title: const Text('Flacify Downloader'),
        actions: [
          if (queue.completedCount > 0)
            IconButton(
              icon: const Icon(Icons.cleaning_services_outlined, color: FlacifyTheme.textSecondary),
              tooltip: 'Clear Completed',
              onPressed: () => queue.clearCompleted(),
            ),
        ],
      ),
      body: Column(
        children: [
          // URL Input & Quality Controls Card
          Container(
            margin: const EdgeInsets.all(16),
            padding: const EdgeInsets.all(16),
            decoration: BoxDecoration(
              color: FlacifyTheme.cardDark,
              borderRadius: BorderRadius.circular(14),
              border: Border.all(color: FlacifyTheme.dividerColor),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                TextField(
                  controller: _urlController,
                  style: const TextStyle(color: FlacifyTheme.textPrimary, fontSize: 14),
                  decoration: InputDecoration(
                    hintText: 'Paste Spotify track, album, or playlist URL...',
                    hintStyle: const TextStyle(color: FlacifyTheme.textSecondary, fontSize: 13),
                    filled: true,
                    fillColor: FlacifyTheme.elevatedDark,
                    border: OutlineInputBorder(
                      borderRadius: BorderRadius.circular(10),
                      borderSide: BorderSide.none,
                    ),
                    prefixIcon: const Icon(Icons.link, color: FlacifyTheme.spotifyEmerald),
                    suffixIcon: IconButton(
                      icon: const Icon(Icons.content_paste, color: FlacifyTheme.textSecondary, size: 20),
                      onPressed: _pasteClipboard,
                      tooltip: 'Paste from clipboard',
                    ),
                  ),
                  onSubmitted: (_) => _handleDownload(),
                ),
                const SizedBox(height: 14),
                Row(
                  children: [
                    // Quality Format Selector Chips
                    _buildQualityChip('FLAC (Lossless)', 'flac'),
                    const SizedBox(width: 8),
                    _buildQualityChip('320k MP3', 'mp3'),
                    const Spacer(),
                    // Download Action Button
                    ElevatedButton(
                      style: ElevatedButton.styleFrom(
                        backgroundColor: FlacifyTheme.spotifyEmerald,
                        foregroundColor: Colors.black,
                        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
                        padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 12),
                      ),
                      onPressed: _isLoading ? null : _handleDownload,
                      child: _isLoading
                          ? const SizedBox(
                              width: 16,
                              height: 16,
                              child: CircularProgressIndicator(strokeWidth: 2, color: Colors.black),
                            )
                          : const Text(
                              'Download',
                              style: TextStyle(fontWeight: FontWeight.bold),
                            ),
                    ),
                  ],
                ),
              ],
            ),
          ),

          // Queue Status Header
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 4),
            child: Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Text(
                  'QUEUE (${queue.items.length})',
                  style: const TextStyle(
                    color: FlacifyTheme.textSecondary,
                    fontSize: 12,
                    fontWeight: FontWeight.bold,
                    letterSpacing: 1.0,
                  ),
                ),
                Text(
                  'Active: ${queue.activeCount} • Pending: ${queue.pendingCount}',
                  style: const TextStyle(color: FlacifyTheme.textSecondary, fontSize: 12),
                ),
              ],
            ),
          ),
          const SizedBox(height: 6),

          // Download Queue List
          Expanded(
            child: queue.items.isEmpty
                ? const Center(
                    child: Text(
                      'Download queue is empty.\nPaste a Spotify URL above or share a song from Spotify.',
                      textAlign: TextAlign.center,
                      style: TextStyle(color: FlacifyTheme.textSecondary, height: 1.5),
                    ),
                  )
                : ListView.builder(
                    padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 6),
                    itemCount: queue.items.length,
                    itemBuilder: (context, index) {
                      final item = queue.items[index];
                      return _buildQueueCard(item, queue);
                    },
                  ),
          ),
        ],
      ),
    );
  }

  Widget _buildQualityChip(String label, String value) {
    final isSelected = _selectedFormat == value;
    return ChoiceChip(
      label: Text(label),
      selected: isSelected,
      onSelected: (selected) {
        if (selected) setState(() => _selectedFormat = value);
      },
      selectedColor: FlacifyTheme.spotifyEmerald.withOpacity(0.2),
      backgroundColor: FlacifyTheme.elevatedDark,
      labelStyle: TextStyle(
        color: isSelected ? FlacifyTheme.spotifyEmerald : FlacifyTheme.textSecondary,
        fontWeight: isSelected ? FontWeight.bold : FontWeight.normal,
        fontSize: 12,
      ),
      side: BorderSide(
        color: isSelected ? FlacifyTheme.spotifyEmerald : Colors.transparent,
      ),
    );
  }

  Widget _buildQueueCard(QueueItem item, DownloadQueueService queue) {
    return Container(
      margin: const EdgeInsets.symmetric(vertical: 6),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: FlacifyTheme.cardDark,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: FlacifyTheme.dividerColor),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              // Cover
              ClipRRect(
                borderRadius: BorderRadius.circular(6),
                child: item.track.coverUrl.isNotEmpty
                    ? Image.network(
                        item.track.coverUrl,
                        width: 48,
                        height: 48,
                        fit: BoxFit.cover,
                        errorBuilder: (_, __, ___) => _fallbackCover(),
                      )
                    : _fallbackCover(),
              ),
              const SizedBox(width: 12),
              // Track Details
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      item.track.title,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(
                        fontWeight: FontWeight.bold,
                        color: FlacifyTheme.textPrimary,
                        fontSize: 14,
                      ),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      item.track.artistStr,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(color: FlacifyTheme.textSecondary, fontSize: 12),
                    ),
                    const SizedBox(height: 4),
                    Text(
                      item.statusMessage,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(
                        color: item.status == QueueStatus.error
                            ? Colors.redAccent
                            : (item.status == QueueStatus.completed
                                ? FlacifyTheme.spotifyEmerald
                                : FlacifyTheme.textSecondary),
                        fontSize: 11,
                      ),
                    ),
                  ],
                ),
              ),
              // Action Buttons
              if (item.status == QueueStatus.error)
                IconButton(
                  icon: const Icon(Icons.refresh, color: FlacifyTheme.spotifyEmerald),
                  onPressed: () => queue.retryItem(item.id),
                )
              else if (item.status == QueueStatus.downloading || item.status == QueueStatus.pending)
                IconButton(
                  icon: const Icon(Icons.close, color: FlacifyTheme.textSecondary),
                  onPressed: () => queue.cancelItem(item.id),
                )
              else if (item.status == QueueStatus.completed)
                const Icon(Icons.check_circle, color: FlacifyTheme.spotifyEmerald, size: 24),
            ],
          ),
          if (item.status == QueueStatus.downloading) ...[
            const SizedBox(height: 8),
            LinearProgressIndicator(
              value: item.progress > 0 ? item.progress : null,
              backgroundColor: FlacifyTheme.elevatedDark,
              valueColor: const AlwaysStoppedAnimation<Color>(FlacifyTheme.spotifyEmerald),
              minHeight: 4,
            ),
          ],
        ],
      ),
    );
  }

  Widget _fallbackCover() {
    return Container(
      width: 48,
      height: 48,
      color: FlacifyTheme.elevatedDark,
      child: const Icon(Icons.music_note, color: FlacifyTheme.textSecondary),
    );
  }
}

