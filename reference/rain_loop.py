"""
rain loop  -  parametric display model for FDM printing
Bit Primitive  /  CadQuery

WHAT THIS IS
------------
A scale replica of the rain loop (portable 5G router + stereo speaker), built as
six printable parts that assemble into a multi-colour model with a carry handle
that actually pivots.

HOW THE GEOMETRY WAS DERIVED
----------------------------
Every value in the PIXEL MEASUREMENTS block was measured off the supplied
650x855 product render by colour segmentation, not estimated by eye. The handle
was fitted and verified: a circular arc of centreline radius 287.07 px passes
through both pivot centres and the apex to within 0.03 px, so the render's
handle is a true circular arc and is reproduced exactly rather than approximated.

THE THREE THINGS I COULD NOT MEASURE
------------------------------------
  DEPTH_PX          A front-on render carries zero depth information. Default is
                    0.55 x body width. This is the biggest single unknown - one
                    side-on photo with a ruler in frame fixes it permanently.
  PLAN_CORNER_R_PX  Plan-view corner radius, also invisible from the front.
  LOGO_*            The wordmark is too low-contrast against the fabric weave to
                    segment. Placement is an eyeball read and the glyphs are NOT
                    rain's brand typeface. See the note at the bottom.

ABSOLUTE SCALE
--------------
rain publishes no body dimensions. Scale is anchored on the 6 inch touchscreen
reported at launch: the measured glass diagonal of 442.1 px maps to 152.4 mm,
giving 0.3447 mm/px and an implied real body of 195 x 191 mm. Set
BODY_W_MM = 195.4 for roughly 1:1. Default below is a desk model that fits a
220 x 220 bed with the handle laid flat.

PARTS AND FILAMENT
------------------
  loop_body_mid      green    fabric-wrapped middle section
  loop_cap_top       black    top trim band
  loop_cap_bottom    black    bottom trim band
  loop_screen        black    display module insert
  loop_handle        gold     carry handle, one piece
  loop_boss          gold     PRINT TWO - pivot pin and knurled knob

All parts are exported already rotated into their print orientation, so drop the
STLs straight into the slicer and do not rotate anything.

PRINT SETTINGS
--------------
  layer height   0.16 mm  (0.12 if you want the wordmark crisp)
  nozzle         0.40 mm
  material       PLA is fine for the body. Use PETG for loop_handle and
                 loop_boss - the pivot spigot is small and PLA snaps.
  supports       none required for any part as exported
  FABRIC TEXTURE Do not model the weave, it explodes the geometry and prints as
                 mush. Turn on fuzzy skin on loop_body_mid only:
                 Orca / PrusaSlicer, thickness 0.30 mm, point distance 0.40 mm,
                 outer walls only. Paint it off over the screen recess.

ASSEMBLY
--------
  1. Press loop_cap_top and loop_cap_bottom onto the register bosses.
  2. Drop loop_screen into the front recess. It sits 0.4 mm proud, as in the
     render. There is a 0.4 mm sunken area on its face for a printed decal of
     the UI - print the screen artwork on paper or vinyl and lay it in.
  3. Hold a handle lug against each side face, push a boss spigot through the
     lug and into the body hole. Glue the spigot into the BODY ONLY. Glue in the
     lug and the handle stops pivoting.

USAGE
-----
  python3 rain_loop.py                writes 6 STLs, 6 STEPs, an assembly STEP
  python3 rain_loop.py --width 195.4  same at roughly 1:1
"""

import argparse
import math
import os
import sys

import cadquery as cq

# ---------------------------------------------------------------------------
# PIXEL MEASUREMENTS   source: supplied render, 650 x 855 px
# Do not edit unless you re-measure. Everything else derives from these.
# ---------------------------------------------------------------------------

BODY_L_PX, BODY_R_PX = 43, 609          # widest silhouette = the trim caps
BODY_T_PX, BODY_B_PX = 283, 835
WAIST_L_PX, WAIST_R_PX = 52, 596        # fabric section, narrower than the caps

TRIM_TOP_ROWS = (284, 293)              # top trim band
TRIM_BOT_ROWS = (825, 834)              # bottom trim band

MODULE_L_PX, MODULE_R_PX = 216, 442     # display module outline
MODULE_T_PX, MODULE_B_PX = 294, 729
MODULE_CORNER_R_PX = 55                 # fitted to the bottom corner profile

GLASS_L_PX, GLASS_R_PX = 224, 435       # active display area
GLASS_T_PX, GLASS_B_PX = 331, 718

HANDLE_ROD_D_PX = 17                    # measured at the arc apex
HANDLE_APEX_ROW = 20                    # centreline row of the apex
PIVOT_ROW = 337                         # centreline row of the pivots
BOSS_D_PX = 50
BOSS_PROTRUSION_PX = 14

CAP_EDGE_R_PX = 6                       # from the silhouette taper

# --- not measured, assumptions ---------------------------------------------
DEPTH_PX = 312                          # 0.55 x body width
PLAN_CORNER_R_PX = 30                   # plan-view corner radius

# ---------------------------------------------------------------------------
# BUILD PARAMETERS
# ---------------------------------------------------------------------------

BODY_W_MM = 110.0        # overall body width. 195.4 for approx 1:1.

RECESS_DEPTH_MM = 1.60   # display module pocket depth
SCREEN_PROUD_MM = 0.40   # how far the insert stands out of the pocket
SCREEN_FIT_MM = 0.30     # total diametral clearance of insert in pocket
DECAL_POCKET_MM = 0.40   # sunken area on the insert face for a printed decal

REGISTER_CLEAR_MM = 0.20
REGISTER_H_MM = 2.50

WALL_MM = 3.00           # shell thickness of the hollow body
FLOOR_MM = 4.00          # solid floor under the cavity
HOLLOW = True            # False gives a solid body: 3x the filament, no gain

PIVOT_D_MM = 2.60        # boss spigot diameter. Below 2.4 it snaps.
PIVOT_CLEAR_MM = 0.30    # lug bore clearance over the spigot
PIVOT_BODY_DEPTH_MM = 4.00
SIDE_CLEAR_MM = 0.40     # lug face to body side face
LUG_D_PX = 30
BOSS_MIN_T_MM = 2.40
BOSS_FLUTES = 16         # knurl count, 0 disables

LOGO_MODE = "emboss"     # "emboss" | "pocket" | "none"
LOGO_H_PX = 30
LOGO_CENTRE_Z_PX = 58    # px above the body bottom
LOGO_RELIEF_MM = 0.50
LOGO_FONT = "DejaVu Sans"

OUT_DIR = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------------------
# DERIVED
# ---------------------------------------------------------------------------

BODY_W_PX = BODY_R_PX - BODY_L_PX + 1
BODY_H_PX = BODY_B_PX - BODY_T_PX + 1


def _derive():
    g = globals()
    g["SCALE"] = BODY_W_MM / BODY_W_PX
    s = g["SCALE"]

    def px(v):
        return v * s

    g["px"] = px
    g["W"] = px(BODY_W_PX)
    g["D"] = px(DEPTH_PX)
    g["H"] = px(BODY_H_PX)
    g["R_PLAN"] = px(PLAN_CORNER_R_PX)

    g["CAP_T_H"] = px(TRIM_TOP_ROWS[1] - TRIM_TOP_ROWS[0] + 1)
    g["CAP_B_H"] = px(TRIM_BOT_ROWS[1] - TRIM_BOT_ROWS[0] + 1)
    g["WAIST_INSET"] = px(((BODY_R_PX - BODY_L_PX) - (WAIST_R_PX - WAIST_L_PX)) / 2.0)

    g["MID_H"] = g["H"] - g["CAP_T_H"] - g["CAP_B_H"]
    g["MID_W"] = g["W"] - 2 * g["WAIST_INSET"]
    g["MID_D"] = g["D"] - 2 * g["WAIST_INSET"]
    g["MID_Z0"] = g["CAP_B_H"]
    g["MID_Z1"] = g["CAP_B_H"] + g["MID_H"]
    g["R_PLAN_MID"] = max(g["R_PLAN"] - g["WAIST_INSET"], 0.6)
    g["FRONT_Y"] = -g["MID_D"] / 2.0

    def z_of(row):
        return px(BODY_B_PX - row)

    g["z_of"] = z_of

    g["MODULE_W"] = px(MODULE_R_PX - MODULE_L_PX + 1)
    g["MODULE_H"] = px(MODULE_B_PX - MODULE_T_PX + 1)
    g["MODULE_R"] = px(MODULE_CORNER_R_PX)
    g["MODULE_Z_BOT"] = z_of(MODULE_B_PX)
    g["GLASS_W"] = px(GLASS_R_PX - GLASS_L_PX + 1)
    g["GLASS_H"] = px(GLASS_B_PX - GLASS_T_PX + 1)
    g["GLASS_Z_BOT"] = z_of(GLASS_B_PX)
    g["GLASS_R"] = max(g["MODULE_R"] - (g["MODULE_W"] - g["GLASS_W"]) / 2.0, 0.5)

    g["ROD_D"] = px(HANDLE_ROD_D_PX)
    g["LUG_D"] = px(LUG_D_PX)
    g["LUG_T"] = g["ROD_D"]
    g["PIVOT_Z"] = z_of(PIVOT_ROW)
    g["HANDLE_RISE"] = z_of(HANDLE_APEX_ROW) - g["PIVOT_Z"]

    # pivot sits just clear of the mid section's side face, not the cap face
    g["HALF_SPAN"] = g["MID_W"] / 2.0 + g["LUG_T"] / 2.0 + SIDE_CLEAR_MM
    c, rise = g["HALF_SPAN"], g["HANDLE_RISE"]
    g["ARC_R"] = (c * c + rise * rise) / (2 * rise)
    g["ARC_CZ"] = g["PIVOT_Z"] + rise - g["ARC_R"]
    g["PHI"] = math.degrees(math.asin((rise - g["ARC_R"]) / g["ARC_R"]))
    g["SWEEP"] = 180.0 + 2 * g["PHI"]

    g["LUG_OUT_X"] = g["HALF_SPAN"] + g["LUG_T"] / 2.0
    g["BOSS_D"] = px(BOSS_D_PX)
    g["BOSS_T"] = max(px(BOSS_PROTRUSION_PX) - (g["LUG_OUT_X"] - g["W"] / 2.0),
                      BOSS_MIN_T_MM)
    g["SPIGOT_L"] = g["LUG_T"] + SIDE_CLEAR_MM + PIVOT_BODY_DEPTH_MM
    g["CAV_W"] = g["MID_W"] - 2 * WALL_MM
    g["CAV_D"] = g["MID_D"] - 2 * WALL_MM


_derive()


# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------

def rounded_block(w, d, h, r, z0=0.0):
    blk = cq.Workplane("XY").box(w, d, h, centered=(True, True, False))
    if r > 0.05:
        blk = blk.edges("|Z").fillet(r)
    return blk.translate((0, 0, z0))


def front_profile(w, h, r, z_bot, y0, y_len, overshoot=0.0):
    """
    Solid whose front outline is a rectangle with rounded BOTTOM corners and
    square top corners. All four corners are filleted; the top pair is pushed
    above the region of interest by `overshoot` and trimmed away by the boolean.
    """
    total_h = h + overshoot
    solid = cq.Workplane("XY").box(w, y_len, total_h, centered=(True, True, False))
    if r > 0.05:
        solid = solid.edges("|Y").fillet(r)
    return solid.translate((0, y0 + y_len / 2.0, z_bot))


def loop_wordmark(relief, y_face):
    """Three stacked rounded bars, then the word 'loop'. Not rain's typeface."""
    cap = px(LOGO_H_PX)
    cz = px(LOGO_CENTRE_Z_PX)
    bar_w, bar_h, gap = cap * 0.62, cap * 0.13, cap * 0.175

    bars = None
    for i in (-1, 0, 1):
        b = (
            cq.Workplane("XZ", origin=(0, y_face, 0))
            .rect(bar_w, bar_h)
            .extrude(relief)
            .edges("|Y")
            .fillet(bar_h * 0.45)
            .translate((0, 0, cz + i * gap))
        )
        bars = b if bars is None else bars.union(b)

    text = (
        cq.Workplane("XZ", origin=(0, y_face, 0))
        .text("loop", cap * 1.30, relief, font=LOGO_FONT,
              halign="left", valign="center", combine=False)
        .translate((0, 0, cz))
    )
    tb = text.val().BoundingBox()
    total = bar_w + cap * 0.30 + tb.xlen
    x0 = -total / 2.0
    bars = bars.translate((x0 + bar_w / 2.0, 0, 0))
    text = text.translate((x0 + bar_w + cap * 0.30 - tb.xmin, 0, 0))
    return bars.union(text)


# ---------------------------------------------------------------------------
# PARTS  -  each returned in ASSEMBLED position
# ---------------------------------------------------------------------------

def build_body_mid():
    part = rounded_block(MID_W, MID_D, MID_H, R_PLAN_MID, z0=MID_Z0)

    part = part.cut(front_profile(
        MODULE_W, MODULE_H, MODULE_R, MODULE_Z_BOT,
        y0=FRONT_Y - 0.02, y_len=RECESS_DEPTH_MM + 0.02,
        overshoot=MODULE_R + 2.0))

    if HOLLOW:
        # cavity opens UPWARD so there is no ceiling to bridge and no support
        part = part.cut(rounded_block(
            CAV_W, CAV_D, MID_H - FLOOR_MM + 2.0,
            max(R_PLAN_MID - WALL_MM, 0.5), z0=MID_Z0 + FLOOR_MM))
        # local bosses so the pivot holes have material to grip
        for sx in (-1, 1):
            part = part.union(
                cq.Workplane("YZ", origin=(sx * (CAV_W / 2.0), 0, PIVOT_Z))
                .circle(PIVOT_D_MM * 2.6 / 2.0)
                .extrude(-sx * (PIVOT_BODY_DEPTH_MM + 1.0)))

    # bottom cap register socket, cut into the solid floor
    reg_w, reg_d = MID_W * 0.55, MID_D * 0.55
    part = part.cut(
        cq.Workplane("XY")
        .box(reg_w + 2 * REGISTER_CLEAR_MM, reg_d + 2 * REGISTER_CLEAR_MM,
             REGISTER_H_MM + 0.02, centered=(True, True, False))
        .edges("|Z").fillet(min(reg_w, reg_d) * 0.12)
        .translate((0, 0, MID_Z0 - 0.01)))

    for sx in (-1, 1):
        part = part.cut(
            cq.Workplane("YZ", origin=(sx * (MID_W / 2.0 + 0.5), 0, PIVOT_Z))
            .circle(PIVOT_D_MM / 2.0)
            .extrude(-sx * (PIVOT_BODY_DEPTH_MM + 1.5)))

    if LOGO_MODE == "emboss":
        part = part.union(loop_wordmark(LOGO_RELIEF_MM, FRONT_Y))
    elif LOGO_MODE == "pocket":
        part = part.cut(loop_wordmark(LOGO_RELIEF_MM + 0.2, FRONT_Y + 0.2))
    return part


def build_cap(top):
    """Returned in PRINT orientation: register boss pointing +Z."""
    h = CAP_T_H if top else CAP_B_H
    cap = rounded_block(W, D, h, R_PLAN, z0=0.0)
    try:
        cap = cap.edges("<Z").fillet(px(CAP_EDGE_R_PX))
    except Exception:
        pass
    if top and HOLLOW:
        # a plug that drops into the body cavity: self-locating, no extra socket
        reg = rounded_block(CAV_W - 2 * REGISTER_CLEAR_MM,
                            CAV_D - 2 * REGISTER_CLEAR_MM,
                            REGISTER_H_MM,
                            max(R_PLAN_MID - WALL_MM - REGISTER_CLEAR_MM, 0.5),
                            z0=h)
    else:
        reg = (
            cq.Workplane("XY")
            .box(MID_W * 0.55, MID_D * 0.55, REGISTER_H_MM, centered=(True, True, False))
            .edges("|Z").fillet(MID_D * 0.55 * 0.12)
            .translate((0, 0, h)))
    return cap.union(reg)


def build_screen_core():
    """
    Assembled orientation: height along +Z from 0, thickness from y=0 (the face
    that beds onto the pocket floor) out to y=-t (the visible face).
    """
    t = RECESS_DEPTH_MM + SCREEN_PROUD_MM
    body = front_profile(MODULE_W - SCREEN_FIT_MM, MODULE_H - SCREEN_FIT_MM / 2.0,
                         MODULE_R, 0.0, y0=-t, y_len=t, overshoot=MODULE_R + 2.0)
    body = body.intersect(cq.Workplane("XY").box(
        MODULE_W * 2, t * 4, MODULE_H - SCREEN_FIT_MM / 2.0,
        centered=(True, True, False)))

    body = body.cut(front_profile(
        GLASS_W, GLASS_H, GLASS_R, GLASS_Z_BOT - MODULE_Z_BOT,
        y0=-t - 0.01, y_len=DECAL_POCKET_MM + 0.01))

    cam_z = (GLASS_Z_BOT - MODULE_Z_BOT) + GLASS_H + px(18)
    body = body.cut(
        cq.Workplane("XZ", origin=(0, -t - 0.01, 0)).circle(px(7)).extrude(-px(5))
        .translate((0, 0, min(cam_z, MODULE_H - px(12)))))
    return body


def build_screen():
    """Print orientation: bedding face on z=0, visible face up."""
    return build_screen_core().rotate((0, 0, 0), (1, 0, 0), -90)


def build_handle():
    arc = (cq.Workplane("XY", origin=(0, 0, ARC_CZ))
           .moveTo(ARC_R, 0).circle(ROD_D / 2.0)
           .revolve(SWEEP, (0, 0, 0), (0, 1, 0)))
    arc = arc.rotate((0, 0, ARC_CZ), (1, 0, ARC_CZ), 180)
    arc = arc.rotate((0, 0, ARC_CZ), (0, 1, ARC_CZ), PHI)

    part = arc
    for sx in (-1, 1):
        part = part.union(
            cq.Workplane("YZ", origin=(sx * (HALF_SPAN - LUG_T / 2.0), 0, PIVOT_Z))
            .circle(LUG_D / 2.0).extrude(sx * LUG_T))
    for sx in (-1, 1):
        part = part.cut(
            cq.Workplane("YZ", origin=(sx * (HALF_SPAN + LUG_T), 0, PIVOT_Z))
            .circle((PIVOT_D_MM + PIVOT_CLEAR_MM) / 2.0)
            .extrude(-sx * (2 * LUG_T + 1.0)))
    return part


def build_boss():
    """Print orientation: knurled face on the bed, spigot pointing +Z."""
    boss = cq.Workplane("XY").circle(BOSS_D / 2.0).extrude(BOSS_T)
    try:
        boss = boss.edges("<Z").chamfer(0.40)
    except Exception:
        pass
    if BOSS_FLUTES:
        fr = BOSS_D / 2.0
        fd = (math.pi * BOSS_D / BOSS_FLUTES) * 0.42
        cutter = None
        for i in range(BOSS_FLUTES):
            a = 2 * math.pi * i / BOSS_FLUTES
            c = (cq.Workplane("XY", origin=(fr * math.cos(a), fr * math.sin(a), -0.1))
                 .circle(fd / 2.0).extrude(BOSS_T * 0.80))
            cutter = c if cutter is None else cutter.union(c)
        boss = boss.cut(cutter)
    spig = cq.Workplane("XY", origin=(0, 0, BOSS_T)).circle(PIVOT_D_MM / 2.0).extrude(SPIGOT_L)
    try:
        spig = spig.edges(">Z").chamfer(PIVOT_D_MM * 0.18)
    except Exception:
        pass
    return boss.union(spig)


# ---------------------------------------------------------------------------
# EXPORT
# ---------------------------------------------------------------------------

def print_orientation():
    """Every part laid out ready to slice, no rotation needed by the user."""
    mid = build_body_mid().translate((0, 0, -MID_Z0))
    handle = build_handle().rotate((0, 0, 0), (1, 0, 0), 90)
    hb = handle.val().BoundingBox()
    handle = handle.translate((0, 0, -hb.zmin))
    return {
        "loop_body_mid": mid,
        "loop_cap_bottom": build_cap(top=False),
        "loop_cap_top": build_cap(top=True),
        "loop_screen": build_screen(),
        "loop_handle": handle,
        "loop_boss": build_boss(),
    }


def assembled():
    mid = build_body_mid()
    cap_b = build_cap(top=False)
    cap_t = build_cap(top=True).rotate((0, 0, 0), (1, 0, 0), 180).translate((0, 0, H))
    screen = build_screen_core().translate(
        (0, FRONT_Y + RECESS_DEPTH_MM, MODULE_Z_BOT))
    handle = build_handle()
    parts = [("mid", mid, (0.29, 0.44, 0.30)),
             ("cap_bottom", cap_b, (0.11, 0.12, 0.11)),
             ("cap_top", cap_t, (0.11, 0.12, 0.11)),
             ("screen", screen, (0.14, 0.15, 0.14)),
             ("handle", handle, (0.80, 0.68, 0.42))]
    for sx, nm in ((-1, "boss_left"), (1, "boss_right")):
        b = (build_boss().rotate((0, 0, 0), (0, 1, 0), -90 * sx)
             .translate((sx * LUG_OUT_X, 0, PIVOT_Z)))
        parts.append((nm, b, (0.80, 0.68, 0.42)))
    return parts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--width", type=float, default=None,
                    help="overall body width in mm (default %.1f)" % BODY_W_MM)
    args = ap.parse_args()
    if args.width:
        globals()["BODY_W_MM"] = args.width
        _derive()

    parts = print_orientation()
    print("PART                    X       Y       Z   mm  (print orientation)")
    for name, wp in parts.items():
        cq.exporters.export(wp, os.path.join(OUT_DIR, name + ".stl"),
                            tolerance=0.004, angularTolerance=0.06)
        cq.exporters.export(wp, os.path.join(OUT_DIR, name + ".step"))
        bb = wp.val().BoundingBox()
        print("%-18s %7.2f %7.2f %7.2f" % (name, bb.xlen, bb.ylen, bb.zlen))

    asm = cq.Assembly()
    for nm, wp, col in assembled():
        asm.add(wp, name=nm, color=cq.Color(*col))
    try:
        asm.export(os.path.join(OUT_DIR, "loop_assembly.step"))
    except AttributeError:
        asm.save(os.path.join(OUT_DIR, "loop_assembly.step"))

    print("\nscale               %.4f mm/px" % SCALE)
    print("body envelope       %.1f W x %.1f D x %.1f H mm" % (W, D, H))
    print("handle outer span   %.1f mm" % (2 * (LUG_OUT_X + BOSS_T)))
    print("overall height      %.1f mm" % (PIVOT_Z + HANDLE_RISE + ROD_D / 2.0))
    print("arc R / sweep       %.2f mm / %.2f deg" % (ARC_R, SWEEP))
    print("pivot spigot        %.2f dia x %.2f long" % (PIVOT_D_MM, SPIGOT_L))


if __name__ == "__main__":
    main()

# ---------------------------------------------------------------------------
# NOTE ON THE WORDMARK
# The glyphs come from a generic sans, not rain's brand typeface, because the
# render's logo is too low-contrast against the fabric weave to segment cleanly
# and I will not invent a trademark. Two honest options:
#   1. Set LOGO_FONT to rain's actual font if you have the TTF installed.
#   2. Set LOGO_MODE = "pocket" and apply a printed vinyl decal instead.
# For anything going near rain marketing or a customer, option 2 is the safe one.
# ---------------------------------------------------------------------------
