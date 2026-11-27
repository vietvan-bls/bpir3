import 'package:material_ui/material_ui.dart';

import '../main.dart';

/// Nhập địa chỉ board + mật khẩu. Tự thử kết nối khi mở app.
class ConnectScreen extends StatefulWidget {
  const ConnectScreen({super.key});

  @override
  State<ConnectScreen> createState() => _ConnectScreenState();
}

class _ConnectScreenState extends State<ConnectScreen> {
  final _pub = TextEditingController();
  final _lan = TextEditingController();
  final _pw = TextEditingController();
  final _user = TextEditingController();
  bool _asCustomer = false;   // đăng nhập tài khoản kho (khách) thay vì quản trị
  bool _busy = false;
  bool _tried = false;
  String? _err;

  @override
  void initState() {
    super.initState();
    final api = ApiScope.read(context);
    _pub.text = api.publicUrl;
    _lan.text = api.lanUrl;
    if (api.publicUrl.isNotEmpty || api.lanUrl.isNotEmpty) {
      WidgetsBinding.instance.addPostFrameCallback((_) => _connect());
    }
  }

  Future<void> _connect() async {
    final api = ApiScope.read(context);
    setState(() {
      _busy = true;
      _err = null;
    });
    await api.saveUrls(lan: _lan.text, pub: _pub.text);
    final ok = await api.connect();
    if (!mounted) return;
    setState(() {
      _busy = false;
      _tried = true;
      _err = ok ? null : 'Không kết nối được tới board. Kiểm tra lại địa chỉ (link công khai đổi mỗi khi board tạo link mới).';
    });
  }

  Future<void> _login() async {
    final api = ApiScope.read(context);
    setState(() {
      _busy = true;
      _err = null;
    });
    try {
      if (_asCustomer) {
        await api.khoLogin(_user.text.trim(), _pw.text);
        if (!api.isKhoCustomer && mounted) setState(() => _err = 'Đăng nhập không thành công');
      } else {
        await api.login(_pw.text);
      }
      _pw.clear();
    } catch (e) {
      if (mounted) setState(() => _err = '$e');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final api = ApiScope.of(context);
    final needPw = api.connected && !api.isAdmin;
    final t = Theme.of(context);
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(24),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 420),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Icon(Icons.router, size: 56, color: t.colorScheme.primary),
                  const SizedBox(height: 8),
                  Text('BPI-R3', textAlign: TextAlign.center, style: t.textTheme.headlineMedium),
                  const SizedBox(height: 24),
                  if (!needPw) ...[
                    TextField(
                      controller: _pub,
                      keyboardType: TextInputType.url,
                      autocorrect: false,
                      decoration: const InputDecoration(
                        labelText: 'Link công khai',
                        hintText: 'https://xxxx.trycloudflare.com',
                        border: OutlineInputBorder(),
                        prefixIcon: Icon(Icons.public),
                      ),
                    ),
                    const SizedBox(height: 12),
                    TextField(
                      controller: _lan,
                      keyboardType: TextInputType.url,
                      autocorrect: false,
                      decoration: const InputDecoration(
                        labelText: 'Địa chỉ trong mạng (không bắt buộc)',
                        hintText: '192.168.1.1:8080',
                        helperText: 'Ở nhà app dùng địa chỉ này trước: nhanh hơn, không cần mật khẩu',
                        border: OutlineInputBorder(),
                        prefixIcon: Icon(Icons.home),
                      ),
                    ),
                    const SizedBox(height: 16),
                    FilledButton.icon(
                      onPressed: _busy ? null : _connect,
                      icon: _busy
                          ? const SizedBox.square(
                              dimension: 18, child: CircularProgressIndicator(strokeWidth: 2))
                          : const Icon(Icons.link),
                      label: Text(_busy ? 'Đang kết nối…' : 'Kết nối'),
                    ),
                  ] else ...[
                    Card(
                      child: ListTile(
                        leading: const Icon(Icons.public),
                        title: Text(api.base, style: t.textTheme.bodySmall),
                        subtitle: const Text('Cần đăng nhập'),
                        trailing: IconButton(
                          icon: const Icon(Icons.edit),
                          tooltip: 'Đổi địa chỉ',
                          onPressed: api.disconnect,
                        ),
                      ),
                    ),
                    const SizedBox(height: 16),
                    SegmentedButton<bool>(
                      segments: const [
                        ButtonSegment(value: false, icon: Icon(Icons.admin_panel_settings), label: Text('Quản trị')),
                        ButtonSegment(value: true, icon: Icon(Icons.inventory_2), label: Text('Khách kho')),
                      ],
                      selected: {_asCustomer},
                      onSelectionChanged: (v) => setState(() {
                        _asCustomer = v.first;
                        _err = null;
                      }),
                    ),
                    const SizedBox(height: 12),
                    if (!_asCustomer && api.who['password_set'] == false)
                      const Text(
                          'Chủ board chưa đặt mật khẩu truy cập từ xa. Hãy kết nối bằng địa chỉ trong mạng và đặt mật khẩu ở mục Hệ thống.')
                    else ...[
                      if (_asCustomer) ...[
                        TextField(
                          controller: _user,
                          autocorrect: false,
                          textCapitalization: TextCapitalization.none,
                          decoration: const InputDecoration(
                            labelText: 'Tên đăng nhập kho',
                            border: OutlineInputBorder(),
                            prefixIcon: Icon(Icons.person),
                          ),
                        ),
                        const SizedBox(height: 10),
                      ],
                      TextField(
                        controller: _pw,
                        obscureText: true,
                        autofocus: true,
                        onSubmitted: (_) => _login(),
                        decoration: const InputDecoration(
                          labelText: 'Mật khẩu',
                          border: OutlineInputBorder(),
                          prefixIcon: Icon(Icons.lock),
                        ),
                      ),
                      const SizedBox(height: 16),
                      FilledButton(
                        onPressed: _busy ? null : _login,
                        child: Text(_busy ? 'Đang đăng nhập…' : 'Đăng nhập'),
                      ),
                    ],
                  ],
                  if (_err != null && (_tried || needPw)) ...[
                    const SizedBox(height: 12),
                    Text(_err!, style: TextStyle(color: t.colorScheme.error)),
                  ],
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}
