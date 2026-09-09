// The verdict, and what the app is allowed to say about it.
//
// WHAT THESE GUARD. Both clients used to print "not re-checked" over every
// part, on the stated grounds that a part on disk carries no verdict and that
// re-verifying costs as long as building. Neither was true - run.json holds
// the whole verify report, and a re-verify measured 0.3s against a build of
// 151s for the same part - and the result was a product that refused to tell
// you whether the thing you were about to print had passed.
//
// The correction has its own way of going wrong: showing a remembered tick.
// So these pin the two rules that keep it honest. A verdict always arrives
// with its provenance, and a genuinely unknown one stays unknown.

import 'package:bpcad_app/api.dart';
import 'package:flutter_test/flutter_test.dart';

Map<String, dynamic> _stored({
  List<String> drift = const [],
  List<String> problems = const [],
  List<String> warnings = const [],
  String verdict = 'PASS',
  bool ok = true,
}) =>
    {
      'verdict': verdict,
      'ok': ok,
      'problems': problems,
      'warnings': warnings,
      'nozzle_mm': 0.4,
      'material': 'petg',
      'print_axis': 'z',
      'lines': [
        {'name': 'watertight', 'value': 'yes', 'status': 'pass'},
        {'name': 'separate bodies', 'value': '1', 'status': 'info'},
        {
          'name': 'worst overhang',
          'value': '0.0 deg from vertical',
          'status': 'pass'
        },
      ],
      'source': 'stored',
      'checked_at':
          DateTime.now().subtract(const Duration(hours: 3)).millisecondsSinceEpoch /
              1000,
      'drift': drift,
    };

void main() {
  test('a stored verdict arrives with the day and the profile behind it', () {
    final checks = Checks.fromJson(_stored());

    expect(checks.verdict, 'PASS');
    expect(checks.ok, isTrue);
    expect(checks.fresh, isFalse);
    expect(checks.stale, isFalse);
    // PROVENANCE OR IT IS A REMEMBERED TICK. A verdict with no date and no
    // profile behind it is exactly what this program refuses to show.
    expect(checks.age, '3 h ago');
    expect(checks.nozzleMm, 0.4);
  });

  test('every check carries the value it read, not just a status', () {
    final checks = Checks.fromJson(_stored());

    expect(checks.lines, hasLength(3));
    for (final line in checks.lines) {
      expect(line.name, isNotEmpty);
      // A status with no number beside it is a green tick, which is what the
      // checks panel exists not to be.
      expect(line.value, isNotEmpty);
      expect(line.status, isIn(['pass', 'warn', 'fail', 'info']));
    }
    // `info` is a real status: the number of separate bodies decides whether
    // a hinge turns and is neither a pass nor a failure.
    expect(checks.lines[1].status, 'info');
  });

  test('a profile that moved under a stored verdict makes it stale', () {
    final checks = Checks.fromJson(_stored(drift: [
      'it was checked against a 0.40 mm nozzle and the profile now says '
          '0.60 mm'
    ]));

    expect(checks.ok, isTrue);
    // STILL A PASS, AND STILL NOT TO BE TRUSTED WITHOUT A LOOK. Those are two
    // separate facts and the screen has to carry both: the check did pass,
    // and the machine it passed on is not the machine you have now.
    expect(checks.stale, isTrue);
    expect(checks.drift.single, contains('0.60 mm'));
  });

  test('a check taken just now says so and has nothing to drift from', () {
    final json = _stored();
    json['source'] = 'just now';
    json['checked_at'] = DateTime.now().millisecondsSinceEpoch / 1000;
    final checks = Checks.fromJson(json);

    expect(checks.fresh, isTrue);
    expect(checks.stale, isFalse);
    expect(checks.age, 'just now');
  });

  test('a failure carries the engine\'s own reason, not a paraphrase', () {
    final checks = Checks.fromJson(_stored(
      verdict: 'FAIL',
      ok: false,
      problems: ['the part is 264.0 mm across and the bed is 260.0 mm'],
      warnings: ['supports needed: 41.20 mm2 of underside falls unsupported'],
    ));

    expect(checks.ok, isFalse);
    expect(checks.verdict, 'FAIL');
    // The measured number and what to change, in the words the engine used.
    expect(checks.problems.single, contains('264.0 mm'));
    expect(checks.warnings.single, contains('41.20 mm2'));
  });

  test('a part with no record has no verdict at all', () {
    // AN IMPORT, OR SOMETHING MADE BEFORE run.json EXISTED. That is a real
    // gap in the record. The server sends no `checks` key, and the app must
    // carry a null rather than manufacture a PASS because the files exist.
    final part = PartDetail.fromJson({
      'name': 'loop_keyring',
      'frames': 24,
      'has_stl': true,
      'files': ['stl'],
    });

    expect(part.checks, isNull);
  });

  test('a part with a record carries it through', () {
    final part = PartDetail.fromJson({
      'name': 'flat_plate_with_holes',
      'frames': 24,
      'has_stl': true,
      'files': ['stl', '3mf'],
      'checks': _stored(),
    });

    expect(part.checks, isNotNull);
    expect(part.checks!.verdict, 'PASS');
    expect(part.checks!.lines, isNotEmpty);
  });

  group('a response missing a key degrades instead of throwing', () {
    // THE CAST TRAP, PINNED. `(json['x'] ?? const {}) as Map<String, dynamic>`
    // throws at runtime, because an empty const map is Map<dynamic, dynamic>.
    // It shipped in six places and bit in one: PartDetail's spec, which threw
    // on every draft and every imported mesh - exactly the parts with no
    // spec.yaml - so opening one was a red screen rather than a screen.
    test('health with nothing in it still parses', () {
      final health = Health.fromJson(const <String, dynamic>{});
      expect(health.modelAvailable, isFalse);
      expect(health.printer, '');
      expect(health.bedMm, isNull);
      expect(health.materials, isEmpty);
    });

    test('a part with no spec, checks or draft still parses', () {
      final part = PartDetail.fromJson(const <String, dynamic>{
        'name': 'loop_keyring',
      });
      expect(part.name, 'loop_keyring');
      expect(part.params, isEmpty);
      expect(part.parametric, isFalse);
      expect(part.checks, isNull);
      expect(part.draft, isNull);
    });

    test('a parameter with no bounds is simply not slidable', () {
      final param = TemplateParam.fromJson(const <String, dynamic>{
        'name': 'wall_mm',
        'type': 'float',
      });
      expect(param.slidable, isFalse);
      expect(param.low, isNull);
      expect(param.label, 'wall');
    });
  });
}
