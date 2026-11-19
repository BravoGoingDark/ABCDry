import 'package:material_ui/material_ui.dart';

import '../api.dart';
import '../auth_widgets.dart';
import '../format.dart';
import '../i18n.dart';

/// Farmer sign-up, the same form as the website's (username, optional email,
/// phone number, password twice). The server applies the website's rules;
/// the app checks the obvious ones first so the farmer is told at once.
/// Pops true once the account exists and the app is signed in with it.
class SignupScreen extends StatefulWidget {
  const SignupScreen({super.key});

  @override
  State<SignupScreen> createState() => _SignupScreenState();
}

class _SignupScreenState extends State<SignupScreen> {
  final _user = TextEditingController();
  final _email = TextEditingController();
  final _phone = TextEditingController();
  final _pass = TextEditingController();
  final _confirm = TextEditingController();
  Map<String, String> _errors = {};
  bool _busy = false;

  @override
  void dispose() {
    for (final c in [_user, _email, _phone, _pass, _confirm]) {
      c.dispose();
    }
    super.dispose();
  }

  /// Errors the app can see without asking the server, by server field name.
  Map<String, String> _localErrors() => {
        if (_user.text.trim().isEmpty) 'username': t('fillRequired'),
        if (_phone.text.trim().isEmpty) 'phone': t('fillRequired'),
        if (_pass.text.length < 6) 'password1': t('passwordShort'),
        if (_confirm.text != _pass.text) 'password2': t('passwordsDiffer'),
      };

  Future<void> _create() async {
    FocusScope.of(context).unfocus();
    final local = _localErrors();
    if (local.isNotEmpty) {
      setState(() => _errors = local);
      await showResultPopup(context, ok: false, title: t('signupFailed'), message: local.values.first);
      return;
    }
    setState(() {
      _busy = true;
      _errors = {};
    });
    Map<String, dynamic> user;
    try {
      user = await Api.I.signup(
        username: _user.text.trim(),
        email: _email.text.trim(),
        phone: _phone.text.trim(),
        password: _pass.text,
        confirm: _confirm.text,
      );
    } on ApiException catch (e) {
      if (!mounted) return;
      // the answer is in: no spinner behind the popup
      setState(() {
        _busy = false;
        _errors = e.fields;
      });
      await showResultPopup(context, ok: false, title: t('signupFailed'), message: e.message);
      return;
    }
    if (!mounted) return;
    setState(() => _busy = false);
    await showResultPopup(
      context,
      ok: true,
      title: t('welcomeNew', {'name': user['name'] ?? user['username'] ?? ''}),
      message: t('welcomeNewText'),
      button: t('start'),
    );
    if (mounted) Navigator.pop(context, true);
  }

  @override
  Widget build(BuildContext context) {
    return AuthPage(
      showBack: true,
      kicker: t('signupKicker'),
      title: t('signupTitle'),
      text: t('signupHint'),
      children: [
        AuthField(
          controller: _user,
          label: t('username'),
          icon: Icons.person_outline,
          autofill: AutofillHints.newUsername,
          error: _errors['username'],
        ),
        AuthField(
          controller: _email,
          label: '${t('email')} (${t('optional')})',
          icon: Icons.mail_outline,
          keyboard: TextInputType.emailAddress,
          autofill: AutofillHints.email,
          error: _errors['email'],
        ),
        AuthField(
          controller: _phone,
          label: t('phone'),
          icon: Icons.phone_outlined,
          keyboard: TextInputType.phone,
          autofill: AutofillHints.telephoneNumber,
          error: _errors['phone'],
        ),
        AuthField(
          controller: _pass,
          label: t('password'),
          icon: Icons.lock_outline,
          password: true,
          autofill: AutofillHints.newPassword,
          error: _errors['password1'],
        ),
        AuthField(
          controller: _confirm,
          label: t('confirmPassword'),
          icon: Icons.lock_outline,
          password: true,
          autofill: AutofillHints.newPassword,
          action: TextInputAction.done,
          onSubmitted: (_) => _create(),
          error: _errors['password2'],
        ),
        const SizedBox(height: 8),
        AuthButton(label: t('createAccount'), busy: _busy, onPressed: _create),
        const SizedBox(height: 18),
        Wrap(alignment: WrapAlignment.center, crossAxisAlignment: WrapCrossAlignment.center, children: [
          Text(t('haveAccount'), style: const TextStyle(color: kSubtle, fontSize: 13.5)),
          TextButton(
            onPressed: _busy ? null : () => Navigator.pop(context),
            child: Text(t('signIn')),
          ),
        ]),
      ],
    );
  }
}
