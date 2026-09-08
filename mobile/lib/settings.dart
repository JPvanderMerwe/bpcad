// What the phone remembers, and what it deliberately does not.
//
// THE SERVER ADDRESS IS THE ONE THAT MATTERS.
//
// It was a compile-time constant of `http://localhost:8765`, which works over
// a USB cable with `adb reverse` and nowhere else. That is a testing path, not
// a product: bpcad runs on a computer with a GPU and the phone is a window
// onto it, so the address of that computer is the single setting without which
// the app does nothing at all on somebody else's desk.
//
// WHAT IS NOT HERE, AND WHY.
//
// The printer profile - bed, nozzle, layer, and above all the running
// clearance - is NOT editable from the phone, and that is a decision rather
// than an omission.
//
// Those values live in config/default.toml on the computer, and they are the
// source every geometry decision is taken from. The config module's own rule
// is that a value with no measured source is written "UNSET" and reading one
// RAISES, because a wrong tolerance is worse than no tolerance. A phone that
// could type 0.15 into a clearance field would be manufacturing a measurement
// - and the part built from it would be dimensionally wrong with nothing on
// screen to say so.
//
// So the Machine screen shows the profile, says where it is set, and says why
// it is not set here. When the calibration-print flow lands (brief 4.3) it
// will write that number from a measured strip, which is the only honest way
// it can be written at all.

import 'package:shared_preferences/shared_preferences.dart';

class Settings {
  Settings._(this._store);

  final SharedPreferences _store;

  static const String _serverKey = 'bpcad.server';
  static const String _materialKey = 'bpcad.material';
  static const String _effectsKey = 'bpcad.effects';

  /// Over a USB cable with `adb reverse tcp:8765 tcp:8765`, the phone's own
  /// localhost is the computer. That is what a fresh install should try, since
  /// it is the one address that needs no typing - but it is a starting point
  /// now rather than the only possibility.
  static const String defaultServer = 'http://localhost:8765';

  static Future<Settings> open() async =>
      Settings._(await SharedPreferences.getInstance());

  String get server => _store.getString(_serverKey) ?? defaultServer;

  /// The material a new part is built in.
  ///
  /// Empty means "whatever the server lists first", which is the right default
  /// - the phone should not have an opinion about a material the computer may
  /// not be configured for.
  String get material => _store.getString(_materialKey) ?? '';

  /// The glass and the ambient washes. On by default, and the design says a
  /// low-end GPU should be able to refuse them.
  bool get effects => _store.getBool(_effectsKey) ?? true;

  Future<void> setServer(String value) async {
    await _store.setString(_serverKey, normalise(value));
  }

  Future<void> setMaterial(String value) async {
    await _store.setString(_materialKey, value);
  }

  Future<void> setEffects(bool value) async {
    await _store.setBool(_effectsKey, value);
  }

  /// Tidy an address a human typed, without guessing at what they meant.
  ///
  /// A HOST WITH NO SCHEME GETS http://, because nobody types the scheme and
  /// a bare `192.168.0.14:8765` would otherwise be parsed as a path. A missing
  /// PORT gets bpcad's own 8765, because that is the port `bpcad web` opens
  /// unless told otherwise and it is the only sensible guess.
  ///
  /// It does NOT correct a typo in a host name or fall back to localhost when
  /// something looks wrong. An address that does not answer has to say so with
  /// the address the user typed in the message - silently substituting a
  /// working one is how somebody spends an afternoon wondering why their
  /// changes are not showing up on a machine they are not talking to.
  static String normalise(String raw) {
    var text = raw.trim();
    if (text.isEmpty) return defaultServer;
    if (!text.contains('://')) text = 'http://$text';
    // Strip a trailing slash: every path in api.dart begins with one, and two
    // together give a 404 that looks like a missing route.
    while (text.endsWith('/')) {
      text = text.substring(0, text.length - 1);
    }
    final uri = Uri.tryParse(text);
    if (uri == null || uri.host.isEmpty) return raw.trim();
    if (uri.hasPort) return text;
    return '$text:8765';
  }
}
