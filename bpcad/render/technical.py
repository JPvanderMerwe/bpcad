"""
The technical view: dark faces, drawn edges, a graticule and three axis lines.

This is the design handoff's viewport, rendered on the CPU. The handoff
describes it exactly (section 5, and prototype/part-viewport.js):

    each solid is a dark `bezel` face mesh with polygonOffset plus a
    LineSegments of its EdgesGeometry in pen-solid ... The graticule is a
    180-unit, 18-division grid in pen-dim at 50% with three phosphor axis
    lines and an origin sphere

WHY THIS EXISTS RATHER THAN A THREE.JS VIEWER
---------------------------------------------
The prototype gets that look from three.js in a browser. Reproducing it live
would mean vendoring three.js AND its GLTFLoader, and it would only fix the
one view a user reaches by tapping "3D" - while the TURNTABLE, which is what
both clients show by default and what brief 2.3 pins as native phase 1, would
carry on being a shaded grey render that looks like a different product.

So it is rendered here, where bpcad's own rasteriser already is, and both
clients get the design's viewport without a byte of new JavaScript.

HOW THE EDGES ARE FOUND, AND WHY IT IS NOT GEOMETRY WORK
--------------------------------------------------------
raster.zbuffer already returns a per-pixel FACE INDEX. An edge is where that
index changes between neighbouring pixels - so the silhouette and every
feature line are already in the buffer, for free, and no half-edge structure
or geometry pass is needed.

The catch is that a cylinder is hundreds of facets, and every boundary between
them is an index change. Drawing all of them would fill a curved surface with
lines. So a boundary only becomes an edge when the angle between the two
faces' normals exceeds EDGE_ANGLE_DEG - which is precisely what three.js's
`EdgesGeometry(geom, 20)` does with its 20-degree threshold, arrived at from
the other end.

The silhouette is always drawn: a boundary against the background has no
second normal to compare, and it is the one line that must never be missing.

THE GRATICULE IS DRAWN IN WORLD SPACE, NOT AS A BACKGROUND IMAGE.
It has to sit on z=0 under the part in the same projection, or it is wallpaper
behind a picture rather than a floor the part stands on - and at 315/26 the
difference is immediate.
"""

from __future__ import annotations

import math

import numpy as np

from bpcad.render.raster import (
    Bounds,
    fit_bounds,
    project_camera,
    view_basis,
    zbuffer,
)

# Design tokens, as floats. Kept here as the render layer's own copy of
# design/tokens.json because this module cannot import a stylesheet, and named
# rather than inlined so a retune is one edit.
#
# tests/test_technical.py checks these against design/tokens.json, so a token
# changed there and not here is a test failure rather than a viewport that
# quietly disagrees with the interface around it.
CASE = (0x0B / 255.0, 0x0F / 255.0, 0x0D / 255.0)
BEZEL = (0x15 / 255.0, 0x1B / 255.0, 0x18 / 255.0)
SOLID = (0xDC / 255.0, 0xE3 / 255.0, 0xDC / 255.0)
PEN_DIM = (0x4A / 255.0, 0x55 / 255.0, 0x4E / 255.0)
PHOSPHOR = (0xFF / 255.0, 0xB0 / 255.0, 0x00 / 255.0)

# three.js's own EdgesGeometry threshold. A boundary between two faces meeting
# at less than this is a facet of one curved surface, not an edge.
EDGE_ANGLE_DEG = 20.0

# The graticule, from the handoff: 180 units across, 18 divisions, at half
# opacity. It is a fixed size in millimetres on purpose - a grid that scaled
# with the part would give no sense of how big the part is, which is the one
# thing a floor grid is for.
GRID_SPAN_MM = 180.0
GRID_DIVISIONS = 18
GRID_ALPHA = 0.5

# Axis lines from the origin, and the origin marker.
AXIS_LEN_MM = 34.0
ORIGIN_R_MM = 1.6


def _line_pixels(
    p0: np.ndarray,
    p1: np.ndarray,
    right: np.ndarray,
    up: np.ndarray,
    bounds: Bounds,
    width: int,
    height: int,
) -> tuple[np.ndarray, np.ndarray]:
    """
    A world-space segment as integer pixel coordinates, clipped to the buffer.

    Sampled rather than Bresenham'd: one sample per half pixel of its own
    projected length, which is enough for a 1px line and is a handful of numpy
    operations instead of a Python loop per pixel. A 19-line graticule is 19
    of these, and it has to be cheap because it runs 24 times per part.
    """
    u0 = float(p0 @ right)
    v0 = float(p0 @ up)
    u1 = float(p1 @ right)
    v1 = float(p1 @ up)

    sx = (u0 - bounds.u0) / bounds.width * width
    sy = (v0 - bounds.v0) / bounds.height * height
    ex = (u1 - bounds.u0) / bounds.width * width
    ey = (v1 - bounds.v0) / bounds.height * height

    steps = int(max(abs(ex - sx), abs(ey - sy)) * 2) + 2
    xs = np.linspace(sx, ex, steps)
    ys = np.linspace(sy, ey, steps)

    cols = np.floor(xs).astype(int)
    rows = np.floor(ys).astype(int)
    inside = (cols >= 0) & (cols < width) & (rows >= 0) & (rows < height)
    return rows[inside], cols[inside]


def _graticule_segments() -> list[tuple[np.ndarray, np.ndarray, tuple, float]]:
    """
    Every line of the floor and the axes, as (start, end, colour, alpha).

    The floor is on z=0 because that is the build plate: bpcad's parts are
    modelled standing on it, so the grid meets the part exactly where the
    print would meet the bed.
    """
    out: list[tuple[np.ndarray, np.ndarray, tuple, float]] = []

    half = GRID_SPAN_MM / 2.0
    step = GRID_SPAN_MM / GRID_DIVISIONS
    for i in range(GRID_DIVISIONS + 1):
        at = -half + i * step
        out.append((np.array([at, -half, 0.0]), np.array([at, half, 0.0]),
                    PEN_DIM, GRID_ALPHA))
        out.append((np.array([-half, at, 0.0]), np.array([half, at, 0.0]),
                    PEN_DIM, GRID_ALPHA))

    # Three axis lines, full strength. They are the origin marker's arms and
    # the only amber in the scene, which is what makes the origin findable.
    for direction in (
        np.array([AXIS_LEN_MM, 0.0, 0.0]),
        np.array([0.0, AXIS_LEN_MM, 0.0]),
        np.array([0.0, 0.0, AXIS_LEN_MM]),
    ):
        out.append((np.zeros(3), direction, PHOSPHOR, 1.0))

    return out


def _origin_pixels(
    right: np.ndarray,
    up: np.ndarray,
    bounds: Bounds,
    width: int,
    height: int,
) -> tuple[np.ndarray, np.ndarray]:
    """
    The origin marker: a small filled square rather than the prototype's
    sphere.

    A sphere at 1.6mm is three pixels across at any sensible framing, and a
    three-pixel sphere is a square with worse edges. It is also the design's
    own rule for data marks - hard corners, no radius - so the square is the
    more faithful of the two.
    """
    scale = width / bounds.width
    radius = max(1, int(round(ORIGIN_R_MM * scale)))

    cx = int((0.0 - bounds.u0) / bounds.width * width)
    cy = int((0.0 - bounds.v0) / bounds.height * height)

    rows, cols = np.mgrid[
        cy - radius:cy + radius + 1, cx - radius:cx + radius + 1
    ]
    rows = rows.ravel()
    cols = cols.ravel()
    inside = (cols >= 0) & (cols < width) & (rows >= 0) & (rows < height)
    return rows[inside], cols[inside]


def _edge_mask(index: np.ndarray, face_normals: np.ndarray) -> np.ndarray:
    """
    Where to draw a line: the silhouette, plus every boundary between two
    faces that actually meet at an angle.

    Vectorised over the whole buffer. For each of the two neighbour directions
    it compares the face index against the pixel to its right and below; where
    they differ, it looks up both normals and keeps the boundary only if the
    angle between them is real. The comparison is done on the DOT PRODUCT
    rather than an arccos, because the threshold is a constant and a buffer of
    arccos calls is the slowest thing in the file.
    """
    height, width = index.shape
    edge = np.zeros((height, width), dtype=bool)
    limit = math.cos(math.radians(EDGE_ANGLE_DEG))

    for axis in (0, 1):
        a = index if axis == 1 else index
        # Neighbour pairs along one axis.
        if axis == 1:
            left, right_ = a[:, :-1], a[:, 1:]
        else:
            left, right_ = a[:-1, :], a[1:, :]

        differs = left != right_
        if not differs.any():
            continue

        # A boundary against the background is the silhouette, and it is
        # always an edge - there is no second face to take an angle against.
        silhouette = differs & ((left < 0) | (right_ < 0))

        both = differs & (left >= 0) & (right_ >= 0)
        keep = silhouette
        if both.any():
            n0 = face_normals[left[both]]
            n1 = face_normals[right_[both]]
            # Normalised on the way in by the caller; guard anyway, because a
            # degenerate facet with a zero normal would otherwise make every
            # boundary around it an edge.
            d0 = np.linalg.norm(n0, axis=1)
            d1 = np.linalg.norm(n1, axis=1)
            safe = (d0 > 1e-12) & (d1 > 1e-12)
            cosine = np.ones(len(n0))
            cosine[safe] = np.abs(
                np.einsum("ij,ij->i", n0[safe], n1[safe])
                / (d0[safe] * d1[safe])
            )
            angled = np.zeros_like(both)
            angled[both] = cosine < limit
            keep = keep | angled

        # Mark BOTH pixels of the pair. Marking one leaves a line that is a
        # pixel thin on one side of every shape and reads as a broken outline
        # where two edges meet.
        if axis == 1:
            edge[:, :-1] |= keep
            edge[:, 1:] |= keep
        else:
            edge[:-1, :] |= keep
            edge[1:, :] |= keep

    return edge


def render_technical(
    vertices: np.ndarray,
    faces: np.ndarray,
    face_normals: np.ndarray,
    width: int = 900,
    height: int = 700,
    elev_deg: float = 26.0,
    azim_deg: float = 315.0,
    alpha: bool = True,
    margin: float = 0.16,
    graticule: bool = True,
) -> np.ndarray:
    """
    Render a mesh in the design's technical style.

    Returns (H, W, 4) by default: the background is transparent so the part
    sits on whichever ground the client draws, exactly as the shaded renderer
    does. Pass alpha=False for an opaque `case` background.

    `margin` is wider than the shaded renderer's because the graticule extends
    past the part and a part filling the frame leaves no floor to stand on.
    """
    vertices = np.asarray(vertices, dtype=float)
    faces = np.asarray(faces)
    face_normals = np.asarray(face_normals, dtype=float)

    right, up, view = view_basis(elev_deg, azim_deg)
    tri_u, tri_v, tri_w = project_camera(vertices, faces, right, up, view)
    bounds = fit_bounds(tri_u, tri_v, width, height, margin=margin)
    depth, index = zbuffer(tri_u, tri_v, tri_w, width, height, bounds)

    img = np.empty((height, width, 3), dtype=float)
    img[:, :] = np.asarray(CASE, dtype=float)
    # Coverage, for the alpha channel. The graticule counts as covered: a
    # transparent grid over a client's own build plate would show two grids.
    covered = np.zeros((height, width), dtype=bool)

    if graticule:
        # UNDER THE PART, and only where the part is not. The floor is drawn
        # first and the faces then paint over it, which is what puts the part
        # ON the grid rather than behind it.
        for p0, p1, colour, line_alpha in _graticule_segments():
            rows, cols = _line_pixels(p0, p1, right, up, bounds, width, height)
            if len(rows) == 0:
                continue
            tint = np.asarray(colour, dtype=float) * line_alpha \
                + np.asarray(CASE, dtype=float) * (1.0 - line_alpha)
            img[rows, cols] = tint
            covered[rows, cols] = True

        rows, cols = _origin_pixels(right, up, bounds, width, height)
        if len(rows):
            img[rows, cols] = np.asarray(PHOSPHOR, dtype=float)
            covered[rows, cols] = True

    hit = index >= 0
    if hit.any():
        # FLAT `bezel` FACES, NO LAMBERT. The design's faces are
        # MeshBasicMaterial: unlit, one value. Shading them would make the
        # edges compete with a gradient, and the whole point of this view is
        # that the lines carry the form.
        img[hit] = np.asarray(BEZEL, dtype=float)
        covered |= hit

        edges = _edge_mask(index, face_normals)
        # Only where something was actually drawn. An edge mask spills one
        # pixel outside the silhouette by design - see _edge_mask - and left
        # unclipped it would draw a halo on the background.
        edges &= hit | np.roll(hit, 1, axis=0) | np.roll(hit, -1, axis=0) \
            | np.roll(hit, 1, axis=1) | np.roll(hit, -1, axis=1)
        img[edges] = np.asarray(SOLID, dtype=float)
        covered |= edges

    rgb = (np.flipud(img) * 255.0 + 0.5).astype(np.uint8)
    if not alpha:
        return rgb
    return np.dstack([rgb, np.flipud(covered).astype(np.uint8) * 255])
