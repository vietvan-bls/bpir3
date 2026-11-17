import 'dart:async';
import 'dart:math';

import 'package:file_picker/file_picker.dart';
import 'package:just_audio/just_audio.dart';
import 'package:material_ui/material_ui.dart';

import '../api.dart';
import '../main.dart';
import '../util.dart';

/// Trình phát trên điện thoại, sống ngoài widget để nhạc không tắt khi đổi tab.
class PhonePlayer {
  static final PhonePlayer i = PhonePlayer._();
  PhonePlayer._() {
    player.processingStateStream.listen((s) {
      if (s == ProcessingState.completed) next(auto: true);
    });
  }

  final player = AudioPlayer();
  List<Map> queue = [];
  int pos = -1;
  bool shuffle = false, repeat = false;
  final changed = StreamController<void>.broadcast();
  Api? _api;

  Map? get current => pos >= 0 && pos < queue.length ? queue[pos] : null;

  Future<void> playFrom(Api api, List<Map> list, int index) async {
    _api = api;
    queue = List.of(list);
    if (shuffle) {
      final first = queue.removeAt(index);
      queue.shuffle(Random());
      queue.insert(0, first);
      index = 0;
    }
    await play(index);
  }

  Future<void> play(int index) async {
    if (index < 0 || index >= queue.length || _api == null) return;
    pos = index;
    changed.add(null);
    final id = Uri.encodeQueryComponent('${queue[index]['id']}');
    try {
      await player.setAudioSource(
          AudioSource.uri(Uri.parse(_api!.url('/music/file?id=$id')), headers: _api!.mediaHeaders));
      unawaited(player.play());
    } catch (_) {
      if (queue.length > 1) Future.delayed(const Duration(milliseconds: 1500), () => next(auto: true));
    }
  }

  void next({bool auto = false}) {
    if (pos + 1 < queue.length) {
      play(pos + 1);
    } else if (repeat || !auto) {
      play(0);
    }
  }

  void prev() {
    if (player.position.inSeconds > 3) {
      player.seek(Duration.zero);
    } else {
      play(pos > 0 ? pos - 1 : queue.length - 1);
    }
  }
}

class MusicScreen extends StatefulWidget {
  const MusicScreen({super.key});

  @override
  State<MusicScreen> createState() => _MusicScreenState();
}

class _MusicScreenState extends State<MusicScreen> {
  static bool _boardOut = false; // nhớ lựa chọn trong phiên
  List<Map> _tracks = [];
  Map? _info;
  Object? _err;
  String _q = '';
  Map? _sp; // trạng thái loa board
  Timer? _spTimer, _scanTimer;
  String? _upMsg;
  bool _upFailed = false, _uploading = false;
  double? _seekDrag, _volDrag;
  final _pp = PhonePlayer.i;
  StreamSubscription? _ppSub;

  Api get api => ApiScope.read(context);

  @override
  void initState() {
    super.initState();
    _load();
    if (_boardOut) _spPoll();
    _ppSub = _pp.changed.stream.listen((_) {
      if (mounted) setState(() {});
    });
  }

  @override
  void dispose() {
    _spTimer?.cancel();
    _scanTimer?.cancel();
    _ppSub?.cancel();
    super.dispose();
  }

  Future<void> _load() async {
    try {
      final j = await api.get('/api/music') as Map;
      if (!mounted) return;
      setState(() {
        _tracks = (j['tracks'] as List).cast<Map>();
        _info = j;
        _err = null;
      });
      if ((j['scanning'] ?? 0) != 0) _scanTimer = Timer(const Duration(seconds: 2), _load);
    } catch (e) {
      if (mounted) setState(() => _err = e);
    }
  }

  List<Map> get _filtered {
    final k = _q.trim().toLowerCase();
    if (k.isEmpty) return _tracks;
    return _tracks
        .where((t) => [t['title'], t['artist'], t['album'], t['folder']].join(' ').toLowerCase().contains(k))
        .toList();
  }

  // ---- loa board
  Future<void> _spPoll() async {
    _spTimer?.cancel();
    try {
      final s = await api.get('/api/speaker') as Map;
      if (mounted) setState(() => _sp = s);
    } catch (_) {}
    if (mounted && _boardOut) _spTimer = Timer(const Duration(seconds: 1), _spPoll);
  }

  Future<void> _spCmd(Map<String, Object?> body) async {
    try {
      final s = await api.post('/api/speaker', body) as Map;
      if (mounted) setState(() => _sp = s);
    } catch (e) {
      if (mounted) toast(context, 'Loa board: $e');
    }
  }

  void _setOut(bool board) {
    setState(() => _boardOut = board);
    if (board) {
      _pp.player.pause();
      _spPoll();
    } else {
      _spTimer?.cancel();
    }
  }

  String? get _curId => '${_boardOut ? _sp?['track']?['id'] : _pp.current?['id']}';

  void _playFrom(int i) {
    final list = _filtered;
    if (_boardOut) {
      _spCmd({'action': 'play', 'ids': list.map((t) => t['id']).toList(), 'index': i});
    } else {
      _pp.playFrom(api, list, i);
    }
  }

  Future<void> _delete(Map t) async {
    if (!await confirm(context, 'Xóa bài?', 'Xóa "${t['title']}" khỏi board? Không khôi phục được.',
        ok: 'Xóa', danger: true)) {
      return;
    }
    try {
      await api.post('/api/music/delete', {'id': t['id']});
      if (mounted) toast(context, 'Đã xóa');
      _load();
    } catch (e) {
      if (mounted) toast(context, 'Lỗi: $e');
    }
  }

  Future<void> _upload() async {
    final files = await FilePicker.pickFiles(type: FileType.audio);
    if (files.isEmpty) return;
    setState(() {
      _uploading = true;
      _upFailed = false;
    });
    var ok = 0;
    final errs = <String>[];
    for (var i = 0; i < files.length; i++) {
      final f = files[i];
      try {
        await api.upload(f.name, f.xFile.openRead(), await f.xFile.length(), (p) {
          if (mounted) setState(() => _upMsg = 'Đang tải lên ${i + 1}/${files.length}: ${f.name} — ${(p * 100).round()}%');
        });
        ok++;
      } catch (e) {
        errs.add('${f.name}: $e');
      }
    }
    if (!mounted) return;
    setState(() {
      _uploading = false;
      _upFailed = errs.isNotEmpty;
      _upMsg = 'Đã tải lên $ok/${files.length} bài.${errs.isEmpty ? '' : ' Lỗi: ${errs.join('; ')}'}';
    });
    _load();
  }

  Widget _cover(Map t, {double size = 44}) => ClipRRect(
        borderRadius: BorderRadius.circular(6),
        child: SizedBox.square(
          dimension: size,
          child: t['cover'] == true
              ? Image.network(api.url('/music/cover?id=${Uri.encodeQueryComponent('${t['id']}')}'),
                  headers: api.mediaHeaders, fit: BoxFit.cover, errorBuilder: (_, _, _) => const Icon(Icons.music_note))
              : ColoredBox(
                  color: Theme.of(context).colorScheme.surfaceContainerHighest,
                  child: const Icon(Icons.music_note)),
        ),
      );

  @override
  Widget build(BuildContext context) {
    final list = _filtered;
    final info = _info;
    return Column(children: [
      Expanded(
        child: RefreshIndicator(
          onRefresh: _load,
          child: ListView(padding: const EdgeInsets.fromLTRB(16, 12, 16, 16), children: [
            SegmentedButton<bool>(
              segments: const [
                ButtonSegment(value: false, icon: Icon(Icons.smartphone), label: Text('Phát trên máy này')),
                ButtonSegment(value: true, icon: Icon(Icons.speaker), label: Text('Loa board')),
              ],
              selected: {_boardOut},
              onSelectionChanged: (s) => _setOut(s.first),
            ),
            if (_boardOut && _sp != null)
              Padding(
                padding: const EdgeInsets.only(top: 6),
                child: Text(
                    (_sp!['available'] == true ? '${_sp!['card']}' : '⚠️ chưa thấy loa USB') +
                        (_sp!['error'] != null ? ' · ${_sp!['error']}' : ''),
                    style: Theme.of(context).textTheme.bodySmall),
              ),
            const SizedBox(height: 12),
            Row(children: [
              Expanded(
                child: TextField(
                  decoration: const InputDecoration(
                      prefixIcon: Icon(Icons.search), hintText: 'Tìm bài, ca sĩ, album…', isDense: true, border: OutlineInputBorder()),
                  onChanged: (v) => setState(() => _q = v),
                ),
              ),
              const SizedBox(width: 8),
              FilledButton.icon(
                  onPressed: _uploading ? null : _upload, icon: const Icon(Icons.upload), label: const Text('Tải lên')),
            ]),
            if (info != null)
              Padding(
                padding: const EdgeInsets.only(top: 6),
                child: Text(
                    '${_tracks.length} bài · ${fmtBytes(info['used'] as num?)} · còn trống ${fmtBytes(info['free'] as num?)}'
                    '${(info['scanning'] ?? 0) != 0 ? ' · đang đọc thông tin ${info['scanning']} bài…' : ''}',
                    style: Theme.of(context).textTheme.bodySmall),
              ),
            if (_upMsg != null) JobBanner({'state': _uploading ? 'running' : _upFailed ? 'failed' : 'ok', 'msg': _upMsg}),
            const SizedBox(height: 8),
            if (_err != null) ErrorText(_err!, onRetry: _load),
            if (_err == null && list.isEmpty)
              Padding(
                padding: const EdgeInsets.all(16),
                child: Text(_tracks.isEmpty ? 'Chưa có bài nào. Bấm “Tải lên” để thêm.' : 'Không có bài nào khớp.'),
              ),
            for (var i = 0; i < list.length; i++)
              ListTile(
                contentPadding: EdgeInsets.zero,
                selected: '${list[i]['id']}' == _curId,
                leading: _cover(list[i]),
                title: Text('${list[i]['title']}', maxLines: 1, overflow: TextOverflow.ellipsis),
                subtitle: Text(
                    [list[i]['artist'], list[i]['album']].where((x) => x != null && '$x'.isNotEmpty).join(' · ').ifEmpty('${list[i]['folder'] ?? ''}'),
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis),
                trailing: Row(mainAxisSize: MainAxisSize.min, children: [
                  if (list[i]['dur'] != null) Text(fmtSec(list[i]['dur'] as num)),
                  IconButton(icon: const Icon(Icons.delete_outline), onPressed: () => _delete(list[i])),
                ]),
                onTap: () => _playFrom(i),
              ),
          ]),
        ),
      ),
      _boardOut ? _boardBar() : _phoneBar(),
    ]);
  }

  // ---- thanh điều khiển
  Widget _bar({required Map? track, required bool playing, required double pos, required double dur,
      required VoidCallback onToggle, required VoidCallback onPrev, required VoidCallback onNext,
      required ValueChanged<double> onSeek, required bool shuffle, required bool repeat,
      required VoidCallback onShuffle, required VoidCallback onRepeat, Widget? extra}) {
    if (track == null) return const SizedBox.shrink();
    final t = Theme.of(context);
    final shown = _seekDrag ?? (dur > 0 ? (pos / dur).clamp(0.0, 1.0) : 0.0);
    return Material(
      elevation: 3,
      color: t.colorScheme.surfaceContainer,
      child: SafeArea(
        top: false,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(12, 8, 12, 4),
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            Row(children: [
              _cover(track, size: 40),
              const SizedBox(width: 10),
              Expanded(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text('${track['title']}', maxLines: 1, overflow: TextOverflow.ellipsis, style: t.textTheme.titleSmall),
                  Text('${track['artist'] ?? ''}', maxLines: 1, overflow: TextOverflow.ellipsis, style: t.textTheme.bodySmall),
                ]),
              ),
              IconButton(icon: Icon(Icons.shuffle, color: shuffle ? t.colorScheme.primary : null), onPressed: onShuffle),
              IconButton(icon: const Icon(Icons.skip_previous), onPressed: onPrev),
              IconButton.filled(icon: Icon(playing ? Icons.pause : Icons.play_arrow), onPressed: onToggle),
              IconButton(icon: const Icon(Icons.skip_next), onPressed: onNext),
              IconButton(icon: Icon(Icons.repeat, color: repeat ? t.colorScheme.primary : null), onPressed: onRepeat),
            ]),
            Row(children: [
              Text(fmtSec(pos), style: t.textTheme.labelSmall),
              Expanded(
                child: Slider(
                  value: shown,
                  onChanged: dur > 0 ? (v) => setState(() => _seekDrag = v) : null,
                  onChangeEnd: (v) {
                    setState(() => _seekDrag = null);
                    onSeek(v * dur);
                  },
                ),
              ),
              Text(fmtSec(dur), style: t.textTheme.labelSmall),
            ]),
            ?extra,
          ]),
        ),
      ),
    );
  }

  Widget _phoneBar() => StreamBuilder(
        stream: _pp.player.positionStream,
        builder: (context, _) {
          final p = _pp.player;
          return _bar(
            track: _pp.current,
            playing: p.playing,
            pos: p.position.inMilliseconds / 1000,
            dur: (p.duration?.inMilliseconds ?? 0) / 1000,
            onToggle: () => p.playing ? p.pause() : p.play(),
            onPrev: _pp.prev,
            onNext: _pp.next,
            onSeek: (s) => p.seek(Duration(milliseconds: (s * 1000).round())),
            shuffle: _pp.shuffle,
            repeat: _pp.repeat,
            onShuffle: () => setState(() => _pp.shuffle = !_pp.shuffle),
            onRepeat: () => setState(() => _pp.repeat = !_pp.repeat),
          );
        },
      );

  Widget _boardBar() {
    final s = _sp;
    if (s == null) return const SizedBox.shrink();
    final vol = _volDrag ?? ((s['volume'] as num?)?.toDouble() ?? 0);
    return _bar(
      track: s['track'] as Map?,
      playing: s['state'] == 'playing',
      pos: (s['pos'] as num?)?.toDouble() ?? 0,
      dur: (s['dur'] as num?)?.toDouble() ?? 0,
      onToggle: () => _spCmd({'action': 'toggle'}),
      onPrev: () => _spCmd({'action': 'prev'}),
      onNext: () => _spCmd({'action': 'next'}),
      onSeek: (p) => _spCmd({'action': 'seek', 'pos': p}),
      shuffle: s['shuffle'] == true,
      repeat: s['repeat'] == true,
      onShuffle: () => _spCmd({'action': 'shuffle', 'on': s['shuffle'] != true}),
      onRepeat: () => _spCmd({'action': 'repeat', 'on': s['repeat'] != true}),
      extra: Row(children: [
        const Icon(Icons.volume_up, size: 18),
        Expanded(
          child: Slider(
            value: vol.clamp(0, 200),
            max: 200,
            divisions: 40,
            onChanged: (v) => setState(() => _volDrag = v),
            onChangeEnd: (v) {
              setState(() => _volDrag = null);
              _spCmd({'action': 'volume', 'volume': v.round()});
            },
          ),
        ),
        Text('${vol.round()}%', style: TextStyle(color: vol > 100 ? Colors.orange : null)),
      ]),
    );
  }
}

extension on String {
  String ifEmpty(String other) => isEmpty ? other : this;
}
