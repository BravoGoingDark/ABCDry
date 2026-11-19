// Pieces shared by the sign-in and sign-up screens, laid out like the
// website's sign-in page (templates/dashboard/login.html) on a phone: the
// logo bar with the language switch, a teal kicker, a big green title,
// labelled fields, one solid button and the data footer. Also the password
// field with show / hide, and the result popup.
import 'dart:async';

import 'package:material_ui/material_ui.dart';

import 'api.dart';
import 'format.dart';
import 'fx.dart';
import 'i18n.dart';

/// Page frame of the sign-in and sign-up screens.
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
      backgroundColor: Colors.white,
      body: SafeArea(
        child: Column(children: [
          // Top bar: back, logo and name on the start side, languages on the end.
          Container(
            height: 64,
            padding: EdgeInsetsDirectional.fromSTEB(showBack ? 4 : 20, 0, 16, 0),
            decoration: const BoxDecoration(border: Border(bottom: BorderSide(color: kOutlineSoft))),
            child: Row(children: [
              if (showBack)
                IconButton(
                  tooltip: MaterialLocalizations.of(context).backButtonTooltip,
                  color: kMuted,
                  icon: const BackButtonIcon(),
                  onPressed: () => Navigator.maybePop(context),
                ),
              const BrandLogo(size: 32),
              const SizedBox(width: 10),
              Text('APWRS', style: hl(17)),
              const Spacer(),
              SizedBox(
                  height: 40,
                  child: LangPill(onPick: (l) async {
                    await Api.I.setLang(l);
                    appLang.value = l;
                  })),
            ]),
          ),
          // The form, then the footer at the bottom of the screen; on a short
          // screen (or with the keyboard open) the footer scrolls after the form.
          Expanded(
            child: LayoutBuilder(
              builder: (context, box) => SingleChildScrollView(
                padding: const EdgeInsets.fromLTRB(24, 24, 24, 16),
                child: ConstrainedBox(
                  constraints: BoxConstraints(minHeight: box.maxHeight - 40),
                  child: IntrinsicHeight(
                    child: Column(children: [
                      Center(
                        child: ConstrainedBox(
                          constraints: const BoxConstraints(maxWidth: 400),
                          child: FadeSlideIn(
                            child: AutofillGroup(
                              child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                                Kicker(kicker),
                                const SizedBox(height: 14),
                                Text(title, style: hl(30).copyWith(letterSpacing: -0.4, height: 1.15)),
                                const SizedBox(height: 10),
                                Text(text, style: const TextStyle(color: kMuted, fontSize: 15, height: 1.5)),
                                const SizedBox(height: 28),
                                ...children,
                              ]),
                            ),
                          ),
                        ),
                      ),
                      const Spacer(),
                      const SizedBox(height: 28),
                      const _Footer(),
                    ]),
                  ),
                ),
              ),
            ),
          ),
        ]),
      ),
    );
  }
}

/// The website's footer, at the end of the page.
class _Footer extends StatelessWidget {
  const _Footer();

  @override
  Widget build(BuildContext context) => Container(
        width: double.infinity,
        padding: const EdgeInsets.only(top: 14),
        decoration: const BoxDecoration(border: Border(top: BorderSide(color: kOutlineSoft))),
        child: Column(children: [
          Text.rich(
            TextSpan(children: [
              TextSpan(text: 'APWRS', style: hl(12, weight: FontWeight.w800)),
              TextSpan(text: ' · ${t('ichkeulBasin')}'),
            ]),
            style: const TextStyle(fontSize: 12, color: kSubtle),
          ),
          const SizedBox(height: 2),
          Text(t('dataSources'), textAlign: TextAlign.center, style: const TextStyle(fontSize: 11, color: kSubtle)),
        ]),
      );
}

/// The website's small label: a short teal line, then teal capitals.
class Kicker extends StatelessWidget {
  const Kicker(this.text, {super.key});
  final String text;

  @override
  Widget build(BuildContext context) => Row(children: [
        Container(width: 28, height: 1.2, color: kSecondary),
        const SizedBox(width: 10),
        Flexible(
          child: Text(text.toUpperCase(),
              style:
                  const TextStyle(fontSize: 11.5, fontWeight: FontWeight.w600, letterSpacing: 2.2, color: kSecondary)),
        ),
      ]);
}

/// A labelled text field, as on the website: the label above, an icon in the
/// field, and an optional error under it.
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

  static const _radius = BorderRadius.all(Radius.circular(8));

  @override
  Widget build(BuildContext context) {
    final decoration = InputDecoration(
      prefixIcon: Icon(icon, size: 20),
      prefixIconColor: WidgetStateColor.resolveWith((s) => s.contains(WidgetState.focused) ? kSecondary : kOutline),
      errorText: error,
      errorMaxLines: 3,
      isDense: true,
      contentPadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 14),
      border: const OutlineInputBorder(borderRadius: _radius, borderSide: BorderSide(color: kOutline)),
      enabledBorder: const OutlineInputBorder(borderRadius: _radius, borderSide: BorderSide(color: kOutline)),
      focusedBorder:
          const OutlineInputBorder(borderRadius: _radius, borderSide: BorderSide(color: kSecondary, width: 1.6)),
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
    return Padding(
      padding: const EdgeInsets.only(bottom: 18),
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Text(label, style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w600, color: kText)),
        const SizedBox(height: 7),
        field,
      ]),
    );
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

/// The website's sign-in button: solid dark green, bold, an arrow, a soft
/// shadow; a spinner while busy.
class AuthButton extends StatelessWidget {
  const AuthButton({super.key, required this.label, required this.busy, required this.onPressed});
  final String label;
  final bool busy;
  final VoidCallback onPressed;

  @override
  Widget build(BuildContext context) => Pressable(
        child: FilledButton(
          onPressed: busy ? null : onPressed,
          style: FilledButton.styleFrom(
            minimumSize: const Size.fromHeight(52),
            backgroundColor: kPrimaryC,
            disabledBackgroundColor: kPrimaryC.withValues(alpha: 0.85),
            disabledForegroundColor: Colors.white,
            elevation: 3,
            shadowColor: const Color(0x66012D1D),
            shape: const RoundedRectangleBorder(borderRadius: BorderRadius.all(Radius.circular(8))),
            textStyle: hl(15, weight: FontWeight.w700),
          ),
          child: busy
              ? const SizedBox(
                  width: 22, height: 22, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
              : Row(mainAxisAlignment: MainAxisAlignment.center, children: [
                  Flexible(child: Text(label, overflow: TextOverflow.ellipsis)),
                  const SizedBox(width: 8),
                  const Icon(Icons.arrow_forward, size: 20),
                ]),
        ),
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
