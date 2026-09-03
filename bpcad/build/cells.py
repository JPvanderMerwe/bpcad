"""
Voronoi cell patterns on a surface of revolution.

WHAT THIS IS, AND WHAT IT IS NOT
---------------------------------
This makes the cellular shell people mean when they say "like Nervous System":
a relaxed Voronoi tessellation wrapped round a turned surface, with the cell
boundaries left as a web of struts and the cell interiors cut away.

It is NOT their algorithm. Their pieces come out of a differential growth
simulation - cells that divide and push against each other over time - and the
irregular, flowing result is a record of that process. This is a one-shot
Voronoi with Lloyd relaxation. It reaches the same visual language and it is
not the same thing, and saying otherwise would be a lie about what you are
holding.

DETERMINISTIC, BECAUSE A SPEC HAS TO REBUILD
---------------------------------------------
Every random number here comes from a seed carried in the spec. The same
spec.yaml gives the same bowl, cell for cell, on any machine and in any year.
A generative pattern that came out different each build would break the
regression digest and, worse, would mean the spec no longer describes the part.

THE UNWRAP IS DELIBERATELY IMPERFECT
-------------------------------------
Cells are laid out in (u, v) where u is angle times a REFERENCE radius and v is
height. On a flared bowl the true radius runs from about 47 mm at the base to
90 mm at the rim, so cells near the rim come out wider than cells near the
base. That is not an error being tolerated: a pattern that grows towards the
opening is what these pieces look like, and forcing equal-area cells would make
it read as a machined grille instead.
"""

from __future__ import annotations

import math

import numpy as np

# How many rounds of Lloyd relaxation. Raw uniform random seeds give clumps and
# slivers; three rounds is enough to even them out while keeping the
# irregularity that makes it look grown rather than drawn. More rounds march
# steadily towards a hex grid, which is exactly the wrong destination.
RELAX_ROUNDS = 3


def relaxed_seeds(
    count: int, u_span: float, v_lo: float, v_hi: float, seed: int
) -> np.ndarray:
    """
    Seed points in a strip that wraps in u, evened out by Lloyd relaxation.

    The strip is tiled three times across u before every Voronoi so that cells
    at the seam see their true neighbours. Without it the pattern has a visible
    join running up the side of the bowl.
    """
    from scipy.spatial import Voronoi

    rng = np.random.RandomState(seed)
    pts = np.column_stack([
        rng.uniform(0.0, u_span, count),
        rng.uniform(v_lo, v_hi, count),
    ])

    for _ in range(RELAX_ROUNDS):
        tiled = np.vstack([pts + (dx, 0.0) for dx in (-u_span, 0.0, u_span)])
        vor = Voronoi(tiled)
        moved = []
        for i in range(count):
            region = vor.regions[vor.point_region[i + count]]
            if not region or -1 in region:
                moved.append(pts[i])
                continue
            poly = np.array(vor.vertices[region], dtype=float)
            poly[:, 1] = np.clip(poly[:, 1], v_lo, v_hi)
            moved.append(poly.mean(axis=0))
        pts = np.asarray(moved)
        pts[:, 0] = np.mod(pts[:, 0], u_span)
        pts[:, 1] = np.clip(pts[:, 1], v_lo, v_hi)
    return pts


def _clip_halfplane(poly: np.ndarray, nx: float, ny: float, c: float):
    """Sutherland-Hodgman clip, keeping the side where n.p <= c."""
    out = []
    n = len(poly)
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        da = nx * a[0] + ny * a[1] - c
        db = nx * b[0] + ny * b[1] - c
        if da <= 0:
            out.append(a)
        if (da > 0) != (db > 0):
            t = da / (da - db)
            out.append(a + t * (b - a))
    return np.asarray(out) if len(out) >= 3 else None


def inset_convex(poly: np.ndarray, distance: float):
    """
    Shrink a convex polygon by a true offset, not by scaling it.

    Scaling about the centroid is the easy version and it is wrong: a long thin
    cell scaled by a factor loses far more width than length, so the struts
    around it come out uneven and the thin ones fall below the nozzle. Voronoi
    cells are convex, so an exact offset is just every edge pushed inward and
    the half-planes re-intersected.
    """
    centre = poly.mean(axis=0)
    current = poly
    for i in range(len(poly)):
        a, b = poly[i], poly[(i + 1) % len(poly)]
        edge = b - a
        length = math.hypot(edge[0], edge[1])
        if length < 1e-9:
            continue
        nx, ny = edge[1] / length, -edge[0] / length
        if nx * (centre[0] - a[0]) + ny * (centre[1] - a[1]) > 0:
            nx, ny = -nx, -ny                 # make the normal point outward
        current = _clip_halfplane(current, nx, ny, nx * a[0] + ny * a[1] - distance)
        if current is None:
            return None
    return current


def cell_polygons(
    count: int,
    u_span: float,
    v_lo: float,
    v_hi: float,
    strut_mm: float,
    seed: int,
) -> list[np.ndarray]:
    """
    The holes, as convex polygons in unwrapped (u, v) millimetres.

    Each is a Voronoi cell inset by half a strut, so the gap between two
    neighbouring holes is one full strut wide.
    """
    from scipy.spatial import Voronoi

    pts = relaxed_seeds(count, u_span, v_lo, v_hi, seed)
    tiled = np.vstack([pts + (dx, 0.0) for dx in (-u_span, 0.0, u_span)])
    vor = Voronoi(tiled)

    out: list[np.ndarray] = []
    for i in range(count):
        region = vor.regions[vor.point_region[i + count]]
        if not region or -1 in region:
            continue                          # unbounded, at the strip's end
        poly = np.array(vor.vertices[region], dtype=float)

        # Trim to the banded region, so the rim and the base stay solid.
        for nx, ny, c in ((0.0, -1.0, -v_lo), (0.0, 1.0, v_hi)):
            poly = _clip_halfplane(poly, nx, ny, c)
            if poly is None:
                break
        if poly is None:
            continue

        poly = inset_convex(poly, strut_mm / 2.0)
        if poly is None or len(poly) < 3:
            continue                          # a cell smaller than its struts
        out.append(poly)
    return out


def open_fraction(polys: list[np.ndarray], u_span: float, v_lo: float, v_hi: float) -> float:
    """How much of the banded area is hole rather than strut. 0..1."""
    band = u_span * (v_hi - v_lo)
    if band <= 0:
        return 0.0
    area = 0.0
    for poly in polys:
        x, y = poly[:, 0], poly[:, 1]
        area += 0.5 * abs(float(np.dot(x, np.roll(y, 1)) - np.dot(y, np.roll(x, 1))))
    return min(area / band, 1.0)


def cell_cutter(
    poly: np.ndarray,
    radius_at,
    u_ref: float,
    z_min: float,
    z_max: float,
    depth_mm: float,
):
    """
    One cell as a PLANAR prism standing on the surface's tangent plane.

    NOT a loft between an inner ring and an outer ring of the same polygon.
    Those rings are not planar on a curved surface, and lofting between two
    non-planar wires produced self-intersecting solids - several with NEGATIVE
    volume - which then subtracted the entire bowl instead of a hole. The build
    reported one body, zero volume, and no error.

    A cell is around 14 mm across on a 180 mm bowl, so its own tangent plane is
    a very good approximation over that patch, and a prism built on a plane is
    valid by construction rather than by luck.
    """
    import cadquery as cq

    def on_surface(u: float, z: float):
        theta = u / u_ref
        r = radius_at(min(max(z, z_min), z_max))
        return np.array([r * math.cos(theta), r * math.sin(theta), z]), theta

    centre_u = float(np.mean(poly[:, 0]))
    centre_z = float(np.mean(poly[:, 1]))
    origin, theta = on_surface(centre_u, centre_z)

    # Outward normal of a surface of revolution, from the profile's own slope.
    step = 0.35
    z0, z1 = max(centre_z - step, z_min), min(centre_z + step, z_max)
    dr, dz = radius_at(z1) - radius_at(z0), z1 - z0
    length = math.hypot(dr, dz) or 1.0
    n_r, n_z = dz / length, -dr / length
    normal = np.array([n_r * math.cos(theta), n_r * math.sin(theta), n_z])

    x_dir = np.array([-math.sin(theta), math.cos(theta), 0.0])
    y_dir = np.cross(normal, x_dir)
    y_dir /= (np.linalg.norm(y_dir) or 1.0)

    flat = []
    for u, z in poly:
        point, _theta = on_surface(u, z)
        d = point - origin
        flat.append((float(np.dot(d, x_dir)), float(np.dot(d, y_dir))))

    plane = cq.Plane(
        origin=cq.Vector(*origin),
        xDir=cq.Vector(*x_dir),
        normal=cq.Vector(*normal),
    )
    return cq.Workplane(plane).polyline(flat).close().extrude(depth_mm, both=True)
