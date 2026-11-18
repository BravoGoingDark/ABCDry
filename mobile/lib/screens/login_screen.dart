import 'package:material_ui/material_ui.dart';

import '../api.dart';
import '../format.dart';
import '../i18n.dart';

class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key, required this.onSignedIn});
  final VoidCallback onSignedIn;

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _user = TextEditingController();
  final _pass = TextEditingController();
  bool _busy = false;
  String? _error;

  Future<void> _signIn() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await Api.I.login(_user.text, _pass.text);
      widget.onSignedIn();
    } on ApiException catch (e) {
      setState(() => _error = e.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(24),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 420),
              child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                // Same header as the website's sign-in page: logo, kicker, title.
                Row(children: [
                  const BrandLogo(size: 44),
                  const SizedBox(width: 12),
                  Text('APWRS', style: hl(20)),
                  const Spacer(),
                  LangPill(onPick: (l) async {
                    await Api.I.setLang(l);
                    appLang.value = l;
                  }),
                ]),
                const SizedBox(height: 36),
                Text(t('farmerSpace').toUpperCase(),
                    style: const TextStyle(
                        fontSize: 11.5, fontWeight: FontWeight.w600, letterSpacing: 2.2, color: kSecondary)),
                const SizedBox(height: 10),
                Text(t('signInTitle'), style: hl(30)),
                const SizedBox(height: 8),
                Text(t('signInHint'), style: const TextStyle(color: kMuted, fontSize: 15, height: 1.45)),
                const SizedBox(height: 28),
                TextField(
                  controller: _user,
                  autofillHints: const [AutofillHints.username],
                  textInputAction: TextInputAction.next,
                  decoration: InputDecoration(labelText: t('username'), prefixIcon: const Icon(Icons.person)),
                ),
                const SizedBox(height: 12),
                TextField(
                  controller: _pass,
                  obscureText: true,
                  autofillHints: const [AutofillHints.password],
                  onSubmitted: (_) => _signIn(),
                  decoration: InputDecoration(labelText: t('password'), prefixIcon: const Icon(Icons.lock)),
                ),
                if (_error != null) ...[
                  const SizedBox(height: 12),
                  Text(_error!, style: const TextStyle(color: kDanger)),
                ],
                const SizedBox(height: 20),
                FilledButton(
                  onPressed: _busy ? null : _signIn,
                  style: FilledButton.styleFrom(minimumSize: const Size.fromHeight(52)),
                  child: _busy
                      ? const SizedBox(
                          width: 22, height: 22, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                      : Row(mainAxisAlignment: MainAxisAlignment.center, children: [
                          Text(t('signIn')),
                          const SizedBox(width: 8),
                          const Icon(Icons.arrow_forward, size: 18),
                        ]),
                ),
              ]),
            ),
          ),
        ),
      ),
    );
  }
}
