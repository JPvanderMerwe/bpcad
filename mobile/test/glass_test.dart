// The glass primitive. Design handoff section 6, task C0.
//
// C0's acceptance clause is two claims: a token change moves the same surface
// on web and native, and the no-blur fallback renders the flat `bezel`
// variant. The first half is checked in Python, where both exports can be
// compared against the one source (tests/test_tokens.py). This file is the
// half that needs a widget tree: that GlassSurface actually composes the
// token it was handed, and that the fallback is a different SURFACE rather
// than the same one with the blur switched off.
//
// These are not tests of how the glass looks. They are tests of the rule that
// keeps it consistent - one primitive, tokens only, and a fallback that is a
// real fallback.

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:bpcad_app/glass.dart';
import 'package:bpcad_app/theme.dart';
import 'package:bpcad_app/tokens.dart';

/// Wraps a surface in the minimum tree it needs, with control over the
/// accessibility flags the primitive reads.
Widget harness(Widget child, {bool highContrast = false}) {
  return MediaQuery(
    data: MediaQueryData(highContrast: highContrast),
    child: Directionality(
      textDirection: TextDirection.ltr,
      child: child,
    ),
  );
}

BoxDecoration decorationOf(WidgetTester tester) {
  // The outermost DecoratedBox the primitive builds. `first` because the
  // ambient light wraps its own, and a blurred surface sits inside a
  // ClipRRect - the pane is the one carrying a border.
  final boxes = tester.widgetList<DecoratedBox>(find.byType(DecoratedBox));
  return boxes
      .map((box) => box.decoration as BoxDecoration)
      .firstWhere((decoration) => decoration.border != null);
}

void main() {
  testWidgets('a surface composes the depth it was given, not a chosen colour',
      (WidgetTester tester) async {
    await tester.pumpWidget(harness(
      const GlassSurface(depth: GlassDepth.card, child: SizedBox(width: 40)),
    ));

    final decoration = decorationOf(tester);
    expect(decoration.color, BpGlass.tint(GlassDepth.card.alpha));
    expect(decoration.borderRadius,
        BorderRadius.circular(GlassDepth.card.radius));

    // The blur is the depth's, to the sigma. A hand-typed number here is the
    // start of the two clients drifting apart.
    final filter = tester.widget<BackdropFilter>(find.byType(BackdropFilter));
    expect(filter.filter.toString(), contains('${GlassDepth.card.blur}'));
  });

  testWidgets('the depths are depths: a float surface is denser than a panel',
      (WidgetTester tester) async {
    // THE ONE RULE THAT KEEPS GLASS LEGIBLE. A surface over content has to be
    // denser than one over the ground, because its text must hold contrast
    // against the brightest thing the render behind it can produce. If this
    // ever inverts, the bottom sheet becomes more transparent than a side
    // panel and the numbers on it stop being readable over a bright part.
    await tester.pumpWidget(harness(
      const GlassSurface(depth: GlassDepth.panel, child: SizedBox()),
    ));
    final panel = decorationOf(tester).color!;

    await tester.pumpWidget(harness(
      const GlassSurface(depth: GlassDepth.float, child: SizedBox()),
    ));
    final float = decorationOf(tester).color!;

    expect(float.a, greaterThan(panel.a));
  });

  testWidgets('blur off falls back to the flat fill, not a paler glass',
      (WidgetTester tester) async {
    // C0'S ACCEPTANCE CLAUSE. The fallback is a DIFFERENT SURFACE - the flat
    // `bezel` at full opacity - because a translucent tint with no blur
    // behind it is not a softer version of the design, it is muddy grey text
    // on grey. Getting this wrong looks like the glass "nearly working".
    await tester.pumpWidget(harness(
      const GlassSurface(
          depth: GlassDepth.float, blur: false, child: SizedBox()),
    ));

    final decoration = decorationOf(tester);
    expect(decoration.color, BpcadColors.bezel);
    expect(decoration.color!.a, 1.0, reason: 'the flat fill must be opaque');
    expect(find.byType(BackdropFilter), findsNothing,
        reason: 'blur: false still built a BackdropFilter');
  });

  testWidgets('high contrast flattens every surface without being asked',
      (WidgetTester tester) async {
    // Flutter surfaces no "reduce transparency" flag, so high contrast is the
    // closest honest signal: somebody who asked for it is not well served by
    // a translucent pane over a busy render.
    await tester.pumpWidget(harness(
      const GlassSurface(child: SizedBox()),
      highContrast: true,
    ));

    expect(decorationOf(tester).color, BpcadColors.bezel);
    expect(find.byType(BackdropFilter), findsNothing);
  });

  testWidgets('a tinted surface keeps its hue and its border outruns its fill',
      (WidgetTester tester) async {
    await tester.pumpWidget(harness(
      const GlassSurface(tint: GlassTint.warn, child: SizedBox()),
    ));

    final decoration = decorationOf(tester);
    expect(decoration.color, GlassTint.warn.fill);
    // The border takes the tint at 35-70% while the fill takes it at 10-18%.
    // One alpha for both gives either an invisible border or a fill that
    // swamps the text sitting on it.
    expect(decoration.border!.top.color.a,
        greaterThan(decoration.color!.a));
    expect(decoration.color!.r, GlassTint.warn.color.r);
  });

  testWidgets('the ambient light paints both washes over the ground',
      (WidgetTester tester) async {
    // Not decoration: a blur with nothing behind it to pick up renders as
    // flat grey and every panel becomes the same slab. Two washes, from
    // opposite corners, over the app ground.
    await tester.pumpWidget(harness(
      const AmbientLight(child: SizedBox(width: 200, height: 400)),
    ));

    final gradients = tester
        .widgetList<DecoratedBox>(find.byType(DecoratedBox))
        .map((box) => (box.decoration as BoxDecoration).gradient)
        .whereType<RadialGradient>()
        .toList();

    expect(gradients.length, 2, reason: 'the design specifies two washes');
    expect(gradients[0].colors.first.r, BpAmbient.wash0.r);
    expect(gradients[1].colors.first.r, BpAmbient.wash1.r);
    // Each fades to nothing rather than to a colour, or it would band.
    for (final gradient in gradients) {
      expect(gradient.colors.last.a, 0.0);
    }
  });

  testWidgets('the ambient light is suppressed under high contrast',
      (WidgetTester tester) async {
    await tester.pumpWidget(harness(
      const AmbientLight(child: SizedBox()),
      highContrast: true,
    ));

    expect(find.byType(DecoratedBox), findsNothing);
    expect(tester.widget<ColoredBox>(find.byType(ColoredBox)).color,
        BpcadColors.bed);
  });
}
