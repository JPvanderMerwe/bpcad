// The marks, and the loading states. Design handoff section 8 and section 4.
//
// WHY THESE ARE DRAWN RATHER THAN AN ICON SET.
//
// The handoff is explicit: "the prototype draws its few marks as bordered CSS
// boxes rather than pulling an icon set, so nothing is faked". Every glyph in
// the design is a rectangle, a square, a slash, an arrow or a plus - because
// this is an instrument, and a rounded-corner camera pictogram from a general
// icon family reads as a consumer app.
//
// The first build used Material's set - grid_view, memory, photo_camera,
// search, close, arrow_back - and every one of them was a different drawing
// language from the rest of the screen. They are gone.
//
// ONE LOADING MARK FOR THE WHOLE PRODUCT.
//
// The caliper. It is in the web client, the building screen, and now every
// other place something is on its way - so it is never a question of which
// kind of waiting this is. A spinner in one place and a bar in another makes
// a user learn two things that mean the same thing.
//
// Every animation here stops under `disableAnimations`. The design says so of
// its own motion, and a loading mark is the one that runs longest.

import 'package:flutter/material.dart';

import 'theme.dart';
import 'tokens.dart';

/// The 2×2 grid of squares that means "your parts".
class GridMark extends StatelessWidget {
  const GridMark({super.key, required this.colour, this.size = 16});

  final Color colour;
  final double size;

  @override
  Widget build(BuildContext context) =>
      CustomPaint(size: Size.square(size), painter: _GridMarkPainter(colour));
}

class _GridMarkPainter extends CustomPainter {
  const _GridMarkPainter(this.colour);

  final Color colour;

  @override
  void paint(Canvas canvas, Size size) {
    final fill = Paint()..color = colour;
    // Four squares with a real gap, hard-cornered. Not a rounded grid glyph:
    // these are the same squares the status badges and the stage dots use.
    final s = size.width * 0.42;
    final gap = size.width - s * 2;
    for (final offset in [
      Offset.zero,
      Offset(s + gap, 0),
      Offset(0, s + gap),
      Offset(s + gap, s + gap),
    ]) {
      canvas.drawRect(offset & Size.square(s), fill);
    }
  }

  @override
  bool shouldRepaint(_GridMarkPainter old) => old.colour != colour;
}

/// A bordered square with an inner square: the machine.
///
/// The design's second tab is a circle outline; this is the same idea in the
/// squared vocabulary the rest of the data chrome uses, and it reads as a chip
/// rather than as a person - which is right, because the tab is about the
/// computer doing the work and not about an account.
class MachineMark extends StatelessWidget {
  const MachineMark({super.key, required this.colour, this.size = 16});

  final Color colour;
  final double size;

  @override
  Widget build(BuildContext context) => CustomPaint(
      size: Size.square(size), painter: _MachineMarkPainter(colour));
}

class _MachineMarkPainter extends CustomPainter {
  const _MachineMarkPainter(this.colour);

  final Color colour;

  @override
  void paint(Canvas canvas, Size size) {
    final line = Paint()
      ..color = colour
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.2;
    canvas.drawRect(Offset.zero & size, line);

    final inset = size.width * 0.3;
    canvas.drawRect(
        Rect.fromLTWH(inset, inset, size.width - inset * 2,
            size.height - inset * 2),
        Paint()..color = colour);

    // Four legs, like a chip. Two strokes a side is enough to read at 16px.
    for (final at in [size.width * 0.33, size.width * 0.67]) {
      canvas.drawLine(Offset(at, 0), Offset(at, -2.5), line);
      canvas.drawLine(
          Offset(at, size.height), Offset(at, size.height + 2.5), line);
    }
  }

  @override
  bool shouldRepaint(_MachineMarkPainter old) => old.colour != colour;
}

/// A bordered rectangle with a notch: a camera, in the design's own language.
class CameraMark extends StatelessWidget {
  const CameraMark({super.key, required this.colour, this.size = 16});

  final Color colour;
  final double size;

  @override
  Widget build(BuildContext context) => CustomPaint(
      size: Size(size, size * 0.75), painter: _CameraMarkPainter(colour));
}

class _CameraMarkPainter extends CustomPainter {
  const _CameraMarkPainter(this.colour);

  final Color colour;

  @override
  void paint(Canvas canvas, Size size) {
    final line = Paint()
      ..color = colour
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.2;
    canvas.drawRect(
        Rect.fromLTWH(0, size.height * 0.2, size.width, size.height * 0.8),
        line);
    // The viewfinder bump, and a square lens. No circle: the design has no
    // circles in its chrome.
    canvas.drawRect(
        Rect.fromLTWH(size.width * 0.3, 0, size.width * 0.4, size.height * 0.2),
        line);
    canvas.drawRect(
        Rect.fromCenter(
            center: Offset(size.width / 2, size.height * 0.6),
            width: size.width * 0.34,
            height: size.width * 0.34),
        line);
  }

  @override
  bool shouldRepaint(_CameraMarkPainter old) => old.colour != colour;
}

/// A glyph drawn as TYPE rather than as an icon.
///
/// The back arrow, the plus, the close and the search prefix are all single
/// characters in the design, set in the mono face like everything else. Using
/// the type means they inherit the interface's weight and colour instead of
/// being a foreign drawing beside it - and the search field's mark is a `/`,
/// which is the design's own prompt character and not a magnifier.
class TypeMark extends StatelessWidget {
  const TypeMark(this.glyph,
      {super.key, required this.colour, this.size = BpType.figure});

  const TypeMark.back({super.key, required this.colour})
      : glyph = '←',
        size = BpType.figure;

  const TypeMark.plus({super.key, required this.colour})
      : glyph = '+',
        size = 22;

  const TypeMark.close({super.key, required this.colour})
      : glyph = '×',
        size = BpType.figure;

  /// The design's search prefix: `/ Search parts and versions`.
  const TypeMark.search({super.key, required this.colour})
      : glyph = '/',
        size = BpType.body;

  final String glyph;
  final Color colour;
  final double size;

  @override
  Widget build(BuildContext context) => Text(glyph,
      style: TextStyle(
          fontFamily: BpType.mono,
          fontSize: size,
          height: 1,
          color: colour));
}

/// THE ONE LOADING MARK. Three amber bars, measuring.
///
/// Borrowed from the web client on purpose, and used for every wait in the
/// app: the library arriving, a part opening, a render on its way, a mesh
/// being fetched. One "working" mark means a user never has to learn which
/// kind of waiting a new shape stands for.
class Caliper extends StatefulWidget {
  const Caliper({super.key, this.colour = BpCore.phosphor, this.height = 16});

  final Color colour;
  final double height;

  @override
  State<Caliper> createState() => _CaliperState();
}

class _CaliperState extends State<Caliper>
    with SingleTickerProviderStateMixin {
  late final AnimationController _controller = AnimationController(
    duration: const Duration(milliseconds: 1050),
    vsync: this,
  )..repeat();

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final low = widget.height * 0.32;
    if (MediaQuery.of(context).disableAnimations) {
      return _Bars(
          heights: [low, widget.height, low], colour: widget.colour,
          box: widget.height);
    }
    return AnimatedBuilder(
      animation: _controller,
      builder: (context, _) {
        double bar(double offset) {
          final t = (_controller.value + offset) % 1.0;
          // A triangle wave, so each bar rises and falls rather than
          // snapping - the design's own 1.05s with a 0.14 stagger.
          final wave = 1 - (t * 2 - 1).abs();
          return low + wave * (widget.height - low);
        }

        return _Bars(
          heights: [bar(0), bar(.14), bar(.28)],
          colour: widget.colour,
          box: widget.height,
        );
      },
    );
  }
}

class _Bars extends StatelessWidget {
  const _Bars({required this.heights, required this.colour, required this.box});

  final List<double> heights;
  final Color colour;
  final double box;

  @override
  Widget build(BuildContext context) => SizedBox(
        height: box,
        child: Row(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.end,
          children: [
            for (final height in heights)
              Container(
                width: 3,
                height: height,
                margin: const EdgeInsets.symmetric(horizontal: 1.5),
                color: colour,
              ),
          ],
        ),
      );
}

/// A wait with the caliper and a word for what is being waited on.
///
/// The word is not optional. "Loading" tells nobody anything; "rendering the
/// part" says which of the several things that take time is happening, and on
/// a CPU machine that is the difference between patience and a force-quit.
class Waiting extends StatelessWidget {
  const Waiting({super.key, required this.what, this.tight = false});

  final String what;
  final bool tight;

  @override
  Widget build(BuildContext context) => Padding(
        padding: EdgeInsets.all(tight ? BpSpace.base : BpSpace.hall),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Caliper(),
            const SizedBox(height: BpSpace.base),
            Text(what,
                textAlign: TextAlign.center,
                style: const TextStyle(
                    fontFamily: BpType.mono,
                    fontSize: BpType.label,
                    color: BpcadColors.inkDim)),
          ],
        ),
      );
}

/// A thumbnail that has not arrived: a slow amber sweep across the graticule.
///
/// Not a grey block. The design's ground is a ruled plate and a card's
/// thumbnail band keeps its own finer graticule, so the honest placeholder is
/// that plate with a light moving over it - which also says "coming" rather
/// than "empty", and the two are easy to confuse on a dark screen.
class Skeleton extends StatefulWidget {
  const Skeleton({super.key});

  @override
  State<Skeleton> createState() => _SkeletonState();
}

class _SkeletonState extends State<Skeleton>
    with SingleTickerProviderStateMixin {
  late final AnimationController _controller = AnimationController(
    duration: const Duration(milliseconds: 1300),
    vsync: this,
  )..repeat();

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    // REDUCED MOTION MEANS A STILL INDICATOR, NOT NO INDICATOR.
    //
    // This returned nothing at all, so on a phone with animations turned off -
    // which every phone used for adb debugging has, because enabling developer
    // options is how the scales get set to 0 - a thumbnail that was still
    // rendering looked exactly like one that had failed.
    //
    // Suppressing MOTION is the accessibility contract. Suppressing the
    // information is a different thing, and the design's own rule is that a
    // wait must be stated.
    if (MediaQuery.of(context).disableAnimations) {
      return const Center(
        child: Text('rendering',
            style: TextStyle(
                fontFamily: BpType.mono,
                fontSize: 9.5,
                color: BpcadColors.inkFaint)),
      );
    }
    return AnimatedBuilder(
      animation: _controller,
      builder: (context, _) => Align(
        alignment: Alignment(_controller.value * 3 - 1.5, 0),
        child: FractionallySizedBox(
          widthFactor: 0.35,
          child: DecoratedBox(
            decoration: BoxDecoration(
              gradient: LinearGradient(colors: [
                BpCore.phosphor.withValues(alpha: 0),
                BpCore.phosphor.withValues(alpha: 0.07),
                BpCore.phosphor.withValues(alpha: 0),
              ]),
            ),
          ),
        ),
      ),
    );
  }
}


/// A chip: bordered, hard-cornered, amber when selected.
///
/// `BpChip`, not `Chip`: Material exports a `Chip` of its own, and a name that
/// collides with one in `flutter/material.dart` is ambiguous at every call
/// site that imports both - which is every screen.
///
/// ONE WIDGET, BECAUSE THE SAME MISTAKE WAS MADE THREE TIMES.
///
/// A Container with a non-null `alignment` sizes itself as large as its
/// constraints allow. Inside a Row in a horizontal scroll view the width is
/// unbounded, so it hugs its child and looks right - which is why the library
/// filter chips were fine. Inside a `Wrap` the width is bounded by the
/// parent, so every chip became a full-width row: the viewport pills stacked
/// down the middle of the part, and then the composer's starting points and
/// material chips did it again in the next commit.
///
/// This has no `alignment` and no `constraints`. It is padding and a border,
/// so it is the width of its label wherever it is put, and the tap target
/// clears the brief's 44 × 32 floor on the padding alone.
class BpChip extends StatelessWidget {
  const BpChip({
    super.key,
    required this.label,
    required this.onTap,
    this.selected = false,
    this.tone,
  });

  final String label;
  final VoidCallback onTap;
  final bool selected;

  /// Overrides the selected colour, for a chip that means something other
  /// than "chosen" - a reference body's cyan, say.
  final Color? tone;

  @override
  Widget build(BuildContext context) {
    final accent = tone ?? BpCore.phosphor;
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(BpRadius.control),
      child: DecoratedBox(
        decoration: BoxDecoration(
          color: selected
              ? accent.withValues(alpha: 0.18)
              : Colors.transparent,
          border: Border.all(color: selected ? accent : BpcadColors.edge),
          borderRadius: BorderRadius.circular(BpRadius.control),
        ),
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 13, vertical: 9),
          child: Text(label,
              style: TextStyle(
                  fontFamily: BpType.mono,
                  fontSize: BpType.label,
                  height: 1.15,
                  color: selected ? accent : BpcadColors.inkDim)),
        ),
      ),
    );
  }
}
