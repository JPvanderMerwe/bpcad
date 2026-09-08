// What a part that did not build looks like.
//
// A DRAFT WAS A DEAD END, AND IT WAS THE WORST ONE IN THE APP.
//
// The library lists drafts, correctly - a run that gave up is still something
// you started, and hiding it would mean four minutes of work vanishing with
// no trace. But tapping one opened the result screen, which asked the server
// for a turntable frame of a part with no mesh, got a 404, and showed a
// viewport of nothing over a sheet with no size, no material, no checks and
// no exports. The screen you land on after a failure told you nothing about
// the failure.
//
// Everything needed was already on disk. run.json records the request, the
// attempts, which models were tried and for how long, and the engine's own
// diagnosis - which for a failed cut is not "invalid spec" but "disc in cut
// mode removed nothing; it sits at (0.0, 0.0, -8.0) and the part spans
// z -8.0..-3.0; set z_mm to -10.00 and height_mm to 9.00". That is a sentence
// somebody can act on.
//
// SO THE POINT OF THIS SCREEN IS THE NEXT MOVE, NOT THE APOLOGY.
//
// The request comes back editable in one tap, because retyping a sentence you
// already wrote is the worst possible way to recover. The diagnosis is there
// in full. And the handoff path is named, because for anyone at the computer
// the fastest fix is to open that file and correct the one number the engine
// just told them about.

import 'package:flutter/material.dart';
import 'package:flutter/services.dart' show Clipboard, ClipboardData;

import 'api.dart';
import 'composer_screen.dart';
import 'glass.dart';
import 'theme.dart';
import 'tokens.dart';

class DraftView extends StatefulWidget {
  const DraftView({
    super.key,
    required this.api,
    required this.name,
    required this.draft,
    this.health,
  });

  final BpcadApi api;
  final String name;
  final Draft draft;
  final Health? health;

  @override
  State<DraftView> createState() => _DraftViewState();
}

class _DraftViewState extends State<DraftView> {
  /// The marked-up spec is long and technical, and it is not the first thing
  /// anybody needs. Folded, with the diagnosis above it in plain sight.
  bool _showSpec = false;
  bool _copied = false;

  Draft get _draft => widget.draft;

  void _tryAgain() {
    // THE SENTENCE COMES BACK, EDITABLE. The useful move after a failure is
    // nearly always to change a few words of what you already wrote - so it
    // is handed straight to the composer with the cursor in it, exactly as a
    // seed chip does.
    Navigator.of(context).pushReplacement(MaterialPageRoute(
      builder: (_) => ComposerScreen(
        api: widget.api,
        health: widget.health,
        seed: _draft.request,
      ),
    ));
  }

  Future<void> _copyPath() async {
    await Clipboard.setData(ClipboardData(text: _draft.handoff));
    if (!mounted) return;
    setState(() => _copied = true);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text(widget.name,
            style: const TextStyle(
                fontFamily: BpType.mono, fontSize: BpType.figure)),
      ),
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.all(BpSpace.base),
          children: [
            _whatHappened(),
            const SizedBox(height: BpSpace.base),
            _diagnosis(),
            const SizedBox(height: BpSpace.base),
            _cost(),
            const SizedBox(height: BpSpace.base),
            _byHand(),
            if (_draft.specDraft.isNotEmpty) ...[
              const SizedBox(height: BpSpace.base),
              _spec(),
            ],
            const SizedBox(height: BpSpace.room),
          ],
        ),
      ),
      bottomNavigationBar: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(BpSpace.base),
          child: SizedBox(
            width: double.infinity,
            height: 48,
            child: FilledButton(
              onPressed: _draft.request.isEmpty ? null : _tryAgain,
              child: const Text('Try again, with the words to hand',
                  style: TextStyle(
                      fontFamily: BpType.mono, fontWeight: FontWeight.w600)),
            ),
          ),
        ),
      ),
    );
  }

  /// The request. Amber rather than red: nothing broke, a run gave up, and
  /// those are different.
  ///
  /// THE CARD HOLDS THE SENTENCE AND NOTHING ELSE. Tinted glass is a callout
  /// - one thing, said once - and packing the run's five figures in beside
  /// the request turned the top third of the screen into a block of amber
  /// with the one line that matters lost inside it.
  Widget _whatHappened() => GlassSurface(
        tint: GlassTint.warn,
        depth: GlassDepth.card,
        padding: const EdgeInsets.all(BpSpace.base),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text('this one did not build',
                style: TextStyle(
                    fontFamily: BpType.mono,
                    fontSize: BpType.micro,
                    letterSpacing: .06,
                    color: BpCore.phosphor)),
            const SizedBox(height: BpSpace.snug),
            Text(_draft.request.isEmpty ? widget.name : _draft.request,
                style: const TextStyle(
                    fontFamily: BpType.mono,
                    fontSize: BpType.reading,
                    height: 1.35,
                    color: BpcadColors.ink)),
          ],
        ),
      );

  /// WHAT IT COST, because that is what decides whether to try again.
  ///
  /// Four attempts over ten minutes is a different situation from one attempt
  /// over twenty seconds, and the second number is the one that says so.
  /// Plain glass: these are figures, not a warning.
  Widget _cost() => GlassSurface(
        depth: GlassDepth.panel,
        padding: const EdgeInsets.all(BpSpace.base),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            _row('attempts', '${_draft.attempts}'),
            _row('time spent', _draft.spent),
            if (_draft.models.isNotEmpty)
              _row('models tried', _draft.models.join(' then ')),
            if (_draft.machine.isNotEmpty) _row('on', _draft.machine),
            if (_draft.levelReached != null)
              _row('got as far as',
                  _draft.levelReached == 1
                      ? 'a template'
                      : _draft.levelReached == 2
                          ? 'composing from primitives'
                          : 'level ${_draft.levelReached}'),
          ],
        ),
      );

  /// THE ENGINE'S OWN WORDS, in the mono face, unwrapped and uncut.
  ///
  /// Not "something went wrong". The copy rule for a failure is a measured
  /// value, why it failed and what to change, and this text already has all
  /// three - paraphrasing it here would throw away every number in it.
  Widget _diagnosis() {
    if (_draft.message.isEmpty) {
      return _note('The run recorded no reason, which is itself worth '
          'knowing: it means it ran out of attempts rather than hitting a '
          'problem it could name.');
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text('what the engine said',
            style: TextStyle(
                fontFamily: BpType.mono,
                fontSize: BpType.micro,
                letterSpacing: .06,
                color: BpcadColors.inkDim)),
        const SizedBox(height: BpSpace.snug),
        GlassSurface(
          depth: GlassDepth.panel,
          padding: const EdgeInsets.all(BpSpace.base),
          child: SelectableText(_draft.message,
              style: const TextStyle(
                  fontFamily: BpType.mono,
                  fontSize: 11.5,
                  height: 1.6,
                  color: BpcadColors.ink)),
        ),
      ],
    );
  }

  /// The fix that does not need another four minutes of model time.
  Widget _byHand() {
    if (_draft.handoff.isEmpty) return const SizedBox.shrink();
    return GlassSurface(
      depth: GlassDepth.panel,
      padding: const EdgeInsets.all(BpSpace.base),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text('or fix it at the computer',
              style: TextStyle(
                  fontFamily: BpType.mono,
                  fontSize: BpType.micro,
                  letterSpacing: .06,
                  color: BpcadColors.inkDim)),
          const SizedBox(height: BpSpace.snug),
          const Text(
              'The closest attempt is written out with every problem marked '
              'inline. Correcting the one number above and building it is '
              'seconds of work, against minutes for another run.',
              style: TextStyle(
                  fontFamily: BpType.prose,
                  fontSize: BpType.micro,
                  height: 1.55,
                  color: BpcadColors.inkFaint)),
          const SizedBox(height: BpSpace.snug),
          SelectableText(_draft.handoff,
              style: const TextStyle(
                  fontFamily: BpType.mono,
                  fontSize: 11,
                  color: BpPen.ref)),
          const SizedBox(height: BpSpace.snug),
          SizedBox(
            height: BpMetric.tap,
            child: OutlinedButton(
              onPressed: _copyPath,
              style: OutlinedButton.styleFrom(
                side: const BorderSide(color: BpcadColors.edge),
                shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(BpRadius.control)),
              ),
              child: Text(_copied ? 'copied' : 'Copy the path',
                  style: TextStyle(
                      fontFamily: BpType.mono,
                      fontSize: BpType.label,
                      color: _copied ? BpPen.pass : BpcadColors.ink)),
            ),
          ),
        ],
      ),
    );
  }

  /// The handoff itself, folded. It is long and it is the second thing you
  /// want, not the first.
  Widget _spec() => Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          InkWell(
            onTap: () => setState(() => _showSpec = !_showSpec),
            child: Padding(
              padding: const EdgeInsets.symmetric(vertical: BpSpace.tight),
              child: Row(children: [
                Text(_showSpec ? '−' : '+',
                    style: const TextStyle(
                        fontFamily: BpType.mono,
                        fontSize: BpType.figure,
                        height: 1,
                        color: BpcadColors.inkDim)),
                const SizedBox(width: BpSpace.snug),
                const Text('the marked-up spec',
                    style: TextStyle(
                        fontFamily: BpType.mono,
                        fontSize: BpType.micro,
                        letterSpacing: .06,
                        color: BpcadColors.inkDim)),
              ]),
            ),
          ),
          if (_showSpec)
            GlassSurface(
              depth: GlassDepth.panel,
              padding: const EdgeInsets.all(BpSpace.base),
              child: SelectableText(_draft.specDraft,
                  style: const TextStyle(
                      fontFamily: BpType.mono,
                      fontSize: 10.5,
                      height: 1.6,
                      color: BpcadColors.inkDim)),
            ),
        ],
      );

  Widget _row(String key, String value) => Padding(
        padding: const EdgeInsets.only(bottom: BpSpace.tight),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            SizedBox(
              width: 104,
              child: Text(key,
                  style: const TextStyle(
                      fontFamily: BpType.mono,
                      fontSize: BpType.label,
                      color: BpcadColors.inkDim)),
            ),
            Expanded(
              child: Text(value,
                  style: const TextStyle(
                      fontFamily: BpType.mono,
                      fontSize: BpType.label,
                      color: BpPen.ref,
                      fontFeatures: [FontFeature.tabularFigures()])),
            ),
          ],
        ),
      );

  Widget _note(String text) => GlassSurface(
        depth: GlassDepth.panel,
        padding: const EdgeInsets.all(BpSpace.base),
        child: Text(text,
            style: const TextStyle(
                fontFamily: BpType.prose,
                fontSize: BpType.label,
                height: 1.55,
                color: BpcadColors.inkDim)),
      );
}
