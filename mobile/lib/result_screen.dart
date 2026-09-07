// Screens 06-09: the result, and the bottom sheet's four states.
// Design handoff section 3, brief 6.3 and 6.7.
//
// The viewport fills the screen with floating glass chrome over it, and a
// sheet that snaps to peek / half. Every sheet state shares one command line
// docked at its bottom.
//
// THE SHEET NEVER TAKES MORE THAN HALF THE SCREEN.
//
// The handoff pins this: "the sheet must never take more than half the screen
// — the viewport stays ≥ 422 px of 844". It is not a proportion chosen for
// looks. The reason you are on this screen is to look at a part, and a sheet
// that can cover it turns the viewport into a strip you have to dismiss
// something to see. So the half snap is computed from the screen rather than
// fixed at 396, and it is clamped.
//
// THE VIEWPORT'S BOTTOM INSET FOLLOWS THE SHEET.
//
// The part is framed inside the band the sheet leaves, not inside the whole
// screen - otherwise opening the parameters puts the part behind the sheet and
// it looks as though it moved. The legend moves with the sheet for the same
// reason.
//
// WHAT IS A TURNTABLE AND WHAT IS LIVE.
//
// Brief 2.3 phase 1 ships a server-rendered turntable on native, and the
// handoff says the prototype's orbitable viewport is the phase 2 target. Both
// exist here now, because the live viewer landed first: the turntable is the
// default because it is instant and cached, and the 3D pill hands over to the
// real mesh on the phone's own GPU. The pill says which one you are looking
// at, because pictures of a part and the part itself are not the same thing
// and a viewport has to say which is on screen.

import 'dart:async';

import 'package:flutter/material.dart';

import 'api.dart';
import 'building_screen.dart';
import 'glass.dart';
import 'theme.dart';
import 'tokens.dart';
import 'viewer_screen.dart';

enum SheetState { peek, parameters, checks, export }

class ResultScreen extends StatefulWidget {
  const ResultScreen({super.key, required this.api, required this.name});

  final BpcadApi api;
  final String name;

  @override
  State<ResultScreen> createState() => _ResultScreenState();
}

class _ResultScreenState extends State<ResultScreen> {
  PartDetail? _part;
  List<TemplateParam> _schema = const [];
  final Map<String, double> _edits = {};
  final List<(String, Color)> _scrollback = [];

  SheetState _sheet = SheetState.peek;
  bool _half = false;
  bool _dims = false;
  int _step = 0;
  int _renderVersion = 1;
  String? _problem;
  bool _warmed = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    // precacheImage reads MediaQuery off the context, and calling it from
    // initState threw on every single tap of a library card. This is the fix,
    // and it is why it lives here rather than one method up.
    if (_warmed || _part == null) return;
    _warmed = true;
    for (final step in [_step, 2, 4, 6]) {
      precacheImage(
              NetworkImage(widget.api
                  .frame(widget.name, step, renderVersion: _renderVersion)
                  .toString()),
              context)
          .ignore();
    }
  }

  Future<void> _load() async {
    try {
      final health = await widget.api.health();
      final part = await widget.api.part(widget.name);
      List<TemplateParam> schema = const [];
      if (part.parametric) {
        try {
          schema = await widget.api.templateParams(part.template!);
        } catch (_) {
          // A missing schema costs the sliders, not the screen. The part's
          // numbers, checks and exports are all still readable.
        }
      }
      if (!mounted) return;
      setState(() {
        _renderVersion = health.renderVersion;
        _part = part;
        _schema = schema;
        _step = (part.frames / 8).round() % part.frames;
      });
    } catch (error) {
      if (!mounted) return;
      setState(() => _problem =
          error is BpcadUnreachable ? error.why : error.toString());
    }
  }

  void _say(String text, Color tone) {
    setState(() => _scrollback.add((text, tone)));
  }

  /// The sheet's height, and the rule that it may not eat the viewport.
  double _sheetHeight(BuildContext context) {
    final screen = MediaQuery.of(context).size.height;
    // The design's peek is 252 of 844. Scaled rather than fixed, so a small
    // phone does not end up with a sheet taking two thirds of it.
    final peek = (screen * 0.30).clamp(200.0, 300.0);
    final half = (screen * 0.47).clamp(peek, screen * 0.5);

    // THE ECHO GETS ITS OWN ROOM RATHER THAN TAKING THE PANEL'S.
    //
    // The sheet is a fixed height and the echo is variable, so adding one
    // squeezed what was already in there: after a command the Edit / Checks /
    // Export row was half cut off by the clip, which looks like a rendering
    // fault rather than a full sheet.
    //
    // Three lines of mono 11 at 1.5, plus the row's padding. Still clamped to
    // half the screen, so the handoff's rule that the viewport keeps at least
    // half of it holds whatever the echo says.
    final echo = _scrollback.isEmpty ? 0.0 : 3 * 11 * 1.5 + BpSpace.base;
    if (_half || _sheet != SheetState.peek) return half;
    return (peek + echo).clamp(peek, screen * 0.5);
  }

  @override
  Widget build(BuildContext context) {
    final part = _part;

    // THE KEYBOARD IS SCAFFOLD'S JOB, AND DOING IT TWICE IS WORSE THAN NOT
    // DOING IT AT ALL.
    //
    // The command line is docked to the sheet's bottom edge and the sheet is
    // pinned to the body's. Tapping the field opened the keyboard over it, so
    // the first fix offset every child by viewInsets.bottom - which pushed
    // the sheet a second keyboard's height up the screen, off the top, with a
    // 400dp black band where the viewport should have been.
    //
    // Scaffold's `resizeToAvoidBottomInset` already shrinks the body to sit
    // above the keyboard. `bottom: 0` is then the top of the keyboard, which
    // is exactly where the command line belongs, and the viewport takes what
    // is left. No arithmetic, and nothing to get wrong twice.
    final inset = part == null ? 0.0 : _sheetHeight(context);

    return Scaffold(
      // StackFit.expand, AND EVERY CHILD POSITIONED. Both halves matter, and
      // getting it wrong put the whole screen upside down on the device while
      // every test passed.
      //
      // A Stack sizes itself to its largest NON-POSITIONED child. The chrome
      // row was one - a SafeArea around a Wrap, about 60dp tall - so the Stack
      // became 60dp tall instead of the screen. From there: the viewport, laid
      // out as top 0 to bottom `inset`, got a NEGATIVE height and vanished;
      // and the sheet, pinned `bottom: 0` with `height: inset`, ran from -240
      // to +60 - so it drew across the top of the screen with its own contents
      // clipped above the status bar.
      //
      // Nothing threw. No overflow warning, no assertion, no red screen: the
      // layout was arithmetically valid and completely wrong. The widget test
      // passed too, because with no server `part` is null, the chrome is never
      // built, and the Stack then has no non-positioned child at all.
      body: Stack(
        fit: StackFit.expand,
        children: [
          // The viewport, framed inside the band the sheet leaves it.
          Positioned.fill(
            bottom: inset,
            child: AmbientLight(
              child: part == null ? _loading() : _viewport(part),
            ),
          ),
          if (part != null)
            Positioned(top: 0, left: 0, right: 0, child: _chrome(part)),
          if (part != null)
            Positioned(
              left: BpSpace.base,
              bottom: inset + BpSpace.base,
              child: _legend(),
            ),
          if (part != null)
            Positioned(
              left: 0,
              right: 0,
              bottom: 0,
              height: inset,
              child: _sheetPanel(part),
            ),
        ],
      ),
    );
  }

  /// THE NAME IS SHOWN BEFORE THE PART ARRIVES, because it is already known -
  /// you tapped a card that said it. Waiting for the fetch to draw the title
  /// makes a slow network look like the wrong part opening, and on a phone
  /// that cannot see the computer at all it left the screen with no clue
  /// which part you were even looking at.
  Widget _loading() => Padding(
        padding: const EdgeInsets.all(BpSpace.loose),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Text(widget.name,
                textAlign: TextAlign.center,
                style: const TextStyle(
                    fontFamily: BpType.mono,
                    fontSize: BpType.figure,
                    color: BpcadColors.ink)),
            const SizedBox(height: BpSpace.base),
            if (_problem == null)
              const SizedBox(
                  width: 18,
                  height: 18,
                  child: CircularProgressIndicator(
                      strokeWidth: 1.5, color: BpcadColors.inkFaint))
            else
              Text('$_problem — at ${widget.api.baseUrl}',
                  textAlign: TextAlign.center,
                  style: const TextStyle(
                      fontFamily: BpType.prose,
                      fontSize: BpType.label,
                      height: 1.5,
                      color: BpcadColors.inkDim)),
          ],
        ),
      );

  /// The turntable, draggable. 24 frames rendered server-side and cached hard,
  /// so a drag is instant after the first pass.
  Widget _viewport(PartDetail part) => GestureDetector(
        onHorizontalDragUpdate: (details) {
          final width = MediaQuery.of(context).size.width;
          final perStep = (width / part.frames).clamp(6.0, 60.0);
          final moved = (details.primaryDelta ?? 0) / perStep;
          if (moved.abs() < 1) return;
          setState(() {
            _step = (_step - moved.round()) % part.frames;
            if (_step < 0) _step += part.frames;
          });
        },
        child: Stack(
          children: [
            Positioned.fill(
              child: Image.network(
                widget.api
                    .frame(part.name, _step,
                        width: 900, renderVersion: _renderVersion)
                    .toString(),
                fit: BoxFit.contain,
                gaplessPlayback: true,
                errorBuilder: (_, __, ___) => Center(
                  child: Text('could not render this part',
                      style: const TextStyle(
                          fontFamily: BpType.mono,
                          fontSize: BpType.label,
                          color: BpPen.fail)),
                ),
              ),
            ),
            if (_dims && part.sizeMm != null) _callouts(part),
          ],
        ),
      );

  /// DIMENSION CALLOUTS, and what they honestly are.
  ///
  /// The design projects these from 3D anchor points. The turntable is a
  /// picture rendered on the computer, so there are no anchors here to project
  /// from - and putting a number next to an edge it does not describe would be
  /// worse than not showing it. What is shown is the measured bounding box,
  /// against the axis it belongs to, in the reference pen.
  Widget _callouts(PartDetail part) {
    final size = part.sizeMm!;
    return Positioned.fill(
      child: Stack(
        children: [
          Align(
              alignment: const Alignment(0, 0.82),
              child: _chip('X ${size[0].toStringAsFixed(1)} mm')),
          Align(
              alignment: const Alignment(0.86, 0),
              child: _chip('Y ${size[1].toStringAsFixed(1)} mm')),
          Align(
              alignment: const Alignment(-0.86, 0),
              child: _chip('Z ${size[2].toStringAsFixed(1)} mm')),
        ],
      ),
    );
  }

  Widget _chip(String text) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 3),
        decoration: BoxDecoration(
          color: BpCore.caseColor.withValues(alpha: 0.82),
          border: Border.all(color: BpPen.ref),
        ),
        child: Text(text,
            style: const TextStyle(
                fontFamily: BpType.mono,
                fontSize: BpType.micro,
                color: BpPen.ref,
                fontFeatures: [FontFeature.tabularFigures()])),
      );

  /// The floating chrome: back, a title chip, and the toggles. One wrapping
  /// row, so a long part name pushes the pills to the next line rather than
  /// under them.
  Widget _chrome(PartDetail part) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(BpSpace.snug),
          child: Wrap(
            spacing: BpSpace.snug,
            runSpacing: BpSpace.snug,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: [
              GlassSurface(
                depth: GlassDepth.pill,
                child: IconButton(
                  icon: const Icon(Icons.arrow_back, size: 18),
                  color: BpcadColors.ink,
                  constraints:
                      const BoxConstraints(minWidth: 32, minHeight: 32),
                  padding: EdgeInsets.zero,
                  onPressed: () => Navigator.of(context).maybePop(),
                ),
              ),
              GlassSurface(
                depth: GlassDepth.pill,
                padding: const EdgeInsets.symmetric(
                    horizontal: BpSpace.snug, vertical: 5),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Text(part.name,
                        style: const TextStyle(
                            fontFamily: BpType.mono,
                            fontSize: 11.5,
                            color: BpcadColors.ink)),
                    Text(
                        part.parametric
                            ? 'parametric'
                            : part.level == 2
                                ? 'composed'
                                : 'imported',
                        style: const TextStyle(
                            fontFamily: BpType.mono,
                            fontSize: 9.5,
                            color: BpcadColors.inkDim)),
                  ],
                ),
              ),
              _pill('dims', _dims, () => setState(() => _dims = !_dims)),
              _pill('3D', false, () {
                Navigator.of(context).push(MaterialPageRoute(
                  builder: (_) =>
                      ViewerScreen(api: widget.api, name: part.name),
                ));
              }),
            ],
          ),
        ),
      );

  Widget _pill(String label, bool on, VoidCallback onTap) => GlassSurface(
        depth: GlassDepth.pill,
        tint: on ? GlassTint.active : null,
        child: InkWell(
          onTap: onTap,
          borderRadius: BorderRadius.circular(BpRadius.control),
          // PADDING ONLY - NO `alignment`, NO `constraints`.
          //
          // A Container with a non-null `alignment` sizes itself as large as
          // its constraints allow. Inside the chrome's Wrap that is the full
          // screen width, so each pill became a full-width row stacked down
          // the viewport instead of a pill beside the part's name. Nothing
          // warned; it is documented Container behaviour.
          //
          // The tap target still clears the brief's 44 × 32 floor on padding
          // alone: the shortest label is "3D", about 17px of mono 12 plus 28
          // of horizontal padding, and 12px of line plus 20 of vertical.
          child: Padding(
            padding:
                const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
            child: Text(label,
                style: TextStyle(
                    fontFamily: BpType.mono,
                    fontSize: BpType.label,
                    color: on ? BpCore.phosphor : BpcadColors.inkDim)),
          ),
        ),
      );

  /// THE PEN LEGEND. Brief 6.7 forbids colour-only status, so every pen is
  /// paired with its meaning in words. It sits above the sheet and moves with
  /// it.
  Widget _legend() => GlassSurface(
        depth: GlassDepth.pill,
        padding: const EdgeInsets.symmetric(
            horizontal: BpSpace.base, vertical: BpSpace.snug),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: const [
            _PenRow(colour: BpPen.solid, meaning: 'printable part'),
            _PenRow(colour: BpPen.ref, meaning: 'measured, not printed'),
            _PenRow(colour: BpPen.pass, meaning: 'check passed'),
            _PenRow(colour: BpPen.warn, meaning: 'tolerance risk'),
          ],
        ),
      );

  // ── the sheet ───────────────────────────────────────────────────────────

  Widget _sheetPanel(PartDetail part) => GlassSurface(
        depth: GlassDepth.float,
        // Docked to the bottom edge, so three of its four sides do not exist.
        borderRadius: const BorderRadius.vertical(
            top: Radius.circular(BpRadius.float)),
        child: Column(
          children: [
            _grip(),
            Expanded(child: _sheetBody(part)),
            // THE ECHO GOES WHERE THE COMMAND LINE IS.
            //
            // It used to be drawn inside the peek body, so a command typed
            // from the parameters or the checks sheet produced an echo the
            // user never saw - and brief 6.4 makes the echo half of the
            // contract: it is how you know the machine read what you meant.
            if (_scrollback.isNotEmpty) _echo(),
            _CommandLine(
              onRun: _runCommand,
              readout: part.sizeMm == null
                  ? ''
                  : 'X ${part.sizeMm![0].toStringAsFixed(1)}  '
                      'Y ${part.sizeMm![1].toStringAsFixed(1)}  '
                      'Z ${part.sizeMm![2].toStringAsFixed(1)}',
            ),
          ],
        ),
      );

  /// 38 × 3 in `etch`, and tappable - the design says so, and a grip that
  /// looks draggable but is not is worse than no grip.
  Widget _grip() => GestureDetector(
        onTap: () => setState(() => _half = !_half),
        onVerticalDragEnd: (details) {
          final velocity = details.primaryVelocity ?? 0;
          if (velocity.abs() < 60) return;
          setState(() => _half = velocity < 0);
        },
        behavior: HitTestBehavior.opaque,
        child: Container(
          width: double.infinity,
          padding: const EdgeInsets.symmetric(vertical: BpSpace.snug),
          alignment: Alignment.center,
          child: Container(width: 38, height: 3, color: BpcadColors.edge),
        ),
      );

  Widget _sheetBody(PartDetail part) {
    switch (_sheet) {
      case SheetState.peek:
        return _peek(part);
      case SheetState.parameters:
        return _parameters(part);
      case SheetState.checks:
        return _checks(part);
      case SheetState.export:
        return _exports(part);
    }
  }

  Widget _peek(PartDetail part) => ListView(
        padding: const EdgeInsets.symmetric(horizontal: BpSpace.base),
        children: [
          Row(children: [
            // NOT RE-CHECKED, and the chip says so. bpcad stores no verdict:
            // the only honest answers are to re-verify (which costs as long as
            // rebuilding) or to say nothing, and a remembered tick is not a
            // check.
            _summaryChip('!', 'not re-checked', BpCore.phosphor),
            const SizedBox(width: BpSpace.snug),
            if (part.bodies != null)
              _summaryChip(part.bodies! > 1 ? '✓' : '·',
                  part.bodies! > 1 ? '${part.bodies} pieces · moves' : '1 piece',
                  part.bodies! > 1 ? BpPen.pass : BpcadColors.inkDim),
          ]),
          const SizedBox(height: BpSpace.base),
          if (part.sizeMm != null)
            _factRow('bbox',
                '${part.sizeMm!.map((v) => v.toStringAsFixed(1)).join(' × ')}'
                ' mm'),
          if (part.volumeCm3 != null)
            _factRow('volume', '${part.volumeCm3!.toStringAsFixed(1)} cm³'),
          if (part.material != null) _factRow('material', part.material!),
          const SizedBox(height: BpSpace.base),
          Row(children: [
            Expanded(
                child: _sheetButton('Edit', SheetState.parameters, false)),
            const SizedBox(width: BpSpace.snug),
            Expanded(child: _sheetButton('Checks', SheetState.checks, false)),
            const SizedBox(width: BpSpace.snug),
            Expanded(child: _sheetButton('Export', SheetState.export, true)),
          ]),
        ],
      );

  Widget _sheetButton(String label, SheetState target, bool commit) => SizedBox(
        height: BpMetric.tap,
        child: commit
            ? FilledButton(
                onPressed: () => setState(() {
                  _sheet = target;
                  _half = true;
                }),
                child: Text(label,
                    style: const TextStyle(
                        fontFamily: BpType.mono, fontSize: BpType.label)),
              )
            : OutlinedButton(
                onPressed: () => setState(() {
                  _sheet = target;
                  _half = true;
                }),
                style: OutlinedButton.styleFrom(
                    side: const BorderSide(color: BpcadColors.edge)),
                child: Text(label,
                    style: const TextStyle(
                        fontFamily: BpType.mono,
                        fontSize: BpType.label,
                        color: BpcadColors.ink)),
              ),
      );

  Widget _summaryChip(String mark, String text, Color tone) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 4),
        decoration: BoxDecoration(border: Border.all(color: tone)),
        child: Row(mainAxisSize: MainAxisSize.min, children: [
          Text(mark,
              style: TextStyle(
                  fontFamily: BpType.mono, fontSize: 10, color: tone)),
          const SizedBox(width: 5),
          Text(text,
              style: TextStyle(
                  fontFamily: BpType.mono, fontSize: BpType.label, color: tone)),
        ]),
      );

  Widget _factRow(String key, String value) => Padding(
        padding: const EdgeInsets.only(bottom: 5),
        child: Row(children: [
          Expanded(
            child: Text(key,
                style: const TextStyle(
                    fontFamily: BpType.mono,
                    fontSize: BpType.label,
                    color: BpcadColors.inkDim)),
          ),
          Text(value,
              style: const TextStyle(
                  fontFamily: BpType.mono,
                  fontSize: BpType.label,
                  color: BpPen.ref,
                  fontFeatures: [FontFeature.tabularFigures()])),
        ]),
      );

  Widget _header(String title, {String? state}) => Padding(
        padding: const EdgeInsets.fromLTRB(
            BpSpace.base, 0, BpSpace.base, BpSpace.snug),
        child: Row(children: [
          Expanded(
            child: Text(title,
                style: const TextStyle(
                    fontFamily: BpType.mono,
                    fontSize: BpType.micro,
                    letterSpacing: .06,
                    color: BpcadColors.inkDim)),
          ),
          if (state != null)
            Text(state,
                style: TextStyle(
                    fontFamily: BpType.mono,
                    fontSize: 9.5,
                    color: _edits.isEmpty
                        ? BpcadColors.inkFaint
                        : BpCore.phosphor)),
          IconButton(
            icon: const Icon(Icons.close, size: 16),
            color: BpcadColors.inkFaint,
            constraints: const BoxConstraints(minWidth: 32, minHeight: 32),
            padding: EdgeInsets.zero,
            onPressed: () => setState(() {
              _sheet = SheetState.peek;
              _half = false;
            }),
          ),
        ]),
      );

  /// SLIDERS ONLY WHERE THERE ARE REAL PARAMETERS AND REAL BOUNDS.
  ///
  /// The bounds are the template's own Pydantic schema. A level-2 part is a
  /// list of primitives with no named parameters - there is no "wall
  /// thickness" to nudge in a list of ops - so the panel says so and points
  /// at the command line, which does work on such a part.
  Widget _parameters(PartDetail part) {
    final slidable = _schema
        .where((p) => p.slidable && part.params[p.name] is num)
        .toList();

    return Column(
      children: [
        _header('parameters',
            state: _edits.isEmpty ? 'up to date' : 'not rebuilt'),
        Expanded(
          child: slidable.isEmpty
              ? Padding(
                  padding: const EdgeInsets.symmetric(
                      horizontal: BpSpace.base),
                  child: Text(
                      part.level == 2
                          ? 'Composed from primitives, so it has no named '
                              'parameters. Ask for a change in words on the '
                              'command line below.'
                          : 'No parameters with bounds are stored for this '
                              'part, so there is nothing to slide.',
                      style: const TextStyle(
                          fontFamily: BpType.prose,
                          fontSize: BpType.label,
                          height: 1.55,
                          color: BpcadColors.inkDim)),
                )
              : ListView(
                  padding:
                      const EdgeInsets.symmetric(horizontal: BpSpace.base),
                  children: [
                    for (final param in slidable)
                      _Slider(
                        param: param,
                        value: _edits[param.name] ??
                            (part.params[param.name] as num).toDouble(),
                        onChanged: (value) =>
                            setState(() => _edits[param.name] = value),
                        onSettled: () {},
                      ),
                    if (_edits.isNotEmpty)
                      Padding(
                        padding: const EdgeInsets.only(top: BpSpace.snug),
                        child: SizedBox(
                          height: BpMetric.tap,
                          child: FilledButton(
                            onPressed: () => _rebuild(part),
                            child: const Text('Rebuild',
                                style: TextStyle(
                                    fontFamily: BpType.mono,
                                    fontSize: BpType.label)),
                          ),
                        ),
                      ),
                  ],
                ),
        ),
      ],
    );
  }

  void _rebuild(PartDetail part) {
    if (_edits.isEmpty) return;
    // One sentence per change, through the same refine path the command line
    // uses - so a slider and `wall 3` cannot ask for different things.
    final sentence = _edits.entries.map((entry) {
      final param = _schema.firstWhere((p) => p.name == entry.key);
      final unit = param.name.endsWith('_mm')
          ? ' mm'
          : param.name.endsWith('_deg')
              ? ' degrees'
              : '';
      final value = param.whole
          ? entry.value.round().toString()
          : entry.value.toStringAsFixed(1);
      return 'set ${param.label} to $value$unit';
    }).join(', ');

    Navigator.of(context).push(MaterialPageRoute(
      builder: (_) => BuildingScreen(
        api: widget.api,
        request: sentence,
        material: part.material ?? 'petg',
        expectedSeconds: 0,
        refineOf: part.name,
      ),
    ));
  }

  Widget _checks(PartDetail part) => Column(
        children: [
          _header('checks'),
          Expanded(
            child: ListView(
              padding: const EdgeInsets.symmetric(horizontal: BpSpace.base),
              children: [
                _Check(
                  tone: BpCore.phosphor,
                  mark: '!',
                  name: 'Not re-checked',
                  tag: 'unverified',
                  why: 'This part was verified when it was built and the '
                      'result is in the report below. bpcad does not store a '
                      'verdict, because re-checking costs as long as '
                      'rebuilding and a remembered tick is not a check.',
                ),
                if (part.bodies != null)
                  _Check(
                    tone: part.bodies! > 1 ? BpPen.pass : BpcadColors.inkDim,
                    mark: part.bodies! > 1 ? '✓' : '·',
                    name: 'Pieces',
                    tag: part.bodies! > 1 ? '${part.bodies} bodies' : 'one body',
                    why: part.bodies! > 1
                        ? 'Separate solids, so they move relative to each '
                            'other. This is the fact that decides whether a '
                            'mechanism works.'
                        : 'One fused solid. Nothing in this part moves.',
                  ),
                if (part.reportMd.isNotEmpty) ...[
                  const SizedBox(height: BpSpace.base),
                  Text('the report as it was written',
                      style: const TextStyle(
                          fontFamily: BpType.mono,
                          fontSize: BpType.micro,
                          color: BpcadColors.inkDim)),
                  const SizedBox(height: BpSpace.tight),
                  Text(part.reportMd,
                      style: const TextStyle(
                          fontFamily: BpType.mono,
                          fontSize: 11,
                          height: 1.6,
                          color: BpcadColors.inkDim)),
                ],
              ],
            ),
          ),
        ],
      );

  Widget _exports(PartDetail part) {
    final rows = <Widget>[];
    if (part.hasStl) {
      rows.add(_ExportRow(
          ext: 'stl',
          name: '${part.name}.stl',
          note: 'Repaired, oriented to a flat base',
          right: '',
          gated: false));
    }
    for (final ext in ['3mf', 'step']) {
      final have = part.files.contains(ext);
      rows.add(_ExportRow(
        ext: ext,
        name: '${part.name}.$ext',
        note: ext == '3mf'
            ? 'With your printer profile embedded'
            : 'Real solid geometry for CAD',
        // Stated rather than hidden, and amber rather than disabled grey:
        // "this part does not have one" and "this is broken" must not look
        // the same.
        right: have ? '' : 'not built',
        gated: !have,
      ));
    }

    return Column(
      children: [
        _header('export'),
        Expanded(
          child: ListView(
            padding: const EdgeInsets.symmetric(horizontal: BpSpace.base),
            children: [
              ...rows,
              const SizedBox(height: BpSpace.base),
              // A download is a file-system action and this app has no
              // download plumbing yet, so it says where the files are instead
              // of offering a button that does nothing. The address is the
              // one the phone is already talking to.
              Text(
                  'The files are on the computer running bpcad, under '
                  'parts/${part.name}/out. Open '
                  '${widget.api.baseUrl}/api/part/${part.name}/stl in a '
                  'browser to pull one down.',
                  style: const TextStyle(
                      fontFamily: BpType.prose,
                      fontSize: BpType.micro,
                      height: 1.55,
                      color: BpcadColors.inkFaint)),
            ],
          ),
        ),
      ],
    );
  }

  /// The last few lines, newest at the bottom, immediately above the input.
  ///
  /// Three rather than the whole history: this is a strip inside a sheet that
  /// may not exceed half the screen, and a scrollback tall enough to scroll
  /// would be competing with the panel it sits under. The full history is
  /// what the web workspace's own scrollback panel is for.
  Widget _echo() => Padding(
        padding: const EdgeInsets.fromLTRB(
            BpSpace.base, 0, BpSpace.base, BpSpace.snug),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            for (final (text, tone) in _scrollback.length <= 3
                ? _scrollback
                : _scrollback.sublist(_scrollback.length - 3))
              Text(text,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(
                      fontFamily: BpType.mono,
                      fontSize: 11,
                      height: 1.5,
                      color: tone)),
          ],
        ),
      );

  // ── the command line ────────────────────────────────────────────────────

  Future<void> _runCommand(String line) async {
    final part = _part;
    if (part == null) return;
    _say('> $line', BpcadColors.ink);

    ParsedCommand parsed;
    try {
      parsed = await widget.api
          .command(line, material: part.material ?? 'petg');
    } catch (error) {
      _say(error is BpcadUnreachable ? error.why : error.toString(),
          BpPen.fail);
      return;
    }

    if (parsed.echo.isNotEmpty) {
      _say(
          parsed.echo,
          parsed.problem != null
              ? BpPen.fail
              : parsed.changesGeometry
                  ? BpCore.phosphor
                  : BpPen.pass);
    }

    if (parsed.changesGeometry && parsed.refine != null) {
      if (!mounted) return;
      Navigator.of(context).push(MaterialPageRoute(
        builder: (_) => BuildingScreen(
          api: widget.api,
          request: parsed.refine!,
          material: part.material ?? 'petg',
          expectedSeconds: 0,
          refineOf: part.name,
        ),
      ));
      return;
    }

    if (parsed.kind == 'motion') {
      // The joint sweep is a rendered turntable on this build, so `motion`
      // reports what exists - the piece count, which is what says whether
      // anything CAN move. Claiming a sweep the renderer did not produce
      // would be the interface lying about geometry.
      _say(
          (part.bodies ?? 1) > 1
              ? '${part.bodies} pieces — they move relative to each other'
              : 'one fused body — nothing in this part moves',
          (part.bodies ?? 1) > 1 ? BpPen.pass : BpCore.phosphor);
    }

    if (parsed.kind == 'prompt') {
      _say('that reads as a new part — start it from the composer',
          BpCore.phosphor);
    }
  }
}

class _PenRow extends StatelessWidget {
  const _PenRow({required this.colour, required this.meaning});

  final Color colour;
  final String meaning;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(bottom: 3),
        child: Row(children: [
          Container(width: 10, height: 2, color: colour),
          const SizedBox(width: 7),
          Text(meaning,
              style: const TextStyle(
                  fontFamily: BpType.mono,
                  fontSize: 9.5,
                  color: BpcadColors.inkDim)),
        ]),
      );
}

/// One parameter: label, a tappable value, a slider, and the bounds beneath.
///
/// THE VALUE IS AN INPUT, NOT A READOUT. A maker knows the exact number, and
/// hunting for it with a thumb on a 2px track is an insult. The field is
/// solid, never glass - a misread digit produces a part that does not fit.
class _Slider extends StatelessWidget {
  const _Slider({
    required this.param,
    required this.value,
    required this.onChanged,
    required this.onSettled,
  });

  final TemplateParam param;
  final double value;
  final ValueChanged<double> onChanged;
  final VoidCallback onSettled;

  @override
  Widget build(BuildContext context) {
    final low = param.low!, high = param.high!;
    final shown =
        param.whole ? value.round().toString() : value.toStringAsFixed(1);

    return Padding(
      padding: const EdgeInsets.only(bottom: BpSpace.base),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(crossAxisAlignment: CrossAxisAlignment.baseline,
              textBaseline: TextBaseline.alphabetic, children: [
            Expanded(
              child: Text(param.label,
                  style: const TextStyle(
                      fontFamily: BpType.mono,
                      fontSize: BpType.label,
                      color: BpcadColors.ink)),
            ),
            Text(shown,
                style: const TextStyle(
                    fontFamily: BpType.mono,
                    fontSize: BpType.figure,
                    fontWeight: FontWeight.w500,
                    color: BpCore.phosphor,
                    fontFeatures: [FontFeature.tabularFigures()])),
            const SizedBox(width: 3),
            Text(param.units,
                style: const TextStyle(
                    fontFamily: BpType.mono,
                    fontSize: 9.5,
                    color: BpcadColors.inkDim)),
          ]),
          Slider(
            value: value.clamp(low, high),
            min: low,
            max: high,
            // An integer parameter steps by one. A blade count of 4.3 is not
            // a louvre vent with four blades and a bit.
            divisions: param.whole ? (high - low).round() : null,
            onChanged: onChanged,
            onChangeEnd: (_) => onSettled(),
          ),
          Row(children: [
            Text(param.whole ? low.round().toString() : low.toStringAsFixed(1),
                style: const TextStyle(
                    fontFamily: BpType.mono,
                    fontSize: 9.5,
                    color: BpcadColors.inkFaint)),
            Expanded(
              child: Text(
                  param.description.replaceAll(RegExp(r'\.$'), ''),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  textAlign: TextAlign.center,
                  style: const TextStyle(
                      fontFamily: BpType.mono,
                      fontSize: 9.5,
                      color: BpcadColors.inkDim)),
            ),
            Text(
                param.whole ? high.round().toString() : high.toStringAsFixed(1),
                style: const TextStyle(
                    fontFamily: BpType.mono,
                    fontSize: 9.5,
                    color: BpcadColors.inkFaint)),
          ]),
        ],
      ),
    );
  }
}

class _Check extends StatelessWidget {
  const _Check({
    required this.tone,
    required this.mark,
    required this.name,
    required this.tag,
    required this.why,
  });

  final Color tone;
  final String mark, name, tag, why;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(bottom: BpSpace.base),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Container(
            width: 16,
            height: 16,
            alignment: Alignment.center,
            decoration: BoxDecoration(border: Border.all(color: tone)),
            child: Text(mark,
                style: TextStyle(
                    fontFamily: BpType.mono, fontSize: 10, color: tone)),
          ),
          const SizedBox(width: BpSpace.snug),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(children: [
                  Text(name,
                      style: const TextStyle(
                          fontFamily: BpType.mono,
                          fontSize: 12.5,
                          color: BpcadColors.ink)),
                  const SizedBox(width: 6),
                  // The word as well as the colour - brief 6.7 forbids
                  // colour-only status.
                  Text(tag,
                      style: TextStyle(
                          fontFamily: BpType.mono, fontSize: 9.5, color: tone)),
                ]),
                const SizedBox(height: 3),
                Text(why,
                    style: const TextStyle(
                        fontFamily: BpType.prose,
                        fontSize: BpType.label,
                        height: 1.5,
                        color: BpcadColors.inkDim)),
              ],
            ),
          ),
        ]),
      );
}

class _ExportRow extends StatelessWidget {
  const _ExportRow({
    required this.ext,
    required this.name,
    required this.note,
    required this.right,
    required this.gated,
  });

  final String ext, name, note, right;
  final bool gated;

  @override
  Widget build(BuildContext context) {
    final tone = gated ? BpCore.phosphor : BpcadColors.inkDim;
    return Container(
      padding: const EdgeInsets.symmetric(vertical: 7),
      decoration: const BoxDecoration(
          border: Border(bottom: BorderSide(color: BpcadColors.edge))),
      child: Row(children: [
        Container(
          width: BpMetric.tap,
          padding: const EdgeInsets.symmetric(vertical: 4),
          alignment: Alignment.center,
          decoration: BoxDecoration(
            border: Border.all(color: tone),
            borderRadius: BorderRadius.circular(BpRadius.edge),
          ),
          child: Text(ext.toUpperCase(),
              style: TextStyle(
                  fontFamily: BpType.mono, fontSize: 9.5, color: tone)),
        ),
        const SizedBox(width: BpSpace.snug),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(name,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(
                      fontFamily: BpType.mono,
                      fontSize: BpType.label,
                      color: BpcadColors.ink)),
              Text(note,
                  style: const TextStyle(
                      fontFamily: BpType.prose,
                      fontSize: 9.5,
                      height: 1.4,
                      color: BpcadColors.inkDim)),
            ],
          ),
        ),
        Text(right,
            style: TextStyle(
                fontFamily: BpType.mono, fontSize: 9.5, color: tone)),
      ]),
    );
  }
}

/// The command line, docked to the bottom of the sheet on every state.
///
/// Brief 6.4: always present. It parses server-side, with the same vocabulary
/// the panels use - see BpcadApi.command.
class _CommandLine extends StatefulWidget {
  const _CommandLine({required this.onRun, required this.readout});

  final Future<void> Function(String) onRun;
  final String readout;

  @override
  State<_CommandLine> createState() => _CommandLineState();
}

class _CommandLineState extends State<_CommandLine> {
  final TextEditingController _controller = TextEditingController();

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  void _run() {
    final line = _controller.text.trim();
    if (line.isEmpty) return;
    _controller.clear();
    widget.onRun(line);
  }

  @override
  Widget build(BuildContext context) => Container(
        padding: EdgeInsets.only(
          left: BpSpace.base,
          right: BpSpace.base,
          // The home-bar inset only matters when the keyboard is DOWN. With
          // it up the sheet is already riding above it and the extra padding
          // is just a gap.
          bottom: (MediaQuery.of(context).viewInsets.bottom > 0
                  ? 0.0
                  : MediaQuery.of(context).padding.bottom) +
              BpSpace.snug,
          top: BpSpace.snug,
        ),
        decoration: const BoxDecoration(
            border: Border(top: BorderSide(color: BpcadColors.edge))),
        child: Row(children: [
          const Text('>',
              style: TextStyle(
                  fontFamily: BpType.mono,
                  fontSize: 12.5,
                  fontWeight: FontWeight.w500,
                  color: BpCore.phosphor)),
          const SizedBox(width: BpSpace.snug),
          Expanded(
            child: TextField(
              controller: _controller,
              onSubmitted: (_) => _run(),
              textInputAction: TextInputAction.send,
              style: const TextStyle(
                  fontFamily: BpType.mono,
                  fontSize: 12.5,
                  color: BpcadColors.ink),
              decoration: const InputDecoration(
                filled: false,
                isDense: true,
                border: InputBorder.none,
                enabledBorder: InputBorder.none,
                focusedBorder: InputBorder.none,
                contentPadding: EdgeInsets.zero,
                hintText: 'hole m4 x4',
                hintStyle: TextStyle(
                    fontFamily: BpType.mono,
                    fontSize: 12.5,
                    color: BpcadColors.inkFaint),
              ),
            ),
          ),
          if (widget.readout.isNotEmpty) ...[
            const SizedBox(width: BpSpace.snug),
            Text(widget.readout,
                style: const TextStyle(
                    fontFamily: BpType.mono,
                    fontSize: 9.5,
                    color: BpcadColors.inkFaint,
                    fontFeatures: [FontFeature.tabularFigures()])),
          ],
        ]),
      );
}
