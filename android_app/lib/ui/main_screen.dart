import 'package:flutter/material.dart';
import '../services/audio_player_service.dart';
import '../services/wifi_sync_service.dart';
import 'views/downloader_view.dart';
import 'views/library_view.dart';
import 'views/sync_view.dart';
import 'widgets/mini_player_bar.dart';

class MainScreen extends StatefulWidget {
  final AudioPlayerHandler audioHandler;
  final WifiSyncService syncService;

  const MainScreen({
    super.key,
    required this.audioHandler,
    required this.syncService,
  });

  @override
  State<MainScreen> createState() => _MainScreenState();
}

class _MainScreenState extends State<MainScreen> {
  int _currentIndex = 0;

  @override
  Widget build(BuildContext context) {
    final List<Widget> pages = [
      const DownloaderView(),
      LibraryView(audioHandler: widget.audioHandler),
      MobileSyncView(syncService: widget.syncService),
    ];

    return Scaffold(
      body: Column(
        children: [
          Expanded(
            child: IndexedStack(
              index: _currentIndex,
              children: pages,
            ),
          ),
          MiniPlayerBar(audioHandler: widget.audioHandler),
        ],
      ),
      bottomNavigationBar: BottomNavigationBar(
        currentIndex: _currentIndex,
        onTap: (index) => setState(() => _currentIndex = index),
        items: const [
          BottomNavigationBarItem(
            icon: Icon(Icons.download_rounded),
            label: 'Downloader',
          ),
          BottomNavigationBarItem(
            icon: Icon(Icons.library_music_rounded),
            label: 'Library',
          ),
          BottomNavigationBarItem(
            icon: Icon(Icons.sync_rounded),
            label: 'Wi-Fi Sync',
          ),
        ],
      ),
    );
  }
}
