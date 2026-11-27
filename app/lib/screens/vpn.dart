import 'dart:async';
import 'dart:convert';

import 'package:file_picker/file_picker.dart';
import 'package:material_ui/material_ui.dart';

import '../api.dart';
import '../main.dart';
import '../util.dart';

/// VPN cho WiFi BPI-R3 (server/vpn.py): máy bắt WiFi của board ra Internet qua VPN nước khác.
String flagOf(String? cc) => cc == null || cc.length != 2
    ? '🌍'
    : String.fromCharCodes(cc.toUpperCase().codeUnits.map((c) => 0x1F1A5 + c));

class VpnScreen extends StatefulWidget {
  const VpnScreen({super.key});

  @override
  State<VpnScreen> createState() => _VpnScreenState();
}

class _VpnScreenState extends State<VpnScreen> {
  Map? _st;
  List? _countries;
  String? _cc;
  Object? _err, _vgErr;
  bool _busy = false;
  Timer? _poll;

  Api get api => ApiScope.read(context);

  @override
  void initState() {
    super.initState();
    _load();
    _loadVpnGate();
  }

  @override
  void dispose() {
    _poll?.cancel();
    super.dispose();
  }

  Future<void> _load({bool check = false}) async {
    try {
      final s = await api.get('/api/vpn/status${check ? '?check=1' : ''}', timeout: const Duration(seconds: 30)) as Map;
      if (mounted) {
        setState(() {
          _st = s;
          _err = null;
        });
      }
    } catch (e) {
      if (mounted) setState(() => _err = e);
    }
  }

  /// Sau khi bật / đổi VPN: hỏi trạng thái vài lần cho tới khi kết nối xong.
  void _watch() {
    _poll?.cancel();
    var n = 0;
    _poll = Timer.periodic(const Duration(seconds: 4), (t) async {
      await _load(check: true);
      if (++n > 10 || (_st?['connected'] == true && _st?['exit']?['query'] != null)) t.cancel();
    });
  }

  Future<void> _loadVpnGate() async {
    try {
      final l = await api.get('/api/vpn/vpngate', timeout: const Duration(seconds: 60)) as List;
      if (mounted) {
        setState(() {
          _countries = l;
          _vgErr = null;
          _cc ??= l.isNotEmpty ? '${l.first['cc']}' : null;
        });
      }
    } catch (e) {
      if (mounted) setState(() => _vgErr = e);
    }
  }

  Future<void> _toggle() async {
    final on = _st?['enabled'] != true;
    setState(() => _busy = true);
    try {
      final s = await api.post('/api/vpn/enable', {'on': on}) as Map;
      if (mounted) {
        setState(() => _st = s);
        toast(context, on ? 'Đang bật VPN…' : 'Đã tắt VPN');
      }
      if (on) _watch();
    } catch (e) {
      if (mounted) toast(context, 'Lỗi: $e');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _useVpnGate(String cc, [String host = '']) async {
    setState(() => _busy = true);
    try {
      final s = await api.post('/api/vpn/vpngate', {'cc': cc, 'host': host}, timeout: const Duration(seconds: 90)) as Map;
      if (mounted) {
        setState(() => _st = s);
        toast(context, 'Đang kết nối ${s['name']}…');
      }
      _watch();
    } catch (e) {
      if (mounted) toast(context, 'Lỗi: $e');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _upload() async {
    final files = await FilePicker.pickFiles(type: FileType.any);
    if (files.isEmpty || !mounted) return;
    final f = files.first;
    final user = TextEditingController(), pass = TextEditingController();
    final isOvpn = f.name.toLowerCase().endsWith('.ovpn');
    if (isOvpn) {
      final ok = await showDialog<bool>(
        context: context,
        builder: (c) => AlertDialog(
          title: Text(f.name),
          content: Column(mainAxisSize: MainAxisSize.min, children: [
            const Text('File OpenVPN thường cần tài khoản riêng cho router (để trống nếu không cần).'),
            TextField(controller: user, decoration: const InputDecoration(labelText: 'Tên đăng nhập VPN')),
            TextField(controller: pass, obscureText: true, decoration: const InputDecoration(labelText: 'Mật khẩu VPN')),
          ]),
          actions: [
            TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Hủy')),
            FilledButton(onPressed: () => Navigator.pop(c, true), child: const Text('Tải lên')),
          ],
        ),
      );
      if (ok != true || !mounted) return;
    }
    setState(() => _busy = true);
    try {
      final bytes = await f.xFile.readAsBytes();
      String b64(String v) => base64.encode(utf8.encode(v));
      final s = await api.uploadBytes('/api/vpn/upload?name=${Uri.encodeQueryComponent(f.name)}', bytes, headers: {
        if (user.text.isNotEmpty) 'X-VPN-User': b64(user.text),
        if (user.text.isNotEmpty) 'X-VPN-Pass': b64(pass.text),
      }) as Map;
      if (mounted) {
        setState(() => _st = s);
        toast(context, 'Đã tải lên, đang kết nối…');
      }
      _watch();
    } catch (e) {
      if (mounted) toast(context, 'Lỗi: $e');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Widget _statusCard() {
    final t = Theme.of(context);
    final s = _st;
    if (s == null) {
      return Card(child: Padding(padding: const EdgeInsets.all(16), child: _err != null ? Text('Lỗi: $_err') : const LinearProgressIndicator()));
    }
    final ex = (s['exit'] as Map?) ?? {};
    final enabled = s['enabled'] == true, connected = s['connected'] == true;
    final (icon, color, title, sub) = s['kind'] == null
        ? (Icons.vpn_lock_outlined, t.colorScheme.outline, 'Chưa chọn VPN', 'Chọn nước VPN Gate hoặc tải file cấu hình bên dưới')
        : !enabled
            ? (Icons.vpn_key_off_outlined, t.colorScheme.outline, 'VPN đang tắt', '${s['name']}')
            : connected
                ? (Icons.vpn_lock, Colors.green, '${flagOf(ex['countryCode'] as String?)} ${ex['country'] ?? s['country'] ?? 'Đã kết nối'}',
                    'IP ${ex['query'] ?? '…'}${ex['city'] != null ? ' · ${ex['city']}' : ''} · ${s['name']}\n'
                        '↓${fmtBytes(s['rx'] as num?)} ↑${fmtBytes(s['tx'] as num?)}')
                : (Icons.sync, Colors.orange, 'Đang kết nối…', '${s['name']}\nMáy trong WiFi tạm không ra Internet (kill-switch)');
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          ListTile(
            contentPadding: EdgeInsets.zero,
            leading: Icon(icon, color: color, size: 36),
            title: Text(title, style: t.textTheme.titleLarge),
            subtitle: Text(sub),
          ),
          Row(children: [
            Expanded(
              child: FilledButton.icon(
                style: enabled ? FilledButton.styleFrom(backgroundColor: Colors.red.shade700) : null,
                onPressed: _busy || s['kind'] == null ? null : _toggle,
                icon: Icon(enabled ? Icons.power_settings_new : Icons.vpn_lock),
                label: Text(enabled ? 'Tắt VPN' : 'Bật VPN'),
              ),
            ),
            const SizedBox(width: 8),
            OutlinedButton.icon(
                onPressed: () => _load(check: true), icon: const Icon(Icons.refresh), label: const Text('Kiểm tra IP')),
          ]),
          if (enabled && !connected && '${s['log'] ?? ''}'.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: Text('${s['log']}'.split('\n').where((l) => l.trim().isNotEmpty).toList().reversed.take(4).toList().reversed.join('\n'),
                  style: t.textTheme.bodySmall?.copyWith(fontFamily: 'monospace')),
            ),
        ]),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context);
    final countries = (_countries ?? const []).cast<Map>();
    final cur = countries.where((c) => '${c['cc']}' == _cc).firstOrNull;
    return RefreshIndicator(
      onRefresh: () => Future.wait([_load(check: true), _loadVpnGate()]),
      child: ListView(padding: const EdgeInsets.all(16), children: [
        _statusCard(),
        const SizedBox(height: 6),
        Text('Bật: mọi máy bắt WiFi BPI-R3 ra Internet qua VPN (Google… thấy IP nước đó). Board, Tailscale, MQTT vẫn đi '
            'mạng thường. VPN rớt thì máy trong WiFi mất Internet (không lộ IP thật). Tắt khi cần vào trang Việt Nam.',
            style: t.textTheme.bodySmall),
        const SizedBox(height: 16),
        Text('VPN Gate (miễn phí, không cần tài khoản)', style: t.textTheme.titleMedium),
        const SizedBox(height: 8),
        if (_vgErr != null) Text('Không tải được danh sách: $_vgErr'),
        if (_countries == null && _vgErr == null) const LinearProgressIndicator(),
        if (countries.isNotEmpty) ...[
          DropdownButtonFormField<String>(
            initialValue: _cc,
            isExpanded: true,
            decoration: const InputDecoration(labelText: 'Nước', border: OutlineInputBorder(), isDense: true),
            items: [
              for (final c in countries)
                DropdownMenuItem(value: '${c['cc']}', child: Text('${flagOf('${c['cc']}')} ${c['country']} (${c['count']} máy chủ)')),
            ],
            onChanged: (v) => setState(() => _cc = v),
          ),
          const SizedBox(height: 8),
          FilledButton.tonalIcon(
            onPressed: _busy || _cc == null ? null : () => _useVpnGate(_cc!),
            icon: const Icon(Icons.flight_takeoff),
            label: Text('Kết nối máy chủ tốt nhất ${flagOf(_cc)} ${cur?['country'] ?? ''}'),
          ),
          for (final s in ((cur?['servers'] as List?) ?? const []).cast<Map>())
            ListTile(
              dense: true,
              contentPadding: EdgeInsets.zero,
              leading: Text(flagOf(_cc), style: const TextStyle(fontSize: 20)),
              title: Text('${s['host']}'),
              subtitle: Text('${s['ping']} ms · ${s['mbps']} Mbps · ${s['sessions']} người dùng'),
              trailing: const Icon(Icons.chevron_right),
              onTap: _busy ? null : () => _useVpnGate(_cc!, '${s['host']}'),
            ),
        ],
        Text('Máy chủ tình nguyện (ĐH Tsukuba, Nhật): tốc độ thất thường, có ghi log → chỉ để đổi vị trí xem nội dung, '
            'không dùng cho ngân hàng / tài khoản quan trọng.',
            style: t.textTheme.bodySmall),
        const SizedBox(height: 20),
        Text('VPN của bạn (file cấu hình)', style: t.textTheme.titleMedium),
        const SizedBox(height: 8),
        OutlinedButton.icon(
          onPressed: _busy ? null : _upload,
          icon: const Icon(Icons.upload_file),
          label: const Text('Chọn file .conf (WireGuard) / .ovpn (OpenVPN)'),
        ),
        const SizedBox(height: 6),
        Text('Proton VPN Free: account.protonvpn.com → Downloads → WireGuard configuration → Router → chọn máy chủ miễn phí '
            '→ tải .conf về điện thoại → chọn ở đây. Khóa chỉ lưu trên board.',
            style: t.textTheme.bodySmall),
      ]),
    );
  }
}
