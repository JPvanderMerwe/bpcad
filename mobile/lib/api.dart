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

  /// Check a part again, now, against the printer profile as it stands.
  ///
  /// NOT A REBUILD, and not a job. No model is called and no geometry is
  /// composed: the mesh is already on disk and the same checks the build ran
  /// are run over it again. It was measured at 0.3s on a part whose build
  /// took 151s - which is why this is a plain request with an answer rather
  /// than a progress screen.
  Future<Checks> reverify(String name) async {
    final response = await http
        .post(_uri('/api/part/${Uri.encodeComponent(name)}/verify'))
        .timeout(const Duration(seconds: 120));
    if (response.statusCode != 200) {
      throw BpcadUnreachable(_messageFrom(response));
    }
    final body = jsonDecode(response.body) as Map<String, dynamic>;
    return Checks.fromJson(body['checks'] as Map<String, dynamic>);
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

  /// Put a photo on the server and get back the reference it became.
  ///
  /// The bytes go up raw with their content type; the server names the file
  /// itself rather than trusting one from a phone.
  ///
  /// IT COMES BACK MEASURED. The server runs the silhouette measurement as
  /// part of taking the file, which is the whole reason this returns an
  /// object rather than a path: a photo that separated nothing from its
  /// background is worth saying so about in the second it lands, not after
  /// the user has spent four minutes of GPU on it.
  Future<Reference> upload(List<int> bytes, String contentType) async {
    final response = await http
        .post(_uri('/api/upload'),
            headers: {'Content-Type': contentType}, body: bytes)
        .timeout(const Duration(seconds: 60));
    if (response.statusCode != 200) {
      throw BpcadUnreachable(_messageFrom(response));
    }
    return Reference.fromJson(
        jsonDecode(response.body) as Map<String, dynamic>);
  }

  /// What the machine is working on right now.
  ///
  /// A generate runs on the computer and outlives the screen that started it -
  /// which is the promise the building screen makes when it says "you can
  /// leave this running". Without this the phone had no way to ask what came
  /// of that, and "it carries on" was a claim the app could not check.
  Future<List<RunningJob>> jobs() async {
    final response = await http.get(_uri('/api/jobs')).timeout(_quick);
    if (response.statusCode != 200) {
      throw BpcadUnreachable('the job list answered ${response.statusCode}');
    }
    final body = jsonDecode(response.body) as Map<String, dynamic>;
    return ((body['jobs'] ?? const []) as List<dynamic>)
        .map((e) => RunningJob.fromJson(e as Map<String, dynamic>))
        .toList();
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
    required this.checks,
    required this.draft,
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

  /// THE VERDICT THIS PART WAS GIVEN, or null when there genuinely is none.
  ///
  /// Null means the part predates run.json or was imported rather than
  /// generated - a real "not known". It does NOT mean "we did not look":
  /// every part built through the pipeline was verified at build time and the
  /// whole report is on disk, which is what this field carries.
  final Checks? checks;

  /// WHY IT DID NOT BUILD, for the ones that did not.
  ///
  /// Non-null means there is no mesh and never was: the run gave up. Opening
  /// one of these used to land on the result screen, which asked for a
  /// turntable frame of a part with no geometry, got a 404, and showed
  /// nothing about what had happened. Everything in here was already on disk.
  final Draft? draft;

  bool get parametric => template != null && params.isNotEmpty;

  factory PartDetail.fromJson(Map<String, dynamic> json) {
    // `as Map<String, dynamic>` on a `const {}` fallback throws: an empty
    // const map is Map<dynamic, dynamic>, and the cast fails at runtime. It
    // never showed up because the server sends a spec for every part that
    // HAS a spec.yaml - and threw on the ones that do not, which is every
    // draft and every imported mesh: exactly the parts that also carry no
    // verdict, so it surfaced the moment those were opened.
    final spec = (json['spec'] as Map<String, dynamic>?) ??
        const <String, dynamic>{};
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
      params: (spec['params'] as Map<String, dynamic>?) ??
          const <String, dynamic>{},
      files: ((json['files'] ?? const []) as List<dynamic>)
          .map((e) => e.toString())
          .toList(),
      hasStl: json['has_stl'] != false,
      frames: (json['frames'] ?? 24) as int,
      checks: json['checks'] is Map<String, dynamic>
          ? Checks.fromJson(json['checks'] as Map<String, dynamic>)
          : null,
      draft: json['draft'] is Map<String, dynamic>
          ? Draft.fromJson(json['draft'] as Map<String, dynamic>)
          : null,
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

/// A reference photo, as the server took it and measured it.
///
/// EVERY NUMBER IN HERE IS IN PIXELS, and that is the point of carrying the
/// caveat on the object rather than leaving the UI to remember it. Nothing
/// measured off a photograph can become a millimetre without one real
/// dimension from the person holding the object - so the screen that shows
/// these says so, every time, beside them.
class Reference {
  Reference({
    required this.path,
    required this.name,
    required this.bytes,
    required this.type,
    required this.measured,
    required this.note,
    required this.needsScale,
  });

  /// Where it landed on the computer. This is what a generate is handed.
  final String path;
  final String name;
  final int bytes;
  final String type;

  /// The silhouette measurement, in the server's own keys: `width_px`,
  /// `height_px`, `aspect`, `background_cut`, and the boxes as read.
  final Map<String, dynamic> measured;

  /// Why the measurement is empty, when it is. A photo whose object touches
  /// the border, or that separated nothing from its background, fails here -
  /// and it is far better to say that now than to spend a build on it.
  final String note;
  final bool needsScale;

  bool get separated => measured.isNotEmpty;

  /// The size of the object in the frame, in pixels. Null when nothing
  /// separated - never a zero, because zero reads as a measurement.
  String? get extentPx {
    final w = measured['width_px'];
    final h = measured['height_px'];
    if (w is! num || h is! num) return null;
    return '${w.round()} × ${h.round()} px';
  }

  String? get aspect {
    final value = measured['aspect'];
    return value is num ? value.toStringAsFixed(3) : null;
  }

  String get weight => bytes < 1048576
      ? '${(bytes / 1024).round()} kB'
      : '${(bytes / 1048576).toStringAsFixed(1)} MB';

  factory Reference.fromJson(Map<String, dynamic> json) => Reference(
        path: (json['path'] ?? '').toString(),
        name: (json['name'] ?? '').toString(),
        bytes: ((json['bytes'] ?? 0) as num).round(),
        type: (json['type'] ?? '').toString(),
        measured: Map<String, dynamic>.from(
            (json['measured'] ?? const <String, dynamic>{}) as Map),
        note: (json['note'] ?? '').toString(),
        needsScale: json['needs_scale'] == true,
      );
}

/// One job on the computer, running or finished.
///
/// The elapsed time is worked out from the server's own clock reading, not
/// from when the phone happened to ask - a phone that has been asleep for ten
/// minutes must not report a job as ten minutes younger than it is.
class RunningJob {
  RunningJob({
    required this.id,
    required this.kind,
    required this.request,
    required this.done,
    required this.ok,
    required this.note,
    required this.name,
    required this.elapsedSeconds,
  });

  final String id;

  /// `generate` or `refine`.
  final String kind;
  final String request;
  final bool done;

  /// Whether it produced a part. Meaningless while [done] is false, which is
  /// why the UI reads [done] first.
  final bool ok;

  /// The last thing the engine said. This is the same text the building
  /// screen lights its stages from.
  final String note;

  /// The part it made, once there is one.
  final String name;
  final int elapsedSeconds;

  String get elapsed => elapsedSeconds >= 90
      ? '${(elapsedSeconds / 60).round()} min'
      : '${elapsedSeconds}s';

  factory RunningJob.fromJson(Map<String, dynamic> json) => RunningJob(
        id: (json['id'] ?? '').toString(),
        kind: (json['kind'] ?? '').toString(),
        request: (json['request'] ?? '').toString(),
        done: json['done'] == true,
        ok: json['ok'] == true,
        note: (json['note'] ?? '').toString(),
        name: (json['name'] ?? '').toString(),
        elapsedSeconds: ((json['elapsed_s'] ?? 0) as num).round(),
      );
}

/// One verify report, stored or just run.
///
/// WHY THIS EXISTS AT ALL. Both clients used to print "not re-checked" over
/// every part, on the stated grounds that a part on disk has no verdict and
/// that re-verifying costs as long as building. Neither was true: run.json
/// holds the entire verify report from the build, and a re-verify of a real
/// part measured 0.3s against that same part's recorded build time of 151s.
/// The expensive thing in a build is the model call, not the checking.
///
/// So a part carries its verdict, WITH the day it was taken and the profile
/// it was taken against - and [drift] says when that profile has moved since,
/// which is the one honest reason to distrust a stored answer.
class Checks {
  Checks({
    required this.verdict,
    required this.ok,
    required this.problems,
    required this.warnings,
    required this.lines,
    required this.source,
    required this.checkedAt,
    required this.drift,
    required this.nozzleMm,
    required this.material,
  });

  /// `PASS`, `PASS, with warnings` or `FAIL`, in the engine's own words.
  final String verdict;
  final bool ok;

  /// What makes the part WRONG. Needing support is deliberately not one of
  /// these - plenty of good parts need it, and a verdict that cries wolf on a
  /// known-good part teaches you to ignore verdicts.
  final List<String> problems;

  /// Worth knowing before printing, but not defects in the geometry.
  final List<String> warnings;

  /// Every check with its measured value. A status without a number is a
  /// green tick, which is what this whole panel exists not to be.
  final List<CheckLine> lines;

  /// `stored` or `just now`.
  final String source;
  final DateTime checkedAt;

  /// Reasons the stored answer may no longer hold - a nozzle that changed in
  /// the profile since. Empty for a check taken this second.
  final List<String> drift;

  final double? nozzleMm;
  final String? material;

  bool get fresh => source == 'just now';
  bool get stale => drift.isNotEmpty;

  /// How long ago, in the words a person uses. Never a raw timestamp: "built
  /// 3 days ago" is a fact somebody can act on and "1788514274" is not.
  String get age {
    final delta = DateTime.now().difference(checkedAt);
    if (delta.inSeconds < 45) return 'just now';
    if (delta.inMinutes < 60) return '${delta.inMinutes} min ago';
    if (delta.inHours < 24) return '${delta.inHours} h ago';
    return '${delta.inDays} d ago';
  }

  factory Checks.fromJson(Map<String, dynamic> json) => Checks(
        verdict: (json['verdict'] ?? '').toString(),
        ok: json['ok'] == true,
        problems: ((json['problems'] ?? const []) as List<dynamic>)
            .map((e) => e.toString())
            .toList(),
        warnings: ((json['warnings'] ?? const []) as List<dynamic>)
            .map((e) => e.toString())
            .toList(),
        lines: ((json['lines'] ?? const []) as List<dynamic>)
            .map((e) => CheckLine.fromJson(e as Map<String, dynamic>))
            .toList(),
        source: (json['source'] ?? 'stored').toString(),
        checkedAt: DateTime.fromMillisecondsSinceEpoch(
            (((json['checked_at'] ?? 0) as num) * 1000).round()),
        drift: ((json['drift'] ?? const []) as List<dynamic>)
            .map((e) => e.toString())
            .toList(),
        nozzleMm: (json['nozzle_mm'] as num?)?.toDouble(),
        material: json['material']?.toString(),
      );
}

/// One measured check: what was looked at, what it read, and how that lands.
///
/// `info` is a real status. The number of separate bodies decides whether a
/// hinge turns and is neither a pass nor a failure - it is the measurement
/// you have to look at yourself.
class CheckLine {
  CheckLine({required this.name, required this.value, required this.status});

  final String name;
  final String value;

  /// `pass`, `warn`, `fail` or `info`.
  final String status;

  factory CheckLine.fromJson(Map<String, dynamic> json) => CheckLine(
        name: (json['name'] ?? '').toString(),
        value: (json['value'] ?? '').toString(),
        status: (json['status'] ?? 'info').toString(),
      );
}

/// A run that gave up, and everything it recorded on the way.
///
/// A DRAFT IS NOT AN EMPTY PART. It is a request, a number of attempts across
/// named models, a measurable amount of time spent, and a diagnosis - which
/// for a failed cut is not "invalid spec" but "disc in cut mode removed
/// nothing; it sits at (0.0, 0.0, -8.0) and the part spans z -8.0..-3.0; set
/// z_mm to -10.00 and height_mm to 9.00". All of that was on disk in run.json
/// and none of it reached either client.
class Draft {
  Draft({
    required this.request,
    required this.attempts,
    required this.elapsedSeconds,
    required this.machine,
    required this.models,
    required this.levelReached,
    required this.message,
    required this.handoff,
    required this.specDraft,
  });

  /// What was asked for, as it was typed. This is what "try again" starts
  /// from - retyping a sentence you already wrote is the worst possible way
  /// to recover from a failure.
  final String request;
  final int attempts;
  final double elapsedSeconds;
  final String machine;

  /// The models tried, in the order they were tried: the primary, then the
  /// smaller fallback. That order is part of the story.
  final List<String> models;
  final int? levelReached;

  /// The engine's diagnosis of the last attempt. Its own words, always -
  /// paraphrasing this loses the measured numbers, which are the only part of
  /// it anybody can act on.
  final String message;

  /// Where the marked-up spec sits on the computer, for fixing by hand.
  final String handoff;
  final String specDraft;

  String get spent => elapsedSeconds >= 90
      ? '${(elapsedSeconds / 60).round()} min'
      : '${elapsedSeconds.round()} s';

  factory Draft.fromJson(Map<String, dynamic> json) => Draft(
        request: (json['request'] ?? '').toString(),
        attempts: ((json['attempts'] ?? 0) as num).round(),
        elapsedSeconds: ((json['elapsed_s'] ?? 0) as num).toDouble(),
        machine: (json['machine'] ?? '').toString(),
        models: ((json['models'] ?? const []) as List<dynamic>)
            .map((e) => e.toString())
            .toList(),
        levelReached: json['level_reached'] as int?,
        message: (json['message'] ?? '').toString(),
        handoff: (json['handoff'] ?? '').toString(),
        specDraft: (json['spec_draft'] ?? '').toString(),
      );
}
