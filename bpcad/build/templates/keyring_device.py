"""
Keyring device template. Ported from reference/rain_loop_keyring.py.

WHAT THE PART IS
----------------
A one-piece keyring: body, fused handle and bosses are a single 2D silhouette
pushed out to one constant thickness. Printed flat on its back, every surface
is horizontal or vertical - zero overhangs, zero supports, nothing to glue, and
the face detail sits on the top surface where an FDM printer resolves it best.

The handle is fused rather than pivoted and doubles as the split-ring loop. The
bosses, which are pivot knobs on the real device, become the fillet-blended pad
carrying the pull load from the handle into the body - exactly where a thin
keyring snaps.

WHAT IS A PARAMETER AND WHAT IS A MEASUREMENT
---------------------------------------------
The PIXEL MEASUREMENTS below are not preferences. They were measured off a
650 x 855 product render by segmentation - see bpcad.measure and Phase 2 - and
they define the shape. Do not edit them unless you re-measure. Everything in
KeyringDeviceParams is a real parameter: change it and you get a different but
still correct part.

TWO DELIBERATE OVERSIZES, BOTH REPORTED EVERY BUILD
---------------------------------------------------
At true proportion the handle rod is 0.90 mm and the logo bar stroke is
0.21 mm. Both are under a 0.40 mm nozzle, so both are drawn oversize. These are
the only places this model knowingly departs from the render, and the factor is
reported every time so you always know how far off you are.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

import cadquery as cq
from pydantic import Field, model_validator

from bpcad.build.helpers import (
    BuildLog,
    clip,
    clip_y,
    disc,
    poly_prism,
    rrect,
    safe_fillet_radius,
    try_edge_op,
)
from bpcad.spec.registry import Template, register
from bpcad.spec.schema import TemplateParams

# ---------------------------------------------------------------------------
# PIXEL MEASUREMENTS   source: the 650 x 855 product render in reference/
# Measured, not estimated. Do not edit unless you re-measure.
# ---------------------------------------------------------------------------

BODY_L_PX, BODY_R_PX = 43, 609
BODY_T_PX, BODY_B_PX = 283, 835
WAIST_L_PX, WAIST_R_PX = 52, 596

TRIM_TOP_ROWS = (284, 293)
TRIM_BOT_ROWS = (825, 834)

MODULE_L_PX, MODULE_R_PX = 216, 442
MODULE_T_PX, MODULE_B_PX = 294, 729
MODULE_CORNER_R_PX = 55

GLASS_L_PX, GLASS_R_PX = 224, 435
GLASS_T_PX, GLASS_B_PX = 331, 718

HANDLE_ROD_D_PX = 17
HANDLE_APEX_ROW = 20
PIVOT_ROW = 337
HALF_SPAN_PX = 285.5
BOSS_D_PX = 50

# ASSUMPTIONS - invisible from a front-on view, so they could not be measured.
# They are declared as Assumption entries by the builder and appear in the
# report under a heading that says so.
PLAN_CORNER_R_PX = 30
LOGO_CENTRE_Y_PX = 58

BODY_W_PX = BODY_R_PX - BODY_L_PX + 1

# Screen UI, engraved as raised cards on the glass floor. Positions measured off
# the render in glass-relative pixels; the glass is 212 x 388 px.
UI_GLASS_PX = (212, 388)
UI_ELEMENTS_DEFAULT: list[tuple[int, int, int, int, str]] = [
    # (x0, y0, x1, y1, kind)  y measured DOWN from the glass top
    (9, 23, 120, 65, "card"),      # clock card
    # Menu toggle. LEAST CERTAIN ELEMENT: its left edge is green against a green
    # wallpaper so it will not segment. Two methods both give ~40x43 px, i.e.
    # squarish, though by eye it reads as a wider pill. With the real UI asset,
    # use (134, 23, 204, 65).
    (168, 23, 205, 65, "pill"),    # menu toggle
    (9, 73, 42, 167, "card"),      # weather
    (49, 73, 127, 167, "card"),    # 5G
    (130, 73, 192, 167, "card"),   # loopzone
    (10, 285, 198, 309, "pill"),   # search bar
    (15, 337, 40, 361, "dot"),     # dock icons
    (54, 337, 78, 361, "dot"),
    (92, 337, 117, 361, "dot"),
    (130, 337, 155, 361, "dot"),
    (169, 337, 194, 361, "dot"),
]
UI_CARD_R_PX = 10


class KeyringDeviceParams(TemplateParams):
    """Every dimension carries its unit in the name. Every field has bounds."""

    body_width_mm: float = Field(
        30.0, gt=10.0, le=200.0,
        description=(
            "Overall body width across the trim caps. At 30 mm the glass side "
            "bezel lands on exactly one extrusion width; below 26 mm drop the "
            "screen detail entirely."
        ),
    )
    depth_mm: float = Field(
        7.0, gt=1.0, le=40.0,
        description="Single constant thickness of the whole part.",
    )
    min_handle_mm: float = Field(
        2.40, gt=0.0, le=20.0,
        description="Thinnest handle section that survives a keychain. Below 2.4 it snaps.",
    )
    min_stroke_mm: float = Field(
        0.45, gt=0.0, le=5.0,
        description="Thinnest engraved or embossed line worth cutting.",
    )
    boss_margin_mm: float = Field(
        1.00, ge=0.0, le=10.0,
        description="How far the boss must reach past the handle on each side.",
    )
    recess_mm: float = Field(
        0.55, gt=0.0, le=10.0,
        description=(
            "Module pocket depth, i.e. the bezel step. Deliberately deeper than "
            "true scale: a scale-correct 0.44 mm recess is geometrically right "
            "and visually dead, with too little depth to catch a shadow."
        ),
    )
    glass_mm: float = Field(
        0.75, gt=0.0, le=10.0,
        description="Additional depth of the glass area inside the bezel.",
    )
    cam_mm: float = Field(0.45, gt=0.0, le=5.0, description="Camera dot depth.")
    front_chamfer_mm: float = Field(
        0.40, ge=0.0, le=5.0,
        description=(
            "Attempted and reverted if OCC produces an invalid solid, which it "
            "does on this silhouette. Set to 0 to stop trying. For elephant foot "
            "use your slicer's first-layer compensation instead - that is the "
            "correct fix and costs no geometry."
        ),
    )
    back_chamfer_mm: float = Field(0.00, ge=0.0, le=5.0, description="As above, back face.")

    logo_on: bool = Field(
        False,
        description=(
            "Engrave the traced wordmark. OFF by default because it requires "
            "logo_json, a file path that has to come from somewhere - a measured "
            "baseline showed this default costing an attempt on every keyring "
            "request that did not mention the logo. Set it true and point "
            "logo_json at the output of `bpcad measure trace`."
        ),
    )
    logo_json: str | None = Field(
        None,
        description=(
            "Path to traced logo outlines from `bpcad measure trace`. Relative "
            "paths resolve against the spec file. Required when logo_on."
        ),
    )
    logo_width_fraction: float = Field(
        0.185, gt=0.0, le=1.0,
        description="Logo width as a fraction of the fabric waist width.",
    )
    logo_depth_mm: float = Field(0.40, gt=0.0, le=5.0, description="Engraving depth.")
    logo_autoscale: bool = Field(
        True, description="Grow the logo until its thinnest stroke is printable."
    )

    ui_on: bool = Field(True, description="Engrave the screen UI as raised cards.")
    ui_raise_mm: float = Field(
        0.45, gt=0.0, le=5.0, description="How far the cards stand above the glass floor."
    )
    ui_shrink_mm: float = Field(
        0.03, ge=0.0, le=1.0,
        description="Shrink every element slightly to keep the gaps printable.",
    )

    @model_validator(mode="after")
    def _physically_possible(self) -> "KeyringDeviceParams":
        pocket = self.recess_mm + self.glass_mm + self.cam_mm
        if pocket >= self.depth_mm:
            raise ValueError(
                "the face detail is deeper than the part: recess_mm + glass_mm + "
                "cam_mm = %.3f mm but depth_mm is %.3f mm. The pocket would cut "
                "straight through. Legal: their sum must stay under depth_mm, and "
                "should stay under about a fifth of it."
                % (pocket, self.depth_mm)
            )
        if self.front_chamfer_mm + self.back_chamfer_mm >= self.depth_mm / 2.0:
            raise ValueError(
                "front_chamfer_mm + back_chamfer_mm = %.3f mm is at least half of "
                "depth_mm %.3f mm, which leaves no flat face between them. "
                "Legal: their sum must be under %.3f mm."
                % (self.front_chamfer_mm + self.back_chamfer_mm, self.depth_mm,
                   self.depth_mm / 2.0)
            )
        if self.logo_on and not self.logo_json:
            raise ValueError(
                "logo_on is true but logo_json is not set. Point it at the output "
                "of `bpcad measure trace <logo crop>`, or set logo_on: false."
            )
        if self.logo_on and self.logo_depth_mm >= self.depth_mm:
            raise ValueError(
                "logo_depth_mm %.3f mm is at least the whole part thickness %.3f mm."
                % (self.logo_depth_mm, self.depth_mm)
            )
        return self


@dataclass
class _Derived:
    """
    Every derived dimension, in the order the reference computes them.

    Kept as a flat record rather than recomputed at each use, because the
    reference derives them once into globals and the ordering matters: the
    bezel guard modifies the glass width, and anything reading GLASS_W before
    that guard would get a different number.
    """

    scale: float
    W: float
    H: float
    T: float
    cap_b_h: float
    cap_t_h: float
    waist_w: float
    waist_y0: float
    waist_y1: float
    r_cap: float
    r_waist: float
    module_w: float
    module_y0: float
    module_y1: float
    module_r: float
    glass_w: float
    glass_y0: float
    glass_y1: float
    glass_r: float
    bezel_trim: float
    rod: float
    rod_factor: float
    true_rod: float
    pivot_y: float
    apex_y: float
    rise: float
    half_span: float
    arc_r: float
    arc_cy: float
    boss_d: float
    boss_factor: float
    true_boss: float
    logo_data: dict | None
    logo_w: float
    logo_stroke: float
    logo_factor: float
    logo_cy: float

    def px(self, v: float) -> float:
        return v * self.scale


def load_logo(path: str | Path) -> dict:
    """
    Read traced outlines and work out the thinnest stroke in them.

    A shape more than 2.5x wider than it is tall is a bar, so its height is the
    stroke. That is what decides whether the wordmark has to be drawn oversize.
    """
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(
            "no traced logo at %s. Produce one with: bpcad measure trace <logo crop> "
            "--out %s" % (p, p.name)
        )
    d = json.loads(p.read_text())
    if "shapes" not in d or not d["shapes"]:
        raise ValueError("%s contains no shapes - the trace found nothing" % p)

    strokes = []
    for sh in d["shapes"]:
        if sh["hole"]:
            continue
        xs = [q[0] for q in sh["pts"]]
        ys = [q[1] for q in sh["pts"]]
        w, h = max(xs) - min(xs), max(ys) - min(ys)
        if h > 1e-6 and w / h > 2.5:
            strokes.append(h)
    d["stroke"] = min(strokes) if strokes else 0.10
    return d


def derive(p: KeyringDeviceParams, nozzle_mm: float, base_dir: Path | None = None) -> _Derived:
    """Mirror of the reference's derive(), same order, same arithmetic."""
    scale = p.body_width_mm / BODY_W_PX

    def px(v: float) -> float:
        return v * scale

    W = px(BODY_W_PX)
    H = px(BODY_B_PX - BODY_T_PX + 1)
    T = p.depth_mm

    cap_b_h = px(TRIM_BOT_ROWS[1] - TRIM_BOT_ROWS[0] + 1)
    cap_t_h = px(TRIM_TOP_ROWS[1] - TRIM_TOP_ROWS[0] + 1)
    waist_w = px(WAIST_R_PX - WAIST_L_PX + 1)
    waist_y0 = cap_b_h
    waist_y1 = H - cap_t_h
    r_cap = min(px(PLAN_CORNER_R_PX), cap_b_h * 0.42)
    r_waist = px(PLAN_CORNER_R_PX)

    def y_of(row: int) -> float:
        return px(BODY_B_PX - row)

    module_w = px(MODULE_R_PX - MODULE_L_PX + 1)
    module_y0 = y_of(MODULE_B_PX)
    module_y1 = y_of(MODULE_T_PX)
    module_r = px(MODULE_CORNER_R_PX)

    gw = px(GLASS_R_PX - GLASS_L_PX + 1)
    gy0, gy1 = y_of(GLASS_B_PX), y_of(GLASS_T_PX)
    # Guard: keep the bezel at or above one extrusion width by pulling the glass
    # in. Costs a few hundredths of a mm and is the difference between a visible
    # bezel and a smeared edge.
    short = nozzle_mm - (module_w - gw) / 2.0
    if short > 0:
        gw -= 2 * short
        gy0 += short
        bezel_trim = short
    else:
        bezel_trim = 0.0
    glass_w = gw
    glass_y0 = gy0
    glass_y1 = gy1
    glass_r = max(module_r - (module_w - glass_w) / 2.0, 0.4)

    # Handle: true-scale arc, oversized section.
    true_rod = px(HANDLE_ROD_D_PX)
    rod = max(true_rod, p.min_handle_mm)
    rod_factor = rod / true_rod

    pivot_y = y_of(PIVOT_ROW)
    apex_y = y_of(HANDLE_APEX_ROW)
    rise = apex_y - pivot_y
    # Half-span straight off the render. The arc is fused rather than pivoted,
    # so it needs no side clearance.
    half_span = px(HALF_SPAN_PX)
    c = half_span
    arc_r = (c * c + rise * rise) / (2 * rise)
    arc_cy = apex_y - arc_r

    true_boss = px(BOSS_D_PX)
    need = rod + 2 * p.boss_margin_mm
    boss_d = max(true_boss, need)
    boss_factor = boss_d / true_boss

    logo_data = None
    logo_w = logo_stroke = 0.0
    logo_factor = 1.0
    if p.logo_on:
        path = Path(p.logo_json)
        if not path.is_absolute() and base_dir is not None:
            path = Path(base_dir) / path
        logo_data = load_logo(path)
        want = p.logo_width_fraction * waist_w
        stroke_norm = logo_data["stroke"]
        if p.logo_autoscale and stroke_norm * want < p.min_stroke_mm:
            logo_factor = p.min_stroke_mm / (stroke_norm * want)
        logo_w = want * logo_factor
        logo_stroke = stroke_norm * logo_w

    return _Derived(
        scale=scale, W=W, H=H, T=T,
        cap_b_h=cap_b_h, cap_t_h=cap_t_h, waist_w=waist_w,
        waist_y0=waist_y0, waist_y1=waist_y1, r_cap=r_cap, r_waist=r_waist,
        module_w=module_w, module_y0=module_y0, module_y1=module_y1, module_r=module_r,
        glass_w=glass_w, glass_y0=glass_y0, glass_y1=glass_y1, glass_r=glass_r,
        bezel_trim=bezel_trim,
        rod=rod, rod_factor=rod_factor, true_rod=true_rod,
        pivot_y=pivot_y, apex_y=apex_y, rise=rise, half_span=half_span,
        arc_r=arc_r, arc_cy=arc_cy,
        boss_d=boss_d, boss_factor=boss_factor, true_boss=true_boss,
        logo_data=logo_data, logo_w=logo_w, logo_stroke=logo_stroke,
        logo_factor=logo_factor, logo_cy=px(LOGO_CENTRE_Y_PX),
    )


def _engrave_logo(part: cq.Workplane, p: KeyringDeviceParams, d: _Derived) -> cq.Workplane:
    """Cut the traced outlines into the front face, then restore the counters."""
    data = d.logo_data
    sc = d.logo_w
    ox = -sc / 2.0
    oy = d.logo_cy - data["aspect_h"] * sc / 2.0
    z0 = d.T - p.logo_depth_mm
    t = p.logo_depth_mm + 1.0

    cut = None
    for sh in data["shapes"]:
        if sh["hole"]:
            continue
        pr = poly_prism(sh["pts"], sc, ox, oy, z0, t)
        cut = pr if cut is None else cut.union(pr)
    part = part.cut(cut)

    # The counters of o, o and p: put the material back.
    for sh in data["shapes"]:
        if not sh["hole"]:
            continue
        part = part.union(poly_prism(sh["pts"], sc, ox, oy, z0, p.logo_depth_mm))
    return part


def _engrave_ui(
    part: cq.Workplane,
    p: KeyringDeviceParams,
    d: _Derived,
    elements: list[tuple[int, int, int, int, str]],
) -> cq.Workplane:
    """Raised cards standing on the glass pocket floor, per the render."""
    gw, gh = UI_GLASS_PX
    ppx = d.glass_w / float(gw)
    ppy = (d.glass_y1 - d.glass_y0) / float(gh)
    floor = d.T - p.recess_mm - p.glass_mm
    sh = p.ui_shrink_mm

    add = None
    for x0, y0, x1, y1, kind in elements:
        mx0 = -d.glass_w / 2.0 + x0 * ppx + sh
        mx1 = -d.glass_w / 2.0 + x1 * ppx - sh
        my1 = d.glass_y1 - y0 * ppy - sh
        my0 = d.glass_y1 - y1 * ppy + sh
        w, h = mx1 - mx0, my1 - my0
        if w <= 0 or h <= 0:
            continue
        cx, cy = (mx0 + mx1) / 2.0, (my0 + my1) / 2.0

        if kind == "dot":
            e = (cq.Workplane("XY", origin=(cx, cy, floor))
                 .circle(min(w, h) / 2.0).extrude(p.ui_raise_mm))
        else:
            r = min(h / 2.0, w / 2.0) if kind == "pill" else UI_CARD_R_PX * ppx
            r = safe_fillet_radius(r, w, h)
            e = cq.Workplane("XY").box(w, h, p.ui_raise_mm, centered=(True, True, False))
            # Shrink the radius until OCC accepts it rather than failing the
            # element. A UI card is cosmetic; losing it to a fillet is not.
            while r > 0.04:
                try:
                    e = e.edges("|Z").fillet(r)
                    break
                except Exception:
                    r *= 0.6
            e = e.translate((cx, cy, floor))
        add = e if add is None else add.union(e)
    return part.union(add)


def build_core(
    p: KeyringDeviceParams,
    d: _Derived,
    log: BuildLog,
    elements: list[tuple[int, int, int, int, str]] | None = None,
) -> cq.Workplane:
    """
    ASSEMBLED orientation. Every solid is a 2D profile in XY extruded +Z from 0.

    Print orientation is a separate function - see build_print. Never derive one
    from the other by rotation: doing that once put a part 1.2 mm off its mating
    face.
    """
    elements = UI_ELEMENTS_DEFAULT if elements is None else elements

    # Small union overlap so the booleans stay clean.
    ov = max(0.30 * d.scale * 100, 0.05)

    # --- silhouette -------------------------------------------------------
    waist = rrect(d.waist_w, d.waist_y1 - d.waist_y0, d.r_waist, d.waist_y0, d.T)
    cap_b = rrect(d.W, d.cap_b_h + ov, d.r_cap, 0.0, d.T)
    cap_t = rrect(d.W, d.cap_t_h + ov, d.r_cap, d.H - d.cap_t_h - ov, d.T)
    part = waist.union(cap_b).union(cap_t)

    # Handle: an annulus clipped to the pivot line gives exactly the render's arc.
    ring = (disc(2 * (d.arc_r + d.rod / 2.0), 0, d.arc_cy, d.T)
            .cut(disc(2 * (d.arc_r - d.rod / 2.0), 0, d.arc_cy, d.T)))
    part = part.union(clip(ring, "y", d.pivot_y, keep="above"))

    # The bosses carry the pull load from the handle into the body.
    for sx in (-1, 1):
        part = part.union(disc(d.boss_d, sx * d.half_span, d.pivot_y, d.T))

    # Blend the boss into the body: this is the joint that would otherwise fail.
    part = try_edge_op(part, "|Z", "fillet", d.rod * 0.30, "boss-to-body blend", log)

    # --- face detail ------------------------------------------------------
    # Module pocket: rounded bottom corners, squared off flush with the waist
    # top. All four corners are filleted and the square end is pushed past the
    # region of interest so the boolean trims the unwanted pair away.
    pocket = rrect(d.module_w, (d.module_y1 - d.module_y0) + d.module_r + 2.0,
                   d.module_r, d.module_y0, p.recess_mm + 1.0, z0=d.T - p.recess_mm)
    part = part.cut(clip_y(pocket, d.module_y1))

    glass = rrect(d.glass_w, (d.glass_y1 - d.glass_y0) + d.glass_r + 2.0,
                  d.glass_r, d.glass_y0, p.glass_mm + 1.0,
                  z0=d.T - p.recess_mm - p.glass_mm)
    part = part.cut(clip_y(glass, d.glass_y1))

    cam_y = d.glass_y1 + d.px(18)
    if cam_y < d.module_y1 - d.px(10):
        part = part.cut(disc(max(d.px(14), 0.40 * 1.5), 0, cam_y, p.cam_mm + 1.0,
                             z0=d.T - p.recess_mm - p.cam_mm))

    if p.ui_on:
        part = _engrave_ui(part, p, d, elements)
    if p.logo_on:
        part = _engrave_logo(part, p, d)

    # --- edge treatment LAST, so a failure here cannot break the detail ----
    part = try_edge_op(part, "<Z", "chamfer", p.back_chamfer_mm, "back edge", log)
    part = try_edge_op(part, ">Z", "chamfer", p.front_chamfer_mm, "front edge", log)
    return part


def build_print(core: cq.Workplane) -> cq.Workplane:
    """
    PRINT orientation.

    For this part it is the same as assembled, and that is a design property
    rather than an accident: the whole point is a constant-depth extrusion that
    prints flat on its back with no rotation. Kept as its own function anyway,
    because deriving one orientation from the other by rotation is the mistake
    this project keeps a rule about.
    """
    return core


def _ui_feature_sizes(
    p: KeyringDeviceParams, d: _Derived, elements: list
) -> tuple[float, float]:
    """Smallest UI element and smallest gap between elements, in mm."""
    gw, gh = UI_GLASS_PX
    ppx = d.glass_w / float(gw)
    sizes = [
        min((x1 - x0) * ppx, (y1 - y0) * (d.glass_y1 - d.glass_y0) / gh)
        - 2 * p.ui_shrink_mm
        for x0, y0, x1, y1, _ in elements
    ]
    xs = sorted((x0, x1) for x0, _, x1, _, _ in elements)
    gaps = [
        (b[0] - a[1]) * ppx + 2 * p.ui_shrink_mm
        for a, b in zip(xs, xs[1:])
        if b[0] > a[1]
    ]
    return (min(sizes) if sizes else 99.0, min(gaps) if gaps else 99.0)


def build(params: KeyringDeviceParams, spec, base_dir: Path | None = None):
    """Template entry point. Returns a BuildResult."""
    from bpcad.build.helpers import BuildResult
    from bpcad.spec.schema import Assumption, ScaleDeparture

    d = derive(params, spec.nozzle_mm, base_dir)
    log = BuildLog()
    core = build_core(params, d, log)

    features = {
        "glass side bezel": (d.module_w - d.glass_w) / 2.0,
        "glass bottom bezel": d.glass_y0 - d.module_y0,
        "trim cap band": d.cap_b_h,
        "waist/cap step": (d.W - d.waist_w) / 2.0,
        "handle section": d.rod,
    }
    if params.logo_on:
        features["logo stroke"] = d.logo_stroke
    if params.ui_on:
        smallest, gap = _ui_feature_sizes(params, d, UI_ELEMENTS_DEFAULT)
        features["smallest UI element"] = smallest
        features["smallest UI gap"] = gap

    assumptions = [
        Assumption(
            name="plan_corner_radius_px",
            value=PLAN_CORNER_R_PX,
            units="px",
            why=(
                "The plan-view corner radius is invisible from a front-on render. "
                "One side-on photo with a ruler in frame fixes it permanently."
            ),
        ),
        Assumption(
            name="logo_centre_y_px",
            value=LOGO_CENTRE_Y_PX,
            units="px above the body bottom",
            why=(
                "The wordmark is too low-contrast against the fabric weave to "
                "segment its vertical position reliably."
            ),
        ),
    ]

    departures = [
        ScaleDeparture(
            name="handle section",
            factor=d.rod_factor,
            true_mm=d.true_rod,
            used_mm=d.rod,
            why="true scale puts the rod under the nozzle width, so it would not print",
        ),
        ScaleDeparture(
            name="boss diameter",
            factor=d.boss_factor,
            true_mm=d.true_boss,
            used_mm=d.boss_d,
            why="the boss must bridge the handle-to-body joint, which carries the pull load",
        ),
    ]
    if params.logo_on and d.logo_factor > 1.0:
        departures.append(
            ScaleDeparture(
                name="logo",
                factor=d.logo_factor,
                true_mm=d.logo_w / d.logo_factor,
                used_mm=d.logo_w,
                why="true scale puts the thinnest bar stroke under the minimum engravable line",
            )
        )
    if d.bezel_trim > 0:
        departures.append(
            ScaleDeparture(
                name="glass area",
                factor=1.0 + 2 * d.bezel_trim / d.glass_w,
                true_mm=d.glass_w + 2 * d.bezel_trim,
                used_mm=d.glass_w,
                why="glass pulled in %.3f mm per side to keep the bezel one extrusion wide"
                    % d.bezel_trim,
            )
        )

    return BuildResult(
        solid=core,
        print_solid=build_print(core),
        features=features,
        log=log,
        assumptions=assumptions,
        scale_departures=departures,
        derived={
            "scale_mm_per_px": d.scale,
            "body_width_mm": d.W,
            "body_height_mm": d.H,
            "thickness_mm": d.T,
            "arc_radius_mm": d.arc_r,
            "split_ring_clearance_mm": d.apex_y - d.rod - d.H,
        },
        body_count_expected=1,
    )


register(Template(
    name="keyring_device",
    summary="One-piece keyring: constant-depth extrusion, fused handle, engraved face detail.",
    makes=(
        "keyring", "key fob", "keychain", "tag", "luggage tag", "charm",
        "pendant", "badge", "engraved plaque",
    ),
    params_model=KeyringDeviceParams,
    builder=build,
    anchors=("front_face", "back_face", "module_pocket_floor", "glass_floor", "waist_side"),
    print_notes=(
        "Orientation: flat, back face on the bed. DO NOT ROTATE.",
        "Layer height 0.12 mm - the face detail is in Z, that is the whole point.",
        "PETG. A PLA keyring at this section will snap at the handle.",
        "4 walls, 100% infill. It is 6.5 cm3; solid costs nothing and a hollow keyring crushes.",
        "No supports. Ironing on the top surface only, if your slicer has it.",
        "Elephant foot: first-layer compensation 0.15 mm.",
    ),
))
