import 'dart:async';

import 'package:material_ui/material_ui.dart';
import 'package:flutter/services.dart';

import '../main.dart';
import '../util.dart';

class OverviewScreen extends StatefulWidget {
  const OverviewScreen({super.key});

  @override
  State<OverviewScreen> createState() => _OverviewScreenState();
}

class _OverviewScreenState extends State<OverviewScreen> {
  Map? _s;
  String? _url;
  bool _offline = false;
  bool _newLinkBusy = false;
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    _refresh();
    _loadUrl();
    _timer = Timer.periodic(const Duration(seconds: 2), (_) => _refresh());
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _refresh() async {
    try {
      final s = await ApiScope.read(context).get('/api/status', timeout: const Duration(seconds: 8));
      if (mounted) setState(() {
        _s = s;
        _offline = false;
      });
    } catch (_) {
      if (mounted) setState(() => _offline = true);
    }
  }

  Future<void> _loadUrl() async {
    try {
      final u = (await ApiScope.read(context).get('/api/public-url'))['url'];
      if (mounted) setState(() => _url = u is String && u.isNotEmpty ? u : null);
    } catch (_) {}
  }

  Future<void> _newLink() async {
    final api = ApiScope.read(context);
    final viaPublic = !api.viaLan;
    if (!await confirm(
        context,
        'Tạo link mới?',
        'Link cũ sẽ ngừng hoạt động.' +
            (viaPublic ? '\n\nBạn đang kết nối qua link công khai: app sẽ tự chuyển sang link mới.' : ''))) {
      return;
    }
    setState(() => _newLinkBusy = true);
    try {
      final u = (await api.post('/api/new-link', {}))['url'];
      if (u is String && u.startsWith('https://')) {
        await api.saveUrls(pub: u);
        setState(() => _url = u);
        if (viaPublic) await api.connect();
        if (mounted) toast(context, 'Đã tạo link mới');
      } else if (mounted) {
        toast(context, 'Chưa lấy được link');
      }
    } catch (e) {
      if (mounted) toast(context, 'Lỗi: $e');
    } finally {
      if (mounted) setState(() => _newLinkBusy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = _s;
    final t = Theme.of(context);
    String v(Object? x, [String unit = '']) => x == null ? '—' : '$x$unit';
    final temps = (s?['temps'] as Map?) ?? {};
    final wifiTemps = ['Wi-Fi 2.4G', 'Wi-Fi 5G'].where((k) => temps[k] != null).map((k) => '${temps[k]}°');
    final cam = s?['camera'] as Map?;

    return RefreshIndicator(
      onRefresh: () => Future.wait([_refresh(), _loadUrl()]),
      child: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          if (_offline)
            Card(
              color: t.colorScheme.errorContainer,
              child: const ListTile(
                leading: Icon(Icons.cloud_off),
                title: Text('Mất kết nối tới board. Đang thử lại…'),
              ),
            ),
          if (s == null && !_offline)
            const Padding(padding: EdgeInsets.all(32), child: Center(child: CircularProgressIndicator())),
          if (s != null)
            GridView.count(
              crossAxisCount: MediaQuery.sizeOf(context).width > 600 ? 3 : 2,
              shrinkWrap: true,
              physics: const NeverScrollableScrollPhysics(),
              mainAxisSpacing: 10,
              crossAxisSpacing: 10,
              childAspectRatio: 1.9,
              children: [
                StatCard('Nhiệt độ CPU', v(s['cpu_temp_c'], ' °C'), icon: Icons.thermostat),
                StatCard('Tải CPU 1/5/15′', ((s['load'] as List?) ?? []).join(' / '), icon: Icons.speed),
                StatCard('RAM trống', '${s['mem_free_mb']} / ${s['mem_total_mb']} MB', icon: Icons.memory),
                StatCard('Máy bắt Wi-Fi', v(s['wifi_clients']), icon: Icons.devices),
                StatCard('Đã chạy', fmtDur(s['uptime_s'] as num?), icon: Icons.timer),
                StatCard('Nhiệt chip Wi-Fi', wifiTemps.isEmpty ? '—' : wifiTemps.join(' / '), icon: Icons.wifi),
              ],
            ),
          if (cam != null) ...[
            const SizedBox(height: 10),
            Card(
              child: ListTile(
                leading: const Icon(Icons.videocam),
                title: const Text('Camera'),
                subtitle: Text(cam['on'] == true
                    ? '${cam['viewers']} người đang xem · ${cam['fps']} fps'
                    : 'Camera đang tắt'),
              ),
            ),
          ],
          const SizedBox(height: 16),
          Text('Link công khai (Internet)', style: t.textTheme.titleMedium),
          const SizedBox(height: 8),
          Card(
            child: Padding(
              padding: const EdgeInsets.all(12),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                SelectableText(_url ?? '(tunnel chưa chạy)', style: t.textTheme.bodyMedium?.copyWith(fontFamily: 'monospace')),
                const SizedBox(height: 8),
                Wrap(spacing: 8, children: [
                  OutlinedButton.icon(
                    onPressed: _url == null
                        ? null
                        : () {
                            Clipboard.setData(ClipboardData(text: _url!));
                            toast(context, 'Đã sao chép link');
                          },
                    icon: const Icon(Icons.copy, size: 18),
                    label: const Text('Sao chép'),
                  ),
                  OutlinedButton.icon(
                    onPressed: _newLinkBusy ? null : _newLink,
                    icon: const Icon(Icons.autorenew, size: 18),
                    label: Text(_newLinkBusy ? 'Đang tạo… (~10 giây)' : 'Tạo link mới'),
                  ),
                ]),
                const SizedBox(height: 4),
                Text('App tự nhớ link mới nhất mỗi lần kết nối.', style: t.textTheme.bodySmall),
              ]),
            ),
          ),
        ],
      ),
    );
  }
}
