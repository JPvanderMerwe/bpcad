// The one place this app talks to bpcad.
//
// WHY THE APP IS A CLIENT AND NOT THE PROGRAM.
//
// bpcad's geometry engine is CadQuery, which is a Python binding to
// OpenCASCADE: desktop native code with no Android or iOS build, and nothing
// that could be cross-compiled into a phone app. The pipeline also wants a
// language model. So the phone cannot run bpcad, and pretending otherwise
// would mean shipping a toy that draws pictures of parts.
//
// What the phone CAN do is be the whole interface to a bpcad that runs
// somewhere else, over the HTTP API bpcad/web/server.py already serves. Every
// endpoint below already exists and is already used by the web app - this app
// is a second front end, not a second implementation.
//
// WHERE THE SERVER IS. Over a USB cable, `adb reverse tcp:8765 tcp:8765`
// makes the phone's own localhost reach the laptop, which is how this is
// tested with no network exposure at all. On a LAN it is the laptop's
// address. Hosted is a decision the owner has not taken yet, so the base URL
// is a setting and not a constant.

import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;

class BpcadApi {
  BpcadApi(this.baseUrl);

  /// The server's root, no trailing slash. Over USB this is
  /// http://localhost:8765 because of `adb reverse`.
  final String baseUrl;

  static const Duration _quick = Duration(seconds: 10);

  Uri _uri(String path) => Uri.parse('$baseUrl$path');

  /// Is a bpcad there, and what can the machine behind it do?
  ///
  /// This is the first call the app makes and the only one whose failure is
  /// expected rather than exceptional: a phone that cannot see the laptop is
  /// the normal state of a phone. The screen says so plainly rather than
  /// showing an empty library that looks like "you have made nothing".
  Future<Health> health() async {
    final response = await http.get(_uri('/api/health')).timeout(_quick);
    if (response.statusCode != 200) {
      throw BpcadUnreachable('the server answered ${response.statusCode}');
    }
    return Health.fromJson(jsonDecode(response.body) as Map<String, dynamic>);
  }

  /// Everything already made, newest first.
  Future<List<PartSummary>> parts() async {
    final response = await http.get(_uri('/api/parts')).timeout(_quick);
    if (response.statusCode != 200) {
      throw BpcadUnreachable('the library answered ${response.statusCode}');
    }
    final body = jsonDecode(response.body) as Map<String, dynamic>;
    return (body['parts'] as List<dynamic>)
        .map((e) => PartSummary.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  /// A turntable frame. The server renders these and marks them immutable, so
  /// the image cache does the right thing without help.
  ///
  /// `renderVersion` is appended because the geometry of a built part never
  /// changes but the RENDERER does: without it, changing the renderer left
  /// every phone showing week-old frames from its own cache.
  Uri frame(String name, int step, {int width = 640, int renderVersion = 1}) =>
      _uri('/api/part/${Uri.encodeComponent(name)}/frame/$step'
          '?w=$width&rv=$renderVersion');

  /// The part as one GLB, for a viewer that draws on the phone's own GPU.
  ///
  /// No render version in this URL: GLB is the MESH, not a picture of it, and
  /// the renderer's colours and camera have nothing to do with it. The server
  /// marks it immutable because a built part's geometry never changes - a
  /// refinement writes a new part - so the phone may cache it hard and a
  /// second look costs nothing.
  Uri glb(String name) => _uri('/api/part/${Uri.encodeComponent(name)}/glb');

  /// Start a generate. Returns the job id; progress arrives on [events].
  Future<String> generate(String request, {String material = 'petg'}) async {
    final response = await http
        .post(
          _uri('/api/generate'),
          headers: const {'Content-Type': 'application/json'},
          body: jsonEncode({'request': request, 'material': material}),
        )
        .timeout(_quick);
    if (response.statusCode != 200) {
      throw BpcadUnreachable(_messageFrom(response));
    }
    return (jsonDecode(response.body) as Map<String, dynamic>)['job'] as String;
  }

  /// Progress for a running job, as server-sent events.
  ///
  /// A generate takes minutes on a CPU, so this is not optional decoration:
  /// a progress line is the difference between "it is working" and "it has
  /// hung", and the user is holding the phone the whole time.
  Stream<JobEvent> events(String jobId) async* {
    final client = http.Client();
    try {
      final request = http.Request('GET', _uri('/api/job/$jobId/events'));
      request.headers['Accept'] = 'text/event-stream';
      final response = await client.send(request);
      final lines = response.stream
          .transform(utf8.decoder)
          .transform(const LineSplitter());
      await for (final line in lines) {
        if (!line.startsWith('data:')) continue;
        final payload = line.substring(5).trim();
        if (payload.isEmpty) continue;
        try {
          yield JobEvent.fromJson(
              jsonDecode(payload) as Map<String, dynamic>);
        } catch (_) {
          // A malformed frame is not worth killing a five-minute job over.
        }
      }
    } finally {
      client.close();
    }
  }

  static String _messageFrom(http.Response response) {
    try {
      final body = jsonDecode(response.body) as Map<String, dynamic>;
      return (body['error'] ?? body['message'] ?? response.body).toString();
    } catch (_) {
      return response.body.isEmpty
          ? 'the server answered ${response.statusCode}'
          : response.body;
    }
  }
}

/// The server is not reachable, or refused. Distinct from a bug in the app,
/// because on a phone it is the ordinary case and the UI must not treat it as
/// a crash.
class BpcadUnreachable implements Exception {
  BpcadUnreachable(this.why);
  final String why;
  @override
  String toString() => why;
}

class Health {
  Health({
    required this.modelAvailable,
    required this.headline,
    required this.printer,
    required this.renderVersion,
    required this.materials,
  });

  final bool modelAvailable;

  /// What this machine can actually do, in the server's own words - including
  /// how long a prompt takes on it. The app does not paraphrase this: the
  /// server measured it and the phone did not.
  final String headline;
  final String printer;
  final int renderVersion;
  final List<String> materials;

  factory Health.fromJson(Map<String, dynamic> json) {
    final model = (json['model'] ?? const {}) as Map<String, dynamic>;
    final capability = (json['capability'] ?? const {}) as Map<String, dynamic>;
    final printer = (json['printer'] ?? const {}) as Map<String, dynamic>;
    return Health(
      modelAvailable: model['available'] == true,
      headline: (capability['headline'] ?? '').toString(),
      printer: (printer['name'] ?? '').toString(),
      renderVersion: (json['render_version'] ?? 1) as int,
      materials: ((json['materials'] ?? const []) as List<dynamic>)
          .map((e) => e.toString())
          .toList(),
    );
  }
}

class PartSummary {
  PartSummary({
    required this.name,
    required this.sizeMm,
    required this.template,
    required this.volumeCm3,
    required this.built,
    required this.prompt,
    required this.makes,
    required this.material,
  });

  final String name;

  /// WHETHER THERE IS A MESH AT ALL. A run that failed hands off with a
  /// draft spec and no geometry, and the library lists it - correctly, it is
  /// something you started. Asking that part for a render is a guaranteed
  /// 404, which is what put a broken card in the library: the app knew the
  /// answer and asked anyway.
  final bool built;

  /// The words this part can be found by: what was typed to make it, and
  /// what its template says it makes. Searching only on `name` misses
  /// "container" finding a part built from the enclosure.
  final String prompt;
  final List<String> makes;
  final String material;

  /// null when the part has never been built, which the card says rather than
  /// showing zeros.
  final List<double>? sizeMm;
  final String? template;
  final double? volumeCm3;

  factory PartSummary.fromJson(Map<String, dynamic> json) {
    final size = json['size_mm'];
    return PartSummary(
      name: (json['name'] ?? '').toString(),
      sizeMm: size is List
          ? size.map((e) => (e as num).toDouble()).toList()
          : null,
      template: json['template']?.toString(),
      volumeCm3: (json['volume_cm3'] as num?)?.toDouble(),
      built: json['built'] != false,
      prompt: (json['prompt'] ?? '').toString(),
      makes: ((json['makes'] ?? const []) as List<dynamic>)
          .map((e) => e.toString())
          .toList(),
      material: (json['material'] ?? '').toString(),
    );
  }

  /// Does this part answer to what somebody typed into the search box?
  ///
  /// Name, the prompt that made it, its template, its material, and the words
  /// the template says it makes - so "container" finds a part built from the
  /// enclosure even though that word appears nowhere in its own name. That is
  /// how the library already searches on the desktop; the phone should not be
  /// worse at it.
  bool matches(String query) {
    final needle = query.trim().toLowerCase();
    if (needle.isEmpty) return true;
    for (final term in needle.split(RegExp(r'\s+'))) {
      final hit = name.toLowerCase().contains(term) ||
          prompt.toLowerCase().contains(term) ||
          (template ?? '').toLowerCase().contains(term) ||
          material.toLowerCase().contains(term) ||
          makes.any((w) => w.toLowerCase().contains(term));
      if (!hit) return false; // every word must land, so search narrows
    }
    return true;
  }

  String get envelope => sizeMm == null
      ? 'not built yet'
      : '${sizeMm!.map((v) => v.toStringAsFixed(0)).join(' × ')} mm';
}

class JobEvent {
  JobEvent({required this.kind, required this.text, required this.done});

  final String kind;
  final String text;
  final bool done;

  factory JobEvent.fromJson(Map<String, dynamic> json) => JobEvent(
        kind: (json['kind'] ?? json['event'] ?? '').toString(),
        text: (json['text'] ?? json['note'] ?? '').toString(),
        done: json['done'] == true,
      );
}
