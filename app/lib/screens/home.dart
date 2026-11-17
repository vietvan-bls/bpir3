import 'package:material_ui/material_ui.dart';

import '../main.dart';
import 'camera.dart';
import 'more.dart';
import 'music.dart';
import 'network.dart';
import 'overview.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  int _tab = 0;

  static const _titles = ['Tổng quan', 'Camera', 'Mạng', 'Nhạc', 'Thêm'];

  @override
  Widget build(BuildContext context) {
    final api = ApiScope.of(context);
    final host = api.who['hostname'] ?? 'BPI-R3';
    return Scaffold(
      appBar: AppBar(
        title: Text(_tab == 0 ? '$host' : _titles[_tab]),
        actions: [
          Padding(
            padding: const EdgeInsets.only(right: 12),
            child: Chip(
              avatar: Icon(api.isLocal ? Icons.home : Icons.public, size: 16),
              label: Text(api.isLocal ? 'Trong mạng' : 'Internet'),
              visualDensity: VisualDensity.compact,
            ),
          ),
        ],
      ),
      // Không dùng IndexedStack: rời tab Camera thì ngắt stream để đỡ tốn băng thông.
      body: switch (_tab) {
        0 => const OverviewScreen(),
        1 => const CameraScreen(),
        2 => const NetworkScreen(),
        3 => const MusicScreen(),
        _ => const MoreScreen(),
      },
      bottomNavigationBar: NavigationBar(
        selectedIndex: _tab,
        onDestinationSelected: (i) => setState(() => _tab = i),
        destinations: const [
          NavigationDestination(icon: Icon(Icons.dashboard_outlined), selectedIcon: Icon(Icons.dashboard), label: 'Tổng quan'),
          NavigationDestination(icon: Icon(Icons.videocam_outlined), selectedIcon: Icon(Icons.videocam), label: 'Camera'),
          NavigationDestination(icon: Icon(Icons.wifi), label: 'Mạng'),
          NavigationDestination(icon: Icon(Icons.music_note_outlined), selectedIcon: Icon(Icons.music_note), label: 'Nhạc'),
          NavigationDestination(icon: Icon(Icons.more_horiz), label: 'Thêm'),
        ],
      ),
    );
  }
}
