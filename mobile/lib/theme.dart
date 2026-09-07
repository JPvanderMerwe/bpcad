// One palette, shared with the web app to the byte.
//
// These are not chosen here. They are brief 11.2's tokens, the same values in
// bpcad/web/static/app.css, and the same ground the CPU rasteriser renders on
// (bpcad/gui/theme.py's VIEWPORT_BG). Change one and you must change all
// three: a render sitting on a different ground from the screen around it
// shows as a hard rectangle behind the part, which is exactly what it looked
// like before that was fixed.

import 'package:flutter/material.dart';

class BpcadColors {
  BpcadColors._();

  /// The build plate. Also render.raster's background, to the byte.
  static const Color bed = Color(0xFF101720);
  static const Color bedDeep = Color(0xFF0A0F16);
  static const Color edge = Color(0x2E96B4D2); // rgba(150,180,210,.18)

  static const Color ink = Color(0xFFE8EEF4);
  static const Color inkDim = Color(0xFF93A6B8);
  static const Color inkFaint = Color(0xFF5E7286);

  /// TWO ACCENTS, TWO JOBS, NEVER SWAPPED. Cyan says "this is live"; amber is
  /// the commit action and there is one per screen. Spending either on
  /// decoration is how an accent stops meaning anything.
  static const Color live = Color(0xFF5BC8D6);
  static const Color act = Color(0xFFF2A33C);
  static const Color pass = Color(0xFF6FC98A);
  static const Color fail = Color(0xFFE06060);
}

class BpcadText {
  BpcadText._();

  /// Every numeral in this product. Tabular, so a column of dimensions lines
  /// up and a 1 cannot be mistaken for a 7 at a glance - on a measuring
  /// instrument that is not a cosmetic point.
  static const TextStyle dimension = TextStyle(
    fontFamily: 'monospace',
    fontSize: 11.5,
    color: BpcadColors.live,
    fontFeatures: [FontFeature.tabularFigures()],
  );

  static const TextStyle fact = TextStyle(
    fontFamily: 'monospace',
    fontSize: 15,
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
        foregroundColor: const Color(0xFF17130A),
        // 44 logical pixels is the minimum hit target this product uses
        // everywhere; a thumb is not a mouse.
        minimumSize: const Size(0, 44),
        padding: const EdgeInsets.symmetric(horizontal: 18),
        textStyle: const TextStyle(fontSize: 15, fontWeight: FontWeight.w600),
        shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(11)),
      ),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: BpcadColors.bedDeep,
      hintStyle: const TextStyle(color: BpcadColors.inkFaint, fontSize: 15),
      contentPadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      border: OutlineInputBorder(
        borderRadius: BorderRadius.circular(11),
        borderSide: const BorderSide(color: BpcadColors.edge),
      ),
      enabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(11),
        borderSide: const BorderSide(color: BpcadColors.edge),
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(11),
        borderSide: const BorderSide(color: BpcadColors.live),
      ),
    ),
    progressIndicatorTheme: const ProgressIndicatorThemeData(
      color: BpcadColors.live,
      linearTrackColor: BpcadColors.edge,
    ),
  );
}
