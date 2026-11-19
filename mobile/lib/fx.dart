// Two quiet motions, as on the website: content eases in when it appears,
// and buttons give a little when pressed (the website's active:scale-[.99]).
import 'dart:math' as math;

import 'package:material_ui/material_ui.dart';

/// Fades its child in while it rises a few pixels, [index] steps after the first.
class FadeSlideIn extends StatefulWidget {
  const FadeSlideIn({super.key, required this.child, this.index = 0, this.offset = 10});
  final Widget child;
  final int index;
  final double offset;

  @override
  State<FadeSlideIn> createState() => _FadeSlideInState();
}

class _FadeSlideInState extends State<FadeSlideIn> with SingleTickerProviderStateMixin {
  static const _step = 50;
  static const _length = 320;
  late final int _delay = math.min(widget.index, 6) * _step;
  late final AnimationController _c =
      AnimationController(vsync: this, duration: Duration(milliseconds: _delay + _length))..forward();
  late final Animation<double> _a =
      CurvedAnimation(parent: _c, curve: Interval(_delay / (_delay + _length), 1, curve: Curves.easeOutCubic));

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => AnimatedBuilder(
        animation: _a,
        builder: (context, child) => Opacity(
          opacity: _a.value,
          child: Transform.translate(offset: Offset(0, widget.offset * (1 - _a.value)), child: child),
        ),
        child: widget.child,
      );
}

/// Shrinks a touch while pressed. Taps go through to the child untouched.
class Pressable extends StatefulWidget {
  const Pressable({super.key, required this.child, this.scale = 0.985});
  final Widget child;
  final double scale;

  @override
  State<Pressable> createState() => _PressableState();
}

class _PressableState extends State<Pressable> {
  bool _down = false;

  void _set(bool v) {
    if (v != _down) setState(() => _down = v);
  }

  @override
  Widget build(BuildContext context) => Listener(
        onPointerDown: (_) => _set(true),
        onPointerUp: (_) => _set(false),
        onPointerCancel: (_) => _set(false),
        child: AnimatedScale(
          scale: _down ? widget.scale : 1,
          duration: const Duration(milliseconds: 120),
          curve: Curves.easeOut,
          child: widget.child,
        ),
      );
}
