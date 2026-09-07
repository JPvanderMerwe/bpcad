// What can be tested without a bpcad to talk to.
//
// The app is a client: almost everything it does needs a server, and a test
// that mocks the whole API would mostly assert that the mock works. So these
// cover the two things that are the app's own responsibility - that it starts
// without a server present, and that it says so honestly rather than showing
// an empty library that reads as "you have made nothing".

import 'package:bpcad_app/api.dart';
import 'package:bpcad_app/main.dart';
import 'package:bpcad_app/tokens.dart';
import 'package:flutter/material.dart';
import 'package:bpcad_app/result_screen.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  testWidgets('the boot self-test names the address it could not reach',
      (WidgetTester tester) async {
    // THE SELF-TEST IS NOT A SCRIPT, and this is the test that keeps it that
    // way. The design shows `self-test .... ok` and a profile and a link, and
    // the obvious build prints those four strings - which would be a
    // decoration saying "ok" while nothing works, on a phone whose cable is
    // out, which is the single most likely way this screen is ever seen.
    //
    // So with no server: it still says bpcad, it says plainly that nothing
    // answered, and it NAMES THE ADDRESS. The fix is nearly always the cable
    // or the port and the user cannot guess which.
    await tester.pumpWidget(const BpcadApp());
    await tester.pump(const Duration(seconds: 1));
    // Not pumpAndSettle: the boot sweep loops for ever by design, and
    // settling waits for animations to stop.
    await tester.pump(const Duration(seconds: 2));

    expect(find.text('bpcad'), findsOneWidget);
    expect(find.textContaining('not answering'), findsOneWidget);
    expect(find.textContaining(kDefaultServer), findsOneWidget);

    // And it lets you in anyway: a bpcad with no server still opens the parts
    // already on the phone, and a dead button would say otherwise.
    expect(find.text('Carry on anyway'), findsOneWidget);
  });

  testWidgets('the self-test reports a failure as a failure',
      (WidgetTester tester) async {
    // The counterpart to the above. Whatever the screen prints for `link`, it
    // must not be the pass pen when nothing answered - a green "ok" beside a
    // dead server is the exact lie this screen exists to avoid.
    await tester.pumpWidget(const BpcadApp());
    await tester.pump(const Duration(seconds: 1));
    await tester.pump(const Duration(seconds: 2));

    final noAnswer = tester.widget<Text>(find.text('no answer'));
    expect(noAnswer.style?.color, BpPen.fail);
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

  test('the GLB url carries a mesh version', () {
    // THE REGRESSION THIS PINS. The GLB was first served immutable for a week
    // on the argument that it is the mesh and not a picture of it, so the
    // renderer's choices could not affect it. That stopped being true when the
    // part's grey was baked into the file: every GLB's content changed while
    // every GLB's URL stayed the same, and a phone that had already been here
    // kept drawing a white silhouette with no way to ask for the new file.
    //
    // The version is separate from the frames' render version because the two
    // change for different reasons - a new camera angle must not throw away
    // every cached mesh, and a new baked colour must not throw away every
    // cached frame.
    final api = BpcadApi('http://localhost:8765');
    expect(api.glb('hinge_pip', meshVersion: 2).toString(),
        'http://localhost:8765/api/part/hinge_pip/glb?mv=2');
    expect(api.frame('hinge_pip', 3, renderVersion: 2).toString(),
        contains('rv=2'));
    // Two versions, two URLs, neither invalidating the other.
    expect(api.glb('hinge_pip', meshVersion: 2).toString(),
        isNot(contains('rv=')));
  });

  test('the viewer url names the part and nothing else', () {
    // One page, served by bpcad, loaded by both clients - which is the only
    // way the phone and the browser show a part the same way rather than
    // nearly the same way. The page asks the server for the mesh version
    // itself, so a number is not repeated in Dart and in JavaScript.
    final api = BpcadApi('http://localhost:8765');
    // `flutter test` is a debug build, so the camera readout is asked for -
    // see BpcadApi.viewer. It is off in every release build.
    expect(api.viewer('hinge_pip').toString(),
        'http://localhost:8765/static/viewer.html?part=hinge_pip&debug=1');
    // A name with a space has to survive the trip; the page validates it
    // again on arrival against the server's own SAFE_NAME shape.
    expect(api.viewer('rod clamp').toString(), contains('part=rod%20clamp'));
  });

  testWidgets('the result screen builds without touching MediaQuery too early',
      (WidgetTester tester) async {
    // THE REGRESSION. precacheImage reads MediaQuery off the context, and
    // calling it from initState threw on every single tap of a library card:
    // "dependOnInheritedWidgetOfExactType<MediaQuery>() was called before
    // initState() completed" - a full red screen instead of the part.
    //
    // Now pinned on ResultScreen, which is the screen that ships and carries
    // the same didChangeDependencies fix. The old PartScreen it was written
    // against is gone: a test guarding a bug on a deleted file guards
    // nothing, and this bug is one a redesign could easily reintroduce.
    //
    // No server is needed to catch it. The failure happened while the widget
    // was being created, before any image request went out.
    await tester.pumpWidget(MaterialApp(
      home: ResultScreen(
        api: BpcadApi('http://localhost:8765'),
        name: 'hinge_pip',
      ),
    ));
    await tester.pump(const Duration(milliseconds: 100));

    // WHAT THIS CAN AND CANNOT ASSERT. Flutter's test harness installs an
    // HttpClient that answers 400 to everything, so the frames always fail to
    // load here and a NetworkImageLoadException is expected. Demanding no
    // exception at all would be a test that only passes with a server
    // running, which is not a unit test.
    //
    // The bug being guarded against threw while the widget was being CREATED,
    // with a specific message, so that is what is checked.
    final thrown = tester.takeException();
    if (thrown != null) {
      expect(thrown.toString(), isNot(contains('initState')),
          reason: 'the part screen touched an inherited widget too early');
      expect(thrown.toString(), isNot(contains('MediaQuery')),
          reason: 'the part screen read MediaQuery before it could');
    }
    expect(find.text('hinge_pip'), findsWidgets);
  });

  // NO WIDGET TEST FOR THE 3D VIEWER. It is a WebView, and webview_flutter
  // has no platform implementation under `flutter test` - pumping it throws
  // "A platform implementation for `webview_flutter` has not been set", which
  // is a fact about the harness and not about the viewer. It is verified on
  // the device instead, which is the only place a GPU exists to verify it on.
}
