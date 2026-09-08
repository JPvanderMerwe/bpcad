// The composer, and the one input the phone has that the computer does not.
//
// WHAT THESE GUARD. A reference photo is scaleless: everything the server
// reads off it is in pixels, and the only way it becomes millimetres is one
// real dimension from whoever is holding the object. Two ways that rule can
// be broken from this side - showing a pixel figure as though it were a
// measurement, and writing a plausible number into the user's own sentence -
// and both are cheap mistakes to make in a later edit, so both are pinned.

import 'package:bpcad_app/api.dart';
import 'package:bpcad_app/composer_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('a reference photo', () {
    test('comes back measured, in pixels, and says it needs a scale', () {
      // The server's own payload, as /api/upload returns it.
      final reference = Reference.fromJson({
        'path': '/home/x/library/uploads/ref-1757000000000.jpg',
        'name': 'ref-1757000000000.jpg',
        'bytes': 812345,
        'type': 'image/jpeg',
        'measured': {
          'background_cut': 41.2,
          'width_px': 638,
          'height_px': 684,
          'aspect': 0.93275,
          'silhouette': 'L17 R654 T13 B696 (638 x 684 px)',
        },
        'note': '',
        'needs_scale': true,
      });

      expect(reference.separated, isTrue);
      // PX, IN THE STRING. Not a bare pair of numbers that a reader could
      // take for millimetres on a screen where every other figure is one.
      expect(reference.extentPx, '638 × 684 px');
      expect(reference.aspect, '0.933');
      expect(reference.needsScale, isTrue);
      expect(reference.weight, '793 kB');
      // The path is the server's, and it is the only thing handed to a build.
      expect(reference.path, endsWith('ref-1757000000000.jpg'));
    });

    test('that separated nothing says so instead of reading as zero', () {
      // An object touching the border of the frame fails the silhouette cut.
      // The server measures on arrival precisely so this is known in a second
      // rather than after a build, and the card must show the reason - not a
      // "0 × 0 px" that looks like a measurement of a very small thing.
      final reference = Reference.fromJson({
        'path': '/home/x/library/uploads/ref-2.png',
        'name': 'ref-2.png',
        'bytes': 2200000,
        'type': 'image/png',
        'measured': const <String, dynamic>{},
        'note': 'nothing separated from the background at a cut of 38.0. '
            'The image may be inverted, or the object may touch the border.',
        'needs_scale': false,
      });

      expect(reference.separated, isFalse);
      expect(reference.extentPx, isNull);
      expect(reference.aspect, isNull);
      expect(reference.note, contains('touch the border'));
      expect(reference.weight, '2.1 MB');
    });
  });

  group('asking for the one dimension a photo cannot give', () {
    test('writes the sentence and leaves the number blank', () {
      final written = scaleSentence(
          'A clamp that fits this pipe', 'The overall width is ');

      expect(written.text, 'A clamp that fits this pipe. '
          'The overall width is  mm.');
      // THE CURSOR SITS IN THE GAP. That gap is the whole point: the app
      // writes the grammar and the user writes the measurement.
      // lastIndexOf, because "fits this pipe" carries an "is " of its own.
      expect(written.cursor,
          written.text.lastIndexOf('is ') + 'is '.length);
      // And nothing in it is a number.
      expect(RegExp(r'\d').hasMatch(written.text), isFalse,
          reason: 'the app put a dimension into the user\'s own sentence');
    });

    test('does not double a full stop, and does not replace what is there',
        () {
      final written =
          scaleSentence('A bracket for this.', 'The hole is ');
      expect(written.text, 'A bracket for this. The hole is  mm.');

      final fromEmpty = scaleSentence('   ', 'The material is ');
      expect(fromEmpty.text, 'The material is  mm.');
      expect(fromEmpty.cursor, 'The material is '.length);
    });
  });

  testWidgets('the composer offers both ways in and promises no parse',
      (WidgetTester tester) async {
    // The tiles were stubs that set an apology string. They are real now, and
    // this checks the screen still says what a photo IS - a reference body,
    // measured and never printed - because that sentence is the difference
    // between this and a generator that prints a picture of your bracket.
    await tester.pumpWidget(MaterialApp(
      home: ComposerScreen(
        api: BpcadApi('http://localhost:8765'),
        health: null,
      ),
    ));
    await tester.pump();

    expect(find.text('camera'), findsOneWidget);
    expect(find.text('files'), findsOneWidget);
    expect(find.textContaining('reference body'), findsWidgets);

    // BOTH ASSUMPTION LISTS STAY EMPTY UNTIL A PART EXISTS. Nothing on this
    // screen may claim to have read a dimension out of the sentence: the
    // model has not run yet, and a chip saying "wall 3.0" would be believed.
    expect(find.textContaining('The lists fill in once the part is built'),
        findsOneWidget);
  });
}
