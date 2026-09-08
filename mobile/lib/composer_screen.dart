// Screen 04: the composer. Design handoff section 3, brief 4.5 and 6.7.
//
// ONE INPUT FOR WORDS AND PHOTOS. Not a "text mode" and a "photo mode" - the
// design is explicit, and it is right: a maker photographing a bracket still
// has to say what they want done with it, and a maker typing a description
// may want to point at the thing it has to fit.
//
// THE CAMERA AND THE FILE PICKER ARE REAL NOW.
//
// They were two 56px tiles that set an apology string. The server has taken
// uploads at /api/upload the whole time and MEASURES them on arrival, so the
// missing piece was only ever on this side: pick, send the bytes, and show
// what came back. It is the one input the phone has that the computer does
// not, and leaving it stubbed made the phone a worse client than the browser
// on the one axis where it should be better.
//
// WHAT COMES BACK IS A MEASUREMENT, AND IT IS IN PIXELS.
//
// The reference card says so beside every figure. Nothing read off a
// photograph can become a millimetre without one real dimension from the
// person holding the object - brief rule 13, measure never estimate - so the
// screen asks for that dimension in words rather than quietly scaling by
// something plausible.
//
// AND A PHOTO THAT SEPARATED NOTHING IS SAID SO IMMEDIATELY. The server runs
// the silhouette cut as it takes the file, which costs a second; a build
// costs minutes. An object touching the border of the frame fails the cut,
// and being told that now is worth far more than being told it after the
// wait.
//
// THE ASSUMPTION CONTRACT IS STILL THE POINT OF THIS SCREEN.
//
// Brief 4.5: never silently invent a dimension. So the screen has two lists -
// what was read out of your words, and what was filled in for you - and both
// are EMPTY until a part exists. The lists cannot be filled honestly before
// the build: what got read out of the words is decided by the model and the
// spec it fills, and this app is a window onto that, not a second parser
// guessing at the same sentence. Showing invented chips beforehand would be
// the single worst thing this screen could do - a maker who sees "wall 3.0"
// as a parsed value believes it was understood.
//
// What CAN be said before the build, honestly, is which road the request took
// and what that means - the router is deterministic and runs before any model
// call. That is the pipeline banner, and it is a trust surface: it says what
// you are about to spend a build on.

import 'dart:typed_data';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart' show PlatformException;
import 'package:image_picker/image_picker.dart';

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

/// The dimension a photo cannot supply, offered as a sentence with the number
/// left blank.
///
/// A REFERENCE PHOTO IS SCALELESS. Every figure the server reads off it is in
/// pixels, and the only way it becomes millimetres is one real dimension from
/// whoever is holding the object. These insert the sentence and put the
/// cursor exactly where the number goes - they never fill one in, because a
/// plausible number typed by the app is precisely the failure this program
/// exists to avoid.
const List<(String, String)> kScaleHints = [
  ('overall width', 'The overall width is '),
  ('overall height', 'The overall height is '),
  ('hole size', 'The hole is '),
  ('thickness', 'The material is '),
];

/// Add one of [kScaleHints] to what is already typed, and say where the
/// cursor goes.
///
/// THE NUMBER IS LEFT OUT ON PURPOSE, and the returned cursor is the gap
/// where it belongs. This is the one place the app writes into the user's
/// sentence, so it is the one place a plausible dimension could get in - and
/// a dimension the app invented, sitting in the prompt in the user's own
/// words, would be indistinguishable from one they measured. It appends
/// rather than replaces, because the description that is already there is
/// what the photo is a reference FOR.
///
/// Top-level and pure so the rule can be tested rather than trusted.
({String text, int cursor}) scaleSentence(String existing, String phrase) {
  final before = existing.trimRight();
  final joined = before.isEmpty
      ? phrase
      : '$before${before.endsWith('.') ? ' ' : '. '}$phrase';
  return (text: '$joined mm.', cursor: joined.length);
}

class _ComposerScreenState extends State<ComposerScreen>
    with WidgetsBindingObserver {
  late final TextEditingController _prompt =
      TextEditingController(text: widget.seed);
  final ImagePicker _picker = ImagePicker();

  /// The photo on the computer, once it is up there and measured. The path in
  /// here is the server's, and it is what a generate is handed.
  Reference? _reference;

  /// The same photo's bytes, kept only to draw the thumbnail. Decoded at 160px
  /// - a full 12-megapixel frame drawn into a 72px square is tens of megabytes
  /// of texture for a picture the size of a stamp.
  Uint8List? _thumbnail;

  bool _uploading = false;
  String? _problem;
  String? _chosenMaterial;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _prompt.dispose();
    super.dispose();
  }

  /// ANDROID KILLS THIS APP WHILE THE CAMERA IS OPEN.
  ///
  /// The camera is another application's activity, so under memory pressure
  /// the system is free to reclaim ours while it is in front - and it does,
  /// on a cheap phone, reliably. Without this the user takes the photo, comes
  /// back to a freshly started app and an empty box, and concludes the camera
  /// does not work. The plugin holds the result; this is where it is
  /// collected.
  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) _recoverLostPhoto();
  }

  Future<void> _recoverLostPhoto() async {
    if (_uploading || _reference != null) return;
    try {
      final lost = await _picker.retrieveLostData();
      final file = lost.file;
      if (file == null) return;
      await _send(await file.readAsBytes(), file.name);
    } catch (_) {
      // Nothing was lost, or the platform has no such notion. Either way this
      // is a best-effort recovery and must never be the reason a screen
      // shows an error.
    }
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
        imagePath: _reference?.path,
        expectedSeconds: seconds,
      ),
    );
    if (!mounted) return;
    await Navigator.of(context).pushReplacement(route);
  }

  // -- attaching a reference ------------------------------------------------

  Future<void> _fromCamera() async {
    try {
      // 2400px is a cap, not a resize for its own sake: the server refuses
      // anything over 10 MB, and a modern phone's full frame can exceed that
      // on its own. The silhouette measurement is in pixels and its aspect is
      // what survives scaling, so the cap costs nothing that is later used as
      // a dimension - and being refused after a 12 MB upload over wifi is a
      // worse trade by a long way.
      final shot = await _picker.pickImage(
        source: ImageSource.camera,
        maxWidth: 2400,
        maxHeight: 2400,
        imageQuality: 90,
      );
      if (shot == null) return;
      await _send(await shot.readAsBytes(), shot.name);
    } on PlatformException catch (error) {
      _refused(error, 'the camera');
    } catch (error) {
      _stop(error.toString());
    }
  }

  Future<void> _fromFiles() async {
    try {
      final picked = await FilePicker.pickFiles(
        type: FileType.image,
        withData: true,
        allowMultiple: false,
      );
      final files = picked?.files ?? const [];
      if (files.isEmpty) return;
      final file = files.first;
      final bytes = file.bytes;
      if (bytes == null) {
        _stop('that file came back with no contents — try it from the '
            'gallery instead');
        return;
      }
      await _send(bytes, file.name);
    } on PlatformException catch (error) {
      _refused(error, 'your files');
    } catch (error) {
      _stop(error.toString());
    }
  }

  /// A denied permission is not a crash and must not read like one. It is
  /// also the one failure the user can fix, so the sentence says where.
  void _refused(PlatformException error, String what) {
    final denied = error.code.contains('denied') ||
        error.code.contains('access') ||
        error.code == 'photo_access_denied';
    _stop(denied
        ? 'bpcad has not been allowed to reach $what. Grant it in the '
            'phone\'s app settings and try again.'
        : error.message ?? error.code);
  }

  /// Up to the computer, and back measured.
  Future<void> _send(Uint8List bytes, String filename) async {
    setState(() {
      _uploading = true;
      _problem = null;
    });
    try {
      final reference = await widget.api.upload(bytes, _contentType(bytes));
      if (!mounted) return;
      setState(() {
        _reference = reference;
        _thumbnail = bytes;
        _uploading = false;
      });
    } on BpcadUnreachable catch (error) {
      // THE SERVER'S OWN WORDS. It is the authority on what it will accept -
      // it checks the magic bytes, not the name - and paraphrasing "that is
      // not a JPEG, PNG or WebP" into "unsupported file" would lose the one
      // sentence that explains why the file the user is looking at, called
      // photo.jpg, was refused.
      _stop(error.why);
    } catch (error) {
      _stop('could not reach ${widget.api.baseUrl} to send the photo — '
          '${error.toString()}');
    }
  }

  /// What to declare the bytes as.
  ///
  /// From the CONTENT, never the filename: an extension is a claim made by
  /// whoever named the file, and on Android a camera frame arrives named
  /// after a timestamp. Anything unrecognised still goes up, declared plainly
  /// - the server checks the magic bytes itself and owns the rule about what
  /// is allowed, and duplicating that rule here is how the two drift apart.
  static String _contentType(Uint8List bytes) {
    bool starts(List<int> magic) {
      if (bytes.length < magic.length) return false;
      for (var i = 0; i < magic.length; i++) {
        if (bytes[i] != magic[i]) return false;
      }
      return true;
    }

    if (starts(const [0xFF, 0xD8, 0xFF])) return 'image/jpeg';
    if (starts(const [0x89, 0x50, 0x4E, 0x47])) return 'image/png';
    if (starts(const [0x52, 0x49, 0x46, 0x46])) return 'image/webp';
    return 'application/octet-stream';
  }

  void _stop(String why) {
    if (!mounted) return;
    setState(() {
      _uploading = false;
      _problem = why;
    });
  }

  void _detach() => setState(() {
        _reference = null;
        _thumbnail = null;
        _problem = null;
      });

  /// Put the sentence in, leave the number out, and place the cursor on it.
  void _askForScale(String phrase) {
    final written = scaleSentence(_prompt.text, phrase);
    _prompt.value = TextEditingValue(
      text: written.text,
      selection: TextSelection.collapsed(offset: written.cursor),
    );
    setState(() {});
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
            if (_reference != null) ...[
              const SizedBox(height: BpSpace.base),
              _referenceCard(_reference!),
            ],
            if (_problem != null) ...[
              const SizedBox(height: BpSpace.base),
              _note(_problem!),
            ],
            const SizedBox(height: BpSpace.base),
            _seeds(),
            const SizedBox(height: BpSpace.base),
            _materialRow(),
            const SizedBox(height: BpSpace.base),
            _pipeline(),
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
                    onPressed:
                        value.text.trim().isEmpty || _uploading ? null : _go,
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
            _attachRow(),
          ],
        ),
      );

  /// The two ways a photo gets in, and what they are doing right now.
  ///
  /// While a photo is going up they are replaced rather than disabled: a
  /// greyed pair of tiles says "not now", and what is true is "this one is on
  /// its way and being measured".
  Widget _attachRow() {
    if (_uploading) {
      return Row(children: [
        const Caliper(height: 14),
        const SizedBox(width: BpSpace.snug),
        Text(
            _reference == null
                ? 'sending the photo to ${_host(widget.api.baseUrl)} and '
                    'measuring it'
                : 'measuring',
            style: const TextStyle(
                fontFamily: BpType.mono,
                fontSize: BpType.micro,
                color: BpcadColors.inkDim)),
      ]);
    }

    return Row(children: [
      _tile('camera', const CameraMark(colour: BpcadColors.inkFaint),
          _fromCamera),
      const SizedBox(width: BpSpace.snug),
      _tile('files', const TypeMark.plus(colour: BpcadColors.inkFaint),
          _fromFiles),
      const SizedBox(width: BpSpace.base),
      const Expanded(
        child: Text(
            'A photo is measured and becomes a reference body. It is never '
            'printed.',
            style: TextStyle(
                fontFamily: BpType.prose,
                fontSize: BpType.micro,
                height: 1.5,
                color: BpcadColors.inkFaint)),
      ),
    ]);
  }

  /// The host, without the scheme. For a sentence, where `http://` is noise.
  static String _host(String base) {
    final uri = Uri.tryParse(base);
    return uri == null || uri.host.isEmpty ? base : uri.authority;
  }

  /// 56px, the design's size, bordered in `etch`. The mark inside is drawn
  /// rather than taken from an icon family - see marks.dart.
  Widget _tile(String caption, Widget mark, VoidCallback onTap) => InkWell(
        onTap: onTap,
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

  /// THE REFERENCE, WITH WHAT WAS ACTUALLY READ OFF IT.
  ///
  /// Cyan, because that is the pen for a reference body - the thing that is
  /// measured and never printed - and the same colour will be on it in the
  /// viewer afterwards.
  ///
  /// Every figure carries `px`. That is not pedantry: the whole difference
  /// between this program and a generator that produces plausible shapes is
  /// that a millimetre here came from somewhere, and no millimetre can come
  /// out of a photograph on its own.
  Widget _referenceCard(Reference reference) => GlassSurface(
        tint: GlassTint.ref,
        depth: GlassDepth.card,
        padding: const EdgeInsets.all(BpSpace.base),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
              if (_thumbnail != null)
                ClipRRect(
                  borderRadius: BorderRadius.circular(BpRadius.edge),
                  child: Image.memory(
                    _thumbnail!,
                    width: 64,
                    height: 64,
                    fit: BoxFit.cover,
                    cacheWidth: 160,
                    // A file the server accepted can still fail to decode
                    // here - a WebP variant the phone's codec does not know.
                    // The card is about the measurement, so it loses its
                    // picture rather than throwing a red box over the screen.
                    errorBuilder: (_, __, ___) => const SizedBox.shrink(),
                  ),
                ),
              const SizedBox(width: BpSpace.base),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text('reference · ${reference.weight}',
                        style: const TextStyle(
                            fontFamily: BpType.mono,
                            fontSize: BpType.micro,
                            color: BpPen.ref)),
                    const SizedBox(height: 3),
                    if (reference.separated) ...[
                      Text(reference.extentPx ?? '',
                          style: const TextStyle(
                              fontFamily: BpType.mono,
                              fontSize: BpType.body,
                              color: BpcadColors.ink,
                              fontFeatures: [FontFeature.tabularFigures()])),
                      const SizedBox(height: 2),
                      Text('aspect ${reference.aspect}',
                          style: const TextStyle(
                              fontFamily: BpType.mono,
                              fontSize: BpType.micro,
                              color: BpcadColors.inkDim,
                              fontFeatures: [FontFeature.tabularFigures()])),
                    ] else
                      Text(
                          reference.note.isEmpty
                              ? 'nothing separated from the background'
                              : reference.note,
                          style: const TextStyle(
                              fontFamily: BpType.prose,
                              fontSize: BpType.micro,
                              height: 1.5,
                              color: BpCore.phosphor)),
                  ],
                ),
              ),
              InkWell(
                onTap: _detach,
                borderRadius: BorderRadius.circular(BpRadius.edge),
                child: const Padding(
                  padding: EdgeInsets.all(6),
                  child: TypeMark.close(colour: BpcadColors.inkDim),
                ),
              ),
            ]),
            if (reference.separated) ...[
              const SizedBox(height: BpSpace.base),
              // THE CAVEAT, AND THE WAY OUT OF IT. Saying "these are pixels"
              // and stopping there leaves the user holding a problem. The
              // chips write the sentence and leave the number blank, which is
              // the only part of it the app has no right to fill in.
              const Text(
                  'Those are pixels. One real dimension turns the whole '
                  'silhouette into millimetres — say it in your words:',
                  style: TextStyle(
                      fontFamily: BpType.prose,
                      fontSize: BpType.micro,
                      height: 1.55,
                      color: BpcadColors.inkDim)),
              const SizedBox(height: BpSpace.snug),
              Wrap(
                spacing: 6,
                runSpacing: 6,
                children: [
                  for (final (label, phrase) in kScaleHints)
                    BpChip(label: label, onTap: () => _askForScale(phrase)),
                ],
              ),
            ],
          ],
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
  ///
  /// It reads differently once a photo is attached, because the road really
  /// is different: the silhouette is measured first and handed to the same
  /// spec fill.
  Widget _pipeline() {
    final withPhoto = _reference != null && _reference!.separated;
    return GlassSurface(
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
                Text(
                    withPhoto
                        ? 'Reading this as a functional part, fitted to your '
                            'photo'
                        : 'Reading this as a functional part',
                    style: const TextStyle(
                        fontFamily: BpType.mono,
                        fontSize: BpType.label,
                        color: BpcadColors.ink)),
                const SizedBox(height: 3),
                Text(
                    withPhoto
                        ? 'The silhouette is measured, then the same spec is '
                            'filled from your words. The photo is a reference '
                            'body — it is measured, not printed.'
                        : 'Parametric solid, dimension-accurate, editable. A '
                            'photo becomes a reference body — it is measured, '
                            'not printed.',
                    style: const TextStyle(
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
  }

  /// The assumption contract, stated rather than faked.
  Widget _contract() => Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text('what you will be shown',
              style: TextStyle(
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
