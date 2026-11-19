import 'package:material_ui/material_ui.dart';

import '../format.dart';
import '../i18n.dart';

/// Loading screen while the app opens, in the website's light style: its
/// soft light-blue wash, the logo with its teal ring, the name and tagline,
/// a thin progress bar and the data sources, easing in.
class SplashView extends StatefulWidget {
  const SplashView({super.key, this.showText = true});

  /// False for the first instant, before the saved language is known.
  final bool showText;

  @override
  State<SplashView> createState() => _SplashViewState();
}

class _SplashViewState extends State<SplashView> with SingleTickerProviderStateMixin {
  late final AnimationController _in = AnimationController(vsync: this, duration: const Duration(milliseconds: 900))
    ..forward();

  @override
  void dispose() {
    _in.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final logo = CurvedAnimation(parent: _in, curve: const Interval(0, 0.7, curve: Curves.easeOutCubic));
    final text = CurvedAnimation(parent: _in, curve: const Interval(0.25, 1, curve: Curves.easeOutCubic));
    return Scaffold(
      body: DecoratedBox(
        // The website's .hero-bg.
        decoration: const BoxDecoration(
          gradient: LinearGradient(
              begin: Alignment.topCenter, end: Alignment.bottomCenter, colors: [Colors.white, kSurfaceLow]),
        ),
        child: DecoratedBox(
          decoration: const BoxDecoration(
            gradient: RadialGradient(
              center: Alignment(1, -1.15),
              radius: 1.2,
              colors: [Color(0x2469D4F4), Color(0x0069D4F4)],
            ),
          ),
          child: SafeArea(
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 32),
              child: Column(children: [
                const Spacer(flex: 5),
                // Already shown by the phone's launch screen: it only settles in.
                ScaleTransition(
                  scale: Tween(begin: 0.96, end: 1.0).animate(logo),
                  child: const BrandLogo(size: 104),
                ),
                const SizedBox(height: 28),
                FadeTransition(
                  opacity: text,
                  child: SlideTransition(
                    position: Tween(begin: const Offset(0, 0.25), end: Offset.zero).animate(text),
                    child: Column(children: [
                      Text('APWRS', style: hl(34).copyWith(letterSpacing: -0.4)),
                      const SizedBox(height: 8),
                      AnimatedOpacity(
                        opacity: widget.showText ? 1 : 0,
                        duration: const Duration(milliseconds: 250),
                        child: Text(t('tagline'),
                            textAlign: TextAlign.center,
                            style: const TextStyle(color: kMuted, fontSize: 13.5, height: 1.4)),
                      ),
                    ]),
                  ),
                ),
                const Spacer(flex: 4),
                FadeTransition(
                  opacity: text,
                  child: AnimatedOpacity(
                    opacity: widget.showText ? 1 : 0,
                    duration: const Duration(milliseconds: 250),
                    child: Column(children: [
                      SizedBox(
                        width: 140,
                        child: ClipRRect(
                          borderRadius: BorderRadius.circular(2),
                          child: const LinearProgressIndicator(
                            minHeight: 3,
                            color: kSecondary,
                            backgroundColor: kSurfaceHigh,
                          ),
                        ),
                      ),
                      const SizedBox(height: 14),
                      Text(t('loadingFarm'), style: const TextStyle(color: kSubtle, fontSize: 13)),
                      const SizedBox(height: 28),
                      Text(t('dataSources'),
                          textAlign: TextAlign.center, style: const TextStyle(color: kSubtle, fontSize: 11.5)),
                      const SizedBox(height: 16),
                    ]),
                  ),
                ),
              ]),
            ),
          ),
        ),
      ),
    );
  }
}
