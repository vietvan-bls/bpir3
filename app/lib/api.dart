import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

class ApiError implements Exception {
  final String message;
  final bool needLogin;
  ApiError(this.message, {this.needLogin = false});
  @override
  String toString() => message;
}

/// Client cho "BPI-R3 Server" (các endpoint /api/*).
///
/// - Đăng nhập bằng cookie phiên (`/api/login`), cookie được lưu lại.
/// - POST phải có header `X-BPI: 1` (server chống CSRF).
/// - Có 2 địa chỉ: [lanUrl] (trong mạng nội bộ, toàn quyền, không cần mật khẩu)
///   và [publicUrl] (link trycloudflare, cần đăng nhập). Khi mở app sẽ thử LAN trước.
class Api extends ChangeNotifier {
  static const _kLan = 'lanUrl', _kPub = 'publicUrl', _kCookie = 'cookie';

  final http.Client _client = http.Client();
  late SharedPreferences _prefs;

  String lanUrl = '';
  String publicUrl = '';
  String base = '';
  String? cookie;
  Map<String, dynamic> who = {};

  bool get connected => base.isNotEmpty;
  bool get isAdmin => who['admin'] == true;
  bool get isLocal => who['local'] == true;
  bool get viaLan => base.isNotEmpty && base == lanUrl;

  Future<void> load() async {
    _prefs = await SharedPreferences.getInstance();
    lanUrl = _prefs.getString(_kLan) ?? '';
    publicUrl = _prefs.getString(_kPub) ?? '';
    cookie = _prefs.getString(_kCookie);
  }

  static String normalize(String url) {
    var u = url.trim();
    if (u.isEmpty) return '';
    if (!u.contains('://')) {
      // IP nội bộ -> http, cổng 8080; tên miền -> https
      final isIp = RegExp(r'^\d{1,3}(\.\d{1,3}){3}(:\d+)?(/.*)?$').hasMatch(u);
      u = isIp ? 'http://$u' : 'https://$u';
      if (isIp && !RegExp(r'^http://[\d.]+:\d+').hasMatch(u)) {
        u = u.replaceFirstMapped(RegExp(r'^(http://[\d.]+)'), (m) => '${m[1]}:8080');
      }
    }
    while (u.endsWith('/')) {
      u = u.substring(0, u.length - 1);
    }
    return u;
  }

  Future<void> saveUrls({String? lan, String? pub}) async {
    if (lan != null) {
      lanUrl = normalize(lan);
      await _prefs.setString(_kLan, lanUrl);
    }
    if (pub != null) {
      publicUrl = normalize(pub);
      await _prefs.setString(_kPub, publicUrl);
    }
    notifyListeners();
  }

  /// Thử kết nối: LAN trước (timeout ngắn), sau đó link công khai.
  /// Trả về true nếu tới được board (có thể vẫn cần đăng nhập: xem [isAdmin]).
  Future<bool> connect() async {
    for (final (url, timeout) in [(lanUrl, 3), (publicUrl, 12)]) {
      if (url.isEmpty) continue;
      try {
        final r = await _client
            .get(Uri.parse('$url/api/whoami'), headers: _headers())
            .timeout(Duration(seconds: timeout));
        if (r.statusCode == 200) {
          who = jsonDecode(utf8.decode(r.bodyBytes)) as Map<String, dynamic>;
          base = url;
          notifyListeners();
          if (isAdmin) unawaited(_learnUrls());
          return true;
        }
      } catch (_) {}
    }
    base = '';
    notifyListeners();
    return false;
  }

  /// Ghi nhớ link công khai mới nhất và IP LAN để lần sau tự kết nối.
  Future<void> _learnUrls() async {
    try {
      final p = await get('/api/public-url');
      final u = p['url'];
      if (u is String && u.startsWith('https://') && normalize(u) != publicUrl) {
        await saveUrls(pub: u);
      }
    } catch (_) {}
    if (lanUrl.isEmpty) {
      try {
        final l = await get('/api/lan');
        if (l['ip'] is String) await saveUrls(lan: 'http://${l['ip']}:8080');
      } catch (_) {}
    }
  }

  Future<void> login(String password) async {
    final r = await _client.post(Uri.parse('$base/api/login'),
        headers: _headers(json: true), body: jsonEncode({'password': password}));
    _check(r);
    final sc = r.headers['set-cookie'];
    if (sc != null) {
      // Lấy các cặp name=value, bỏ thuộc tính (Path, HttpOnly, ...)
      final parts = RegExp(r'(?:^|,\s*)([^=;,\s]+)=([^;,]*)')
          .allMatches(sc)
          .where((m) => !const {'path', 'expires', 'max-age', 'domain', 'samesite'}
              .contains(m[1]!.toLowerCase()))
          .map((m) => '${m[1]}=${m[2]}');
      cookie = parts.join('; ');
      await _prefs.setString(_kCookie, cookie!);
    }
    await connect();
  }

  Future<void> logout() async {
    try {
      await post('/api/logout', {});
    } catch (_) {}
    cookie = null;
    await _prefs.remove(_kCookie);
    who = {};
    notifyListeners();
  }

  void disconnect() {
    base = '';
    who = {};
    notifyListeners();
  }

  Map<String, String> _headers({bool json = false}) => {
        if (cookie != null) 'Cookie': cookie!,
        'X-BPI': '1',
        if (json) 'Content-Type': 'application/json',
      };

  /// Header dùng cho Image.network / audio (cần cookie khi đi qua link công khai).
  Map<String, String> get mediaHeaders => {if (cookie != null) 'Cookie': cookie!};

  String url(String path) => '$base$path';

  dynamic _check(http.Response r) {
    dynamic j;
    try {
      j = jsonDecode(utf8.decode(r.bodyBytes));
    } catch (_) {
      j = {};
    }
    if (r.statusCode == 401 && j is Map && j['login'] == true) {
      who = {...who, 'admin': false};
      notifyListeners();
      throw ApiError('Cần đăng nhập', needLogin: true);
    }
    if (r.statusCode < 200 || r.statusCode >= 300) {
      throw ApiError(j is Map && j['error'] != null ? '${j['error']}' : 'HTTP ${r.statusCode}');
    }
    return j;
  }

  Future<dynamic> get(String path, {Duration timeout = const Duration(seconds: 20)}) async {
    final r = await _client.get(Uri.parse(url(path)), headers: _headers()).timeout(timeout);
    return _check(r);
  }

  Future<dynamic> post(String path, Object body,
      {Duration timeout = const Duration(seconds: 60)}) async {
    final r = await _client
        .post(Uri.parse(url(path)), headers: _headers(json: true), body: jsonEncode(body))
        .timeout(timeout);
    return _check(r);
  }

  /// Mở một stream HTTP dài (MJPEG, SSE). Gọi `close()` trên client trả về để ngắt.
  Future<(http.Client, Stream<List<int>>)> openStream(String path) async {
    final c = http.Client();
    final req = http.Request('GET', Uri.parse(url(path)))..headers.addAll(_headers());
    final res = await c.send(req);
    if (res.statusCode != 200) {
      c.close();
      throw ApiError('HTTP ${res.statusCode}');
    }
    return (c, res.stream);
  }

  /// Server-Sent Events: trả về từng object JSON trong các dòng `data:`.
  Stream<Map<String, dynamic>> sse(String path) async* {
    final (c, s) = await openStream(path);
    try {
      final buf = StringBuffer();
      await for (final line in s.transform(utf8.decoder).transform(const LineSplitter())) {
        if (line.startsWith('data:')) {
          buf.write(line.substring(5).trimLeft());
        } else if (line.isEmpty && buf.isNotEmpty) {
          try {
            yield jsonDecode(buf.toString()) as Map<String, dynamic>;
          } catch (_) {}
          buf.clear();
        }
      }
    } finally {
      c.close();
    }
  }

  /// Tải file nhạc lên (body là dữ liệu thô, giống trang web).
  Future<void> upload(String name, Stream<List<int>> data, int length,
      void Function(double) onProgress) async {
    final req = http.StreamedRequest(
        'POST', Uri.parse(url('/api/music/upload?name=${Uri.encodeQueryComponent(name)}')))
      ..headers.addAll(_headers())
      ..headers['Content-Type'] = 'application/octet-stream'
      ..contentLength = length;
    var sent = 0;
    final done = _client.send(req);
    await for (final chunk in data) {
      req.sink.add(chunk);
      sent += chunk.length;
      if (length > 0) onProgress(sent / length);
    }
    await req.sink.close();
    final res = await http.Response.fromStream(await done);
    _check(res);
  }

  /// Tải lên dữ liệu thô (file CSV/XLSX…) tới [path], trả về JSON.
  Future<dynamic> uploadBytes(String path, List<int> data) async {
    final r = await _client
        .post(Uri.parse(url(path)),
            headers: {..._headers(), 'Content-Type': 'application/octet-stream'}, body: data)
        .timeout(const Duration(seconds: 60));
    return _check(r);
  }

  /// Gọi thẳng tới một địa chỉ khác (dùng khi đổi IP LAN để xác nhận IP mới).
  Future<bool> ping(String fullUrl) async {
    try {
      final r = await _client.get(Uri.parse(fullUrl)).timeout(const Duration(seconds: 3));
      return r.statusCode < 500;
    } catch (_) {
      return false;
    }
  }
}
