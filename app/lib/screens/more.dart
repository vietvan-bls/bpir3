import 'dart:async';

import 'package:material_ui/material_ui.dart';

import '../main.dart';
import '../util.dart';

class MoreScreen extends StatelessWidget {
  const MoreScreen({super.key});

  @override
  Widget build(BuildContext context) {
    void open(String title, Widget page) => Navigator.push(
        context, MaterialPageRoute(builder: (_) => Scaffold(appBar: AppBar(title: Text(title)), body: page)));
    return ListView(children: [
      ListTile(leading: const Icon(Icons.public), title: const Text('Truy cập web'), subtitle: const Text('Máy nào vào trang nào'),
          onTap: () => open('Truy cập web', const TrafficScreen())),
      ListTile(leading: const Icon(Icons.lightbulb_outline), title: const Text('Điều khiển LED'),
          onTap: () => open('Điều khiển LED', const LedScreen())),
      ListTile(leading: const Icon(Icons.article_outlined), title: const Text('Log'),
          onTap: () => open('Log', const LogScreen())),
      ListTile(leading: const Icon(Icons.settings_outlined), title: const Text('Hệ thống'), subtitle: const Text('Mật khẩu, khởi động lại, đăng xuất'),
          onTap: () => open('Hệ thống', const SystemScreen())),
    ]);
  }
}

// ------------------------------------------------------------------ Truy cập web
const _cat = {
  'video': '🎬 Video', 'mxh': '👥 MXH', 'chat': '💬 Chat', 'mua': '🛒 Mua sắm', 'nhac': '🎵 Nhạc',
  'ai': '🤖 AI', 'game': '🎮 Game', 'web': '🌐 Web', 'nen': '⚙️ Nền', 'dns': '🔒 DNS riêng',
};
const _dohWarn = 'Máy này có dấu hiệu dùng DNS mã hóa riêng (DoH/DoT), nhiều trang có thể không được ghi';

class TrafficScreen extends StatefulWidget {
  const TrafficScreen({super.key});

  @override
  State<TrafficScreen> createState() => _TrafficScreenState();
}

class _TrafficScreenState extends State<TrafficScreen> {
  Map? _d;
  Object? _err;
  bool _hideBg = true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load([String? day]) async {
    try {
      final d = await ApiScope.read(context).get('/api/traffic${day != null ? '?day=$day' : ''}') as Map;
      if (mounted) setState(() {
        _d = d;
        _err = null;
      });
    } catch (e) {
      if (mounted) setState(() => _err = e);
    }
  }

  @override
  Widget build(BuildContext context) {
    final d = _d;
    if (d == null) return _err != null ? ErrorText(_err!, onRetry: _load) : const Center(child: CircularProgressIndicator());
    final devs = (d['devices'] as List).cast<Map>();
    final bytes = (d['bytes'] as Map?) ?? {};
    return RefreshIndicator(
      onRefresh: () => _load(d['day']),
      child: ListView(padding: const EdgeInsets.all(16), children: [
        Row(children: [
          DropdownButton<String>(
            value: '${d['day']}',
            items: [
              for (final x in (d['days'] as List))
                DropdownMenuItem(value: '$x', child: Text(x == d['today'] ? 'Hôm nay' : '$x')),
            ],
            onChanged: (v) => _load(v),
          ),
          const Spacer(),
          const Text('Ẩn dịch vụ nền'),
          Switch(value: _hideBg, onChanged: (v) => setState(() => _hideBg = v)),
        ]),
        if (devs.isEmpty) const Text('Chưa có dữ liệu. Dùng thử một máy bắt Wi-Fi của board rồi kéo xuống để làm mới.'),
        for (final dev in devs)
          Card(
            margin: const EdgeInsets.only(top: 8),
            child: ListTile(
              title: Text('${dev['name'] ?? dev['ip'] ?? dev['mac']}'
                  '${(dev['sites'] as List).any((s) => s['c'] == 'dns') ? ' ⚠️' : ''}'),
              subtitle: Text([
                '${dev['ip'] ?? ''} · ${fmtMin(dev['minutes'] as num)}',
                if (bytes[dev['mac']] != null) '↓${fmtBytes(bytes[dev['mac']]['rx'])} ↑${fmtBytes(bytes[dev['mac']]['tx'])}',
                _sites(dev).take(4).map((s) => s['site']).join(', '),
              ].join('\n')),
              isThreeLine: true,
              trailing: const Icon(Icons.chevron_right),
              onTap: () => Navigator.push(
                  context,
                  MaterialPageRoute(
                      builder: (_) => _DeviceTraffic(dev: dev, bytes: bytes[dev['mac']] as Map?, live: d['day'] == d['today'], hideBg: _hideBg))),
            ),
          ),
      ]),
    );
  }

  List<Map> _sites(Map dev) =>
      (dev['sites'] as List).cast<Map>().where((s) => !_hideBg || s['c'] != 'nen').toList();
}

class _DeviceTraffic extends StatefulWidget {
  final Map dev;
  final Map? bytes;
  final bool live, hideBg;
  const _DeviceTraffic({required this.dev, required this.bytes, required this.live, required this.hideBg});

  @override
  State<_DeviceTraffic> createState() => _DeviceTrafficState();
}

class _DeviceTrafficState extends State<_DeviceTraffic> {
  List? _recent;
  Timer? _t;

  @override
  void initState() {
    super.initState();
    if (widget.live) {
      _loadRecent();
      _t = Timer.periodic(const Duration(seconds: 5), (_) => _loadRecent());
    }
  }

  @override
  void dispose() {
    _t?.cancel();
    super.dispose();
  }

  Future<void> _loadRecent() async {
    try {
      final r = await ApiScope.read(context)
          .get('/api/traffic/recent?mac=${Uri.encodeQueryComponent('${widget.dev['mac']}')}') as List;
      if (mounted) setState(() => _recent = r.where((e) => !widget.hideBg || e['c'] != 'nen').toList());
    } catch (_) {}
  }

  @override
  Widget build(BuildContext context) {
    final d = widget.dev;
    final t = Theme.of(context);
    final hours = (d['hours'] as List).cast<num>();
    final max = hours.fold<num>(1, (a, b) => b > a ? b : a);
    final sites = (d['sites'] as List).cast<Map>().where((s) => !widget.hideBg || s['c'] != 'nen');
    final b = widget.bytes;
    return Scaffold(
      appBar: AppBar(title: Text('${d['name'] ?? d['ip'] ?? d['mac']}')),
      body: ListView(padding: const EdgeInsets.all(16), children: [
        Text('${fmtMin(d['minutes'] as num)} · ${d['site_count']} trang'
            '${b != null ? ' · ↓${fmtBytes(b['rx'])} ↑${fmtBytes(b['tx'])}' : ''}'),
        if ((d['sites'] as List).any((s) => s['c'] == 'dns'))
          Padding(padding: const EdgeInsets.only(top: 4), child: Text('⚠️ $_dohWarn', style: t.textTheme.bodySmall)),
        const SizedBox(height: 12),
        Text('Theo giờ (phút)', style: t.textTheme.titleSmall),
        const SizedBox(height: 6),
        SizedBox(
          height: 80,
          child: Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
            for (var h = 0; h < hours.length; h++)
              Expanded(
                child: Tooltip(
                  message: '${h}h: ${hours[h]} phút',
                  child: Container(
                    margin: const EdgeInsets.symmetric(horizontal: 1),
                    height: (hours[h] / max * 78).clamp(2, 78).toDouble(),
                    color: hours[h] > 0 ? t.colorScheme.primary : t.colorScheme.outlineVariant,
                  ),
                ),
              ),
          ]),
        ),
        Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
          for (final h in ['0h', '6h', '12h', '18h', '23h']) Text(h, style: t.textTheme.labelSmall),
        ]),
        const SizedBox(height: 16),
        Text('Trang đã vào', style: t.textTheme.titleSmall),
        for (final s in sites)
          ListTile(
            contentPadding: EdgeInsets.zero,
            dense: true,
            title: Text('${s['site']}'),
            subtitle: Text('${_cat[s['c']] ?? s['c']} · ${(s['x'] as List).join(', ')}', maxLines: 2, overflow: TextOverflow.ellipsis),
            trailing: Text('${s['m']} phút\n${fmtClock(s['l'] as num)}', textAlign: TextAlign.right),
          ),
        const SizedBox(height: 16),
        Text(widget.live ? 'Gần đây (tự cập nhật mỗi 5 giây)' : 'Gần đây (chỉ có cho hôm nay)', style: t.textTheme.titleSmall),
        if (widget.live && (_recent?.isEmpty ?? false)) const Text('Chưa có (chỉ ghi từ lúc server chạy)'),
        for (final e in (_recent ?? const []).take(60))
          ListTile(
            contentPadding: EdgeInsets.zero,
            dense: true,
            leading: Text(fmtClock(e['t'] as num)),
            title: Text('${e['site']}'),
            subtitle: Text('${e['host']}'),
          ),
      ]),
    );
  }
}

// ------------------------------------------------------------------ LED
class LedScreen extends StatefulWidget {
  const LedScreen({super.key});

  @override
  State<LedScreen> createState() => _LedScreenState();
}

class _LedScreenState extends State<LedScreen> {
  String? _mode;

  @override
  void initState() {
    super.initState();
    ApiScope.read(context).get('/api/status').then((s) {
      if (mounted) setState(() => _mode = '${s['led']}');
    }).catchError((_) {});
  }

  Future<void> _set(String m) async {
    try {
      final r = await ApiScope.read(context).post('/api/led', {'mode': m});
      if (mounted) setState(() => _mode = '${r['led']}');
    } catch (e) {
      if (mounted) toast(context, 'Lỗi: $e');
    }
  }

  @override
  Widget build(BuildContext context) {
    final on = _mode != null && _mode != 'off';
    return ListView(padding: const EdgeInsets.all(24), children: [
      Icon(on ? Icons.lightbulb : Icons.lightbulb_outline, size: 72, color: on ? Colors.amber : Colors.grey),
      const SizedBox(height: 8),
      Text('Chế độ hiện tại: ${_mode ?? '…'}', textAlign: TextAlign.center),
      const SizedBox(height: 24),
      Wrap(spacing: 8, runSpacing: 8, alignment: WrapAlignment.center, children: [
        for (final (m, label) in [('on', 'Bật'), ('off', 'Tắt'), ('blink', 'Nhấp nháy'), ('heartbeat', 'Nhịp tim')])
          ChoiceChip(label: Text(label), selected: _mode == m, onSelected: (_) => _set(m)),
      ]),
    ]);
  }
}

// ------------------------------------------------------------------ Log
class LogScreen extends StatefulWidget {
  const LogScreen({super.key});

  @override
  State<LogScreen> createState() => _LogScreenState();
}

class _LogScreenState extends State<LogScreen> {
  String _src = 'server';
  String? _log;
  final _scroll = ScrollController();

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load([String? src]) async {
    if (src != null) setState(() => _src = src);
    try {
      final l = (await ApiScope.read(context).get('/api/log?src=$_src'))['log'];
      if (!mounted) return;
      setState(() => _log = (l is String && l.isNotEmpty) ? l : '(trống)');
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (_scroll.hasClients) _scroll.jumpTo(_scroll.position.maxScrollExtent);
      });
    } catch (e) {
      if (mounted) setState(() => _log = 'Lỗi: $e');
    }
  }

  @override
  Widget build(BuildContext context) => Column(children: [
        Padding(
          padding: const EdgeInsets.all(12),
          child: Row(children: [
            Expanded(
              child: SegmentedButton<String>(
                segments: const [
                  ButtonSegment(value: 'server', label: Text('Server')),
                  ButtonSegment(value: 'tunnel', label: Text('Tunnel')),
                  ButtonSegment(value: 'system', label: Text('Hệ thống')),
                ],
                selected: {_src},
                onSelectionChanged: (s) => _load(s.first),
              ),
            ),
            IconButton(icon: const Icon(Icons.refresh), onPressed: _load),
          ]),
        ),
        Expanded(
          child: Container(
            width: double.infinity,
            color: const Color(0xFF0F172A),
            child: SingleChildScrollView(
              controller: _scroll,
              padding: const EdgeInsets.all(12),
              child: SelectableText(_log ?? '…',
                  style: const TextStyle(color: Color(0xFFE2E8F0), fontFamily: 'monospace', fontSize: 12)),
            ),
          ),
        ),
      ]);
}

// ------------------------------------------------------------------ Hệ thống
class SystemScreen extends StatefulWidget {
  const SystemScreen({super.key});

  @override
  State<SystemScreen> createState() => _SystemScreenState();
}

class _SystemScreenState extends State<SystemScreen> {
  final _cur = TextEditingController(), _new = TextEditingController(), _new2 = TextEditingController();

  Future<void> _savePw() async {
    final api = ApiScope.read(context);
    if (_new.text.length < 8) return toast(context, 'Mật khẩu mới phải có ít nhất 8 ký tự');
    if (_new.text != _new2.text) return toast(context, 'Hai lần nhập mật khẩu mới không khớp');
    try {
      await api.post('/api/password', {'new': _new.text, 'current': _cur.text});
      for (final c in [_cur, _new, _new2]) {
        c.clear();
      }
      api.who = {...api.who, 'password_set': true};
      if (mounted) {
        setState(() {});
        toast(context, 'Đã lưu mật khẩu');
      }
    } catch (e) {
      if (mounted) toast(context, 'Lỗi: $e');
    }
  }

  Future<void> _restart() async {
    try {
      final r = await ApiScope.read(context).post('/api/restart', {});
      if (mounted) toast(context, '${r['msg'] ?? 'Đang khởi động lại server'}');
    } catch (e) {
      if (mounted) toast(context, 'Lỗi: $e');
    }
  }

  Future<void> _reboot() async {
    if (!await confirm(context, 'Khởi động lại board?', 'Wi-Fi và link công khai sẽ mất khoảng 1 phút. Link công khai sẽ đổi.',
        ok: 'Khởi động lại', danger: true)) {
      return;
    }
    if (!mounted) return;
    try {
      final r = await ApiScope.read(context).post('/api/reboot', {});
      if (mounted) toast(context, '${r['msg'] ?? 'Đang khởi động lại board'}');
    } catch (e) {
      if (mounted) toast(context, 'Lỗi: $e');
    }
  }

  @override
  Widget build(BuildContext context) {
    final api = ApiScope.of(context);
    final t = Theme.of(context);
    final needCur = !api.isLocal && api.who['password_set'] == true;
    return ListView(padding: const EdgeInsets.all(16), children: [
      Text('Mật khẩu truy cập từ xa', style: t.textTheme.titleMedium),
      const SizedBox(height: 4),
      Text(api.who['password_set'] == true
          ? '✅ Đã đặt mật khẩu.'
          : '⚠️ Chưa đặt mật khẩu: chưa ai vào được qua link công khai.'),
      const SizedBox(height: 12),
      if (needCur) ...[
        TextField(controller: _cur, obscureText: true, decoration: const InputDecoration(labelText: 'Mật khẩu hiện tại', border: OutlineInputBorder())),
        const SizedBox(height: 10),
      ],
      TextField(controller: _new, obscureText: true, decoration: const InputDecoration(labelText: 'Mật khẩu mới (ít nhất 8 ký tự)', border: OutlineInputBorder())),
      const SizedBox(height: 10),
      TextField(controller: _new2, obscureText: true, decoration: const InputDecoration(labelText: 'Nhập lại mật khẩu mới', border: OutlineInputBorder())),
      const SizedBox(height: 10),
      FilledButton(onPressed: _savePw, child: const Text('Lưu mật khẩu')),
      Text('Đổi mật khẩu sẽ đăng xuất mọi thiết bị đang đăng nhập từ xa. Sai 5 lần liên tiếp sẽ bị khóa 5 phút.',
          style: t.textTheme.bodySmall),
      const Divider(height: 32),
      Text('Khởi động lại', style: t.textTheme.titleMedium),
      const SizedBox(height: 8),
      Wrap(spacing: 8, runSpacing: 8, children: [
        OutlinedButton(onPressed: _restart, child: const Text('Khởi động lại server')),
        FilledButton(
            style: FilledButton.styleFrom(backgroundColor: Colors.red.shade700),
            onPressed: _reboot,
            child: const Text('Khởi động lại board')),
      ]),
      const Divider(height: 32),
      Text('Kết nối', style: t.textTheme.titleMedium),
      ListTile(contentPadding: EdgeInsets.zero, title: const Text('Đang dùng'), subtitle: Text(api.base)),
      Wrap(spacing: 8, children: [
        OutlinedButton.icon(
          icon: const Icon(Icons.edit),
          label: const Text('Đổi địa chỉ'),
          onPressed: () {
            Navigator.popUntil(context, (r) => r.isFirst);
            api.disconnect();
          },
        ),
        if (api.who['authed'] == true && !api.isLocal)
          OutlinedButton.icon(
            icon: const Icon(Icons.logout),
            label: const Text('Đăng xuất'),
            onPressed: () {
              Navigator.popUntil(context, (r) => r.isFirst);
              api.logout();
            },
          ),
      ]),
    ]);
  }
}
