import 'package:material_ui/material_ui.dart';
import 'package:mobile_scanner/mobile_scanner.dart';

import '../api.dart';
import '../main.dart';
import '../util.dart';
import 'ocr.dart';
import 'kho.dart';

/// Tra một mã (QR, C…, chữ) rồi hiện bảng nhập kho. Trả về tên linh kiện nếu đã nhập.
Future<String?> showCodeResult(BuildContext context, String code) async {
  final api = ApiScope.read(context);
  final r = await api.post('/api/kho/scan', {'code': code}) as Map;
  if (!context.mounted) return null;
  return showModalBottomSheet<String>(
    context: context,
    isScrollControlled: true,
    useSafeArea: true,
    builder: (_) => ApiScope(api: api, child: _ScanResult(code: code, r: r)),
  );
}

/// Hỏi mã LCSC (gõ C2040 hoặc chỉ 2040) -> tự ra thông số -> nhập số lượng.
Future<String?> addByLcscCode(BuildContext context) async {
  final c = TextEditingController();
  final v = await showDialog<String>(
    context: context,
    builder: (d) => AlertDialog(
      title: const Text('Nhập mã LCSC'),
      content: TextField(
        controller: c,
        autofocus: true,
        textCapitalization: TextCapitalization.characters,
        decoration: const InputDecoration(hintText: 'C25804 hoặc 25804', helperText: 'Tự lấy thông số từ LCSC'),
        onSubmitted: (t) => Navigator.pop(d, t),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(d), child: const Text('Hủy')),
        FilledButton(onPressed: () => Navigator.pop(d, c.text), child: const Text('Tra')),
      ],
    ),
  );
  var code = (v ?? '').trim().toUpperCase().replaceAll(' ', '');
  if (code.isEmpty || !context.mounted) return null;
  if (RegExp(r'^\d{2,10}$').hasMatch(code)) code = 'C$code';
  try {
    return await showCodeResult(context, code);
  } catch (e) {
    if (context.mounted) toast(context, 'Lỗi: $e');
    return null;
  }
}

/// Quét mã trên nhãn linh kiện (ưu tiên QR LCSC) để nhập kho liên tục.
/// Server đọc mã (/api/kho/scan): QR LCSC {pc:C…,pm:…,qty:…}, DataMatrix Digi-Key, mã C…, hoặc chữ để tìm.
class ScanScreen extends StatefulWidget {
  const ScanScreen({super.key});

  @override
  State<ScanScreen> createState() => _ScanScreenState();
}

class _ScanScreenState extends State<ScanScreen> {
  static String lastLocation = '';   // giữ vị trí giữa các lần quét (quét cả chồng túi cùng một hộp)
  final _ctrl = MobileScannerController(detectionSpeed: DetectionSpeed.noDuplicates, autoZoom: true);
  bool _busy = false;
  int _count = 0;
  String? _last;

  Api get api => ApiScope.read(context);

  @override
  void dispose() {
    _ctrl.dispose();
    super.dispose();
  }

  Future<void> _onDetect(BarcodeCapture cap) async {
    if (_busy) return;
    final code = cap.barcodes.map((b) => b.rawValue).firstWhere((v) => v != null && v.trim().isNotEmpty, orElse: () => null);
    if (code == null) return;
    await _handle(code);
  }

  Future<void> _manual() async {
    final c = TextEditingController();
    final v = await showDialog<String>(
      context: context,
      builder: (d) => AlertDialog(
        title: const Text('Nhập mã'),
        content: TextField(
            controller: c,
            autofocus: true,
            decoration: const InputDecoration(hintText: 'C25804, MPN, hoặc nội dung QR')),
        actions: [
          TextButton(onPressed: () => Navigator.pop(d), child: const Text('Hủy')),
          FilledButton(onPressed: () => Navigator.pop(d, c.text), child: const Text('Tìm')),
        ],
      ),
    );
    if (v != null && v.trim().isNotEmpty) await _handle(v.trim());
  }

  Future<void> _handle(String code) async {
    setState(() => _busy = true);
    try {
      final done = await showCodeResult(context, code);
      if (done != null && mounted) {
        setState(() {
          _count++;
          _last = done;
        });
      }
    } catch (e) {
      if (mounted) toast(context, 'Lỗi: $e');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(
          title: const Text('Quét nhãn linh kiện'),
          actions: [
            IconButton(icon: const Icon(Icons.flashlight_on_outlined), tooltip: 'Đèn', onPressed: () => _ctrl.toggleTorch()),
            IconButton(
                icon: const Icon(Icons.document_scanner_outlined),
                tooltip: 'Chụp nhãn (không có QR)',
                onPressed: () async {
                  await _ctrl.stop();
                  if (!mounted) return;
                  final done = await ocrLabelMenu(context);
                  if (done != null && mounted) {
                    setState(() {
                      _count++;
                      _last = done;
                    });
                  }
                  await _ctrl.start();
                }),
            IconButton(icon: const Icon(Icons.keyboard), tooltip: 'Nhập mã bằng tay', onPressed: _manual),
          ],
        ),
        body: Stack(children: [
          MobileScanner(
            controller: _ctrl,
            onDetect: _onDetect,
            errorBuilder: (c, e) => Center(
              child: Padding(
                padding: const EdgeInsets.all(24),
                child: Text('Không mở được camera: ${e.errorDetails?.message ?? e.errorCode.name}\n'
                    'Cho phép quyền Camera trong Cài đặt của điện thoại, hoặc bấm ⌨ để nhập mã.',
                    textAlign: TextAlign.center, style: const TextStyle(color: Colors.white)),
              ),
            ),
          ),
          // khung ngắm
          IgnorePointer(
            child: Center(
              child: Container(
                width: 240,
                height: 240,
                decoration: BoxDecoration(
                    border: Border.all(color: Colors.white70, width: 2), borderRadius: BorderRadius.circular(16)),
              ),
            ),
          ),
          Positioned(
            left: 16,
            right: 16,
            bottom: 24,
            child: Container(
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(color: Colors.black54, borderRadius: BorderRadius.circular(12)),
              child: Text(
                _busy
                    ? 'Đang đọc…'
                    : _count == 0
                        ? 'Đưa QR / mã vạch trên túi LCSC (hoặc Digi-Key) vào khung\nKhông có mã? Bấm biểu tượng chụp nhãn ở trên'
                        : 'Đã nhập $_count nhãn · gần nhất: $_last\nQuét tiếp nhãn kế tiếp',
                textAlign: TextAlign.center,
                style: const TextStyle(color: Colors.white),
              ),
            ),
          ),
        ]),
      );
}

/// Bảng kết quả sau khi quét: nhập vào linh kiện có sẵn, hoặc tạo mới (tự điền từ LCSC).
class _ScanResult extends StatefulWidget {
  final String code;
  final Map r;
  const _ScanResult({required this.code, required this.r});

  @override
  State<_ScanResult> createState() => _ScanResultState();
}

class _ScanResultState extends State<_ScanResult> {
  late final Map lab = widget.r['label'] as Map;
  late Map? part = widget.r['part'] as Map?;
  late final Map? already = widget.r['already'] as Map?;
  late final _qty = TextEditingController(text: already != null ? '0' : '${lab['qty'] ?? 0}');
  final _loc = TextEditingController(text: _ScanScreenState.lastLocation);
  final _min = TextEditingController();
  bool _saving = false;

  @override
  void initState() {
    super.initState();
    _qty.selection = TextSelection(baseOffset: 0, extentOffset: _qty.text.length);   // gõ số là thay luôn
    _qty.addListener(() => setState(() {}));
  }

  Future<void> _apply(String action, {int? partId}) async {
    setState(() => _saving = true);
    _ScanScreenState.lastLocation = _loc.text.trim();
    try {
      final p = await ApiScope.read(context).post('/api/kho/scan/apply', {
        'code': widget.code,
        'action': action,
        'qty': int.tryParse(_qty.text.trim()) ?? 0,
        'part_id': ?partId,
        'fields': {
          if (_loc.text.trim().isNotEmpty) 'location': _loc.text.trim(),
          if (_min.text.trim().isNotEmpty) 'min_qty': int.tryParse(_min.text.trim()) ?? 0,
        },
      }) as Map;
      if (!mounted) return;
      toast(context, '${partTitle(p)}: còn ${p['qty']}');
      Navigator.pop(context, partTitle(p));
    } catch (e) {
      if (mounted) toast(context, 'Lỗi: $e');
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  Widget _fields({bool showLoc = true}) => Column(children: [
        TextField(
            controller: _qty,
            autofocus: (lab['qty'] as num? ?? 0) == 0 && already == null,   // nhập mã tay: gõ số lượng ngay
            keyboardType: TextInputType.number,
            decoration: const InputDecoration(labelText: 'Số lượng nhập thêm', border: OutlineInputBorder(), isDense: true)),
        if (showLoc) ...[
          const SizedBox(height: 10),
          Row(children: [
            Expanded(
                flex: 2,
                child: TextField(
                    controller: _loc,
                    decoration: InputDecoration(
                        labelText: part == null ? 'Vị trí' : 'Đổi vị trí (để trống = giữ)',
                        border: const OutlineInputBorder(),
                        isDense: true))),
            const SizedBox(width: 8),
            Expanded(
                child: TextField(
                    controller: _min,
                    keyboardType: TextInputType.number,
                    decoration:
                        const InputDecoration(labelText: 'Cảnh báo ≤', border: OutlineInputBorder(), isDense: true))),
          ]),
        ],
      ]);

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context);
    final r = widget.r;
    final results = (r['results'] as List? ?? const []).cast<Map>();
    final info = r['lcsc_info'] as Map?;
    final codeText = [
      if ('${lab['lcsc']}'.isNotEmpty) 'LCSC ${lab['lcsc']}',
      if ('${lab['digikey']}'.isNotEmpty) 'Digi-Key ${lab['digikey']}',
      if ('${lab['mpn']}'.isNotEmpty) 'MPN ${lab['mpn']}',
      if ((lab['qty'] as num? ?? 0) > 0) 'SL nhãn ${lab['qty']}',
    ].join(' · ');
    return Padding(
      padding: EdgeInsets.fromLTRB(16, 16, 16, 16 + MediaQuery.viewInsetsOf(context).bottom),
      child: SingleChildScrollView(
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, mainAxisSize: MainAxisSize.min, children: [
          // --------- mã chữ (không phải nhãn): kết quả tìm kiếm
          if ('${lab['query']}'.isNotEmpty && part == null) ...[
            Text('Tìm “${lab['query']}”', style: t.textTheme.titleMedium),
            if (results.isEmpty) const Padding(padding: EdgeInsets.all(16), child: Text('Không thấy trong kho.')),
            for (final p in results)
              ListTile(
                title: Text(partTitle(p)),
                subtitle: Text(partSub(p)),
                trailing: Text('${p['qty']}'),
                onTap: () => setState(() => part = p),
              ),
          ] else ...[
            if (codeText.isNotEmpty) Text(codeText, style: t.textTheme.bodySmall),
            const SizedBox(height: 8),
            if (already != null)
              Container(
                padding: const EdgeInsets.all(10),
                margin: const EdgeInsets.only(bottom: 10),
                decoration: BoxDecoration(color: Colors.orange.withValues(alpha: .15), borderRadius: BorderRadius.circular(8)),
                child: Text('⚠️ Nhãn này đã nhập lúc ${fmtTime(already!['ts'] as num)} (+${already!['qty']}). '
                    'Để 0 nếu chỉ muốn xem, hoặc sửa số lượng nếu đúng là nhập lại.'),
              ),
            if (part != null) ...[
              // --------- đã có trong kho
              Text(partTitle(part!), style: t.textTheme.titleLarge),
              if (partSub(part!).isNotEmpty) Text(partSub(part!), style: t.textTheme.bodySmall),
              const SizedBox(height: 6),
              Text('Trong kho: ${part!['qty']}${'${part!['location'] ?? ''}'.isNotEmpty ? ' · 📍 ${part!['location']}' : ''}',
                  style: t.textTheme.titleSmall),
              const SizedBox(height: 12),
              _fields(),
              const SizedBox(height: 12),
              FilledButton.icon(
                onPressed: _saving ? null : () => _apply('add', partId: part!['id'] as int),
                icon: const Icon(Icons.add),
                label: Text('Nhập +${_qty.text.isEmpty ? 0 : _qty.text}'),
              ),
              TextButton(
                onPressed: () async {
                  final nav = Navigator.of(context);
                  final id = part!['id'] as int;
                  nav.pop();
                  await nav.push(MaterialPageRoute(builder: (_) => PartScreen(id: id)));
                },
                child: const Text('Mở linh kiện'),
              ),
            ] else ...[
              // --------- chưa có trong kho
              Text('Chưa có trong kho', style: t.textTheme.titleLarge),
              const SizedBox(height: 6),
              if (info != null)
                Card(
                  child: ListTile(
                    leading: info['image'] != null
                        ? ClipRRect(
                            borderRadius: BorderRadius.circular(6),
                            child: Image.network('${info['image']}', width: 48, height: 48, fit: BoxFit.cover,
                                errorBuilder: (_, _, _) => const Icon(Icons.memory)))
                        : const Icon(Icons.memory),
                    title: Text('${info['mpn'] ?? lab['mpn']}'),
                    subtitle: Text([info['value'], info['package'], info['manufacturer'], info['category'], info['name']]
                        .where((x) => x != null && '$x'.isNotEmpty)
                        .toSet()
                        .join(' · ')),
                  ),
                )
              else if ('${r['lcsc_error'] ?? ''}'.isNotEmpty)
                Text('Không tra được LCSC (${r['lcsc_error']}). Vẫn tạo được, thông tin điền sau.',
                    style: t.textTheme.bodySmall),
              const SizedBox(height: 12),
              _fields(),
              const SizedBox(height: 12),
              FilledButton.icon(
                onPressed: _saving ? null : () => _apply('create'),
                icon: const Icon(Icons.add_box),
                label: Text('Tạo mới & nhập ${_qty.text.isEmpty ? 0 : _qty.text}'),
              ),
              TextButton(
                onPressed: _saving
                    ? null
                    : () async {
                        final pid = await Navigator.push<int>(context,
                            MaterialPageRoute(builder: (_) => PartPickerScreen(initial: '${lab['mpn'] ?? ''}')));
                        if (pid != null) await _apply('add', partId: pid);
                      },
                child: const Text('Là linh kiện có sẵn khác → chọn'),
              ),
            ],
          ],
          TextButton(onPressed: () => Navigator.pop(context), child: const Text('Bỏ qua')),
        ]),
      ),
    );
  }
}
