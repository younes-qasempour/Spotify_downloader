import 'dart:io';
import 'package:flutter/material.dart';
import 'package:path/path.dart' as p;
import 'package:path_provider/path_provider.dart';
import 'package:provider/provider.dart';
import '../../models/sync_models.dart';
import '../../models/track_metadata.dart';
import '../../services/audio_player_service.dart';
import '../../services/download_queue_service.dart';
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
  List<SyncPlaylistItem> _playlists = [];
  List<SyncPlaylistItem> _filteredPlaylists = [];
  String _selectedFilter = 'tracks';
  final TextEditingController _searchController = TextEditingController();
  bool _isLoading = true;
  int _lastCompletedDownloads = 0;
  DownloadQueueService? _queueService;

  @override
  void initState() {
    super.initState();
    _loadLibrary();
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final queue = Provider.of<DownloadQueueService>(context);
    if (_queueService != queue) {
      _queueService?.removeListener(_onQueueChanged);
      _queueService = queue;
      _lastCompletedDownloads = queue.completedCount;
      _queueService?.addListener(_onQueueChanged);
    }
  }

  void _onQueueChanged() {
    final currentCompleted = _queueService?.completedCount ?? 0;
    if (currentCompleted != _lastCompletedDownloads) {
      _lastCompletedDownloads = currentCompleted;
      _loadLibrary();
    }
  }

  @override
  void dispose() {
    _queueService?.removeListener(_onQueueChanged);
    _searchController.dispose();
    super.dispose();
  }

  Future<void> _loadLibrary() async {
    setState(() => _isLoading = true);
    final tracks = await LocalDatabase.instance.getAllTracks();
    final playlists = await LocalDatabase.instance.getAllPlaylists();
    if (mounted) {
      setState(() {
        _tracks = tracks;
        _playlists = playlists;
        _applySearch();
        _isLoading = false;
      });
    }
  }

  void _applySearch() {
    final query = _searchController.text.trim().toLowerCase();
    if (query.isEmpty) {
      _filteredTracks = List.from(_tracks);
      _filteredPlaylists = List.from(_playlists);
    } else {
      _filteredTracks = _tracks.where((t) {
        return t.title.toLowerCase().contains(query) ||
            t.artistStr.toLowerCase().contains(query) ||
            t.album.toLowerCase().contains(query);
      }).toList();
      _filteredPlaylists = _playlists.where((p) {
        return p.name.toLowerCase().contains(query);
      }).toList();
    }
  }

  String _formatDuration(int ms) {
    final d = Duration(milliseconds: ms);
    final minutes = d.inMinutes;
    final seconds = d.inSeconds % 60;
    return '$minutes:${seconds.toString().padLeft(2, '0')}';
  }

  Future<Directory> _getFlacifyMusicDir() async {
    Directory? musicDir;
    try {
      final dirs = await getExternalStorageDirectories(type: StorageDirectory.music);
      if (dirs != null && dirs.isNotEmpty) {
        musicDir = dirs.first;
      }
    } catch (_) {}
    musicDir ??= await getApplicationDocumentsDirectory();
    final flacifyDir = Directory(p.join(musicDir.path, 'FlacifyMusic'));
    if (!await flacifyDir.exists()) {
      await flacifyDir.create(recursive: true);
    }
    return flacifyDir;
  }

  Future<void> _exportCurrentViewToM3u8() async {
    if (_filteredTracks.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('No tracks to export.')),
      );
      return;
    }
    try {
      final dir = await _getFlacifyMusicDir();
      final name = _selectedFilter == 'tracks'
          ? 'Flacify_Tracks'
          : 'Flacify_${_selectedFilter[0].toUpperCase()}${_selectedFilter.substring(1)}';
      final path = await LocalDatabase.instance.exportM3u8Playlist(
        name: name,
        tracks: _filteredTracks,
        targetDirPath: dir.path,
      );
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('Exported playlist to: $path'),
            backgroundColor: FlacifyTheme.cardDark,
          ),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Export failed: $e')),
        );
      }
    }
  }

  Future<void> _exportPlaylistToM3u8(SyncPlaylistItem pl) async {
    final matchingTracks = _tracks.where((localTrack) {
      return pl.tracks.any((pt) =>
          pt.spotifyId == localTrack.id ||
          (pt.title.toLowerCase() == localTrack.title.toLowerCase() &&
              pt.artist.toLowerCase() == localTrack.artistStr.toLowerCase()));
    }).toList();

    if (matchingTracks.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('No downloaded tracks found for "${pl.name}".'),
          duration: const Duration(seconds: 2),
        ),
      );
      return;
    }

    try {
      final dir = await _getFlacifyMusicDir();
      final path = await LocalDatabase.instance.exportM3u8Playlist(
        name: pl.name,
        tracks: matchingTracks,
        targetDirPath: dir.path,
      );
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('Exported playlist to: $path'),
            backgroundColor: FlacifyTheme.cardDark,
          ),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Export failed: $e')),
        );
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Your Library'),
        actions: [
          IconButton(
            icon: const Icon(Icons.playlist_add_check, color: FlacifyTheme.textSecondary),
            tooltip: 'Export M3U8 Playlist',
            onPressed: _exportCurrentViewToM3u8,
          ),
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

          // Content Area based on Filter
          Expanded(
            child: _isLoading
                ? const Center(child: CircularProgressIndicator(color: FlacifyTheme.spotifyEmerald))
                : RefreshIndicator(
                    onRefresh: _loadLibrary,
                    color: FlacifyTheme.spotifyEmerald,
                    child: _buildContent(),
                  ),
          ),
        ],
      ),
    );
  }

  Widget _buildContent() {
    switch (_selectedFilter) {
      case 'playlists':
        return _buildPlaylistList();
      case 'albums':
        return _buildAlbumList();
      case 'artists':
        return _buildArtistList();
      case 'tracks':
      default:
        return _buildTrackList();
    }
  }

  Widget _buildTrackList() {
    if (_filteredTracks.isEmpty) {
      return _buildEmptyView(
        _tracks.isEmpty
            ? 'Your offline library is empty.\nDownload songs or sync from your Windows PC.'
            : 'No tracks match your search.',
      );
    }

    return ListView.builder(
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
    );
  }

  Widget _buildPlaylistList() {
    if (_filteredPlaylists.isEmpty) {
      return _buildEmptyView(
        _playlists.isEmpty
            ? 'No playlists found.\nSync playlists from your PC via Wi-Fi Sync.'
            : 'No playlists match your search.',
      );
    }

    return ListView.builder(
      itemCount: _filteredPlaylists.length,
      itemBuilder: (context, index) {
        final pl = _filteredPlaylists[index];

        return ListTile(
          leading: ClipRRect(
            borderRadius: BorderRadius.circular(4),
            child: pl.coverUrl.isNotEmpty
                ? Image.network(
                    pl.coverUrl,
                    width: 48,
                    height: 48,
                    fit: BoxFit.cover,
                    errorBuilder: (_, __, ___) => _playlistCoverFallback(),
                  )
                : _playlistCoverFallback(),
          ),
          title: Text(
            pl.name,
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: const TextStyle(
              fontWeight: FontWeight.bold,
              color: FlacifyTheme.textPrimary,
              fontSize: 14,
            ),
          ),
          subtitle: Text(
            '${pl.tracks.isNotEmpty ? pl.tracks.length : pl.totalTracks} tracks',
            style: const TextStyle(color: FlacifyTheme.textSecondary, fontSize: 12),
          ),
          trailing: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              IconButton(
                icon: const Icon(Icons.file_download_outlined, color: FlacifyTheme.textSecondary, size: 22),
                tooltip: 'Export to M3U8',
                onPressed: () => _exportPlaylistToM3u8(pl),
              ),
              IconButton(
                icon: const Icon(Icons.play_circle_fill, color: FlacifyTheme.spotifyEmerald, size: 28),
                onPressed: () {
                  final matchingTracks = _tracks.where((localTrack) {
                    return pl.tracks.any((pt) =>
                        pt.spotifyId == localTrack.id ||
                        (pt.title.toLowerCase() == localTrack.title.toLowerCase() &&
                            pt.artist.toLowerCase() == localTrack.artistStr.toLowerCase()));
                  }).toList();

                  if (matchingTracks.isNotEmpty) {
                    widget.audioHandler.loadPlaylist(matchingTracks, startIndex: 0);
                  } else {
                    ScaffoldMessenger.of(context).showSnackBar(
                      SnackBar(
                        content: Text('No downloaded tracks found for "${pl.name}".'),
                        duration: const Duration(seconds: 2),
                      ),
                    );
                  }
                },
              ),
            ],
          ),
          onTap: () {
            final matchingTracks = _tracks.where((localTrack) {
              return pl.tracks.any((pt) =>
                  pt.spotifyId == localTrack.id ||
                  (pt.title.toLowerCase() == localTrack.title.toLowerCase() &&
                      pt.artist.toLowerCase() == localTrack.artistStr.toLowerCase()));
            }).toList();

            if (matchingTracks.isNotEmpty) {
              widget.audioHandler.loadPlaylist(matchingTracks, startIndex: 0);
            } else {
              ScaffoldMessenger.of(context).showSnackBar(
                SnackBar(
                  content: Text('No downloaded tracks found for "${pl.name}".'),
                  duration: const Duration(seconds: 2),
                ),
              );
            }
          },
        );
      },
    );
  }

  Widget _buildAlbumList() {
    final Map<String, List<TrackMetadata>> albums = {};
    for (final track in _filteredTracks) {
      final name = track.album.isNotEmpty ? track.album : 'Unknown Album';
      albums.putIfAbsent(name, () => []).add(track);
    }

    if (albums.isEmpty) {
      return _buildEmptyView('No albums found.');
    }

    final albumKeys = albums.keys.toList();

    return ListView.builder(
      itemCount: albumKeys.length,
      itemBuilder: (context, index) {
        final albumName = albumKeys[index];
        final albumTracks = albums[albumName]!;
        final firstTrack = albumTracks.first;

        return ListTile(
          leading: ClipRRect(
            borderRadius: BorderRadius.circular(4),
            child: firstTrack.coverUrl.isNotEmpty
                ? Image.network(
                    firstTrack.coverUrl,
                    width: 48,
                    height: 48,
                    fit: BoxFit.cover,
                    errorBuilder: (_, __, ___) => _fallbackCover(),
                  )
                : _fallbackCover(),
          ),
          title: Text(
            albumName,
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: const TextStyle(
              fontWeight: FontWeight.bold,
              color: FlacifyTheme.textPrimary,
              fontSize: 14,
            ),
          ),
          subtitle: Text(
            '${firstTrack.primaryArtist} • ${albumTracks.length} song(s)',
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: const TextStyle(color: FlacifyTheme.textSecondary, fontSize: 12),
          ),
          trailing: const Icon(Icons.play_circle_fill, color: FlacifyTheme.spotifyEmerald, size: 28),
          onTap: () {
            final sorted = List<TrackMetadata>.from(albumTracks)
              ..sort((a, b) => a.trackNumber.compareTo(b.trackNumber));
            widget.audioHandler.loadPlaylist(sorted, startIndex: 0);
          },
        );
      },
    );
  }

  Widget _buildArtistList() {
    final Map<String, List<TrackMetadata>> artists = {};
    for (final track in _filteredTracks) {
      final name = track.primaryArtist.isNotEmpty ? track.primaryArtist : 'Unknown Artist';
      artists.putIfAbsent(name, () => []).add(track);
    }

    if (artists.isEmpty) {
      return _buildEmptyView('No artists found.');
    }

    final artistKeys = artists.keys.toList();

    return ListView.builder(
      itemCount: artistKeys.length,
      itemBuilder: (context, index) {
        final artistName = artistKeys[index];
        final artistTracks = artists[artistName]!;
        final firstTrack = artistTracks.first;

        return ListTile(
          leading: CircleAvatar(
            backgroundColor: FlacifyTheme.elevatedDark,
            backgroundImage: firstTrack.coverUrl.isNotEmpty ? NetworkImage(firstTrack.coverUrl) : null,
            child: firstTrack.coverUrl.isEmpty
                ? const Icon(Icons.person, color: FlacifyTheme.textSecondary)
                : null,
          ),
          title: Text(
            artistName,
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: const TextStyle(
              fontWeight: FontWeight.bold,
              color: FlacifyTheme.textPrimary,
              fontSize: 14,
            ),
          ),
          subtitle: Text(
            '${artistTracks.length} song(s)',
            style: const TextStyle(color: FlacifyTheme.textSecondary, fontSize: 12),
          ),
          trailing: const Icon(Icons.play_circle_fill, color: FlacifyTheme.spotifyEmerald, size: 28),
          onTap: () {
            widget.audioHandler.loadPlaylist(artistTracks, startIndex: 0);
          },
        );
      },
    );
  }

  Widget _buildEmptyView(String message) {
    return Center(
      child: SingleChildScrollView(
        physics: const AlwaysScrollableScrollPhysics(),
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 32, vertical: 48),
          child: Text(
            message,
            textAlign: TextAlign.center,
            style: const TextStyle(color: FlacifyTheme.textSecondary, height: 1.5),
          ),
        ),
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

  Widget _playlistCoverFallback() {
    return Container(
      width: 48,
      height: 48,
      color: FlacifyTheme.elevatedDark,
      child: const Icon(Icons.queue_music, color: FlacifyTheme.textSecondary),
    );
  }
}

