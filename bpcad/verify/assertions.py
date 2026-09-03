"""
Machine-checkable assertions, measured off the solid.

BRIEF 9.4 - THE SPEC IS THE CONTRACT
-------------------------------------
"The user asked for an 8.2 mm hole" becomes a check that a cylindrical face of
diameter 8.2 +/- 0.05 exists. That sentence is the whole of this module, and it
is what makes two other things possible:

  - Section 5's first-try fit rate becomes computable rather than a feeling.
  - Section 3.2's "we never charge for a failed part" becomes enforceable
    rather than a slogan, because failure is detected programmatically.

MEASURED OFF THE B-REP, NOT THE MESH
-------------------------------------
A hole in a mesh is a ring of flat facets and its "diameter" depends on how
finely it was tessellated. A hole in a solid is a cylindrical face with an
exact radius. Asked for 8.2 mm, the kernel returns 8.2000 - so the check can
carry a 0.05 mm tolerance and mean it. Measuring the mesh would force a
tolerance wide enough to hide real errors.

The envelope is the one thing taken from the bounding box, because that is
what an envelope is.

WHAT AN ASSERTION IS NOT
-------------------------
It is not a test of whether the part is nice. It is a test of whether the part
is the part that was ASKED FOR. A bracket that is beautifully made and 4 mm too
short fails; a crude one with every dimension right passes. That ordering is
deliberate - the brief's whole product claim is first-try dimensional
correctness, and everything else is downstream of it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Brief 9.4 names this figure for a hole. It is achievable because the
# measurement comes off the kernel: a hole cut at 8.2 measures 8.2000.
HOLE_TOLERANCE_MM = 0.05

# An overall extent is looser, because a request that says "80 mm wide" is
# usually describing the part and not a mating surface, and because corner
# radii and fillets legitimately move an envelope by a fraction.
EXTENT_TOLERANCE_MM = 0.5

# A wall is reported by the template as a feature rather than measured off the
# geometry, so this checks what the builder claims. Measuring a minimum wall
# thickness on an arbitrary solid is a much harder problem and is not pretended
# at here.
WALL_TOLERANCE_MM = 0.05


@dataclass
class Check:
    """One assertion, its expectation, and what was actually measured."""

    kind: str
    name: str
    expected: float | int
    measured: float | int | None = None
    tolerance: float = 0.0
    passed: bool = False
    detail: str = ""

    def line(self) -> str:
        if self.measured is None:
            return "  %-24s expected %-9s NOT MEASURABLE  %s" % (
                self.name, self._fmt(self.expected), self.detail)
        mark = "pass" if self.passed else "FAIL"
        return "  %-24s expected %-9s got %-9s %s  %s" % (
            self.name, self._fmt(self.expected), self._fmt(self.measured),
            mark, self.detail)

    @staticmethod
    def _fmt(value) -> str:
        if isinstance(value, float):
            return "%.3f" % value
        return str(value)


@dataclass
class AssertionReport:
    """Every assertion for one part, and whether the part is what was asked for."""

    checks: list[Check] = field(default_factory=list)
    error: str = ""

    @property
    def total(self) -> int:
        return len(self.checks)

    @property
    def passed(self) -> int:
        return sum(1 for c in self.checks if c.passed)

    @property
    def fits(self) -> bool:
        """
        Every assertion passed. Not "most" - a part with one wrong hole is a
        part that does not fit, and averaging that away is how a fit rate
        stops meaning anything.
        """
        return bool(self.checks) and not self.error and all(c.passed for c in self.checks)

    def summary(self) -> list[str]:
        if self.error:
            return ["could not check: %s" % self.error]
        if not self.checks:
            return ["no assertions - nothing was claimed about this part"]
        head = "%d of %d assertions passed%s" % (
            self.passed, self.total, "" if self.fits else "  -> DOES NOT FIT")
        return [head] + [c.line() for c in self.checks]


# ---------------------------------------------------------------------------
# measuring
# ---------------------------------------------------------------------------


def cylindrical_faces(solid) -> list[dict[str, float]]:
    """
    Every cylindrical face: its diameter and where its axis sits.

    This is how a hole is measured. A counterbore contributes two faces of
    different diameters, which is correct - they are two different features.
    """
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_SurfaceType

    out: list[dict[str, float]] = []
    for face in solid.faces().vals():
        adaptor = BRepAdaptor_Surface(face.wrapped)
        if adaptor.GetType() != GeomAbs_SurfaceType.GeomAbs_Cylinder:
            continue
        cylinder = adaptor.Cylinder()
        location = cylinder.Location()
        axis = cylinder.Axis().Direction()
        out.append({
            "diameter_mm": round(2.0 * float(cylinder.Radius()), 4),
            "x_mm": round(float(location.X()), 3),
            "y_mm": round(float(location.Y()), 3),
            "z_mm": round(float(location.Z()), 3),
            "axis_x": round(float(axis.X()), 3),
            "axis_y": round(float(axis.Y()), 3),
            "axis_z": round(float(axis.Z()), 3),
        })
    return out


def _holes_of_diameter(solid, diameter: float, tolerance: float) -> list[dict]:
    """Cylindrical faces matching a diameter, de-duplicated by axis position.

    A single hole can present as more than one face when it passes through
    several bodies or is split by a boolean, so faces sharing an axis line are
    counted once. Counting faces instead of holes reported four holes in a
    plate that has two.
    """
    matching = [c for c in cylindrical_faces(solid)
                if abs(c["diameter_mm"] - diameter) <= tolerance]
    unique: list[dict] = []
    for candidate in matching:
        for seen in unique:
            same_axis = (abs(candidate["axis_x"] - seen["axis_x"]) < 0.01
                         and abs(candidate["axis_y"] - seen["axis_y"]) < 0.01
                         and abs(candidate["axis_z"] - seen["axis_z"]) < 0.01)
            # Distance between the two axis reference points, ignoring the
            # component along the axis itself - two faces of one bore differ
            # only in how far up the bore they sit.
            dx = candidate["x_mm"] - seen["x_mm"]
            dy = candidate["y_mm"] - seen["y_mm"]
            dz = candidate["z_mm"] - seen["z_mm"]
            along = (dx * seen["axis_x"] + dy * seen["axis_y"] + dz * seen["axis_z"])
            off = ((dx - along * seen["axis_x"]) ** 2
                   + (dy - along * seen["axis_y"]) ** 2
                   + (dz - along * seen["axis_z"]) ** 2) ** 0.5
            if same_axis and off < 0.05:
                break
        else:
            unique.append(candidate)
    return unique


# ---------------------------------------------------------------------------
# the assertions
# ---------------------------------------------------------------------------


def check(solid, want: dict[str, Any], features: dict[str, float] | None = None,
          bodies: int | None = None) -> AssertionReport:
    """
    Run the assertions in `want` against a built solid.

    `want` is the corpus entry's `expect` block - the known-correct dimensions
    a person would measure with calipers. Each key is an assertion kind:

        extent_x_mm / extent_y_mm / extent_z_mm   overall size on that axis
        extent_any_mm                             some axis is this long
        hole_dia_mm                               a hole of this diameter exists
        hole_count                                how many of hole_dia_mm
        hole_spacing_mm                           between two of them
        wall_mm                                   the builder's own wall figure
        bodies                                    separate pieces
    """
    report = AssertionReport()
    features = features or {}

    try:
        bounding = solid.val().BoundingBox()
        extents = {"x": bounding.xlen, "y": bounding.ylen, "z": bounding.zlen}
    except Exception as exc:
        report.error = "could not measure the solid: %s" % str(exc)[:160]
        return report

    for axis in "xyz":
        key = "extent_%s_mm" % axis
        if key in want:
            expected = float(want[key])
            measured = round(float(extents[axis]), 3)
            report.checks.append(Check(
                kind="extent", name=key, expected=expected, measured=measured,
                tolerance=EXTENT_TOLERANCE_MM,
                passed=abs(measured - expected) <= EXTENT_TOLERANCE_MM,
            ))

    if "extent_any_mm" in want:
        # A request rarely says which way round it means, and guessing invents
        # failures. See verify/intent.py, which reached the same conclusion.
        expected = float(want["extent_any_mm"])
        best = min(extents.values(), key=lambda v: abs(v - expected))
        report.checks.append(Check(
            kind="extent", name="extent_any_mm", expected=expected,
            measured=round(float(best), 3), tolerance=EXTENT_TOLERANCE_MM,
            passed=abs(best - expected) <= EXTENT_TOLERANCE_MM,
            detail="any axis",
        ))

    if "hole_dia_mm" in want:
        expected = float(want["hole_dia_mm"])
        found = _holes_of_diameter(solid, expected, HOLE_TOLERANCE_MM)
        report.checks.append(Check(
            kind="hole", name="hole_dia_mm", expected=expected,
            measured=round(found[0]["diameter_mm"], 3) if found else None,
            tolerance=HOLE_TOLERANCE_MM, passed=bool(found),
            detail="" if found else "no cylindrical face at that diameter",
        ))

        if "hole_count" in want:
            wanted = int(want["hole_count"])
            report.checks.append(Check(
                kind="hole_count", name="hole_count", expected=wanted,
                measured=len(found), tolerance=0, passed=len(found) == wanted,
            ))

        if "hole_spacing_mm" in want and len(found) >= 2:
            expected_gap = float(want["hole_spacing_mm"])
            gaps = []
            for i in range(len(found)):
                for j in range(i + 1, len(found)):
                    a, b = found[i], found[j]
                    gaps.append(((a["x_mm"] - b["x_mm"]) ** 2
                                 + (a["y_mm"] - b["y_mm"]) ** 2
                                 + (a["z_mm"] - b["z_mm"]) ** 2) ** 0.5)
            closest = min(gaps, key=lambda g: abs(g - expected_gap))
            report.checks.append(Check(
                kind="hole_spacing", name="hole_spacing_mm",
                expected=expected_gap, measured=round(closest, 3),
                tolerance=EXTENT_TOLERANCE_MM,
                passed=abs(closest - expected_gap) <= EXTENT_TOLERANCE_MM,
            ))
        elif "hole_spacing_mm" in want:
            report.checks.append(Check(
                kind="hole_spacing", name="hole_spacing_mm",
                expected=float(want["hole_spacing_mm"]), measured=None,
                detail="fewer than two holes of that diameter",
            ))

    if "wall_mm" in want:
        expected = float(want["wall_mm"])
        # The builder's own claim, not a measurement of the geometry. Finding
        # the true minimum wall thickness of an arbitrary solid is a much
        # harder problem and is not pretended at here.
        candidates = [v for k, v in features.items() if "wall" in k.lower()]
        measured = round(float(min(candidates)), 3) if candidates else None
        report.checks.append(Check(
            kind="wall", name="wall_mm", expected=expected, measured=measured,
            tolerance=WALL_TOLERANCE_MM,
            passed=measured is not None and abs(measured - expected) <= WALL_TOLERANCE_MM,
            detail="from the builder's features" if measured is not None
                   else "the builder reported no wall",
        ))

    if "bodies" in want:
        wanted = int(want["bodies"])
        measured = bodies if bodies is not None else len(solid.val().Solids())
        report.checks.append(Check(
            kind="bodies", name="bodies", expected=wanted, measured=measured,
            tolerance=0, passed=measured == wanted,
        ))

    return report
