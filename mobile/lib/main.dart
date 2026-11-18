import 'package:material_ui/material_ui.dart';
import 'package:cupertino_ui/cupertino_ui.dart' show GlobalCupertinoLocalizations;
import 'package:flutter_localizations/flutter_localizations.dart' show GlobalWidgetsLocalizations;
import 'package:intl/date_symbol_data_local.dart';

import 'api.dart';
import 'format.dart';
import 'i18n.dart';
import 'screens/home_screen.dart';
import 'screens/login_screen.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await initializeDateFormatting();
  await Api.I.load();
  appLang.value = Api.I.lang;
  offlineFlag = Api.I.offline;
  runApp(const FarmerApp());
}

class FarmerApp extends StatefulWidget {
  const FarmerApp({super.key});

  @override
  State<FarmerApp> createState() => _FarmerAppState();
}

class _FarmerAppState extends State<FarmerApp> {
  bool _signedIn = Api.I.token != null;

  @override
  void initState() {
    super.initState();
    // The server refused the token (revoked or expired): back to sign-in.
    Api.I.onSignedOut = () {
      if (mounted) setState(() => _signedIn = false);
    };
  }

  @override
  Widget build(BuildContext context) {
    return ValueListenableBuilder<String>(
      valueListenable: appLang,
      builder: (context, lang, _) => MaterialApp(
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
        home: _signedIn
            ? HomeScreen(key: ValueKey('home-$lang'), onSignedOut: () => setState(() => _signedIn = false))
            : LoginScreen(onSignedIn: () => setState(() => _signedIn = true)),
      ),
    );
  }
}
