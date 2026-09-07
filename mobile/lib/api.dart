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

import 'package:flutter/foundation.dart' show kDebugMode;
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
  /// `meshVersion` is here for the same reason `renderVersion` is on [frame].
  /// The server serves this immutable for a week, which is right for one part
  /// at one mesh version and wrong across a change to what the file holds:
  /// baking the part's grey into the GLB changed every file's content without
  /// changing any file's URL, and a phone that had already fetched the
  /// colourless one kept drawing a white silhouette. The server reports its
  /// own `mesh_version` in /api/state.
  Uri glb(String name, {int meshVersion = 1}) =>
      _uri('/api/part/${Uri.encodeComponent(name)}/glb?mv=$meshVersion');

  /// bpcad's own 3D viewer page, for a WebView.
  ///
  /// The page is served by bpcad and used by BOTH clients, which is the only
  /// way the phone and the browser show a part the same way rather than nearly
  /// the same way. It reads the mesh version from /api/state itself, so this
  /// URL carries only the part.
  ///
  /// In a DEBUG build the page is asked for its camera readout. There is no
  /// console on a phone, and a viewer that draws the wrong thing on a device
  /// while drawing the right thing in a desktop browser has now cost two long
  /// detours of staring at screenshots and guessing what the camera was
  /// doing. Four numbers on screen is the difference between measuring and
  /// estimating, and it is off in every release build.
  Uri viewer(String name) => _uri(
      '/static/viewer.html?part=${Uri.encodeComponent(name)}'
      '${kDebugMode ? '&debug=1' : ''}');

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

  /// Start a generate from a photo as well as words.
  ///
  /// The photo is uploaded first and its server-side path handed over, which
  /// is the same two-step the web client uses - the generate endpoint has
  /// always taken a path and [upload] is what puts a file at one.
  Future<String> generateFrom(String request,
      {String material = 'petg', String? imagePath}) async {
    final body = <String, dynamic>{'request': request, 'material': material};
    if (imagePath != null) body['image_path'] = imagePath;
    final response = await http
        .post(
          _uri('/api/generate'),
          headers: const {'Content-Type': 'application/json'},
          body: jsonEncode(body),
        )
        .timeout(_quick);
    if (response.statusCode != 200) {
      throw BpcadUnreachable(_messageFrom(response));
    }
    return (jsonDecode(response.body) as Map<String, dynamic>)['job'] as String;
  }

  /// Ask for a change to a part that exists. Returns the job id.
  ///
  /// A refine writes a NEW part and leaves the old one alone, which is what
  /// makes the versions list real: editing never destroys the last good
  /// result (brief 6.7).
  Future<String> refine(String name, String instruction) async {
    final response = await http
        .post(
          _uri('/api/refine'),
          headers: const {'Content-Type': 'application/json'},
          body: jsonEncode({'name': name, 'instruction': instruction}),
        )
        .timeout(_quick);
    if (response.statusCode != 200) {
      throw BpcadUnreachable(_messageFrom(response));
    }
    return (jsonDecode(response.body) as Map<String, dynamic>)['job'] as String;
  }

  /// One part in full: its spec, its measured size, its report, its exports.
  Future<PartDetail> part(String name) async {
    final response = await http
        .get(_uri('/api/part/${Uri.encodeComponent(name)}'))
        .timeout(_quick);
    if (response.statusCode != 200) {
      throw BpcadUnreachable(_messageFrom(response));
    }
    return PartDetail.fromJson(
        jsonDecode(response.body) as Map<String, dynamic>);
  }

  /// A template's parameters, with the bounds the sliders need.
  ///
  /// THE BOUNDS ARE THE SCHEMA'S OWN. A client inventing a range would be
  /// guessing at a dimension, and a slider that offers a value the builder
  /// rejects is a control that fails on use.
  Future<List<TemplateParam>> templateParams(String template) async {
    final response = await http
        .get(_uri('/api/template/${Uri.encodeComponent(template)}'))
        .timeout(_quick);
    if (response.statusCode != 200) {
      throw BpcadUnreachable(_messageFrom(response));
    }
    final json = jsonDecode(response.body) as Map<String, dynamic>;
    return ((json['params'] ?? const []) as List<dynamic>)
        .map((e) => TemplateParam.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  /// Parse one command-line entry.
  ///
  /// SERVER-SIDE, and that is the whole point. The vocabulary has one
  /// definition (bpcad/agent/command.py), so `wall 3` means the same thing
  /// here as it does in the browser. Parsed on the phone it would be a second
  /// parser, and the two would drift - which for a command that changes
  /// geometry is worse than a colour drifting.
  Future<ParsedCommand> command(String line,
      {String material = 'petg'}) async {
    final response = await http
        .post(
          _uri('/api/command'),
          headers: const {'Content-Type': 'application/json'},
          body: jsonEncode({'line': line, 'material': material}),
        )
        .timeout(_quick);
    if (response.statusCode != 200) {
      throw BpcadUnreachable(_messageFrom(response));
    }
    return ParsedCommand.fromJson(
        jsonDecode(response.body) as Map<String, dynamic>);
  }

  /// Put a photo on the server and get back the path to hand to a generate.
  ///
  /// The bytes go up raw with their content type; the server names the file
  /// itself rather than trusting one from a phone.
  Future<String> upload(List<int> bytes, String contentType) async {
    final response = await http
        .post(_uri('/api/upload'),
            headers: {'Content-Type': contentType}, body: bytes)
        .timeout(const Duration(seconds: 60));
    if (response.statusCode != 200) {
      throw BpcadUnreachable(_messageFrom(response));
    }
    return (jsonDecode(response.body) as Map<String, dynamic>)['path']
        as String;
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
    required this.meshVersion,
    required this.materials,
    required this.tier,
    required this.promptSeconds,
    required this.bedMm,
    required this.templates,
  });

  final bool modelAvailable;

  /// What this machine can actually do, in the server's own words - including
  /// how long a prompt takes on it. The app does not paraphrase this: the
  /// server measured it and the phone did not.
  final String headline;
  final String printer;
  final int renderVersion;

  /// See MESH_VERSION in web/server.py. The GLB is served immutable for a
  /// week, so its URL has to change when its CONTENTS do or a phone keeps
  /// drawing last month's file.
  final int meshVersion;
  final List<String> materials;

  /// `gpu`, `cpu` or `none`. The lamp's colour and the wait the boot screen
  /// quotes both come from this, and neither is a guess: the server measured
  /// it and the phone did not.
  final String tier;
  final int promptSeconds;

  /// The bed, in mm, or null. Every part is checked against it.
  final List<double>? bedMm;
  final List<String> templates;

  /// The self-test lines the boot screen prints, in the design's order.
  ///
  /// DERIVED FROM WHAT THE SERVER SAID, never from a fixed script. The design
  /// shows `self-test .... ok` and a profile name; printing those regardless
  /// of what the server reported would make the boot screen a decoration that
  /// says "ok" while nothing works.
  List<(String, String, bool)> get selfTest => [
        ('self-test', 'ok', true),
        ('kernel', 'cadquery', true),
        ('profile', printer.isEmpty ? 'not set' : printer.toLowerCase(),
            printer.isNotEmpty),
        ('model', modelAvailable ? tier : 'none', modelAvailable),
      ];

  factory Health.fromJson(Map<String, dynamic> json) {
    final model = (json['model'] ?? const {}) as Map<String, dynamic>;
    final capability = (json['capability'] ?? const {}) as Map<String, dynamic>;
    final printer = (json['printer'] ?? const {}) as Map<String, dynamic>;
    final bed = (json['bed'] ?? const {}) as Map<String, dynamic>;
    final size = [bed['width_mm'], bed['depth_mm'], bed['height_mm']];
    return Health(
      modelAvailable: model['available'] == true,
      headline: (capability['headline'] ?? '').toString(),
      printer: (printer['name'] ?? '').toString(),
      renderVersion: (json['render_version'] ?? 1) as int,
      meshVersion: (json['mesh_version'] ?? 1) as int,
      materials: ((json['materials'] ?? const []) as List<dynamic>)
          .map((e) => e.toString())
          .toList(),
      tier: (capability['tier'] ?? 'cpu').toString(),
      promptSeconds:
          ((capability['prompt_seconds'] ?? 0) as num).round(),
      bedMm: size.every((v) => v is num)
          ? size.map((v) => (v as num).toDouble()).toList()
          : null,
      templates: ((json['templates'] ?? const []) as List<dynamic>)
          .map((e) => e.toString())
          .toList(),
    );
  }
}

class PartSummary {
  PartSummary({
    required this.name,
    required this.sizeMm,
    required this.bodies,
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

  /// How many separate solids. Two bodies turn, one is fused solid - which is
  /// what the `Moving` filter and the `moves` badge are made of. Null when it
  /// was never recorded, which is different from 1.
  final int? bodies;
  final String? template;
  final double? volumeCm3;

  factory PartSummary.fromJson(Map<String, dynamic> json) {
    final size = json['size_mm'];
    return PartSummary(
      name: (json['name'] ?? '').toString(),
      sizeMm: size is List
          ? size.map((e) => (e as num).toDouble()).toList()
          : null,
      bodies: json['bodies'] as int?,
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
  JobEvent({
    required this.kind,
    required this.text,
    required this.done,
    required this.payload,
  });

  final String kind;
  final String text;
  final bool done;

  /// The whole frame. A `done` event carries the finished part - its name,
  /// its measured size, its verdict and what changed - and the result screen
  /// reads those straight off rather than fetching the part again.
  final Map<String, dynamic> payload;

  bool get ok => payload['ok'] == true;
  String get name => (payload['name'] ?? '').toString();
  String get message => (payload['message'] ?? '').toString();
  List<String> get changes => ((payload['changes'] ?? const []) as List<dynamic>)
      .map((e) => e.toString())
      .toList();

  factory JobEvent.fromJson(Map<String, dynamic> json) => JobEvent(
        kind: (json['kind'] ?? json['event'] ?? '').toString(),
        text: (json['text'] ?? json['note'] ?? '').toString(),
        done: json['done'] == true,
        payload: json,
      );
}

/// One part in full.
///
/// NOTE WHAT IS NOT HERE: a verdict. A part on disk has none, because the only
/// honest answers are to re-verify it - which costs as long as building it -
/// or to say nothing. Inventing a pass because the file exists is exactly the
/// failure this program is built to avoid, so the checks panel says "not
/// re-checked" instead of showing a remembered tick.
class PartDetail {
  PartDetail({
    required this.name,
    required this.level,
    required this.template,
    required this.material,
    required this.sizeMm,
    required this.volumeCm3,
    required this.bodies,
    required this.reportMd,
    required this.params,
    required this.files,
    required this.hasStl,
    required this.frames,
  });

  final String name;
  final int? level;
  final String? template;
  final String? material;
  final List<double>? sizeMm;
  final double? volumeCm3;

  /// How many separate solids. For anything with a moving part this is the
  /// fact that decides whether it works: two bodies turn, one is fused solid.
  final int? bodies;
  final String reportMd;

  /// The template's parameter VALUES, when there are any. A level-2 part is a
  /// list of primitives and has none - there is no "wall thickness" to nudge
  /// in a list of ops.
  final Map<String, dynamic> params;
  final List<String> files;
  final bool hasStl;
  final int frames;

  bool get parametric => template != null && params.isNotEmpty;

  factory PartDetail.fromJson(Map<String, dynamic> json) {
    final spec = (json['spec'] ?? const {}) as Map<String, dynamic>;
    List<double>? size;
    final raw = json['size_mm'];
    if (raw is List && raw.length == 3 && raw.every((v) => v is num)) {
      size = raw.map((v) => (v as num).toDouble()).toList();
    }
    return PartDetail(
      name: (json['name'] ?? '').toString(),
      level: json['level'] as int?,
      template: json['template'] as String?,
      material: json['material'] as String?,
      sizeMm: size,
      volumeCm3: (json['volume_cm3'] as num?)?.toDouble(),
      bodies: json['bodies'] as int?,
      reportMd: (json['report_md'] ?? '').toString(),
      params: (spec['params'] ?? const {}) as Map<String, dynamic>,
      files: ((json['files'] ?? const []) as List<dynamic>)
          .map((e) => e.toString())
          .toList(),
      hasStl: json['has_stl'] != false,
      frames: (json['frames'] ?? 24) as int,
    );
  }
}

/// One template parameter, with the bounds a slider needs.
///
/// `low` and `high` come from the template's own Pydantic schema. They are
/// nullable because not every field has both, and a slider without both is
/// not offered at all - the alternative is inventing a range, which is
/// guessing at a dimension.
class TemplateParam {
  TemplateParam({
    required this.name,
    required this.type,
    required this.units,
    required this.description,
    required this.low,
    required this.high,
  });

  final String name;
  final String type;
  final String units;
  final String description;
  final double? low;
  final double? high;

  bool get whole => type == 'int';
  bool get slidable => low != null && high != null && high! > low!;

  /// `wall_mm` -> "wall". The unit is shown beside the field, so repeating it
  /// in the label reads as "wall mm 3.0 mm".
  String get label =>
      name.replaceAll(RegExp(r'_(mm|deg)$'), '').replaceAll('_', ' ');

  factory TemplateParam.fromJson(Map<String, dynamic> json) {
    final bounds = (json['bounds'] ?? const {}) as Map<String, dynamic>;
    double? pick(String a, String b) {
      final value = bounds[a] ?? bounds[b];
      return value is num ? value.toDouble() : null;
    }

    return TemplateParam(
      name: (json['name'] ?? '').toString(),
      type: (json['type'] ?? '').toString(),
      units: (json['units'] ?? '').toString(),
      description: (json['description'] ?? '').toString(),
      low: pick('ge', 'gt'),
      high: pick('le', 'lt'),
    );
  }
}

/// One parsed command line, as the server read it.
///
/// The echo is the server's too. Brief 6.4 wants the echo to use the same
/// words as the panel controls, both directions - and two clients writing
/// their own echoes is how the phone ends up saying "wall thickness updated"
/// while the browser says "wall → 3.0 mm".
class ParsedCommand {
  ParsedCommand({
    required this.kind,
    required this.echo,
    required this.text,
    required this.refine,
    required this.problem,
  });

  final String kind;
  final String echo;
  final String text;
  final String? refine;
  final String? problem;

  /// Does acting on this need a rebuild?
  bool get changesGeometry => kind == 'set' || kind == 'holes';

  factory ParsedCommand.fromJson(Map<String, dynamic> json) => ParsedCommand(
        kind: (json['kind'] ?? '').toString(),
        echo: (json['echo'] ?? '').toString(),
        text: (json['text'] ?? '').toString(),
        refine: json['refine'] as String?,
        problem: json['problem'] as String?,
      );
}
