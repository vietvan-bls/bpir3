import 'dart:io';

import 'package:google_mlkit_text_recognition/google_mlkit_text_recognition.dart';
import 'package:image_picker/image_picker.dart';
import 'package:material_ui/material_ui.dart';

import '../util.dart';
import 'scan.dart';

/// Thông tin đọc được từ chữ trên nhãn (khi không quét được QR).
class LabelText {
  String lcsc = '', mpn = '', digikey = '', order = '';
  int qty = 0;
  List<String> lcscAll = [], tokens = [];
}

/// Sửa lỗi OCR hay gặp trong phần số của mã LCSC (O->0, I/l->1, S->5, B->8, Z->2).
String _fixDigits(String s) => s
    .replaceAll(RegExp('[Oo]'), '0')
    .replaceAll(RegExp('[Il|]'), '1')
    .replaceAll('S', '5')
    .replaceAll('B', '8')
    .replaceAll('Z', '2');

int _parseQty(String s) {
  final t = s.replaceAll(RegExp(r'\s'), '');
  // 1,500 / 1.500 / 1500 -> 1500 (dấu , . là phân cách hàng nghìn)
  final m = RegExp(r'^\d{1,3}([.,]\d{3})+$').hasMatch(t) ? t.replaceAll(RegExp('[.,]'), '') : t.split(RegExp('[.,]')).first;
  return int.tryParse(m) ?? 0;
}

/// Tách mã LCSC, MPN, số lượng… từ chữ OCR của nhãn (LCSC, Digi-Key, Mouser, nhãn tự in).
LabelText parseLabelText(String text) {
  final r = LabelText();
  var mpnStrong = false;
  final lines = text.split('\n').map((l) => l.trim()).where((l) => l.isNotEmpty).toList();
  for (final line in lines) {
    final compact = line.replaceAll(' ', '');
    // mã LCSC: C + 3–10 chữ số (cho phép lỗi O/I/S trong phần số), đứng riêng
    for (final m in RegExp(r'(?<![A-Z0-9])C([0-9OoIlSBZ]{3,10})(?![A-Za-z0-9])').allMatches(compact)) {
      final digits = _fixDigits(m.group(1)!);
      if (RegExp(r'^\d+$').hasMatch(digits) && RegExp(r'\d').allMatches(m.group(1)!).length >= 3) {
        final c = 'C$digits';
        if (!r.lcscAll.contains(c)) r.lcscAll.add(c);
      }
    }
    // MPN: nhãn chắc chắn ("MPN", "Mfr Part", "Manufacturer Part") ưu tiên hơn nhãn chung ("P/N", "Part No")
    final strong = RegExp(r"(?:MPN|Mfr\.?\s*(?:Part)?\s*(?:No\.?|#|Number)?|Manufacturer\s*Part\s*(?:No\.?|#|Number)?)\s*[:：#.]?\s*(.+)$",
            caseSensitive: false)
        .firstMatch(line);
    final generic = RegExp(r"(?:P\s*/\s*N|Part\s*No\.?|Part\s*Number)\s*[:：#.]?\s*(.+)$", caseSensitive: false).firstMatch(line);
    for (final (mm, isStrong) in [(strong, true), (generic, false)]) {
      if (mm == null || (!isStrong && RegExp('digi|mouser|lcsc|customer', caseSensitive: false).hasMatch(line))) continue;
      final v = mm.group(1)!.replaceAll(' ', '').replaceAll(RegExp(r'[,;:.]+$'), '');
      if (v.length < 3 || v.toUpperCase().endsWith('-ND')) continue;
      if (isStrong && !mpnStrong) {
        r.mpn = v;
        mpnStrong = true;
      } else if (!isStrong && r.mpn.isEmpty) {
        r.mpn = v;
      }
      break;
    }
    final q = RegExp(r"(?:QTY|Q'TY|Quantity|S[ốo]\s*l[ưu][ợo]ng|SL)\s*[:：.]?\s*(\d[\d.,\s]*)", caseSensitive: false).firstMatch(line);
    if (q != null && r.qty == 0) r.qty = _parseQty(q.group(1)!);
    final o = RegExp(r'WM\d{8,}').firstMatch(compact.replaceAll('.', ''));
    if (o != null && r.order.isEmpty) r.order = o.group(0)!;
    final dk = RegExp(r'[A-Z0-9][A-Z0-9.\-/]{2,}-ND\b').firstMatch(compact.toUpperCase());
    if (dk != null && r.digikey.isEmpty) r.digikey = dk.group(0)!;
    // các cụm có cả chữ lẫn số (ứng viên MPN để chạm chọn)
    for (final w in line.split(RegExp(r'[\s:：,;]+'))) {
      final t = w.replaceAll(RegExp(r'^[^A-Za-z0-9]+|[^A-Za-z0-9]+$'), '');
      if (t.length >= 4 &&
          t.length <= 40 &&
          RegExp('[A-Za-z]').hasMatch(t) &&
          RegExp(r'\d').hasMatch(t) &&
          !r.tokens.contains(t) &&
          !RegExp(r'^(QTY|MPN|COO|WM\d+)', caseSensitive: false).hasMatch(t)) {
        r.tokens.add(t);
      }
    }
  }
  // dự phòng: OCR đọc chữ C đầu mã thành 6 / G / ( -> dòng chỉ có một dãy số đứng riêng
  if (r.lcscAll.isEmpty) {
    for (final line in lines) {
      final m = RegExp(r'^[^A-Za-z0-9]*[6G(]([0-9OIlS]{5,9})$').firstMatch(line.replaceAll(' ', ''));
      if (m != null) {
        final c = 'C${_fixDigits(m.group(1)!)}';
        if (RegExp(r'^C\d+$').hasMatch(c)) r.lcscAll.add(c);
      }
    }
  }
  if (r.lcscAll.isNotEmpty) r.lcsc = r.lcscAll.first;
  return r;
}

/// Mã giả lập theo định dạng nhãn mà server hiểu (/api/kho/scan), để đi chung luồng với quét QR.
String buildCode({String lcsc = '', String mpn = '', String digikey = '', String order = '', int qty = 0}) {
  String clean(String s) => s.replaceAll(RegExp(r'[,{}]'), '').trim();
  if (lcsc.isEmpty && digikey.isNotEmpty) {
    return '[)>\u001e06\u001dP${clean(digikey)}\u001d1P${clean(mpn)}\u001dQ$qty\u001d1K${clean(order)}';
  }
  return '{on:${clean(order)},pc:${clean(lcsc).toUpperCase()},pm:${clean(mpn)},qty:$qty}';
}

/// Chụp (hoặc chọn) ảnh nhãn -> đọc chữ -> màn hình xác nhận. Trả về tên linh kiện nếu đã nhập kho.
Future<String?> ocrLabel(BuildContext context, {ImageSource source = ImageSource.camera}) async {
  final XFile? img;
  try {
    img = await ImagePicker().pickImage(source: source, maxWidth: 2400, imageQuality: 92);
  } catch (e) {
    if (context.mounted) toast(context, 'Không mở được camera: $e');
    return null;
  }
  if (img == null || !context.mounted) return null;
  final rec = TextRecognizer(script: TextRecognitionScript.latin);
  String text;
  try {
    text = (await rec.processImage(InputImage.fromFilePath(img.path))).text;
  } catch (e) {
    if (context.mounted) toast(context, 'Lỗi đọc chữ: $e');
    return null;
  } finally {
    rec.close();
  }
  if (!context.mounted) return null;
  return Navigator.push<String>(
      context, MaterialPageRoute(builder: (_) => OcrResultScreen(imagePath: img!.path, text: text)));
}

class OcrResultScreen extends StatefulWidget {
  final String imagePath, text;
  const OcrResultScreen({required this.imagePath, required this.text, super.key});

  @override
  State<OcrResultScreen> createState() => _OcrResultScreenState();
}

class _OcrResultScreenState extends State<OcrResultScreen> {
  late final LabelText lt = parseLabelText(widget.text);
  late final _lcsc = TextEditingController(text: lt.lcsc);
  late final _mpn = TextEditingController(text: lt.mpn);
  late final _qty = TextEditingController(text: lt.qty > 0 ? '${lt.qty}' : '');
  bool _showText = false;

  Future<void> _go() async {
    var lcsc = _lcsc.text.trim().toUpperCase();
    if (RegExp(r'^\d{3,10}$').hasMatch(lcsc)) lcsc = 'C$lcsc';
    final mpn = _mpn.text.trim();
    if (lcsc.isEmpty && mpn.isEmpty && lt.digikey.isEmpty) {
      return toast(context, 'Cần mã LCSC hoặc MPN (chạm vào một cụm chữ bên dưới để chọn)');
    }
    final code = buildCode(lcsc: lcsc, mpn: mpn, digikey: lt.digikey, order: lt.order, qty: int.tryParse(_qty.text.trim()) ?? 0);
    try {
      final done = await showCodeResult(context, code);
      if (done != null && mounted) Navigator.pop(context, done);
    } catch (e) {
      if (mounted) toast(context, 'Lỗi: $e');
    }
  }

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context);
    return Scaffold(
      appBar: AppBar(title: const Text('Đọc chữ trên nhãn')),
      body: ListView(padding: const EdgeInsets.all(16), children: [
        ClipRRect(
          borderRadius: BorderRadius.circular(12),
          child: Image.file(File(widget.imagePath), height: 180, fit: BoxFit.cover),
        ),
        const SizedBox(height: 12),
        if (widget.text.trim().isEmpty)
          const Text('Không đọc được chữ nào. Chụp lại gần hơn, đủ sáng, nhãn không bị lóa.'),
        TextField(
          controller: _lcsc,
          textCapitalization: TextCapitalization.characters,
          decoration: InputDecoration(
            labelText: 'Mã LCSC',
            hintText: 'C25804',
            border: const OutlineInputBorder(),
            isDense: true,
            helperText: lt.lcscAll.length > 1 ? 'Đọc được nhiều mã: ${lt.lcscAll.join(', ')}' : 'Có mã LCSC thì tự lấy thông số',
          ),
        ),
        const SizedBox(height: 10),
        TextField(
            controller: _mpn,
            decoration: const InputDecoration(labelText: 'MPN', border: OutlineInputBorder(), isDense: true)),
        const SizedBox(height: 10),
        TextField(
            controller: _qty,
            keyboardType: TextInputType.number,
            decoration: const InputDecoration(labelText: 'Số lượng', border: OutlineInputBorder(), isDense: true)),
        if (lt.digikey.isNotEmpty || lt.order.isNotEmpty)
          Padding(
            padding: const EdgeInsets.only(top: 6),
            child: Text([if (lt.digikey.isNotEmpty) 'Digi-Key ${lt.digikey}', if (lt.order.isNotEmpty) 'Đơn ${lt.order}'].join(' · '),
                style: t.textTheme.bodySmall),
          ),
        const SizedBox(height: 14),
        FilledButton.icon(onPressed: _go, icon: const Icon(Icons.arrow_forward), label: const Text('Tiếp tục')),
        const SizedBox(height: 16),
        if (lt.tokens.isNotEmpty) ...[
          Text('Chạm để dùng làm MPN (giữ lâu: làm mã LCSC)', style: t.textTheme.labelMedium),
          const SizedBox(height: 6),
          Wrap(spacing: 6, runSpacing: 6, children: [
            for (final tok in lt.tokens)
              GestureDetector(
                onLongPress: () => setState(() => _lcsc.text = tok.toUpperCase()),
                child: ActionChip(label: Text(tok), onPressed: () => setState(() => _mpn.text = tok)),
              ),
          ]),
        ],
        const SizedBox(height: 8),
        TextButton(
            onPressed: () => setState(() => _showText = !_showText),
            child: Text(_showText ? 'Ẩn chữ đọc được' : 'Xem toàn bộ chữ đọc được')),
        if (_showText) SelectableText(widget.text, style: t.textTheme.bodySmall),
      ]),
    );
  }
}

/// Dùng ở màn hình Kho / Quét: chọn chụp ảnh hay lấy ảnh có sẵn.
Future<String?> ocrLabelMenu(BuildContext context) async {
  final src = await showModalBottomSheet<ImageSource>(
    context: context,
    builder: (c) => SafeArea(
      child: Column(mainAxisSize: MainAxisSize.min, children: [
        const ListTile(title: Text('Đọc chữ trên nhãn'), subtitle: Text('Khi nhãn không có QR / mã vạch')),
        ListTile(
            leading: const Icon(Icons.photo_camera),
            title: const Text('Chụp ảnh'),
            onTap: () => Navigator.pop(c, ImageSource.camera)),
        ListTile(
            leading: const Icon(Icons.photo_library),
            title: const Text('Chọn ảnh có sẵn'),
            onTap: () => Navigator.pop(c, ImageSource.gallery)),
      ]),
    ),
  );
  if (src == null || !context.mounted) return null;
  return ocrLabel(context, source: src);
}

