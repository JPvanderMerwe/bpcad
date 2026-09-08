// Screen 04: the composer. Design handoff section 3, brief 4.5 and 6.7.
//
// ONE INPUT FOR WORDS AND PHOTOS. Not a "text mode" and a "photo mode" - the
// design is explicit, and it is right: a maker photographing a bracket still
// has to say what they want done with it, and a maker typing a description
// may want to point at the thing it has to fit.
//
// THE ASSUMPTION CONTRACT IS THE POINT OF THIS SCREEN.
//
// Brief 4.5: never silently invent a dimension. So the screen has two lists -
// what was read out of your words, and what was filled in for you - and the
// second is amber and editable. A part built from this screen must not
// contain a number the user was not shown.
//
// AND THAT IS WHY BOTH LISTS ARE EMPTY UNTIL A PART EXISTS.
//
// The lists cannot be filled honestly before the build: what got read out of
// the words is decided by the model and the spec it fills, and this app is a
// window onto that, not a second parser guessing at the same sentence. The
// design shows them populated because the design shows a part that has been
// generated. Showing invented chips beforehand would be the single worst
// thing this screen could do - a maker who sees "wall 3.0" as a parsed value
// believes it was understood.
//
// What CAN be said before the build, honestly, is which road the request took
// and what that means - the router is deterministic and runs before any model
// call. That is the pipeline banner, and it is a trust surface: it says what
// you are about to spend a build on.

import 'package:flutter/material.dart';

import 'api.dart';
import 'building_screen.dart';
import 'glass.dart';
import 'marks.dart';
import 'theme.dart';
import 'tokens.dart';

class ComposerScreen extends StatefulWidget {
  const ComposerScreen({
    super.key,
    required this.api,
    required this.health,
    this.remembered,
    this.seed = '',
  });

  final BpcadApi api;
  final Health? health;

  /// The material the user last chose, from Settings. Empty means "whatever
  /// the server lists first" - the phone should not have an opinion about a
  /// material the computer may not be configured for.
  final String? remembered;

  /// A starting sentence, for the library's "fit a part to something on your
  /// bench" invitation.
  final String seed;

  @override
  State<ComposerScreen> createState() => _ComposerScreenState();
}

/// Starting points, and every one is a part bpcad can actually make.
///
/// A BLANK BOX IS THE HARDEST THING TO ANSWER. The whole product turns on
/// somebody typing a sentence, and "describe a part" with nothing else on
/// screen is the point most people put the phone down - they do not know how
/// much to say, or whether millimetres are expected, or whether it will
/// understand "M4".
///
/// So these are worked examples rather than categories: each one shows the
/// shape of a sentence that works, with its units and its fasteners in it.
/// Tapping fills the box and leaves the cursor there, because the useful move
/// is nearly always to edit one number.
const List<(String, String)> kSeeds = [
  ('Rod bracket', 'Bracket to hold an 8 mm rod to a wall'),
  ('Drilled plate',
      'A flat plate 80 by 40 by 6 mm with two 5 mm holes 60 mm apart'),
  ('Enclosure', 'An enclosure 100 by 60 by 30 mm with 2.5 mm walls'),
  ('Hinge', 'A hinge 40 mm wide that prints in place and actually turns'),
  ('Vent', 'A louvre vent 76 mm wide with four blades'),
  ('Wall hook', 'A wall hook 80 mm tall screwed through two 5 mm holes'),
];

class _ComposerScreenState extends State<ComposerScreen> {
  late final TextEditingController _prompt =
      TextEditingController(text: widget.seed);
  String? _photoPath;
  String? _problem;
  String? _chosenMaterial;

  @override
  void dispose() {
    _prompt.dispose();
    super.dispose();
  }

  /// THE MATERIAL IS THE FIRST ONE THE SERVER LISTS, not a constant here.
  /// A phone hardcoding "petg" would build in petg on a machine configured
  /// for something else, and the clearance that comes out would be wrong by a
  /// tenth of a millimetre with nothing on screen to say so.
  String get _material {
    if (_chosenMaterial != null) return _chosenMaterial!;
    if (widget.remembered != null && widget.remembered!.isNotEmpty) {
      return widget.remembered!;
    }
    return (widget.health?.materials.isNotEmpty ?? false)
        ? widget.health!.materials.first
        : 'petg';
  }

  Future<void> _go() async {
    final request = _prompt.text.trim();
    if (request.isEmpty) return;

    // The wait is stated before it starts, from the server's own measurement.
    final seconds = widget.health?.promptSeconds ?? 0;
    final route = MaterialPageRoute<void>(
      builder: (_) => BuildingScreen(
        api: widget.api,
        request: request,
        material: _material,
        imagePath: _photoPath,
        expectedSeconds: seconds,
      ),
    );
    if (!mounted) return;
    await Navigator.of(context).pushReplacement(route);
  }

  Future<void> _attach() async {
    // NO PLUGIN, AND THIS IS A REAL LIMIT RATHER THAN A CHOICE.
    //
    // Camera capture and a file picker both need a platform plugin, and the
    // design's camera flow (brief 3.1) has a next-angle guide overlay that is
    // a screen of its own and is listed in the handoff's own "designed but not
    // drawn" section. Rather than ship a half camera, this says what it can
    // and cannot do - and the web client, which can attach a photo today,
    // is one URL away on the same server.
    setState(() {
      _problem = 'Attaching a photo needs the camera, which is the next piece '
          'of work — the handoff lists the capture flow with its next-angle '
          'guide as designed but not drawn. Until then bpcad on the computer '
          'takes a photo upload, and the part lands in this library.';
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('New part',
            style: TextStyle(
                fontFamily: BpType.mono, fontSize: BpType.figure)),
      ),
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.all(BpSpace.base),
          children: [
            _promptBox(),
            const SizedBox(height: BpSpace.base),
            _seeds(),
            const SizedBox(height: BpSpace.base),
            _materialRow(),
            const SizedBox(height: BpSpace.base),
            _pipeline(),
            if (_problem != null) ...[
              const SizedBox(height: BpSpace.base),
              _note(_problem!),
            ],
            const SizedBox(height: BpSpace.base),
            _contract(),
          ],
        ),
      ),
      bottomNavigationBar: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(BpSpace.base),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              SizedBox(
                width: double.infinity,
                height: 48,
                child: ValueListenableBuilder<TextEditingValue>(
                  valueListenable: _prompt,
                  builder: (context, value, _) => FilledButton(
                    onPressed: value.text.trim().isEmpty ? null : _go,
                    child: const Text('Generate part',
                        style: TextStyle(
                            fontFamily: BpType.mono,
                            fontWeight: FontWeight.w600)),
                  ),
                ),
              ),
              const SizedBox(height: BpSpace.snug),
              Text(
                // The design's line is "1 credit · no account needed for your
                // first part". There is no account system and no credit
                // ledger, so quoting a price would be inventing a product
                // that does not exist yet. What is true is what it costs in
                // time on this machine.
                widget.health == null
                    ? 'the computer running bpcad is not answering'
                    : widget.health!.promptSeconds > 90
                        ? 'about ${(widget.health!.promptSeconds / 60).round()}'
                            ' minutes on ${widget.health!.printer.isEmpty
                            ? 'this machine' : widget.health!.printer}'
                        : 'about ${widget.health!.promptSeconds} seconds',
                style: const TextStyle(
                    fontFamily: BpType.mono,
                    fontSize: BpType.micro,
                    color: BpcadColors.inkFaint),
              ),
            ],
          ),
        ),
      ),
    );
  }

  /// The one amber-bordered surface on the screen. The design gives the
  /// commit action one element per screen and on the composer it is this.
  Widget _promptBox() => GlassSurface(
        depth: GlassDepth.pill,
        borderRadius: BorderRadius.circular(12),
        padding: const EdgeInsets.all(BpSpace.base),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            TextField(
              controller: _prompt,
              maxLines: 5,
              minLines: 3,
              autofocus: widget.seed.isEmpty,
              textCapitalization: TextCapitalization.sentences,
              keyboardType: TextInputType.multiline,
              style: const TextStyle(
                  fontFamily: BpType.prose,
                  fontSize: BpType.reading,
                  height: 1.5,
                  color: BpcadColors.ink),
              decoration: const InputDecoration(
                filled: false,
                border: InputBorder.none,
                enabledBorder: InputBorder.none,
                focusedBorder: InputBorder.none,
                isDense: true,
                contentPadding: EdgeInsets.zero,
                hintText: 'A hinged clamp for a 32 mm pipe, wall 3 mm, '
                    'four M4 tabs, prints in place',
                hintStyle: TextStyle(
                    fontFamily: BpType.prose,
                    fontSize: BpType.reading,
                    height: 1.5,
                    color: BpcadColors.inkFaint),
              ),
            ),
            const SizedBox(height: BpSpace.base),
            Row(children: [
              _tile('camera',
                  const CameraMark(colour: BpcadColors.inkFaint)),
              const SizedBox(width: BpSpace.snug),
              _tile('files', const TypeMark.plus(colour: BpcadColors.inkFaint)),
            ]),
          ],
        ),
      );

  /// 56px, the design's size, bordered in `etch` and going amber on press.
  /// 56px, the design's size, bordered in `etch`. The mark inside is drawn
  /// rather than taken from an icon family - see marks.dart.
  Widget _tile(String caption, Widget mark) => InkWell(
        onTap: _attach,
        borderRadius: BorderRadius.circular(BpRadius.control),
        child: Container(
          width: 56,
          height: 56,
          decoration: BoxDecoration(
            border: Border.all(color: BpcadColors.edge),
            borderRadius: BorderRadius.circular(BpRadius.control),
          ),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              mark,
              const SizedBox(height: 4),
              Text(caption,
                  style: const TextStyle(
                      fontFamily: BpType.mono,
                      fontSize: 9.5,
                      color: BpcadColors.inkFaint)),
            ],
          ),
        ),
      );

  Widget _seeds() => Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text('or start from one of these',
              style: TextStyle(
                  fontFamily: BpType.mono,
                  fontSize: BpType.micro,
                  color: BpcadColors.inkDim)),
          const SizedBox(height: BpSpace.snug),
          Wrap(
            spacing: 6,
            runSpacing: 6,
            children: [
              for (final (label, sentence) in kSeeds)
                BpChip(
                  label: label,
                  onTap: () {
                    _prompt.text = sentence;
                    // The cursor goes to the END, because the useful next move
                    // is nearly always to change one number - not to retype
                    // the sentence from the front.
                    _prompt.selection =
                        TextSelection.collapsed(offset: sentence.length);
                    setState(() {});
                  },
                ),
            ],
          ),
        ],
      );

  /// WHICH MATERIAL, because it decides the clearance.
  ///
  /// This was hardcoded to whatever the server listed first. Material is not
  /// a preference here: the running clearance of a moving joint comes from
  /// it, so a hinge built in the wrong one binds or rattles - and the number
  /// is per material in config. Offering the choice is the difference between
  /// a part that turns and a part that does not.
  Widget _materialRow() {
    final materials = widget.health?.materials ?? const <String>[];
    if (materials.length < 2) return const SizedBox.shrink();

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text('material',
            style: TextStyle(
                fontFamily: BpType.mono,
                fontSize: BpType.micro,
                color: BpcadColors.inkDim)),
        const SizedBox(height: BpSpace.snug),
        Wrap(
          spacing: 6,
          children: [
            for (final name in materials)
              BpChip(
                label: name,
                selected: name == _material,
                onTap: () => setState(() => _chosenMaterial = name),
              ),
          ],
        ),
      ],
    );
  }

  /// THE PIPELINE BANNER. A trust surface: it says what the request is about
  /// to be spent on. It states the road every request on this build takes -
  /// the router is deterministic and its decision is not a guess - and it
  /// does not claim to have parsed anything yet.
  Widget _pipeline() => GlassSurface(
        tint: GlassTint.ref,
        depth: GlassDepth.card,
        padding: const EdgeInsets.all(BpSpace.base),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Container(
              width: 18,
              height: 18,
              alignment: Alignment.center,
              decoration: BoxDecoration(
                border: Border.all(color: BpPen.ref),
                borderRadius: BorderRadius.circular(2),
              ),
              child: const Text('B',
                  style: TextStyle(
                      fontFamily: BpType.mono,
                      fontSize: 10,
                      color: BpPen.ref)),
            ),
            const SizedBox(width: BpSpace.snug),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text('Reading this as a functional part',
                      style: TextStyle(
                          fontFamily: BpType.mono,
                          fontSize: BpType.label,
                          color: BpcadColors.ink)),
                  const SizedBox(height: 3),
                  const Text(
                      'Parametric solid, dimension-accurate, editable. A '
                      'photo becomes a reference body — it is measured, not '
                      'printed.',
                      style: TextStyle(
                          fontFamily: BpType.prose,
                          fontSize: BpType.label,
                          height: 1.5,
                          color: BpcadColors.inkDim)),
                ],
              ),
            ),
          ],
        ),
      );

  /// The assumption contract, stated rather than faked.
  Widget _contract() => Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('what you will be shown',
              style: const TextStyle(
                  fontFamily: BpType.mono,
                  fontSize: BpType.micro,
                  letterSpacing: .06,
                  color: BpcadColors.inkDim)),
          const SizedBox(height: BpSpace.snug),
          GlassSurface(
            depth: GlassDepth.panel,
            padding: const EdgeInsets.all(BpSpace.base),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                _contractLine(BpPen.pass,
                    'Every dimension read out of your words, as it was read.'),
                const SizedBox(height: BpSpace.snug),
                _contractLine(BpCore.phosphor,
                    'Every dimension filled in for you, marked as an '
                    'assumption and adjustable afterwards.'),
                const SizedBox(height: BpSpace.snug),
                _contractLine(BpPen.fail,
                    'Any check the part fails, with the measured number and '
                    'what to change.'),
                const SizedBox(height: BpSpace.base),
                const Text(
                    'The lists fill in once the part is built, from the spec '
                    'that was actually filled — not from a second guess at '
                    'your sentence made here on the phone.',
                    style: TextStyle(
                        fontFamily: BpType.prose,
                        fontSize: BpType.micro,
                        height: 1.55,
                        color: BpcadColors.inkFaint)),
              ],
            ),
          ),
        ],
      );

  Widget _contractLine(Color tone, String text) => Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // A square, not a dot: data marks keep the hard radii.
          Container(
              width: 8, height: 8, color: tone, margin: const EdgeInsets.only(top: 5)),
          const SizedBox(width: BpSpace.snug),
          Expanded(
            child: Text(text,
                style: const TextStyle(
                    fontFamily: BpType.prose,
                    fontSize: BpType.label,
                    height: 1.5,
                    color: BpcadColors.inkDim)),
          ),
        ],
      );

  Widget _note(String text) => GlassSurface(
        tint: GlassTint.warn,
        depth: GlassDepth.card,
        padding: const EdgeInsets.all(BpSpace.base),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Container(
              width: 12,
              height: 12,
              alignment: Alignment.center,
              margin: const EdgeInsets.only(top: 2),
              decoration: BoxDecoration(
                  border: Border.all(color: BpCore.phosphor)),
              child: const Text('!',
                  style: TextStyle(
                      fontFamily: BpType.mono,
                      fontSize: 8,
                      height: 1.3,
                      color: BpCore.phosphor)),
            ),
            const SizedBox(width: BpSpace.snug),
            Expanded(
              child: Text(text,
                  style: const TextStyle(
                      fontFamily: BpType.prose,
                      fontSize: BpType.label,
                      height: 1.5,
                      color: BpcadColors.inkDim)),
            ),
          ],
        ),
      );
}
