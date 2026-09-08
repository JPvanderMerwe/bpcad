// Screen 05: building. Design handoff section 3.
//
// A stage list, a progress line and the elapsed clock, while a part is made on
// the computer.
//
// PROGRESS IS DRIVEN BY REAL JOB STATUS, NOT A TIMER.
//
// The handoff says this in bold about its own prototype, which fakes it at
// 90ms ticks: "Progress must be driven by real job status from the queue". So
// every stage here is lit by an event the engine actually emitted, and the bar
// steps when one completes and then WAITS - it does not creep toward 99% while
// nothing is happening, which is the standard lie of a progress bar and is
// especially bad here because a real generate takes minutes on a CPU and the
// user is holding the phone the whole time.
//
// The consequence is that the bar sometimes sits still for ninety seconds. That
// is the honest shape of the work, and the elapsed clock beside it is what
// tells you the difference between slow and hung.
//
// THE DESIGN'S OUTLINE DRAWING IS NOT HERE, and that is deliberate. It is a
// 230px SVG of the part's own outline, stroked over 2.6s - and the part does
// not exist yet, so there is no outline to stroke. Drawing some other part's
// silhouette while yours is being built would be decoration standing in for
// information. What is drawn instead is the caliper mark this app already
// uses for every kind of waiting, so it is never a question of which kind of
// waiting this is.

import 'dart:async';

import 'package:flutter/material.dart';

import 'api.dart';
import 'glass.dart';
import 'result_screen.dart';
import 'theme.dart';
import 'tokens.dart';

/// The stages the engine really reports, in the order it reports them, with
/// the design's wording. Each carries the pattern that lights it.
///
/// The right-hand note is the design's too - "units, fasteners", "cadquery" -
/// and each is a fact about what that stage does rather than a status.
const List<(String, String, Pattern)> kStages = [
  ('Parsed the description', 'units, fasteners', 'using'),
  ('Resolved standards', 'template or primitives', 'template'),
  ('Built the solid', 'cadquery', 'building geometry'),
  ('Ran your printer checks', 'watertight, bed, walls', 'verify'),
  ('Wrote the exports', 'stl, 3mf', 'export'),
];

class BuildingScreen extends StatefulWidget {
  const BuildingScreen({
    super.key,
    required this.api,
    required this.request,
    required this.material,
    required this.expectedSeconds,
    this.imagePath,
    this.refineOf,
  });

  final BpcadApi api;
  final String request;
  final String material;
  final int expectedSeconds;
  final String? imagePath;

  /// When set, this is a refine of that part rather than a new build.
  final String? refineOf;

  @override
  State<BuildingScreen> createState() => _BuildingScreenState();
}

class _BuildingScreenState extends State<BuildingScreen> {
  final List<String> _log = [];
  int _reached = -1;
  int _elapsed = 0;
  Timer? _clock;
  StreamSubscription<JobEvent>? _stream;
  String? _problem;
  bool _finished = false;

  @override
  void initState() {
    super.initState();
    _clock = Timer.periodic(const Duration(seconds: 1), (_) {
      if (mounted) setState(() => _elapsed += 1);
    });
    _start();
  }

  @override
  void dispose() {
    _clock?.cancel();
    // The subscription is dropped, NOT the job. A generate carries on server
    // side whether or not this screen is listening - which is what makes
    // leaving the screen safe, and what the design's "you can leave" promise
    // rests on.
    _stream?.cancel();
    super.dispose();
  }

  Future<void> _start() async {
    try {
      final job = widget.refineOf != null
          ? await widget.api.refine(widget.refineOf!, widget.request)
          : await widget.api.generateFrom(widget.request,
              material: widget.material, imagePath: widget.imagePath);

      _stream = widget.api.events(job).listen(
        _onEvent,
        onError: (Object error) => _fail(error.toString()),
        onDone: () {
          // A stream that ends without a done frame means the connection went
          // rather than the job. Said plainly, because the two look identical
          // from here and only one of them means the part is lost.
          if (!_finished && mounted) {
            setState(() => _problem =
                'the connection dropped — the build carries on, and the part '
                'appears in your library when it lands');
          }
        },
      );
    } catch (error) {
      _fail(error is BpcadUnreachable ? error.why : error.toString());
    }
  }

  void _onEvent(JobEvent event) {
    if (!mounted) return;

    if (event.kind == 'note' || event.kind == 'started') {
      final text = event.text.isEmpty ? 'started' : event.text;
      setState(() {
        _log.add(text);
        for (var i = kStages.length - 1; i >= 0; i--) {
          if (text.toLowerCase().contains(
                  kStages[i].$3.toString().toLowerCase()) &&
              i > _reached) {
            _reached = i;
            break;
          }
        }
      });
      return;
    }

    if (event.kind == 'done' || event.kind == 'failed') {
      _finished = true;
      if (event.ok) {
        setState(() => _reached = kStages.length - 1);
        _open(event.name);
      } else {
        _fail(event.message.isEmpty ? 'no part came out' : event.message);
      }
    }
  }

  void _fail(String why) {
    if (!mounted) return;
    setState(() {
      _finished = true;
      _problem = why;
    });
  }

  void _open(String name) {
    if (!mounted || name.isEmpty) return;
    Navigator.of(context).pushReplacement(MaterialPageRoute(
      builder: (_) => ResultScreen(api: widget.api, name: name),
    ));
  }

  /// Stages done, out of the ones there are. Never a fraction of a guessed
  /// duration - see the note at the top of the file.
  double get _fraction =>
      _reached < 0 ? 0.02 : (_reached + 1) / kStages.length;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(BpSpace.loose),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(widget.refineOf == null ? 'building' : 'rebuilding',
                  style: const TextStyle(
                      fontFamily: BpType.mono,
                      fontSize: BpType.micro,
                      letterSpacing: .06,
                      color: BpCore.phosphor)),
              const SizedBox(height: BpSpace.tight),
              // MONO, not prose. The design sets this line in the mono face
              // like every other label in the product - it is the request as
              // the machine read it, which is data, and prose here made it
              // read as a heading somebody wrote.
              Text(widget.request,
                  maxLines: 3,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(
                      fontFamily: BpType.mono,
                      fontSize: BpType.figure,
                      height: 1.35,
                      color: BpcadColors.ink)),
              if (_problem == null) _waiting() else Expanded(child: _failed()),
              _stages(),
              const SizedBox(height: BpSpace.loose),
              _progress(),
              const SizedBox(height: BpSpace.base),
              _leave(),
            ],
          ),
        ),
      ),
    );
  }

  /// The design draws the part's own outline here with an amber bar scanning
  /// down it. The part does not exist yet, so there is no outline to draw -
  /// and drawing some other part's silhouette while yours is being built
  /// would be decoration standing in for information.
  ///
  /// What is honest and carries the same motion: the graticule, with the
  /// design's own 2.6s amber scan sweeping across it. The plate is real - it
  /// is the plate the part will land on - and the bar says the machine is
  /// working without claiming to show you anything it has made.
  Widget _waiting() => Expanded(
        child: Stack(
          children: [
            const Positioned.fill(child: _ScanPlate()),
            Center(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  const _Caliper(),
                  const SizedBox(height: BpSpace.wide),
                  Text(
                      widget.expectedSeconds > 90
                          ? 'about ${(widget.expectedSeconds / 60).round()}'
                              ' minutes on that machine'
                          : widget.expectedSeconds > 0
                              ? 'about ${widget.expectedSeconds} seconds'
                              : '',
                      style: const TextStyle(
                          fontFamily: BpType.mono,
                          fontSize: BpType.label,
                          color: BpcadColors.inkDim)),
                ],
              ),
            ),
          ],
        ),
      );

  Widget _failed() => GlassSurface(
        tint: GlassTint.warn,
        depth: GlassDepth.card,
        padding: const EdgeInsets.all(BpSpace.base),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text('Nothing came out',
                style: TextStyle(
                    fontFamily: BpType.mono,
                    fontSize: BpType.label,
                    color: BpCore.screen)),
            const SizedBox(height: BpSpace.tight),
            // THE ENGINE'S OWN WORDS. Not "something went wrong" - the copy
            // rule is a measured value, why it failed and what to change, and
            // paraphrasing the server's reason here would lose all three.
            Text(_problem!,
                style: const TextStyle(
                    fontFamily: BpType.prose,
                    fontSize: BpType.label,
                    height: 1.5,
                    color: BpcadColors.inkDim)),
          ],
        ),
      );

  Widget _stages() => Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          for (var i = 0; i < kStages.length; i++)
            _StageRow(
              label: kStages[i].$1,
              note: kStages[i].$2,
              done: i <= _reached,
              live: i == _reached + 1 && _problem == null && !_finished,
            ),
        ],
      );

  Widget _progress() => Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // A 2px track: it is a data mark, so it keeps the hard edge.
          SizedBox(
            height: 2,
            child: LinearProgressIndicator(
              value: _fraction,
              backgroundColor: BpcadColors.edge,
              color: _problem == null ? BpCore.phosphor : BpPen.fail,
            ),
          ),
          const SizedBox(height: BpSpace.snug),
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Text(
                  _reached < 0
                      ? 'starting'
                      : '${_reached + 1} of ${kStages.length} stages',
                  style: const TextStyle(
                      fontFamily: BpType.mono,
                      fontSize: BpType.micro,
                      color: BpcadColors.inkDim,
                      fontFeatures: [FontFeature.tabularFigures()])),
              Text('${_elapsed}s',
                  style: const TextStyle(
                      fontFamily: BpType.mono,
                      fontSize: BpType.micro,
                      color: BpcadColors.inkDim,
                      fontFeatures: [FontFeature.tabularFigures()])),
            ],
          ),
        ],
      );

  Widget _leave() => Column(
        children: [
          Text(
              _problem != null
                  ? 'Go back and try different words, or fewer of them.'
                  : 'You can leave this screen — the build carries on and the '
                      'part appears in your library.',
              textAlign: TextAlign.center,
              style: const TextStyle(
                  fontFamily: BpType.prose,
                  fontSize: BpType.micro,
                  height: 1.55,
                  color: BpcadColors.inkFaint)),
          const SizedBox(height: BpSpace.snug),
          // A BORDERED GHOST, which is what the design draws. A bare text
          // button on a dark screen does not read as a control, and this one
          // is the only way off the screen.
          SizedBox(
            width: double.infinity,
            height: BpMetric.tap,
            child: OutlinedButton(
              onPressed: () => Navigator.of(context).maybePop(),
              style: OutlinedButton.styleFrom(
                side: const BorderSide(color: BpcadColors.edge),
                shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(BpRadius.control)),
              ),
              child: Text(_problem != null ? 'Back' : 'Leave it running',
                  style: const TextStyle(
                      fontFamily: BpType.mono,
                      fontSize: BpType.label,
                      color: BpcadColors.inkDim)),
            ),
          ),
        ],
      );
}

class _StageRow extends StatelessWidget {
  const _StageRow({
    required this.label,
    required this.note,
    required this.done,
    required this.live,
  });

  final String label;
  final String note;
  final bool done;
  final bool live;

  @override
  Widget build(BuildContext context) {
    // A 9px SQUARE: hollow while pending, filled amber and pulsing while live,
    // filled with the pass pen when done. Never colour alone - the row's text
    // brightens too, and the design pairs every pen with a mark or a word.
    final mark = Container(
      width: 9,
      height: 9,
      decoration: BoxDecoration(
        color: done
            ? BpPen.pass
            : live
                ? BpCore.phosphor
                : Colors.transparent,
        border: Border.all(color: done ? BpPen.pass : BpPen.dim),
      ),
    );

    return Padding(
      padding: const EdgeInsets.only(bottom: BpSpace.base),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.center,
        children: [
          live && !MediaQuery.of(context).disableAnimations
              ? _Blink(child: mark)
              : mark,
          const SizedBox(width: BpSpace.base),
          Expanded(
            child: Text(label,
                style: TextStyle(
                    fontFamily: BpType.mono,
                    fontSize: 12.5,
                    color: done || live
                        ? BpcadColors.ink
                        : BpcadColors.inkFaint)),
          ),
          Text(note,
              style: const TextStyle(
                  fontFamily: BpType.mono,
                  fontSize: BpType.micro,
                  color: BpPen.dim)),
        ],
      ),
    );
  }
}

/// One second, opacity pulse, on the live stage only. The design's timing.
class _Blink extends StatefulWidget {
  const _Blink({required this.child});

  final Widget child;

  @override
  State<_Blink> createState() => _BlinkState();
}

class _BlinkState extends State<_Blink> with SingleTickerProviderStateMixin {
  late final AnimationController _controller = AnimationController(
    duration: const Duration(milliseconds: 1000),
    vsync: this,
  )..repeat(reverse: true);

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => FadeTransition(
        opacity: Tween<double>(begin: 0.35, end: 1).animate(_controller),
        child: widget.child,
      );
}

/// The one "working" mark in this app, borrowed from the web client on
/// purpose: it is never a question of which kind of waiting this is.
class _Caliper extends StatefulWidget {
  const _Caliper();

  @override
  State<_Caliper> createState() => _CaliperState();
}

class _CaliperState extends State<_Caliper>
    with SingleTickerProviderStateMixin {
  late final AnimationController _controller = AnimationController(
    duration: const Duration(milliseconds: 1050),
    vsync: this,
  )..repeat();

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    if (MediaQuery.of(context).disableAnimations) {
      return const _CaliperBars(heights: [10, 14, 10]);
    }
    return AnimatedBuilder(
      animation: _controller,
      builder: (context, _) {
        double bar(double offset) {
          final t = (_controller.value + offset) % 1.0;
          final wave = 1 - (t * 2 - 1).abs();
          return 5 + wave * 9;
        }

        return _CaliperBars(heights: [bar(0), bar(.14), bar(.28)]);
      },
    );
  }
}

class _CaliperBars extends StatelessWidget {
  const _CaliperBars({required this.heights});

  final List<double> heights;

  @override
  Widget build(BuildContext context) => SizedBox(
        height: 16,
        child: Row(
          mainAxisAlignment: MainAxisAlignment.center,
          crossAxisAlignment: CrossAxisAlignment.end,
          children: [
            for (final height in heights)
              Container(
                width: 3,
                height: height,
                margin: const EdgeInsets.symmetric(horizontal: 1.5),
                color: BpCore.phosphor,
              ),
          ],
        ),
      );
}


/// The graticule with an amber bar scanning across it.
///
/// The design's building screen has a 2px amber gradient bar travelling over
/// 2.6 seconds. Here it travels over the build plate rather than over a
/// drawing of the part, for the reason given at `_waiting`.
class _ScanPlate extends StatefulWidget {
  const _ScanPlate();

  @override
  State<_ScanPlate> createState() => _ScanPlateState();
}

class _ScanPlateState extends State<_ScanPlate>
    with SingleTickerProviderStateMixin {
  late final AnimationController _controller = AnimationController(
    duration: const Duration(milliseconds: 2600),
    vsync: this,
  )..repeat();

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final plate = CustomPaint(
      size: Size.infinite,
      painter: _PlatePainter(),
    );
    if (MediaQuery.of(context).disableAnimations) return plate;

    return Stack(
      fit: StackFit.expand,
      children: [
        plate,
        AnimatedBuilder(
          animation: _controller,
          builder: (context, _) => Align(
            // Linear, per the design: a scan is a constant sweep, and easing
            // it would read as something being dragged.
            alignment: Alignment(0, _controller.value * 2 - 1),
            child: Container(
              height: 2,
              decoration: BoxDecoration(
                gradient: LinearGradient(colors: [
                  BpCore.phosphor.withValues(alpha: 0),
                  BpCore.phosphor.withValues(alpha: 0.45),
                  BpCore.phosphor.withValues(alpha: 0),
                ]),
              ),
            ),
          ),
        ),
      ],
    );
  }
}

class _PlatePainter extends CustomPainter {
  /// 26px, the design's pitch on the app ground - the same as the boot
  /// screen's, because it is the same plate.
  static const double pitch = 26;

  @override
  void paint(Canvas canvas, Size size) {
    final line = Paint()
      ..color = BpCore.grid
      ..strokeWidth = 1;
    for (double x = 0; x < size.width; x += pitch) {
      canvas.drawLine(Offset(x, 0), Offset(x, size.height), line);
    }
    for (double y = 0; y < size.height; y += pitch) {
      canvas.drawLine(Offset(0, y), Offset(size.width, y), line);
    }
  }

  @override
  bool shouldRepaint(_PlatePainter oldDelegate) => false;
}
