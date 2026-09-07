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

    profile: Literal["straight", "flared", "belly", "cylinder", "custom"] = Field(
        "flared",
        description=(
            "straight is a plain cone. flared opens out towards the rim like a "
            "bowl. belly bulges in the middle and draws back in like a vase. "
            "cylinder is a straight-sided pot. custom takes the silhouette "
            "from profile_points, which is how a shape MEASURED off a mesh "
            "becomes an editable part."
        ),
    )
    profile_points: list[tuple[float, float]] | None = Field(
        None, min_length=3, max_length=400,
        description=(
            "The silhouette as (radius_mm, height_mm) pairs from the base up. "
            "Only used when profile is custom. This is what a generated mesh "
            "turns into: measured off the surface, then editable like any "
            "other number."
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

    # --- cellular shell ----------------------------------------------------
    # The Voronoi web. See bpcad/build/cells.py for what this is and, more
    # importantly, what it is not: it reaches the visual language of a grown
    # cellular piece, and it is not a growth simulation.
    pattern: Literal["solid", "cells"] = Field(
        "solid",
        description=(
            "solid is a plain wall. cells cuts a Voronoi web through it, "
            "leaving a strut between every pair of holes."
        ),
    )
    cell_count: int = Field(
        110, ge=8, le=600,
        description="How many cells around and up the wall. More means finer.",
    )
    strut_mm: float = Field(
        3.0, gt=0.4, le=30.0,
        description="Width of the web between two holes. This is the part that carries the load.",
    )
    cell_seed: int = Field(
        7, ge=0, le=10_000_000,
        description=(
            "Which arrangement of cells. Change it for a different pattern of "
            "the same character. The same seed always gives the same bowl."
        ),
    )
    rim_band_mm: float = Field(
        7.0, ge=0.0, le=200.0,
        description="Solid band left under the rim. The rim is what holds the whole thing round.",
    )
    base_band_mm: float = Field(
        6.0, ge=0.0, le=200.0,
        description="Solid band left above the floor, so the base is not perforated.",
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
        if self.profile == "custom" and self.profile_points:
            return self.profile_points[-1][0] * 2.0
        return {
            "straight": self.outer_dia_mm,
            "cylinder": self.outer_dia_mm,
            "flared": self.outer_dia_mm,
            "belly": self.outer_dia_mm * 0.72,
        }[self.profile]

    def base(self) -> float:
        if self.base_dia_mm is not None:
            return self.base_dia_mm
        if self.profile == "custom" and self.profile_points:
            return self.profile_points[0][0] * 2.0
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
        if self.profile == "custom":
            if not self.profile_points:
                raise ValueError(
                    "profile is custom but profile_points is empty. Legal: give "
                    "the silhouette as (radius_mm, height_mm) pairs, or pick one "
                    "of straight, flared, belly, cylinder."
                )
            zs = [z for _r, z in self.profile_points]
            if any(b <= a for a, b in zip(zs, zs[1:])):
                raise ValueError(
                    "profile_points must climb: every height above the one "
                    "before it. A profile that doubles back is not a silhouette "
                    "a lathe can follow."
                )
            if min(r for r, _z in self.profile_points) <= 0:
                raise ValueError("a profile point with zero or negative radius is not on the part")
        elif self.profile_points:
            raise ValueError(
                "profile_points was given but profile is %r, so it would be "
                "silently ignored. Legal: set profile to custom, or drop the "
                "points." % self.profile
            )
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

        if self.pattern == "cells":
            # A strut is a printed wall and obeys the same rule as any other:
            # narrower than two extrusions and the slicer either drops it or
            # prints a single wobbling bead. The nozzle is not known here, so
            # this is the floor for a 0.4 - the real check is the feature
            # linter, which sees the actual nozzle.
            if self.strut_mm < 0.8:
                raise ValueError(
                    "a %.2f mm strut is thinner than two extrusions of a 0.4 mm "
                    "nozzle, so the web would not print. Legal: strut_mm above 0.8."
                    % self.strut_mm
                )
            band = self.banded_height_mm()
            if band <= self.strut_mm * 2:
                raise ValueError(
                    "the bands leave only %.1f mm of wall to pattern, which is "
                    "less than two struts. Legal: a taller vessel, or smaller "
                    "rim_band_mm and base_band_mm." % band
                )
            # Cells have to be bigger than the struts between them, or the web
            # closes up into a solid wall with dimples in it.
            span = self.pattern_span_mm()
            per_cell = math.sqrt(max(span * band / self.cell_count, 0.0))
            if per_cell < self.strut_mm * 1.8:
                raise ValueError(
                    "%d cells over %.0f x %.0f mm of wall gives about %.1f mm "
                    "per cell, and a %.1f mm strut would close them up. Legal: "
                    "fewer cells, or a thinner strut."
                    % (self.cell_count, span, band, per_cell, self.strut_mm)
                )

        if self.drain_holes and self.drain_dia_mm >= self.foot() * 0.6:
            raise ValueError(
                "%d holes of %.1f mm will not fit in a %.1f mm base. Legal: "
                "drain_dia_mm under %.1f."
                % (self.drain_holes, self.drain_dia_mm, self.foot(),
                   self.foot() * 0.6)
            )
        return self

    def pattern_u_ref_mm(self) -> float:
        """
        The reference radius the unwrap uses.

        Three quarters of the widest radius rather than the mean, because on a
        flared bowl most of the WALL AREA is up near the rim, and unwrapping
        about the mean makes the cells up there noticeably coarser than the
        ones below.
        """
        return self.outer_dia_mm / 2.0 * 0.75

    def pattern_span_mm(self) -> float:
        return 2.0 * math.pi * self.pattern_u_ref_mm()

    def pattern_z_range(self) -> tuple[float, float]:
        lo = self.foot_mm + self.floor_thickness_mm + self.base_band_mm
        return lo, self.height_mm - self.rim_band_mm

    def banded_height_mm(self) -> float:
        lo, hi = self.pattern_z_range()
        return max(hi - lo, 0.0)

    def worst_lean_deg(self) -> float:
        """Steepest outward lean of the outer wall, in degrees from vertical."""
        pts = _outer_profile(self)
        worst = 0.0
        for (r0, z0), (r1, z1) in zip(pts, pts[1:]):
            if r1 <= r0 or z1 <= z0:
                continue                     # going in, or going nowhere
            worst = max(worst, math.degrees(math.atan2(r1 - r0, z1 - z0)))
        return worst


def _bezier_control_for_peak(base_r: float, rim_r: float, peak_r: float) -> float:
    """
    The control point that makes a quadratic Bezier PEAK at `peak_r`.

    For B(t) = (1-t)^2 P0 + 2(1-t)t U + t^2 P2 the maximum is at the vertex of
    a parabola, and solving B(t*) = R for U gives

        U = R +/- sqrt(R^2 - P0^2 + (P0 - R)(P0 + P2))

    Take the root whose vertex falls inside the curve; if neither does, the
    peak is unreachable between these ends and the widest end wins, which is
    what the plain control point already did.

    Exact, so no build-measure-correct loop: the peak lands on the number that
    was asked for the first time.
    """
    if peak_r <= max(base_r, rim_r):
        return peak_r

    under = peak_r ** 2 - base_r ** 2 + (base_r - peak_r) * (base_r + rim_r)
    if under < 0:
        return peak_r

    for candidate in (peak_r + math.sqrt(under), peak_r - math.sqrt(under)):
        denominator = base_r - 2.0 * candidate + rim_r
        if abs(denominator) < 1e-12:
            continue
        t_star = (base_r - candidate) / denominator
        if 0.0 < t_star < 1.0:
            return candidate
    return peak_r


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
    # A BEZIER DOES NOT PASS THROUGH ITS CONTROL POINT, and this used
    # outer_dia_mm/2 as one - so a belly asked for 120 mm across came out
    # 99.8, which is 17% under a stated dimension, with nominal_mm still
    # claiming 120. The comment below has always said "widest at the waist";
    # the curve just never went there.
    control_r = _bezier_control_for_peak(base_r, rim_r, wide_r)
    h = p.body_height_mm
    z0 = p.foot_mm

    # A STRAIGHT PROFILE NEEDS TWO STATIONS, NOT TWENTY-FIVE. Lofting a cone
    # through 25 evenly spaced circles builds 24 bands of one identical cone,
    # which is slower, heavier, and the thing that made the shape upgrader
    # fall over. Curves need the stations; straight lines do not.
    steps = 1 if p.profile in ("straight", "cylinder") else STATIONS

    if p.profile == "custom":
        # The points carry the SHAPE; height_mm and outer_dia_mm carry the SIZE.
        #
        # Without this the points carried both, and "make it 200 mm tall" on a
        # fitted vase came back 147 mm tall - the number was accepted, stored
        # in the spec, and silently ignored. A parameter that does nothing is
        # worse than one that is missing.
        #
        # The shape itself is never resampled or smoothed: that would throw
        # away the thing that was measured.
        pts = [(float(r), float(zz)) for r, zz in p.profile_points]
        src_h = pts[-1][1] - pts[0][1]
        src_max_r = max(r for r, _z in pts)
        z_scale = (p.body_height_mm / src_h) if src_h > 1e-9 else 1.0
        r_scale = (p.outer_dia_mm / 2.0 / src_max_r) if src_max_r > 1e-9 else 1.0
        return [(max(r * r_scale, 0.4), z0 + (zz - pts[0][1]) * z_scale)
                for r, zz in pts]

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
            r = ((1 - t) ** 2 * base_r + 2 * (1 - t) * t * control_r
                 + t ** 2 * rim_r)
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


# How far the delivered widest point may fall short of the stated one before
# the rim is compensated. 0.05 mm is the harness's own hole tolerance and ten
# times the STL export tolerance, so anything above it is a real discrepancy
# between a parameter and a part; anything below it cannot be measured off the
# exported mesh anyway. Correcting below this line would rebuild every bowl to
# chase a number thinner than the file it is written to.
RIM_COMPENSATION_FLOOR_MM = 0.05


def build_core(p: VesselParams, log: BuildLog) -> cq.Workplane:
    """
    The vessel, upright, open at the top. Print and assembled are the same.

    Built at most twice: once as asked, and once more with the rim widened
    when the cosmetic rim rounding has eaten the widest point. See
    _compensate_rim.
    """
    body = _build_body(p, log)

    bump = _rim_deficit(p, body)
    if bump > RIM_COMPENSATION_FLOOR_MM:
        # MEASURE, THEN CORRECT. The bite the fillet takes out of the widest
        # point depends on the wall's local lean and on how OCC chose to build
        # the torus, so it is measured off the solid rather than predicted.
        # One correction lands it: the second-order change in lean from a
        # 0.5 mm wider rim is far below the floor above, and the residual is
        # logged either way rather than assumed.
        widened = p.model_copy(update={"rim_dia_mm": p.rim() + 2.0 * bump})
        second = _build_body(widened, log)
        residual = _rim_deficit(p, second)
        log.notes.append(
            "rim widened %.3f mm so the widest point delivers the %.2f mm "
            "asked for - the %.2f mm rim rounding had taken %.3f mm off it. "
            "Residual after correction %.3f mm"
            % (2.0 * bump, p.outer_dia_mm, p.rim_round_mm, 2.0 * bump, residual)
        )
        if abs(residual) <= abs(2.0 * bump):
            body = second
    return body


def _widest_stated_dia(p: VesselParams) -> float:
    """
    The diameter the parameters SAY is the widest point of the body.

    Not the bounding box and not nominal_mm: the number a person reading the
    spec would expect to measure across the widest part of the finished pot.
    """
    stations = _outer_profile(p)
    return 2.0 * max(r for r, _z in stations)


def _rim_deficit(p: VesselParams, body: cq.Workplane) -> float:
    """
    Half the shortfall between the stated widest diameter and the built one.

    Half, because it is applied to a radius. Returns 0.0 when the part is at
    or over size, and when the measurement cannot be taken - a compensation
    that fires on a failed measurement is worse than none.
    """
    try:
        bb = body.val().BoundingBox()
    except Exception:
        return 0.0
    got = max(bb.xmax - bb.xmin, bb.ymax - bb.ymin)
    return max(_widest_stated_dia(p) - got, 0.0) / 2.0


def _build_body(p: VesselParams, log: BuildLog) -> cq.Workplane:
    """One pass of the geometry, exactly as it was before compensation."""
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
    if p.profile == "custom":
        steps = max(len(p.profile_points) - 1, 1)

    inner: list[tuple[float, float]] = []
    for i in range(steps + 1):
        z = z_bottom + (z_top - z_bottom) * i / steps
        r = _radius_at(outer_stations, min(z, p.height_mm)) - p.wall_mm
        inner.append((max(r, 0.3), z))
    body = body.cut(_loft_circles(inner))

    for cutter in _drains(p):
        body = body.cut(cutter)

    if p.pattern == "cells":
        body = _cut_cells(p, outer_stations, body, log)

    if p.rim_round_mm > MIN_FILLET_MM:
        r = safe_fillet_radius(p.rim_round_mm, p.wall_mm)
        body = try_edge_op(body, ">Z", "fillet", r, "rim", log)

    return body


def _cut_cells(p: VesselParams, stations, body: cq.Workplane,
               log: BuildLog) -> cq.Workplane:
    """
    Cut the Voronoi web through the wall.

    ONE CUT AGAINST A COMPOUND, not a hundred cuts in a row. Each boolean on a
    turned shell costs over a second, so cutting the cells one at a time is
    minutes; handing OpenCascade the whole set at once is a few seconds.
    """
    from bpcad.build import cells as cellmod
    from bpcad.build.helpers import compound_of

    z_lo, z_hi = p.pattern_z_range()
    u_ref = p.pattern_u_ref_mm()
    polys = cellmod.cell_polygons(
        p.cell_count, p.pattern_span_mm(), z_lo, z_hi, p.strut_mm, p.cell_seed
    )
    if not polys:
        log.notes.append(
            "the cell pattern produced no holes at all - the struts have closed "
            "it up, and the vessel is solid-walled"
        )
        return body

    z_min, z_max = stations[0][1], stations[-1][1]
    radius_at = lambda z: _radius_at(stations, z)   # noqa: E731
    depth = p.wall_mm + 6.0

    cutters = []
    for poly in polys:
        try:
            cutters.append(
                cellmod.cell_cutter(poly, radius_at, u_ref, z_min, z_max, depth)
            )
        except Exception:
            # One malformed cell is a missing hole, not a failed bowl.
            continue

    if not cutters:
        log.notes.append("no cell could be turned into a cutter - wall left solid")
        return body

    holed = body.cut(compound_of(cutters))

    # probe(), not isValid(). A shell with a hundred holes in it is exactly the
    # sort of thing that reports valid and then breaks the next boolean.
    from bpcad.build.helpers import probe

    if not probe(holed) or not holed.vals():
        # WHY THIS HAPPENS, so the note is worth reading. Each cell is cut by a
        # prism standing on the surface's TANGENT PLANE, which is an excellent
        # approximation over a small patch and a poor one over a large patch of
        # a strongly curved profile - the prism stops following the wall and
        # starts poking through it. Measured on a wobbly fitted vase: 90 cells
        # fails, 160 and 220 both cut cleanly. So the fix is more cells, not
        # fewer, which is the opposite of what anyone would guess.
        log.notes.append(
            "the %d-cell pattern would not cut cleanly on this profile and was "
            "reverted, leaving the wall solid. Each cell is cut on the "
            "surface's tangent plane, and a large cell on a strongly curved "
            "wall stops following it. Try MORE cells - roughly %d - with a "
            "thinner strut; smaller patches follow the curve."
            % (p.cell_count, int(p.cell_count * 1.8))
        )
        return body

    log.notes.append(
        "%d cells cut, %.0f%% of the patterned band is open, %.1f mm struts"
        % (len(cutters),
           100 * cellmod.open_fraction(polys, p.pattern_span_mm(), z_lo, z_hi),
           p.strut_mm)
    )
    return holed


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
    if params.pattern == "cells":
        # The strut is a printed wall. Recording it means the nozzle linter
        # judges it against the REAL nozzle, rather than the 0.4 assumed by
        # the validator's floor.
        features["cell strut"] = params.strut_mm

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
        # "plate" WAS BARE HERE, and a bare shape word you only half make
        # is the pot/planter mistake in enclosure.py all over again: every
        # request for a flat drilled plate matched this, chose the vessel or
        # the enclosure, and got a part that was not a plate. Qualified, it
        # claims the round one it actually turns; a rectangular plate is a
        # prism and a pattern of cuts, which primitives already build.
        "trinket dish", "catch-all", "saucer", "round plate", "tray round",
        # What people call the cellular version.
        "voronoi bowl", "cell bowl", "cellular bowl", "lattice bowl",
        "fruit basket", "openwork bowl", "mesh bowl", "generative bowl",
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
