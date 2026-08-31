"""
Bracket: an L of two plates, with a gusset and fixing holes.

WHY THIS ONE
------------
It is the commonest functional print there is - a shelf bracket, a monitor arm
mount, a cable-tray hanger, a corner brace - and every one of them is the same
object with different numbers. Without it a request for a bracket falls through
to composing primitives, which produces something bracket-shaped and
structurally wrong.

WHERE A BRACKET FAILS, AND WHAT THAT MEANS HERE
-----------------------------------------------
A printed bracket breaks at the inside corner, along a layer line, because that
is where the bending moment is highest and where FDM is weakest. So:

  * the corner gets a fillet, not a sharp angle - a sharp internal corner is a
    stress raiser and a crack starter
  * it gets a gusset by default, because the gusset carries the moment into the
    wall plate instead of the corner
  * it prints STANDING ON ITS BACK EDGE, so the layers run across the load
    rather than along the crack. Printed flat it is roughly a third as strong,
    and that orientation is the single biggest thing separating a bracket that
    holds a shelf from one that snaps.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import cadquery as cq
from pydantic import Field, model_validator

from bpcad.build.helpers import BuildLog, MIN_FILLET_MM, safe_fillet_radius, try_edge_op
from bpcad.spec.registry import Template, register
from bpcad.spec.schema import TemplateParams


class BracketParams(TemplateParams):
    """Every dimension carries its unit in the name."""

    # --- the two plates ---------------------------------------------------
    wall_length_mm: float = Field(
        80.0, gt=10.0, le=400.0,
        description="Length of the plate that goes against the wall, up the wall.",
    )
    shelf_length_mm: float = Field(
        80.0, gt=10.0, le=400.0,
        description="Length of the plate that sticks out, carrying the load.",
    )
    width_mm: float = Field(
        30.0, gt=5.0, le=300.0, description="How wide the bracket is."
    )
    thickness_mm: float = Field(
        6.0, gt=1.0, le=40.0,
        description=(
            "Plate thickness. 6 mm in PETG carries a shelf; below 4 it flexes "
            "and the fixings pull through."
        ),
    )
    corner_r_mm: float | None = Field(
        None, ge=0.0, le=100.0,
        description=(
            "Fillet on the inside corner. Leave unset for 1.5 x thickness, "
            "which is where the stress raiser stops mattering."
        ),
    )

    # --- the gusset -------------------------------------------------------
    gusset: bool = Field(
        True,
        description=(
            "A triangular web across the corner. It carries the bending moment "
            "into the wall plate instead of the corner, and it is why a printed "
            "bracket holds."
        ),
    )
    gusset_thickness_mm: float | None = Field(
        None, gt=0.4, le=40.0,
        description="Gusset thickness. Leave unset to match the plates.",
    )
    gusset_fraction: float = Field(
        0.7, gt=0.1, le=1.0,
        description="How far along each plate the gusset reaches, as a fraction.",
    )

    # --- fixings ----------------------------------------------------------
    wall_holes: int = Field(2, ge=0, le=8, description="Fixing holes in the wall plate.")
    shelf_holes: int = Field(2, ge=0, le=8, description="Fixing holes in the shelf plate.")
    hole_dia_mm: float = Field(
        5.5, gt=1.0, le=30.0,
        description="Fixing hole diameter. 5.5 clears an M5; 4.5 an M4.",
    )
    counterbore_mm: float = Field(
        0.0, ge=0.0, le=30.0,
        description=(
            "Counterbore depth for a screw head to sit flush. 0 for none. The "
            "bore is on the OUTSIDE face, so it prints as a plain step."
        ),
    )
    edge_margin_mm: float | None = Field(
        None, gt=1.0, le=100.0,
        description=(
            "Distance from a hole centre to the plate edge. Leave unset for "
            "1.4 x the hole diameter, below which the material tears out."
        ),
    )

    # ---- derived ---------------------------------------------------------

    @property
    def corner_radius_mm(self) -> float:
        if self.corner_r_mm is not None:
            return self.corner_r_mm
        return self.thickness_mm * 1.5

    @property
    def gusset_t_mm(self) -> float:
        return (self.gusset_thickness_mm
                if self.gusset_thickness_mm is not None else self.thickness_mm)

    @property
    def margin_mm(self) -> float:
        if self.edge_margin_mm is not None:
            return self.edge_margin_mm
        return self.hole_dia_mm * 1.4

    @model_validator(mode="after")
    def _buildable(self) -> "BracketParams":
        if self.hole_dia_mm + 2 * self.margin_mm > self.width_mm:
            raise ValueError(
                "a %.1f mm hole with %.1f mm of margin needs a plate at least "
                "%.1f mm wide, and this one is %.1f. Legal: widen width_mm, or "
                "use a smaller hole_dia_mm."
                % (self.hole_dia_mm, self.margin_mm,
                   self.hole_dia_mm + 2 * self.margin_mm, self.width_mm)
            )

        for name, length, count in (("wall", self.wall_length_mm, self.wall_holes),
                                    ("shelf", self.shelf_length_mm, self.shelf_holes)):
            if not count:
                continue
            need = self.thickness_mm + self.margin_mm * (2 * count)
            if need > length:
                raise ValueError(
                    "%d holes do not fit along a %.0f mm %s plate with %.1f mm "
                    "margins - it needs %.0f mm. Legal: fewer holes, a longer "
                    "plate, or a smaller edge_margin_mm."
                    % (count, length, name, self.margin_mm, need)
                )

        if self.counterbore_mm >= self.thickness_mm:
            raise ValueError(
                "a %.1f mm counterbore goes straight through a %.1f mm plate. "
                "Legal: under %.1f mm."
                % (self.counterbore_mm, self.thickness_mm, self.thickness_mm)
            )

        if self.corner_radius_mm > min(self.wall_length_mm, self.shelf_length_mm) / 2:
            raise ValueError(
                "a %.1f mm corner fillet is more than half the shorter plate "
                "(%.0f mm). Legal: reduce corner_r_mm."
                % (self.corner_radius_mm, min(self.wall_length_mm, self.shelf_length_mm))
            )
        return self


@dataclass
class _Derived:
    corner_r: float
    gusset_t: float
    margin: float
    gusset_wall: float
    gusset_shelf: float


def derive(p: BracketParams) -> _Derived:
    return _Derived(
        corner_r=p.corner_radius_mm,
        gusset_t=p.gusset_t_mm,
        margin=p.margin_mm,
        gusset_wall=(p.wall_length_mm - p.thickness_mm) * p.gusset_fraction,
        gusset_shelf=(p.shelf_length_mm - p.thickness_mm) * p.gusset_fraction,
    )


def _hole_positions(length: float, thickness: float, count: int,
                    margin: float) -> list[float]:
    """
    Where the holes go along a plate, measured from the inside corner.

    Evenly spaced between the corner and the far end, both ends kept clear by
    the margin - a hole too near an edge tears out under load, which is how a
    bracket fails second most often after the corner.
    """
    if count <= 0:
        return []
    lo = thickness + margin
    hi = length - margin
    if hi <= lo:
        return []
    if count == 1:
        return [(lo + hi) / 2.0]
    step = (hi - lo) / (count - 1)
    return [lo + i * step for i in range(count)]


def build_core(p: BracketParams, d: _Derived, log: BuildLog) -> cq.Workplane:
    """
    ASSEMBLED orientation: wall plate in the YZ plane at x=0, shelf along +X.

    Built as one solid rather than two plates unioned, so the corner is
    continuous material and the fillet has something to bite on.
    """
    # The L, as a profile in XZ swept across the width.
    profile = (
        cq.Workplane("XZ")
        .moveTo(0, 0)
        .lineTo(p.shelf_length_mm, 0)
        .lineTo(p.shelf_length_mm, p.thickness_mm)
        .lineTo(p.thickness_mm, p.thickness_mm)
        .lineTo(p.thickness_mm, p.wall_length_mm)
        .lineTo(0, p.wall_length_mm)
        .close()
        .extrude(p.width_mm)
        # An XZ workplane extrudes along -Y, so the solid spans -width..0 and
        # centring it means moving it POSITIVE by half the width. Translating
        # negative - which reads correct - put the plate and the gusset in
        # different places, and the part came out as two loose bodies.
        .translate((0, p.width_mm / 2.0, 0))
    )

    # The inside corner is where it breaks. A sharp internal corner is a stress
    # raiser; this is the single most load-bearing fillet on the part, so it is
    # not left to the cosmetic attempt-and-revert pass at the end.
    if d.corner_r > MIN_FILLET_MM:
        try:
            profile = (
                profile.edges("|Y")
                .edges(cq.selectors.NearestToPointSelector(
                    (p.thickness_mm, 0, p.thickness_mm)))
                .fillet(d.corner_r)
            )
            log.notes.append(
                "inside corner filleted %.1f mm - a sharp internal corner is a "
                "stress raiser and where a printed bracket cracks" % d.corner_r
            )
        except Exception:
            log.notes.append(
                "the inside corner fillet was refused by the kernel - the part "
                "is sound but weaker at the corner than intended"
            )

    if p.gusset:
        profile = profile.union(_gusset(p, d))

    for cutter in _holes(p, d):
        profile = profile.cut(cutter)

    profile = try_edge_op(profile, "|Y", "fillet",
                          min(p.thickness_mm * 0.25, 2.0), "outer edges", log)
    return profile


def _gusset(p: BracketParams, d: _Derived) -> cq.Workplane:
    """A triangular web across the corner, centred on the width."""
    return (
        cq.Workplane("XZ")
        .moveTo(p.thickness_mm, p.thickness_mm)
        .lineTo(p.thickness_mm + d.gusset_shelf, p.thickness_mm)
        .lineTo(p.thickness_mm, p.thickness_mm + d.gusset_wall)
        .close()
        .extrude(d.gusset_t)
        .translate((0, d.gusset_t / 2.0, 0))     # see build_core on the sign
    )


def _holes(p: BracketParams, d: _Derived):
    """Fixing holes through both plates, with optional counterbores."""
    out = []
    through = max(p.thickness_mm, p.counterbore_mm) + 4.0

    # Wall plate: bores run along +X, through a plate lying in YZ.
    for z in _hole_positions(p.wall_length_mm, p.thickness_mm, p.wall_holes, d.margin):
        out.append(
            cq.Workplane("YZ", origin=(-2.0, 0, z))
            .circle(p.hole_dia_mm / 2.0).extrude(through)
        )
        if p.counterbore_mm > 0:
            out.append(
                cq.Workplane("YZ", origin=(-2.0, 0, z))
                .circle(p.hole_dia_mm)
                .extrude(p.counterbore_mm + 2.0)
            )

    # Shelf plate: bores run along +Z, through a plate lying in XY.
    for x in _hole_positions(p.shelf_length_mm, p.thickness_mm, p.shelf_holes, d.margin):
        out.append(
            cq.Workplane("XY", origin=(x, 0, -2.0))
            .circle(p.hole_dia_mm / 2.0).extrude(through)
        )
        if p.counterbore_mm > 0:
            out.append(
                cq.Workplane("XY", origin=(x, 0, p.thickness_mm - p.counterbore_mm))
                .circle(p.hole_dia_mm).extrude(p.counterbore_mm + 2.0)
            )
    return out


def build_print(p: BracketParams, d: _Derived, log: BuildLog) -> cq.Workplane:
    """
    PRINT orientation: standing on its back edge, layers across the load.

    THIS IS THE WHOLE STRENGTH OF THE PART. Printed flat, the layer lines run
    along the crack that opens at the inside corner and the bracket is roughly a
    third as strong. Standing it on the back edge of the wall plate puts the
    layers across the bending load and gives a flat face on the bed with no
    support.

    Never derived from the assembled model by an arbitrary rotation - that
    mistake is what this project keeps a rule about - but the rotation IS the
    orientation change here, so it is done deliberately and named.
    """
    # A fresh log: build_core is run twice, once for each orientation, and
    # letting both write to the caller's log duplicates every note it makes.
    core = build_core(p, d, BuildLog())
    standing = core.rotate((0, 0, 0), (0, 1, 0), -90)
    bb = standing.val().BoundingBox()
    return standing.translate((-bb.xmin, 0, -bb.zmin))


def build(params: BracketParams, spec, base_dir: Path | None = None):
    """Template entry point."""
    from bpcad.build.helpers import BuildResult
    from bpcad.spec.schema import Assumption

    d = derive(params)
    log = BuildLog()
    core = build_core(params, d, log)
    printed = build_print(params, d, log)

    features = {
        "plate thickness": params.thickness_mm,
        "corner fillet": d.corner_r,
        "hole edge margin": d.margin,
    }
    if params.gusset:
        features["gusset thickness"] = d.gusset_t

    assumptions = []
    if params.corner_r_mm is None:
        assumptions.append(Assumption(
            name="corner_r_mm", value=round(d.corner_r, 2), units="mm",
            why=(
                "Not stated, so it is 1.5 x the plate thickness - enough that "
                "the internal corner stops acting as a stress raiser. This is "
                "where a printed bracket cracks, so it is worth setting "
                "deliberately if the load is known."
            ),
        ))
    if params.edge_margin_mm is None:
        assumptions.append(Assumption(
            name="edge_margin_mm", value=round(d.margin, 2), units="mm",
            why=(
                "Not stated, so it is 1.4 x the hole diameter. Below that the "
                "material between the hole and the edge tears out under load."
            ),
        ))

    log.notes.append(
        "prints standing on its back edge so the layers run ACROSS the bending "
        "load - printed flat this part is roughly a third as strong"
    )

    return BuildResult(
        solid=core,
        print_solid=printed,
        features=features,
        log=log,
        assumptions=assumptions,
        scale_departures=[],
        derived={
            "corner_fillet_mm": d.corner_r,
            "gusset_reach_wall_mm": d.gusset_wall if params.gusset else 0.0,
            "gusset_reach_shelf_mm": d.gusset_shelf if params.gusset else 0.0,
            "hole_margin_mm": d.margin,
        },
        body_count_expected=1,
        nominal_mm=(params.shelf_length_mm, params.width_mm, params.wall_length_mm),
    )


register(Template(
    name="bracket",
    summary=(
        "An L of two plates with a gusset across the corner and fixing holes. "
        "Prints standing on its back edge so the layers run across the load."
    ),
    makes=(
        "bracket", "shelf bracket", "l bracket", "angle bracket", "corner brace",
        "gusset", "support", "mount", "wall mount", "shelf support",
        "monitor mount", "hanger", "cable tray bracket", "batten",
    ),
    params_model=BracketParams,
    builder=build,
    anchors=("wall_face", "shelf_face", "corner"),
    print_notes=(
        "Orientation: standing on the back edge of the wall plate. DO NOT "
        "ROTATE - printed flat this is about a third as strong.",
        "No supports needed in that orientation.",
        "PETG or ABS. PLA creeps under a sustained load and the shelf droops.",
        "4 walls and 40% infill. On a bracket the walls carry the load, so wall "
        "count matters far more than infill density.",
        "Layer 0.2 mm. Finer does not make it stronger.",
    ),
))
