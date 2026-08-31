"""
Orthographic z-buffer rasteriser with per-face Lambert shading.

Pure CPU. No GPU, no OpenGL, no network. numpy only.

WHY THIS EXISTS AT ALL
----------------------
matplotlib's Poly3DCollection cannot depth-sort across interpenetrating parts.
It sorts whole polygons by a single depth value, so a shell renders straight
through and you see the inside of a part you are looking at from outside. There
is no option that fixes it. A real per-pixel z-buffer is the only honest answer,
and at these mesh sizes it costs under a second in numpy.

THE Z-TEST DIRECTION IS THE DANGEROUS PART
------------------------------------------
An inverted z-test produces a picture that looks entirely plausible - you are
simply looking at the BACK of the object without realising it. It is not
obvious by eye. So the convention is stated once here and asserted by tests
against a deliberately asymmetric scene:

    `view` points FROM the scene TOWARD the camera.
    depth = vertex . view
    LARGER depth means NEARER the camera.
    The z-buffer keeps the MAXIMUM depth per pixel.

BUFFER ORIENTATION
------------------
Buffers are built with row 0 at the BOTTOM (v increasing with row index),
because that is how the maths reads. to_image() flips vertically on the way
out, because that is how a PNG reads. Do not flip twice.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

# Barycentric coordinates are allowed to go this far negative before a pixel is
# considered outside a triangle. Without it, pixels landing exactly on a shared
# edge fall through the crack between two adjacent triangles and leave pinholes.
EDGE_EPS = 1e-7

# Cyclic axis triples: for axis a, (u, v, w) are the columns to project onto.
AXIS_COLUMNS = {"z": (0, 1, 2), "x": (1, 2, 0), "y": (2, 0, 1)}


@dataclass(frozen=True)
class Bounds:
    """The rectangle of world space the buffer covers, in projected units."""

    u0: float
    u1: float
    v0: float
    v1: float

    @property
    def width(self) -> float:
        return self.u1 - self.u0

    @property
    def height(self) -> float:
        return self.v1 - self.v0


def view_basis(elev_deg: float, azim_deg: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Camera basis as (right, up, view).

    `view` points from the scene toward the camera - see the module docstring.
    azim is measured about +Z, from +X toward +Y. elev is degrees above the XY
    plane. So elev=0, azim=0 puts the camera on +X looking back at the origin,
    with screen-right = +Y and screen-up = +Z.
    """
    e = math.radians(elev_deg)
    a = math.radians(azim_deg)
    view = np.array(
        [math.cos(e) * math.cos(a), math.cos(e) * math.sin(a), math.sin(e)],
        dtype=float,
    )
    view /= np.linalg.norm(view)

    world_up = np.array([0.0, 0.0, 1.0])
    if abs(float(view @ world_up)) > 0.999:      # looking straight down the axis
        world_up = np.array([0.0, 1.0, 0.0])

    right = np.cross(world_up, view)
    right /= np.linalg.norm(right)
    up = np.cross(view, right)
    up /= np.linalg.norm(up)
    return right, up, view


def fit_bounds(u: np.ndarray, v: np.ndarray, width: int, height: int, margin: float = 0.06) -> Bounds:
    """
    Smallest window containing every projected point, padded, then widened on
    one axis so the pixel aspect stays square and nothing is stretched.
    """
    u0, u1 = float(u.min()), float(u.max())
    v0, v1 = float(v.min()), float(v.max())

    du = max(u1 - u0, 1e-9)
    dv = max(v1 - v0, 1e-9)
    pad = margin * max(du, dv)
    u0, u1 = u0 - pad, u1 + pad
    v0, v1 = v0 - pad, v1 + pad

    du = u1 - u0
    dv = v1 - v0
    want = width / height
    have = du / dv
    if have < want:                              # too narrow, widen u
        extra = (want * dv - du) / 2.0
        u0, u1 = u0 - extra, u1 + extra
    else:                                        # too short, heighten v
        extra = (du / want - dv) / 2.0
        v0, v1 = v0 - extra, v1 + extra
    return Bounds(u0, u1, v0, v1)


def zbuffer(
    tri_u: np.ndarray,
    tri_v: np.ndarray,
    tri_w: np.ndarray,
    width: int,
    height: int,
    bounds: Bounds,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Rasterise triangles into a depth buffer and a winning-triangle index buffer.

    tri_u, tri_v, tri_w are each (M, 3): the projected u, v and depth of every
    triangle's three vertices. Returns:

        depth  (height, width) float, -inf where nothing was hit
        index  (height, width) int64, -1 where nothing was hit

    Keeps the MAXIMUM depth per pixel. See the module docstring on why that
    direction is the one that matters.

    This is shared with verify.probe.height_map, which is the same operation
    viewed straight down a print axis. One algorithm, one place.
    """
    depth = np.full((height, width), -np.inf, dtype=float)
    index = np.full((height, width), -1, dtype=np.int64)
    if len(tri_u) == 0:
        return depth, index

    du = bounds.width / width
    dv = bounds.height / height
    us = bounds.u0 + (np.arange(width) + 0.5) * du
    vs = bounds.v0 + (np.arange(height) + 0.5) * dv

    au, bu, cu = tri_u[:, 0], tri_u[:, 1], tri_u[:, 2]
    av, bv, cv = tri_v[:, 0], tri_v[:, 1], tri_v[:, 2]

    # Twice the signed projected area. Zero means the triangle projects to a
    # line and covers no pixels - skip it rather than dividing by zero.
    denom = (bv - cv) * (au - cu) + (cu - bu) * (av - cv)

    lo_u = np.minimum(np.minimum(au, bu), cu)
    hi_u = np.maximum(np.maximum(au, bu), cu)
    lo_v = np.minimum(np.minimum(av, bv), cv)
    hi_v = np.maximum(np.maximum(av, bv), cv)

    i0s = np.clip(np.floor((lo_u - bounds.u0) / du - 0.5).astype(int), 0, width)
    i1s = np.clip(np.ceil((hi_u - bounds.u0) / du + 0.5).astype(int), 0, width)
    j0s = np.clip(np.floor((lo_v - bounds.v0) / dv - 0.5).astype(int), 0, height)
    j1s = np.clip(np.ceil((hi_v - bounds.v0) / dv + 0.5).astype(int), 0, height)

    for t in range(tri_u.shape[0]):
        d = denom[t]
        if d == 0.0:
            continue
        i0, i1, j0, j1 = i0s[t], i1s[t], j0s[t], j1s[t]
        if i0 >= i1 or j0 >= j1:
            continue

        U = us[i0:i1][None, :]
        V = vs[j0:j1][:, None]

        l1 = ((bv[t] - cv[t]) * (U - cu[t]) + (cu[t] - bu[t]) * (V - cv[t])) / d
        l2 = ((cv[t] - av[t]) * (U - cu[t]) + (au[t] - cu[t]) * (V - cv[t])) / d
        l3 = 1.0 - l1 - l2

        inside = (l1 >= -EDGE_EPS) & (l2 >= -EDGE_EPS) & (l3 >= -EDGE_EPS)
        if not inside.any():
            continue

        z = l1 * tri_w[t, 0] + l2 * tri_w[t, 1] + l3 * tri_w[t, 2]

        sub_depth = depth[j0:j1, i0:i1]
        win = inside & (z > sub_depth)           # MAXIMUM depth wins. See docstring.
        if not win.any():
            continue
        sub_depth[win] = z[win]
        index[j0:j1, i0:i1][win] = t

    return depth, index


def project_axis(
    vertices: np.ndarray, faces: np.ndarray, axis: str = "z"
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Project triangles straight down a world axis. Used by the height map."""
    if axis not in AXIS_COLUMNS:
        raise ValueError(
            "axis must be one of %s, got %r" % (", ".join(sorted(AXIS_COLUMNS)), axis)
        )
    cu, cv, cw = AXIS_COLUMNS[axis]
    tris = vertices[faces]
    return tris[:, :, cu], tris[:, :, cv], tris[:, :, cw]


def project_camera(
    vertices: np.ndarray, faces: np.ndarray, right: np.ndarray, up: np.ndarray, view: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Project triangles into camera space. Depth grows toward the camera."""
    tris = vertices[faces]
    return tris @ right, tris @ up, tris @ view


def shade_lambert(
    normals: np.ndarray,
    light: np.ndarray,
    view: np.ndarray,
    ambient: float = 0.32,
) -> np.ndarray:
    """
    Per-face Lambert term in 0..1, one value per face.

    Normals are flipped toward the camera first. On a watertight, consistently
    wound mesh that is a no-op, because the face you can see always points at
    you. On a mesh with inconsistent winding it stops visible faces rendering
    black, which would otherwise look like a geometry fault that is not there.
    """
    n = np.asarray(normals, dtype=float)
    flip = (n @ view) < 0.0
    n = np.where(flip[:, None], -n, n)

    light = np.asarray(light, dtype=float)
    light = light / np.linalg.norm(light)
    return ambient + (1.0 - ambient) * np.clip(n @ light, 0.0, 1.0)


def to_image(
    depth: np.ndarray,
    index: np.ndarray,
    shade: np.ndarray,
    colour: tuple[float, float, float],
    background: tuple[float, float, float],
) -> np.ndarray:
    """
    Compose depth, face index and per-face shading into an (H, W, 3) uint8
    image, flipped so row 0 is the TOP of the picture.
    """
    h, w = depth.shape
    img = np.empty((h, w, 3), dtype=float)
    img[:, :] = np.asarray(background, dtype=float)

    hit = index >= 0
    if hit.any():
        s = shade[index[hit]][:, None]
        img[hit] = np.clip(np.asarray(colour, dtype=float)[None, :] * s, 0.0, 1.0)

    return (np.flipud(img) * 255.0 + 0.5).astype(np.uint8)


def render(
    vertices: np.ndarray,
    faces: np.ndarray,
    face_normals: np.ndarray,
    width: int = 900,
    height: int = 700,
    elev_deg: float = 25.0,
    azim_deg: float = 315.0,
    colour: tuple[float, float, float] = (0.62, 0.66, 0.72),
    background: tuple[float, float, float] = (0.035, 0.035, 0.043),
    light_dir: np.ndarray | None = None,
    ambient: float = 0.32,
    margin: float = 0.06,
) -> np.ndarray:
    """
    Render a mesh to an (H, W, 3) uint8 image. Orthographic, per-face Lambert.

    light_dir defaults to over the camera's left shoulder, so the lighting is
    consistent from every view instead of swinging around as the camera moves.
    """
    vertices = np.asarray(vertices, dtype=float)
    faces = np.asarray(faces)
    right, up, view = view_basis(elev_deg, azim_deg)

    tri_u, tri_v, tri_w = project_camera(vertices, faces, right, up, view)
    bounds = fit_bounds(tri_u, tri_v, width, height, margin=margin)
    depth, index = zbuffer(tri_u, tri_v, tri_w, width, height, bounds)

    if light_dir is None:
        light_dir = 0.62 * view + 0.55 * up - 0.36 * right
    shade = shade_lambert(face_normals, light_dir, view, ambient=ambient)

    return to_image(depth, index, shade, colour, background)
