// The screen you land on after a failure.
//
// WHAT THIS GUARDS. Opening a draft used to be a dead end: a viewport asking
// for a turntable frame of a part with no mesh, a 404, and a sheet with no
// size, no checks and no exports. Nothing on it said what had happened.
//
// The failure mode of the fix is subtler and worth pinning: a screen that
// says "something went wrong" and offers a retry. The engine's diagnosis is
// not "invalid spec" - it carries the measured spans and the numbers to
// change - and paraphrasing it throws away the only part anybody can act on.
// So these check that the words survive, and that the request comes back so
// nobody has to retype a sentence they already wrote.

import 'package:bpcad_app/api.dart';
import 'package:bpcad_app/draft_view.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

const String _diagnosis =
    'a cut in this spec did not do what a cut was asked to do, so a feature '
    'that was asked for is not in the part:\n'
    '  disc in cut mode removed nothing - it does not touch the part. It '
    'sits at (0.0, 0.0, -8.0) and the part spans x -20.0..15.0, y -5.0..5.0, '
    'z -8.0..-3.0. Set z_mm to -10.00 and height_mm to 9.00.';

/// The server's own payload, as /api/part returns it for a draft.
Draft _draft() => Draft.fromJson({
      'request': 'a hinge',
      'attempts': 4,
      'elapsed_s': 597.6,
      'machine': 'laptop',
      'models': ['qwen2.5-coder:7b', 'hermes3:latest'],
      'level_reached': 2,
      'message': _diagnosis,
      'handoff': 'parts/a_hinge/spec.draft.yaml',
      'spec_draft': '# bpcad handoff - the model could not produce a valid '
          'spec.\nname: hinge\nparams: {}\n',
    });

void main() {
  test('a draft carries the run, not just the fact that it failed', () {
    final draft = _draft();

    expect(draft.request, 'a hinge');
    expect(draft.attempts, 4);
    // FOUR ATTEMPTS OVER TEN MINUTES IS A DIFFERENT SITUATION from one
    // attempt over twenty seconds, and the second number is what says so -
    // it is the fact that decides whether trying the same thing again is
    // worth the wait.
    expect(draft.spent, '10 min');
    expect(draft.models, ['qwen2.5-coder:7b', 'hermes3:latest']);
    expect(draft.handoff, endsWith('spec.draft.yaml'));
  });

  test('a short run reads in seconds rather than a rounded zero minutes', () {
    final draft = Draft.fromJson({'request': 'x', 'elapsed_s': 21.4});
    expect(draft.spent, '21 s');
  });

  testWidgets('the screen shows the engine\'s numbers, not a paraphrase',
      (WidgetTester tester) async {
    await tester.pumpWidget(MaterialApp(
      home: DraftView(
        api: BpcadApi('http://localhost:8765'),
        name: 'hinge',
        draft: _draft(),
      ),
    ));
    await tester.pump();

    // The request, so the retry starts from it.
    expect(find.text('a hinge'), findsOneWidget);

    // THE DIAGNOSIS, WORD FOR WORD. The measured spans and the numbers to
    // change are the whole value of it: "invalid spec" is not actionable and
    // "set z_mm to -10.00 and height_mm to 9.00" is.
    expect(find.textContaining('Set z_mm to -10.00'), findsOneWidget);
    expect(find.textContaining('the part spans x -20.0..15.0'), findsOneWidget);

    // What it cost, and where to fix it by hand.
    expect(find.text('4'), findsOneWidget);
    expect(find.text('10 min'), findsOneWidget);
    expect(find.textContaining('spec.draft.yaml'), findsWidgets);

    // And a way forward that is not retyping the sentence.
    expect(find.textContaining('Try again'), findsOneWidget);
  });

  testWidgets('a run that recorded no reason says that, rather than nothing',
      (WidgetTester tester) async {
    // Running out of attempts without hitting a nameable problem is a real
    // outcome and a different one. An empty panel would read as a screen
    // that failed to load.
    await tester.pumpWidget(MaterialApp(
      home: DraftView(
        api: BpcadApi('http://localhost:8765'),
        name: 'hinge',
        draft: Draft.fromJson({'request': 'a hinge', 'attempts': 4}),
      ),
    ));
    await tester.pump();

    expect(find.textContaining('recorded no reason'), findsOneWidget);
  });
}
