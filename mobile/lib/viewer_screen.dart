// The 3D viewer: bpcad's own page, in a WebView, on the phone's own GPU.
//
// WHY A PLAIN WEBVIEW AND NOT A 3D PACKAGE.
//
// The first attempt used model_viewer_plus, which on mobile starts its own
// loopback HTTP server on an ephemeral port inside the app, proxies the mesh
// through it, points a WebView at that, and fetches model-viewer's JavaScript
// from a CDN. On the device the mesh arrived - the server logged the GLB
// request and served it - and the page drew nothing, with no error in logcat
// and no exception in Dart. Three moving parts nobody controls and a network
// dependency, to show a file the server was already holding.
//
// So the page is bpcad's: /static/viewer.html, with model-viewer vendored
// beside it. That removes the proxy, the ephemeral port and the CDN, and the
// web client loads the identical page - which is the only way two clients
// show a part the same way rather than nearly the same way.
//
// The mesh is drawn by the phone's GPU either way. What changed is who serves
// the page around it.

import 'package:flutter/material.dart';
import 'package:webview_flutter/webview_flutter.dart';

import 'api.dart';
import 'theme.dart';
import 'tokens.dart';

class ViewerScreen extends StatefulWidget {
  const ViewerScreen({super.key, required this.api, required this.name});

  final BpcadApi api;
  final String name;

  @override
  State<ViewerScreen> createState() => _ViewerScreenState();
}

class _ViewerScreenState extends State<ViewerScreen> {
  late final WebViewController _controller;
  String? _problem;
  bool _ready = false;

  @override
  void initState() {
    super.initState();
    // No inherited widgets touched here - that is what threw on the part
    // screen. A WebViewController needs nothing from the context.
    _controller = WebViewController()
      ..setJavaScriptMode(JavaScriptMode.unrestricted)
      // The page's own ground, not the app's. This is only visible for the
      // frame between the WebView being attached and its first paint, so it
      // has to match what the page paints or that frame is a seam. The
      // default is white, which is the flash every WebView template has.
      ..setBackgroundColor(BpCore.caseColor)
      ..setNavigationDelegate(NavigationDelegate(
        onPageFinished: (_) {
          if (mounted) setState(() => _ready = true);
        },
        onWebResourceError: (error) {
          // The ordinary failure is the cable being out, and it has to say so
          // rather than leave a dark rectangle - which is exactly how the
          // broken viewer looked, and why it took a server log to diagnose.
          //
          // MAIN FRAME ONLY. This fires for every subresource as well, so a
          // missing favicon would otherwise replace a working 3D view with an
          // error page. `isForMainFrame` is null on platforms that do not
          // report it, and a null there is treated as the main frame because
          // the alternative is swallowing the real failure.
          if (!mounted) return;
          if (error.isForMainFrame == false) return;
          setState(() => _problem = error.description);
        },
        // Nothing in this page navigates. Anything trying to is not ours.
        onNavigationRequest: (request) =>
            request.url.startsWith(widget.api.baseUrl)
                ? NavigationDecision.navigate
                : NavigationDecision.prevent,
      ))
      ..loadRequest(widget.api.viewer(widget.name));
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text(widget.name),
        actions: [
          if (_ready && _problem == null)
            const Padding(
              padding: EdgeInsets.only(right: 14),
              child: Center(
                child: Text('drag · pinch',
                    style: TextStyle(
                        fontSize: 11.5, color: BpcadColors.inkFaint)),
              ),
            ),
        ],
      ),
      body: _problem != null ? _cannotLoad(_problem!) : Stack(
        children: [
          WebViewWidget(controller: _controller),
          if (!_ready)
            const Center(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  SizedBox(
                    width: 18,
                    height: 18,
                    child: CircularProgressIndicator(
                        strokeWidth: 1.5, color: BpcadColors.inkFaint),
                  ),
                  SizedBox(height: 12),
                  Text('opening the viewer',
                      style: TextStyle(
                          fontSize: 12.5, color: BpcadColors.inkFaint)),
                ],
              ),
            ),
        ],
      ),
    );
  }

  Widget _cannotLoad(String why) => Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text('Could not open the 3D view',
                style: TextStyle(fontSize: 17, fontWeight: FontWeight.w600)),
            const SizedBox(height: 10),
            Text(why,
                style: const TextStyle(
                    fontSize: 13, color: BpcadColors.inkDim, height: 1.45)),
            const SizedBox(height: 12),
            const Text(
              'The mesh and the viewer both come from the computer running '
              'bpcad. The turntable on the previous screen works from cached '
              'images, so it is worth going back to check whether this is the '
              'connection or the part.',
              style: TextStyle(
                  fontSize: 12.5, color: BpcadColors.inkFaint, height: 1.5),
            ),
          ],
        ),
      );
}
