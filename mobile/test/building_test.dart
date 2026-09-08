// The drawing on the building screen, looked at.
//
// THIS PROJECT'S RULE IS THAT NOTHING IS DONE UNTIL A PICTURE OF IT HAS BEEN
// GENERATED AND LOOKED AT. That was written about parts and height maps, and
// it applies just as well to a picture the app draws: a wireframe with its
// projection inverted, or a visor sweeping somewhere other than through the
// solid, is arithmetically valid and completely wrong, and no assertion about
// widget types would catch it.
//
// So these render the rig at the progress each stage reaches and write a
// golden. Run with `flutter test --update-goldens` after changing the drawing,
// then LOOK AT the files in test/goldens/ before committing them.
//
// WHY THE RIG IS ITS OWN WIDGET. The building screen calls the server the
// moment it is built, so with no server it is showing its failure panel within
// a frame and the drawing is never on screen at all. Pulling the drawing out
// is what makes it possible to see it here.

import 'package:bpcad_app/build_rig.dart';
import 'package:bpcad_app/tokens.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

/// One frame of the rig, on the plate, at a fixed size so the goldens are
/// comparable to each other.
Widget _frame(double progress) => MaterialApp(
      debugShowCheckedModeBanner: false,
      home: Scaffold(
        backgroundColor: BpCore.caseColor,
        body: Center(
          child: RepaintBoundary(
            child: SizedBox(
              width: 300,
              height: 300,
              child: Stack(
                children: [
                  const Positioned.fill(child: BuildPlate()),
                  Positioned.fill(child: BuildRig(progress: progress)),
                ],
              ),
            ),
          ),
        ),
      ),
    );

void main() {
  // The stage fractions the engine actually produces: five stages, so the
  // drawing is asked for exactly the states a real build passes through.
  for (final (label, progress) in const [
    ('start', 0.0),
    ('parsed', 0.2),
    ('solid', 0.6),
    ('done', 1.0),
  ]) {
    testWidgets('the rig draws at $label', (WidgetTester tester) async {
      await tester.pumpWidget(_frame(progress));
      // Past the stroke easing and a little way into the turn, so the golden
      // catches the wireframe mid-revolution rather than dead square on.
      await tester.pump(const Duration(milliseconds: 1200));

      await expectLater(
        find.byType(RepaintBoundary).first,
        matchesGoldenFile('goldens/rig_$label.png'),
      );
    });
  }

  testWidgets('reduced motion still shows how far the build has got',
      (WidgetTester tester) async {
    // NOT A BLANK PANEL. Somebody who has turned animation off still needs to
    // see the progress the drawing carries - it is the one motion on this
    // screen that means anything - so the wireframe is drawn at its real
    // fraction, parked, with no turn and no visor.
    await tester.pumpWidget(MediaQuery(
      data: const MediaQueryData(disableAnimations: true),
      child: _frame(0.6),
    ));
    await tester.pump(const Duration(milliseconds: 1200));

    await expectLater(
      find.byType(RepaintBoundary).first,
      matchesGoldenFile('goldens/rig_reduced_motion.png'),
    );

    // And it is genuinely still: pumping further must not change the frame,
    // or an animation is running that was asked not to.
    await tester.pump(const Duration(seconds: 3));
    await expectLater(
      find.byType(RepaintBoundary).first,
      matchesGoldenFile('goldens/rig_reduced_motion.png'),
    );
  });
}
