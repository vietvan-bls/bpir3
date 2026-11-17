import 'dart:async';
import 'dart:typed_data';

import 'package:flutter/services.dart';
import 'package:http/http.dart' as http;
import 'package:material_ui/material_ui.dart';

import '../main.dart';

/// Xem camera MJPEG (`/camera.mjpg`) + khung nhận dạng người (`/api/vision/stream`).
class CameraScreen extends StatefulWidget {
  const CameraScreen({super.key});

  @override
  State<CameraScreen> createState() => _CameraScreenState();
}

class _CameraScreenState extends State<CameraScreen> {
  bool _boxes = true, _trails = true;
  Map<String, dynamic>? _det;
  StreamSubscription? _visionSub;
  Timer? _visionRetry;

  @override
  void initState() {
    super.initState();
    _startVision();
  }

  void _startVision() {
    _visionSub?.cancel();
    _visionSub = ApiScope.read(context).sse('/api/vision/stream').listen(
      (d) {
        if (mounted) setState(() => _det = d);
      },
      onError: (_) => _retryVision(),
      onDone: _retryVision,
      cancelOnError: true,
    );
  }

  void _retryVision() {
    if (!mounted) return;
    setState(() => _det = null);
    _visionRetry?.cancel();
    _visionRetry = Timer(const Duration(seconds: 3), _startVision);
  }

  @override
  void dispose() {
    _visionRetry?.cancel();
    _visionSub?.cancel();
    super.dispose();
  }

  Widget _view({bool full = false}) => AspectRatio(
        aspectRatio: _det != null ? (_det!['w'] as num) / (_det!['h'] as num) : 4 / 3,
        child: Stack(fit: StackFit.expand, children: [
          const MjpegView(path: '/camera.mjpg'),
          CustomPaint(painter: _DetPainter(_det, boxes: _boxes, trails: _trails)),
          Positioned(
            left: 8,
            top: 8,
            child: _osd(const Text('● LIVE · CAM-01', style: TextStyle(color: Colors.white, fontSize: 12))),
          ),
          if (_det != null)
            Positioned(
              left: 8,
              bottom: 8,
              child: _osd(Text('👤 ${_det!['count']} người · tổng ${_det!['total']}',
                  style: const TextStyle(color: Colors.white, fontSize: 12))),
            ),
          if (full)
            Positioned(
              right: 8,
              top: 8,
              child: IconButton.filledTonal(
                  onPressed: () => Navigator.pop(context), icon: const Icon(Icons.fullscreen_exit)),
            ),
        ]),
      );

  Widget _osd(Widget child) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 3),
        decoration: BoxDecoration(color: Colors.black54, borderRadius: BorderRadius.circular(4)),
        child: child,
      );

  Future<void> _fullscreen() async {
    await SystemChrome.setPreferredOrientations(
        [DeviceOrientation.landscapeLeft, DeviceOrientation.landscapeRight]);
    await SystemChrome.setEnabledSystemUIMode(SystemUiMode.immersive);
    if (!mounted) return;
    await Navigator.push(
      context,
      MaterialPageRoute(
        builder: (_) => StatefulBuilder(
          builder: (c, _) => Scaffold(backgroundColor: Colors.black, body: Center(child: _view(full: true))),
        ),
      ),
    );
    await SystemChrome.setPreferredOrientations([]);
    await SystemChrome.setEnabledSystemUIMode(SystemUiMode.edgeToEdge);
  }

  @override
  Widget build(BuildContext context) {
    final api = ApiScope.of(context);
    final d = _det;
    return ListView(padding: const EdgeInsets.all(16), children: [
      ClipRRect(
        borderRadius: BorderRadius.circular(12),
        child: ColoredBox(color: Colors.black, child: _view()),
      ),
      const SizedBox(height: 12),
      Row(children: [
        Expanded(child: _stat('Đang thấy', d == null ? '–' : '${d['count']}')),
        const SizedBox(width: 8),
        Expanded(child: _stat('Tổng lượt', d == null ? '–' : '${d['total']}')),
        const SizedBox(width: 8),
        Expanded(child: _stat('Xử lý', d == null ? '–' : '${d['ms']} ms')),
      ]),
      const SizedBox(height: 8),
      SwitchListTile(
        title: const Text('Khung + ID'),
        value: _boxes,
        onChanged: (v) => setState(() => _boxes = v),
      ),
      SwitchListTile(
        title: const Text('Vệt đường đi'),
        value: _trails,
        onChanged: (v) => setState(() => _trails = v),
      ),
      Wrap(spacing: 8, runSpacing: 8, children: [
        OutlinedButton.icon(
            onPressed: _fullscreen, icon: const Icon(Icons.fullscreen), label: const Text('Toàn màn hình')),
        OutlinedButton.icon(
          onPressed: () {
            final u = '${api.publicUrl.isNotEmpty && !api.viaLan ? api.publicUrl : api.base}/camera.mjpg';
            Clipboard.setData(ClipboardData(text: u));
            ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Đã sao chép: $u')));
          },
          icon: const Icon(Icons.link),
          label: const Text('Sao chép link stream'),
        ),
      ]),
    ]);
  }

  Widget _stat(String label, String value) => Card(
        child: Padding(
          padding: const EdgeInsets.all(10),
          child: Column(children: [
            Text(label, style: Theme.of(context).textTheme.labelSmall),
            Text(value, style: Theme.of(context).textTheme.titleMedium),
          ]),
        ),
      );
}

Color _idColor(int id) => HSLColor.fromAHSL(1, (id * 67 % 360).toDouble(), .9, .55).toColor();

class _DetPainter extends CustomPainter {
  final Map<String, dynamic>? d;
  final bool boxes, trails;
  _DetPainter(this.d, {required this.boxes, required this.trails});

  @override
  void paint(Canvas canvas, Size size) {
    final d = this.d;
    if (d == null) return;
    final w = (d['w'] as num).toDouble(), h = (d['h'] as num).toDouble();
    final s = size.width / w < size.height / h ? size.width / w : size.height / h;
    final ox = (size.width - w * s) / 2, oy = (size.height - h * s) / 2;
    Offset pt(num x, num y) => Offset(ox + x * s, oy + y * s);
    for (final p in (d['people'] as List? ?? const [])) {
      final col = _idColor((p['id'] as num).toInt());
      final paint = Paint()
        ..color = col
        ..strokeWidth = 2
        ..style = PaintingStyle.stroke;
      final trail = (p['trail'] as List? ?? const []);
      if (trails && trail.length > 1) {
        final path = Path();
        for (var i = 0; i < trail.length; i++) {
          final o = pt(trail[i][0] as num, trail[i][1] as num);
          i == 0 ? path.moveTo(o.dx, o.dy) : path.lineTo(o.dx, o.dy);
        }
        canvas.drawPath(path, paint..color = col.withValues(alpha: .8));
      }
      if (boxes) {
        final b = p['box'] as List;
        final r = pt(b[0] as num, b[1] as num) & Size((b[2] as num) * s, (b[3] as num) * s);
        canvas.drawRect(r, paint..color = col);
        final tp = TextPainter(
          text: TextSpan(
              text: '#${p['id']}',
              style: const TextStyle(color: Colors.black, fontSize: 12, fontWeight: FontWeight.w600)),
          textDirection: TextDirection.ltr,
        )..layout();
        canvas.drawRect(Rect.fromLTWH(r.left, r.top - 16, tp.width + 8, 16), Paint()..color = col);
        tp.paint(canvas, Offset(r.left + 4, r.top - 15));
      }
    }
  }

  @override
  bool shouldRepaint(_DetPainter old) => old.d != d || old.boxes != boxes || old.trails != trails;
}

/// Đọc stream multipart MJPEG, tách từng ảnh JPEG theo marker FFD8…FFD9.
class MjpegView extends StatefulWidget {
  final String path;
  const MjpegView({required this.path, super.key});

  @override
  State<MjpegView> createState() => _MjpegViewState();
}

class _MjpegViewState extends State<MjpegView> {
  Uint8List? _frame;
  String? _msg = 'Đang kết nối camera…';
  http.Client? _client;
  StreamSubscription? _sub;
  Timer? _retry;
  final _buf = BytesBuilder(copy: false);

  @override
  void initState() {
    super.initState();
    _start();
  }

  Future<void> _start() async {
    _stop();
    try {
      final (c, stream) = await ApiScope.read(context).openStream('${widget.path}?t=${DateTime.now().millisecondsSinceEpoch}');
      if (!mounted) {
        c.close();
        return;
      }
      _client = c;
      _sub = stream.listen(_onData, onError: (_) => _fail(), onDone: _fail, cancelOnError: true);
    } catch (_) {
      _fail();
    }
  }

  void _onData(List<int> chunk) {
    _buf.add(chunk);
    var data = _buf.toBytes();
    Uint8List? last;
    var consumed = 0;
    while (true) {
      final start = _find(data, 0xD8, consumed);
      if (start < 0) break;
      final end = _find(data, 0xD9, start + 2);
      if (end < 0) {
        consumed = start;
        break;
      }
      last = Uint8List.sublistView(data, start, end + 2);
      consumed = end + 2;
    }
    _buf.clear();
    if (consumed < data.length) _buf.add(Uint8List.sublistView(data, consumed));
    if (_buf.length > 4 << 20) _buf.clear(); // dữ liệu lỗi: bỏ
    if (last != null && mounted) {
      final frame = Uint8List.fromList(last);
      setState(() {
        _frame = frame;
        _msg = null;
      });
    }
  }

  static int _find(Uint8List d, int marker, int from) {
    for (var i = from; i < d.length - 1; i++) {
      if (d[i] == 0xFF && d[i + 1] == marker) return i;
    }
    return -1;
  }

  void _fail() {
    if (!mounted) return;
    setState(() => _msg = 'Mất kết nối camera, đang thử lại…');
    _retry?.cancel();
    _retry = Timer(const Duration(seconds: 3), _start);
  }

  void _stop() {
    _retry?.cancel();
    _sub?.cancel();
    _client?.close();
    _client = null;
    _buf.clear();
  }

  @override
  void dispose() {
    _stop();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Stack(fit: StackFit.expand, children: [
        if (_frame != null) Image.memory(_frame!, gaplessPlayback: true, fit: BoxFit.contain),
        if (_msg != null)
          Center(child: Text(_msg!, style: const TextStyle(color: Colors.white70))),
      ]);
}
