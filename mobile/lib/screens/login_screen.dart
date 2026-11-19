import 'package:material_ui/material_ui.dart';

import '../api.dart';
import '../auth_widgets.dart';
import '../format.dart';
import '../i18n.dart';
import 'signup_screen.dart';

/// Sign in with the farmer account used on the website, or create one.
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

  @override
  void dispose() {
    _user.dispose();
    _pass.dispose();
    super.dispose();
  }

  Future<void> _signIn() async {
    FocusScope.of(context).unfocus();
    if (_user.text.trim().isEmpty || _pass.text.isEmpty) {
      await showResultPopup(context, ok: false, title: t('signInFailed'), message: t('fillSignIn'));
      return;
    }
    setState(() => _busy = true);
    Map<String, dynamic> user;
    try {
      user = await Api.I.login(_user.text.trim(), _pass.text);
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() => _busy = false); // the answer is in: no spinner behind the popup
      await showResultPopup(context, ok: false, title: t('signInFailed'), message: e.message);
      return;
    }
    if (!mounted) return;
    setState(() => _busy = false);
    await showResultPopup(
      context,
      ok: true,
      title: t('welcomeBack', {'name': user['name'] ?? user['username'] ?? ''}),
      message: t('welcomeBackText'),
      button: t('start'),
      autoClose: const Duration(milliseconds: 1600),
    );
    widget.onSignedIn();
  }

  Future<void> _signUp() async {
    final created = await Navigator.push<bool>(context, MaterialPageRoute(builder: (_) => const SignupScreen()));
    if (created == true) widget.onSignedIn();
  }

  @override
  Widget build(BuildContext context) {
    return AuthPage(
      kicker: t('farmerSpace'),
      title: t('signInTitle'),
      text: t('signInHint'),
      children: [
        AuthField(
            controller: _user, label: t('username'), icon: Icons.person_outline, autofill: AutofillHints.username),
        AuthField(
          controller: _pass,
          label: t('password'),
          icon: Icons.lock_outline,
          password: true,
          autofill: AutofillHints.password,
          action: TextInputAction.done,
          onSubmitted: (_) => _signIn(),
        ),
        const SizedBox(height: 8),
        AuthButton(label: t('signIn'), busy: _busy, onPressed: _signIn),
        const SizedBox(height: 28),
        // The website's "Need an account? Sign up" link, as a button.
        Row(children: [
          const Expanded(child: Divider()),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 12),
            child: Text(t('noAccount'), style: const TextStyle(color: kSubtle, fontSize: 13)),
          ),
          const Expanded(child: Divider()),
        ]),
        const SizedBox(height: 14),
        OutlinedButton.icon(
          style: OutlinedButton.styleFrom(minimumSize: const Size.fromHeight(50)),
          icon: const Icon(Icons.person_add_alt_1_outlined),
          label: Text(t('signUp')),
          onPressed: _busy ? null : _signUp,
        ),
      ],
    );
  }
}
