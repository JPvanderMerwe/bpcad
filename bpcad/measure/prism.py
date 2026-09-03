"""
Read an extruded profile back out of a mesh.

WHY THIS AND NOT ANOTHER TEMPLATE
----------------------------------
A template can only make what it was written to make. Twenty templates is
twenty things, and the twenty-first request - "a birdhouse with a feeder and a
retainer" - comes back as whichever of the twenty claimed the loudest word,
with the rest of the sentence silently dropped. That is not a tuning problem,
it is the ceiling of the approach.

A fitter has no such ceiling. Give it a mesh and it hands back a spec, and
where the mesh came from stops mattering: a download, a scan, or a generative
model. `measure/revolve.py` does this for turned shapes - bowls, pots, vases.
This does it for the other large family, and between them they cover most of
what anybody prints.

WHAT A PRISM IS, AND WHY SO MUCH IS ONE
----------------------------------------
A prism is one 2D outline dragged along a straight line. Brackets, plates,
gussets, hooks, clips, enclosures, trays, gears, keyrings, anything laser-cut
or extruded - all prisms. They look nothing alike and they are all the same
kind of object, which is exactly what makes fitting them worthwhile: one
measurement recovers the whole family.

The output is a level-2 op list rather than a template's parameters, because
`profile_extrude` already exists in the DSL and already takes an outline and a
height. A fitted prism is therefore editable in the same way everything else
is, with no new machinery.

MEASURED, WITH THE EVIDENCE
----------------------------
`constancy` says how much the cross-section actually varies along the axis; a
true prism sits near zero and a cone does not. `residual_mm` says how far the
simplified outline sits from the real section. A shape that is not a prism is
REFUSED - a bracket fitted out of a teapot looks like an answer, which is worse
than no answer.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

AXES = {"x": (1.0, 0.0, 0.0), "y": (0.0, 1.0, 0.0), "z": (0.0, 0.0, 1.0)}

# Slices taken along the candidate axis. Enough to catch a step or a taper,
# few enough that sectioning stays quick on a large mesh.
SLICES = 15

# How much the OUTER outline's area may vary along the axis and still be called
# a prism.
#
# THIS WAS 0.12 AND THAT WAS TOO LOOSE. A flared bowl sectioned along Y scores
# 0.1139 - it slipped under and was fitted as an extrusion, which is precisely
# the confident wrong answer this fitter exists to refuse. A bowl is not a
# prism from any angle.
#
# Measured, on real parts: a plate 0.0000, an L hook 0.0000, a keyring 0.0000,
# a bowl along its worst axis 0.1139, a louvre vent 0.39. Genuine extrusions
# sit at zero, so the threshold belongs near zero and not near the first thing
# that fails.
MAX_CONSTANCY = 0.03

# Endpoint matching when chaining section segments into loops. The sections come
# from a tessellated mesh, so coincident endpoints agree to floating point and
# this only has to beat that.
WELD_MM = 1e-4

# Douglas-Peucker tolerance, as a fraction of the outline's own size. A profile
# with three hundred points is not editable by a person and rebuilds slowly.
SIMPLIFY_FRACTION = 0.004


@dataclass
class PrismFit:
    """An extruded profile read off a mesh, with the evidence."""

    axis: str = "z"
    profile: list[tuple[float, float]] = field(default_factory=list)
    height_mm: float = 0.0
    base_offset_mm: float = 0.0
    # Each cut-out found inside the outline: its shape, where it starts along
    # the axis, and how deep it goes. A pocket is not a hole and the difference
    # is most of the volume.
    cutouts: list[dict] = field(default_factory=list)

    constancy: float = 1.0        # 0 = the section never changes
    residual_mm: float = 0.0      # simplified outline against the real section
    section_area_mm2: float = 0.0
    reasons: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.reasons

    def summary(self) -> list[str]:
        if not self.ok:
            return ["not an extruded shape: " + "; ".join(self.reasons)]
        return [
            "extruded profile fitted from the mesh",
            "  extruded along  %s, %.1f mm" % (self.axis.upper(), self.height_mm),
            "  outline         %d points, %.0f mm2" % (len(self.profile),
                                                       self.section_area_mm2),
            "  cut-outs        %d (%d round, %d shaped)" % (
                len(self.cutouts),
                sum(1 for c in self.cutouts if c["round"]),
                sum(1 for c in self.cutouts if not c["round"])),
            "  through / pocket %d / %d" % (
                sum(1 for c in self.cutouts if c["through"]),
                sum(1 for c in self.cutouts if not c["through"])),
            "  constancy       %.4f  (0 means the section never changes)" % self.constancy,
            "  fit residual    %.3f mm" % self.residual_mm,
        ]


# ---------------------------------------------------------------------------
# sectioning, without shapely
# ---------------------------------------------------------------------------


def _loops_at(mesh, axis: str, position: float) -> list[np.ndarray]:
    """
    Closed 2D loops where a plane cuts the mesh.

    trimesh can section a mesh but turning the result into polygons goes
    through shapely, which is not installed and is not worth a dependency for
    this. The segments come back unordered, so they are chained by welding
    endpoints - which is all `polygons_full` would have done.
    """
    from trimesh.intersections import mesh_plane

    normal = np.array(AXES[axis])
    origin = normal * position
    segments = np.asarray(mesh_plane(mesh, plane_normal=normal, plane_origin=origin))
    if len(segments) == 0:
        return []

    keep = [i for i in range(3) if abs(normal[i]) < 0.5]
    flat = segments[:, :, keep]                      # (n, 2, 2)

    # Weld endpoints onto a grid so chaining is a dictionary lookup rather than
    # a distance search - a section of a dense mesh has thousands of segments.
    quantised = np.round(flat / WELD_MM).astype(np.int64)
    ends: dict[tuple[int, int], list[int]] = {}
    for index, seg in enumerate(quantised):
        for point in (tuple(seg[0]), tuple(seg[1])):
            ends.setdefault(point, []).append(index)

    used = set()
    loops: list[np.ndarray] = []
    for start in range(len(flat)):
        if start in used:
            continue
        used.add(start)
        chain = [flat[start][0], flat[start][1]]
        here = tuple(quantised[start][1])
        while True:
            nxt = None
            for candidate in ends.get(here, ()):
                if candidate not in used:
                    nxt = candidate
                    break
            if nxt is None:
                break
            used.add(nxt)
            a, b = quantised[nxt]
            if tuple(a) == here:
                chain.append(flat[nxt][1]); here = tuple(b)
            else:
                chain.append(flat[nxt][0]); here = tuple(a)
            if here == tuple(quantised[start][0]):
                break                                 # closed
        if len(chain) >= 4:
            loops.append(np.asarray(chain, dtype=float))
    return loops


def _area(loop: np.ndarray) -> float:
    """Signed shoelace area. Sign carries the winding, which says outer or hole."""
    x, y = loop[:, 0], loop[:, 1]
    return 0.5 * float(np.dot(x, np.roll(y, 1)) - np.dot(y, np.roll(x, 1)))


def _perimeter(loop: np.ndarray) -> float:
    d = np.diff(np.vstack([loop, loop[:1]]), axis=0)
    return float(np.hypot(d[:, 0], d[:, 1]).sum())


def simplify(loop: np.ndarray, tolerance: float) -> np.ndarray:
    """
    Douglas-Peucker, iteratively so a long outline cannot blow the stack.

    A section of a tessellated mesh has a point every fraction of a millimetre
    along what is geometrically one straight edge. Keeping them makes a spec
    nobody can read and a rebuild that crawls; the tolerance is what decides
    how much shape is given up, and the residual reports the result.
    """
    if len(loop) < 4:
        return loop
    keep = np.zeros(len(loop), dtype=bool)
    keep[0] = keep[-1] = True
    stack = [(0, len(loop) - 1)]
    while stack:
        start, end = stack.pop()
        if end <= start + 1:
            continue
        a, b = loop[start], loop[end]
        span = b - a
        length = math.hypot(span[0], span[1])
        seg = loop[start + 1:end]
        if length < 1e-12:
            dist = np.hypot(seg[:, 0] - a[0], seg[:, 1] - a[1])
        else:
            dist = np.abs(span[0] * (a[1] - seg[:, 1]) - (a[0] - seg[:, 0]) * span[1]) / length
        worst = int(np.argmax(dist))
        if dist[worst] > tolerance:
            index = start + 1 + worst
            keep[index] = True
            stack.append((start, index))
            stack.append((index, end))
    return loop[keep]


def _circularity(loop: np.ndarray) -> float:
    """1.0 for a circle, lower for anything else. 4*pi*A / P^2."""
    perimeter = _perimeter(loop)
    if perimeter <= 0:
        return 0.0
    return float(4.0 * math.pi * abs(_area(loop)) / (perimeter ** 2))


# ---------------------------------------------------------------------------
# the fit
# ---------------------------------------------------------------------------


def fit_prism(mesh, slices: int = SLICES) -> PrismFit:
    """Find the axis this mesh is extruded along, and the outline it extrudes."""
    fit = PrismFit()
    bounds = np.asarray(mesh.bounds, dtype=float)
    size = bounds[1] - bounds[0]
    if float(size.min()) <= 0.2:
        fit.reasons.append("flat - there is no third dimension to extrude along")
        return fit

    # ONE BODY. A print layout has the lid lying on the bed beside the box, and
    # sectioning that gives two outer outlines - the larger would be taken as
    # the profile and the smaller as a HOLE in it, which is a confident wrong
    # answer about a part that is simply two parts.
    try:
        pieces = mesh.split(only_watertight=False)
    except Exception:
        pieces = []
    if len(pieces) > 1:
        fit.reasons.append(
            "this mesh is %d separate bodies. Fit them one at a time - a "
            "section across two of them reads the second as a hole in the "
            "first" % len(pieces)
        )
        return fit

    best = None
    for axis_index, axis in enumerate("xyz"):
        low, high = bounds[0][axis_index], bounds[1][axis_index]
        span = high - low
        if span <= 0.5:
            continue
        # Inside the ends: a slice exactly on a face returns the face itself.
        positions = np.linspace(low + span * 0.12, high - span * 0.12, slices)
        areas, loopsets = [], []
        for position in positions:
            loops = _loops_at(mesh, axis, float(position))
            if not loops:
                continue
            # THE OUTER OUTLINE ONLY, not the total area.
            #
            # Summing every loop counts the holes, and a hole that appears
            # partway up changes the total while the outline it is cut into
            # never moves. A birdhouse shell measured 14% "variation" and was
            # refused on the strength of its own entrance hole - and a box with
            # a hole in it is exactly the thing this is for. Holes are features
            # to be found, not evidence against the shape.
            areas.append(max(abs(_area(loop)) for loop in loops))
            loopsets.append((float(position), loops))
        if len(areas) < max(4, slices // 3):
            continue
        areas_arr = np.asarray(areas)
        mean = float(areas_arr.mean())
        if mean <= 1e-9:
            continue
        constancy = float(areas_arr.std() / mean)
        if best is None or constancy < best[0]:
            best = (constancy, axis, span, low, loopsets, mean)

    if best is None:
        fit.reasons.append("the mesh could not be sectioned on any axis")
        return fit

    constancy, axis, span, low, loopsets, mean_area = best
    fit.axis = axis
    fit.constancy = constancy
    fit.height_mm = float(span)
    fit.base_offset_mm = float(low)
    fit.section_area_mm2 = mean_area

    if constancy > MAX_CONSTANCY:
        fit.reasons.append(
            "the cross-section changes by %.0f%% along its own axis, so this is "
            "not one outline extruded - fitting a prism to it would produce a "
            "confident wrong answer" % (100 * constancy)
        )
        return fit

    # The MEDIAN slice, not the first: an end slice can clip a chamfer or a
    # counterbore that the rest of the part does not have.
    position, loops = loopsets[len(loopsets) // 2]
    loops = sorted(loops, key=lambda l: abs(_area(l)), reverse=True)
    outer = loops[0]

    extent = max(np.ptp(outer[:, 0]), np.ptp(outer[:, 1]))
    tolerance = extent * SIMPLIFY_FRACTION
    simplified = simplify(outer, tolerance)
    if len(simplified) < 3:
        fit.reasons.append("the outline simplified away to nothing")
        return fit

    fit.profile = [(round(float(x), 3), round(float(y), 3)) for x, y in simplified]
    fit.residual_mm = _outline_residual(outer, simplified)

    fit.cutouts = _find_cutouts(loopsets, tolerance, span, low)
    return fit


def _find_cutouts(loopsets, tolerance: float, span: float, low: float) -> list[dict]:
    """
    Every cut-out inside the outline: its shape, its start, and its DEPTH.

    Two things the first version got wrong, and both cost volume.

    IT ONLY KEPT ROUND ONES. A non-circular inner loop was discarded entirely,
    so the pocket it described was filled in solid - the keyring rebuilt 32.75%
    heavier than the mesh it was measured from. A shaped pocket is a
    profile_extrude cut, which the DSL already has.

    AND IT ASSUMED EVERYTHING WENT THROUGH. A pocket has a floor. Depth is
    measurable: follow each cut-out across the slices and see where it stops.
    Cutting a 1 mm engraving all the way through a 7 mm part is not a small
    error, it is a hole where there should be a mark.
    """
    # Group inner loops across slices by where their centres are.
    groups: list[dict] = []
    for position, loops in loopsets:
        if len(loops) < 2:
            continue
        ordered = sorted(loops, key=lambda l: abs(_area(l)), reverse=True)
        for loop in ordered[1:]:
            area = abs(_area(loop))
            if area < 1.0:
                continue
            centre = (float(loop[:, 0].mean()), float(loop[:, 1].mean()))
            size = math.sqrt(area)
            for group in groups:
                dx = centre[0] - group["centre"][0]
                dy = centre[1] - group["centre"][1]
                if math.hypot(dx, dy) < max(size * 0.5, 1.5):
                    group["positions"].append(position)
                    group["loops"].append(loop)
                    break
            else:
                groups.append({"centre": centre, "positions": [position],
                               "loops": [loop]})

    out: list[dict] = []
    for group in groups:
        positions = sorted(group["positions"])
        # The representative shape is the MEDIAN slice's, for the same reason
        # the outline is: an end slice can catch a chamfer the rest lacks.
        loop = group["loops"][len(group["loops"]) // 2]
        area = abs(_area(loop))
        round_ = _circularity(loop) > 0.90

        # Depth, from where the cut-out actually appears. The slices are inset
        # from the ends, so a cut-out present in the first or last sampled
        # slice is taken to run out to that end.
        first, last = positions[0], positions[-1]
        step = (positions[1] - positions[0]) if len(positions) > 1 else span * 0.1
        at_bottom = first <= low + span * 0.13 + step * 0.5
        at_top = last >= low + span * 0.87 - step * 0.5
        through = at_bottom and at_top

        start = low if at_bottom else first - step / 2.0
        end = (low + span) if at_top else last + step / 2.0

        cut = {
            "round": bool(round_),
            "through": bool(through),
            "x_mm": round(group["centre"][0], 3),
            "y_mm": round(group["centre"][1], 3),
            "start_mm": round(float(start - low), 3),
            "depth_mm": round(float(end - start), 3),
        }
        if round_:
            cut["diameter_mm"] = round(2.0 * math.sqrt(area / math.pi), 3)
        else:
            simplified = simplify(loop, tolerance)
            if len(simplified) < 3:
                continue
            cut["points"] = [(round(float(x), 3), round(float(y), 3))
                             for x, y in simplified]
        out.append(cut)
    return out


def _outline_residual(original: np.ndarray, simplified: np.ndarray) -> float:
    """Mean distance from the real section to the outline that replaced it."""
    if len(simplified) < 2:
        return 0.0
    a = simplified
    b = np.roll(simplified, -1, axis=0)
    seg = b - a
    length2 = np.maximum((seg ** 2).sum(axis=1), 1e-12)

    total = 0.0
    for point in original:
        t = np.clip(((point - a) * seg).sum(axis=1) / length2, 0.0, 1.0)
        closest = a + seg * t[:, None]
        total += float(np.hypot(*(point - closest).T).min())
    return round(total / len(original), 4)


def to_dsl_ops(fit: PrismFit) -> list[dict]:
    """
    The fit as a level-2 op list: an extruded outline, plus its round holes.

    Level 2 rather than a template, because `profile_extrude` already takes an
    outline and a height and every op is already validated. A fitted prism is
    editable exactly like anything else in this program, with no new machinery
    and no new place for a bug to live.
    """
    if not fit.ok:
        raise ValueError("cannot make a spec from a shape that is not extruded: "
                         + "; ".join(fit.reasons))

    ops: list[dict] = [{
        "op": "profile_extrude",
        "points": [list(p) for p in fit.profile],
        "height_mm": round(fit.height_mm, 3),
    }]

    for cut in fit.cutouts:
        # A THROUGH cut overshoots both ends; a POCKET starts where it starts
        # and stops where it stops. A cutter that ends exactly flush with a
        # surface leaves a zero-thickness face the mesher may or may not close,
        # so a through cut gets 2 mm of air at each end and a pocket gets it at
        # the open end only.
        if cut["through"]:
            z0, height = -2.0, fit.height_mm + 4.0
        elif cut["start_mm"] <= 0.01:
            z0, height = -2.0, cut["depth_mm"] + 2.0
        else:
            z0, height = cut["start_mm"], cut["depth_mm"] + 2.0

        if cut["round"]:
            ops.append({
                "op": "disc",
                "diameter_mm": cut["diameter_mm"],
                "height_mm": round(height, 3),
                "x_mm": cut["x_mm"], "y_mm": cut["y_mm"], "z_mm": round(z0, 3),
                "mode": "cut",
            })
        else:
            ops.append({
                "op": "profile_extrude",
                "points": [list(p) for p in cut["points"]],
                "height_mm": round(height, 3),
                "z_mm": round(z0, 3),
                "mode": "cut",
            })
    return ops
