"""
Raster to polygon outlines: blur, marching squares, Douglas-Peucker simplify.

Ported from reference/trace_logo.py. The algorithm and every default is that
file's, unchanged - upsample 10, blur 1.1 x upsample, iso level 0.55 on the
normalised luminance, simplify tolerance 0.055 x upsample. What is generalised
is the plumbing: it takes any image, returns objects instead of writing a fixed
JSON file, and the normalisation step is separable so pixel-space polygons are
available too.

WHY THE UPSAMPLE AND THE BLUR
-----------------------------
The upsample buys sub-pixel contour placement: marching squares interpolates
between samples, so a 10x grid puts an edge to a tenth of a source pixel. The
blur kills the fabric weave, which is high-frequency, without moving the edge
of a large shape. Both numbers came out of tracing a real wordmark off a woven
fabric crop and are left exactly as they were.

The tracing of the rain loop wordmark is also what showed the mark is a WAVE
over two straight bars, not three equal bars - worth knowing if it is ever
redrawn by hand.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageFilter
from skimage import measure

from bpcad.measure.segment import as_array

# reference/trace_logo.py, verbatim
UPSAMPLE = 10
BLUR_FACTOR = 1.1          # blur = BLUR_FACTOR * upsample
LEVEL = 0.55               # iso level on the normalised luminance
SIMPLIFY_FACTOR = 0.055    # tolerance = SIMPLIFY_FACTOR * upsample
MIN_CONTOUR_POINTS = 50
MIN_POLYGON_VERTICES = 6
MIN_AREA_FACTOR = 2.0      # min area = (MIN_AREA_FACTOR * upsample) ** 2


@dataclass
class Shape:
    """One traced outline. `pts` is (N, 2) in upsampled (row, col) pixels."""

    pts: np.ndarray
    hole: bool

    @property
    def area(self) -> float:
        p = self.pts
        return 0.5 * abs(
            np.dot(p[:, 1], np.roll(p[:, 0], 1)) - np.dot(p[:, 0], np.roll(p[:, 1], 1))
        )


@dataclass
class TraceResult:
    shapes: list[Shape]
    upsample: int

    @property
    def outers(self) -> list[Shape]:
        return [s for s in self.shapes if not s.hole]

    @property
    def holes(self) -> list[Shape]:
        return [s for s in self.shapes if s.hole]

    def normalised(self, source: str = "", ndigits: int = 5) -> dict:
        """
        The structure reference/rain_loop_keyring.py consumes.

        Coordinates are normalised so the total WIDTH is 1.0, x to the right,
        y up, origin at the bottom-left of the bounding box. That convention is
        the reference's and must not drift: the keyring template scales by
        width and would silently mis-size the wordmark if y ever became the
        normalising dimension.
        """
        if not self.shapes:
            raise ValueError("nothing was traced, so there is nothing to normalise")

        allp = np.vstack([s.pts for s in self.shapes])
        r0, r1 = allp[:, 0].min(), allp[:, 0].max()
        c0, c1 = allp[:, 1].min(), allp[:, 1].max()
        wn = c1 - c0

        out = []
        for s in self.shapes:
            pts = [
                [round(float((x - c0) / wn), ndigits), round(float((r1 - y) / wn), ndigits)]
                for y, x in s.pts
            ]
            if pts and pts[0] == pts[-1]:
                pts = pts[:-1]
            out.append({"hole": bool(s.hole), "pts": pts})

        return {
            "source": source,
            "aspect_h": round(float((r1 - r0) / wn), ndigits),
            "shapes": out,
        }

    def min_stroke(self, aspect_ratio: float = 2.5) -> float:
        """
        Thinnest bar in the traced mark, normalised to total width.

        A shape wider than `aspect_ratio` times its height is a bar, so its
        height is the stroke. This is what decides whether a wordmark has to be
        drawn oversize to clear the nozzle.
        """
        d = self.normalised()
        strokes = []
        for sh in d["shapes"]:
            if sh["hole"]:
                continue
            xs = [p[0] for p in sh["pts"]]
            ys = [p[1] for p in sh["pts"]]
            w, h = max(xs) - min(xs), max(ys) - min(ys)
            if h > 1e-6 and w / h > aspect_ratio:
                strokes.append(h)
        return min(strokes) if strokes else 0.10


def _inside(pt, poly) -> bool:
    """
    Ray-cast point-in-polygon, in (row, col) order.

    Ported unchanged from trace_logo.py rather than swapped for a library
    call - it decides hole parity, and a different edge-case convention would
    silently flip a counter from solid to hollow.
    """
    y, x = pt
    c = False
    for i in range(len(poly)):
        y1, x1 = poly[i]
        y2, x2 = poly[(i + 1) % len(poly)]
        if (x1 > x) != (x2 > x):
            if y1 + (x - x1) * (y2 - y1) / (x2 - x1) > y:
                c = not c
    return c


def trace(
    img,
    upsample: int = UPSAMPLE,
    blur: float | None = None,
    level: float = LEVEL,
    simplify: float | None = None,
    min_contour_points: int = MIN_CONTOUR_POINTS,
    min_vertices: int = MIN_POLYGON_VERTICES,
    min_area: float | None = None,
) -> TraceResult:
    """
    Trace an image to simplified polygon outlines with hole flags.

    `blur`, `simplify` and `min_area` default to the reference's values scaled
    off `upsample`, so changing the upsample keeps the rest in proportion.
    """
    if upsample < 1:
        raise ValueError("upsample must be at least 1, got %r" % upsample)
    blur = upsample * BLUR_FACTOR if blur is None else blur
    simplify = upsample * SIMPLIFY_FACTOR if simplify is None else simplify
    min_area = (MIN_AREA_FACTOR * upsample) ** 2 if min_area is None else min_area

    im = Image.fromarray(as_array(img))
    big = im.resize((im.width * upsample, im.height * upsample), Image.LANCZOS)
    if blur > 0:
        big = big.filter(ImageFilter.GaussianBlur(blur))

    lum = np.array(big).astype(float).sum(axis=2)
    lo, hi = np.percentile(lum, 2), np.percentile(lum, 98)
    if hi - lo < 1e-9:
        raise ValueError(
            "the image has no contrast between its 2nd and 98th percentiles, "
            "so there is no edge to trace"
        )
    norm = (lum - lo) / (hi - lo)

    polys: list[np.ndarray] = []
    for c in measure.find_contours(norm, level):
        if len(c) < min_contour_points:
            continue
        p = measure.approximate_polygon(c, tolerance=simplify)
        if len(p) < min_vertices:
            continue
        area = 0.5 * abs(
            np.dot(p[:, 1], np.roll(p[:, 0], 1)) - np.dot(p[:, 0], np.roll(p[:, 1], 1))
        )
        if area < min_area:
            continue
        polys.append(p)

    depth = [
        sum(1 for j, q in enumerate(polys) if j != i and _inside(p[0], q))
        for i, p in enumerate(polys)
    ]
    shapes = [Shape(pts=p, hole=bool(d % 2)) for p, d in zip(polys, depth)]
    return TraceResult(shapes=shapes, upsample=upsample)
