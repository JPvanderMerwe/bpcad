// The glass layer for the native client. Design handoff section 6, task C0.
//
// ONE PRIMITIVE, AND IT IS THE WHOLE POINT OF THIS FILE.
//
// Every raised surface in the app is a [GlassSurface] at a [GlassDepth]. This
// is the only place in `mobile/` that constructs a BackdropFilter, and that
// rule is the deliverable rather than the blur itself: five widgets each
// tuning their own blur and alpha is how the two clients drift apart a
// fortnight later, and the drift is invisible until somebody puts the phone
// next to the browser.
//
// WHAT STAYS FLAT. The app ground and its graticule, the 3D canvas, and INK.
// Text, numerals, dimension callouts, slider thumbs and check marks are full
// opacity and never translucent - glass is the surface UNDER a value, never
// the value. A numeric field on glass is a misread digit and a part that does
// not fit.
//
// DEPTH IS OVERLAP, NOT TASTE. A surface over content is denser than one over
// the ground, because contrast has to hold against the brightest thing the
// render behind it can produce. The alphas come from the token source and a
// caller cannot go below one.
//
// THE RASTER COST IS REAL. A BackdropFilter samples everything painted behind
// it, every frame. The handoff's own note is to cap it to the sheet, the tab
// bar and the floating pills if a scrolling list drops frames - so
// [GlassSurface] takes `blur: false` and falls back to the flat `bezel` fill,
// and a long list can turn it off per item without any call site inventing a
// different colour.

import 'dart:ui' show ImageFilter;

import 'package:flutter/material.dart';

import 'theme.dart';
import 'tokens.dart';

class GlassSurface extends StatelessWidget {
  const GlassSurface({
    super.key,
    required this.child,
    this.depth = GlassDepth.card,
    this.tint,
    this.padding,
    this.blur = true,
    this.borderRadius,
    this.border = true,
  });

  final Widget child;

  /// How far above the ground this surface sits. Not a shade - a depth.
  final GlassDepth depth;

  /// Tinted glass keeps its hue and gains alpha over the same blur: the amber
  /// clearance callout, the cyan pipeline banner, an active pill. Its border
  /// takes the tint rather than the neutral hairline.
  final GlassTint? tint;

  final EdgeInsetsGeometry? padding;

  /// Set false where the raster cost is not worth it - inside a long
  /// scrolling list, or under a canvas repainting every frame. The surface
  /// stays the right colour; it just stops sampling what is behind it.
  final bool blur;

  /// Override only for a shape the depth's radius cannot express. The default
  /// is the depth's own radius, which is the token the design specifies.
  final BorderRadius? borderRadius;

  final bool border;

  @override
  Widget build(BuildContext context) {
    final radius = borderRadius ?? BorderRadius.circular(depth.radius);

    // Reduced transparency and reduced motion are separate settings, and
    // Flutter surfaces neither as a "reduce transparency" flag. `highContrast`
    // is the closest honest signal: somebody who has asked for high contrast
    // is not well served by a translucent pane over a busy render.
    final flatten = !blur || MediaQuery.of(context).highContrast;

    final fill = tint?.fill ?? BpGlass.tint(depth.alpha);
    final line = tint?.border ?? BpGlass.hairline();

    final pane = DecoratedBox(
      decoration: BoxDecoration(
        color: flatten ? BpcadColors.bezel : fill,
        borderRadius: radius,
        border: border
            ? Border.all(
                color: flatten ? (tint?.color ?? BpcadColors.edge) : line,
                width: 1)
            : null,
        // The light catching the top edge of the pane. An inset line rather
        // than a gradient: a gradient reads as a button.
        boxShadow: flatten
            ? null
            : [
                BoxShadow(
                  color: BpGlass.highlight(),
                  offset: const Offset(0, 1),
                  blurRadius: 0,
                  spreadRadius: -1,
                ),
              ],
      ),
      child: padding == null
          ? child
          : Padding(padding: padding!, child: child),
    );

    if (flatten) return pane;

    // ClipRRect first: a BackdropFilter with no clip blurs the whole layer
    // it is in, which on a Stack means the entire screen goes soft and it is
    // not obvious from the code that it did.
    return ClipRRect(
      borderRadius: radius,
      child: BackdropFilter(
        filter: ImageFilter.blur(sigmaX: depth.blur, sigmaY: depth.blur),
        child: pane,
      ),
    );
  }
}

/// Ambient light BEHIND the glass.
///
/// Not decoration. A blur with nothing behind it to pick up renders as flat
/// grey, and every panel in the app becomes the same slab - which is what the
/// design's own note says, and it is the difference between the glass reading
/// as glass and reading as a translucent rectangle.
///
/// Two washes, phosphor and pen-ref at low alpha, from the token source. No
/// new hue enters the palette here. Wrap the VIEWPORT with this, not a panel:
/// the design's limits rule out full-screen curvature and stains, and putting
/// it on the app ground instead stained the whole web page amber before it was
/// moved onto the one container the floating chrome actually sits over.
class AmbientLight extends StatelessWidget {
  const AmbientLight({super.key, required this.child});

  final Widget child;

  @override
  Widget build(BuildContext context) {
    // Suppressed with the glass: somebody who asked for high contrast is not
    // served by two coloured washes under their text.
    if (MediaQuery.of(context).highContrast) {
      return ColoredBox(color: BpcadColors.bed, child: child);
    }

    return Stack(
      fit: StackFit.passthrough,
      children: [
        const ColoredBox(color: BpcadColors.bed),
        // Two layers because a BoxDecoration carries one gradient, and the
        // design specifies two washes from opposite corners. Painted in the
        // token's order so the amber sits over the cyan, as on the web.
        _Wash(
          colour: BpAmbient.wash0,
          alpha: BpAmbient.wash0Alpha,
          at: BpAmbient.wash0At,
          scale: BpAmbient.wash0Size,
          stop: BpAmbient.wash0Stop,
        ),
        _Wash(
          colour: BpAmbient.wash1,
          alpha: BpAmbient.wash1Alpha,
          at: BpAmbient.wash1At,
          scale: BpAmbient.wash1Size,
          stop: BpAmbient.wash1Stop,
        ),
        child,
      ],
    );
  }
}

class _Wash extends StatelessWidget {
  const _Wash({
    required this.colour,
    required this.alpha,
    required this.at,
    required this.scale,
    required this.stop,
  });

  final Color colour;
  final double alpha;
  final Alignment at;
  final Size scale;
  final double stop;

  @override
  Widget build(BuildContext context) {
    return DecoratedBox(
      decoration: BoxDecoration(
        gradient: RadialGradient(
          center: at,
          // Flutter measures a radial gradient's radius against the box's
          // SHORTEST side, so a plain radius cannot express CSS's separate
          // width and height percentages - the wash would come out circular
          // and the design's ellipse would be lost. _EllipseTransform scales
          // the two axes independently instead.
          radius: 0.5,
          transform: _EllipseTransform(scale, at),
          colors: [colour.withValues(alpha: alpha), colour.withValues(alpha: 0)],
          stops: [0.0, stop],
        ),
      ),
    );
  }
}

/// Scales a gradient's axes independently, so a CSS `120% 60%` ellipse can be
/// drawn as one.
///
/// Flutter measures a radial gradient's radius against the box's SHORTEST
/// side, so a single `radius` cannot express two percentages: the wash comes
/// out circular and the design's ellipse is lost. This scales the two axes
/// instead.
///
/// It scales about the wash's OWN centre, not the box's. Scaling about the box
/// centre slides the wash away from the corner `at` positioned it at, which
/// looks exactly like a wrong `at` value rather than a wrong transform - a
/// genuinely confusing way to lose an afternoon.
class _EllipseTransform extends GradientTransform {
  const _EllipseTransform(this.scale, this.at);

  /// Fractions of the box, as CSS writes them: width then height.
  final Size scale;

  /// Where the wash is centred, which is the point this scales about.
  final Alignment at;

  @override
  Matrix4? transform(Rect bounds, {TextDirection? textDirection}) {
    final shortest = bounds.shortestSide;
    if (shortest == 0 || bounds.isEmpty) return null;

    // Flutter will draw a circle of radius 0.5 * shortestSide. Convert each
    // axis to the fraction of the BOX the design asked for.
    final sx = bounds.width * scale.width / shortest;
    final sy = bounds.height * scale.height / shortest;

    final centre = at.withinRect(bounds);
    return Matrix4.identity()
      ..translate(centre.dx, centre.dy)
      ..scale(sx, sy)
      ..translate(-centre.dx, -centre.dy);
  }

  @override
  bool operator ==(Object other) =>
      other is _EllipseTransform && other.scale == scale && other.at == at;

  @override
  int get hashCode => Object.hash(scale, at);
}
