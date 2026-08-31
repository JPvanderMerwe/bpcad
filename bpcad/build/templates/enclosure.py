"""
Enclosure: a hollow box with walls, an opening and a roof.

WHY THIS TEMPLATE EXISTS
------------------------
Asked for a birdhouse, the pipeline had only a keyring and a louvre vent, so it
fell to composing primitives one at a time - and produced a 120 x 100 x 145 mm
block that was 96 percent SOLID. Correct on the outside, 2.1 kg of filament, and
useless as a birdhouse, because nothing in the system knew that a birdhouse is a
container and a container is hollow.

That is the whole point of a template. It carries the knowledge that a thing of
this kind has a wall thickness, a cavity that opens upward so it prints without
support, a floor with drainage, and a roof that keeps rain off the entrance. A
model asked to remember all of that in one shot forgets some of it. A model
asked to fill in six numbers does not.

It covers a family, not one object: birdhouse, nesting box, storage box,
planter, project case, bat box. What changes between them is the numbers.

PRINTABILITY IS BUILT IN, NOT CHECKED AFTERWARDS
------------------------------------------------
  * the cavity opens UPWARD, so there is no ceiling to bridge and no support
  * the roof is a separate piece printed flat, because a sloped roof modelled
    in place is an overhang across its whole area
  * the entrance is a vertical-axis hole in a vertical wall, which needs no
    support either
  * every wall is checked against the nozzle before any geometry is built
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

from typing import Literal

import cadquery as cq
from pydantic import Field, model_validator

from bpcad.build.helpers import BuildLog, MIN_FILLET_MM, disc, rrect, safe_fillet_radius, try_edge_op
from bpcad.spec.registry import Template, register
from bpcad.spec.schema import TemplateParams


class EnclosureParams(TemplateParams):
    """
    A hollow box with a roof. Every dimension carries its unit in the name.

    The defaults describe a small-bird nesting box: 120 x 100 x 160 mm outside,
    3 mm walls, a 32 mm entrance - which is the size for a starling. Change the
    numbers and it is a storage box or a planter.
    """

    # --- the box ----------------------------------------------------------
    width_mm: float = Field(120.0, gt=20.0, le=600.0, description="X, outside width.")
    depth_mm: float = Field(100.0, gt=20.0, le=600.0, description="Y, outside depth.")
    height_mm: float = Field(
        160.0, gt=20.0, le=600.0,
        description="Z, outside height of the box, not counting the roof.",
    )
    wall_mm: float = Field(
        3.0, gt=0.4, le=30.0,
        description="Wall thickness. 3 mm is sound for a birdhouse in PETG.",
    )
    floor_mm: float | None = Field(
        None, gt=0.4, le=50.0,
        description="Floor thickness. Leave unset to match the wall.",
    )
    corner_r_mm: float = Field(
        4.0, ge=0.0, le=80.0, description="Vertical corner radius on the outside."
    )

    # --- the opening ------------------------------------------------------
    entrance_dia_mm: float | None = Field(
        32.0, ge=0.0, le=300.0,
        description=(
            "Entrance hole diameter. 32 mm suits a starling, 28 a great tit, "
            "25 a blue tit. Set 0 for no entrance - a plain box."
        ),
    )
    entrance_height_mm: float | None = Field(
        None, gt=0.0, le=600.0,
        description=(
            "Height of the entrance centre above the floor. Leave unset to put "
            "it in the upper third, which keeps chicks away from a reaching cat."
        ),
    )
    entrance_face: str = Field(
        "front", description="Which wall the entrance goes in: front, back, left or right."
    )
    predator_guard_mm: float = Field(
        0.0, ge=0.0, le=60.0,
        description=(
            "A raised collar around the entrance, thickening the wall so a cat "
            "or a squirrel cannot reach through to the nest. 18 to 25 mm is "
            "usual. 0 for none."
        ),
    )

    # NO PERCH, AND NOT BY OVERSIGHT. A perch below the entrance is the single
    # most common mistake on a homemade birdhouse: the birds that use nest boxes
    # do not need one, and it gives a predator somewhere to stand and reach in.
    # There is deliberately no parameter for it.

    back_plate_mm: float = Field(
        0.0, ge=0.0, le=200.0,
        description=(
            "Extend the back wall this far above and below the box, giving a "
            "flat plate to screw to a tree or a post. 0 for none."
        ),
    )

    # --- the roof ---------------------------------------------------------
    roof: bool = Field(True, description="Include a roof. Printed as a separate piece.")
    roof_overhang_mm: float = Field(
        20.0, ge=0.0, le=200.0,
        description="How far the roof stands proud on every side, to shed rain clear of the entrance.",
    )
    roof_thick_mm: float = Field(6.0, gt=0.8, le=60.0, description="Roof slab thickness.")
    roof_pitch_deg: float = Field(
        18.0, ge=0.0, le=60.0,
        description=(
            "Roof slope. Printed FLAT and set on at an angle, so the slope costs "
            "no support. 0 gives a flat roof."
        ),
    )
    roof_lip_mm: float = Field(
        0.0, ge=0.0, le=40.0,
        description=(
            "Depth of the lip under the roof that drops into the cavity and "
            "locates the lid. For FLAT lids. A lip cannot enter a rectangular "
            "hole while the lid is tilted, so a pitched roof wants 0 and glue."
        ),
    )
    roof_clearance_mm: float = Field(
        0.4, ge=0.0, le=3.0,
        description="Gap between the lip and the box, so the roof lifts off.",
    )

    # --- exterior finish ---------------------------------------------------
    # A FINISH IS GEOMETRY, NOT A TEXTURE. There is no material to fake grain
    # with, so the only honest way to make a printed box look like anything is
    # to cut the relief into it and let the light do the rest. That means every
    # groove is a real feature with a real width, it gets checked against the
    # nozzle like any other, and it is a number you can change afterwards.
    finish: Literal["plain", "board", "slat"] = Field(
        "plain",
        description=(
            "Exterior relief. plain is flat. board cuts horizontal shiplap "
            "grooves for a weatherboard look. slat cuts vertical reveals for a "
            "modern slatted panel look."
        ),
    )
    finish_pitch_mm: float = Field(
        11.0, gt=2.0, le=100.0,
        description="Spacing between grooves, centre to centre.",
    )
    finish_groove_mm: float = Field(
        1.2, gt=0.0, le=20.0,
        description="Width of each groove. Must be at least two nozzle widths to resolve.",
    )
    finish_depth_mm: float = Field(
        0.8, gt=0.0, le=20.0,
        description="How deep the grooves cut into the wall.",
    )

    # --- practicalities ---------------------------------------------------
    drain_holes: int = Field(
        4, ge=0, le=24,
        description="Drainage holes in the floor. A birdhouse without them rots.",
    )
    drain_dia_mm: float = Field(6.0, gt=0.0, le=40.0, description="Drainage hole diameter.")
    vent_slots: int = Field(
        2, ge=0, le=12,
        description="Ventilation slots near the top of each side wall.",
    )
    mount_holes: bool = Field(
        True, description="Two screw holes through the back wall for mounting."
    )
    mount_dia_mm: float = Field(4.5, gt=1.0, le=20.0, description="Mounting hole diameter.")

    # ---- derived ---------------------------------------------------------

    @property
    def floor_thickness_mm(self) -> float:
        return self.floor_mm if self.floor_mm is not None else self.wall_mm

    @property
    def cavity_w_mm(self) -> float:
        return self.width_mm - 2 * self.wall_mm

    @property
    def cavity_d_mm(self) -> float:
        return self.depth_mm - 2 * self.wall_mm

    @property
    def cavity_h_mm(self) -> float:
        return self.height_mm - self.floor_thickness_mm

    @property
    def total_height_mm(self) -> float:
        return self.height_mm + 2 * self.back_plate_mm

    @property
    def entrance_z_mm(self) -> float:
        if self.entrance_height_mm is not None:
            return self.entrance_height_mm
        # Upper third: far enough above the floor that a cat cannot reach the
        # chicks, far enough below the roof that the bird can get in.
        return self.floor_thickness_mm + self.cavity_h_mm * 0.68

    @model_validator(mode="after")
    def _buildable(self) -> "EnclosureParams":
        if self.cavity_w_mm <= 4 or self.cavity_d_mm <= 4:
            raise ValueError(
                "wall_mm %.2f leaves a cavity of only %.1f x %.1f mm inside a "
                "%.0f x %.0f mm box. Legal: wall_mm under %.2f."
                % (self.wall_mm, self.cavity_w_mm, self.cavity_d_mm,
                   self.width_mm, self.depth_mm,
                   (min(self.width_mm, self.depth_mm) - 4) / 2)
            )
        if self.cavity_h_mm <= 10:
            raise ValueError(
                "floor_mm %.2f leaves only %.1f mm of usable height inside a "
                "%.0f mm box." % (self.floor_thickness_mm, self.cavity_h_mm, self.height_mm)
            )

        if self.entrance_face not in ("front", "back", "left", "right"):
            raise ValueError(
                "entrance_face %r is not a wall. Legal: front, back, left, right."
                % self.entrance_face
            )

        if self.entrance_dia_mm and self.predator_guard_mm:
            collar = self.entrance_dia_mm + 2 * max(self.wall_mm * 2, 6.0)
            span = (self.width_mm if self.entrance_face in ("front", "back")
                    else self.depth_mm)
            if collar >= span:
                raise ValueError(
                    "a %.0f mm entrance with a predator guard needs a %.0f mm "
                    "collar, which does not fit on a %.0f mm face. Legal: "
                    "reduce entrance_dia_mm, or widen the box."
                    % (self.entrance_dia_mm, collar, span)
                )

        if self.entrance_dia_mm:
            span = (self.width_mm if self.entrance_face in ("front", "back")
                    else self.depth_mm)
            if self.entrance_dia_mm >= span - 2 * self.wall_mm - 4:
                raise ValueError(
                    "an entrance of %.1f mm does not fit in a %.0f mm wall with "
                    "%.1f mm walls - it would break through the corners. Legal: "
                    "entrance_dia_mm under %.1f."
                    % (self.entrance_dia_mm, span, self.wall_mm,
                       span - 2 * self.wall_mm - 4)
                )
            top = self.entrance_z_mm + self.entrance_dia_mm / 2
            if top > self.height_mm - 2:
                raise ValueError(
                    "the entrance reaches %.1f mm up a %.0f mm box and breaks "
                    "through the top. Lower entrance_height_mm, or raise "
                    "height_mm." % (top, self.height_mm)
                )
            if self.entrance_z_mm - self.entrance_dia_mm / 2 < self.floor_thickness_mm + 2:
                raise ValueError(
                    "the entrance reaches below the floor. Raise "
                    "entrance_height_mm above %.1f."
                    % (self.floor_thickness_mm + self.entrance_dia_mm / 2 + 2)
                )

        if self.finish != "plain":
            # A groove deeper than a third of the wall is not a finish, it is
            # a weakness - and on a birdhouse the wall is the only thing
            # between the weather and the nest.
            if self.finish_depth_mm > self.wall_mm / 3.0:
                raise ValueError(
                    "a %.2f mm groove in a %.2f mm wall takes more than a third "
                    "of it. Legal: finish_depth_mm up to %.2f, or a thicker wall."
                    % (self.finish_depth_mm, self.wall_mm, self.wall_mm / 3.0)
                )
            if self.finish_groove_mm >= self.finish_pitch_mm:
                raise ValueError(
                    "grooves %.2f mm wide at %.2f mm spacing overlap, which "
                    "removes the whole face rather than texturing it. Legal: "
                    "finish_groove_mm under %.2f."
                    % (self.finish_groove_mm, self.finish_pitch_mm,
                       self.finish_pitch_mm)
                )

        if self.roof and self.roof_lip_mm > 0 and self.roof_pitch_deg > 0:
            # A rigid lip cannot enter a rectangular hole while the lid is
            # tilted. Swinging it in sweeps lip * tan(pitch) sideways, and that
            # has to fit in the clearance or the lip binds on the rim. Default
            # 4 mm lip at 18 deg needs 1.30 mm and had 0.40, so it jammed - and
            # nothing said so, because the render looked right.
            need = self.roof_lip_mm * math.tan(math.radians(self.roof_pitch_deg))
            if self.roof_clearance_mm < need + 0.2:
                raise ValueError(
                    "a %.1f mm lip on a roof pitched %.0f deg has to swing "
                    "%.2f mm sideways to seat, and roof_clearance_mm is %.2f. "
                    "Legal: roof_lip_mm 0 (pitched roofs are glued, not "
                    "located), roof_pitch_deg 0 for a flat lid that keeps the "
                    "lip, or roof_clearance_mm above %.2f."
                    % (self.roof_lip_mm, self.roof_pitch_deg, need,
                       self.roof_clearance_mm, need + 0.2)
                )

        if self.roof and self.roof_lip_mm > 0:
            lip_w = self.cavity_w_mm - 2 * self.roof_clearance_mm
            if lip_w <= 4.0:
                raise ValueError(
                    "the roof lip drops into the cavity, and a %.0f mm box with "
                    "%.1f mm walls leaves only %.1f mm for it. Legal: thinner "
                    "walls, a wider box, or roof_lip_mm 0 for a flat lid."
                    % (self.width_mm, self.wall_mm, lip_w)
                )

        if self.drain_holes and self.drain_dia_mm >= min(self.cavity_w_mm, self.cavity_d_mm) / 3:
            raise ValueError(
                "drain_dia_mm %.1f is too big for a %.0f x %.0f mm floor. Legal: "
                "under %.1f." % (self.drain_dia_mm, self.cavity_w_mm,
                                 self.cavity_d_mm,
                                 min(self.cavity_w_mm, self.cavity_d_mm) / 3)
            )
        return self


@dataclass
class _Derived:
    cavity_w: float
    cavity_d: float
    cavity_h: float
    floor_t: float
    entrance_z: float
    roof_w: float
    roof_d: float
    roof_rise: float


def derive(p: EnclosureParams) -> _Derived:
    return _Derived(
        cavity_w=p.cavity_w_mm,
        cavity_d=p.cavity_d_mm,
        cavity_h=p.cavity_h_mm,
        floor_t=p.floor_thickness_mm,
        entrance_z=p.entrance_z_mm,
        roof_w=p.width_mm + 2 * p.roof_overhang_mm,
        roof_d=p.depth_mm + 2 * p.roof_overhang_mm,
        roof_rise=(p.depth_mm + 2 * p.roof_overhang_mm)
        * math.tan(math.radians(p.roof_pitch_deg)) / 2.0,
    )


def build_box(p: EnclosureParams, d: _Derived, log: BuildLog) -> cq.Workplane:
    """
    The box, in print orientation: standing upright, cavity opening up.

    THE CAVITY OPENS UPWARD ON PURPOSE. A box hollowed downward has a ceiling
    over its whole footprint, which needs support inside a cavity nobody can
    reach to clean it out of. Opening upward makes every surface either a wall
    or a floor.
    """
    box = rrect(p.width_mm, p.depth_mm, p.corner_r_mm, -p.depth_mm / 2.0, p.height_mm)

    cavity = rrect(
        d.cavity_w, d.cavity_d,
        max(p.corner_r_mm - p.wall_mm, 0.0),
        -d.cavity_d / 2.0,
        d.cavity_h + 1.0,
        z0=d.floor_t,
    )
    box = box.cut(cavity)

    if p.entrance_dia_mm:
        box = box.cut(_entrance(p, d))

    if p.back_plate_mm > 0:
        box = box.union(_back_plate(p, d))
    if p.entrance_dia_mm and p.predator_guard_mm > 0:
        box = box.union(_predator_guard(p, d))
        # Re-cut the entrance so the collar is bored through as well - a guard
        # with no hole in it is a plug.
        box = box.cut(_entrance(p, d))

    for cutter in _drains(p, d):
        box = box.cut(cutter)
    for cutter in _vents(p, d):
        box = box.cut(cutter)
    if p.mount_holes:
        for cutter in _mounts(p, d):
            box = box.cut(cutter)

    # The finish goes on AFTER every functional cut and before the cosmetic
    # fillet. Before the entrance, and the entrance would re-bore through
    # grooves that are already there for no reason; after the fillet, and each
    # groove would carve a notch out of the rounded corner.
    for cutter in _finish_cutters(p, d):
        box = box.cut(cutter)

    # Cosmetic, last, and reverted if OCC objects.
    box = try_edge_op(box, "|Z", "fillet", min(p.wall_mm * 0.3, 1.0),
                      "outside corners", log)
    return box


# How far a board groove climbs while it returns to the wall face, as a
# multiple of its depth. 1.0 is exactly 45 degrees, which the overhang check
# treats as a failure and not a pass. 1.7 is 30 degrees off vertical.
RAMP_RISE = 1.7


def _finish_cutters(p: EnclosureParams, d: _Derived) -> list[cq.Workplane]:
    """
    The exterior relief, as solids to subtract.

    BOARD is a stack of rings. Each groove goes right around the box, so the
    corners read as a continuous line the way real weatherboard does - cutting
    only the flat faces leaves the corners proud and the whole thing looks like
    four separate panels leaning together.

    SLAT is vertical, and therefore per-face: a groove that ran around the box
    horizontally is one shape, but four faces of vertical grooves are four sets
    of cutters, because a vertical groove on the front and one on the side are
    not the same solid at any rotation.

    Both stop clear of the top and bottom. A groove that runs off the end of
    the box breaks the edge into a comb, and a groove that opens into the
    cavity is a hole in the wall.
    """
    depth = p.finish_depth_mm
    groove = p.finish_groove_mm
    pitch = p.finish_pitch_mm
    out: list[cq.Workplane] = []

    if p.finish == "board":
        # Leave a solid band at the floor and under the rim, so the box has a
        # plinth and a top rail rather than a groove hanging off each end.
        low = d.floor_t + pitch * 0.5
        high = p.height_mm - pitch * 0.5
        # THE GROOVE IS RAMPED, NOT SQUARE.
        #
        # A groove's upper flank has to come back out to the wall face as it
        # rises, and a surface moving outward as it rises leans over the air
        # below it. That is an overhang whatever shape it is; the only thing
        # that can be chosen is the angle. Square-cut, forty grooves put 4 600
        # mm2 of horizontal ceiling on this box.
        #
        # THE RAMP MUST END ON THE WALL FACE AND NOWHERE ELSE. The first
        # attempt lofted out to width + 4 - the size of the throwaway slab -
        # instead of to the wall. That spreads two millimetres sideways for
        # every 1.4 of rise, which is not a ramp, it is a ceiling at 26 degrees
        # off straight down, and it made the overhang WORSE than square-cutting
        # had. Measured, not reasoned about: the faces were right there in the
        # mesh at 26 degrees.
        #
        # Ending on the wall face, the run is exactly `depth` over
        # `depth * RAMP_RISE`, which is 30 degrees off vertical and prints
        # unsupported. It is also what weatherboard actually looks like: each
        # board oversails the one below it on a slope.
        ramp_rise = depth * RAMP_RISE
        z = low
        while z + groove + ramp_rise <= high:
            slab = rrect(p.width_mm + 4.0, p.depth_mm + 4.0,
                         p.corner_r_mm + 2.0, -(p.depth_mm + 4.0) / 2.0,
                         groove + ramp_rise, z0=z)
            # The land the groove is cut against, and the ramp back out of it.
            # THE KEEP AND THE RAMP MUST MEET EXACTLY. Started half a
            # millimetre low and ended half a millimetre low, this left a 0.5
            # mm band where neither protected the wall, so the cutter went
            # straight through and the box came out as eighteen loose rings.
            # It still exported, and it was still watertight.
            keep = rrect(p.width_mm - 2 * depth, p.depth_mm - 2 * depth,
                         max(p.corner_r_mm - depth, 0.0),
                         -(p.depth_mm - 2 * depth) / 2.0,
                         groove + 0.5, z0=z - 0.5)
            ramp = (
                cq.Workplane("XY")
                .workplane(offset=z + groove)
                .rect(p.width_mm - 2 * depth, p.depth_mm - 2 * depth)
                .workplane(offset=ramp_rise)
                .rect(p.width_mm, p.depth_mm)
                .loft()
            )
            out.append(slab.cut(keep.union(ramp)))
            z += pitch
        return out

    if p.finish == "slat":
        z0 = d.floor_t + 2.0
        height = p.height_mm - z0 - 2.0
        if height <= 0:
            return out

        def slot_x(x: float, y0: float) -> cq.Workplane:
            """A vertical groove in a face that faces along Y."""
            return rrect(groove, 2 * depth, 0.0, y0, height, z0=z0).translate((x, 0, 0))

        def slot_y(y: float, x0: float) -> cq.Workplane:
            """A vertical groove in a face that faces along X."""
            return (rrect(2 * depth, groove, 0.0, -groove / 2.0, height, z0=z0)
                    .translate((x0 + depth, y, 0)))

        # Centred on the face, working outwards, so the pattern is symmetric
        # however many fit - an odd count that starts at one edge looks like a
        # mistake rather than a design.
        def offsets(span: float) -> list[float]:
            usable = span - 2 * (p.corner_r_mm + groove)
            if usable <= 0:
                return []
            count = int(usable // pitch)
            if count < 1:
                return []
            first = -count * pitch / 2.0
            return [first + i * pitch for i in range(count + 1)]

        for x in offsets(p.width_mm):
            out.append(slot_x(x, -p.depth_mm / 2.0 - depth))          # front
            out.append(slot_x(x, p.depth_mm / 2.0 - depth))           # back
        for y in offsets(p.depth_mm):
            out.append(slot_y(y, -p.width_mm / 2.0 - depth))          # left
            out.append(slot_y(y, p.width_mm / 2.0 - depth))           # right
        return out

    return out


def _entrance(p: EnclosureParams, d: _Derived) -> cq.Workplane:
    """A horizontal-axis hole through one wall. Round, so a bird cannot perch on a corner."""
    r = p.entrance_dia_mm / 2.0
    through = max(p.width_mm, p.depth_mm) + 20.0

    if p.entrance_face in ("front", "back"):
        plane = cq.Workplane("XZ", origin=(0, 0, 0))
        cutter = plane.center(0, d.entrance_z).circle(r).extrude(through)
        return cutter.translate((0, p.depth_mm / 2.0 + 5.0, 0)) if p.entrance_face == "front" \
            else cutter.translate((0, -p.depth_mm / 2.0 - 5.0, 0)).mirror("XZ")
    plane = cq.Workplane("YZ", origin=(0, 0, 0))
    cutter = plane.center(0, d.entrance_z).circle(r).extrude(through)
    sign = -1.0 if p.entrance_face == "left" else 1.0
    return cutter.translate((sign * (p.width_mm / 2.0 + 5.0), 0, 0))


def _predator_guard(p: EnclosureParams, d: _Derived) -> cq.Workplane:
    """
    A collar around the entrance, so the wall is thick where it matters.

    A cat on the roof reaches down through a 3 mm wall and gets the chicks. The
    same hole through 25 mm of material is a tunnel it cannot reach along. It
    prints as part of the wall it sits on, so it needs no support.
    """
    outer = p.entrance_dia_mm + 2 * max(p.wall_mm * 2, 6.0)
    depth = p.predator_guard_mm

    if p.entrance_face in ("front", "back"):
        sign = 1.0 if p.entrance_face == "front" else -1.0
        plane = cq.Workplane("XZ", origin=(0, 0, 0))
        collar = plane.center(0, d.entrance_z).circle(outer / 2.0).extrude(depth)
        y = p.depth_mm / 2.0
        return collar.translate((0, sign * y, 0)) if sign > 0 else \
            collar.translate((0, -y - depth, 0))

    sign = 1.0 if p.entrance_face == "right" else -1.0
    plane = cq.Workplane("YZ", origin=(0, 0, 0))
    collar = plane.center(0, d.entrance_z).circle(outer / 2.0).extrude(depth * sign)
    return collar.translate((sign * p.width_mm / 2.0, 0, 0))


def _back_plate(p: EnclosureParams, d: _Derived) -> cq.Workplane:
    """
    The back wall carried on above and below the box, to screw to a post.

    Printed in the same plane as the back wall, so it adds no overhang - it is
    simply more of a surface that was already vertical.
    """
    plate = rrect(
        p.width_mm, p.wall_mm, min(p.corner_r_mm, p.wall_mm / 2.0),
        -p.depth_mm / 2.0, p.height_mm + 2 * p.back_plate_mm,
        z0=-p.back_plate_mm,
    )
    return plate


def _drains(p: EnclosureParams, d: _Derived):
    """
    Drainage in the floor. A birdhouse without it holds water and rots, and the
    holes cost nothing because they print as vertical bores.
    """
    if not p.drain_holes:
        return []
    out = []
    inset_x = d.cavity_w / 4.0
    inset_y = d.cavity_d / 4.0
    spots = [(-inset_x, -inset_y), (inset_x, -inset_y),
             (-inset_x, inset_y), (inset_x, inset_y)]
    for i in range(min(p.drain_holes, len(spots))):
        x, y = spots[i]
        out.append(disc(p.drain_dia_mm, x, y, d.floor_t + 2.0, z0=-1.0))
    return out


def _vents(p: EnclosureParams, d: _Derived):
    """Ventilation slots high on the side walls, under the roof line."""
    if not p.vent_slots:
        return []
    out = []
    slot_w = min(d.cavity_d * 0.4, 24.0)
    slot_h = max(p.wall_mm * 1.2, 3.0)
    z = p.height_mm - slot_h - max(p.wall_mm, 3.0)
    through = p.width_mm + 20.0
    for i in range(p.vent_slots):
        y = (i - (p.vent_slots - 1) / 2.0) * (slot_w + 8.0)
        cutter = (cq.Workplane("YZ", origin=(-p.width_mm / 2.0 - 10.0, y, z))
                  .rect(slot_w, slot_h).extrude(through))
        out.append(cutter)
    return out


def _mounts(p: EnclosureParams, d: _Derived):
    """Two screw holes through the back wall, top and bottom."""
    out = []
    through = p.depth_mm + 20.0
    if p.back_plate_mm > 0:
        # Through the plate, where a screw can actually be reached, rather than
        # inside the box where a screwdriver will not go.
        heights = (-p.back_plate_mm / 2.0, p.height_mm + p.back_plate_mm / 2.0)
    else:
        heights = (d.floor_t + 12.0, p.height_mm - 14.0)
    for z in heights:
        if not -p.back_plate_mm < z < p.height_mm + p.back_plate_mm:
            continue
        # An XZ workplane extrudes along -Y, so this has to START in front of
        # the box and cut backwards. Starting behind it - which reads more
        # naturally - extrudes further away and the holes simply never appear,
        # silently, with the part still watertight.
        out.append(
            cq.Workplane("XZ", origin=(0, p.depth_mm / 2.0 + 10.0, 0))
            .center(0, z).circle(p.mount_dia_mm / 2.0).extrude(through)
        )
    return out


def build_roof(p: EnclosureParams, d: _Derived, log: BuildLog) -> cq.Workplane:
    """
    The roof, FLAT, in print orientation.

    A pitched roof modelled in place is an overhang across its entire area. This
    is a flat slab with a locating lip, printed lying down and set on the box
    afterwards - so the slope costs nothing to print. The pitch is reported so
    you know what angle to glue it at.
    """
    slab = rrect(d.roof_w, d.roof_d, p.corner_r_mm + p.roof_overhang_mm * 0.2,
                 -d.roof_d / 2.0, p.roof_thick_mm)

    if p.roof_lip_mm > 0:
        # THE LIP DROPS INTO THE CAVITY, so it is sized from the CAVITY and not
        # from the outside of the box. Sized from the outside it is bigger than
        # the hole it is meant to enter, so it locates nothing and the roof just
        # rests on the rim - which looks right in a render and falls off in a
        # breeze. Found by measuring the gap between the two bodies: 0.014 mm
        # where the clearance says 0.40.
        cavity_w = p.width_mm - 2 * p.wall_mm
        cavity_d = p.depth_mm - 2 * p.wall_mm
        lip_w = cavity_w - 2 * p.roof_clearance_mm
        lip_d = cavity_d - 2 * p.roof_clearance_mm
        lip_wall = min(p.wall_mm, max(lip_w, lip_d) / 4.0)

        lip = rrect(lip_w, lip_d, max(p.corner_r_mm - p.wall_mm, 0.0),
                    -lip_d / 2.0, p.roof_lip_mm, z0=p.roof_thick_mm)
        inner = rrect(lip_w - 2 * lip_wall, lip_d - 2 * lip_wall,
                      max(p.corner_r_mm - p.wall_mm - lip_wall, 0.0),
                      -(lip_d - 2 * lip_wall) / 2.0,
                      p.roof_lip_mm + 1.0, z0=p.roof_thick_mm - 0.5)
        slab = slab.union(lip.cut(inner))

    slab = try_edge_op(slab, "|Z", "fillet", min(p.roof_thick_mm * 0.25, 1.5),
                       "roof corners", log)
    return slab


def build_core(p: EnclosureParams, d: _Derived, log: BuildLog) -> cq.Workplane:
    """ASSEMBLED orientation: the roof sitting on the box, pitched."""
    box = build_box(p, d, log)
    if not p.roof:
        return box

    # THE ROOF PRINTS LIP-UP AND IS ASSEMBLED LIP-DOWN, so the assembled view
    # has to turn it over. Without the flip the lip points at the sky, locates
    # nothing, and the roof just balances on the rim - which renders perfectly
    # and falls off the moment you touch it.
    roof = build_roof(p, d, log)
    roof = roof.rotate((0, 0, 0), (1, 0, 0), 180.0)

    # After the flip the slab's inner face is at z=0 and the lip hangs below it,
    # so lifting by height + thickness seats the slab on the rim and puts the
    # lip in the cavity.
    roof = roof.translate((0, 0, p.height_mm + p.roof_thick_mm))
    if p.roof_pitch_deg:
        # PIVOT ON THE FRONT RIM EDGE, NOT THE CENTRE. One flat printed slab
        # cannot be a gable, it can only be a lean-to. Tilting it about the
        # centre of the box drives its low half straight down through the wall
        # - the render looks like a roof and the solid is two bodies sharing
        # the same space. Pivoting on the front edge keeps every part of the
        # roof at or above the rim.
        y_edge = p.depth_mm / 2.0
        roof = roof.rotate((0, y_edge, p.height_mm), (1, y_edge, p.height_mm),
                           -p.roof_pitch_deg)

    # A COMPOUND, NOT A UNION. The roof lifts off - that is the whole point of
    # the lip and the clearance - so fusing it to the box in the assembled view
    # is wrong twice over: it is not what the object is, and it destroys the
    # gap, so nothing can then measure whether the lid actually fits.
    from bpcad.build.helpers import compound_of

    return compound_of([box, roof])


def build_print(p: EnclosureParams, d: _Derived, log: BuildLog) -> cq.Workplane:
    """
    PRINT orientation: box upright, roof flat beside it.

    Deliberately NOT the assembled model rotated. The roof prints flat and the
    box prints upright, and there is no single rotation that puts both where
    they need to be.
    """
    box = build_box(p, d, log)
    if not p.roof:
        return box

    roof = build_roof(p, d, log)
    gap = 8.0
    roof = roof.translate((p.width_mm / 2.0 + d.roof_w / 2.0 + gap, 0, 0))

    from bpcad.build.helpers import compound_of

    return compound_of([box, roof])


def build(params: EnclosureParams, spec, base_dir: Path | None = None):
    """Template entry point."""
    from bpcad.build.helpers import BuildResult
    from bpcad.spec.schema import Assumption

    d = derive(params)
    log = BuildLog()
    core = build_core(params, d, log)
    printed = build_print(params, d, log)

    features = {
        "wall": params.wall_mm,
        "floor": d.floor_t,
    }
    if params.predator_guard_mm:
        features["predator guard"] = params.predator_guard_mm
    if params.back_plate_mm:
        features["back plate"] = params.wall_mm
    if params.roof:
        features["roof thickness"] = params.roof_thick_mm
        if params.roof_lip_mm:
            features["roof lip"] = params.roof_lip_mm
    if params.vent_slots:
        features["vent slot"] = max(params.wall_mm * 1.2, 3.0)
    if params.finish != "plain":
        # The groove is a real feature with a real width, so the nozzle linter
        # judges it exactly as it judges a wall. A finish too fine to print is
        # a finish that comes out as a smooth face and a wasted print, and
        # nothing else in the pipeline would have noticed.
        features["finish groove"] = params.finish_groove_mm
        features["finish rib"] = params.finish_pitch_mm - params.finish_groove_mm

    assumptions = []
    if params.entrance_dia_mm and params.entrance_height_mm is None:
        assumptions.append(Assumption(
            name="entrance_height_mm",
            value=round(d.entrance_z, 1),
            units="mm above the floor",
            why=(
                "Not stated, so it is placed in the upper third of the cavity - "
                "high enough that a cat reaching through cannot get to chicks on "
                "the floor, low enough that the bird can get in. Set it "
                "explicitly if you have a species in mind."
            ),
        ))

    log.notes.append(
        "the cavity opens upward, so it prints with no support and no ceiling "
        "to bridge"
    )
    if params.roof:
        log.notes.append(
            "the roof prints FLAT beside the box and is set on at %.0f degrees - "
            "modelling the pitch in place would be an overhang across its whole "
            "area" % params.roof_pitch_deg
        )

    return BuildResult(
        solid=core,
        print_solid=printed,
        features=features,
        log=log,
        assumptions=assumptions,
        scale_departures=[],
        derived={
            "total_height_mm": params.total_height_mm,
            "cavity_w_mm": d.cavity_w,
            "cavity_d_mm": d.cavity_d,
            "cavity_h_mm": d.cavity_h,
            "entrance_height_mm": d.entrance_z,
            "roof_w_mm": d.roof_w if params.roof else 0.0,
            "roof_d_mm": d.roof_d if params.roof else 0.0,
            "roof_rise_mm": d.roof_rise if params.roof else 0.0,
        },
        body_count_expected=2 if params.roof else 1,
        body_roles=("box", "roof") if params.roof else ("box",),
        # The box itself, not the roof overhang and not the print layout.
        nominal_mm=(params.width_mm, params.depth_mm, params.height_mm),
    )


register(Template(
    name="enclosure",
    summary=(
        "RECTANGULAR. For anything round use `vessel`. "
        "A hollow box: walls, a floor, an optional opening in one wall, an "
        "optional lift-off roof or lid, drainage, ventilation, a predator "
        "guard and a mounting plate. Everything optional is off by setting it "
        "to zero, so a plain open-topped box is this template with the extras "
        "turned off."
    ),
    # What people call it. A request for "a container" found nothing when this
    # said only "birdhouse, nesting box, planter" and fell through to composing
    # primitives, which makes a far worse part.
    makes=(
        # RECTANGULAR THINGS ONLY. This list used to claim "pot", "planter",
        # "plant pot" and "tub", and a model picking a template matches on
        # words: every request for a bowl or a pot found one of them, chose
        # this, and was handed a square box. It passed every check, because
        # nothing downstream knows what a bowl looks like. Claiming a word you
        # cannot make is worse than claiming nothing - falling through to
        # primitives gives a rough bowl, this gave a confident brick.
        # Round vessels live in the `vessel` template.
        #
        # "container" stays here AND on vessel, deliberately. It is not a shape
        # word - a container is as often square as round - so both claim it and
        # the rest of the request decides. Removing it from here entirely made
        # "make me a container" match nothing at all, which is worse than
        # either template answering.
        "container", "box", "storage box", "bin", "crate", "tote", "tray", "caddy",
        "organiser", "drawer insert", "case", "enclosure", "housing", "shell",
        "project box", "junction box", "electronics enclosure",
        "birdhouse", "bird box", "nesting box", "nest box", "bat box",
        "hive", "feeder body", "letterbox", "post box", "donation box",
    ),
    params_model=EnclosureParams,
    builder=build,
    anchors=("front_face", "back_face", "left_face", "right_face", "top_face", "floor"),
    print_notes=(
        "Two pieces: the box upright, the roof flat beside it. Do not rotate.",
        "No supports. The cavity opens upward and the entrance is a horizontal bore.",
        "Layer height 0.2 to 0.28 mm. This is a big part and detail is not the point.",
        "PETG or ASA outdoors. PLA goes brittle in UV within a season.",
        "3 walls and 15% infill is plenty - the walls carry it, not the infill.",
        "Glue the roof on at the stated pitch, or leave it loose to clean the box out.",
        "No perch, deliberately: nest-box birds do not need one and it gives a "
        "predator somewhere to stand.",
    ),
))
