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

import 'dart:async';

import 'package:flutter/material.dart';

import 'api.dart';
import 'boot_screen.dart';
import 'composer_screen.dart';
import 'glass.dart';
import 'marks.dart';
import 'result_screen.dart';
import 'settings.dart';
import 'theme.dart';
import 'tokens.dart';

void main() => runApp(const BpcadApp());

/// What a fresh install tries first. The real address is a SETTING now - see
/// settings.dart - because a compile-time constant of localhost works over a
/// USB cable and nowhere else, and bpcad runs on a computer the phone has to
/// be told about.
///
/// Kept as an alias so the tests and any caller that just wants "the default"
/// have one name for it rather than two.
const String kDefaultServer = Settings.defaultServer;

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
  /// THE CLIENT IS REBUILT WHEN THE ADDRESS CHANGES, not mutated.
  ///
  /// BpcadApi holds its base URL, and every screen below takes the instance
  /// rather than looking one up - so pointing the phone at a different
  /// computer means a new client and a fresh self-test, and the `key` on the
  /// tab body is what makes the screens throw away what they read from the
  /// old one.
  Settings? _settings;
  BpcadApi _api = BpcadApi(Settings.defaultServer);

  /// Boot runs once. Brief 6.6 allows exactly one boot moment and it must not
  /// repeat on a later screen - which means it cannot live in the tab stack.
  bool _booted = false;
  Health? _health;
  int _tab = 0;

  @override
  void initState() {
    super.initState();
    _open();
  }

  Future<void> _open() async {
    final settings = await Settings.open();
    if (!mounted) return;
    setState(() {
      _settings = settings;
      _api = BpcadApi(settings.server);
    });
  }

  void _useServer(String address) {
    setState(() {
      _api = BpcadApi(address);
      _health = null;
    });
    // Re-read the machine straight away, so the panel above the address field
    // is describing the computer it now points at.
    _api.health().then((health) {
      if (mounted) setState(() => _health = health);
    }).catchError((Object _) {});
  }

  @override
  Widget build(BuildContext context) {
    final settings = _settings;
    // The settings read is a single file open and takes a frame or two. The
    // boot screen cannot start until the address is known, or it would
    // self-test against the default and then be told a different one.
    if (settings == null) {
      return const Scaffold(body: SizedBox.shrink());
    }

    if (!_booted) {
      return BootScreen(
        key: ValueKey(_api.baseUrl),
        api: _api,
        onStart: (health) => setState(() {
          _health = health;
          _booted = true;
        }),
      );
    }

    return Scaffold(
      body: _tab == 0
          ? LibraryScreen(
              key: ValueKey(_api.baseUrl), api: _api, health: _health)
          : MachineScreen(
              api: _api,
              settings: settings,
              health: _health,
              onServerChanged: _useServer,
              // The health was read once at boot and never again, so starting
              // the model on the computer left every screen still saying
              // "none" until the app was restarted. The Machine tab re-reads
              // it, and hands it back so the rest of the app has it too.
              onHealth: (health) => setState(() => _health = health),
            ),
      bottomNavigationBar: _TabBar(
        index: _tab,
        onTab: (index) => setState(() => _tab = index),
        onCompose: () async {
          await Navigator.of(context).push(MaterialPageRoute(
            builder: (_) => ComposerScreen(
              api: _api,
              health: _health,
              remembered: settings.material,
            ),
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
                // WIDER THAN TALL, which is what the design's numbers give.
                //
                // The thumbnail band is 104px on a card about 177px across at
                // 390px of screen - so with the kind label, the name and the
                // size line beneath, a card is roughly 1.15 wide for 1 tall.
                // At 0.78 - taller than wide, which is what this was - the
                // grid showed two rows where the design shows nearly three,
                // and every thumbnail was a tall band of empty plate above
                // and below the part.
                gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
                  crossAxisCount: 2,
                  mainAxisSpacing: BpSpace.base,
                  crossAxisSpacing: BpSpace.base,
                  childAspectRatio: 1.15,
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
              // THE DESIGN'S PILL, carrying a fact rather than a balance.
              //
              // The design puts a credits pill here - an amber square and a
              // tabular count. There is no credit ledger, so the count is
              // how many parts you have, which is true and is the number a
              // maker actually wants at the top of their library. The pill's
              // shape, square and tabular figure are the design's.
              Container(
                padding: const EdgeInsets.symmetric(
                    horizontal: BpSpace.snug, vertical: 4),
                decoration: BoxDecoration(
                  border: Border.all(color: BpcadColors.edge),
                  borderRadius: BorderRadius.circular(BpRadius.control),
                ),
                child: Row(mainAxisSize: MainAxisSize.min, children: [
                  Container(width: 7, height: 7, color: BpCore.phosphor),
                  const SizedBox(width: 6),
                  Text('${_parts.length}',
                      style: const TextStyle(
                          fontFamily: BpType.mono,
                          fontSize: BpType.label,
                          color: BpcadColors.ink,
                          fontFeatures: [FontFeature.tabularFigures()])),
                ]),
              ),
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

  Widget _chip(_Filter filter) => BpChip(
        label: filter.label,
        selected: _filter == filter,
        onTap: () => setState(() => _filter = filter),
      );

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
            const SizedBox(height: 6),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 2),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(part.name,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(
                          fontFamily: BpType.mono,
                          fontSize: BpType.label,
                          height: 1.2,
                          color: BpcadColors.ink)),
                  // The design's second line is `v4 · 32 mm · moving` - a
                  // version, the headline dimension and what it does. There is
                  // no stored version number, so it is the measured envelope,
                  // which is the fact a maker reads a library for.
                  Text(part.envelope,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(
                          fontFamily: BpType.mono,
                          fontSize: 9.5,
                          height: 1.4,
                          color: BpPen.ref,
                          fontFeatures: [FontFeature.tabularFigures()])),
                ],
              ),
            ),
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

/// The second tab: the machine, and the settings that change what it does.
///
/// The design calls this Account and fills it with a credit balance, a usage
/// bar and a plan. There is no account system, no credit ledger and no
/// billing, and the handoff lists store IAP rules as an open blocker not to
/// be built against - so a balance here would be a fabrication in the middle
/// of a product whose whole promise is that every figure on screen was
/// measured.
///
/// What belongs here instead is the machine: which computer is answering,
/// WHAT IT IS DOING RIGHT NOW, what it holds, what it can make, and the two
/// settings that decide whether the app works at all and whether a moving
/// part comes out moving.
///
/// THE WORK PANEL IS WHY THIS TAB EXISTS RATHER THAN BEING A SETTINGS SHEET.
///
/// Both clients promise that a build outlives the screen that started it -
/// "you can leave this running" is written on the building screen. Until
/// /api/jobs there was no way to ask whether that was true: a phone that
/// locked its screen mid-build had to guess from whether a part turned up in
/// the library later. Now the tab answers it, and the answer comes from the
/// job's own event log rather than from a stage this app decided it must be
/// at by now.
class MachineScreen extends StatefulWidget {
  const MachineScreen({
    super.key,
    required this.api,
    required this.settings,
    required this.onServerChanged,
    this.onHealth,
    this.health,
  });

  final BpcadApi api;
  final Settings settings;

  /// Handed the new address so the shell can rebuild its client and re-run
  /// the self-test - the API object holds its base URL, so changing it means
  /// making a new one.
  final ValueChanged<String> onServerChanged;

  /// Handed a fresh reading so the rest of the app gets it too. The health
  /// was read once at boot and then never again, which meant starting the
  /// model on the computer left every other screen still saying "none" until
  /// the app was restarted.
  final ValueChanged<Health>? onHealth;

  final Health? health;

  @override
  State<MachineScreen> createState() => _MachineScreenState();
}

class _MachineScreenState extends State<MachineScreen> {
  late final TextEditingController _server =
      TextEditingController(text: widget.settings.server);
  String? _testing;
  bool _reachable = false;
  bool _tested = false;

  /// The machine's own reading, refreshed here rather than frozen at boot.
  Health? _health;

  List<RunningJob> _jobs = const [];
  List<PartSummary> _parts = const [];
  String? _libraryProblem;
  Timer? _poll;

  /// A read is already in flight. The job read has a ten-second timeout and
  /// the poll fires every three, so against a computer that is not answering
  /// - which is the ordinary state of a phone - they would stack three deep
  /// and stay there.
  bool _reading = false;

  @override
  void initState() {
    super.initState();
    _health = widget.health;
    _refresh();
    // THREE SECONDS, and only while this tab is on screen - the shell builds
    // the Machine tab only when it is selected, so the timer dies with it.
    // A build takes minutes, so this is not a tight loop chasing a fast
    // number; it is slow enough to be cheap and quick enough that a stage
    // landing is visible while you are looking at it.
    _poll = Timer.periodic(const Duration(seconds: 3), (_) => _readJobs());
  }

  @override
  void dispose() {
    _poll?.cancel();
    _server.dispose();
    super.dispose();
  }

  Future<void> _refresh() async {
    await Future.wait([_readHealth(), _readJobs(), _readLibrary()]);
  }

  Future<void> _readHealth() async {
    try {
      final health = await widget.api.health();
      if (!mounted) return;
      setState(() => _health = health);
      widget.onHealth?.call(health);
    } catch (_) {
      // The panels below already say what a null health means, and they say
      // it with the address in the sentence. A second error line here would
      // be the same fact twice.
    }
  }

  Future<void> _readJobs() async {
    if (_reading) return;
    _reading = true;
    try {
      final jobs = await widget.api.jobs();
      if (mounted) setState(() => _jobs = jobs);
    } catch (_) {
      if (mounted) setState(() => _jobs = const []);
    } finally {
      _reading = false;
    }
  }

  Future<void> _readLibrary() async {
    try {
      final parts = await widget.api.parts();
      if (!mounted) return;
      setState(() {
        _parts = parts;
        _libraryProblem = null;
      });
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _parts = const [];
        _libraryProblem = error is BpcadUnreachable ? error.why : '$error';
      });
    }
  }

  /// Try the address BEFORE saving it.
  ///
  /// Saving first and letting the app fail against it means an unusable app
  /// and a settings screen that says everything is fine. This asks the
  /// address whether anything is there, says what came back, and only then
  /// offers to keep it.
  Future<void> _test() async {
    final address = Settings.normalise(_server.text);
    setState(() {
      _testing = 'asking $address';
      _tested = false;
    });
    try {
      final health = await BpcadApi(address).health();
      if (!mounted) return;
      setState(() {
        _reachable = true;
        _tested = true;
        _testing = health.printer.isEmpty
            ? 'answered — no printer configured'
            : 'answered — ${health.printer}, model ${health.tier}';
      });
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _reachable = false;
        _tested = true;
        // The address is in the message. "Could not connect" with no address
        // is the least useful sentence an app can print.
        _testing = error is BpcadUnreachable
            ? '${error.why} — at $address'
            : 'nothing answered at $address';
      });
    }
  }

  Future<void> _save() async {
    final address = Settings.normalise(_server.text);
    await widget.settings.setServer(address);
    _server.text = address;
    widget.onServerChanged(address);
    if (mounted) {
      setState(() => _testing = 'using $address');
    }
  }

  void _openPart(String name) {
    if (name.isEmpty) return;
    Navigator.of(context).push(MaterialPageRoute(
      builder: (_) => ResultScreen(api: widget.api, name: name),
    ));
  }

  @override
  Widget build(BuildContext context) {
    final health = _health;
    return SafeArea(
      bottom: false,
      // PULL TO REFRESH, because everything on this screen is a reading of
      // another computer and every reading here goes stale. The three reads
      // it runs are the three panels below it.
      child: RefreshIndicator(
        onRefresh: _refresh,
        color: BpCore.phosphor,
        backgroundColor: BpcadColors.bezel,
        child: ListView(
          padding: const EdgeInsets.all(BpSpace.base),
          physics: const AlwaysScrollableScrollPhysics(),
          children: [
            const Text('This machine',
                style: TextStyle(
                    fontFamily: BpType.mono,
                    fontSize: BpType.title,
                    fontWeight: FontWeight.w600,
                    color: BpcadColors.ink)),
            const SizedBox(height: BpSpace.base),
            _workPanel(),
            const SizedBox(height: BpSpace.base),
            _serverPanel(),
            const SizedBox(height: BpSpace.base),
            _statePanel(health),
            const SizedBox(height: BpSpace.base),
            _libraryPanel(),
            const SizedBox(height: BpSpace.base),
            _makesPanel(health),
            const SizedBox(height: BpSpace.base),
            _materialPanel(health),
            const SizedBox(height: BpSpace.base),
            _effectsPanel(),
            const SizedBox(height: BpSpace.base),
            _profilePanel(health),
            const SizedBox(height: BpSpace.room),
          ],
        ),
      ),
    );
  }

  /// WHAT THE COMPUTER IS DOING, from its own job log.
  ///
  /// Running work first, then what it just finished, because the first
  /// question is "is it working" and the second is "what came of the one I
  /// left". A finished job that produced a part opens it - which is the
  /// shortest path there is from "it is done" to looking at it.
  Widget _workPanel() {
    final running = _jobs.where((job) => !job.done).toList();
    final finished = _jobs.where((job) => job.done).take(3).toList();

    return GlassSurface(
      depth: GlassDepth.card,
      padding: const EdgeInsets.all(BpSpace.base),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(children: [
            const Text('working on',
                style: TextStyle(
                    fontFamily: BpType.mono,
                    fontSize: BpType.micro,
                    color: BpcadColors.inkDim)),
            const Spacer(),
            if (running.isNotEmpty) const Caliper(height: 12),
          ]),
          const SizedBox(height: BpSpace.snug),
          if (running.isEmpty && finished.isEmpty)
            Text(
                _health == null
                    ? 'not answering, so there is nothing to report'
                    : 'nothing running',
                style: const TextStyle(
                    fontFamily: BpType.mono,
                    fontSize: BpType.label,
                    color: BpcadColors.inkFaint)),
          for (final job in running) _jobRow(job),
          if (running.isNotEmpty && finished.isNotEmpty)
            const Padding(
              padding: EdgeInsets.symmetric(vertical: BpSpace.snug),
              child: Divider(height: 1, color: BpcadColors.edge),
            ),
          for (final job in finished) _jobRow(job),
        ],
      ),
    );
  }

  Widget _jobRow(RunningJob job) {
    // Never colour alone - brief 6.7. The square is paired with the word
    // beside it in every state.
    final (Color tone, String state) = job.done
        ? (job.ok ? BpPen.pass : BpPen.fail, job.ok ? 'built' : 'failed')
        : (BpCore.phosphor, job.kind == 'refine' ? 'rebuilding' : 'building');

    return InkWell(
      onTap: job.done && job.ok ? () => _openPart(job.name) : null,
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: BpSpace.tight),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Container(
              width: 9,
              height: 9,
              margin: const EdgeInsets.only(top: 4),
              decoration: BoxDecoration(
                color: job.done ? tone : Colors.transparent,
                border: Border.all(color: tone),
              ),
            ),
            const SizedBox(width: BpSpace.snug),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(job.request.isEmpty ? job.kind : job.request,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(
                          fontFamily: BpType.mono,
                          fontSize: BpType.label,
                          height: 1.35,
                          color: BpcadColors.ink)),
                  const SizedBox(height: 2),
                  Text(
                      // THE ENGINE'S LAST WORDS. Not a stage this app worked
                      // out from the clock - the whole point of the building
                      // screen's honesty rule, kept here too.
                      job.done
                          ? (job.ok
                              ? '$state · ${job.name} · ${job.elapsed}'
                              : '$state after ${job.elapsed}')
                          : job.note.isEmpty
                              ? '$state · ${job.elapsed}'
                              : '${job.note} · ${job.elapsed}',
                      style: TextStyle(
                          fontFamily: BpType.mono,
                          fontSize: BpType.micro,
                          color: job.done && !job.ok
                              ? BpPen.fail
                              : BpcadColors.inkDim,
                          fontFeatures: const [
                            FontFeature.tabularFigures()
                          ])),
                ],
              ),
            ),
            if (job.done && job.ok)
              const Padding(
                padding: EdgeInsets.only(left: BpSpace.snug, top: 2),
                child: TypeMark('›', colour: BpcadColors.inkFaint),
              ),
          ],
        ),
      ),
    );
  }

  /// THE ONE SETTING WITHOUT WHICH THE APP DOES NOTHING.
  ///
  /// It was a compile-time constant of localhost:8765, which works over a USB
  /// cable with `adb reverse` and nowhere else on earth. bpcad runs on a
  /// computer and the phone is a window onto it, so the address of that
  /// computer is not a preference - it is the product's one piece of wiring.
  Widget _serverPanel() => GlassSurface(
        depth: GlassDepth.card,
        padding: const EdgeInsets.all(BpSpace.base),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text('the computer running bpcad',
                style: TextStyle(
                    fontFamily: BpType.mono,
                    fontSize: BpType.micro,
                    color: BpcadColors.inkDim)),
            const SizedBox(height: BpSpace.snug),
            GlassSurface(
              depth: GlassDepth.well,
              blur: false,
              padding: const EdgeInsets.symmetric(horizontal: BpSpace.base),
              child: TextField(
                controller: _server,
                autocorrect: false,
                keyboardType: TextInputType.url,
                textInputAction: TextInputAction.done,
                onSubmitted: (_) => _test(),
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
                  hintText: '192.168.0.14:8765',
                  hintStyle: TextStyle(
                      fontFamily: BpType.mono,
                      fontSize: BpType.body,
                      color: BpcadColors.inkFaint),
                ),
              ),
            ),
            const SizedBox(height: BpSpace.snug),
            Row(children: [
              Expanded(
                child: SizedBox(
                  height: BpMetric.tap,
                  child: OutlinedButton(
                    onPressed: _test,
                    style: OutlinedButton.styleFrom(
                      side: const BorderSide(color: BpcadColors.edge),
                      shape: RoundedRectangleBorder(
                          borderRadius:
                              BorderRadius.circular(BpRadius.control)),
                    ),
                    child: const Text('Test',
                        style: TextStyle(
                            fontFamily: BpType.mono,
                            fontSize: BpType.label,
                            color: BpcadColors.ink)),
                  ),
                ),
              ),
              const SizedBox(width: BpSpace.snug),
              Expanded(
                child: SizedBox(
                  height: BpMetric.tap,
                  // ONLY AFTER IT ANSWERED. Saving an address that does not
                  // work leaves an unusable app and a settings screen that
                  // says everything is fine.
                  child: FilledButton(
                    onPressed: _tested && _reachable ? _save : null,
                    child: const Text('Use this',
                        style: TextStyle(
                            fontFamily: BpType.mono, fontSize: BpType.label)),
                  ),
                ),
              ),
            ]),
            if (_testing != null) ...[
              const SizedBox(height: BpSpace.snug),
              Text(_testing!,
                  style: TextStyle(
                      fontFamily: BpType.mono,
                      fontSize: BpType.micro,
                      height: 1.5,
                      color: !_tested
                          ? BpcadColors.inkDim
                          : _reachable
                              ? BpPen.pass
                              : BpPen.fail)),
            ],
            const SizedBox(height: BpSpace.snug),
            const Text(
                'Over a USB cable with `adb reverse tcp:8765 tcp:8765`, '
                'localhost is the computer. On wifi, use its address and the '
                'port `bpcad web` opened.',
                style: TextStyle(
                    fontFamily: BpType.prose,
                    fontSize: BpType.micro,
                    height: 1.55,
                    color: BpcadColors.inkFaint)),
          ],
        ),
      );

  Widget _statePanel(Health? health) => GlassSurface(
        depth: GlassDepth.card,
        padding: const EdgeInsets.all(BpSpace.base),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            _row('now using', widget.api.baseUrl),
            _row('model',
                health == null
                    ? 'not answering'
                    : health.modelAvailable ? health.tier : 'none'),
            if (health != null && health.promptSeconds > 0)
              _row('a part takes',
                  health.promptSeconds > 90
                      ? '~${(health.promptSeconds / 60).round()} min'
                      : '~${health.promptSeconds} s'),
            if (health?.headline.isNotEmpty == true) ...[
              const SizedBox(height: BpSpace.snug),
              // THE SERVER'S OWN SENTENCE, not a paraphrase. It measured how
              // long a part takes on that hardware and the phone did not.
              Text(health!.headline,
                  style: const TextStyle(
                      fontFamily: BpType.prose,
                      fontSize: BpType.micro,
                      height: 1.55,
                      color: BpCore.phosphor)),
            ],
          ],
        ),
      );

  /// WHAT IT HOLDS. Counted from the library the server serves, not stored
  /// here - the two would drift, and the number that mattered would be the
  /// wrong one.
  ///
  /// A DRAFT IS COUNTED SEPARATELY AND ON PURPOSE. A run that failed hands
  /// off a spec with no geometry, and it is right that the library lists it -
  /// it is something you started. Folding it into "17 parts" would make the
  /// count a claim that seventeen things exist to print.
  Widget _libraryPanel() {
    final built = _parts.where((part) => part.built).length;
    final drafts = _parts.length - built;

    return GlassSurface(
      depth: GlassDepth.card,
      padding: const EdgeInsets.all(BpSpace.base),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text('what is on it',
              style: TextStyle(
                  fontFamily: BpType.mono,
                  fontSize: BpType.micro,
                  color: BpcadColors.inkDim)),
          const SizedBox(height: BpSpace.snug),
          if (_libraryProblem != null)
            Text(_libraryProblem!,
                style: const TextStyle(
                    fontFamily: BpType.prose,
                    fontSize: BpType.micro,
                    height: 1.55,
                    color: BpPen.fail))
          else ...[
            _row('parts built', '$built'),
            if (drafts > 0) _row('drafts', '$drafts, never built'),
            if (_parts.isEmpty)
              const Text('nothing made yet',
                  style: TextStyle(
                      fontFamily: BpType.mono,
                      fontSize: BpType.label,
                      color: BpcadColors.inkFaint)),
          ],
        ],
      ),
    );
  }

  /// WHAT IT CAN MAKE, named rather than counted.
  ///
  /// The templates were shown as "14 known", which tells you a number and
  /// nothing else. These are the shapes the engine has a real, parametric,
  /// verified path to - the difference between a request that lands on a
  /// template and one that has to be composed from primitives - so naming
  /// them is the most useful thing this screen can say about what to ask for.
  Widget _makesPanel(Health? health) {
    final templates = health?.templates ?? const <String>[];
    if (templates.isEmpty) return const SizedBox.shrink();

    return GlassSurface(
      depth: GlassDepth.card,
      padding: const EdgeInsets.all(BpSpace.base),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('what it can make · ${templates.length}',
              style: const TextStyle(
                  fontFamily: BpType.mono,
                  fontSize: BpType.micro,
                  color: BpcadColors.inkDim)),
          const SizedBox(height: BpSpace.snug),
          Wrap(
            spacing: 6,
            runSpacing: 6,
            children: [
              for (final name in templates)
                BpChip(
                  label: name.replaceAll('_', ' '),
                  // Straight into the composer with the template named. The
                  // sentence is the user's to write - this only says which
                  // shape they are starting from, which is a fact.
                  onTap: () => Navigator.of(context).push(MaterialPageRoute(
                    builder: (_) => ComposerScreen(
                      api: widget.api,
                      health: health,
                      remembered: widget.settings.material,
                      seed: 'A ${name.replaceAll('_', ' ')} ',
                    ),
                  )),
                ),
            ],
          ),
          const SizedBox(height: BpSpace.snug),
          const Text(
              'A request that lands on one of these gets a parametric solid '
              'with bounds the builder enforces. Anything else is composed '
              'from primitives, which works and is less certain.',
              style: TextStyle(
                  fontFamily: BpType.prose,
                  fontSize: BpType.micro,
                  height: 1.55,
                  color: BpcadColors.inkFaint)),
        ],
      ),
    );
  }

  /// WHICH MATERIAL A NEW PART IS BUILT IN, and it is not a preference.
  ///
  /// The running clearance of a moving joint comes from the material, per
  /// material, out of config. A hinge built in the wrong one binds or
  /// rattles - so this is a real setting with a real consequence, and it is
  /// remembered rather than asked on every part.
  Widget _materialPanel(Health? health) {
    final materials = health?.materials ?? const <String>[];
    if (materials.isEmpty) return const SizedBox.shrink();
    final chosen = widget.settings.material.isEmpty
        ? materials.first
        : widget.settings.material;

    return GlassSurface(
      depth: GlassDepth.card,
      padding: const EdgeInsets.all(BpSpace.base),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text('material for new parts',
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
                  selected: name == chosen,
                  onTap: () async {
                    await widget.settings.setMaterial(name);
                    if (mounted) setState(() {});
                  },
                ),
            ],
          ),
          const SizedBox(height: BpSpace.snug),
          const Text(
              'The joint clearance of a moving part comes from this, per '
              'material. It is not a colour preference.',
              style: TextStyle(
                  fontFamily: BpType.prose,
                  fontSize: BpType.micro,
                  height: 1.55,
                  color: BpcadColors.inkFaint)),
        ],
      ),
    );
  }

  Widget _effectsPanel() => GlassSurface(
        depth: GlassDepth.card,
        padding: const EdgeInsets.all(BpSpace.base),
        child: Row(children: [
          const Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('glass and ambient light',
                    style: TextStyle(
                        fontFamily: BpType.mono,
                        fontSize: BpType.label,
                        color: BpcadColors.ink)),
                SizedBox(height: 3),
                Text('Off is cheaper on an older phone. The design says a '
                    'low-end GPU should be able to refuse them.',
                    style: TextStyle(
                        fontFamily: BpType.prose,
                        fontSize: BpType.micro,
                        height: 1.5,
                        color: BpcadColors.inkFaint)),
              ],
            ),
          ),
          const SizedBox(width: BpSpace.base),
          // A SQUARE-CORNERED SWITCH, per the design's settings rows - 38 × 20
          // with hard corners, because it is data chrome.
          _Switch(
            on: widget.settings.effects,
            onChanged: (value) async {
              await widget.settings.setEffects(value);
              if (mounted) setState(() {});
            },
          ),
        ]),
      );

  /// The printer profile, READ ONLY, and it says why.
  Widget _profilePanel(Health? health) => GlassSurface(
        depth: GlassDepth.panel,
        padding: const EdgeInsets.all(BpSpace.base),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text('printer profile',
                style: TextStyle(
                    fontFamily: BpType.mono,
                    fontSize: BpType.micro,
                    color: BpcadColors.inkDim)),
            const SizedBox(height: BpSpace.snug),
            _row('printer', health?.printer ?? '—'),
            if (health?.bedMm != null)
              _row('bed',
                  '${health!.bedMm!.map((v) => v.toStringAsFixed(0)).join(' × ')} mm'),
            const SizedBox(height: BpSpace.snug),
            // WHY IT IS NOT EDITABLE HERE. Not an omission: these values are
            // the source every geometry decision is taken from, and config's
            // own rule is that an unmeasured value is UNSET and reading one
            // raises, because a wrong tolerance is worse than no tolerance. A
            // phone that could type a clearance would be manufacturing a
            // measurement, and the part built from it would be wrong with
            // nothing on screen to say so.
            const Text(
                'Set in config/default.toml on the computer. It is not '
                'editable here: the joint clearance in it is a measured '
                'value, and a number typed on a phone would be a measurement '
                'nobody took. The calibration print is what will write it.',
                style: TextStyle(
                    fontFamily: BpType.prose,
                    fontSize: BpType.micro,
                    height: 1.55,
                    color: BpcadColors.inkFaint)),
          ],
        ),
      );

  Widget _row(String key, String value) => Padding(
        padding: const EdgeInsets.only(bottom: BpSpace.snug),
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
}

/// 38 × 20, hard-cornered. The design's own switch: data chrome keeps the
/// squared radii, and Material's pill would be the only rounded control on
/// the screen.
class _Switch extends StatelessWidget {
  const _Switch({required this.on, required this.onChanged});

  final bool on;
  final ValueChanged<bool> onChanged;

  @override
  Widget build(BuildContext context) => InkWell(
        onTap: () => onChanged(!on),
        child: Container(
          width: 38,
          height: 20,
          padding: const EdgeInsets.all(2),
          decoration: BoxDecoration(
            border: Border.all(
                color: on ? BpCore.phosphor : BpcadColors.edge),
          ),
          child: Align(
            alignment: on ? Alignment.centerRight : Alignment.centerLeft,
            child: Container(
              width: 14,
              height: 14,
              color: on ? BpCore.phosphor : BpcadColors.inkFaint,
            ),
          ),
        ),
      );
}
