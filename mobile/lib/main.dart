// bpcad on a phone.
//
// FIRST SLICE, AND WHAT IT DELIBERATELY IS NOT. This connects to a running
// bpcad, says honestly whether it can see one, lists what has been made, and
// shows a part with the numbers measured off it. Generating is wired to the
// real endpoint with real progress. It is not yet the whole app: there is no
// refine, no upload, no variant screen.
//
// The house style is the web app's, on purpose - same ground, same two
// accents, same rule that the part is the biggest thing on screen and the
// dimensions are the best-treated text. A phone app that looked like a
// different product would be a second product.

import 'package:flutter/material.dart';

import 'api.dart';
import 'theme.dart';
import 'part_screen.dart';

void main() => runApp(const BpcadApp());

/// Over a USB cable with `adb reverse tcp:8765 tcp:8765`, the phone's own
/// localhost is the laptop. That is the testing path and it exposes nothing to
/// the network. A hosted address is a decision not yet taken, so this is a
/// constant in one place rather than a assumption spread through the app.
const String kDefaultServer = 'http://localhost:8765';

class BpcadApp extends StatelessWidget {
  const BpcadApp({super.key});

  @override
  Widget build(BuildContext context) => MaterialApp(
        title: 'bpcad',
        debugShowCheckedModeBanner: false,
        theme: bpcadTheme(),
        home: const LibraryScreen(),
      );
}

class LibraryScreen extends StatefulWidget {
  const LibraryScreen({super.key});

  @override
  State<LibraryScreen> createState() => _LibraryScreenState();
}

class _LibraryScreenState extends State<LibraryScreen> {
  final BpcadApi _api = BpcadApi(kDefaultServer);
  final TextEditingController _prompt = TextEditingController();

  Health? _health;
  List<PartSummary> _parts = const [];
  String? _problem;
  bool _loading = true;

  /// Filtering happens on the phone, not the server. The whole library is a
  /// few kilobytes of JSON and the phone already has it, so typing narrows
  /// instantly and keeps working when the cable comes out - a search box that
  /// waits on a round trip per keystroke feels broken even when it is not.
  String _query = '';

  List<PartSummary> get _visible =>
      _parts.where((p) => p.matches(_query)).toList();

  @override
  void initState() {
    super.initState();
    _refresh();
  }

  @override
  void dispose() {
    _prompt.dispose();
    super.dispose();
  }

  Future<void> _refresh() async {
    setState(() {
      _loading = true;
      _problem = null;
    });
    try {
      final health = await _api.health();
      final parts = await _api.parts();
      if (!mounted) return;
      setState(() {
        _health = health;
        _parts = parts;
        _loading = false;
      });
    } catch (error) {
      if (!mounted) return;
      // A phone that cannot see the laptop is the ordinary case, not a crash.
      setState(() {
        _problem = error is BpcadUnreachable ? error.why : error.toString();
        _loading = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: RefreshIndicator(
          onRefresh: _refresh,
          color: BpcadColors.live,
          backgroundColor: BpcadColors.bedDeep,
          child: CustomScrollView(
            slivers: [
              SliverToBoxAdapter(child: _header()),
              if (_problem != null)
                SliverToBoxAdapter(child: _cannotReach(_problem!)),
              if (_loading)
                const SliverToBoxAdapter(
                  child: Padding(
                    padding: EdgeInsets.all(32),
                    child: Center(
                      child: CircularProgressIndicator(
                          color: BpcadColors.live, strokeWidth: 2),
                    ),
                  ),
                ),
              if (!_loading && _problem == null) ...[
                SliverToBoxAdapter(child: _askBox()),
                SliverToBoxAdapter(child: _searchBox()),
                _partGrid(),
              ],
            ],
          ),
        ),
      ),
    );
  }

  Widget _header() => Padding(
        padding: const EdgeInsets.fromLTRB(16, 14, 16, 6),
        child: Row(
          children: [
            Container(
              width: 22,
              height: 22,
              decoration: BoxDecoration(
                borderRadius: BorderRadius.circular(6),
                gradient: const LinearGradient(
                  begin: Alignment.topLeft,
                  end: Alignment.bottomRight,
                  colors: [BpcadColors.live, Color(0xFF2C7F8C)],
                ),
              ),
            ),
            const SizedBox(width: 9),
            const Text('bpcad',
                style: TextStyle(
                    fontSize: 17,
                    fontWeight: FontWeight.w600,
                    letterSpacing: -0.2)),
            const Spacer(),
            if (_health != null) _machineLamp(_health!),
          ],
        ),
      );

  Widget _machineLamp(Health health) => Row(
        children: [
          Container(
            width: 7,
            height: 7,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              color: health.modelAvailable
                  ? BpcadColors.act
                  : BpcadColors.fail,
            ),
          ),
          const SizedBox(width: 7),
          Text(
            health.modelAvailable ? 'model ready' : 'no model',
            style: const TextStyle(fontSize: 12, color: BpcadColors.inkDim),
          ),
        ],
      );

  /// The honest empty state. It names the address it tried, because the fix is
  /// almost always the cable or the port and the user cannot guess which.
  Widget _cannotReach(String why) => Padding(
        padding: const EdgeInsets.all(16),
        child: Container(
          padding: const EdgeInsets.all(16),
          decoration: BoxDecoration(
            color: BpcadColors.bedDeep,
            border: Border.all(color: BpcadColors.edge),
            borderRadius: BorderRadius.circular(14),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text('No bpcad to talk to',
                  style: TextStyle(
                      fontSize: 17, fontWeight: FontWeight.w600)),
              const SizedBox(height: 8),
              Text(
                'Tried $kDefaultServer and got: $why',
                style: const TextStyle(
                    fontSize: 13, color: BpcadColors.inkDim, height: 1.45),
              ),
              const SizedBox(height: 10),
              const Text(
                'The geometry engine runs on a computer, not on the phone. '
                'Over USB, `adb reverse tcp:8765 tcp:8765` points this app at '
                'it; on wifi, use the computer’s address with '
                '`bpcad web --lan`.',
                style: TextStyle(
                    fontSize: 12.5, color: BpcadColors.inkFaint, height: 1.5),
              ),
              const SizedBox(height: 14),
              FilledButton(onPressed: _refresh, child: const Text('Try again')),
            ],
          ),
        ),
      );

  Widget _askBox() => Padding(
        padding: const EdgeInsets.fromLTRB(16, 8, 16, 4),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Expanded(
                  child: TextField(
                    controller: _prompt,
                    minLines: 2,
                    maxLines: 4,
                    style: const TextStyle(fontSize: 15),
                    decoration: const InputDecoration(
                      hintText: 'Bracket to hold an 8 mm rod to a wall',
                    ),
                  ),
                ),
                const SizedBox(width: 10),
                // The ONE amber thing on the screen. Amber is the commit
                // action in this product and spending it anywhere else is how
                // an accent stops meaning anything.
                FilledButton(
                  onPressed: _generate,
                  child: const Text('Generate'),
                ),
              ],
            ),
            if (_health != null && _health!.headline.isNotEmpty) ...[
              const SizedBox(height: 10),
              Text(_health!.headline,
                  style: const TextStyle(
                      fontSize: 12.5, color: BpcadColors.act, height: 1.45)),
            ],
          ],
        ),
      );

  Widget _searchBox() {
    final shown = _visible.length;
    final total = _parts.length;
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 18, 16, 8),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          TextField(
            onChanged: (value) => setState(() => _query = value),
            style: const TextStyle(fontSize: 15),
            decoration: InputDecoration(
              hintText: 'Search parts, prompts, materials',
              prefixIcon: const Icon(Icons.search,
                  size: 20, color: BpcadColors.inkFaint),
              suffixIcon: _query.isEmpty
                  ? null
                  : IconButton(
                      icon: const Icon(Icons.close, size: 18),
                      color: BpcadColors.inkFaint,
                      onPressed: () => setState(() => _query = ''),
                    ),
            ),
          ),
          const SizedBox(height: 10),
          Text(
            _query.isEmpty
                ? 'Your parts · $total'
                : '$shown of $total match “$_query”',
            style: const TextStyle(
                fontSize: 13, fontWeight: FontWeight.w600),
          ),
        ],
      ),
    );
  }

  Widget _partGrid() {
    final visible = _visible;
    if (visible.isEmpty) {
      return SliverToBoxAdapter(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 4, 16, 24),
          child: Text(
            _parts.isEmpty
                ? 'Nothing made yet.'
                : 'Nothing matches “$_query”.',
            style: const TextStyle(
                color: BpcadColors.inkFaint, fontSize: 13),
          ),
        ),
      );
    }
    return SliverPadding(
      padding: const EdgeInsets.fromLTRB(16, 0, 16, 28),
      sliver: SliverGrid.builder(
        gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
          crossAxisCount: 2,
          mainAxisSpacing: 10,
          crossAxisSpacing: 10,
          childAspectRatio: 0.82,
        ),
        itemCount: visible.length,
        itemBuilder: (context, index) => _partCard(visible[index]),
      ),
    );
  }

  Widget _partCard(PartSummary part) {
    final renderVersion = _health?.renderVersion ?? 1;
    return InkWell(
      borderRadius: BorderRadius.circular(12),
      onTap: () => Navigator.of(context).push(MaterialPageRoute(
        builder: (_) => PartScreen(
            api: _api, name: part.name, renderVersion: renderVersion),
      )),
      child: Container(
        decoration: BoxDecoration(
          color: BpcadColors.bedDeep,
          border: Border.all(color: BpcadColors.edge),
          borderRadius: BorderRadius.circular(12),
        ),
        padding: const EdgeInsets.all(7),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Expanded(
              child: ClipRRect(
                borderRadius: BorderRadius.circular(7),
                child: Container(
                  color: BpcadColors.bed,
                  width: double.infinity,
                  // A DRAFT HAS NO MESH, so it has no render, and asking for
                  // one is a guaranteed 404 that shows as a broken card. The
                  // library payload says `built` and the app used to ignore
                  // it.
                  child: !part.built
                      ? const Center(
                          child: Padding(
                            padding: EdgeInsets.all(8),
                            child: Text(
                              'draft\nnot built',
                              textAlign: TextAlign.center,
                              style: TextStyle(
                                  fontSize: 11.5,
                                  height: 1.4,
                                  color: BpcadColors.inkFaint),
                            ),
                          ),
                        )
                      : Image.network(
                    _api
                        .frame(part.name, 3,
                            width: 420, renderVersion: renderVersion)
                        .toString(),
                    fit: BoxFit.contain,
                    // A render is made on demand and a big mesh takes
                    // seconds. Saying nothing looks like a broken image.
                    loadingBuilder: (context, child, progress) =>
                        progress == null
                            ? child
                            : const Center(
                                child: SizedBox(
                                  width: 16,
                                  height: 16,
                                  child: CircularProgressIndicator(
                                      strokeWidth: 1.5,
                                      color: BpcadColors.inkFaint),
                                ),
                              ),
                          errorBuilder: (context, error, stack) => const Center(
                            child: Text('no render',
                                style: TextStyle(
                                    fontSize: 11,
                                    color: BpcadColors.inkFaint)),
                          ),
                        ),
                ),
              ),
            ),
            const SizedBox(height: 6),
            Text(part.name,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(fontSize: 12.5)),
            const SizedBox(height: 2),
            // Dimensions are mono and tabular, as everywhere else in this
            // product: a 1 must not be mistakable for a 7 at a glance.
            Text(part.envelope, style: BpcadText.dimension),
          ],
        ),
      ),
    );
  }

  Future<void> _generate() async {
    final request = _prompt.text.trim();
    if (request.isEmpty) return;
    final messenger = ScaffoldMessenger.of(context);
    try {
      final job = await _api.generate(request);
      if (!mounted) return;
      await Navigator.of(context).push(MaterialPageRoute(
        builder: (_) => GeneratingScreen(api: _api, jobId: job, request: request),
      ));
      if (mounted) _refresh();
    } catch (error) {
      messenger.showSnackBar(SnackBar(content: Text('$error')));
    }
  }
}

/// Progress for a run that takes minutes. Brief 11.7's rule, on a phone:
/// state the wait plainly, because somebody who is not told concludes it hung.
class GeneratingScreen extends StatefulWidget {
  const GeneratingScreen(
      {super.key, required this.api, required this.jobId, required this.request});

  final BpcadApi api;
  final String jobId;
  final String request;

  @override
  State<GeneratingScreen> createState() => _GeneratingScreenState();
}

class _GeneratingScreenState extends State<GeneratingScreen> {
  final List<String> _log = [];
  bool _done = false;
  late final Stopwatch _clock = Stopwatch()..start();

  @override
  void initState() {
    super.initState();
    widget.api.events(widget.jobId).listen(
      (event) {
        if (!mounted) return;
        setState(() {
          if (event.text.isNotEmpty) _log.insert(0, event.text);
          if (event.done) _done = true;
        });
      },
      onError: (error) {
        if (!mounted) return;
        setState(() => _log.insert(0, 'lost the connection: $error'));
      },
      onDone: () {
        if (mounted) setState(() => _done = true);
      },
    );
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: Text(_done ? 'Done' : 'Working')),
        body: SafeArea(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(widget.request,
                    style: const TextStyle(fontSize: 15, height: 1.4)),
                const SizedBox(height: 14),
                if (!_done)
                  const LinearProgressIndicator(
                      color: BpcadColors.live,
                      backgroundColor: BpcadColors.edge,
                      minHeight: 2),
                const SizedBox(height: 14),
                Text(
                  _done
                      ? 'Finished in ${_clock.elapsed.inSeconds}s'
                      : 'A prompt takes minutes on a CPU. '
                          '${_clock.elapsed.inSeconds}s so far.',
                  style: const TextStyle(
                      fontSize: 13, color: BpcadColors.inkDim),
                ),
                const SizedBox(height: 16),
                Expanded(
                  child: ListView.builder(
                    itemCount: _log.length,
                    itemBuilder: (context, index) => Padding(
                      padding: const EdgeInsets.symmetric(vertical: 3),
                      child: Text(_log[index],
                          style: const TextStyle(
                              fontFamily: 'monospace',
                              fontSize: 12,
                              color: BpcadColors.inkDim)),
                    ),
                  ),
                ),
                if (_done)
                  SizedBox(
                    width: double.infinity,
                    child: FilledButton(
                      onPressed: () => Navigator.of(context).pop(),
                      child: const Text('Back to the library'),
                    ),
                  ),
              ],
            ),
          ),
        ),
      );
}
