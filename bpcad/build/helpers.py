"""
CadQuery helpers, and the hard-won rules baked in at the exact site each one
applies.

Every rule in here is a real bug that cost real debugging time. Read the
comments before changing anything: the obvious simplification is usually the
thing that was tried first and broke.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import cadquery as cq

# A fillet radius must clear half the smallest dimension by a REAL margin, not
# an epsilon. h/2 - 0.001 produces degenerate faces or a hard OCC failure; the
# geometry is valid on paper and unbuildable in practice.
FILLET_MARGIN_MM = 0.03

# Below this a fillet is not worth attempting - it costs a boolean and buys a
# feature no printer resolves.
MIN_FILLET_MM = 0.05


@dataclass
class EdgeOpRecord:
    """What happened to one cosmetic edge operation. Ends up in the report."""

    label: str
    kind: str
    amount_mm: float
    applied: bool
    reason: str = ""

    def __str__(self) -> str:
        if self.applied:
            return "%-24s %s %.2f mm" % (self.label, self.kind, self.amount_mm)
        return "%-24s SKIPPED, %s" % (self.label, self.reason)


@dataclass
class BuildLog:
    """Collects edge-op outcomes so a build can report what it actually did."""

    edge_ops: list[EdgeOpRecord] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def lines(self) -> list[str]:
        return [str(r) for r in self.edge_ops] + list(self.notes)


@dataclass
class BuildResult:
    """
    What every template and every level-2 composition returns.

    `features` is the contract that makes verify/features.py generic: a dict of
    named sizes in mm. The linter never has to know what the part is - hand it
    {"glass side bezel": 0.40, "logo stroke": 0.45} and it will tell you which
    ones an FDM printer cannot resolve.

    `solid` and `print_solid` are separate on purpose. Deriving one from the
    other by rotation once put a part 1.2 mm off its mating face.
    """

    solid: "cq.Workplane"
    print_solid: "cq.Workplane"
    features: dict[str, float] = field(default_factory=dict)
    log: BuildLog = field(default_factory=BuildLog)
    assumptions: list = field(default_factory=list)
    scale_departures: list = field(default_factory=list)
    derived: dict[str, float] = field(default_factory=dict)
    body_count_expected: int = 1

    # The part's NOMINAL size, when the template knows it: the numbers a person
    # would quote if asked how big it is. Neither bounding box answers that. The
    # enclosure's print layout is 288 mm wide because the roof lies beside the
    # box, and its assembled envelope is 160 because the roof overhangs - while
    # the birdhouse itself is 120. Only the template can say which is meant.
    nominal_mm: tuple[float, float, float] | None = None

    # What each separate body IS, in print order: ("box", "roof"). A
    # multi-material printer wants one object per filament, so these become
    # separate STLs and a filament assignment in the report. A name is worth
    # far more than a colour here - "roof" tells you which one to load in the
    # second colour; a hex value does not.
    body_roles: tuple[str, ...] = ()


def safe_fillet_radius(requested: float, *dimensions: float) -> float:
    """
    Clamp a fillet radius to something OCC will actually build.

    The clamp is half the smallest dimension MINUS FILLET_MARGIN_MM. An epsilon
    is not enough - see the constant.
    """
    limit = min(dimensions) / 2.0 - FILLET_MARGIN_MM if dimensions else requested
    return min(requested, limit)


def probe(solid: cq.Workplane) -> bool:
    """
    Real usability test for a solid.

    Shape.isValid() is NOT sufficient. A chamfer once produced a solid that
    reported valid and then broke every subsequent boolean, silently, three
    operations later. The only trustworthy check is to attempt a real boolean
    and see whether OCC copes, so this cuts a throwaway sliver well outside the
    part and asks for the volume back.
    """
    try:
        bb = solid.val().BoundingBox()
        far = max(abs(bb.xmax), abs(bb.xmin), 1.0) * 3.0 + 10.0
        test = solid.cut(cq.Workplane("XY", origin=(far, 0, 0)).box(1, 1, 1))
        test.val().Volume()
        return True
    except Exception:
        return False


def try_edge_op(
    solid: cq.Workplane,
    selector: str,
    kind: str,
    amount: float,
    label: str,
    log: BuildLog | None = None,
) -> cq.Workplane:
    """
    Apply a fillet or chamfer, and revert it if it corrupts the solid.

    Fillets and chamfers on complex unions fail often and fail badly. A
    cosmetic edge operation must never be able to break a build, so this is
    always attempt-and-revert, and the outcome is always recorded rather than
    swallowed.

    Apply these LAST, after every pocket is cut. A failure partway through then
    cannot corrupt detail that was already there.
    """
    if amount <= 0:
        # Not requested. Recorded rather than silently absent, so the report
        # distinguishes "turned off" from "attempted and failed".
        if log is not None:
            log.edge_ops.append(EdgeOpRecord(
                label=label, kind=kind, amount_mm=0.0, applied=False,
                reason="not requested (amount is 0)",
            ))
        return solid

    record = EdgeOpRecord(label=label, kind=kind, amount_mm=amount, applied=False)
    try:
        out = getattr(solid.edges(selector), kind)(amount)
        if out.val().isValid() and probe(out) and out.val().Volume() > 0:
            record.applied = True
        else:
            record.reason = "%s corrupted the solid" % kind
    except Exception:
        out = solid
        record.reason = "OCC rejected it"

    if log is not None:
        log.edge_ops.append(record)
    return out if record.applied else solid


def rrect(
    w: float,
    h: float,
    r: float,
    y0: float,
    t: float,
    z0: float = 0.0,
) -> cq.Workplane:
    """
    Rounded rectangle, centred in X, spanning y0..y0+h and z0..z0+t.

    The radius is clamped by safe_fillet_radius, so a caller asking for
    something impossible gets the largest radius that works rather than a
    crash.
    """
    s = cq.Workplane("XY").box(w, h, t, centered=(True, True, False))
    r = safe_fillet_radius(r, w, h)
    if r > MIN_FILLET_MM:
        s = s.edges("|Z").fillet(r)
    return s.translate((0, y0 + h / 2.0, z0))


def disc(d: float, cx: float, cy: float, t: float, z0: float = 0.0) -> cq.Workplane:
    """Cylinder of diameter d, axis at (cx, cy), spanning z0..z0+t."""
    return cq.Workplane("XY", origin=(cx, cy, z0)).circle(d / 2.0).extrude(t)


def poly_prism(
    pts, scale: float, ox: float, oy: float, z0: float, t: float
) -> cq.Workplane:
    """
    Closed polygon in normalised coordinates, extruded into a prism.

    `pts` are (x, y) with the polygon's own scale; `scale` maps them to mm and
    (ox, oy) places them. This is what turns a traced logo outline into
    geometry.
    """
    pts = list(pts)
    if len(pts) < 3:
        raise ValueError("a prism needs at least 3 points, got %d" % len(pts))
    wp = cq.Workplane("XY", origin=(0, 0, z0))
    wp = wp.moveTo(ox + pts[0][0] * scale, oy + pts[0][1] * scale)
    for x, y in pts[1:]:
        wp = wp.lineTo(ox + x * scale, oy + y * scale)
    return wp.close().extrude(t)


def clip(solid: cq.Workplane, axis: str, limit: float, keep: str = "below") -> cq.Workplane:
    """
    Trim a solid to one side of an axis-aligned plane.

    Used to square off rounded corners at one end of a profile: fillet all four
    corners, push the square end beyond the region of interest, and let the
    boolean take the unwanted fillets away. Trying to fillet only two corners
    of a rectangle is the version that does not work.

    The cutting box is sized and positioned from the SOLID'S bounding box, not
    from the origin. A box centred on the origin silently fails to reach a
    solid that is not centred there - the module pocket sits at z 6.45 to 7.45
    and an origin-centred box of the same extent covers z -3.1 to 3.1, so the
    intersect returns nothing and the pocket vanishes without an error.
    """
    if axis not in "xyz":
        raise ValueError("axis must be x, y or z, got %r" % axis)
    if keep not in ("below", "above"):
        raise ValueError("keep must be 'below' or 'above', got %r" % keep)

    bb = solid.val().BoundingBox()
    pad = max(bb.xlen, bb.ylen, bb.zlen, 1.0) * 2.0 + 10.0
    size = [bb.xlen + 2 * pad, bb.ylen + 2 * pad, bb.zlen + 2 * pad]
    centre = [
        (bb.xmin + bb.xmax) / 2.0,
        (bb.ymin + bb.ymax) / 2.0,
        (bb.zmin + bb.zmax) / 2.0,
    ]

    i = "xyz".index(axis)
    half = size[i] / 2.0
    centre[i] = (limit - half) if keep == "below" else (limit + half)

    box = cq.Workplane("XY").box(*size, centered=(True, True, True))
    return solid.intersect(box.translate(tuple(centre)))


def clip_y(solid: cq.Workplane, y_max: float) -> cq.Workplane:
    """Trim a solid to y <= y_max. The reference's shorthand, kept by name."""
    return clip(solid, "y", y_max, keep="below")


def revolve_about_axis(
    profile: cq.Workplane,
    angle: float,
    axis_start: tuple[float, float, float],
    axis_end: tuple[float, float, float],
) -> cq.Workplane:
    """
    Revolve, with the trap spelled out.

    Workplane.revolve(angle, axisStart, axisEnd) takes the axis in the
    WORKPLANE'S LOCAL coordinates. Calling .center(x, y) first moves the local
    origin onto the profile, which puts the axis through the profile and makes
    the revolve fail. Use .moveTo(x, y) instead so the origin stays on the
    axis. This wrapper exists so that sentence is in front of you at the call
    site.
    """
    return profile.revolve(angle, axis_start, axis_end)


def compound_of(parts: list[cq.Workplane]) -> cq.Workplane:
    """
    Combine deliberately disjoint bodies into a compound, NOT a union.

    A print-in-place mechanism's bodies are separated by design - 0.30 mm of
    air at every shoulder. union() is semantically wrong for that and
    numerically fragile: it intermittently fused parts that were 0.3 mm apart,
    turning a working linkage into one welded lump.
    """
    solids = []
    for p in parts:
        solids.extend(p.val().Solids())
    return cq.Workplane("XY").newObject([cq.Compound.makeCompound(solids)])
