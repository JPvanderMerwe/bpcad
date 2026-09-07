// Screen 01: boot and self-test. Design handoff section 3.
//
// A dot-leadered self-test, an amber hairline sweeping down the screen once,
// and a Start button. It is the design's single boot moment - brief 6.6 allows
// exactly one, and it must not repeat on any later screen.
//
// THE LINES ARE NOT A SCRIPT.
//
// The design shows `self-test .... ok` and a printer profile and a link. The
// obvious way to build this is to print those four strings and move on, and
// that would be a decoration that says "ok" while nothing works - on a phone
// whose cable is out, which is the single most likely way this screen is ever
// seen. So every line's value and its pass/fail comes from what /api/health
// actually returned, and the screen will happily say `model ... none` in
// amber and let you carry on, because a bpcad with no model still opens every
// part you already have.
//
// WHY THERE IS A START BUTTON AT ALL rather than falling straight through: the
// self-test is the one place the machine's state is stated plainly, and on a
// CPU-only box the wait it quotes is the difference between "this is slow" and
// "this is broken". Skipping it to save a tap would mean nobody ever reads it.

import 'package:flutter/material.dart';

import 'api.dart';
import 'glass.dart';
import 'theme.dart';
import 'tokens.dart';

class BootScreen extends StatefulWidget {
  const BootScreen({super.key, required this.api, required this.onStart});

  final BpcadApi api;

  /// Handed the health the self-test read, so the app behind this screen does
  /// not fetch it a second time.
  final void Function(Health?) onStart;

  @override
  State<BootScreen> createState() => _BootScreenState();
}

class _BootScreenState extends State<BootScreen>
    with SingleTickerProviderStateMixin {
  late final AnimationController _sweep;
  Health? _health;
  String? _problem;
  bool _done = false;

  @override
  void initState() {
    super.initState();
    // 2.4s, cubic-bezier(.5,0,.4,1), looping - the design's own timing.
    _sweep = AnimationController(
      duration: const Duration(milliseconds: 2400),
      vsync: this,
    )..repeat();
    _check();
  }

  Future<void> _check() async {
    try {
      final health = await widget.api.health();
      if (!mounted) return;
      setState(() {
        _health = health;
        _done = true;
      });
    } catch (error) {
      if (!mounted) return;
      setState(() {
        // THE ADDRESS IS ALWAYS NAMED. "Could not connect" with no address is
        // the least useful sentence an app can print: the one thing the user
        // can act on is which machine was not answering, and the fix is
        // nearly always the cable or the port.
        //
        // It is appended rather than substituted because BpcadUnreachable's
        // own message says WHAT went wrong ("connection refused", "timed
        // out") and not WHERE - the two halves are both needed and neither
        // one implies the other.
        final why = error is BpcadUnreachable ? error.why : error.toString();
        _problem = '$why — at ${widget.api.baseUrl}';
        _done = true;
      });
    }
  }

  @override
  void dispose() {
    _sweep.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    // The sweep is motion, so it goes under reduced motion - and it is the
    // only thing on this screen that does.
    final still = MediaQuery.of(context).disableAnimations;

    return Scaffold(
      body: Stack(
        children: [
          const _Graticule(),
          if (!still) _Sweep(_sweep),
          SafeArea(
            child: Padding(
              padding: const EdgeInsets.all(BpSpace.loose),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Spacer(),
                  _wordmark(),
                  const SizedBox(height: BpSpace.room),
                  _selfTest(),
                  const Spacer(),
                  if (_problem != null) _unreachable(),
                  _start(),
                  const SizedBox(height: BpSpace.base),
                  Text('bit primitive — bpcad',
                      style: TextStyle(
                          fontFamily: BpType.mono,
                          fontSize: BpType.micro,
                          color: BpPen.dim)),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _wordmark() => Row(
        children: [
          // The mark, at the design's 72px with a 14 radius. The real icon
          // ships in the app bundle; this is the launcher's own gradient so
          // the boot screen and the launcher agree.
          Container(
            width: 72,
            height: 72,
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(14),
              gradient: const LinearGradient(
                begin: Alignment.topLeft,
                end: Alignment.bottomRight,
                colors: [BpCore.phosphor, BpCore.bezel],
              ),
            ),
          ),
          const SizedBox(width: BpSpace.wide),
          Text('bpcad',
              style: TextStyle(
                  fontFamily: BpType.mono,
                  fontSize: BpType.display,
                  fontWeight: FontWeight.w600,
                  color: BpCore.screen)),
        ],
      );

  /// Dot-leadered, with the value in the pass pen and the profile in amber -
  /// the design's own colouring, and it means something: amber is a value
  /// that came from configuration rather than from a test.
  Widget _selfTest() {
    if (!_done) {
      return _line('link', 'checking…', BpcadColors.inkDim, pulsing: true);
    }
    final health = _health;
    if (health == null) {
      return Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _line('self-test', 'ok', BpPen.pass),
          _line('link', 'no answer', BpPen.fail),
        ],
      );
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        for (final (key, value, good) in health.selfTest)
          _line(key, value,
              good ? (key == 'profile' ? BpCore.phosphor : BpPen.pass)
                   : BpCore.phosphor),
        if (health.promptSeconds > 0)
          _line('a part takes',
              health.promptSeconds > 90
                  ? '~${(health.promptSeconds / 60).round()} min'
                  : '~${health.promptSeconds} s',
              BpCore.phosphor),
      ],
    );
  }

  Widget _line(String key, String value, Color tone, {bool pulsing = false}) {
    final row = Padding(
      padding: const EdgeInsets.only(bottom: BpSpace.snug),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.baseline,
        textBaseline: TextBaseline.alphabetic,
        children: [
          Text(key,
              style: TextStyle(
                  fontFamily: BpType.mono,
                  fontSize: BpType.label,
                  color: BpcadColors.inkDim)),
          // The dot leader. Drawn rather than typed, so it fills whatever
          // width the phone has instead of being a guessed number of dots.
          Expanded(
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: BpSpace.snug),
              child: Text('.' * 200,
                  maxLines: 1,
                  overflow: TextOverflow.clip,
                  style: TextStyle(
                      fontFamily: BpType.mono,
                      fontSize: BpType.label,
                      height: 1,
                      color: BpPen.dim)),
            ),
          ),
          Text(value,
              style: TextStyle(
                  fontFamily: BpType.mono,
                  fontSize: BpType.label,
                  color: tone,
                  fontFeatures: const [FontFeature.tabularFigures()])),
        ],
      ),
    );
    if (!pulsing || MediaQuery.of(context).disableAnimations) return row;
    return _Pulse(child: row);
  }

  Widget _unreachable() => Padding(
        padding: const EdgeInsets.only(bottom: BpSpace.base),
        child: GlassSurface(
          tint: GlassTint.warn,
          depth: GlassDepth.card,
          padding: const EdgeInsets.all(BpSpace.base),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text('The computer running bpcad is not answering',
                  style: TextStyle(
                      fontFamily: BpType.mono,
                      fontSize: BpType.label,
                      color: BpCore.screen)),
              const SizedBox(height: BpSpace.tight),
              Text(_problem!,
                  style: TextStyle(
                      fontFamily: BpType.prose,
                      fontSize: BpType.label,
                      height: 1.5,
                      color: BpcadColors.inkDim)),
              const SizedBox(height: BpSpace.snug),
              // WHAT TO DO, not just what went wrong. The whole geometry
              // engine is Python on a computer; the phone is a window onto it,
              // and that is worth saying once rather than leaving somebody to
              // conclude the app is broken.
              Text('bpcad builds parts on a computer, not on the phone. Start '
                  '`bpcad web` there and check both are on the same network. '
                  'Parts already downloaded stay readable.',
                  style: TextStyle(
                      fontFamily: BpType.prose,
                      fontSize: BpType.micro,
                      height: 1.55,
                      color: BpcadColors.inkFaint)),
            ],
          ),
        ),
      );

  Widget _start() => SizedBox(
        width: double.infinity,
        height: 48,
        child: FilledButton(
          // Enabled either way: a bpcad with no server still opens what is
          // already on the phone, and a dead button would say otherwise.
          onPressed: _done ? () => widget.onStart(_health) : null,
          child: Text(_problem == null ? 'Start' : 'Carry on anyway',
              style: const TextStyle(
                  fontFamily: BpType.mono, fontWeight: FontWeight.w600)),
        ),
      );
}

/// The graticule. The one flat surface in the design, along with the 3D
/// canvas - it is the ground, and glass sits on it rather than replacing it.
class _Graticule extends StatelessWidget {
  const _Graticule();

  @override
  Widget build(BuildContext context) =>
      const CustomPaint(size: Size.infinite, painter: _GridPainter());
}

class _GridPainter extends CustomPainter {
  const _GridPainter();

  /// 26px, the design's pitch on the app ground.
  static const double pitch = 26;

  @override
  void paint(Canvas canvas, Size size) {
    canvas.drawRect(Offset.zero & size, Paint()..color = BpCore.caseColor);
    final line = Paint()
      ..color = BpCore.grid
      ..strokeWidth = 1;
    for (double x = 0; x < size.width; x += pitch) {
      canvas.drawLine(Offset(x, 0), Offset(x, size.height), line);
    }
    for (double y = 0; y < size.height; y += pitch) {
      canvas.drawLine(Offset(0, y), Offset(size.width, y), line);
    }
  }

  @override
  bool shouldRepaint(_GridPainter oldDelegate) => false;
}

/// One amber hairline, sweeping down. Brief 6.6's single boot moment.
class _Sweep extends StatelessWidget {
  const _Sweep(this.controller);

  final AnimationController controller;

  @override
  Widget build(BuildContext context) {
    return IgnorePointer(
      child: AnimatedBuilder(
        animation: controller,
        builder: (context, _) {
          // The design's easing, as a curve rather than a linear slide: the
          // line accelerates in and eases out, which is what makes it read as
          // a scan rather than a loading bar.
          final t = const Cubic(.5, 0, .4, 1).transform(controller.value);
          return Align(
            alignment: Alignment(0, t * 2 - 1),
            child: Container(
              height: 1,
              decoration: BoxDecoration(
                gradient: LinearGradient(colors: [
                  BpCore.phosphor.withValues(alpha: 0),
                  BpCore.phosphor.withValues(alpha: 0.55),
                  BpCore.phosphor.withValues(alpha: 0),
                ]),
              ),
            ),
          );
        },
      ),
    );
  }
}

/// Opacity .25 → 1 → .25 over 1.4s, per the design, on the line that is still
/// resolving. Only ever one line at a time.
class _Pulse extends StatefulWidget {
  const _Pulse({required this.child});

  final Widget child;

  @override
  State<_Pulse> createState() => _PulseState();
}

class _PulseState extends State<_Pulse>
    with SingleTickerProviderStateMixin {
  late final AnimationController _controller = AnimationController(
    duration: const Duration(milliseconds: 1400),
    vsync: this,
  )..repeat(reverse: true);

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => FadeTransition(
        opacity: Tween<double>(begin: 0.25, end: 1.0).animate(_controller),
        child: widget.child,
      );
}
