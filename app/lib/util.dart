import 'package:material_ui/material_ui.dart';

String fmtDur(num? secs) {
  if (secs == null) return '';
  final s = secs.floor();
  final d = s ~/ 86400, h = s % 86400 ~/ 3600, m = s % 3600 ~/ 60;
  if (d > 0) return '${d}d ${h}h ${m}m';
  if (h > 0) return '${h}h ${m}m';
  return '${m}m ${s % 60}s';
}

String fmtBytes(num? b) {
  if (b == null || b == 0) return '0';
  const u = ['B', 'KB', 'MB', 'GB', 'TB'];
  var v = b.toDouble();
  var i = 0;
  while (v >= 1024 && i < u.length - 1) {
    v /= 1024;
    i++;
  }
  return '${v >= 100 || i == 0 ? v.toStringAsFixed(0) : v.toStringAsFixed(1)} ${u[i]}';
}

String fmtSec(num? secs) {
  final s = (secs ?? 0).floor();
  return '${s ~/ 60}:${(s % 60).toString().padLeft(2, '0')}';
}

String fmtMin(num m) => m >= 60 ? '${m ~/ 60}h ${m % 60}m' : '$m phút';

String fmtClock(num unix) {
  final t = DateTime.fromMillisecondsSinceEpoch((unix * 1000).round());
  return '${t.hour.toString().padLeft(2, '0')}:${t.minute.toString().padLeft(2, '0')}';
}

void toast(BuildContext context, String msg) {
  ScaffoldMessenger.of(context)
    ..hideCurrentSnackBar()
    ..showSnackBar(SnackBar(content: Text(msg), duration: const Duration(seconds: 3)));
}

Future<bool> confirm(BuildContext context, String title, String body,
    {String ok = 'Đồng ý', bool danger = false}) async {
  final r = await showDialog<bool>(
    context: context,
    builder: (c) => AlertDialog(
      title: Text(title),
      content: Text(body),
      actions: [
        TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Hủy')),
        FilledButton(
          style: danger ? FilledButton.styleFrom(backgroundColor: Colors.red.shade700) : null,
          onPressed: () => Navigator.pop(c, true),
          child: Text(ok),
        ),
      ],
    ),
  );
  return r == true;
}

/// Vạch sóng Wi-Fi (0–4 vạch) theo dBm.
class SignalBars extends StatelessWidget {
  final num? dbm;
  const SignalBars(this.dbm, {super.key});

  @override
  Widget build(BuildContext context) {
    final s = dbm;
    final n = s == null ? 0 : s >= -55 ? 4 : s >= -65 ? 3 : s >= -75 ? 2 : 1;
    final on = Theme.of(context).colorScheme.primary;
    final off = Theme.of(context).colorScheme.outlineVariant;
    return Row(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.end,
      children: [
        for (var i = 0; i < 4; i++)
          Container(
            width: 4,
            height: [6.0, 9.0, 12.0, 15.0][i],
            margin: const EdgeInsets.only(right: 2),
            decoration: BoxDecoration(
                color: i < n ? on : off, borderRadius: BorderRadius.circular(1)),
          ),
      ],
    );
  }
}

/// Thẻ chỉ số nhỏ (nhãn + giá trị).
class StatCard extends StatelessWidget {
  final String label;
  final String value;
  final IconData? icon;
  const StatCard(this.label, this.value, {this.icon, super.key});

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context);
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Row(children: [
              if (icon != null) ...[
                Icon(icon, size: 16, color: t.colorScheme.onSurfaceVariant),
                const SizedBox(width: 6),
              ],
              Expanded(
                child: Text(label,
                    style: t.textTheme.labelMedium
                        ?.copyWith(color: t.colorScheme.onSurfaceVariant),
                    overflow: TextOverflow.ellipsis),
              ),
            ]),
            const SizedBox(height: 6),
            Text(value,
                style: t.textTheme.titleLarge?.copyWith(fontWeight: FontWeight.w600),
                maxLines: 1,
                overflow: TextOverflow.ellipsis),
          ],
        ),
      ),
    );
  }
}

/// Dòng trạng thái công việc chạy nền trên board (job.state: running/ok/failed).
class JobBanner extends StatelessWidget {
  final Map? job;
  const JobBanner(this.job, {super.key});

  @override
  Widget build(BuildContext context) {
    final j = job ?? {};
    final state = j['state'];
    final msg = '${j['msg'] ?? ''}';
    if (state == null || state == 'idle' || msg.isEmpty) return const SizedBox.shrink();
    final (color, icon) = switch (state) {
      'running' => (Colors.blue, Icons.hourglass_top),
      'ok' => (Colors.green, Icons.check_circle),
      _ => (Colors.red, Icons.error),
    };
    return Container(
      margin: const EdgeInsets.only(top: 8),
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
          color: color.withValues(alpha: .12), borderRadius: BorderRadius.circular(8)),
      child: Row(children: [
        Icon(icon, color: color, size: 18),
        const SizedBox(width: 8),
        Expanded(child: Text(msg)),
      ]),
    );
  }
}

class ErrorText extends StatelessWidget {
  final Object error;
  final VoidCallback? onRetry;
  const ErrorText(this.error, {this.onRetry, super.key});

  @override
  Widget build(BuildContext context) => Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            const Icon(Icons.cloud_off, size: 40),
            const SizedBox(height: 8),
            Text('Lỗi: $error', textAlign: TextAlign.center),
            if (onRetry != null)
              TextButton(onPressed: onRetry, child: const Text('Thử lại')),
          ]),
        ),
      );
}
