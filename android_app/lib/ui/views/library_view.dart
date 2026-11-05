import 'package:flutter/material.dart';
import '../../models/track_metadata.dart';
import '../../services/audio_player_service.dart';
import '../../services/local_database.dart';
import '../theme.dart';

class LibraryView extends StatefulWidget {
  final AudioPlayerHandler audioHandler;

  const LibraryView({super.key, required this.audioHandler});

  @override
  State<LibraryView> createState() => _LibraryViewState();
}

class _LibraryViewState extends State<LibraryView> {
  List<TrackMetadata> _tracks = [];
  List<TrackMetadata> _filteredTracks = [];
  String _selectedFilter = 'tracks';
  final TextEditingController _searchController = TextEditingController();
  bool _isLoading = true;

  @override
  void initState() {
    super.initState();
    _loadLibrary();
  }

  Future<void> _loadLibrary() async {
    setState(() => _isLoading = true);
    final tracks = await LocalDatabase.instance.getAllTracks();
    if (mounted) {
      setState(() {
        _tracks = tracks;
        _applySearch();
        _isLoading = false;
      });
    }
  }

  void _applySearch() {
    final query = _searchController.text.trim().toLowerCase();
    if (query.isEmpty) {
      _filteredTracks = List.from(_tracks);
    } else {
      _filteredTracks = _tracks.where((t) {
        return t.title.toLowerCase().contains(query) ||
            t.artistStr.toLowerCase().contains(query) ||
            t.album.toLowerCase().contains(query);
      }).toList();
    }
  }

  String _formatDuration(int ms) {
    final d = Duration(milliseconds: ms);
    final minutes = d.inMinutes;
    final seconds = d.inSeconds % 60;
    return '$minutes:${seconds.toString().padLeft(2, '0')}';
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Your Library'),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh, color: FlacifyTheme.textSecondary),
            onPressed: _loadLibrary,
          ),
        ],
      ),
      body: Column(
        children: [
          // Search Bar
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
            child: TextField(
              controller: _searchController,
              onChanged: (_) => setState(_applySearch),
              style: const TextStyle(color: FlacifyTheme.textPrimary, fontSize: 14),
              decoration: InputDecoration(
                hintText: 'Search songs, artists, or albums...',
                hintStyle: const TextStyle(color: FlacifyTheme.textSecondary, fontSize: 13),
                filled: true,
                fillColor: FlacifyTheme.cardDark,
                prefixIcon: const Icon(Icons.search, color: FlacifyTheme.textSecondary, size: 20),
                border: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(10),
                  borderSide: BorderSide.none,
                ),
                contentPadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
              ),
            ),
          ),

          // Filter Chips Row
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
            child: Row(
              children: [
                _buildFilterChip('Tracks', 'tracks'),
                const SizedBox(width: 8),
                _buildFilterChip('Playlists', 'playlists'),
                const SizedBox(width: 8),
                _buildFilterChip('Albums', 'albums'),
                const SizedBox(width: 8),
                _buildFilterChip('Artists', 'artists'),
              ],
            ),
          ),
          const SizedBox(height: 8),

          // Track List
          Expanded(
            child: _isLoading
                ? const Center(child: CircularProgressIndicator(color: FlacifyTheme.spotifyEmerald))
                : _filteredTracks.isEmpty
                    ? Center(
                        child: Text(
                          _tracks.isEmpty
                              ? 'Your offline library is empty.\nDownload songs or sync from your Windows PC.'
                              : 'No matches found.',
                          textAlign: TextAlign.center,
                          style: const TextStyle(color: FlacifyTheme.textSecondary, height: 1.5),
                        ),
                      )
                    : RefreshIndicator(
                        onRefresh: _loadLibrary,
                        color: FlacifyTheme.spotifyEmerald,
                        child: ListView.builder(
                          itemCount: _filteredTracks.length,
                          itemBuilder: (context, index) {
                            final track = _filteredTracks[index];
                            final isPlaying = widget.audioHandler.currentTrack?.id == track.id;

                            return ListTile(
                              leading: ClipRRect(
                                borderRadius: BorderRadius.circular(4),
                                child: track.coverUrl.isNotEmpty
                                    ? Image.network(
                                        track.coverUrl,
                                        width: 48,
                                        height: 48,
                                        fit: BoxFit.cover,
                                        errorBuilder: (_, __, ___) => _fallbackCover(),
                                      )
                                    : _fallbackCover(),
                              ),
                              title: Text(
                                track.title,
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                                style: TextStyle(
                                  fontWeight: FontWeight.bold,
                                  color: isPlaying ? FlacifyTheme.spotifyEmerald : FlacifyTheme.textPrimary,
                                  fontSize: 14,
                                ),
                              ),
                              subtitle: Text(
                                '${track.artistStr} • ${track.album}',
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                                style: const TextStyle(color: FlacifyTheme.textSecondary, fontSize: 12),
                              ),
                              trailing: Row(
                                mainAxisSize: MainAxisSize.min,
                                children: [
                                  if (track.qualityBadge != null)
                                    Container(
                                      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                                      decoration: BoxDecoration(
                                        color: FlacifyTheme.elevatedDark,
                                        borderRadius: BorderRadius.circular(4),
                                      ),
                                      child: Text(
                                        track.qualityBadge!,
                                        style: const TextStyle(
                                          color: FlacifyTheme.spotifyEmerald,
                                          fontSize: 10,
                                          fontWeight: FontWeight.bold,
                                        ),
                                      ),
                                    ),
                                  const SizedBox(width: 8),
                                  Text(
                                    _formatDuration(track.durationMs),
                                    style: const TextStyle(color: FlacifyTheme.textSecondary, fontSize: 12),
                                  ),
                                ],
                              ),
                              onTap: () {
                                widget.audioHandler.loadPlaylist(_filteredTracks, startIndex: index);
                              },
                            );
                          },
                        ),
                      ),
          ),
        ],
      ),
    );
  }

  Widget _buildFilterChip(String label, String value) {
    final isSelected = _selectedFilter == value;
    return ChoiceChip(
      label: Text(label),
      selected: isSelected,
      onSelected: (selected) {
        if (selected) setState(() => _selectedFilter = value);
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

  Widget _fallbackCover() {
    return Container(
      width: 48,
      height: 48,
      color: FlacifyTheme.elevatedDark,
      child: const Icon(Icons.music_note, color: FlacifyTheme.textSecondary),
    );
  }
}

