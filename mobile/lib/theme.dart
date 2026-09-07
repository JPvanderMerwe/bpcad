// One palette, and it is not chosen here.
//
// Every value on this screen comes from design/tokens.json through
// tools/tokens.py, which writes tokens.dart beside this file and tokens.css
// for the web client from the same source. The design handoff calls a colour
// that differs between web and native a bug rather than an inconsistency, and
// tests/test_tokens.py fails if either export is stale.
//
// So this file holds NO hex values. What it holds is the mapping from this
// app's own vocabulary to the tokens - by ROLE, not by name.
//
// THE ONE TRAP IN THAT MAPPING. This app's `live` is the CYAN that says "this
// is measured data", and the token called `dim` is grey secondary text. A
// name-for-name mapping would have turned every dimension figure grey and
// every label cyan, and both would have looked deliberate. `live` maps to
// `pen-ref`, which is the design's own word for the same job.
//
// The CPU rasteriser's ground (bpcad/gui/theme.py's VIEWPORT_BG) has to agree
// with `bed` or a render sits on a different ground from the screen around it
// and shows as a hard rectangle behind the part - which is exactly what it
// looked like before that was fixed.

import 'package:flutter/material.dart';

import 'tokens.dart';

class BpcadColors {
  BpcadColors._();

  /// The app ground. Also render.raster's background, to the byte.
  static const Color bed = BpCore.caseColor;

  /// The graticule ruled over the ground - `case` lightened.
  static const Color grid = BpCore.grid;

  /// The flat fill for a surface that cannot carry a blur.
  static const Color bezel = BpCore.bezel;

  /// Hairlines on flat chrome. `etch` is the token for exactly this; the
  /// translucent one on glass is BpGlass.hairline().
  static const Color edge = BpCore.etch;

  static const Color ink = BpCore.screen;
  static const Color inkDim = BpCore.dim;

  /// The faintest text is the pen set's construction-line grey, borrowed
  /// deliberately: a version string IS construction geometry.
  static const Color inkFaint = BpPen.dim;

  /// TWO ACCENTS, TWO JOBS, NEVER SWAPPED. Cyan says "this is measured";
  /// amber is the commit action and there is one per screen. Spending either
  /// on decoration is how an accent stops meaning anything.
  static const Color live = BpPen.ref;
  static const Color act = BpCore.phosphor;
  static const Color pass = BpPen.pass;
  static const Color fail = BpPen.fail;
}

class BpcadText {
  BpcadText._();

  /// Every numeral in this product. Tabular, so a column of dimensions lines
  /// up and a 1 cannot be mistaken for a 7 at a glance - on a measuring
  /// instrument that is not a cosmetic point.
  static const TextStyle dimension = TextStyle(
    fontFamily: BpType.mono,
    fontSize: BpType.micro,
    color: BpcadColors.live,
    fontFeatures: [FontFeature.tabularFigures()],
  );

  static const TextStyle fact = TextStyle(
    fontFamily: BpType.mono,
    fontSize: BpType.reading,
    color: BpcadColors.live,
    fontFeatures: [FontFeature.tabularFigures()],
  );
}

ThemeData bpcadTheme() {
  const scheme = ColorScheme.dark(
    surface: BpcadColors.bed,
    primary: BpcadColors.live,
    secondary: BpcadColors.act,
    error: BpcadColors.fail,
    onSurface: BpcadColors.ink,
  );

  // Data chrome keeps the hard radii and floating surfaces get the soft ones.
  // Buttons and fields are controls, so they take `control`.
  final control = BorderRadius.circular(BpRadius.control);

  return ThemeData(
    useMaterial3: true,
    colorScheme: scheme,
    scaffoldBackgroundColor: BpcadColors.bed,
    canvasColor: BpcadColors.bed,
    appBarTheme: const AppBarTheme(
      backgroundColor: BpcadColors.bed,
      surfaceTintColor: Colors.transparent,
      elevation: 0,
      foregroundColor: BpcadColors.ink,
    ),
    textTheme: const TextTheme().apply(
      bodyColor: BpcadColors.ink,
      displayColor: BpcadColors.ink,
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        backgroundColor: BpcadColors.act,
        // `case` on phosphor, which is what the design says plainly. The old
        // value was a hand-darkened brown that existed nowhere else.
        foregroundColor: BpCore.caseColor,
        // The brief pins 44 logical pixels as the minimum hit target
        // everywhere; a thumb is not a mouse.
        minimumSize: const Size(0, BpMetric.tap),
        padding: const EdgeInsets.symmetric(horizontal: BpSpace.wide),
        textStyle: const TextStyle(
            fontSize: BpType.reading, fontWeight: FontWeight.w600),
        shape: RoundedRectangleBorder(borderRadius: control),
      ),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      // A field WELL, which the design makes glass - but an InputDecoration
      // cannot carry a BackdropFilter, so it takes the flat fill. A field
      // wrapped in GlassSurface sets `filled: false` and lets the pane show.
      fillColor: BpcadColors.bezel,
      hintStyle: const TextStyle(
          color: BpcadColors.inkFaint, fontSize: BpType.reading),
      contentPadding: const EdgeInsets.symmetric(
          horizontal: BpSpace.base, vertical: BpSpace.base),
      border: OutlineInputBorder(
        borderRadius: control,
        borderSide: const BorderSide(color: BpcadColors.edge),
      ),
      enabledBorder: OutlineInputBorder(
        borderRadius: control,
        borderSide: const BorderSide(color: BpcadColors.edge),
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: control,
        // The focus ring is phosphor: brief 6.7 wants keyboard focus visible,
        // and amber is the one colour that reads as "this is where you are".
        borderSide: const BorderSide(color: BpcadColors.act),
      ),
    ),
    sliderTheme: const SliderThemeData(
      activeTrackColor: BpcadColors.act,
      inactiveTrackColor: BpcadColors.edge,
      thumbColor: BpcadColors.act,
      trackHeight: 2,
      // A 12px SQUARE THUMB, NOT MATERIAL'S CIRCLE.
      //
      // The handoff states the reason rather than the taste: soft radii belong
      // to floating SURFACES, and 0 stays on DATA marks - check marks, status
      // squares, progress bars and slider thumbs. "That contrast is the point,
      // and it is what stops the glass reading as a generic consumer app."
      //
      // Material's default is a 20dp circle, so leaving it alone lost both
      // halves at once: the wrong shape and twice the size.
      thumbShape: SquareSliderThumb(),
      overlayShape: RoundSliderOverlayShape(overlayRadius: 20),
    ),
    progressIndicatorTheme: const ProgressIndicatorThemeData(
      // Progress is a commit in flight, so it is amber, and its track is the
      // etch hairline. 2px: it is a data mark, not a decoration.
      color: BpcadColors.act,
      linearTrackColor: BpcadColors.edge,
      linearMinHeight: 2,
    ),
  );
}


/// A square slider thumb, 12px, per the design.
///
/// Written out because Flutter ships circles only. It is the same twelve
/// pixels the web client's `input[type=range]::-webkit-slider-thumb` uses, so
/// a parameter row looks the same on both clients - which is the whole reason
/// the tokens exist.
class SquareSliderThumb extends SliderComponentShape {
  const SquareSliderThumb({this.side = 12});

  final double side;

  @override
  Size getPreferredSize(bool isEnabled, bool isDiscrete) =>
      Size(side, side);

  @override
  void paint(
    PaintingContext context,
    Offset center, {
    required Animation<double> activationAnimation,
    required Animation<double> enableAnimation,
    required bool isDiscrete,
    required TextPainter labelPainter,
    required RenderBox parentBox,
    required SliderThemeData sliderTheme,
    required TextDirection textDirection,
    required double value,
    required double textScaleFactor,
    required Size sizeWithOverflow,
  }) {
    final paint = Paint()
      ..color = sliderTheme.thumbColor ?? BpcadColors.act
      ..style = PaintingStyle.fill;

    // No radius at all - Radius.zero rather than a small one. A 1px round is
    // not a square with softer corners, it is a circle nobody can see the
    // point of.
    context.canvas.drawRect(
      Rect.fromCenter(center: center, width: side, height: side),
      paint,
    );
  }
}
