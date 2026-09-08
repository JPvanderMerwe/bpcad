// THE MODEL BEING DRAWN AND TURNED, on the plate it will be printed on.
//
// Its own file for two reasons. It is a self-contained drawing that knows
// nothing about jobs, events or HTTP - and it is the only part of the
// building screen that can be LOOKED AT without a server, which matters:
// this project's rule is that no part is done until a picture of it has been
// generated and looked at, and the same goes for a picture the app draws.
// See test/building_test.dart, whose goldens are that look.

import 'dart:math' as math;

import 'package:flutter/material.dart';

import 'tokens.dart';

/// The build plate, ruled. Static, and behind everything that moves.
///
/// It was a graticule with a 2px amber bar travelling across the whole panel.
/// The bar has moved onto the object itself - see [_Rig] - because a scan
/// that sweeps the panel is a screen effect, and one that descends through
/// the solid is the machine looking at the thing it is making.
class BuildPlate extends StatelessWidget {
  const BuildPlate({super.key});

  @override
  Widget build(BuildContext context) =>
      CustomPaint(size: Size.infinite, painter: _PlatePainter());
}

class _PlatePainter extends CustomPainter {
  /// 26px, the design's pitch on the app ground - the same as the boot
  /// screen's, because it is the same plate.
  static const double pitch = 26;

  @override
  void paint(Canvas canvas, Size size) {
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
  bool shouldRepaint(_PlatePainter oldDelegate) => false;
}

/// An isometric wireframe, turning on the plate, with a visor descending
/// through it - and stroked on as the build reports progress.
///
/// THREE MOTIONS, AND ONLY ONE OF THEM CARRIES INFORMATION.
///
/// `progress` is the fraction of the outline to draw and it comes from the
/// stage list, so by "Built the solid" the box is closed and by the checks it
/// has its bore. The TURN and the VISOR carry nothing and are not pretending
/// to: they are what makes the panel read as a machine at work rather than a
/// diagram that has stopped, on a screen that otherwise does not move for
/// ninety seconds at a stretch.
class BuildRig extends StatefulWidget {
  const BuildRig({super.key, required this.progress});

  final double progress;

  @override
  State<BuildRig> createState() => _RigState();
}

class _RigState extends State<BuildRig> with TickerProviderStateMixin {
  /// SLOW. 18 seconds a revolution: fast enough that it is plainly turning,
  /// slow enough that it never reads as a spinner. A part being made is not a
  /// thing being loaded.
  late final AnimationController _spin = AnimationController(
    duration: const Duration(seconds: 18),
    vsync: this,
  )..repeat();

  /// 2.6 seconds, which is the design's own pass timing - kept exactly,
  /// because it is the one number the design gives for this motion.
  late final AnimationController _visor = AnimationController(
    duration: const Duration(milliseconds: 2600),
    vsync: this,
  )..repeat();

  /// The stages arrive minutes apart, so the stroke is eased between them
  /// rather than snapping - a jump would read as a glitch.
  late final AnimationController _grow = AnimationController(
    duration: const Duration(milliseconds: 900),
    vsync: this,
  );
  late double _shown = _floor;

  /// Never zero. A screen that says "building" over an empty plate for the
  /// first ninety seconds looks like a screen that failed to start, so the
  /// footprint is on from the beginning.
  static const double _floor = 0.18;

  @override
  void initState() {
    super.initState();
    _grow.value = 1;
  }

  @override
  void didUpdateWidget(BuildRig old) {
    super.didUpdateWidget(old);
    if (old.progress == widget.progress) return;
    _shown = _target(old.progress);
    _grow.forward(from: 0);
  }

  double _target(double progress) => _floor + progress * (1 - _floor);

  @override
  void dispose() {
    _spin.dispose();
    _visor.dispose();
    _grow.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final to = _target(widget.progress);
    final still = MediaQuery.of(context).disableAnimations;

    // REDUCED MOTION GETS THE DRAWING, NOT NOTHING. Somebody who has turned
    // animation off still needs to see how far the build has got, so the
    // wireframe is drawn at its real progress, parked at a readable angle,
    // with no turn and no visor.
    if (still) {
      return CustomPaint(
        painter: _RigPainter(drawn: to, spin: 0.06, visor: null),
      );
    }

    return AnimatedBuilder(
      animation: Listenable.merge([_spin, _visor, _grow]),
      builder: (context, _) {
        final drawn = _shown +
            (to - _shown) * Curves.easeOutCubic.transform(_grow.value);
        return CustomPaint(
          painter: _RigPainter(
            drawn: drawn,
            spin: _spin.value,
            visor: _visor.value,
          ),
        );
      },
    );
  }
}

class _RigPainter extends CustomPainter {
  const _RigPainter({
    required this.drawn,
    required this.spin,
    required this.visor,
  });

  /// The fraction of the outline that has been stroked. From the stages.
  final double drawn;

  /// Turn about the vertical, 0..1 of a revolution.
  final double spin;

  /// Where the visor is in its descent, 0..1, or null for no visor at all.
  final double? visor;

  /// A 2 x 2 x 1 slab. The bore's radius, and how far the visor overhangs the
  /// solid - a scanning frame that stopped exactly at the corners would read
  /// as part of the object.
  static const double _h = 1.0;
  static const double _bore = 0.45;
  static const double _reach = 1.42;

  /// The isometric projection this product uses everywhere: azimuth 315,
  /// elevation 26, with the model turning under it. Written out rather than
  /// borrowed from the renderer, because this is a drawing of nothing in
  /// particular and does not belong in the pipeline that draws real parts.
  Offset _at(double x, double y, double z, Size size, double scale) {
    const cos30 = 0.8660254;
    final angle = spin * 2 * math.pi;
    final ca = math.cos(angle), sa = math.sin(angle);
    // Turn in plan, then project. Turning the model under a fixed camera
    // rather than orbiting the camera keeps the plate and the light still,
    // which is what a turntable is.
    final rx = x * ca - y * sa;
    final ry = x * sa + y * ca;
    final sx = (rx - ry) * cos30;
    final sy = (rx + ry) * 0.5 - z;
    return Offset(size.width / 2 + sx * scale, size.height / 2 + sy * scale);
  }

  @override
  void paint(Canvas canvas, Size size) {
    final scale = size.shortestSide / 6.2;
    Offset at(double x, double y, double z) => _at(x, y, z, size, scale);

    // The edges in the order a solid is actually made: the footprint first,
    // then the verticals, then the top face, then the bore. That order is the
    // engine's, and it is why the drawing fills in the way it does.
    final footprint = <(Offset, Offset)>[
      (at(-1, -1, 0), at(1, -1, 0)),
      (at(1, -1, 0), at(1, 1, 0)),
      (at(1, 1, 0), at(-1, 1, 0)),
      (at(-1, 1, 0), at(-1, -1, 0)),
    ];
    final verticals = <(Offset, Offset)>[
      (at(-1, -1, 0), at(-1, -1, _h)),
      (at(1, -1, 0), at(1, -1, _h)),
      (at(1, 1, 0), at(1, 1, _h)),
      (at(-1, 1, 0), at(-1, 1, _h)),
    ];
    final top = <(Offset, Offset)>[
      (at(-1, -1, _h), at(1, -1, _h)),
      (at(1, -1, _h), at(1, 1, _h)),
      (at(1, 1, _h), at(-1, 1, _h)),
      (at(-1, 1, _h), at(-1, -1, _h)),
    ];

    final segments = <(Offset, Offset)>[...footprint, ...verticals, ...top];

    // The bore, as a ring on the top face. Last, because a cut comes after
    // the solid it is cut from - which is the order the engine works in too.
    const steps = 40;
    for (var i = 0; i < steps; i++) {
      final a0 = i / steps * 2 * math.pi;
      final a1 = (i + 1) / steps * 2 * math.pi;
      segments.add((
        at(_bore * math.cos(a0), _bore * math.sin(a0), _h),
        at(_bore * math.cos(a1), _bore * math.sin(a1), _h),
      ));
    }

    final count = (segments.length * drawn.clamp(0.0, 1.0)).floor();
    final line = Paint()
      ..color = BpCore.screen
      ..strokeWidth = 1.6
      ..strokeCap = StrokeCap.round;

    for (var i = 0; i < count && i < segments.length; i++) {
      canvas.drawLine(segments[i].$1, segments[i].$2, line);
    }

    // The segment currently being drawn, in amber. One moving mark, and it is
    // what makes the drawing read as being made rather than as being revealed.
    if (count < segments.length) {
      canvas.drawLine(
        segments[count].$1,
        segments[count].$2,
        Paint()
          ..color = BpCore.phosphor
          ..strokeWidth = 2
          ..strokeCap = StrokeCap.round,
      );
    }

    if (visor != null) _paintVisor(canvas, at, visor!);
  }

  /// THE VISOR, COMING DOWN THROUGH THE PART.
  ///
  /// A frame at one height, descending from just above the solid to the
  /// plate, and marking every vertical edge it crosses on the way. That is
  /// what the design's amber pass becomes when it belongs to the object
  /// rather than to the panel: the pass used to sweep the whole screen, which
  /// is a screen effect - this is a machine looking at the thing it is making.
  ///
  /// It fades in at the top of its travel and out at the bottom, so the reset
  /// is a scan ending rather than a line jumping back up.
  void _paintVisor(Canvas canvas, Offset Function(double, double, double) at,
      double phase) {
    // Starts a little above the top face and ends a little below the plate,
    // so nothing pops into existence on the solid itself.
    final z = 1.18 - phase * 1.36;

    // Fade over the first and last eighth of the travel.
    final ends = phase < 0.12
        ? phase / 0.12
        : phase > 0.88
            ? (1 - phase) / 0.12
            : 1.0;
    final alpha = (ends).clamp(0.0, 1.0);
    if (alpha <= 0.01) return;

    final frame = Paint()
      ..color = BpCore.phosphor.withValues(alpha: 0.55 * alpha)
      ..strokeWidth = 1.4
      ..strokeCap = StrokeCap.round;

    final corners = [
      at(-_reach, -_reach, z),
      at(_reach, -_reach, z),
      at(_reach, _reach, z),
      at(-_reach, _reach, z),
    ];
    for (var i = 0; i < corners.length; i++) {
      canvas.drawLine(corners[i], corners[(i + 1) % corners.length], frame);
    }

    // WHERE IT CROSSES AN EDGE, IT MARKS THE CROSSING. Four small squares
    // riding down the four verticals - hard-cornered, because a data mark
    // keeps the squared radii, and this is the part of the motion that reads
    // as measurement rather than as light.
    if (z < 0 || z > _h) return;
    final mark = Paint()..color = BpCore.phosphor.withValues(alpha: alpha);
    for (final (x, y) in const [(-1.0, -1.0), (1.0, -1.0), (1.0, 1.0), (-1.0, 1.0)]) {
      final p = at(x, y, z);
      canvas.drawRect(
          Rect.fromCenter(center: p, width: 4.5, height: 4.5), mark);
    }
  }

  @override
  bool shouldRepaint(_RigPainter old) =>
      old.drawn != drawn || old.spin != spin || old.visor != visor;
}
