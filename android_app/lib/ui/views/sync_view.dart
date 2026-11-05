import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:path_provider/path_provider.dart';
import 'package:path/path.dart' as p;
import '../../services/wifi_sync_service.dart';
import '../theme.dart';

class MobileSyncView extends StatefulWidget {
  final WifiSyncService syncService;

  const MobileSyncView({super.key, required this.syncService});

  @override
  State<MobileSyncView> createState() => _MobileSyncViewState();
}

class _MobileSyncViewState extends State<MobileSyncView> {
  bool _isDiscovering = false;
  bool _isSyncing = false;
  String _statusText = 'Ready to sync with Windows laptop';
  double _currentProgress = 0.0;
  final List<String> _logs = [];

  final TextEditingController _ipController = TextEditingController();
  final TextEditingController _portController = TextEditingController(text: '8765');
  final TextEditingController _tokenController = TextEditingController(text: '');

  @override
  void initState() {
    super.initState();
    _checkInitialConnection();
  }

  @override
  void dispose() {
    _ipController.dispose();
    _portController.dispose();
    _tokenController.dispose();
    super.dispose();
  }

  Future<void> _checkInitialConnection() async {
    final loaded = await widget.syncService.loadSavedConnection();
    if (loaded) {
      if (widget.syncService.ip != null) {
        _ipController.text = widget.syncService.ip!;
      }
      if (widget.syncService.port != null) {
        _portController.text = widget.syncService.port.toString();
      }
      _tokenController.text = widget.syncService.token;
    }
    if (widget.syncService.isConfigured) {
      await widget.syncService.pingServer();
    }
    if (mounted) setState(() {});
  }

  Future<void> _autoDiscover() async {
    setState(() {
      _isDiscovering = true;
      _statusText = 'Scanning local Wi-Fi subnet for Windows PC...';
    });
    _addLog('Starting mDNS / LAN subnet auto-discovery...');

    final discoveredIp = await widget.syncService.autoDiscoverServer();
    if (mounted) {
      setState(() {
        _isDiscovering = false;
        if (discoveredIp != null) {
          _statusText = 'Found PC at $discoveredIp:8765';
          _addLog('Connected to PC: $discoveredIp');
        } else {
          _statusText = 'No PC found on current Wi-Fi subnet.';
          _addLog('Auto-discovery timed out. Try manual IP or QR code.');
        }
      });
    }
  }

  void _addLog(String msg) {
    setState(() {
      _logs.insert(0, '[${DateTime.now().toIso8601String().substring(11, 19)}] $msg');
    });
  }

  Future<void> _startTwoWaySync() async {
    if (!widget.syncService.isConfigured) {
      _showManualConfigDialog();
      return;
    }

    setState(() {
      _isSyncing = true;
      _currentProgress = 0.0;
      _statusText = 'Connecting to Windows PC...';
    });
    _addLog('Initiating bidirectional sync...');

    try {
      Directory? musicDir;
      final dirs = await getExternalStorageDirectories(type: StorageDirectory.music);
      if (dirs != null && dirs.isNotEmpty) {
        musicDir = dirs.first;
      }
      musicDir ??= await getApplicationDocumentsDirectory();
      final flacifyDir = Directory(p.join(musicDir.path, 'FlacifyMusic'));

      await widget.syncService.performTwoWaySync(
        localMusicDir: flacifyDir,
        onProgress: (currentTrack, completed, total, fileProgress) {
          if (mounted) {
            setState(() {
              _statusText = '$currentTrack ($completed/$total)';
              _currentProgress = fileProgress;
            });
            if (fileProgress >= 1.0) {
              _addLog('$currentTrack completed');
            }
          }
        },
      );

      _addLog('Library & Playlists successfully synchronized!');
      if (mounted) {
        setState(() {
          _statusText = 'Synchronization Complete!';
        });
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Library & Playlists synced with Windows PC!')),
        );
      }
    } catch (e) {
      _addLog('Sync Error: $e');
      if (mounted) {
        setState(() {
          _statusText = 'Sync failed: $e';
        });
      }
    } finally {
      if (mounted) setState(() => _isSyncing = false);
    }
  }

  void _showManualConfigDialog() {
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: FlacifyTheme.cardDark,
        title: const Text('Configure PC Sync Server'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            OutlinedButton.icon(
              icon: const Icon(Icons.content_paste, size: 16),
              label: const Text('Paste Pairing Code'),
              style: OutlinedButton.styleFrom(
                foregroundColor: FlacifyTheme.spotifyEmerald,
                side: const BorderSide(color: FlacifyTheme.spotifyEmerald),
                padding: const EdgeInsets.symmetric(vertical: 10),
              ),
              onPressed: () async {
                final data = await Clipboard.getData(Clipboard.kTextPlain);
                if (!mounted) return;
                final text = data?.text?.trim() ?? '';
                if (text.isNotEmpty) {
                  try {
                    widget.syncService.configureFromQrCode(text);
                    if (widget.syncService.ip != null) {
                      _ipController.text = widget.syncService.ip!;
                    }
                    if (widget.syncService.port != null) {
                      _portController.text = widget.syncService.port.toString();
                    }
                    _tokenController.text = widget.syncService.token;
                    if (ctx.mounted) Navigator.pop(ctx);
                    _checkInitialConnection();
                    if (!mounted) return;
                    ScaffoldMessenger.of(context).showSnackBar(
                      const SnackBar(content: Text('Pairing code applied successfully.')),
                    );
                  } catch (e) {
                    if (!mounted) return;
                    ScaffoldMessenger.of(context).showSnackBar(
                      SnackBar(content: Text('Invalid pairing code: $e')),
                    );
                  }
                } else {
                  if (!mounted) return;
                  ScaffoldMessenger.of(context).showSnackBar(
                    const SnackBar(content: Text('Clipboard is empty.')),
                  );
                }
              },
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _ipController,
              decoration: const InputDecoration(
                labelText: 'Windows PC LAN IP',
                hintText: 'e.g. 192.168.1.100',
              ),
            ),
            const SizedBox(height: 10),
            TextField(
              controller: _portController,
              decoration: const InputDecoration(
                labelText: 'Port',
                hintText: '8765',
              ),
              keyboardType: TextInputType.number,
            ),
            const SizedBox(height: 10),
            TextField(
              controller: _tokenController,
              decoration: const InputDecoration(
                labelText: 'Sync Token',
              ),
            ),
          ],
        ),
        actions: [
          TextButton(
            child: const Text('Cancel', style: TextStyle(color: FlacifyTheme.textSecondary)),
            onPressed: () => Navigator.pop(ctx),
          ),
          ElevatedButton(
            style: ElevatedButton.styleFrom(
              backgroundColor: FlacifyTheme.spotifyEmerald,
              foregroundColor: Colors.black,
            ),
            child: const Text('Connect'),
            onPressed: () {
              widget.syncService.configureConnection(
                ip: _ipController.text.trim(),
                port: int.tryParse(_portController.text.trim()) ?? 8765,
                token: _tokenController.text.trim(),
              );
              Navigator.pop(ctx);
              _checkInitialConnection();
            },
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Local Wi-Fi Sync'),
        actions: [
          IconButton(
            icon: const Icon(Icons.settings, color: FlacifyTheme.textSecondary),
            onPressed: _showManualConfigDialog,
          ),
        ],
      ),
      body: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            // Connection Status Card
            Container(
              padding: const EdgeInsets.all(18),
              decoration: BoxDecoration(
                color: FlacifyTheme.cardDark,
                borderRadius: BorderRadius.circular(14),
                border: Border.all(color: FlacifyTheme.dividerColor),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      const Text(
                        'Windows Laptop Pairing',
                        style: TextStyle(fontWeight: FontWeight.bold, fontSize: 16),
                      ),
                      Container(
                        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                        decoration: BoxDecoration(
                          color: widget.syncService.isConfigured
                              ? const Color(0xFF12331C)
                              : FlacifyTheme.elevatedDark,
                          borderRadius: BorderRadius.circular(12),
                        ),
                        child: Text(
                          widget.syncService.isConfigured ? 'PAIRED' : 'NOT PAIRED',
                          style: TextStyle(
                            color: widget.syncService.isConfigured
                                ? FlacifyTheme.spotifyEmerald
                                : FlacifyTheme.textSecondary,
                            fontWeight: FontWeight.bold,
                            fontSize: 11,
                          ),
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 10),
                  Text(
                    widget.syncService.isConfigured
                        ? 'Target: ${widget.syncService.baseUrl}'
                        : 'Tap Auto-Discover or configure your PC IP to pair over local Wi-Fi.',
                    style: const TextStyle(color: FlacifyTheme.textSecondary, fontSize: 13),
                  ),
                  const SizedBox(height: 14),
                  Row(
                    children: [
                      Expanded(
                        child: OutlinedButton.icon(
                          icon: _isDiscovering
                              ? const SizedBox(
                                  width: 14,
                                  height: 14,
                                  child: CircularProgressIndicator(strokeWidth: 2, color: FlacifyTheme.spotifyEmerald),
                                )
                              : const Icon(Icons.wifi_find, size: 18),
                          label: const Text('Auto-Discover'),
                          style: OutlinedButton.styleFrom(
                            foregroundColor: FlacifyTheme.textPrimary,
                            side: const BorderSide(color: FlacifyTheme.dividerColor),
                          ),
                          onPressed: _isDiscovering ? null : _autoDiscover,
                        ),
                      ),
                      const SizedBox(width: 10),
                      Expanded(
                        child: OutlinedButton.icon(
                          icon: const Icon(Icons.qr_code_scanner, size: 18),
                          label: const Text('Enter Code'),
                          style: OutlinedButton.styleFrom(
                            foregroundColor: FlacifyTheme.textPrimary,
                            side: const BorderSide(color: FlacifyTheme.dividerColor),
                          ),
                          onPressed: _showManualConfigDialog,
                        ),
                      ),
                    ],
                  ),
                ],
              ),
            ),
            const SizedBox(height: 18),

            // Sync Action Button
            ElevatedButton.icon(
              icon: _isSyncing
                  ? const SizedBox(
                      width: 18,
                      height: 18,
                      child: CircularProgressIndicator(strokeWidth: 2, color: Colors.black),
                    )
                  : const Icon(Icons.sync, color: Colors.black),
              label: Text(
                _isSyncing ? 'Synchronizing...' : 'Sync Library Now',
                style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 16),
              ),
              style: ElevatedButton.styleFrom(
                backgroundColor: FlacifyTheme.spotifyEmerald,
                foregroundColor: Colors.black,
                padding: const EdgeInsets.symmetric(vertical: 16),
                shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
              ),
              onPressed: _isSyncing ? null : _startTwoWaySync,
            ),
            const SizedBox(height: 16),

            // Live Transfer Status Card
            Container(
              padding: const EdgeInsets.all(14),
              decoration: BoxDecoration(
                color: FlacifyTheme.cardDark,
                borderRadius: BorderRadius.circular(10),
                border: Border.all(color: FlacifyTheme.dividerColor),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    _statusText,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                      color: FlacifyTheme.spotifyEmerald,
                      fontWeight: FontWeight.bold,
                      fontSize: 13,
                    ),
                  ),
                  if (_isSyncing) ...[
                    const SizedBox(height: 8),
                    LinearProgressIndicator(
                      value: _currentProgress > 0 ? _currentProgress : null,
                      backgroundColor: FlacifyTheme.elevatedDark,
                      valueColor: const AlwaysStoppedAnimation<Color>(FlacifyTheme.spotifyEmerald),
                      minHeight: 5,
                    ),
                  ],
                ],
              ),
            ),
            const SizedBox(height: 16),

            // Activity Log
            const Text(
              'SYNC LOGS',
              style: TextStyle(
                color: FlacifyTheme.textSecondary,
                fontSize: 12,
                fontWeight: FontWeight.bold,
                letterSpacing: 1.0,
              ),
            ),
            const SizedBox(height: 8),
            Expanded(
              child: Container(
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: const Color(0xFF151515),
                  borderRadius: BorderRadius.circular(8),
                  border: Border.all(color: FlacifyTheme.dividerColor),
                ),
                child: _logs.isEmpty
                    ? const Center(
                        child: Text(
                          'No sync events logged yet.',
                          style: TextStyle(color: FlacifyTheme.textSecondary, fontSize: 12),
                        ),
                      )
                    : ListView.builder(
                        itemCount: _logs.length,
                        itemBuilder: (context, idx) => Padding(
                          padding: const EdgeInsets.symmetric(vertical: 3),
                          child: Text(
                            _logs[idx],
                            style: const TextStyle(
                              color: Color(0xFFCCCCCC),
                              fontSize: 11,
                              fontFamily: 'monospace',
                            ),
                          ),
                        ),
                      ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
