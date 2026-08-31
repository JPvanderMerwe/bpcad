"""
A round vessel: bowl, dish, plant pot, cup, vase.

WHY THIS EXISTS, WHICH IS A BUG REPORT
---------------------------------------
Asked for a bowl, this program produced a rectangular birdhouse. Not once - as
the reliable answer, every time.

The reason was not the model. The `enclosure` template - which makes a
RECTANGULAR box - claimed the words "pot", "planter", "plant pot", "tub" and
"container" in its `makes` list. A model picking a template matches on words,
found "pot", picked the box, and did exactly what it was told. Every round
thing anybody asked for came out square, and the part passed every check,
because nothing in the pipeline knows what a bowl looks like.

Claiming a word you cannot make is worse than claiming nothing. Falling through
to primitives gives a rough bowl; being confidently handed a box gives a box.

So the round words moved here, and this makes them properly: a revolved profile
with a real wall, a real floor, and a foot.

PRINTING A BOWL
---------------
A bowl is the good case for FDM - the cavity opens upward, which is the print
direction, so there is no ceiling anywhere and no support needed. The only
thing that can go wrong is the OUTSIDE wall leaning out too far as it rises.

A flared bowl is an overhang by definition: the wall moves outward as it goes
up. `wall_angle_deg` is therefore measured from vertical and refused past 45,
because past 45 an FDM printer is extruding onto air. That is not a style
limit, it is the machine, and the number belongs in the validator rather than
in a note somebody reads afterwards.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Literal

import cadquery as cq
from pydantic import Field, model_validator

from bpcad.build.helpers import BuildLog, MIN_FILLET_MM, safe_fillet_radius, try_edge_op
from bpcad.spec.registry import Template, register
from bpcad.spec.schema import TemplateParams

# How many circles the profile is lofted through. Enough that a curved wall
# reads as a curve rather than a stack of cones, and few enough that the
# tessellation stays sane.
STATIONS = 24

# The steepest a wall may lean out from vertical before FDM is printing onto
# air. Not a style choice.
MAX_LEAN_DEG = 45.0


class VesselParams(TemplateParams):
    """A round vessel, revolved about Z, open at the top."""

    outer_dia_mm: float = Field(
        160.0, gt=4.0, le=600.0,
        description="Diameter at the widest point of the body.",
    )
    height_mm: float = Field(
        70.0, gt=2.0, le=600.0, description="Overall height including the foot.",
    )
    wall_mm: float = Field(
        2.4, gt=0.4, le=40.0, description="Wall thickness.",
    )
    floor_mm: float | None = Field(
        None, gt=0.4, le=60.0,
        description="Thickness of the base. Defaults to a little over the wall.",
    )

    profile: Literal["straight", "flared", "belly", "cylinder"] = Field(
        "flared",
        description=(
            "straight is a plain cone. flared opens out towards the rim like a "
            "bowl. belly bulges in the middle and draws back in like a vase. "
            "cylinder is a straight-sided pot."
        ),
    )
    rim_dia_mm: float | None = Field(
        None, gt=2.0, le=600.0,
        description="Diameter at the rim. Derived from the profile if left out.",
    )
    base_dia_mm: float | None = Field(
        None, gt=2.0, le=600.0,
        description="Diameter where it meets the foot. Derived if left out.",
    )

    foot_mm: float = Field(
        0.0, ge=0.0, le=100.0,
        description="Height of a narrower foot ring under the body. 0 for none.",
    )
    foot_dia_mm: float | None = Field(
        None, gt=2.0, le=600.0, description="Foot diameter. Derived if left out.",
    )

    rim_round_mm: float = Field(
        1.2, ge=0.0, le=20.0,
        description="Rounding on the rim edge, so it is not a knife edge.",
    )
    drain_holes: int = Field(
        0, ge=0, le=24,
        description="Holes through the base. A plant pot needs them, a bowl does not.",
    )
    drain_dia_mm: float = Field(
        6.0, gt=0.5, le=60.0, description="Diameter of each drainage hole.",
    )

    # -- derived ------------------------------------------------------------

    @property
    def floor_thickness_mm(self) -> float:
        # A floor the same as the wall is the usual mistake: the base is what
        # the whole thing stands on and what a drill of drainage holes goes
        # through, so it gets a little more.
        return self.floor_mm if self.floor_mm is not None else self.wall_mm * 1.5

    @property
    def body_height_mm(self) -> float:
        return self.height_mm - self.foot_mm

    def rim(self) -> float:
        if self.rim_dia_mm is not None:
            return self.rim_dia_mm
        return {
            "straight": self.outer_dia_mm,
            "cylinder": self.outer_dia_mm,
            "flared": self.outer_dia_mm,
            "belly": self.outer_dia_mm * 0.72,
        }[self.profile]

    def base(self) -> float:
        if self.base_dia_mm is not None:
            return self.base_dia_mm
        return {
            "straight": self.outer_dia_mm * 0.62,
            "cylinder": self.outer_dia_mm,
            "flared": self.outer_dia_mm * 0.52,
            "belly": self.outer_dia_mm * 0.58,
        }[self.profile]

    def foot(self) -> float:
        if self.foot_dia_mm is not None:
            return self.foot_dia_mm
        return max(self.base() * 0.86, 6.0)

    @model_validator(mode="after")
    def _check(self):
        if 2 * self.wall_mm + 2.0 >= min(self.base(), self.rim()):
            raise ValueError(
                "wall_mm %.2f leaves no cavity - two walls is %.2f mm and the "
                "narrowest part of this vessel is %.2f mm across. Legal: "
                "wall_mm under %.2f."
                % (self.wall_mm, 2 * self.wall_mm,
                   min(self.base(), self.rim()), (min(self.base(), self.rim()) - 2.0) / 2)
            )
        if self.floor_thickness_mm >= self.body_height_mm:
            raise ValueError(
                "a %.2f mm floor in a %.2f mm body leaves nothing to hold "
                "anything. Legal: floor_mm under %.2f, or a taller vessel."
                % (self.floor_thickness_mm, self.body_height_mm, self.body_height_mm)
            )

        # THE OVERHANG RULE, AS A NUMBER. A wall that opens outward as it rises
        # is extruding onto air past 45 degrees from vertical. Refused here
        # rather than reported afterwards, because "your bowl needs supports
        # inside it" is not something anyone can act on.
        lean = self.worst_lean_deg()
        if lean > MAX_LEAN_DEG:
            raise ValueError(
                "this profile leans %.1f degrees out from vertical, and past "
                "%.0f an FDM printer is extruding onto air - the outside of "
                "the bowl would need supports. Legal: a taller vessel, a "
                "smaller rim_dia_mm, or a larger base_dia_mm."
                % (lean, MAX_LEAN_DEG)
            )

        if self.drain_holes and self.drain_dia_mm >= self.foot() * 0.6:
            raise ValueError(
                "%d holes of %.1f mm will not fit in a %.1f mm base. Legal: "
                "drain_dia_mm under %.1f."
                % (self.drain_holes, self.drain_dia_mm, self.foot(),
                   self.foot() * 0.6)
            )
        return self

    def worst_lean_deg(self) -> float:
        """Steepest outward lean of the outer wall, in degrees from vertical."""
        pts = _outer_profile(self)
        worst = 0.0
        for (r0, z0), (r1, z1) in zip(pts, pts[1:]):
            if r1 <= r0 or z1 <= z0:
                continue                     # going in, or going nowhere
            worst = max(worst, math.degrees(math.atan2(r1 - r0, z1 - z0)))
        return worst


def _outer_profile(p: VesselParams) -> list[tuple[float, float]]:
    """
    (radius, z) stations up the outside of the body, foot excluded.

    The curve is a plain quadratic through base, waist and rim. Nothing here
    needs a spline: three controlled radii and a smooth interpolation is what
    a thrown pot is, and it keeps the lean angle something that can be
    calculated rather than sampled and hoped about.
    """
    base_r, rim_r = p.base() / 2.0, p.rim() / 2.0
    wide_r = p.outer_dia_mm / 2.0
    h = p.body_height_mm
    z0 = p.foot_mm

    # A STRAIGHT PROFILE NEEDS TWO STATIONS, NOT TWENTY-FIVE. Lofting a cone
    # through 25 evenly spaced circles builds 24 bands of one identical cone,
    # which is slower, heavier, and the thing that made the shape upgrader
    # fall over. Curves need the stations; straight lines do not.
    steps = 1 if p.profile in ("straight", "cylinder") else STATIONS

    out = []
    for i in range(steps + 1):
        t = i / steps
        if p.profile == "cylinder":
            r = base_r + (rim_r - base_r) * t
        elif p.profile == "straight":
            r = base_r + (rim_r - base_r) * t
        elif p.profile == "flared":
            # Opens out, fastest low down, easing towards the rim.
            r = base_r + (rim_r - base_r) * math.sin(t * math.pi / 2.0)
        else:                                 # belly
            # Quadratic Bezier: base -> widest at the waist -> rim.
            r = ((1 - t) ** 2 * base_r + 2 * (1 - t) * t * wide_r + t ** 2 * rim_r)
        out.append((max(r, 0.4), z0 + h * t))
    return out


def _radius_at(stations: list[tuple[float, float]], z: float) -> float:
    """The outer radius at a height, interpolated between the stations."""
    if z <= stations[0][1]:
        return stations[0][0]
    if z >= stations[-1][1]:
        return stations[-1][0]
    for (r0, z0), (r1, z1) in zip(stations, stations[1:]):
        if z0 <= z <= z1:
            if z1 == z0:
                return r1
            return r0 + (r1 - r0) * (z - z0) / (z1 - z0)
    return stations[-1][0]


def _loft_circles(stations: list[tuple[float, float]]) -> cq.Workplane:
    """
    A solid of revolution through a list of (radius, z) circles.

    RULED, NOT SPLINED. `loft(ruled=False)` fits a B-spline surface through the
    sections, and a B-spline is punishing to tessellate: the same bowl came out
    at 157 910 triangles against 28 472 ruled, took ten times as long to build
    and twenty times as long to export, and the volumes differ by 0.02%. With
    fewer sections it got WORSE rather than better - 16 sections splined is
    444 558 triangles, because the fit through fewer points is a wilder surface.

    Ruled is a stack of conical bands. At 24 stations up a 70 mm bowl each band
    is under 3 mm tall and the flats are far below anything a 0.4 mm nozzle can
    express. There is no visible or measurable difference, and it is the
    difference between a bowl that builds in a second and one that does not.
    """
    wp = cq.Workplane("XY")
    last_z = 0.0
    for i, (r, z) in enumerate(stations):
        wp = wp.workplane(offset=z - last_z) if i else wp.workplane(offset=z)
        wp = wp.circle(r)
        last_z = z
    # clean=False. `clean()` runs a shape upgrader that merges coplanar
    # faces, and a straight-sided pot is 24 ruled bands that are all the SAME
    # cone - so the upgrader tries to sew them into one face and dies with
    # "Courbes non jointives". Nothing here needs the merge: the faces are
    # already a closed solid and the exporter does not care how many there are.
    return wp.loft(ruled=True, clean=False)


def build_core(p: VesselParams, log: BuildLog) -> cq.Workplane:
    """The vessel, upright, open at the top. Print and assembled are the same."""
    outer_stations = _outer_profile(p)
    body = _loft_circles(outer_stations)

    if p.foot_mm > 0:
        foot = (
            cq.Workplane("XY")
            .circle(p.foot() / 2.0)
            .extrude(p.foot_mm + 0.01)
        )
        body = body.union(foot)

    # THE CAVITY IS SAMPLED, NOT FILTERED.
    #
    # It used to be built by dropping the outer stations that fell below the
    # floor. That works while there are 25 of them and is silently fatal when
    # there are two: a straight-sided pot has stations only at its base and its
    # rim, the base one sits under the floor, one station is left, and the
    # "if len(inner) >= 2" guard skipped the cut entirely. The pot came out
    # SOLID - 502.5 cm3 for a 80 x 100 mm pen pot, which is exactly pi r^2 h -
    # and it was watertight, one body, and reported PASS.
    #
    # Sampling the outer radius at heights of the cavity's own choosing has no
    # such dependency on how the outside happened to be divided up.
    floor_t = p.floor_thickness_mm
    z_bottom = p.foot_mm + floor_t
    z_top = p.height_mm + 1.0
    steps = 1 if p.profile in ("straight", "cylinder") else STATIONS

    inner: list[tuple[float, float]] = []
    for i in range(steps + 1):
        z = z_bottom + (z_top - z_bottom) * i / steps
        r = _radius_at(outer_stations, min(z, p.height_mm)) - p.wall_mm
        inner.append((max(r, 0.3), z))
    body = body.cut(_loft_circles(inner))

    for cutter in _drains(p):
        body = body.cut(cutter)

    if p.rim_round_mm > MIN_FILLET_MM:
        r = safe_fillet_radius(p.rim_round_mm, p.wall_mm)
        body = try_edge_op(body, ">Z", "fillet", r, "rim", log)

    return body


def _drains(p: VesselParams) -> list[cq.Workplane]:
    """Drainage holes through the base, in a ring, plus one in the middle."""
    if not p.drain_holes:
        return []
    out = []
    through = p.foot_mm + p.floor_thickness_mm + 2.0
    ring_r = max(p.foot() / 2.0 - p.drain_dia_mm, 0.0)
    count = p.drain_holes
    if ring_r < p.drain_dia_mm:
        # Too small for a ring - one hole in the middle is the honest answer.
        return [cq.Workplane("XY", origin=(0, 0, -1.0))
                .circle(p.drain_dia_mm / 2.0).extrude(through)]
    for i in range(count):
        a = 2 * math.pi * i / count
        out.append(
            cq.Workplane("XY", origin=(ring_r * math.cos(a), ring_r * math.sin(a), -1.0))
            .circle(p.drain_dia_mm / 2.0)
            .extrude(through)
        )
    return out


def build(params: VesselParams, spec, base_dir: Path | None = None):
    """Template entry point."""
    from bpcad.build.helpers import BuildResult

    log = BuildLog()
    core = build_core(params, log)

    features = {
        "wall": params.wall_mm,
        "floor": params.floor_thickness_mm,
    }
    if params.drain_holes:
        features["drain hole"] = params.drain_dia_mm
    if params.rim_round_mm:
        features["rim round"] = params.rim_round_mm

    log.notes.append(
        "outer wall leans %.1f degrees from vertical at its steepest (%.0f is "
        "the limit for printing without support)"
        % (params.worst_lean_deg(), MAX_LEAN_DEG)
    )

    return BuildResult(
        # A vessel prints the way it sits. There is no second orientation to
        # get wrong, so both are the same object rather than one derived from
        # the other by a rotation nobody checked.
        solid=core,
        print_solid=core,
        features=features,
        log=log,
        derived={
            "rim_dia_mm": params.rim(),
            "base_dia_mm": params.base(),
            "foot_dia_mm": params.foot(),
            "worst_lean_deg": params.worst_lean_deg(),
        },
        body_count_expected=1,
        nominal_mm=(params.outer_dia_mm, params.outer_dia_mm, params.height_mm),
    )


register(Template(
    name="vessel",
    summary=(
        "A ROUND vessel turned about its axis - bowl, dish, plant pot, cup or "
        "vase. Open at the top, with a real wall, a floor and an optional foot. "
        "Use this whenever the thing is round. The enclosure template is "
        "rectangular and will make a square box out of a bowl."
    ),
    makes=(
        "bowl", "dish", "round bowl", "serving bowl", "fruit bowl", "cup",
        "mug body", "beaker", "tumbler", "pot", "plant pot", "planter",
        "flower pot", "vase", "jar", "canister", "tub", "basin",
        # "container" is shared with the rectangular enclosure on purpose: it
        # is not a shape word. "bin" is not here - a bin is usually square.
        "container", "round container", "pen pot", "pencil pot", "utensil pot",
        "ramekin",
        "trinket dish", "catch-all", "saucer", "plate", "tray round",
    ),
    params_model=VesselParams,
    builder=build,
    anchors=("rim", "base", "outside"),
    print_notes=(
        "Orientation: standing upright, exactly as modelled. The cavity opens "
        "upward, so there is nothing to support.",
        "No supports. If the profile needed them the spec would have been "
        "refused - the wall lean is checked against 45 degrees.",
        "Vase mode / spiralised outer contour suits this well if the wall is a "
        "single extrusion wide and there are no drainage holes.",
        "PETG for anything that holds water. PLA is fine dry and will soften "
        "in a hot car or a dishwasher.",
        "3 walls minimum. On a thin turned wall the walls ARE the part.",
    ),
))
