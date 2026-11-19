import 'package:material_ui/material_ui.dart';

import '../format.dart';
import '../i18n.dart';

/// Loading screen while the app opens: the brand green of the launch screen,
/// the app icon, the name, the website's tagline and a quiet progress bar.
class SplashView extends StatefulWidget {
  const SplashView({super.key, this.showText = true});

  /// False for the first instant, before the saved language is known.
  final bool showText;

  @override
  State<SplashView> createState() => _SplashViewState();
}

class _SplashViewState extends State<SplashView> with SingleTickerProviderStateMixin {
  late final AnimationController _in = AnimationController(vsync: this, duration: const Duration(milliseconds: 700))
    ..forward();

  @override
  void dispose() {
    _in.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final fade = CurvedAnimation(parent: _in, curve: Curves.easeOut);
    return Scaffold(
      backgroundColor: kPrimary,
      body: Container(
        decoration: const BoxDecoration(
          gradient: RadialGradient(
            center: Alignment(0, -0.25),
            radius: 1.1,
            colors: [kPrimaryC, kPrimary],
          ),
        ),
        child: SafeArea(
          child: Column(children: [
            const Spacer(flex: 5),
            ScaleTransition(
              scale: Tween(begin: 0.9, end: 1.0).animate(fade),
              child: Container(
                width: 112,
                height: 112,
                decoration: BoxDecoration(
                  borderRadius: BorderRadius.circular(28),
                  border: Border.all(color: const Color(0x5969D4F4), width: 2),
                  boxShadow: const [BoxShadow(color: Color(0x66000000), blurRadius: 30, offset: Offset(0, 12))],
                ),
                child: ClipRRect(
                  borderRadius: BorderRadius.circular(26),
                  child: Image.asset('assets/img/app_icon.png', fit: BoxFit.cover),
                ),
              ),
            ),
            const SizedBox(height: 26),
            FadeTransition(
              opacity: fade,
              child: Column(children: [
                Text('APWRS', style: hl(34, color: Colors.white)),
                const SizedBox(height: 6),
                AnimatedOpacity(
                  opacity: widget.showText ? 1 : 0,
                  duration: const Duration(milliseconds: 250),
                  child: Text(t('farmerSpace').toUpperCase(),
                      style: const TextStyle(
                          color: kSecondaryFixed, fontSize: 12, fontWeight: FontWeight.w600, letterSpacing: 2.4)),
                ),
              ]),
            ),
            const Spacer(flex: 4),
            AnimatedOpacity(
              opacity: widget.showText ? 1 : 0,
              duration: const Duration(milliseconds: 250),
              child: Column(children: [
                SizedBox(
                  width: 120,
                  child: ClipRRect(
                    borderRadius: BorderRadius.circular(4),
                    child: const LinearProgressIndicator(
                      minHeight: 4,
                      color: kSecondaryFixed,
                      backgroundColor: Color(0x33FFFFFF),
                    ),
                  ),
                ),
                const SizedBox(height: 14),
                Text(t('loadingFarm'), style: const TextStyle(color: Color(0xCCFFFFFF), fontSize: 13.5)),
                const SizedBox(height: 28),
                Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 32),
                  child: Text(t('tagline'),
                      textAlign: TextAlign.center,
                      style: const TextStyle(color: Color(0xFF86AF99), fontSize: 11.5, height: 1.4)),
                ),
                const SizedBox(height: 18),
              ]),
            ),
          ]),
        ),
      ),
    );
  }
}
