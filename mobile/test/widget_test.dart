// What can be tested without a bpcad to talk to.
//
// The app is a client: almost everything it does needs a server, and a test
// that mocks the whole API would mostly assert that the mock works. So these
// cover the two things that are the app's own responsibility - that it starts
// without a server present, and that it says so honestly rather than showing
// an empty library that reads as "you have made nothing".

import 'package:bpcad_app/api.dart';
import 'package:bpcad_app/main.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  testWidgets('it starts with no server and says what it tried',
      (WidgetTester tester) async {
    await tester.pumpWidget(const BpcadApp());
    // The health call fails against nothing; give it a moment to come back.
    await tester.pump(const Duration(seconds: 1));
    await tester.pumpAndSettle(const Duration(seconds: 2));

    expect(find.text('bpcad'), findsOneWidget);
    // A phone that cannot see the laptop is the ordinary case, and the screen
    // has to name the address it tried - the fix is nearly always the cable or
    // the port, and the user cannot guess which.
    expect(find.textContaining('No bpcad to talk to'), findsOneWidget);
    expect(find.textContaining(kDefaultServer), findsOneWidget);
  });

  test('a part with no build says so instead of showing zeros', () {
    final unbuilt = PartSummary.fromJson({'name': 'x', 'size_mm': null});
    expect(unbuilt.envelope, 'not built yet');

    final built = PartSummary.fromJson({
      'name': 'y',
      'size_mm': [80.0, 40.0, 6.0],
    });
    expect(built.envelope, '80 × 40 × 6 mm');
  });

  test('the GLB url carries no render version', () {
    // GLB is the mesh, not a picture of it: the renderer's colours and camera
    // have nothing to do with it, and putting a version in the URL would
    // throw away the phone's cache every time the renderer changed.
    final api = BpcadApi('http://localhost:8765');
    expect(api.glb('hinge_pip').toString(),
        'http://localhost:8765/api/part/hinge_pip/glb');
    expect(api.frame('hinge_pip', 3, renderVersion: 2).toString(),
        contains('rv=2'));
  });
}
