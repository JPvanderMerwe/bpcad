// A real 3D viewer: the part, on the phone's own GPU.
//
// WHY THIS REPLACES THE TURNTABLE STRIP.
//
// The turntable is 24 pictures rendered by the server. It reads as rotation
// and it was the right first move - the frames already existed and cost the
// phone nothing. But it is 24 fixed viewpoints: you cannot look under a part,
// you cannot get close to a hole to see whether it goes through, and every
// step is a network round trip. On a phone, deciding whether to print
// something means turning it over in your hand.
//
// So the part is fetched ONCE as GLB and drawn locally. GLB rather than the
// STL that already exists: STL is triangles and nothing else - no units, no
// orientation convention, no material - and every viewer guesses differently.
// glTF is what viewers actually take, and trimesh already writes it, so the
// server gained an endpoint rather than the project gaining a dependency.
//
// THE MESH IS THE PART, NOT A PICTURE OF IT. Which means this viewer must not
// smooth, decimate or re-orient anything: a viewer that quietly improves the
// geometry is a viewer that lies about what will come off the printer.

import 'package:flutter/material.dart';
import 'package:model_viewer_plus/model_viewer_plus.dart';

import 'api.dart';
import 'theme.dart';

class ViewerScreen extends StatelessWidget {
  const ViewerScreen({super.key, required this.api, required this.name});

  final BpcadApi api;
  final String name;

  @override
  Widget build(BuildContext context) {
    final source = api.glb(name).toString();
    return Scaffold(
      appBar: AppBar(
        title: Text(name),
        actions: const [
          Padding(
            padding: EdgeInsets.only(right: 14),
            child: Center(
              child: Text('drag · pinch',
                  style: TextStyle(fontSize: 11.5, color: BpcadColors.inkFaint)),
            ),
          ),
        ],
      ),
      body: ModelViewer(
        src: source,
        alt: name,
        // The same ground the server renders on and the same the app is
        // painted in, so the part does not sit in a box of a different
        // colour to everything around it.
        backgroundColor: BpcadColors.bed,
        cameraControls: true,
        // Orbit, but never below the bed: a part is looked at standing on a
        // plate, and letting the camera go under it is disorienting rather
        // than useful.
        minCameraOrbit: 'auto 0deg auto',
        maxCameraOrbit: 'auto 90deg auto',
        autoRotate: false,
        // No environment image and no shadow: this is a measuring
        // instrument, and a studio-lit render flatters geometry. Flat
        // shading over the plate colour is what the CPU rasteriser does and
        // what the height map is checked against.
        disableZoom: false,
        loading: Loading.eager,
      ),
    );
  }
}
