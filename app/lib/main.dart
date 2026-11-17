import 'package:material_ui/material_ui.dart';

import 'api.dart';
import 'screens/connect.dart';
import 'screens/home.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final api = Api();
  await api.load();
  runApp(BpiApp(api: api));
}

/// Cho mọi màn hình truy cập [Api] mà không cần thư viện state management.
class ApiScope extends InheritedNotifier<Api> {
  const ApiScope({required Api api, required super.child, super.key}) : super(notifier: api);

  static Api of(BuildContext context) =>
      context.dependOnInheritedWidgetOfExactType<ApiScope>()!.notifier!;
  static Api read(BuildContext context) =>
      context.getInheritedWidgetOfExactType<ApiScope>()!.notifier!;
}

class BpiApp extends StatelessWidget {
  final Api api;
  const BpiApp({required this.api, super.key});

  @override
  Widget build(BuildContext context) {
    ThemeData theme(Brightness b) => ThemeData(
          colorScheme: ColorScheme.fromSeed(seedColor: const Color(0xFF2563EB), brightness: b),
          useMaterial3: true,
          cardTheme: const CardThemeData(margin: EdgeInsets.zero),
        );
    return ApiScope(
      api: api,
      child: MaterialApp(
        title: 'BPI-R3',
        debugShowCheckedModeBanner: false,
        theme: theme(Brightness.light),
        darkTheme: theme(Brightness.dark),
        home: const Root(),
      ),
    );
  }
}

/// Chưa kết nối / chưa đăng nhập -> màn hình kết nối; xong -> bảng điều khiển.
class Root extends StatelessWidget {
  const Root({super.key});

  @override
  Widget build(BuildContext context) {
    final api = ApiScope.of(context);
    return api.connected && api.isAdmin ? const HomeScreen() : const ConnectScreen();
  }
}
