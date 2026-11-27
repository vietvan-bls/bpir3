import 'dart:async';
import 'dart:convert';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/services.dart';
import 'package:material_ui/material_ui.dart';

import '../api.dart';
import '../main.dart';
import '../util.dart';
import 'ocr.dart';
import 'scan.dart';

/// Kho linh kiện: dùng API /api/kho/* của server trên board (kho.py).

const supNames = {'lcsc': 'LCSC', 'digikey': 'Digi-Key', 'mouser': 'Mouser', 'taobao': 'Taobao', 'other': 'Khác'};

String partTitle(Map p) => [p['mpn'], p['value'], p['name']].firstWhere((x) => x != null && '$x'.isNotEmpty,
    orElse: () => '(không tên)').toString();

String partSub(Map p) => [
      if ('${p['mpn'] ?? ''}'.isNotEmpty && '${p['value'] ?? ''}'.isNotEmpty) p['value'],
      p['package'],
      p['manufacturer'],
      p['name'],
    ].where((x) => x != null && '$x'.isNotEmpty).join(' · ');

String fmtTime(num t) {
  final d = DateTime.fromMillisecondsSinceEpoch((t * 1000).round());
  String two(int v) => v.toString().padLeft(2, '0');
  return '${two(d.day)}/${two(d.month)} ${two(d.hour)}:${two(d.minute)}';
}

bool isLow(Map p) => p['low'] == true || (p['qty'] as num? ?? 0) <= 0;

Widget supChips(BuildContext context, List? sups) => Wrap(spacing: 4, runSpacing: 4, children: [
      for (final s in (sups ?? const []))
        ActionChip(
          visualDensity: VisualDensity.compact,
          label: Text('${supNames[s['supplier']] ?? s['supplier']}${'${s['sku'] ?? ''}'.isNotEmpty ? ' ${s['sku']}' : ''}',
              style: const TextStyle(fontSize: 12)),
          onPressed: () {
            final t = '${s['url'] ?? ''}'.isNotEmpty ? '${s['url']}' : '${s['sku']}';
            Clipboard.setData(ClipboardData(text: t));
            toast(context, 'Đã sao chép: $t');
          },
        ),
    ]);

// ============================================================ màn hình chính
class KhoScreen extends StatefulWidget {
  const KhoScreen({super.key});

  @override
  State<KhoScreen> createState() => _KhoScreenState();
}

class _KhoScreenState extends State<KhoScreen> {
  final _q = TextEditingController();
  final _scroll = ScrollController();
  List<Map> _items = [];
  int _total = 0;
  Map? _meta;
  bool _lowOnly = false, _loading = false;
  Object? _err;
  Timer? _debounce;

  Api get api => ApiScope.read(context);

  @override
  void initState() {
    super.initState();
    _reload();
    _scroll.addListener(() {
      if (_scroll.position.pixels > _scroll.position.maxScrollExtent - 300 && !_loading && _items.length < _total) {
        _load(more: true);
      }
    });
  }

  @override
  void dispose() {
    _debounce?.cancel();
    _scroll.dispose();
    super.dispose();
  }

  Future<void> _reload() async {
    await Future.wait([_load(), _loadMeta()]);
  }

  Future<void> _loadMeta() async {
    try {
      final m = await api.get('/api/kho/meta') as Map;
      if (mounted) setState(() => _meta = m);
    } catch (_) {}
  }

  Future<void> _load({bool more = false}) async {
    setState(() => _loading = true);
    try {
      final q = Uri(queryParameters: {
        'q': _q.text.trim(),
        if (_lowOnly) 'low': '1',
        'sort': _lowOnly ? 'qty' : 'updated',
        'limit': '60',
        'offset': '${more ? _items.length : 0}',
      }).query;
      final r = await api.get('/api/kho/parts?$q') as Map;
      if (!mounted) return;
      setState(() {
        final items = (r['items'] as List).cast<Map>();
        _items = more ? [..._items, ...items] : items;
        _total = r['total'] as int;
        _err = null;
      });
    } catch (e) {
      if (mounted) setState(() => _err = e);
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _open(Widget page) async {
    await Navigator.push(context, MaterialPageRoute(builder: (_) => page));
    _reload();
  }

  @override
  Widget build(BuildContext context) {
    final m = _meta;
    final t = Theme.of(context);
    final low = (m?['low'] as num?) ?? 0;
    return Scaffold(
      floatingActionButton: FloatingActionButton.extended(
        onPressed: () => _open(const ScanScreen()),
        icon: const Icon(Icons.qr_code_scanner),
        label: const Text('Quét'),
      ),
      body: Column(children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(12, 10, 12, 4),
          child: TextField(
            controller: _q,
            decoration: InputDecoration(
              prefixIcon: const Icon(Icons.search),
              hintText: 'MPN, giá trị, package, mã LCSC, vị trí…',
              isDense: true,
              border: const OutlineInputBorder(),
              suffixIcon: _q.text.isEmpty
                  ? null
                  : IconButton(
                      icon: const Icon(Icons.clear),
                      onPressed: () {
                        _q.clear();
                        _load();
                      }),
            ),
            onChanged: (_) {
              _debounce?.cancel();
              _debounce = Timer(const Duration(milliseconds: 300), _load);
            },
          ),
        ),
        SingleChildScrollView(
          scrollDirection: Axis.horizontal,
          padding: const EdgeInsets.symmetric(horizontal: 12),
          child: Row(children: [
            FilterChip(
              label: Text('Sắp hết${low > 0 ? ' ($low)' : ''}'),
              avatar: Icon(Icons.warning_amber, size: 18, color: low > 0 ? t.colorScheme.error : null),
              selected: _lowOnly,
              onSelected: (v) {
                setState(() => _lowOnly = v);
                _load();
              },
            ),
            const SizedBox(width: 8),
            ActionChip(
                avatar: const Icon(Icons.pin, size: 18),
                label: const Text('Nhập mã LCSC'),
                onPressed: () async {
                  if (await addByLcscCode(context) != null) _reload();
                }),
            const SizedBox(width: 8),
            ActionChip(
                avatar: const Icon(Icons.document_scanner_outlined, size: 18),
                label: const Text('Chụp nhãn'),
                onPressed: () async {
                  if (await ocrLabelMenu(context) != null) _reload();
                }),
            const SizedBox(width: 8),
            ActionChip(
                avatar: const Icon(Icons.add, size: 18),
                label: const Text('Thêm tay'),
                onPressed: () => _open(const PartEditScreen())),
            const SizedBox(width: 8),
            ActionChip(
                avatar: const Icon(Icons.list_alt, size: 18),
                label: Text('BOM${m != null ? ' (${m['boms']})' : ''}'),
                onPressed: () => _open(const BomListScreen())),
            const SizedBox(width: 8),
            ActionChip(
                avatar: const Icon(Icons.file_download, size: 18),
                label: const Text('Nhập đơn hàng'),
                onPressed: () async {
                  final ok = await importFile(context, 'stock');
                  if (ok) _reload();
                }),
          ]),
        ),
        if (m != null)
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 4, 16, 0),
            child: Text(
                '${m['n']} loại · ${m['pcs']} con · ≈ ${(m['value'] as num).toStringAsFixed(2)} USD${(m['out'] as num) > 0 ? ' · ${m['out']} hết hàng' : ''}',
                style: t.textTheme.bodySmall),
          ),
        Expanded(
          child: RefreshIndicator(
            onRefresh: _reload,
            child: _err != null && _items.isEmpty
                ? ListView(children: [ErrorText(_err!, onRetry: _reload)])
                : _items.isEmpty && !_loading
                    ? ListView(children: [
                        Padding(
                          padding: const EdgeInsets.all(32),
                          child: Text(
                              _q.text.isNotEmpty || _lowOnly
                                  ? 'Không có kết quả.'
                                  : 'Kho trống. Bấm + để thêm, hoặc “Nhập đơn hàng” để nhập file từ LCSC / Digi-Key / Mouser.',
                              textAlign: TextAlign.center),
                        )
                      ])
                    : ListView.separated(
                        controller: _scroll,
                        padding: const EdgeInsets.only(bottom: 88),
                        itemCount: _items.length + (_items.length < _total ? 1 : 0),
                        separatorBuilder: (_, _) => const Divider(height: 1),
                        itemBuilder: (context, i) {
                          if (i >= _items.length) {
                            return const Padding(
                                padding: EdgeInsets.all(16), child: Center(child: CircularProgressIndicator()));
                          }
                          final p = _items[i];
                          return ListTile(
                            title: Text(partTitle(p), style: const TextStyle(fontWeight: FontWeight.w600)),
                            subtitle: Text(
                                [partSub(p), if ('${p['location']}'.isNotEmpty) '📍 ${p['location']}'].join('\n'),
                                maxLines: 3,
                                overflow: TextOverflow.ellipsis),
                            trailing: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
                              Text('${p['qty']}',
                                  style: t.textTheme.titleLarge?.copyWith(
                                      fontWeight: FontWeight.w600, color: isLow(p) ? t.colorScheme.error : null)),
                              if (p['low'] == true) Text('sắp hết', style: TextStyle(fontSize: 11, color: t.colorScheme.error)),
                            ]),
                            onTap: () => _open(PartScreen(id: p['id'] as int)),
                          );
                        },
                      ),
          ),
        ),
      ]),
    );
  }
}

// ============================================================ chi tiết linh kiện
class PartScreen extends StatefulWidget {
  final int id;
  const PartScreen({required this.id, super.key});

  @override
  State<PartScreen> createState() => _PartScreenState();
}

class _PartScreenState extends State<PartScreen> {
  Map? _p;
  Object? _err;
  bool _busy = false;

  Api get api => ApiScope.read(context);

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final p = await api.get('/api/kho/part?id=${widget.id}') as Map;
      if (mounted) setState(() => _p = p);
    } catch (e) {
      if (mounted) setState(() => _err = e);
    }
  }

  Future<void> _stock({int? delta, int? set, String reason = ''}) async {
    setState(() => _busy = true);
    try {
      final p = await api.post('/api/kho/stock', {
        'id': widget.id,
        'delta': ?delta,
        'set': ?set,
        'reason': reason,
      }) as Map;
      if (!mounted) return;
      setState(() => _p = p);
      toast(context, 'Còn ${p['qty']}');
    } catch (e) {
      if (mounted) toast(context, 'Lỗi: $e');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _askNumber({required bool isSet}) async {
    final n = TextEditingController(text: isSet ? '${_p!['qty']}' : '');
    final reason = TextEditingController();
    var sign = -1;
    final r = await showDialog<bool>(
      context: context,
      builder: (c) => StatefulBuilder(
        builder: (c, setD) => AlertDialog(
          title: Text(isSet ? 'Kiểm kê: số lượng thực tế' : 'Nhập / xuất'),
          content: Column(mainAxisSize: MainAxisSize.min, children: [
            if (!isSet)
              SegmentedButton<int>(
                segments: const [
                  ButtonSegment(value: -1, label: Text('Xuất (−)')),
                  ButtonSegment(value: 1, label: Text('Nhập (+)')),
                ],
                selected: {sign},
                onSelectionChanged: (v) => setD(() => sign = v.first),
              ),
            TextField(
                controller: n,
                autofocus: true,
                keyboardType: TextInputType.number,
                decoration: const InputDecoration(labelText: 'Số lượng')),
            TextField(controller: reason, decoration: const InputDecoration(labelText: 'Lý do (không bắt buộc)')),
          ]),
          actions: [
            TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Hủy')),
            FilledButton(onPressed: () => Navigator.pop(c, true), child: const Text('Lưu')),
          ],
        ),
      ),
    );
    final v = int.tryParse(n.text.trim());
    if (r != true || v == null) return;
    isSet
        ? await _stock(set: v, reason: reason.text.isEmpty ? 'Kiểm kê' : reason.text)
        : await _stock(delta: sign * v.abs(), reason: reason.text);
  }

  Future<void> _delete() async {
    if (!await confirm(context, 'Xóa linh kiện?', 'Xóa “${partTitle(_p!)}” và lịch sử của nó khỏi kho.',
        ok: 'Xóa', danger: true)) {
      return;
    }
    try {
      await api.post('/api/kho/part/delete', {'id': widget.id});
      if (mounted) Navigator.pop(context);
    } catch (e) {
      if (mounted) toast(context, 'Lỗi: $e');
    }
  }

  @override
  Widget build(BuildContext context) {
    final p = _p;
    final t = Theme.of(context);
    return Scaffold(
      appBar: AppBar(
        title: Text(p == null ? 'Linh kiện' : partTitle(p)),
        actions: [
          if (p != null) ...[
            IconButton(
                icon: const Icon(Icons.edit),
                tooltip: 'Sửa',
                onPressed: () async {
                  await Navigator.push(context, MaterialPageRoute(builder: (_) => PartEditScreen(part: p)));
                  _load();
                }),
            PopupMenuButton<String>(
              onSelected: (v) async {
                if (v == 'delete') return _delete();
                try {
                  final r = await api.post('/api/kho/part/lcsc-fill', {'id': widget.id, 'overwrite': v == 'lcsc-all'}) as Map;
                  if (mounted) {
                    setState(() => _p = r);
                    toast(context, 'Đã cập nhật từ LCSC');
                  }
                } catch (e) {
                  if (mounted) toast(context, 'Lỗi: $e');
                }
              },
              itemBuilder: (_) => [
                if ((p['suppliers'] as List).any((s) => s['supplier'] == 'lcsc')) ...const [
                  PopupMenuItem(value: 'lcsc', child: Text('Điền thông tin còn trống từ LCSC')),
                  PopupMenuItem(value: 'lcsc-all', child: Text('Lấy lại toàn bộ thông tin từ LCSC')),
                ],
                const PopupMenuItem(value: 'delete', child: Text('Xóa linh kiện')),
              ],
            ),
          ],
        ],
      ),
      body: p == null
          ? (_err != null ? ErrorText(_err!, onRetry: _load) : const Center(child: CircularProgressIndicator()))
          : RefreshIndicator(
              onRefresh: _load,
              child: ListView(padding: const EdgeInsets.all(16), children: [
                if ('${p['image'] ?? ''}'.isNotEmpty)
                  Center(
                    child: ClipRRect(
                      borderRadius: BorderRadius.circular(12),
                      child: Image.network('${p['image']}', height: 140, fit: BoxFit.contain,
                          errorBuilder: (_, _, _) => const SizedBox.shrink()),
                    ),
                  ),
                if (partSub(p).isNotEmpty) Text(partSub(p), style: t.textTheme.bodyMedium),
                const SizedBox(height: 12),
                Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
                  Text('${p['qty']}',
                      style: t.textTheme.displayMedium?.copyWith(
                          fontWeight: FontWeight.w700, color: isLow(p) ? t.colorScheme.error : null)),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Padding(
                      padding: const EdgeInsets.only(bottom: 10),
                      child: Text(
                          (p['min_qty'] as num) > 0
                              ? 'con · cảnh báo khi ≤ ${p['min_qty']}${p['low'] == true ? '  ⚠️ sắp hết' : ''}'
                              : 'con · chưa đặt mức cảnh báo',
                          style: t.textTheme.bodySmall),
                    ),
                  ),
                ]),
                const SizedBox(height: 8),
                Wrap(spacing: 8, runSpacing: 8, children: [
                  for (final d in [-10, -1, 1, 10])
                    OutlinedButton(
                        onPressed: _busy ? null : () => _stock(delta: d), child: Text(d > 0 ? '+$d' : '$d')),
                  FilledButton.tonal(
                      onPressed: _busy ? null : () => _askNumber(isSet: false), child: const Text('Nhập / xuất…')),
                  FilledButton.tonal(
                      onPressed: _busy ? null : () => _askNumber(isSet: true), child: const Text('Kiểm kê…')),
                ]),
                const SizedBox(height: 16),
                Card(
                  child: Padding(
                    padding: const EdgeInsets.all(12),
                    child: Column(children: [
                      for (final (label, key) in [
                        ('Loại', 'category'),
                        ('Package', 'package'),
                        ('Giá trị', 'value'),
                        ('Vị trí', 'location'),
                        ('Hãng', 'manufacturer'),
                        ('Đơn giá', 'price'),
                        ('Ghi chú', 'notes'),
                        ('Datasheet', 'datasheet'),
                      ])
                        if (p[key] != null && '${p[key]}'.isNotEmpty)
                          Padding(
                            padding: const EdgeInsets.symmetric(vertical: 4),
                            child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                              SizedBox(width: 90, child: Text(label, style: t.textTheme.bodySmall)),
                              Expanded(
                                  child: SelectableText(key == 'price' ? '${p[key]} ${p['currency'] ?? 'USD'}' : '${p[key]}')),
                            ]),
                          ),
                    ]),
                  ),
                ),
                if ((p['suppliers'] as List).isNotEmpty) ...[
                  const SizedBox(height: 12),
                  Text('Mua ở (chạm để sao chép mã / link)', style: t.textTheme.labelMedium),
                  const SizedBox(height: 4),
                  supChips(context, p['suppliers'] as List),
                ],
                if ((p['boms'] as List).isNotEmpty) ...[
                  const SizedBox(height: 12),
                  Text('Dùng trong BOM', style: t.textTheme.labelMedium),
                  for (final b in p['boms'] as List)
                    ListTile(
                      dense: true,
                      contentPadding: EdgeInsets.zero,
                      leading: const Icon(Icons.list_alt),
                      title: Text('${b['name']}'),
                      trailing: Text('${b['qty']}/bo'),
                      onTap: () => Navigator.push(
                          context, MaterialPageRoute(builder: (_) => BomScreen(id: b['id'] as int))),
                    ),
                ],
                const SizedBox(height: 12),
                Text('Lịch sử', style: t.textTheme.titleSmall),
                if ((p['log'] as List).isEmpty) const Text('Chưa có'),
                for (final l in p['log'] as List)
                  ListTile(
                    dense: true,
                    contentPadding: EdgeInsets.zero,
                    leading: Text('${(l['delta'] as num) > 0 ? '+' : ''}${l['delta']}',
                        style: TextStyle(
                            fontWeight: FontWeight.w600,
                            color: (l['delta'] as num) > 0 ? Colors.green.shade700 : t.colorScheme.error)),
                    title: Text('${l['reason']}'),
                    subtitle: Text(fmtTime(l['ts'] as num)),
                    trailing: Text('→ ${l['qty_after']}'),
                  ),
              ]),
            ),
    );
  }
}

// ============================================================ thêm / sửa
class PartEditScreen extends StatefulWidget {
  final Map? part;
  const PartEditScreen({this.part, super.key});

  @override
  State<PartEditScreen> createState() => _PartEditScreenState();
}

class _PartEditScreenState extends State<PartEditScreen> {
  static const _fields = [
    ('mpn', 'MPN'),
    ('manufacturer', 'Hãng'),
    ('value', 'Giá trị (10k, 100nF…)'),
    ('package', 'Package (0603, SOT-23…)'),
    ('category', 'Loại (Điện trở, IC…)'),
    ('location', 'Vị trí (Hộp A / ngăn 3)'),
    ('qty', 'Số lượng'),
    ('min_qty', 'Cảnh báo khi ≤ (0 = không)'),
    ('price', 'Đơn giá (USD)'),
    ('name', 'Mô tả'),
    ('datasheet', 'Datasheet (link)'),
    ('image', 'Ảnh (link)'),
    ('notes', 'Ghi chú'),
  ];
  late final Map<String, TextEditingController> _c;
  final List<(String, TextEditingController, TextEditingController)> _sups = [];
  bool _saving = false;

  @override
  void initState() {
    super.initState();
    final p = widget.part ?? {};
    _c = {for (final (k, _) in _fields) k: TextEditingController(text: p[k] == null ? (k == 'qty' ? '0' : '') : '${p[k]}')};
    for (final s in (p['suppliers'] as List? ?? [
      {'supplier': 'lcsc'}
    ])) {
      _sups.add(('${s['supplier']}', TextEditingController(text: '${s['sku'] ?? ''}'),
          TextEditingController(text: '${s['url'] ?? ''}')));
    }
  }

  /// Điền các ô còn trống từ thông tin LCSC.
  Future<void> _fillLcsc(String raw) async {
    var code = raw.trim().toUpperCase();
    if (RegExp(r'^\d{2,10}$').hasMatch(code)) code = 'C$code';
    if (!RegExp(r'^C\d{2,10}$').hasMatch(code)) return toast(context, 'Nhập mã LCSC dạng C25804 trước');
    try {
      final info = await ApiScope.read(context).get('/api/kho/lcsc?code=$code') as Map;
      var n = 0;
      setState(() {
        for (final e in info.entries) {
          final c = _c[e.key];
          if (c != null && c.text.trim().isEmpty && e.value != null) {
            c.text = '${e.value}';
            n++;
          }
        }
        for (var i = 0; i < _sups.length; i++) {
          if (_sups[i].$1 == 'lcsc' && _sups[i].$2.text.trim().toUpperCase() != code && _sups[i].$2.text.trim() == raw.trim()) {
            _sups[i].$2.text = code;
          }
        }
      });
      if (mounted) toast(context, n > 0 ? 'Đã điền $n ô từ LCSC: ${info['mpn'] ?? ''}' : 'Các ô đã có sẵn, không điền gì thêm');
    } catch (e) {
      if (mounted) toast(context, 'Lỗi: $e');
    }
  }

  Future<void> _save() async {
    setState(() => _saving = true);
    final d = <String, Object?>{for (final e in _c.entries) e.key: e.value.text.trim()};
    if (d['min_qty'] == '') d['min_qty'] = 0;
    if (d['price'] == '') d['price'] = null;
    d['suppliers'] = [
      for (final (sup, sku, url) in _sups)
        if (sku.text.trim().isNotEmpty || url.text.trim().isNotEmpty)
          {'supplier': sup, 'sku': sku.text.trim(), 'url': url.text.trim()}
    ];
    if (widget.part != null) d['id'] = widget.part!['id'];
    try {
      final p = await ApiScope.read(context).post('/api/kho/part', d) as Map;
      if (!mounted) return;
      if (widget.part == null) {
        Navigator.pushReplacement(context, MaterialPageRoute(builder: (_) => PartScreen(id: p['id'] as int)));
      } else {
        Navigator.pop(context);
      }
    } catch (e) {
      if (mounted) toast(context, 'Lỗi: $e');
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(
          title: Text(widget.part == null ? 'Thêm linh kiện' : 'Sửa ${partTitle(widget.part!)}'),
          actions: [
            TextButton(onPressed: _saving ? null : _save, child: const Text('Lưu')),
          ],
        ),
        body: ListView(padding: const EdgeInsets.all(16), children: [
          for (final (k, label) in _fields)
            Padding(
              padding: const EdgeInsets.only(bottom: 10),
              child: TextField(
                controller: _c[k],
                keyboardType: const {'qty', 'min_qty'}.contains(k)
                    ? TextInputType.number
                    : k == 'price'
                        ? const TextInputType.numberWithOptions(decimal: true)
                        : TextInputType.text,
                decoration: InputDecoration(labelText: label, border: const OutlineInputBorder(), isDense: true),
              ),
            ),
          const SizedBox(height: 8),
          Text('Mã / link nhà cung cấp', style: Theme.of(context).textTheme.titleSmall),
          for (var i = 0; i < _sups.length; i++)
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: Row(children: [
                DropdownButton<String>(
                  value: _sups[i].$1,
                  items: [for (final e in supNames.entries) DropdownMenuItem(value: e.key, child: Text(e.value))],
                  onChanged: (v) => setState(() => _sups[i] = (v!, _sups[i].$2, _sups[i].$3)),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: TextField(
                      controller: _sups[i].$1 == 'taobao' ? _sups[i].$3 : _sups[i].$2,
                      decoration: InputDecoration(
                          isDense: true, hintText: _sups[i].$1 == 'taobao' ? 'link Taobao' : 'mã (C25804, …-ND)')),
                ),
                if (_sups[i].$1 == 'lcsc')
                  IconButton(
                      icon: const Icon(Icons.cloud_download_outlined),
                      tooltip: 'Lấy thông số từ LCSC',
                      onPressed: () => _fillLcsc(_sups[i].$2.text)),
                IconButton(icon: const Icon(Icons.close), onPressed: () => setState(() => _sups.removeAt(i))),
              ]),
            ),
          Align(
            alignment: Alignment.centerLeft,
            child: TextButton.icon(
              icon: const Icon(Icons.add),
              label: const Text('Thêm nơi mua'),
              onPressed: () => setState(() => _sups.add(('lcsc', TextEditingController(), TextEditingController()))),
            ),
          ),
          const SizedBox(height: 16),
          FilledButton(onPressed: _saving ? null : _save, child: const Text('Lưu')),
        ]),
      );
}

// ============================================================ nhập file (BOM / đơn hàng)
/// Chọn file trên điện thoại, xem cột đã nhận, rồi nhập. Trả về true nếu đã nhập.
Future<bool> importFile(BuildContext context, String kind, {void Function(int bomId)? onBom}) async {
  final api = ApiScope.read(context);
  final files = await FilePicker.pickFiles(type: FileType.custom, allowedExtensions: ['csv', 'xlsx', 'tsv', 'txt']);
  if (files.isEmpty || !context.mounted) return false;
  final f = files.first;
  Map pv;
  try {
    final bytes = await f.xFile.readAsBytes();
    pv = await api.uploadBytes(
        '/api/kho/preview?name=${Uri.encodeQueryComponent(f.name)}&kind=$kind', bytes) as Map;
  } catch (e) {
    if (context.mounted) toast(context, 'Lỗi đọc file: $e');
    return false;
  }
  if (!context.mounted) return false;
  final headers = (pv['headers'] as List).map((e) => '$e').toList();
  final fields = Map<String, String>.from(pv['fields'] as Map);
  // cột -> trường
  final colField = <int, String?>{for (final e in (pv['mapping'] as Map).entries) e.value as int: e.key as String};
  final name = TextEditingController(text: f.name.replaceAll(RegExp(r'\.[^.]+$'), ''));
  final boards = TextEditingController(text: '1');
  final loc = TextEditingController(), ref = TextEditingController();
  var mode = 'add';
  final sample = (pv['sample_raw'] as List).cast<List>();
  final ok = await Navigator.push<bool>(
    context,
    MaterialPageRoute(
      builder: (c) => StatefulBuilder(
        builder: (c, setS) => Scaffold(
          appBar: AppBar(title: Text(kind == 'bom' ? 'Thêm BOM' : 'Nhập hàng')),
          body: ListView(padding: const EdgeInsets.all(16), children: [
            Text('${f.name}: ${pv['rows']} dòng. Kiểm tra cột nào là gì (đã tự đoán), sửa nếu sai.'),
            const SizedBox(height: 8),
            for (var i = 0; i < headers.length; i++)
              Card(
                child: Padding(
                  padding: const EdgeInsets.fromLTRB(12, 6, 12, 6),
                  child: Row(children: [
                    Expanded(
                      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                        Text(headers[i], style: const TextStyle(fontWeight: FontWeight.w600)),
                        Text(sample.take(2).map((r) => i < r.length ? '${r[i]}' : '').join(' · '),
                            maxLines: 1, overflow: TextOverflow.ellipsis, style: Theme.of(c).textTheme.bodySmall),
                      ]),
                    ),
                    DropdownButton<String?>(
                      value: colField[i],
                      hint: const Text('bỏ qua'),
                      items: [
                        const DropdownMenuItem(value: null, child: Text('— bỏ qua —')),
                        for (final e in fields.entries) DropdownMenuItem(value: e.key, child: Text(e.value)),
                      ],
                      onChanged: (v) => setS(() {
                        colField.removeWhere((_, f) => f == v && v != null);
                        colField[i] = v;
                      }),
                    ),
                  ]),
                ),
              ),
            const SizedBox(height: 12),
            if (kind == 'bom') ...[
              TextField(controller: name, decoration: const InputDecoration(labelText: 'Tên BOM')),
              TextField(
                  controller: boards,
                  keyboardType: TextInputType.number,
                  decoration: const InputDecoration(labelText: 'Số bo')),
            ] else ...[
              SegmentedButton<String>(
                segments: const [
                  ButtonSegment(value: 'add', label: Text('Cộng thêm')),
                  ButtonSegment(value: 'set', label: Text('Đặt đúng SL (kiểm kê)')),
                ],
                selected: {mode},
                onSelectionChanged: (v) => setS(() => mode = v.first),
              ),
              TextField(controller: loc, decoration: const InputDecoration(labelText: 'Vị trí cho linh kiện mới')),
              TextField(controller: ref, decoration: const InputDecoration(labelText: 'Ghi chú lịch sử (mã đơn…)')),
            ],
            const SizedBox(height: 16),
            FilledButton(
                onPressed: () => Navigator.pop(c, true),
                child: Text(kind == 'bom' ? 'Tạo BOM' : 'Nhập vào kho')),
          ]),
        ),
      ),
    ),
  );
  if (ok != true || !context.mounted) return false;
  final mapping = {for (final e in colField.entries) if (e.value != null) e.value!: e.key};
  try {
    if (kind == 'bom') {
      final b = await api.post('/api/kho/bom/create', {
        'token': pv['token'],
        'mapping': mapping,
        'name': name.text,
        'boards': int.tryParse(boards.text) ?? 1,
      }) as Map;
      onBom?.call(b['id'] as int);
    } else {
      final r = await api.post('/api/kho/import',
          {'token': pv['token'], 'mapping': mapping, 'mode': mode, 'location': loc.text, 'ref': ref.text}) as Map;
      if (context.mounted) {
        toast(context, 'Xong: ${r['created']} mới, ${r['updated']} cập nhật${(r['skipped'] as num) > 0 ? ', bỏ qua ${r['skipped']}' : ''}');
      }
    }
    return true;
  } catch (e) {
    if (context.mounted) toast(context, 'Lỗi: $e');
    return false;
  }
}

// ============================================================ BOM
class BomListScreen extends StatefulWidget {
  const BomListScreen({super.key});

  @override
  State<BomListScreen> createState() => _BomListScreenState();
}

class _BomListScreenState extends State<BomListScreen> {
  List? _boms;
  Object? _err;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final r = await ApiScope.read(context).get('/api/kho/boms') as List;
      if (mounted) setState(() => _boms = r);
    } catch (e) {
      if (mounted) setState(() => _err = e);
    }
  }

  Future<void> _open(int id) async {
    await Navigator.push(context, MaterialPageRoute(builder: (_) => BomScreen(id: id)));
    _load();
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('BOM')),
        floatingActionButton: FloatingActionButton.extended(
          icon: const Icon(Icons.upload_file),
          label: const Text('Thêm BOM'),
          onPressed: () => importFile(context, 'bom', onBom: _open),
        ),
        body: _boms == null
            ? (_err != null ? ErrorText(_err!, onRetry: _load) : const Center(child: CircularProgressIndicator()))
            : RefreshIndicator(
                onRefresh: _load,
                child: ListView(padding: const EdgeInsets.only(bottom: 88), children: [
                  if (_boms!.isEmpty)
                    const Padding(
                        padding: EdgeInsets.all(32),
                        child: Text('Chưa có BOM. Bấm “Thêm BOM” và chọn file CSV / XLSX (KiCad, EasyEDA, Altium…).',
                            textAlign: TextAlign.center)),
                  for (final b in _boms!)
                    ListTile(
                      leading: const Icon(Icons.list_alt),
                      title: Text('${b['name']}'),
                      subtitle: Text('${b['lines']} dòng · ${fmtTime(b['created'] as num)}'),
                      trailing: (b['unmatched'] as num? ?? 0) > 0
                          ? Chip(
                              label: Text('${b['unmatched']} chưa khớp'),
                              visualDensity: VisualDensity.compact,
                              backgroundColor: Theme.of(context).colorScheme.errorContainer)
                          : const Icon(Icons.chevron_right),
                      onTap: () => _open(b['id'] as int),
                    ),
                ]),
              ),
      );
}

class BomScreen extends StatefulWidget {
  final int id;
  const BomScreen({required this.id, super.key});

  @override
  State<BomScreen> createState() => _BomScreenState();
}

class _BomScreenState extends State<BomScreen> {
  Map? _b;
  Object? _err;
  int? _boards;

  Api get api => ApiScope.read(context);

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final b = await api.get('/api/kho/bom?id=${widget.id}${_boards != null ? '&boards=$_boards' : ''}') as Map;
      if (mounted) {
        setState(() {
          _b = b;
          _boards = b['boards_view'] as int;
        });
      }
    } catch (e) {
      if (mounted) setState(() => _err = e);
    }
  }

  void _setBoards(int n) {
    setState(() => _boards = n.clamp(1, 100000));
    api.post('/api/kho/bom/update', {'id': widget.id, 'boards': _boards}).catchError((_) => null);
    _load();
  }

  Future<void> _act(String act) async {
    try {
      final r = await api.post('/api/kho/bom/$act', {'id': widget.id}) as Map;
      if (mounted) toast(context, act == 'add-missing' ? 'Đã thêm ${r['added']} linh kiện vào kho (SL 0)' : 'Đã khớp lại');
      _load();
    } catch (e) {
      if (mounted) toast(context, 'Lỗi: $e');
    }
  }

  Future<void> _consume() async {
    if (!await confirm(context, 'Lắp $_boards bo?', 'Trừ kho toàn bộ linh kiện của “${_b!['name']}” cho $_boards bo.',
        ok: 'Trừ kho')) {
      return;
    }
    try {
      await api.post('/api/kho/bom/consume', {'id': widget.id, 'boards': _boards});
      if (mounted) toast(context, 'Đã trừ kho cho $_boards bo');
      _load();
    } catch (e) {
      if (mounted) toast(context, 'Lỗi: $e');
    }
  }

  Future<void> _shareShortage(String supplier) async {
    try {
      final r = await httpGetText(api, '/api/kho/bom/shortage.csv?id=${widget.id}&boards=$_boards&supplier=$supplier');
      await Clipboard.setData(ClipboardData(text: r.replaceFirst('﻿', '')));
      if (mounted) {
        toast(context, supplier == 'lcsc'
            ? 'Đã sao chép danh sách cần mua (mã LCSC, số lượng): dán vào BOM Tool của LCSC'
            : 'Đã sao chép danh sách cần mua (CSV)');
      }
    } catch (e) {
      if (mounted) toast(context, 'Lỗi: $e');
    }
  }

  Future<void> _line(Map l) async {
    final action = await showModalBottomSheet<String>(
      context: context,
      builder: (c) => SafeArea(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          ListTile(
              title: Text('${l['designator']}'),
              subtitle: Text([l['mpn'], l['value'], l['package']].where((x) => '${x ?? ''}'.isNotEmpty).join(' · '))),
          const Divider(height: 1),
          ListTile(leading: const Icon(Icons.search), title: const Text('Chọn linh kiện khác trong kho'), onTap: () => Navigator.pop(c, 'pick')),
          if (l['part_id'] != null)
            ListTile(leading: const Icon(Icons.inventory_2), title: const Text('Xem linh kiện'), onTap: () => Navigator.pop(c, 'open')),
          if (l['part_id'] != null)
            ListTile(leading: const Icon(Icons.link_off), title: const Text('Bỏ khớp'), onTap: () => Navigator.pop(c, 'unlink')),
          ListTile(
              leading: const Icon(Icons.block),
              title: Text(l['dnp'] == 1 ? 'Lắp lại dòng này' : 'Không lắp (DNP)'),
              onTap: () => Navigator.pop(c, 'dnp')),
        ]),
      ),
    );
    if (!mounted || action == null) return;
    try {
      switch (action) {
        case 'open':
          await Navigator.push(context, MaterialPageRoute(builder: (_) => PartScreen(id: l['part_id'] as int)));
        case 'unlink':
          await api.post('/api/kho/bom/line', {'line_id': l['id'], 'part_id': 0});
        case 'dnp':
          await api.post('/api/kho/bom/line', {'line_id': l['id'], 'dnp': l['dnp'] == 1 ? 0 : 1});
        case 'pick':
          final pid = await Navigator.push<int>(
              context, MaterialPageRoute(builder: (_) => PartPickerScreen(initial: '${l['mpn'] ?? l['value'] ?? ''}')));
          if (pid != null) await api.post('/api/kho/bom/line', {'line_id': l['id'], 'part_id': pid});
      }
      _load();
    } catch (e) {
      if (mounted) toast(context, 'Lỗi: $e');
    }
  }

  @override
  Widget build(BuildContext context) {
    final b = _b;
    final t = Theme.of(context);
    if (b == null) {
      return Scaffold(
          appBar: AppBar(title: const Text('BOM')),
          body: _err != null ? ErrorText(_err!, onRetry: _load) : const Center(child: CircularProgressIndicator()));
    }
    final s = b['summary'] as Map;
    final canBuild = (s['short'] as num) == 0 && (s['missing'] as num) == 0;
    Color statusColor(String st) => switch (st) {
          'ok' => Colors.green,
          'short' => Colors.orange,
          'missing' => t.colorScheme.error,
          _ => t.colorScheme.outline,
        };
    return Scaffold(
      appBar: AppBar(
        title: Text('${b['name']}'),
        actions: [
          PopupMenuButton<String>(
            onSelected: (v) async {
              if (v == 'delete') {
                if (!await confirm(context, 'Xóa BOM?', 'Không ảnh hưởng số lượng trong kho.', ok: 'Xóa', danger: true)) return;
                await api.post('/api/kho/bom/delete', {'id': widget.id});
                if (context.mounted) Navigator.pop(context);
              } else if (v.startsWith('csv-')) {
                _shareShortage(v.substring(4));
              } else {
                _act(v);
              }
            },
            itemBuilder: (_) => const [
              PopupMenuItem(value: 'rematch', child: Text('Khớp lại với kho')),
              PopupMenuItem(value: 'add-missing', child: Text('Thêm dòng thiếu vào kho (SL 0)')),
              PopupMenuItem(value: 'csv-lcsc', child: Text('Sao chép cần mua (LCSC)')),
              PopupMenuItem(value: 'csv-all', child: Text('Sao chép cần mua (đủ cột)')),
              PopupMenuItem(value: 'delete', child: Text('Xóa BOM')),
            ],
          ),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: _load,
        child: ListView(padding: const EdgeInsets.only(bottom: 24), children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 12, 16, 4),
            child: Row(children: [
              const Text('Số bo'),
              IconButton(icon: const Icon(Icons.remove_circle_outline), onPressed: () => _setBoards((_boards ?? 1) - 1)),
              InkWell(
                onTap: () async {
                  final c = TextEditingController(text: '$_boards');
                  final v = await showDialog<String>(
                      context: context,
                      builder: (d) => AlertDialog(
                            title: const Text('Số bo cần làm'),
                            content: TextField(controller: c, autofocus: true, keyboardType: TextInputType.number),
                            actions: [FilledButton(onPressed: () => Navigator.pop(d, c.text), child: const Text('OK'))],
                          ));
                  final n = int.tryParse(v ?? '');
                  if (n != null) _setBoards(n);
                },
                child: Text('$_boards', style: t.textTheme.headlineSmall),
              ),
              IconButton(icon: const Icon(Icons.add_circle_outline), onPressed: () => _setBoards((_boards ?? 1) + 1)),
              const Spacer(),
              FilledButton.icon(
                  onPressed: canBuild ? _consume : null, icon: const Icon(Icons.build), label: const Text('Lắp bo')),
            ]),
          ),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16),
            child: Wrap(spacing: 6, runSpacing: 6, children: [
              Chip(label: Text('${s['ok']} đủ'), backgroundColor: Colors.green.withValues(alpha: .15)),
              if ((s['short'] as num) > 0) Chip(label: Text('${s['short']} thiếu'), backgroundColor: Colors.orange.withValues(alpha: .18)),
              if ((s['missing'] as num) > 0)
                Chip(label: Text('${s['missing']} chưa có trong kho'), backgroundColor: t.colorScheme.errorContainer),
              if ((s['dnp'] as num) > 0) Chip(label: Text('${s['dnp']} DNP')),
              if ((s['missing'] as num) == 0) Chip(label: Text('làm được tối đa ${s['buildable']} bo')),
              if ((s['cost_short'] as num) > 0) Chip(label: Text('mua thêm ≈ ${s['cost_short']} USD')),
            ]),
          ),
          const SizedBox(height: 8),
          for (final l in (b['lines'] as List).cast<Map>())
            Container(
              decoration: BoxDecoration(border: Border(left: BorderSide(color: statusColor('${l['status']}'), width: 4))),
              child: Opacity(
                opacity: l['status'] == 'dnp' ? .5 : 1,
                child: ListTile(
                  onTap: () => _line(l),
                  title: Text('${l['designator'] ?? ''}'.isEmpty ? 'Dòng ${l['line']}' : '${l['designator']}',
                      maxLines: 2, overflow: TextOverflow.ellipsis),
                  subtitle: Text(
                    [
                      [l['mpn'], l['value'], l['package']].where((x) => '${x ?? ''}'.isNotEmpty).join(' · '),
                      l['part_id'] != null
                          ? '→ ${partTitle({'mpn': l['p_mpn'], 'value': l['p_value'], 'name': l['p_name']})}${'${l['p_location'] ?? ''}'.isNotEmpty ? ' · 📍 ${l['p_location']}' : ''}'
                          : '→ chưa có trong kho',
                    ].join('\n'),
                    maxLines: 3,
                  ),
                  trailing: Column(mainAxisAlignment: MainAxisAlignment.center, crossAxisAlignment: CrossAxisAlignment.end, children: [
                    Text('cần ${l['need']} · có ${l['have'] ?? 0}', style: t.textTheme.bodySmall),
                    if ((l['short'] as num? ?? 0) > 0)
                      Text('thiếu ${l['short']}',
                          style: TextStyle(color: t.colorScheme.error, fontWeight: FontWeight.w600)),
                  ]),
                ),
              ),
            ),
        ]),
      ),
    );
  }
}

/// Đọc nội dung chữ (CSV) từ server.
Future<String> httpGetText(Api api, String path) async {
  final (c, s) = await api.openStream(path);
  try {
    return await s.transform(const Utf8Decoder(allowMalformed: true)).join();
  } finally {
    c.close();
  }
}

class PartPickerScreen extends StatefulWidget {
  final String initial;
  const PartPickerScreen({this.initial = '', super.key});

  @override
  State<PartPickerScreen> createState() => _PartPickerScreenState();
}

class _PartPickerScreenState extends State<PartPickerScreen> {
  late final _q = TextEditingController(text: widget.initial);
  List _items = [];
  Timer? _deb;

  @override
  void initState() {
    super.initState();
    _search();
  }

  Future<void> _search() async {
    try {
      final r = await ApiScope.read(context).get('/api/kho/parts?limit=50&q=${Uri.encodeQueryComponent(_q.text.trim())}') as Map;
      if (mounted) setState(() => _items = r['items'] as List);
    } catch (_) {}
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(
          title: TextField(
            controller: _q,
            autofocus: true,
            decoration: const InputDecoration(hintText: 'Tìm linh kiện…', border: InputBorder.none),
            onChanged: (_) {
              _deb?.cancel();
              _deb = Timer(const Duration(milliseconds: 300), _search);
            },
          ),
        ),
        body: ListView(children: [
          for (final p in _items)
            ListTile(
              title: Text(partTitle(p as Map)),
              subtitle: Text([partSub(p), p['location']].where((x) => '${x ?? ''}'.isNotEmpty).join(' · ')),
              trailing: Text('${p['qty']}'),
              onTap: () => Navigator.pop(context, p['id'] as int),
            ),
        ]),
      );
}
