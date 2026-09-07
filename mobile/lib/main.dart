// bpcad on a phone. Design handoff, task C2.
//
// The app shell and the library. Boot leads in once, then a tab bar with the
// composer on a centre button - the design's own arrangement, and it puts the
// one thing you came to do under a thumb.
//
// The house style is the web app's, to the byte, because both read the same
// design/tokens.json through tools/tokens.py. A phone app that looked like a
// different product would be a second product, and the handoff calls a colour
// that differs between clients a bug rather than an inconsistency.
//
// WHAT IS NOT HERE, AND WHY IT IS NOT A PLACEHOLDER.
//
// The design has an Account tab with a credit balance, a usage bar and a plan,
// and a Plans screen with three tiers and prices. There is no account system,
// no credit ledger and no billing, and the handoff itself lists store IAP
// rules as an open blocker that must not be built against. So the second tab
// says what bpcad is and what this machine is doing, which is true, instead of
// showing "12 credits" - a number that would be a fabrication sitting in the
// middle of a product whose entire promise is that every figure on screen was
// measured.

import 'package:flutter/material.dart';

import 'api.dart';
import 'boot_screen.dart';
import 'composer_screen.dart';
import 'glass.dart';
import 'marks.dart';
import 'result_screen.dart';
import 'theme.dart';
import 'tokens.dart';

void main() => runApp(const BpcadApp());

/// Over a USB cable with `adb reverse tcp:8765 tcp:8765`, the phone's own
/// localhost is the laptop. That is the testing path and it exposes nothing to
/// the network. A hosted address is a decision not yet taken, so this is a
/// constant in one place rather than an assumption spread through the app.
const String kDefaultServer = 'http://localhost:8765';

class BpcadApp extends StatelessWidget {
  const BpcadApp({super.key});

  @override
  Widget build(BuildContext context) => MaterialApp(
        title: 'bpcad',
        debugShowCheckedModeBanner: false,
        theme: bpcadTheme(),
        home: const Shell(),
      );
}

class Shell extends StatefulWidget {
  const Shell({super.key});

  @override
  State<Shell> createState() => _ShellState();
}

class _ShellState extends State<Shell> {
  final BpcadApi _api = BpcadApi(kDefaultServer);

  /// Boot runs once. Brief 6.6 allows exactly one boot moment and it must not
  /// repeat on a later screen - which means it cannot live in the tab stack.
  bool _booted = false;
  Health? _health;
  int _tab = 0;

  @override
  Widget build(BuildContext context) {
    if (!_booted) {
      return BootScreen(
        api: _api,
        onStart: (health) => setState(() {
          _health = health;
          _booted = true;
        }),
      );
    }

    return Scaffold(
      body: _tab == 0
          ? LibraryScreen(api: _api, health: _health)
          : MachineScreen(api: _api, health: _health),
      bottomNavigationBar: _TabBar(
        index: _tab,
        onTab: (index) => setState(() => _tab = index),
        onCompose: () async {
          await Navigator.of(context).push(MaterialPageRoute(
            builder: (_) => ComposerScreen(api: _api, health: _health),
          ));
          // A build that finished while the composer was open has to show up
          // without a pull-to-refresh: the library is the only place a part
          // can be found again.
          if (mounted) setState(() {});
        },
      ),
    );
  }
}

/// The tab bar, with the composer on a centre button.
///
/// Glass at the `float` depth - it sits over content, and the design lists the
/// tab bar there by name. The centre button is the one amber element on the
/// screen, which is what the design gives a commit action.
class _TabBar extends StatelessWidget {
  const _TabBar({
    required this.index,
    required this.onTab,
    required this.onCompose,
  });

  final int index;
  final ValueChanged<int> onTab;
  final VoidCallback onCompose;

  @override
  Widget build(BuildContext context) {
    return GlassSurface(
      depth: GlassDepth.float,
      borderRadius: BorderRadius.zero,
      border: false,
      child: SafeArea(
        top: false,
        child: Container(
          height: 62,
          decoration: const BoxDecoration(
              border: Border(top: BorderSide(color: BpcadColors.edge))),
          child: Row(
            children: [
              Expanded(
                  child: _tab('Library', index == 0, () => onTab(0),
                      (colour) => GridMark(colour: colour))),
              // 56 across, and a real tap target - the brief pins 44 as the
              // floor and this is the button the whole app is for.
              SizedBox(
                width: 84,
                child: Center(
                  child: InkWell(
                    onTap: onCompose,
                    borderRadius: BorderRadius.circular(BpRadius.control),
                    child: Container(
                      width: 56,
                      height: 44,
                      alignment: Alignment.center,
                      decoration: BoxDecoration(
                        color: BpCore.phosphor,
                        borderRadius:
                            BorderRadius.circular(BpRadius.control),
                      ),
                      child: const TypeMark.plus(colour: BpCore.caseColor),
                    ),
                  ),
                ),
              ),
              Expanded(
                  child: _tab('Machine', index == 1, () => onTab(1),
                      (colour) => MachineMark(colour: colour))),
            ],
          ),
        ),
      ),
    );
  }

  Widget _tab(String label, bool on, VoidCallback onTap,
          Widget Function(Color) mark) =>
      InkWell(
        onTap: onTap,
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            mark(on ? BpCore.phosphor : BpcadColors.inkFaint),
            const SizedBox(height: 5),
            // The word as well as the icon. Colour never carries meaning
            // alone - brief 6.7.
            Text(label,
                style: TextStyle(
                    fontFamily: BpType.mono,
                    fontSize: 9.5,
                    color: on ? BpCore.phosphor : BpcadColors.inkFaint)),
          ],
        ),
      );
}

/// Screen 03: the library.
class LibraryScreen extends StatefulWidget {
  const LibraryScreen({super.key, required this.api, this.health});

  final BpcadApi api;
  final Health? health;

  @override
  State<LibraryScreen> createState() => _LibraryScreenState();
}

/// The filter chips. `All` first, then the three the design names.
///
/// EVERY ONE IS DECIDED FROM DATA THE LIBRARY ALREADY CARRIES - the spec's
/// level, its template, the body count. A chip that filtered on something the
/// server does not report would quietly return nothing and look like an empty
/// library.
enum _Filter {
  all('All'),
  parametric('Parametric'),
  fromPhoto('From photo'),
  moving('Moving');

  const _Filter(this.label);
  final String label;
}

class _LibraryScreenState extends State<LibraryScreen> {
  List<PartSummary> _parts = const [];
  String? _problem;
  bool _loading = true;
  _Filter _filter = _Filter.all;

  /// Filtering happens on the phone, not the server. The whole library is a
  /// few kilobytes of JSON and the phone already has it, so typing narrows
  /// instantly and keeps working when the cable comes out - a search box that
  /// waits on a round trip per keystroke feels broken even when it is not.
  String _query = '';

  List<PartSummary> get _visible => _parts.where((part) {
        if (!part.matches(_query)) return false;
        switch (_filter) {
          case _Filter.all:
            return true;
          case _Filter.parametric:
            return part.template != null && part.template!.isNotEmpty;
          case _Filter.fromPhoto:
            // THE DESIGN'S OWN FOURTH CHIP. A part fitted to a photograph is
            // one the reconstructor produced, and none exist on this build -
            // the reconstruct backend is still `null`. So the chip is here,
            // it filters on the real thing, and it comes back empty and says
            // so rather than being quietly renamed to something that does
            // have results.
            return part.makes.contains('from photo');
          case _Filter.moving:
            return (part.bodies ?? 1) > 1;
        }
      }).toList();

  @override
  void initState() {
    super.initState();
    _refresh();
  }

  Future<void> _refresh() async {
    setState(() {
      _loading = true;
      _problem = null;
    });
    try {
      final parts = await widget.api.parts();
      if (!mounted) return;
      setState(() {
        _parts = parts;
        _loading = false;
      });
    } catch (error) {
      if (!mounted) return;
      // A phone that cannot see the computer is the ordinary case, not a
      // crash.
      setState(() {
        _problem = error is BpcadUnreachable ? error.why : error.toString();
        _loading = false;
      });
    }
  }

  void _open(PartSummary part) {
    Navigator.of(context)
        .push(MaterialPageRoute(
          builder: (_) => ResultScreen(api: widget.api, name: part.name),
        ))
        .then((_) {
      if (mounted) _refresh();
    });
  }

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      bottom: false,
      child: RefreshIndicator(
        onRefresh: _refresh,
        color: BpCore.phosphor,
        backgroundColor: BpcadColors.bezel,
        child: CustomScrollView(
          slivers: [
            SliverToBoxAdapter(child: _header()),
            if (_problem != null)
              SliverToBoxAdapter(child: _unreachable(_problem!)),
            if (_loading && _parts.isEmpty)
              const SliverToBoxAdapter(
                child: Center(child: Waiting(what: 'reading your parts')))
            else if (_visible.isEmpty)
              SliverToBoxAdapter(child: _empty()),
            SliverPadding(
              padding: const EdgeInsets.symmetric(horizontal: BpSpace.base),
              sliver: SliverGrid(
                gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
                  crossAxisCount: 2,
                  mainAxisSpacing: BpSpace.base,
                  crossAxisSpacing: BpSpace.base,
                  childAspectRatio: 0.78,
                ),
                delegate: SliverChildBuilderDelegate(
                  (context, index) => _Card(
                    part: _visible[index],
                    api: widget.api,
                    renderVersion: widget.health?.renderVersion ?? 1,
                    onTap: () => _open(_visible[index]),
                  ),
                  childCount: _visible.length,
                ),
              ),
            ),
            SliverToBoxAdapter(child: _invitation()),
            const SliverToBoxAdapter(child: SizedBox(height: BpSpace.room)),
          ],
        ),
      ),
    );
  }

  Widget _header() => Padding(
        padding: const EdgeInsets.fromLTRB(
            BpSpace.base, BpSpace.base, BpSpace.base, BpSpace.snug),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(children: [
              const Text('Your parts',
                  style: TextStyle(
                      fontFamily: BpType.mono,
                      fontSize: BpType.title,
                      fontWeight: FontWeight.w600,
                      color: BpcadColors.ink)),
              const Spacer(),
              // Where the design puts a credits pill. The honest equivalent
              // is the count, which is a fact.
              Text('${_parts.length}',
                  style: const TextStyle(
                      fontFamily: BpType.mono,
                      fontSize: BpType.label,
                      color: BpcadColors.inkDim,
                      fontFeatures: [FontFeature.tabularFigures()])),
            ]),
            const SizedBox(height: BpSpace.base),
            GlassSurface(
              depth: GlassDepth.well,
              blur: false,
              padding: const EdgeInsets.symmetric(horizontal: BpSpace.base),
              child: Row(children: [
                // THE DESIGN'S PREFIX IS A SLASH, not a magnifier: `/ Search
                // parts and versions`. It is the same prompt character the
                // command line uses, which is the point - this field takes
                // words, like every other input in the product.
                const TypeMark.search(colour: BpcadColors.inkFaint),
                const SizedBox(width: BpSpace.snug),
                Expanded(
                  child: TextField(
                    onChanged: (value) => setState(() => _query = value),
                    style: const TextStyle(
                        fontFamily: BpType.mono,
                        fontSize: BpType.body,
                        color: BpcadColors.ink),
                    decoration: const InputDecoration(
                      filled: false,
                      isDense: true,
                      border: InputBorder.none,
                      enabledBorder: InputBorder.none,
                      focusedBorder: InputBorder.none,
                      contentPadding:
                          EdgeInsets.symmetric(vertical: BpSpace.base),
                      hintText: 'Search parts and versions',
                      hintStyle: TextStyle(
                          fontFamily: BpType.mono,
                          fontSize: BpType.body,
                          color: BpcadColors.inkFaint),
                    ),
                  ),
                ),
              ]),
            ),
            const SizedBox(height: BpSpace.snug),
            SingleChildScrollView(
              scrollDirection: Axis.horizontal,
              child: Row(
                children: [
                  for (final filter in _Filter.values) ...[
                    _chip(filter),
                    const SizedBox(width: 6),
                  ],
                ],
              ),
            ),
          ],
        ),
      );

  Widget _chip(_Filter filter) {
    final on = _filter == filter;
    return InkWell(
      onTap: () => setState(() => _filter = filter),
      borderRadius: BorderRadius.circular(BpRadius.control),
      child: Container(
        constraints: const BoxConstraints(minHeight: 30),
        padding: const EdgeInsets.symmetric(horizontal: 11),
        alignment: Alignment.center,
        decoration: BoxDecoration(
          color: on ? GlassTint.active.fill : Colors.transparent,
          border: Border.all(
              color: on ? BpCore.phosphor : BpcadColors.edge),
          borderRadius: BorderRadius.circular(BpRadius.control),
        ),
        child: Text(filter.label,
            style: TextStyle(
                fontFamily: BpType.mono,
                fontSize: BpType.label,
                color: on ? BpCore.phosphor : BpcadColors.inkDim)),
      ),
    );
  }

  Widget _empty() => Padding(
        padding: const EdgeInsets.all(BpSpace.loose),
        child: Text(
            _query.isNotEmpty || _filter != _Filter.all
                ? 'Nothing matches that.'
                : 'Nothing here yet. Tap the amber button and describe a part.',
            style: const TextStyle(
                fontFamily: BpType.prose,
                fontSize: BpType.body,
                height: 1.55,
                color: BpcadColors.inkFaint)),
      );

  Widget _unreachable(String why) => Padding(
        padding: const EdgeInsets.fromLTRB(
            BpSpace.base, 0, BpSpace.base, BpSpace.base),
        child: GlassSurface(
          tint: GlassTint.warn,
          depth: GlassDepth.card,
          padding: const EdgeInsets.all(BpSpace.base),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text('Cannot see the computer running bpcad',
                  style: TextStyle(
                      fontFamily: BpType.mono,
                      fontSize: BpType.label,
                      color: BpCore.screen)),
              const SizedBox(height: BpSpace.tight),
              Text(why,
                  style: const TextStyle(
                      fontFamily: BpType.prose,
                      fontSize: BpType.label,
                      height: 1.5,
                      color: BpcadColors.inkDim)),
            ],
          ),
        ),
      );

  /// The photo-fit invitation. Dashed border in the reference pen, because
  /// that is what a photographed object becomes: a measured body, not a
  /// printed one.
  Widget _invitation() => Padding(
        padding: const EdgeInsets.all(BpSpace.base),
        child: InkWell(
          onTap: () => Navigator.of(context).push(MaterialPageRoute(
            builder: (_) => ComposerScreen(
              api: widget.api,
              health: widget.health,
              seed: 'A cradle that fits ',
            ),
          )),
          borderRadius: BorderRadius.circular(BpRadius.card),
          child: CustomPaint(
            painter: const _DashedBorder(colour: BpPen.ref),
            child: Padding(
              padding: const EdgeInsets.all(BpSpace.base),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text('Fit a part to something on your bench',
                      style: TextStyle(
                          fontFamily: BpType.mono,
                          fontSize: BpType.label,
                          color: BpPen.ref)),
                  const SizedBox(height: BpSpace.tight),
                  const Text(
                      'Photograph the object, give it one real measurement, '
                      'and we build a cradle or clamp around it.',
                      style: TextStyle(
                          fontFamily: BpType.prose,
                          fontSize: BpType.label,
                          height: 1.5,
                          color: BpcadColors.inkDim)),
                ],
              ),
            ),
          ),
        ),
      );
}

/// A library card. Glass at the `card` depth, with the blur off.
///
/// THE BLUR IS OFF ON PURPOSE. This is a grid item in a scrolling list, and a
/// BackdropFilter per card samples everything behind it on every frame of
/// every scroll. The handoff's own note says cap the blur to the sheet, the
/// tab bar and the floating pills for exactly this reason.
class _Card extends StatelessWidget {
  const _Card({
    required this.part,
    required this.api,
    required this.renderVersion,
    required this.onTap,
  });

  final PartSummary part;
  final BpcadApi api;
  final int renderVersion;
  final VoidCallback onTap;

  /// The status badge, bordered in its pen colour with the word spelled out.
  /// Colour never carries status alone - brief 6.7.
  (String, Color)? get _badge {
    if (!part.built) return ('draft', BpcadColors.inkFaint);
    if ((part.bodies ?? 1) > 1) return ('moves', BpPen.pass);
    if (part.sizeMm == null) return ('no scale', BpCore.phosphor);
    return ('ok', BpPen.pass);
  }

  @override
  Widget build(BuildContext context) {
    final badge = _badge;
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(BpRadius.card),
      child: GlassSurface(
        depth: GlassDepth.card,
        blur: false,
        padding: const EdgeInsets.all(5),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Expanded(
              child: Stack(
                children: [
                  Positioned.fill(
                    child: ClipRRect(
                      borderRadius: BorderRadius.circular(BpRadius.control),
                      // The thumbnail band sits on `case` with its own finer
                      // graticule, so a render with a transparent background
                      // has the build plate behind it rather than the card.
                      child: CustomPaint(
                        painter: const _FineGrid(),
                        child: part.built
                            ? Image.network(
                                api
                                    .frame(part.name, 3,
                                        width: 320,
                                        renderVersion: renderVersion)
                                    .toString(),
                                fit: BoxFit.contain,
                                // A RENDER ON ITS WAY IS NOT AN EMPTY CARD.
                                // The first view of a part is rendered on
                                // demand and takes real time, and a bare
                                // graticule looks exactly like a part that
                                // failed. The amber sweeps across the plate
                                // instead - which says "coming" rather than
                                // "nothing".
                                loadingBuilder:
                                    (context, child, progress) =>
                                        progress == null
                                            ? child
                                            : const Skeleton(),
                                errorBuilder: (_, __, ___) => const Center(
                                  child: Text('no render',
                                      style: TextStyle(
                                          fontFamily: BpType.mono,
                                          fontSize: 9.5,
                                          color: BpcadColors.inkFaint)),
                                ),
                              )
                            : const Center(
                                child: Text('draft\nnot built',
                                    textAlign: TextAlign.center,
                                    style: TextStyle(
                                        fontFamily: BpType.mono,
                                        fontSize: 9.5,
                                        height: 1.5,
                                        color: BpcadColors.inkFaint)),
                              ),
                      ),
                    ),
                  ),
                  Positioned(
                    left: 4,
                    top: 4,
                    child: Text(
                        part.template?.isNotEmpty == true
                            ? 'parametric'
                            : 'composed',
                        style: const TextStyle(
                            fontFamily: BpType.mono,
                            fontSize: 9,
                            color: BpcadColors.inkFaint)),
                  ),
                  if (badge != null)
                    Positioned(
                      right: 4,
                      bottom: 4,
                      child: Container(
                        padding: const EdgeInsets.symmetric(
                            horizontal: 5, vertical: 2),
                        decoration:
                            BoxDecoration(border: Border.all(color: badge.$2)),
                        child: Text(badge.$1,
                            style: TextStyle(
                                fontFamily: BpType.mono,
                                fontSize: 9,
                                color: badge.$2)),
                      ),
                    ),
                ],
              ),
            ),
            const SizedBox(height: 5),
            Text(part.name,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(
                    fontFamily: BpType.mono,
                    fontSize: BpType.label,
                    color: BpcadColors.ink)),
            Text(part.envelope,
                style: const TextStyle(
                    fontFamily: BpType.mono,
                    fontSize: 9.5,
                    color: BpPen.ref,
                    fontFeatures: [FontFeature.tabularFigures()])),
          ],
        ),
      ),
    );
  }
}

/// The thumbnail's own graticule. 13px - half the app ground's pitch, per the
/// design, so a small render still reads as sitting on a plate.
class _FineGrid extends CustomPainter {
  const _FineGrid();

  @override
  void paint(Canvas canvas, Size size) {
    canvas.drawRect(Offset.zero & size, Paint()..color = BpCore.caseColor);
    final line = Paint()
      ..color = BpCore.grid
      ..strokeWidth = 1;
    for (double x = 0; x < size.width; x += 13) {
      canvas.drawLine(Offset(x, 0), Offset(x, size.height), line);
    }
    for (double y = 0; y < size.height; y += 13) {
      canvas.drawLine(Offset(0, y), Offset(size.width, y), line);
    }
  }

  @override
  bool shouldRepaint(_FineGrid oldDelegate) => false;
}

class _DashedBorder extends CustomPainter {
  const _DashedBorder({required this.colour});

  final Color colour;

  @override
  void paint(Canvas canvas, Size size) {
    final paint = Paint()
      ..color = colour.withValues(alpha: 0.5)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1;
    const dash = 5.0, gap = 4.0, radius = BpRadius.card;

    final rect = RRect.fromRectAndRadius(
        Offset.zero & size, const Radius.circular(radius));
    final path = Path()..addRRect(rect);
    for (final metric in path.computeMetrics()) {
      double at = 0;
      while (at < metric.length) {
        final end = (at + dash).clamp(0.0, metric.length);
        canvas.drawPath(metric.extractPath(at, end), paint);
        at = end + gap;
      }
    }
  }

  @override
  bool shouldRepaint(_DashedBorder oldDelegate) =>
      oldDelegate.colour != colour;
}

/// The second tab. What the design calls Account, told honestly.
///
/// There is no account, no credit ledger and no billing, and the handoff lists
/// store IAP rules as an open blocker that must not be built against. What
/// this machine IS doing is a real thing worth a screen: which computer is
/// answering, what it can do, how long a part takes on it, and the printer
/// profile every part is checked against.
class MachineScreen extends StatelessWidget {
  const MachineScreen({super.key, required this.api, this.health});

  final BpcadApi api;
  final Health? health;

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      bottom: false,
      child: ListView(
        padding: const EdgeInsets.all(BpSpace.base),
        children: [
          const Text('This machine',
              style: TextStyle(
                  fontFamily: BpType.mono,
                  fontSize: BpType.title,
                  fontWeight: FontWeight.w600,
                  color: BpcadColors.ink)),
          const SizedBox(height: BpSpace.base),
          GlassSurface(
            depth: GlassDepth.card,
            padding: const EdgeInsets.all(BpSpace.base),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                _row('server', api.baseUrl),
                _row('model',
                    health == null
                        ? 'not answering'
                        : health!.modelAvailable
                            ? health!.tier
                            : 'none'),
                if (health != null && health!.promptSeconds > 0)
                  _row('a part takes',
                      health!.promptSeconds > 90
                          ? '~${(health!.promptSeconds / 60).round()} min'
                          : '~${health!.promptSeconds} s'),
                _row('printer', health?.printer ?? '—'),
                if (health?.bedMm != null)
                  _row('bed',
                      '${health!.bedMm!.map((v) => v.toStringAsFixed(0)).join(' × ')} mm'),
                if (health != null && health!.materials.isNotEmpty)
                  _row('materials', health!.materials.join(', ')),
              ],
            ),
          ),
          if (health?.headline.isNotEmpty == true) ...[
            const SizedBox(height: BpSpace.base),
            GlassSurface(
              tint: GlassTint.warn,
              depth: GlassDepth.card,
              padding: const EdgeInsets.all(BpSpace.base),
              // THE SERVER'S OWN SENTENCE, not a paraphrase. It measured how
              // long a part takes on that hardware and the phone did not.
              child: Text(health!.headline,
                  style: const TextStyle(
                      fontFamily: BpType.prose,
                      fontSize: BpType.label,
                      height: 1.55,
                      color: BpcadColors.inkDim)),
            ),
          ],
          const SizedBox(height: BpSpace.base),
          GlassSurface(
            depth: GlassDepth.panel,
            padding: const EdgeInsets.all(BpSpace.base),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: const [
                Text('Accounts, credits and plans',
                    style: TextStyle(
                        fontFamily: BpType.mono,
                        fontSize: BpType.label,
                        color: BpcadColors.ink)),
                SizedBox(height: BpSpace.tight),
                Text(
                    'Not built. bpcad runs on your own computer and every part '
                    'you make is on its disk — there is nothing to meter yet, '
                    'and a balance shown here would be a number nobody '
                    'measured.',
                    style: TextStyle(
                        fontFamily: BpType.prose,
                        fontSize: BpType.label,
                        height: 1.55,
                        color: BpcadColors.inkDim)),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _row(String key, String value) => Padding(
        padding: const EdgeInsets.only(bottom: BpSpace.snug),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            SizedBox(
              width: 96,
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
}
