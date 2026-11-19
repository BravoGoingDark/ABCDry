// Pieces shared by the sign-in and sign-up screens: the website-style header,
// a password field with show / hide, and the result popup.
import 'dart:async';

import 'package:material_ui/material_ui.dart';

import 'api.dart';
import 'format.dart';
import 'i18n.dart';

/// Page frame of the sign-in and sign-up screens, like the website's: logo
/// and language switch, a small coloured kicker, a big title, a short text.
class AuthPage extends StatelessWidget {
  const AuthPage({
    super.key,
    required this.kicker,
    required this.title,
    required this.text,
    required this.children,
    this.showBack = false,
  });
  final String kicker;
  final String title;
  final String text;
  final List<Widget> children;
  final bool showBack;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.fromLTRB(24, 16, 24, 24),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 420),
              child: AutofillGroup(
                child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                  Row(children: [
                    if (showBack)
                      Padding(
                        padding: const EdgeInsetsDirectional.only(end: 4),
                        child: IconButton(
                          tooltip: MaterialLocalizations.of(context).backButtonTooltip,
                          icon: const BackButtonIcon(),
                          onPressed: () => Navigator.maybePop(context),
                        ),
                      ),
                    const BrandLogo(size: 44),
                    const SizedBox(width: 12),
                    Text('APWRS', style: hl(20)),
                    const Spacer(),
                    LangPill(onPick: (l) async {
                      await Api.I.setLang(l);
                      appLang.value = l;
                    }),
                  ]),
                  const SizedBox(height: 32),
                  Text(kicker.toUpperCase(),
                      style: const TextStyle(
                          fontSize: 11.5, fontWeight: FontWeight.w600, letterSpacing: 2.2, color: kSecondary)),
                  const SizedBox(height: 10),
                  Text(title, style: hl(30)),
                  const SizedBox(height: 8),
                  Text(text, style: const TextStyle(color: kMuted, fontSize: 15, height: 1.45)),
                  const SizedBox(height: 26),
                  ...children,
                ]),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

/// Text field with a leading icon and an optional error under it.
class AuthField extends StatelessWidget {
  const AuthField({
    super.key,
    required this.controller,
    required this.label,
    required this.icon,
    this.error,
    this.keyboard,
    this.autofill,
    this.action = TextInputAction.next,
    this.onSubmitted,
    this.password = false,
  });
  final TextEditingController controller;
  final String label;
  final IconData icon;
  final String? error;
  final TextInputType? keyboard;
  final String? autofill;
  final TextInputAction action;
  final ValueChanged<String>? onSubmitted;
  final bool password;

  @override
  Widget build(BuildContext context) {
    final decoration = InputDecoration(
      labelText: label,
      prefixIcon: Icon(icon),
      errorText: error,
      errorMaxLines: 3,
    );
    final field = password
        ? _PasswordField(
            controller: controller,
            decoration: decoration,
            autofill: autofill,
            action: action,
            onSubmitted: onSubmitted)
        : TextField(
            controller: controller,
            keyboardType: keyboard,
            autofillHints: autofill != null ? [autofill!] : null,
            textInputAction: action,
            onSubmitted: onSubmitted,
            decoration: decoration,
          );
    return Padding(padding: const EdgeInsets.only(bottom: 12), child: field);
  }
}

class _PasswordField extends StatefulWidget {
  const _PasswordField(
      {required this.controller, required this.decoration, this.autofill, required this.action, this.onSubmitted});
  final TextEditingController controller;
  final InputDecoration decoration;
  final String? autofill;
  final TextInputAction action;
  final ValueChanged<String>? onSubmitted;

  @override
  State<_PasswordField> createState() => _PasswordFieldState();
}

class _PasswordFieldState extends State<_PasswordField> {
  bool _hidden = true;

  @override
  Widget build(BuildContext context) => TextField(
        controller: widget.controller,
        obscureText: _hidden,
        autofillHints: widget.autofill != null ? [widget.autofill!] : null,
        textInputAction: widget.action,
        onSubmitted: widget.onSubmitted,
        decoration: widget.decoration.copyWith(
          suffixIcon: IconButton(
            tooltip: t(_hidden ? 'showPassword' : 'hidePassword'),
            icon: Icon(_hidden ? Icons.visibility_outlined : Icons.visibility_off_outlined),
            onPressed: () => setState(() => _hidden = !_hidden),
          ),
        ),
      );
}

/// The big dark-green button of the auth screens, with its spinner.
class AuthButton extends StatelessWidget {
  const AuthButton({super.key, required this.label, required this.busy, required this.onPressed});
  final String label;
  final bool busy;
  final VoidCallback onPressed;

  @override
  Widget build(BuildContext context) => FilledButton(
        onPressed: busy ? null : onPressed,
        style: FilledButton.styleFrom(minimumSize: const Size.fromHeight(52)),
        child: busy
            ? const SizedBox(
                width: 22, height: 22, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
            : Row(mainAxisAlignment: MainAxisAlignment.center, children: [
                Flexible(child: Text(label, overflow: TextOverflow.ellipsis)),
                const SizedBox(width: 8),
                const Icon(Icons.arrow_forward, size: 18),
              ]),
      );
}

/// Popup for the result of signing in or up: a round mint check for good
/// news, a red mark for a refusal, a title, a text and one button. With
/// [autoClose] it also closes by itself after that time.
Future<void> showResultPopup(
  BuildContext context, {
  required bool ok,
  required String title,
  required String message,
  String? button,
  Duration? autoClose,
}) {
  Timer? timer;
  final done = showGeneralDialog<void>(
    context: context,
    barrierDismissible: true,
    barrierLabel: MaterialLocalizations.of(context).modalBarrierDismissLabel,
    barrierColor: const Color(0x8C012D1D),
    transitionDuration: const Duration(milliseconds: 260),
    pageBuilder: (dialogContext, _, __) {
      if (autoClose != null) {
        timer = Timer(autoClose, () {
          if (Navigator.of(dialogContext).canPop()) Navigator.of(dialogContext).pop();
        });
      }
      return _ResultCard(ok: ok, title: title, message: message, button: button ?? t('ok'));
    },
    transitionBuilder: (_, animation, __, child) {
      final curved = CurvedAnimation(parent: animation, curve: Curves.easeOutBack, reverseCurve: Curves.easeIn);
      return FadeTransition(
        opacity: animation,
        child: ScaleTransition(scale: Tween(begin: 0.88, end: 1.0).animate(curved), child: child),
      );
    },
  );
  return done.whenComplete(() => timer?.cancel());
}

class _ResultCard extends StatelessWidget {
  const _ResultCard({required this.ok, required this.title, required this.message, required this.button});
  final bool ok;
  final String title;
  final String message;
  final String button;

  @override
  Widget build(BuildContext context) => Center(
        child: Padding(
          padding: const EdgeInsets.all(28),
          child: Material(
            color: Colors.white,
            borderRadius: BorderRadius.circular(24),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 380),
              child: Padding(
                padding: const EdgeInsets.fromLTRB(24, 28, 24, 20),
                child: Column(mainAxisSize: MainAxisSize.min, children: [
                  Container(
                    width: 72,
                    height: 72,
                    decoration: BoxDecoration(color: ok ? kMint : kDangerBg, shape: BoxShape.circle),
                    child: Icon(ok ? Icons.check_rounded : Icons.priority_high_rounded,
                        size: 40, color: ok ? kLeaf : kDanger),
                  ),
                  const SizedBox(height: 18),
                  Text(title, textAlign: TextAlign.center, style: hl(21)),
                  const SizedBox(height: 8),
                  Text(message,
                      textAlign: TextAlign.center, style: const TextStyle(color: kMuted, fontSize: 14.5, height: 1.45)),
                  const SizedBox(height: 22),
                  FilledButton(
                    style: FilledButton.styleFrom(
                      minimumSize: const Size.fromHeight(48),
                      backgroundColor: ok ? kPrimary : kDanger,
                    ),
                    onPressed: () => Navigator.of(context).pop(),
                    child: Text(button),
                  ),
                ]),
              ),
            ),
          ),
        ),
      );
}
