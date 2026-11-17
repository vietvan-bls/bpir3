import 'dart:async';

import 'package:material_ui/material_ui.dart';

import '../main.dart';
import '../util.dart';

class NetworkScreen extends StatelessWidget {
  const NetworkScreen({super.key});

  @override
  Widget build(BuildContext context) => const DefaultTabController(
        length: 3,
        child: Column(children: [
          TabBar(tabs: [Tab(text: 'Wi-Fi Internet'), Tab(text: 'Mạng LAN'), Tab(text: 'Máy kết nối')]),
          Expanded(child: TabBarView(children: [WifiTab(), LanTab(), ClientsTab()])),
        ]),
      );
}

String bandText(Object? b) => b == '5g' ? '5 GHz' : '2.4 GHz';

// ------------------------------------------------------------------ Wi-Fi
class WifiTab extends StatefulWidget {
  const WifiTab({super.key});

  @override
  State<WifiTab> createState() => _WifiTabState();
}

class _WifiTabState extends State<WifiTab> {
  Map? _st;
  List? _nets;
  bool _scanning = false;
  String? _scanErr;
  Timer? _poll;

  @override
  void initState() {
    super.initState();
    _load().then((s) {
      if (s?['job']?['state'] == 'running') _watch();
    });
    _poll = Timer.periodic(const Duration(seconds: 10), (_) => _load());
  }

  @override
  void dispose() {
    _poll?.cancel();
    super.dispose();
  }

  Future<Map?> _load() async {
    try {
      final s = await ApiScope.read(context).get('/api/wifi/status') as Map;
      if (mounted) setState(() => _st = s);
      return s;
    } catch (_) {
      return null;
    }
  }

  void _watch() {
    _poll?.cancel();
    _poll = Timer.periodic(const Duration(seconds: 2), (_) async {
      final s = await _load(); // null khi Wi-Fi board đang rớt: cứ thử lại
      if (s != null && s['job']?['state'] != 'running') {
        _poll?.cancel();
        _poll = Timer.periodic(const Duration(seconds: 10), (_) => _load());
        if (mounted) toast(context, '${s['job']['state'] == 'ok' ? '✅' : '❌'} ${s['job']['msg']}');
        if (_nets != null) _scan();
      }
    });
  }

  Future<void> _scan() async {
    setState(() {
      _scanning = true;
      _scanErr = null;
    });
    try {
      final l = await ApiScope.read(context).get('/api/wifi/scan', timeout: const Duration(seconds: 40));
      if (mounted) setState(() => _nets = l as List);
    } catch (e) {
      if (mounted) setState(() => _scanErr = '$e');
    } finally {
      if (mounted) setState(() => _scanning = false);
    }
  }

  Future<void> _connect(Map? net) async {
    final ssid = TextEditingController(), key = TextEditingController();
    var band = '2g';
    final open = net != null && net['encryption'] == 'none';
    final ch = net?['channel'] as num?;
    final dfs = net != null && net['band'] == '5g' && ch != null && ch >= 52 && ch <= 144;
    final ok = await showDialog<bool>(
      context: context,
      builder: (c) => StatefulBuilder(
        builder: (c, setD) => AlertDialog(
          title: Text(net?['ssid'] ?? 'Mạng ẩn'),
          content: SingleChildScrollView(
            child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
              if (net != null)
                Text('${bandText(net['band'])} · kênh ${net['channel']} · ${net['enc_text']} · ${net['signal']} dBm')
              else
                const Text('Nhập tên và mật khẩu (để trống nếu mạng mở).'),
              if (dfs)
                Padding(
                  padding: const EdgeInsets.only(top: 8),
                  child: Text(
                      '⚠ Kênh $ch là kênh DFS (radar): Wi-Fi BPI-R3-5G của board sẽ TẮT khi bắt mạng này. Nên chọn bản 2.4 GHz.',
                      style: TextStyle(color: Colors.orange.shade800)),
                )
              else if (net?['band'] == '5g')
                Padding(
                  padding: const EdgeInsets.only(top: 8),
                  child: Text('Wi-Fi BPI-R3-5G sẽ chuyển sang kênh $ch.',
                      style: TextStyle(color: Colors.orange.shade800)),
                ),
              if (net == null) ...[
                const SizedBox(height: 12),
                TextField(controller: ssid, decoration: const InputDecoration(labelText: 'Tên Wi-Fi (SSID)')),
                DropdownButtonFormField<String>(
                  initialValue: band,
                  decoration: const InputDecoration(labelText: 'Băng tần'),
                  items: const [
                    DropdownMenuItem(value: '2g', child: Text('2.4 GHz')),
                    DropdownMenuItem(value: '5g', child: Text('5 GHz')),
                  ],
                  onChanged: (v) => setD(() => band = v!),
                ),
              ],
              if (!open) ...[
                const SizedBox(height: 12),
                TextField(
                    controller: key,
                    obscureText: true,
                    autofocus: net != null,
                    decoration: const InputDecoration(labelText: 'Mật khẩu')),
              ],
            ]),
          ),
          actions: [
            TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Hủy')),
            FilledButton(onPressed: () => Navigator.pop(c, true), child: const Text('Kết nối')),
          ],
        ),
      ),
    );
    if (ok != true || !mounted) return;
    final body = net != null
        ? {'ssid': net['ssid'], 'band': net['band'], 'encryption': net['encryption'], 'key': key.text}
        : {'ssid': ssid.text.trim(), 'band': band, 'key': key.text};
    if ((body['ssid'] as String).isEmpty) return toast(context, 'Nhập tên Wi-Fi');
    try {
      await ApiScope.read(context).post('/api/wifi/connect', body);
      setState(() => _st = {
            'ssid': body['ssid'],
            'job': {'state': 'running', 'msg': "Đang kết nối '${body['ssid']}'… (tối đa ~1 phút)"}
          });
      _watch();
    } catch (e) {
      if (mounted) toast(context, 'Lỗi: $e');
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = _st;
    return RefreshIndicator(
      onRefresh: () async => _load(),
      child: ListView(padding: const EdgeInsets.all(16), children: [
        Text('Board đang bắt mạng nào để lấy Internet', style: Theme.of(context).textTheme.titleMedium),
        const SizedBox(height: 8),
        Card(
          child: s == null
              ? const ListTile(title: Text('…'))
              : ListTile(
                  leading: Icon(Icons.circle, size: 14, color: s['connected'] == true && s['ip'] != null ? Colors.green : Colors.grey),
                  title: Text('${s['ssid'] ?? '(chưa cấu hình)'}'),
                  subtitle: Text(s['connected'] == true && s['ip'] != null
                      ? '${bandText(s['band'])} · kênh ${s['channel']} · ${s['signal']} dBm · ${s['bitrate_mbps']} Mbps · IP ${s['ip']}'
                      : 'chưa có kết nối Internet'),
                  trailing: s['connected'] == true ? SignalBars(s['signal'] as num?) : null,
                ),
        ),
        JobBanner(s?['job'] as Map?),
        const SizedBox(height: 12),
        Row(children: [
          FilledButton.icon(
            onPressed: _scanning ? null : _scan,
            icon: const Icon(Icons.wifi_find),
            label: Text(_scanning ? 'Đang quét…' : _nets == null ? 'Quét Wi-Fi' : 'Quét lại'),
          ),
          const SizedBox(width: 8),
          OutlinedButton(onPressed: () => _connect(null), child: const Text('Mạng ẩn…')),
        ]),
        const SizedBox(height: 8),
        if (_scanning) const Text('Đang quét cả 2.4 GHz và 5 GHz (khoảng 5–10 giây)…'),
        if (_scanErr != null) Text('Lỗi quét: $_scanErr'),
        if (_nets != null && _nets!.isEmpty) const Text('Không thấy mạng nào.'),
        for (final n in _nets ?? const [])
          Card(
            margin: const EdgeInsets.only(top: 6),
            child: ListTile(
              enabled: n['supported'] != false,
              leading: SignalBars(n['signal'] as num?),
              title: Row(children: [
                Flexible(child: Text('${n['ssid']}', overflow: TextOverflow.ellipsis)),
                if (n['current'] == true) ...[
                  const SizedBox(width: 6),
                  const Chip(label: Text('đang dùng'), visualDensity: VisualDensity.compact),
                ],
              ]),
              subtitle: Text(
                  '${n['encryption'] == 'none' ? '🔓' : '🔒'} ${n['enc_text']} · ${bandText(n['band'])} · ${n['signal']} dBm'),
              onTap: () => _connect(n as Map),
            ),
          ),
        const SizedBox(height: 12),
        Text(
            'Nếu sai mật khẩu, board tự quay về mạng cũ. Khi đổi mạng, Wi-Fi BPI-R3 sẽ rớt vài giây.',
            style: Theme.of(context).textTheme.bodySmall),
      ]),
    );
  }
}

// ------------------------------------------------------------------ LAN
class LanTab extends StatefulWidget {
  const LanTab({super.key});

  @override
  State<LanTab> createState() => _LanTabState();
}

class _LanTabState extends State<LanTab> {
  Map? _c;
  Object? _err;
  final _ip = TextEditingController(), _start = TextEditingController(), _limit = TextEditingController();
  int _prefix = 24;
  String? _progress;
  bool _failed = false, _busy = false;

  static const _prefixes = {
    24: '/24 — 255.255.255.0 (254 máy)',
    23: '/23 — 255.255.254.0 (510 máy)',
    22: '/22 — 255.255.252.0 (1022 máy)',
    20: '/20 — 255.255.240.0 (4094 máy)',
    16: '/16 — 255.255.0.0 (65534 máy)',
    25: '/25 — 255.255.255.128 (126 máy)',
    26: '/26 — 255.255.255.192 (62 máy)',
  };

  @override
  void initState() {
    super.initState();
    _load();
    for (final c in [_ip, _start, _limit]) {
      c.addListener(() => setState(() {}));
    }
  }

  Future<void> _load() async {
    try {
      final c = await ApiScope.read(context).get('/api/lan') as Map;
      if (!mounted) return;
      setState(() {
        _c = c;
        _err = null;
        if (_ip.text.isEmpty) {
          _ip.text = '${c['ip']}';
          _prefix = (c['prefix'] as num).toInt();
          _start.text = '${c['dhcp_start']}';
          _limit.text = '${c['dhcp_limit']}';
        }
      });
    } catch (e) {
      if (mounted) setState(() => _err = e);
    }
  }

  static bool _validIp(String s) =>
      RegExp(r'^(\d{1,3}\.){3}\d{1,3}$').hasMatch(s) && s.split('.').every((o) => int.parse(o) <= 255);
  static int _ip2n(String s) => s.split('.').fold(0, (a, o) => a * 256 + int.parse(o));
  static String _n2ip(int n) => [24, 16, 8, 0].map((s) => (n >> s) & 255).join('.');

  String _preview() {
    final ip = _ip.text.trim();
    if (!_validIp(ip)) return 'IP không hợp lệ';
    final st = int.tryParse(_start.text) ?? 0, lim = int.tryParse(_limit.text) ?? 0;
    final size = 1 << (32 - _prefix), net = _ip2n(ip) ~/ size * size;
    final ok = st >= 1 && lim >= 1 && st + lim < size - 1;
    return 'Mạng ${_n2ip(net)}/$_prefix · board ở $ip · ' +
        (ok ? 'cấp IP từ ${_n2ip(net + st)} đến ${_n2ip(net + st + lim - 1)}' : 'dải DHCP vượt quá mạng');
  }

  Future<void> _apply() async {
    final api = ApiScope.read(context);
    final body = {
      'ip': _ip.text.trim(),
      'prefix': _prefix,
      'dhcp_start': int.tryParse(_start.text) ?? 0,
      'dhcp_limit': int.tryParse(_limit.text) ?? 0,
    };
    if (!_validIp(body['ip'] as String)) return toast(context, 'IP không hợp lệ');
    if (!await confirm(
        context,
        'Đổi IP board?',
        'Đổi sang ${body['ip']}/$_prefix.\n\nMạng sẽ rớt vài giây. Nếu trong 3 phút không vào được địa chỉ mới, board tự quay về ${_c!['ip']}.')) {
      return;
    }
    Map r;
    try {
      r = await api.post('/api/lan', body) as Map;
    } catch (e) {
      if (mounted) toast(context, 'Lỗi: $e');
      return;
    }
    final newUrl = 'http://${r['new_ip']}:8080';
    final deadline = DateTime.now().add(Duration(seconds: (r['wait_s'] as num).toInt()));
    setState(() {
      _busy = true;
      _failed = false;
    });
    await Future.delayed(const Duration(seconds: 4));
    while (mounted) {
      final left = deadline.difference(DateTime.now()).inSeconds;
      if (left <= 0) {
        setState(() {
          _failed = true;
          _busy = false;
          _progress = 'Không vào được ${r['new_ip']}, board đã quay về ${_c!['ip']}. Tắt/bật Wi-Fi điện thoại rồi thử lại.';
        });
        return;
      }
      setState(() => _progress =
          'Đang chuyển sang ${r['new_ip']}… còn ${left}s. Nếu lâu quá, hãy tắt/bật Wi-Fi điện thoại để nhận IP mới.');
      if (await api.ping('$newUrl/api/lan/confirm?token=${r['token']}')) {
        await api.saveUrls(lan: newUrl);
        await api.connect();
        if (!mounted) return;
        setState(() {
          _busy = false;
          _progress = '✅ Đã đổi xong, app đang dùng $newUrl';
          _ip.clear();
        });
        _load();
        return;
      }
      await Future.delayed(const Duration(seconds: 2));
    }
  }

  @override
  Widget build(BuildContext context) {
    final api = ApiScope.of(context);
    final c = _c;
    if (c == null) return _err != null ? ErrorText(_err!, onRetry: _load) : const Center(child: CircularProgressIndicator());
    final viaLan = Uri.parse(api.base).host == c['ip'];
    return ListView(padding: const EdgeInsets.all(16), children: [
      Card(
        child: ListTile(
          leading: const Icon(Icons.lan),
          title: Text('${c['ip']}/${c['prefix']}'),
          subtitle: Text('mạng ${c['network']} · DHCP ${c['dhcp_from']} – ${c['dhcp_to']}'),
        ),
      ),
      const SizedBox(height: 16),
      TextField(controller: _ip, keyboardType: TextInputType.number, decoration: const InputDecoration(labelText: 'IP của board', border: OutlineInputBorder())),
      const SizedBox(height: 12),
      DropdownButtonFormField<int>(
        initialValue: _prefixes.containsKey(_prefix) ? _prefix : 24,
        isExpanded: true,
        decoration: const InputDecoration(labelText: 'Dải mạng (subnet)', border: OutlineInputBorder()),
        items: [for (final e in _prefixes.entries) DropdownMenuItem(value: e.key, child: Text(e.value))],
        onChanged: (v) => setState(() => _prefix = v!),
      ),
      const SizedBox(height: 12),
      Row(children: [
        Expanded(child: TextField(controller: _start, keyboardType: TextInputType.number, decoration: const InputDecoration(labelText: 'DHCP bắt đầu từ', border: OutlineInputBorder()))),
        const SizedBox(width: 12),
        Expanded(child: TextField(controller: _limit, keyboardType: TextInputType.number, decoration: const InputDecoration(labelText: 'Số máy tối đa', border: OutlineInputBorder()))),
      ]),
      const SizedBox(height: 8),
      Text(_preview(), style: Theme.of(context).textTheme.bodySmall),
      const SizedBox(height: 12),
      FilledButton(
        onPressed: !viaLan || _busy || c['job']?['state'] == 'running' ? null : _apply,
        child: const Text('Áp dụng'),
      ),
      if (!viaLan)
        Padding(
          padding: const EdgeInsets.only(top: 8),
          child: Text('Muốn đổi, hãy bắt Wi-Fi BPI-R3 rồi kết nối app bằng http://${c['ip']}:8080',
              style: Theme.of(context).textTheme.bodySmall),
        ),
      if (_progress != null) JobBanner({'state': _busy ? 'running' : _failed ? 'failed' : 'ok', 'msg': _progress}),
    ]);
  }
}

// ------------------------------------------------------------------ Máy kết nối
class ClientsTab extends StatefulWidget {
  const ClientsTab({super.key});

  @override
  State<ClientsTab> createState() => _ClientsTabState();
}

class _ClientsTabState extends State<ClientsTab> {
  List? _list;
  Object? _err;
  Timer? _t;

  @override
  void initState() {
    super.initState();
    _load();
    _t = Timer.periodic(const Duration(seconds: 10), (_) => _load());
  }

  @override
  void dispose() {
    _t?.cancel();
    super.dispose();
  }

  Future<void> _load() async {
    try {
      final l = await ApiScope.read(context).get('/api/clients') as List;
      if (mounted) setState(() {
        _list = l;
        _err = null;
      });
    } catch (e) {
      if (mounted) setState(() => _err = e);
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_list == null) return _err != null ? ErrorText(_err!, onRetry: _load) : const Center(child: CircularProgressIndicator());
    return RefreshIndicator(
      onRefresh: _load,
      child: ListView(padding: const EdgeInsets.all(16), children: [
        if (_list!.isEmpty) const Text('Chưa có máy nào bắt Wi-Fi của board.'),
        for (final c in _list!)
          Card(
            margin: const EdgeInsets.only(bottom: 8),
            child: ListTile(
              leading: SignalBars(c['signal'] as num?),
              title: Text((c['name'] as String?)?.isNotEmpty == true ? c['name'] : '(không tên)'),
              subtitle: Text('${c['ip'] ?? ''} · ${c['band'] ?? ''} · ${c['signal'] ?? '?'} dBm\n${c['mac']}'),
              isThreeLine: true,
              trailing: Text(fmtDur(c['connected_s'] as num?)),
            ),
          ),
      ]),
    );
  }
}
