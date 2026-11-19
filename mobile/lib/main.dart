import 'package:material_ui/material_ui.dart';
import 'package:cupertino_ui/cupertino_ui.dart' show GlobalCupertinoLocalizations;
import 'package:flutter_localizations/flutter_localizations.dart' show GlobalWidgetsLocalizations;
import 'package:intl/date_symbol_data_local.dart';

import 'api.dart';
import 'format.dart';
import 'i18n.dart';
import 'screens/home_screen.dart';
import 'screens/login_screen.dart';
import 'screens/splash_screen.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  offlineFlag = Api.I.offline;
  runApp(const FarmerApp());
}

class FarmerApp extends StatefulWidget {
  const FarmerApp({super.key});

  /// Shortest time the loading screen stays, so it never just flickers.
  static const minSplash = Duration(milliseconds: 1800);

  /// Longest wait for the farms before showing Home anyway (it keeps loading).
  static const maxFarmWait = Duration(seconds: 8);

  @override
  State<FarmerApp> createState() => _FarmerAppState();
}

class _FarmerAppState extends State<FarmerApp> {
  bool _loaded = false; // saved settings read: the loading screen can show its texts
  bool _ready = false; // loading done: show sign-in or home
  bool _signedIn = false;

  /// The farm list fetched behind the loading screen, handed to Home once.
  Future<dynamic>? _firstFarms;

  @override
  void initState() {
    super.initState();
    // The server refused the token (revoked or expired): back to sign-in.
    Api.I.onSignedOut = () {
      if (mounted) setState(() => _signedIn = false);
    };
    _boot();
  }

  Future<void> _boot() async {
    final started = DateTime.now();
    await initializeDateFormatting();
    await Api.I.load();
    appLang.value = Api.I.lang;
    if (!mounted) return;
    setState(() {
      _loaded = true;
      _signedIn = Api.I.token != null;
    });
    if (_signedIn) {
      // Saved data answers at once; a sleeping server is waited for a little.
      _firstFarms = Api.I.get('/farmer/api/farms/');
      try {
        await _firstFarms!.timeout(FarmerApp.maxFarmWait);
      } catch (_) {
        // Home shows the error or keeps waiting with its own spinner.
      }
    }
    final left = FarmerApp.minSplash - DateTime.now().difference(started);
    if (left > Duration.zero) await Future<void>.delayed(left);
    if (mounted) setState(() => _ready = true);
  }

  @override
  Widget build(BuildContext context) {
    return ValueListenableBuilder<String>(
      valueListenable: appLang,
      builder: (context, lang, _) {
        final first = _firstFarms;
        _firstFarms = null; // only the first Home uses it; later ones load fresh
        final Widget page = !_ready
            ? SplashView(key: const ValueKey('splash'), showText: _loaded)
            : _signedIn
                ? HomeScreen(
                    key: ValueKey('home-$lang'),
                    initialFarms: first,
                    onSignedOut: () => setState(() => _signedIn = false))
                : LoginScreen(key: const ValueKey('login'), onSignedIn: () => setState(() => _signedIn = true));
        return MaterialApp(
          title: tr(lang, 'appName'),
          debugShowCheckedModeBanner: false,
          theme: appTheme(),
          locale: Locale(lang),
          supportedLocales: [for (final l in supportedLangs) Locale(l)],
          localizationsDelegates: const [
            GlobalMaterialLocalizations.delegate,
            GlobalWidgetsLocalizations.delegate,
            GlobalCupertinoLocalizations.delegate,
          ],
          // Arabic is laid out right to left by the Global*Localizations delegates.
          home: AnimatedSwitcher(duration: const Duration(milliseconds: 450), child: page),
        );
      },
    );
  }
}
