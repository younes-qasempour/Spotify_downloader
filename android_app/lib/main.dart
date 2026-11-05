import 'package:audio_service/audio_service.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';
import 'services/audio_player_service.dart';
import 'services/download_queue_service.dart';
import 'services/wifi_sync_service.dart';
import 'ui/main_screen.dart';
import 'ui/theme.dart';

late AudioPlayerHandler _audioHandler;

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();

  // Set system navigation bar & status bar transparent for edge-to-edge dark theme
  SystemChrome.setSystemUIOverlayStyle(const SystemUiOverlayStyle(
    statusBarColor: Colors.transparent,
    statusBarIconBrightness: Brightness.light,
    systemNavigationBarColor: FlacifyTheme.spotifyBlack,
    systemNavigationBarIconBrightness: Brightness.light,
  ));

  // Initialize Background Audio Service
  _audioHandler = await AudioService.init(
    builder: () => AudioPlayerHandler(),
    config: const AudioServiceConfig(
      androidNotificationChannelId: 'com.flacify.app.channel.audio',
      androidNotificationChannelName: 'Flacify Music Playback',
      androidNotificationOngoing: true,
      androidStopForegroundOnPause: true,
    ),
  );

  final syncService = WifiSyncService();

  runApp(
    MultiProvider(
      providers: [
        ChangeNotifierProvider(create: (_) => DownloadQueueService()),
      ],
      child: FlacifyApp(
        audioHandler: _audioHandler,
        syncService: syncService,
      ),
    ),
  );
}

class FlacifyApp extends StatefulWidget {
  final AudioPlayerHandler audioHandler;
  final WifiSyncService syncService;

  const FlacifyApp({
    super.key,
    required this.audioHandler,
    required this.syncService,
  });

  @override
  State<FlacifyApp> createState() => _FlacifyAppState();
}

class _FlacifyAppState extends State<FlacifyApp> {
  static const MethodChannel _intentChannel = MethodChannel('com.flacify.app/intent');

  @override
  void initState() {
    super.initState();
    _handleIncomingShareIntent();
  }

  Future<void> _handleIncomingShareIntent() async {
    try {
      final sharedText = await _intentChannel.invokeMethod<String>('getSharedText');
      if (sharedText != null && sharedText.contains('spotify.com')) {
        if (mounted) {
          final queue = Provider.of<DownloadQueueService>(context, listen: false);
          await queue.addUrl(sharedText.trim());
        }
      }
    } catch (_) {}
  }

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Flacify Mobile',
      debugShowCheckedModeBanner: false,
      theme: FlacifyTheme.darkTheme,
      home: MainScreen(
        audioHandler: widget.audioHandler,
        syncService: widget.syncService,
      ),
    );
  }
}
