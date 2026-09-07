// One part: the render, and the numbers measured off it.
//
// THE PART IS THE BIGGEST THING ON THE SCREEN and the dimensions are the
// best-treated text. That ordering is the whole product on a phone - somebody
// is deciding whether to print this, and what they need is the shape and the
// figures, not chrome.
//
// The turntable is a strip of server-rendered frames rather than a 3D view.
// A real 3D viewport on a phone means shipping the mesh to the phone and a
// GPU renderer with it; the frames are already rendered, already cached
// immutably by the server, and dragging through them reads as rotation.

import 'package:flutter/material.dart';

import 'api.dart';
import 'theme.dart';
import 'viewer_screen.dart';

class PartScreen extends StatefulWidget {
  const PartScreen({
    super.key,
    required this.api,
    required this.name,
    required this.renderVersion,
  });

  final BpcadApi api;
  final String name;
  final int renderVersion;

  @override
  State<PartScreen> createState() => _PartScreenState();
}

class _PartScreenState extends State<PartScreen> {
  static const int _steps = 24;

  int _step = 3;
  double _dragFrom = 0;
  int _stepFrom = 3;

  @override
  void initState() {
    super.initState();
    // Warm the frames either side of the first one, so a drag does not stall
    // on a render the server has not been asked for yet.
    for (final step in [2, 4, 5, 1]) {
      precacheImage(
        NetworkImage(widget.api
            .frame(widget.name, step,
                width: 760, renderVersion: widget.renderVersion)
            .toString()),
        context,
      ).ignore();
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text(widget.name),
        actions: [
          // The turntable is 24 fixed viewpoints; this is the part itself.
          IconButton(
            tooltip: 'Open the 3D viewer',
            icon: const Icon(Icons.threed_rotation),
            onPressed: () => Navigator.of(context).push(MaterialPageRoute(
              builder: (_) => ViewerScreen(api: widget.api, name: widget.name),
            )),
          ),
        ],
      ),
      body: SafeArea(
        child: Column(
          children: [
            Expanded(
              child: GestureDetector(
                onHorizontalDragStart: (details) {
                  _dragFrom = details.localPosition.dx;
                  _stepFrom = _step;
                },
                onHorizontalDragUpdate: (details) {
                  final width = MediaQuery.of(context).size.width;
                  final perStep = (width / _steps).clamp(6.0, 40.0);
                  final moved =
                      ((details.localPosition.dx - _dragFrom) / perStep).round();
                  setState(() {
                    _step = (_stepFrom - moved) % _steps;
                    if (_step < 0) _step += _steps;
                  });
                },
                child: Container(
                  width: double.infinity,
                  color: BpcadColors.bed,
                  child: Image.network(
                    widget.api
                        .frame(widget.name, _step,
                            width: 760, renderVersion: widget.renderVersion)
                        .toString(),
                    fit: BoxFit.contain,
                    gaplessPlayback: true,
                    loadingBuilder: (context, child, progress) =>
                        progress == null
                            ? child
                            : Center(
                                child: Column(
                                  mainAxisAlignment: MainAxisAlignment.center,
                                  children: const [
                                    SizedBox(
                                      width: 18,
                                      height: 18,
                                      child: CircularProgressIndicator(
                                          strokeWidth: 1.5,
                                          color: BpcadColors.inkFaint),
                                    ),
                                    SizedBox(height: 10),
                                    Text(
                                      'Rendering — the first view of a big '
                                      'mesh takes a few seconds',
                                      textAlign: TextAlign.center,
                                      style: TextStyle(
                                          fontSize: 12,
                                          color: BpcadColors.inkFaint),
                                    ),
                                  ],
                                ),
                              ),
                    errorBuilder: (context, error, stack) => const Center(
                      child: Text('Could not render this part',
                          style: TextStyle(
                              fontSize: 13, color: BpcadColors.fail)),
                    ),
                  ),
                ),
              ),
            ),
            const Padding(
              padding: EdgeInsets.symmetric(vertical: 6),
              child: Text('drag to turn it',
                  style:
                      TextStyle(fontSize: 11, color: BpcadColors.inkFaint)),
            ),
            _facts(),
          ],
        ),
      ),
    );
  }

  /// The numbers, from the server's own measurements. Nothing here is computed
  /// on the phone: the phone has no mesh and no business deriving dimensions.
  Widget _facts() => FutureBuilder<List<PartSummary>>(
        future: widget.api.parts(),
        builder: (context, snapshot) {
          if (!snapshot.hasData) return const SizedBox(height: 96);
          final part = snapshot.data!
              .where((p) => p.name == widget.name)
              .cast<PartSummary?>()
              .firstWhere((p) => true, orElse: () => null);
          if (part == null) return const SizedBox(height: 96);
          final size = part.sizeMm;
          return Container(
            width: double.infinity,
            padding: const EdgeInsets.all(16),
            decoration: const BoxDecoration(
              color: BpcadColors.bedDeep,
              border: Border(top: BorderSide(color: BpcadColors.edge)),
            ),
            child: Row(
              children: [
                if (size != null && size.length == 3) ...[
                  _fact('Width', '${size[0].toStringAsFixed(1)} mm'),
                  _fact('Depth', '${size[1].toStringAsFixed(1)} mm'),
                  _fact('Height', '${size[2].toStringAsFixed(1)} mm'),
                ],
                if (part.volumeCm3 != null)
                  _fact('Volume',
                      '${part.volumeCm3!.toStringAsFixed(1)} cm³'),
              ],
            ),
          );
        },
      );

  Widget _fact(String label, String value) => Expanded(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(label,
                style: const TextStyle(
                    fontSize: 10.5, color: BpcadColors.inkFaint)),
            const SizedBox(height: 2),
            Text(value, style: BpcadText.fact),
          ],
        ),
      );
}
