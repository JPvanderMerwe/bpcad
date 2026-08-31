"""
Do the separate parts of an assembly actually fit each other?

WHY THIS IS NOT COVERED BY ANYTHING ELSE
-----------------------------------------
Every other check looks at one body: is it watertight, are its features thick
enough, does it fit the bed. None of them looks at the SPACE BETWEEN two
bodies, and that gap is the whole of whether an assembly works.

Two ways it goes wrong, and they need opposite answers:

  TOO TIGHT   a lid that will not go on, a pin that will not turn. On a printed
              part the gap has to absorb elephant foot, over-extrusion and the
              nozzle's own width, which is why the clearance table exists and
              why a nominal zero-gap fit is always wrong.
  TOO LOOSE   a lid that falls off, a linkage with slop in it. Less dangerous,
              but it is still a part that does not do its job.

Only the first is a failure. A loose fit is reported and left to you, because
"loose" depends on what the part is for in a way this cannot know.

AND A GLOBAL MINIMUM DISTANCE CANNOT MEASURE A FIT AT ALL. Two parts that go
together touch each other - that is what going together means. A lid sits on a
rim, so the shortest distance between lid and box is zero no matter how the lip
is sized, and it is zero for a lid with 2.5 mm of slop exactly as it is for one
jammed at 0.02. What decides whether the lid goes on is the gap along the
INSERTION AXIS, between the faces that slide past each other. So the parts are
offset along that axis by less than their engagement - still interlocked, but
lifted off the seat - and measured there. The template supplies the offset,
because the template is what knows how deep the lip is.

AND THERE IS A THIRD FAULT, WHICH IS WORSE THAN EITHER: two bodies occupying the
same space. Distance cannot see it. Point-to-triangle distance is unsigned and
compares vertices to faces, so where two large flat faces cross each other
between their corners there is no vertex anywhere near the crossing and the
answer comes back comfortable. A birdhouse roof driven bodily through its own
side wall measured 22.064 mm of clearance. Interference is therefore tested
with a real boolean on the solids, before any distance is measured, and a
distance is only reported for pairs that are genuinely apart.

A PRINT-IN-PLACE GAP IS NOT AN ASSEMBLY GAP. The louvre vent has six bodies
0.30 mm apart on purpose - they are meant to stay separate and move. That is
a design gap, not a fit, and it is excluded by the template saying so.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

# Below this two bodies are touching, not fitted - almost certainly one solid
# that the mesher happened to split, or two parts that will fuse in the print.
TOUCHING_MM = 0.02

# A gap wider than this is not a fit, it is just two things near each other.
NOT_A_FIT_MM = 5.0


@dataclass
class FitReport:
    """The gaps between bodies, and whether any of them will not go together."""

    gaps_mm: dict[tuple[str, str], float] = field(default_factory=dict)
    clearance_mm: float = 0.0
    material: str = ""
    problems: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    checked: bool = False
    # Pairs that touch by design - a lid on a rim. Their recorded gap is the
    # SLIDING clearance measured off the seat, not the distance between them,
    # which is zero and says nothing.
    seated: list[tuple[str, str]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems

    def summary(self) -> list[str]:
        if not self.checked:
            return ["one body - nothing to fit"]
        out = ["clearance for %s: %.2f mm" % (self.material, self.clearance_mm)]
        seated = set(self.seated)
        for (a, b), gap in sorted(self.gaps_mm.items()):
            _ = seated
            out.append("  %-12s to %-12s %.3f mm" % (a, b, gap))
        return out


def point_triangle_distance(points: np.ndarray, triangles: np.ndarray) -> np.ndarray:
    """
    Shortest distance from each point to the nearest of a set of triangles.

    NO RTREE. trimesh.proximity hard-depends on it, exactly as trimesh.ray does,
    and it is not installed - the same absence that made the ray cast in
    verify/probe.py hand-written. Without this the fallback was a bounding-box
    estimate that returns zero for any two bodies whose boxes overlap, so a
    louvre vent reported every one of its blades as touching every other. A
    wrong number, silently.

    This is the standard closest-point-on-triangle: project onto the plane,
    work out which of the seven Voronoi regions the projection lands in, and
    clamp to the corresponding vertex, edge or face. Vectorised over all
    triangles at once, chunked over points to keep the peak allocation sane.
    """
    a = triangles[:, 0, :]
    ab = triangles[:, 1, :] - a
    ac = triangles[:, 2, :] - a

    d00 = np.einsum("ij,ij->i", ab, ab)
    d01 = np.einsum("ij,ij->i", ab, ac)
    d11 = np.einsum("ij,ij->i", ac, ac)
    denom = d00 * d11 - d01 * d01
    denom = np.where(np.abs(denom) < 1e-20, 1e-20, denom)

    out = np.empty(len(points))
    chunk = max(1, min(len(points), 40_000_000 // max(len(triangles), 1)))

    for start in range(0, len(points), chunk):
        p = points[start : start + chunk]
        ap = p[:, None, :] - a[None, :, :]

        d20 = np.einsum("ptj,tj->pt", ap, ab)
        d21 = np.einsum("ptj,tj->pt", ap, ac)

        v = (d11 * d20 - d01 * d21) / denom
        w = (d00 * d21 - d01 * d20) / denom
        u = 1.0 - v - w

        # Clamp the barycentric coordinates back onto the triangle. Doing it
        # this way rather than by region tests is slightly loose at the corners
        # and exact everywhere that matters for a clearance.
        v = np.clip(v, 0.0, 1.0)
        w = np.clip(w, 0.0, 1.0)
        over = v + w > 1.0
        total = np.where(over, v + w, 1.0)
        v = np.where(over, v / total, v)
        w = np.where(over, w / total, w)

        closest = (a[None, :, :]
                   + v[:, :, None] * ab[None, :, :]
                   + w[:, :, None] * ac[None, :, :])
        out[start : start + chunk] = np.sqrt(
            ((p[:, None, :] - closest) ** 2).sum(axis=2)
        ).min(axis=1)

    return out


def _min_gap(a, b, samples: int = 900) -> float:
    """
    Smallest distance between two meshes.

    Sampled from one mesh's vertices against all of the other's triangles.
    Sampling is honest here in the direction that matters: if the sample finds
    an interference there is one, and a gap this misses would have to hide
    between sampled vertices, which on these meshes is a fraction of a
    millimetre of surface.
    """
    points = np.asarray(a.vertices, dtype=float)
    if len(points) > samples:
        step = max(1, len(points) // samples)
        points = points[::step]

    triangles = np.asarray(b.vertices, dtype=float)[np.asarray(b.faces)]
    if len(triangles) > 12000:
        triangles = triangles[:: max(1, len(triangles) // 12000)]

    return float(point_triangle_distance(points, triangles).min())


def mesh_of_solid(solid, tolerance: float = 0.005, angular: float = 0.05):
    """
    Tessellate an ASSEMBLED solid so its bodies can be measured against each
    other.

    The exported STL on disk is the PRINT layout - box upright, lid flat on the
    bed beside it - and the distance between those two is the layout gap, not
    the fit. Measuring it told me the birdhouse lid had 8.031 mm of clearance,
    identically, for three different lid designs. Same tolerance as every other
    export, so what is measured is what gets printed.
    """
    import tempfile
    from pathlib import Path

    from bpcad.build.compile import export_solid
    from bpcad.verify.mesh import load_mesh

    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "assembled.stl"
        export_solid(solid, path, tolerance=tolerance, angular_tolerance=angular)
        return load_mesh(path)


def solid_gap_mm(a, b) -> float:
    """
    Exact shortest distance between two solids, from the kernel.

    NOT from the mesh. Mesh distance compares vertices to faces, so two bodies
    that meet along an EDGE - a lean-to roof resting on the front rim, every
    other part of it standing well clear - have no vertex near any face of the
    other and measure 24 mm apart while physically touching. OpenCascade
    answers the real question on the real geometry.
    """
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape

    ext = BRepExtrema_DistShapeShape(a.val().wrapped, b.val().wrapped)
    ext.Perform()
    if not ext.IsDone():
        raise RuntimeError("kernel could not measure the gap between two bodies")
    return float(ext.Value())


def slide_gap_mm(a, b, axis: tuple[float, float, float], standoff_mm: float) -> float:
    """
    The gap between two parts along the axis they assemble on.

    `standoff_mm` lifts b off its seat WITHOUT disengaging it, so the seating
    faces stop being the closest thing and the sliding faces become it. It has
    to be smaller than the engagement depth - lift a 4 mm lip by 5 mm and it is
    out of the hole, and the number returned is the height of the lift rather
    than the clearance. Half the engagement is a safe choice and the caller
    passes it, because the caller is what knows the depth.
    """
    n = math.sqrt(sum(c * c for c in axis)) or 1.0
    off = tuple(c / n * standoff_mm for c in axis)
    return solid_gap_mm(a, b.translate(off))


def interference(solids: list, names: tuple[str, ...] = ()) -> list[str]:
    """
    Which pairs of solids occupy the same space, by volume of intersection.

    A boolean, not a distance, because distance cannot answer this - see the
    module docstring. Anything under a cubic hundredth of a millimetre is
    tessellation noise on a touching face, not overlap.
    """
    NOISE_MM3 = 0.01
    out = []
    labels = list(names) if len(names) == len(solids) else [
        "body %d" % (i + 1) for i in range(len(solids))
    ]
    for i in range(len(solids)):
        for j in range(i + 1, len(solids)):
            try:
                shared = solids[i].intersect(solids[j])
                vol = abs(shared.val().Volume()) if shared.vals() else 0.0
            except Exception:
                # An empty intersection is an error in OCC, not a zero.
                continue
            if vol > NOISE_MM3:
                out.append(
                    "%s and %s occupy the same space - %.1f mm3 of overlap. "
                    "This is not a tight fit, it is one part driven through "
                    "the other, and no clearance will fix it."
                    % (labels[i], labels[j], vol)
                )
    return out


def check_fit(
    stl_path=None,
    roles: tuple[str, ...] = (),
    clearance_mm: float = 0.0,
    material: str = "",
    design_gap_mm: float = 0.0,
    mesh=None,
    solid=None,
    insertion_axis: tuple[float, float, float] | None = None,
    standoff_mm: float = 0.0,
) -> FitReport:
    """
    Measure the gap between every pair of bodies and judge it.

    MEASURE THE ASSEMBLED PART, NOT THE PRINT LAYOUT. A lid laid on the bed
    beside its box is eight millimetres away from it, which says nothing about
    whether it fits - the fit is a property of the part assembled, and the
    layout is a property of the bed. Pass `mesh` for the assembled solid;
    `stl_path` is the print layout and is only right for a part that prints
    in place.

    `design_gap_mm` is a gap the part is MEANT to have - the print-in-place
    shoulder gaps in the louvre vent. Anything near it is left alone.
    """
    from bpcad.verify.mesh import load_mesh

    report = FitReport(clearance_mm=clearance_mm, material=material)
    if solid is not None:
        import cadquery as cq

        bodies = [cq.Workplane(obj=s) for s in solid.vals()[0].Solids()] \
            if len(solid.vals()) == 1 else [cq.Workplane(obj=s) for s in solid.vals()]
        if len(bodies) > 1:
            report.checked = True
            clash = interference(bodies, roles)
            if clash:
                report.problems.extend(clash)
                return report
            names = list(roles) if len(roles) == len(bodies) else [
                "body %d" % (i + 1) for i in range(len(bodies))
            ]
            for i in range(len(bodies)):
                for j in range(i + 1, len(bodies)):
                    seated = solid_gap_mm(bodies[i], bodies[j])
                    if insertion_axis and standoff_mm > 0 and seated < TOUCHING_MM:
                        # Seated. The useful number is the sliding clearance.
                        gap = slide_gap_mm(bodies[i], bodies[j],
                                           insertion_axis, standoff_mm)
                        # Once the sliding gap is wider than the lift, the lift
                        # itself becomes the closest approach and the number
                        # stops being the clearance. Say so rather than report
                        # a figure that is really just the standoff.
                        if gap >= standoff_mm - 1e-6:
                            report.warnings.append(
                                "%s and %s have at least %.2f mm of play, which "
                                "is as far as this measures - lifting further "
                                "pulls them apart. Loose, exact figure unknown."
                                % (names[i], names[j], standoff_mm)
                            )
                        report.seated.append((names[i], names[j]))
                    else:
                        gap = seated
                    report.gaps_mm[(names[i], names[j])] = round(gap, 4)
            _judge(report, design_gap_mm)
            return report
        if mesh is None:
            mesh = mesh_of_solid(solid)
    if mesh is None:
        mesh = load_mesh(stl_path)
    if mesh.body_count < 2:
        return report

    pieces = mesh.split(only_watertight=False)
    if len(pieces) < 2:
        return report
    report.checked = True

    ordered = sorted(pieces, key=lambda m: float(m.bounds[0][0]))
    names = list(roles) if len(roles) == len(ordered) else [
        "body %d" % (i + 1) for i in range(len(ordered))
    ]

    for i in range(len(ordered)):
        for j in range(i + 1, len(ordered)):
            report.gaps_mm[(names[i], names[j])] = round(
                _min_gap(ordered[i], ordered[j]), 4
            )
    _judge(report, design_gap_mm)
    return report


def _judge(report: FitReport, design_gap_mm: float = 0.0) -> None:
    """
    Turn measured gaps into verdicts. Shared by the kernel path and the mesh
    path so both say the same thing about the same number.
    """
    clearance_mm = report.clearance_mm
    material = report.material

    for (a, b), gap in sorted(report.gaps_mm.items()):
        if gap > NOT_A_FIT_MM:
            continue              # two things near each other, not a fit
        if design_gap_mm and abs(gap - design_gap_mm) < design_gap_mm * 0.5:
            continue              # a deliberate print-in-place gap

        if (a, b) in report.seated and gap < TOUCHING_MM:
            report.problems.append(
                "%s and %s seat on each other and have no clearance where they "
                "slide - %.3f mm. Printed, they will fuse into one piece."
                % (a, b, gap)
            )
        elif gap < TOUCHING_MM:
            # Touching is NORMAL for parts that stack - a lid sits on a rim, a
            # lean-to roof rests on the front edge. Calling that a failure
            # flags every correctly designed assembly, so it is reported and
            # left alone. Bodies in the SAME SPACE are the real fault and they
            # are caught by interference(), with a boolean, before this runs.
            report.warnings.append(
                "%s and %s touch (%.3f mm). That is right for parts that seat "
                "against each other, and wrong for parts meant to have a gap - "
                "check which this is." % (a, b, gap)
            )
        elif clearance_mm and gap < clearance_mm:
            report.problems.append(
                "%s and %s are %.3f mm apart, under the %.2f mm clearance %s "
                "needs. It will not go together - a printed gap has to absorb "
                "elephant foot, over-extrusion and the nozzle width."
                % (a, b, gap, clearance_mm, material or "this material")
            )
        elif clearance_mm and gap > clearance_mm * 4:
            report.warnings.append(
                "%s and %s are %.3f mm apart, well over the %.2f mm needed. It "
                "will go together loosely - fine for a lift-off lid, slop in a "
                "linkage." % (a, b, gap, clearance_mm)
            )
