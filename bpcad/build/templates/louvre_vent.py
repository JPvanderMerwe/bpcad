"""
Louvre vent template. Ported from reference/vent_louvre.py.

WHAT THE PART IS
----------------
A print-in-place adjustable louvre vent with a working parallel-crank linkage.
Blades are VERTICAL and pivot about Z, so the part prints flat and every pin is
a vertical cylinder: no overhangs, no round features printed in mid-air.

The blades are ganged by a parallel crank, not a clamp. Each blade has a crank
socket at CRANK_R from its pivot; one tie bar carries a crank pin for each
blade. Because every crank arm is the same length and parallel, the pin spacing
never changes as the blades swing - the bar simply translates bodily.

Z layer stack, bottom to top, all print-in-place:

    0        .. wall_mm       bottom rail, pivot pins rise from its top face
    +gap     .. +bar_thick    tie bar, free to slide, crank pins rise from it
    +gap     .. blade top     blades, sockets in their undersides
    +gap     .. frame_h       top rail, sockets receive the blade top pins

Every pin points UP. Each air gap is pin_gap_z_mm and is bridged by the first
layer of whatever prints above it.

WHY THE VALIDATORS MATTER HERE
------------------------------
This part has a mechanism, and a mechanism has ways of being geometrically
valid and functionally dead. The reference guarded them with asserts; they are
Pydantic validators now, so a bad combination is rejected before any geometry
exists rather than after a four-second build.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import cadquery as cq
from pydantic import Field, model_validator

from bpcad.build.helpers import BuildLog, compound_of, safe_fillet_radius
from bpcad.spec.registry import Template, register
from bpcad.spec.schema import TemplateParams


# The reference part's blade pitch. Used only to pick a sensible DEFAULT blade
# count for a frame of a different size - an explicit n_blades is never
# overridden.
REFERENCE_PITCH_MM = 17.0

# Chord as a fraction of pitch. The reference is 14.0 / 17.0 = 0.824; the blades
# must not touch as they swing, so this stays under 1.0 with real margin.
CHORD_OF_PITCH = 0.82

# The crank radius ceiling is chord/2 + 0.2 - crank_hub_dia/2. With the default
# pin sizes that is chord/2 - 1.9, so chord/2 - 2.0 sits just inside it and
# lands on exactly 5.00 mm at the reference chord of 14.0.
CRANK_BELOW_HALF_CHORD_MM = 2.0


class LouvreVentParams(TemplateParams):
    """
    Every dimension carries its unit in the name. Every field has bounds.

    WHY FOUR DEFAULTS ARE `None` RATHER THAN NUMBERS
    ------------------------------------------------
    A measured baseline of ten prompts put the level-1 success rate at 50%, and
    every single failure was a default that only held at the reference part's
    dimensions. Ask for a narrower frame and the fixed 14.0 mm chord exceeds the
    blade pitch; shrink the chord as instructed and the fixed 5.0 mm crank
    radius then pokes past the blade trailing edge. Two validators in sequence,
    neither default having moved with the frame.

    So n_blades, blade_chord_mm, crank_r_mm and grip_len_mm derive from the
    frame when they are not given. A value that IS given is never overridden -
    silently correcting what someone asked for would be worse than refusing it.
    """

    # Envelope
    frame_w_mm: float = Field(76.0, gt=10.0, le=400.0, description="X, outside width of the body.")
    frame_d_mm: float = Field(22.0, gt=5.0, le=200.0, description="Y, body depth, the insertion direction.")
    frame_h_mm: float = Field(30.0, gt=10.0, le=400.0, description="Z, outside height and print height.")
    wall_mm: float = Field(4.0, gt=0.4, le=20.0, description="Rail thickness top and bottom.")
    bezel_r_mm: float = Field(1.5, ge=0.0, le=10.0, description="Vertical corner radius on the body.")

    # Mounting flange
    flange_t_mm: float = Field(2.0, gt=0.4, le=20.0, description="Flange thickness in Y.")
    flange_over_mm: float = Field(5.0, gt=0.0, le=50.0, description="How far the flange stands proud, all round.")
    screw_dia_mm: float = Field(3.4, gt=0.5, le=20.0, description="Screw clearance hole. 3.4 is M3 clearance.")
    body_clear_mm: float = Field(0.3, ge=0.0, le=5.0, description="Advisory: cut your hole this much over body size.")

    # Blades
    n_blades: int | None = Field(
        None, ge=2, le=24,
        description=(
            "Number of louvre blades. Leave unset to derive from the aperture "
            "width, keeping roughly the reference 17 mm pitch and never "
            "exceeding what the crank linkage can fit."
        ),
    )
    blade_chord_mm: float | None = Field(
        None, gt=2.0, le=100.0,
        description=(
            "Blade depth in Y when straight through. Leave unset to derive as "
            "0.82 of the blade pitch, so the blades clear each other as they "
            "swing whatever the frame width."
        ),
    )
    blade_thick_mm: float = Field(1.8, gt=0.4, le=20.0, description="Blade thickness in X.")
    blade_angle_deg: float = Field(0.0, ge=-89.0, le=89.0, description="As printed. 0 = straight through.")
    max_angle_deg: float = Field(38.0, gt=0.0, le=80.0,
                                description="Mechanism travel limit. Past ~40 the bar fouls the pivot pins.")
    blade_tip_r_mm: float = Field(0.7, ge=0.0, le=10.0, description="Rounding on the blade edges.")

    # Pivot pins, blade to frame
    pin_dia_mm: float = Field(2.6, gt=0.8, le=20.0, description="Pivot pin diameter. Below 2.4 it snaps.")
    pin_clear_r_mm: float = Field(0.30, gt=0.0, le=2.0, description="Radial clearance, pin to socket.")
    pin_engage_mm: float = Field(2.6, gt=0.2, le=20.0, description="How far a pin sits inside its socket.")
    pin_gap_z_mm: float = Field(0.30, gt=0.0, le=2.0,
                                description="Vertical air gap at every shoulder. Bridged by the layer above.")
    socket_extra_mm: float = Field(0.40, ge=0.0, le=5.0, description="Socket depth beyond the engagement.")
    hub_wall_mm: float = Field(1.2, gt=0.2, le=10.0, description="Material around a pivot socket.")

    # Crank linkage
    crank_r_mm: float | None = Field(
        None, gt=0.5, le=50.0,
        description=(
            "Crank arm length, pivot to crank pin. Leave unset to derive from "
            "the chord, which keeps the crank hub inside the blade."
        ),
    )
    crank_pin_dia_mm: float = Field(1.8, gt=0.5, le=20.0, description="Crank pin diameter.")
    crank_engage_mm: float = Field(2.4, gt=0.2, le=20.0, description="Crank pin engagement depth.")
    crank_hub_wall_mm: float = Field(0.9, gt=0.2, le=10.0, description="Material around a crank socket.")

    # Tie bar, fully enclosed inside the body behind the flange
    bar_thick_mm: float = Field(2.4, gt=0.4, le=20.0, description="Tie bar thickness in Z.")
    bar_width_mm: float = Field(3.2, gt=0.4, le=20.0, description="Tie bar width in Y.")
    bar_tail_mm: float = Field(3.0, ge=0.0, le=30.0, description="Material beyond the outermost crank pin.")

    # Front grip tab
    grip_blade: int | None = Field(
        None, ge=0,
        description=(
            "Which blade carries the thumb tab, as an index. Leave unset to use "
            "the most central blade, which gives the tab the most room to sweep "
            "before it reaches the edge of the aperture."
        ),
    )
    grip_len_mm: float | None = Field(
        None, gt=1.0, le=200.0,
        description=(
            "Pivot to tab tip. Leave unset to derive from the frame depth. It "
            "must stay proud of the flange at max_angle_deg, not merely at rest, "
            "so a deeper frame needs a longer tab."
        ),
    )
    grip_w_mm: float = Field(3.6, gt=0.4, le=30.0, description="Tab thickness in X, a little fatter than the blade.")
    grip_pad_w_mm: float = Field(8.0, gt=1.0, le=60.0, description="Thumb paddle width in X.")
    grip_pad_d_mm: float = Field(3.0, gt=0.5, le=30.0, description="Thumb paddle depth in Y.")

    # ---- filling in what was not given -----------------------------------

    @model_validator(mode="before")
    @classmethod
    def _derive_defaults(cls, data):
        """
        Fill in the four dimensions that depend on the frame.

        Runs BEFORE field validation, on the raw input, so the derived values go
        through the same bounds checks as anything typed by hand. Only fields
        that are absent or explicitly None are touched.
        """
        if not isinstance(data, dict):
            return data
        d = dict(data)

        def given(key, fallback):
            v = d.get(key)
            return fallback if v is None else v

        frame_w = float(given("frame_w_mm", 76.0))
        frame_d = float(given("frame_d_mm", 22.0))
        wall = float(given("wall_mm", 4.0))
        flange_t = float(given("flange_t_mm", 2.0))
        max_angle = float(given("max_angle_deg", 38.0))

        pin_dia = float(given("pin_dia_mm", 2.6))
        pin_clear = float(given("pin_clear_r_mm", 0.30))
        crank_pin = float(given("crank_pin_dia_mm", 1.8))
        crank_wall = float(given("crank_hub_wall_mm", 0.9))
        bar_width = float(given("bar_width_mm", 3.2))

        aperture = frame_w - 2 * wall
        if aperture <= 0:
            return d          # a later validator reports this properly

        cos_a = math.cos(math.radians(max_angle))
        if cos_a <= 0:
            return d

        # The tie bar must clear the fixed pivot pins at full travel, which puts
        # a FLOOR under the crank radius, which puts a floor under the chord,
        # which caps how many blades fit. Work that cap out rather than letting
        # the model discover it one validator at a time.
        crank_floor = (0.4 + bar_width / 2 + pin_dia / 2 + pin_clear) / cos_a
        chord_floor = 2 * (crank_floor + CRANK_BELOW_HALF_CHORD_MM)
        pitch_floor = chord_floor / CHORD_OF_PITCH
        max_blades = int(aperture // pitch_floor) if pitch_floor > 0 else 2

        if d.get("n_blades") is None:
            want = int(round(aperture / REFERENCE_PITCH_MM))
            d["n_blades"] = max(2, min(want, max_blades)) if max_blades >= 2 else 2

        n_blades = int(d["n_blades"])
        pitch = aperture / n_blades if n_blades else 0.0

        if d.get("blade_chord_mm") is None and pitch > 0:
            d["blade_chord_mm"] = round(CHORD_OF_PITCH * pitch, 3)

        chord = d.get("blade_chord_mm")
        if d.get("crank_r_mm") is None and chord:
            d["crank_r_mm"] = round(float(chord) / 2 - CRANK_BELOW_HALF_CHORD_MM, 3)

        # The tab goes on the most central blade. On a 4-blade frame that is
        # index 2, which is what the reference uses; on an odd count it lands on
        # the centreline, where it has the most room to sweep before reaching
        # the edge of the aperture.
        if d.get("grip_blade") is None:
            d["grip_blade"] = n_blades // 2

        if d.get("grip_len_mm") is None:
            # The tab has a FLOOR and a CEILING, and the first version of this
            # only respected the floor, which put the tab outside the aperture
            # on a narrow frame.
            #   floor:   grip_len * cos(a) > frame_d/2 + flange_t + 1
            #            or it retracts behind the flange at full travel and is
            #            unreachable inside the mounting hole
            #   ceiling: grip_len * sin(a) + grip_pad_w/2 + |blade_x| < aperture/2
            #            or it sweeps outside the flange aperture
            grip_pad_w = float(given("grip_pad_w_mm", 8.0))
            sin_a = math.sin(math.radians(max_angle))
            idx = int(d["grip_blade"])
            pitch_now = aperture / n_blades if n_blades else 0.0
            blade_x = abs(-aperture / 2 + pitch_now * (idx + 0.5)) if pitch_now else 0.0

            floor = (frame_d / 2 + flange_t + 1.0) / cos_a
            room = aperture / 2 - grip_pad_w / 2 - blade_x
            ceiling = room / sin_a if sin_a > 0 and room > 0 else floor * 1.13

            want = floor * 1.13          # 20.08 mm at the reference frame
            d["grip_len_mm"] = round(max(floor * 1.02, min(want, ceiling * 0.9)), 3)

        return d

    # ---- derived, exposed as read-only helpers ---------------------------

    @property
    def aperture_w_mm(self) -> float:
        return self.frame_w_mm - 2 * self.wall_mm

    @property
    def aperture_h_mm(self) -> float:
        return self.frame_h_mm - 2 * self.wall_mm

    @property
    def pitch_mm(self) -> float:
        return self.aperture_w_mm / self.n_blades

    @property
    def hub_dia_mm(self) -> float:
        return self.pin_dia_mm + 2 * self.pin_clear_r_mm + 2 * self.hub_wall_mm

    @property
    def crank_hub_dia_mm(self) -> float:
        return self.crank_pin_dia_mm + 2 * self.pin_clear_r_mm + 2 * self.crank_hub_wall_mm

    @property
    def blade_xs(self) -> list[float]:
        return [
            -self.aperture_w_mm / 2 + self.pitch_mm * (i + 0.5)
            for i in range(self.n_blades)
        ]

    def bar_offset(self, angle_deg: float) -> tuple[float, float]:
        """
        Where the tie bar sits for a given blade angle.

        A blade rotated by +angle about Z carries its crank socket from (0, R)
        to (-R sin, R cos). The bar must follow exactly that, hence the minus.
        """
        t = math.radians(angle_deg)
        return -self.crank_r_mm * math.sin(t), self.crank_r_mm * math.cos(t)

    # ---- the mechanism checks --------------------------------------------

    @model_validator(mode="after")
    def _mechanism_is_buildable(self) -> "LouvreVentParams":
        if self.wall_mm * 2 >= self.frame_h_mm:
            raise ValueError(
                "wall_mm %.2f x 2 leaves no aperture in a frame_h_mm of %.2f. "
                "Legal: wall_mm must be under %.2f."
                % (self.wall_mm, self.frame_h_mm, self.frame_h_mm / 2)
            )
        if self.wall_mm * 2 >= self.frame_w_mm:
            raise ValueError(
                "wall_mm %.2f x 2 leaves no aperture in a frame_w_mm of %.2f."
                % (self.wall_mm, self.frame_w_mm)
            )
        if self.hub_dia_mm >= self.pitch_mm:
            raise ValueError(
                "pivot hub %.2f mm exceeds the blade pitch %.2f mm, so adjacent "
                "hubs collide. Legal: reduce pin_dia_mm, pin_clear_r_mm or "
                "hub_wall_mm, or use fewer blades."
                % (self.hub_dia_mm, self.pitch_mm)
            )
        if self.blade_chord_mm >= self.pitch_mm:
            # Name a value that WORKS, not just the boundary. The default chord
            # of 14.0 suits the reference frame (pitch 17.0) and is too wide for
            # any smaller one, so a person - or a model - asking for a narrower
            # vent hits this on the very first try and needs to be told what to
            # put, not merely what is forbidden. 0.82 is the reference's own
            # chord-to-pitch ratio.
            raise ValueError(
                "blade_chord_mm %.2f is at least the blade pitch %.2f, so the "
                "blades collide when they swing. The pitch comes from "
                "frame_w_mm, wall_mm and n_blades: (%.1f - 2 x %.1f) / %d = "
                "%.2f. Set blade_chord_mm to about %.1f, or leave it unset and "
                "it will be derived from the frame."
                % (self.blade_chord_mm, self.pitch_mm, self.frame_w_mm,
                   self.wall_mm, self.n_blades, self.pitch_mm,
                   round(self.pitch_mm * CHORD_OF_PITCH, 1))
            )
        if self.crank_r_mm + self.crank_hub_dia_mm / 2 > self.blade_chord_mm / 2 + 0.2:
            raise ValueError(
                "the crank hub pokes past the blade trailing edge: crank_r_mm "
                "%.2f + half the crank hub %.2f exceeds half the chord %.2f "
                "plus 0.2. Legal: shorten crank_r_mm or lengthen blade_chord_mm."
                % (self.crank_r_mm, self.crank_hub_dia_mm / 2, self.blade_chord_mm / 2)
            )
        if abs(self.blade_angle_deg) > self.max_angle_deg:
            raise ValueError(
                "blade_angle_deg %.1f exceeds the mechanism limit max_angle_deg "
                "%.1f. Legal: -%.1f to %.1f."
                % (self.blade_angle_deg, self.max_angle_deg,
                   self.max_angle_deg, self.max_angle_deg)
            )

        _, y = self.bar_offset(self.max_angle_deg)
        margin = (y - self.bar_width_mm / 2) - (self.pin_dia_mm / 2 + self.pin_clear_r_mm)
        if margin <= 0.4:
            # This is where an over-ambitious blade count really surfaces, so
            # say so in those terms. Telling someone to "raise crank_r_mm" when
            # the real problem is that eight blades will not fit in the frame
            # sends them round the cascade one more time.
            cos_a = math.cos(math.radians(self.max_angle_deg))
            crank_floor = (
                0.4 + self.bar_width_mm / 2 + self.pin_dia_mm / 2 + self.pin_clear_r_mm
            ) / max(cos_a, 1e-9)
            pitch_floor = 2 * (crank_floor + CRANK_BELOW_HALF_CHORD_MM) / CHORD_OF_PITCH
            max_blades = int(self.aperture_w_mm // pitch_floor)
            raise ValueError(
                "the tie bar fouls the pivot pins at max_angle_deg: clearance "
                "%.3f mm, needs more than 0.4 mm. A %.0f mm frame with %.0f mm "
                "walls fits at most %d blade(s) with this linkage - set "
                "n_blades to %d or fewer, or leave n_blades, blade_chord_mm and "
                "crank_r_mm unset and they will all be derived to fit."
                % (margin, self.frame_w_mm, self.wall_mm, max(max_blades, 1),
                   max(max_blades, 1))
            )

        body_front = -self.frame_d_mm / 2
        grip_y = -self.grip_len_mm * math.cos(math.radians(self.max_angle_deg))
        if grip_y >= body_front - self.flange_t_mm - 1.0:
            raise ValueError(
                "the grip tab retracts behind the flange at max_angle_deg and "
                "would be unreachable inside the mounting hole. Legal: raise "
                "grip_len_mm above %.2f mm."
                % ((abs(body_front) + self.flange_t_mm + 1.0)
                   / math.cos(math.radians(self.max_angle_deg)))
            )
        if not 0 <= self.grip_blade < self.n_blades:
            raise ValueError(
                "grip_blade %d is out of range. Legal: 0 to %d."
                % (self.grip_blade, self.n_blades - 1)
            )
        sweep = (
            self.grip_len_mm * math.sin(math.radians(self.max_angle_deg))
            + self.grip_pad_w_mm / 2
            + abs(self.blade_xs[self.grip_blade])
        )
        if sweep >= self.aperture_w_mm / 2:
            # When grip_len_mm was derived, this means the frame is too narrow
            # for its own depth: the tab has to reach far enough forward to clear
            # a frame_d_mm-deep body plus its flange, and at max_angle_deg that
            # reach swings it outside the aperture. Saying "shorten grip_len_mm"
            # is not actionable when shortening it would put the tab out of
            # reach inside the mounting hole.
            reach = self.frame_d_mm / 2 + self.flange_t_mm + 1.0
            raise ValueError(
                "the grip tab sweeps %.2f mm from centre, outside the flange "
                "aperture half-width %.2f mm. The tab must reach %.1f mm forward "
                "to stay usable on a %.0f mm deep frame, and at %.0f degrees of "
                "travel that swings it too far sideways for a %.0f mm frame. "
                "Legal: widen frame_w_mm, reduce frame_d_mm, or reduce "
                "max_angle_deg."
                % (sweep, self.aperture_w_mm / 2, reach, self.frame_d_mm,
                   self.max_angle_deg, self.frame_w_mm)
            )
        return self


@dataclass
class _Derived:
    aperture_w: float
    aperture_h: float
    rail_bot_top: float
    rail_top_bot: float
    bar_z0: float
    bar_z1: float
    blade_z0: float
    blade_z1: float
    blade_h: float
    socket_dia: float
    socket_depth: float
    hub_dia: float
    crank_socket_dia: float
    crank_socket_depth: float
    crank_hub_dia: float
    pitch: float
    blade_xs: list[float]
    body_front: float
    flange_y0: float
    flange_w: float
    flange_h: float


def derive(p: LouvreVentParams) -> _Derived:
    """Mirror of the reference's DERIVED block, same order, same arithmetic."""
    aperture_w = p.frame_w_mm - 2 * p.wall_mm
    aperture_h = p.frame_h_mm - 2 * p.wall_mm

    rail_bot_top = p.wall_mm
    rail_top_bot = p.frame_h_mm - p.wall_mm

    bar_z0 = rail_bot_top + p.pin_gap_z_mm
    bar_z1 = bar_z0 + p.bar_thick_mm
    blade_z0 = bar_z1 + p.pin_gap_z_mm
    blade_z1 = rail_top_bot - p.pin_gap_z_mm

    socket_dia = p.pin_dia_mm + 2 * p.pin_clear_r_mm
    crank_socket_dia = p.crank_pin_dia_mm + 2 * p.pin_clear_r_mm

    body_front = -p.frame_d_mm / 2

    return _Derived(
        aperture_w=aperture_w,
        aperture_h=aperture_h,
        rail_bot_top=rail_bot_top,
        rail_top_bot=rail_top_bot,
        bar_z0=bar_z0,
        bar_z1=bar_z1,
        blade_z0=blade_z0,
        blade_z1=blade_z1,
        blade_h=blade_z1 - blade_z0,
        socket_dia=socket_dia,
        socket_depth=p.pin_engage_mm + p.socket_extra_mm,
        hub_dia=socket_dia + 2 * p.hub_wall_mm,
        crank_socket_dia=crank_socket_dia,
        crank_socket_depth=p.crank_engage_mm + p.socket_extra_mm,
        crank_hub_dia=crank_socket_dia + 2 * p.crank_hub_wall_mm,
        pitch=aperture_w / p.n_blades,
        blade_xs=p.blade_xs,
        body_front=body_front,
        flange_y0=body_front - p.flange_t_mm,
        flange_w=p.frame_w_mm + 2 * p.flange_over_mm,
        # Flush with the bed at the bottom. A symmetric flange would need the
        # lower lip to print in mid-air; this way the overhangs are left, right
        # and top only.
        flange_h=p.frame_h_mm + p.flange_over_mm,
    )


def make_frame(p: LouvreVentParams, d: _Derived) -> cq.Workplane:
    """Body plus flange, with the airflow aperture and the screw holes."""
    body = (cq.Workplane("XY").rect(p.frame_w_mm, p.frame_d_mm).extrude(p.frame_h_mm)
            .edges("|Z").fillet(p.bezel_r_mm))

    # An XZ workplane extrudes along -Y, so start at the body front face and the
    # flange grows forward, fusing to the body.
    flange = (cq.Workplane("XZ").workplane(offset=-d.body_front)
              .center(0, d.flange_h / 2)
              .rect(d.flange_w, d.flange_h).extrude(p.flange_t_mm)
              .edges("|Y").fillet(p.bezel_r_mm * 2))
    frame = body.union(flange)

    aperture = (cq.Workplane("XY").workplane(offset=p.wall_mm)
                .rect(d.aperture_w, p.frame_d_mm + 2 * p.flange_t_mm + 4)
                .extrude(d.aperture_h))
    frame = frame.cut(aperture)

    x_screw = p.frame_w_mm / 2 + p.flange_over_mm / 2
    for sx in (-x_screw, x_screw):
        hole = (cq.Workplane("XZ").workplane(offset=-d.flange_y0 - 1)
                .center(sx, p.frame_h_mm / 2)
                .circle(p.screw_dia_mm / 2).extrude(p.flange_t_mm + 2))
        frame = frame.cut(hole)

    # Integral pivot pins rising from the bottom rail.
    for x in d.blade_xs:
        pin = (cq.Workplane("XY").workplane(offset=d.rail_bot_top)
               .center(x, 0).circle(p.pin_dia_mm / 2)
               .extrude(d.blade_z0 - d.rail_bot_top + p.pin_engage_mm))
        frame = frame.union(pin)

    # Sockets bored up into the top rail.
    for x in d.blade_xs:
        sk = (cq.Workplane("XY").workplane(offset=d.rail_top_bot - 0.01)
              .center(x, 0).circle(d.socket_dia / 2).extrude(d.socket_depth))
        frame = frame.cut(sk)

    return frame


def make_blade(p: LouvreVentParams, d: _Derived, x_pos: float, angle: float,
               grip: bool = False) -> cq.Workplane:
    """Plate, pivot hub and crank hub; sockets underneath, pivot pin on top."""
    plate = (cq.Workplane("XY").workplane(offset=d.blade_z0)
             .rect(p.blade_thick_mm, p.blade_chord_mm).extrude(d.blade_h)
             .edges("|Z").fillet(min(p.blade_tip_r_mm, p.blade_thick_mm / 2 - 0.05)))

    hub = (cq.Workplane("XY").workplane(offset=d.blade_z0)
           .circle(d.hub_dia / 2).extrude(d.blade_h))
    crank_hub = (cq.Workplane("XY").workplane(offset=d.blade_z0)
                 .center(0, p.crank_r_mm).circle(d.crank_hub_dia / 2)
                 .extrude(d.blade_h))
    blade = plate.union(hub).union(crank_hub)

    if grip:
        # Stem reaching forward from the leading edge, out past the flange.
        stem_len = p.grip_len_mm - p.blade_chord_mm / 2
        stem = (cq.Workplane("XY").workplane(offset=d.blade_z0)
                .center(0, -(p.blade_chord_mm / 2 + stem_len / 2))
                .rect(p.grip_w_mm, stem_len).extrude(d.blade_h))
        pad = (cq.Workplane("XY").workplane(offset=d.blade_z0)
               .center(0, -(p.grip_len_mm - p.grip_pad_d_mm / 2))
               .rect(p.grip_pad_w_mm, p.grip_pad_d_mm).extrude(d.blade_h)
               .edges("|Z").fillet(p.grip_pad_d_mm / 2.5))
        blade = blade.union(stem).union(pad)

    blade = blade.cut(cq.Workplane("XY").workplane(offset=d.blade_z0 - 0.01)
                      .circle(d.socket_dia / 2).extrude(d.socket_depth))
    blade = blade.cut(cq.Workplane("XY").workplane(offset=d.blade_z0 - 0.01)
                      .center(0, p.crank_r_mm).circle(d.crank_socket_dia / 2)
                      .extrude(d.crank_socket_depth))
    blade = blade.union(cq.Workplane("XY").workplane(offset=d.blade_z1)
                        .circle(p.pin_dia_mm / 2)
                        .extrude(p.pin_gap_z_mm + p.pin_engage_mm))

    blade = blade.rotate((0, 0, 0), (0, 0, 1), angle)
    return blade.translate((x_pos, 0, 0))


def make_tie_bar(p: LouvreVentParams, d: _Derived, angle: float) -> cq.Workplane:
    """Tie bar with one crank pin per blade. Fully enclosed, no exit knob."""
    dx, y = p.bar_offset(angle)
    x_lo = d.blade_xs[0] - p.bar_tail_mm
    x_hi = d.blade_xs[-1] + p.bar_tail_mm
    length = x_hi - x_lo

    bar = (cq.Workplane("XY")
           .workplane(offset=d.bar_z0)
           .center((x_lo + x_hi) / 2, 0)
           .rect(length, p.bar_width_mm).extrude(p.bar_thick_mm)
           .edges("|Z").fillet(p.bar_width_mm / 3))

    for x in d.blade_xs:
        pin = (cq.Workplane("XY").workplane(offset=d.bar_z1)
               .center(x, 0).circle(p.crank_pin_dia_mm / 2)
               .extrude(p.pin_gap_z_mm + p.crank_engage_mm))
        bar = bar.union(pin)

    return bar.translate((dx, y, 0))


def build_core(p: LouvreVentParams, d: _Derived, log: BuildLog,
               angle: float | None = None) -> cq.Workplane:
    """
    ASSEMBLED orientation, which for a print-in-place part is also how it
    prints. See build_print.

    Assembled as a COMPOUND, not a boolean union. The bodies are deliberately
    disjoint - pin_gap_z_mm of air at every shoulder - so union() is both
    semantically wrong and numerically fragile: it intermittently fused parts
    that are 0.3 mm apart, turning a working linkage into one welded lump.
    """
    a = p.blade_angle_deg if angle is None else angle
    parts = [make_frame(p, d)]
    parts += [make_blade(p, d, x, a, grip=(i == p.grip_blade))
              for i, x in enumerate(d.blade_xs)]
    parts.append(make_tie_bar(p, d, a))
    return compound_of(parts)


def build_print(core: cq.Workplane) -> cq.Workplane:
    """
    PRINT orientation: as modelled, flange edge-on, frame flat on the bed.

    Same as assembled here because the mechanism is designed to print in place.
    Kept separate anyway - deriving one orientation from the other by rotation
    is the mistake this project keeps a rule about.
    """
    return core


def build(params: LouvreVentParams, spec, base_dir: Path | None = None):
    """Template entry point. Returns a BuildResult."""
    from bpcad.build.helpers import BuildResult

    d = derive(params)
    log = BuildLog()
    core = build_core(params, d, log)

    _, bar_y = params.bar_offset(params.max_angle_deg)
    bar_clearance = (bar_y - params.bar_width_mm / 2) - (
        params.pin_dia_mm / 2 + params.pin_clear_r_mm
    )
    grip_y = -params.grip_len_mm * math.cos(math.radians(params.max_angle_deg))

    # SOLID features only. A clearance is not a feature size: the linter's rule
    # is "must exceed the nozzle", and a fit clearance wants the opposite - the
    # 0.30 mm pin clearance and the 0.30 mm print-in-place gap are correct
    # precisely because they are under a nozzle width. Feeding them to
    # check_features reports two loud failures on a part that prints perfectly.
    # Gaps are reported under `derived` instead, where they are visible without
    # being measured against the wrong rule.
    features = {
        "wall": params.wall_mm,
        "flange thickness": params.flange_t_mm,
        "blade thickness": params.blade_thick_mm,
        "tie bar width": params.bar_width_mm,
        "crank pin diameter": params.crank_pin_dia_mm,
        "pivot pin diameter": params.pin_dia_mm,
        "grip tab thickness": params.grip_w_mm,
    }

    log.notes.append(
        "bodies are a compound, not a union - they are meant to be separate"
    )

    return BuildResult(
        solid=core,
        print_solid=build_print(core),
        features=features,
        log=log,
        assumptions=[],
        scale_departures=[],
        derived={
            "pin_radial_clearance_mm": params.pin_clear_r_mm,
            "print_in_place_gap_mm": params.pin_gap_z_mm,
            "tie_bar_to_pivot_clearance_mm": bar_clearance,
            "aperture_w_mm": d.aperture_w,
            "aperture_h_mm": d.aperture_h,
            "blade_pitch_mm": d.pitch,
            "bar_throw_mm": abs(params.bar_offset(params.max_angle_deg)[0]),
            "cut_hole_w_mm": params.frame_w_mm + params.body_clear_mm,
            "cut_hole_h_mm": params.frame_h_mm + params.body_clear_mm,
            "grip_proud_at_rest_mm": (d.body_front - params.flange_t_mm) - (-params.grip_len_mm),
            "grip_proud_at_full_travel_mm": (d.body_front - params.flange_t_mm) - grip_y,
        },
        body_count_expected=params.n_blades + 2,
        # No body roles. This is a print-in-place mechanism: the pieces are
        # nested inside one another, they are printed together in one go, and
        # they cannot be laid out left to right - so there is no ordering that
        # would let them be named reliably, and no reason to split them into
        # separate files.
        nominal_mm=(params.frame_w_mm, params.frame_d_mm, params.frame_h_mm),
    )


register(Template(
    name="louvre_vent",
    summary="Print-in-place adjustable louvre vent with a parallel-crank linkage.",
    makes=(
        "vent", "louvre vent", "air vent", "grille", "register", "airbrick",
        "adjustable vent", "shutter", "damper", "cupboard vent", "wall vent",
    ),
    params_model=LouvreVentParams,
    builder=build,
    anchors=("flange_face", "aperture", "bottom_rail_top", "top_rail_bottom"),
    print_notes=(
        "Orientation: as modelled, flange edge-on, frame flat on the bed.",
        "Layer height 0.20 mm.",
        "PETG or ABS. PLA creeps and the blades go slack.",
        "No supports. Every print-in-place gap is bridged by the layer above it.",
        "After printing, work the knob back and forth a few times to free the pins.",
        "Cut your mounting hole body_clear_mm over the body size.",
    ),
))
