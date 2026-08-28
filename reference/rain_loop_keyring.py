"""
rain loop  -  ONE PIECE KEYRING
Bit Primitive  /  CadQuery

WHAT CHANGED FROM THE DESK MODEL AND WHY
----------------------------------------
The desk model was six parts because a 110 mm replica wants a real pivoting
handle and multi-colour trim. None of that survives a shrink to keyring size,
so this is a different design rather than the same model scaled down:

  1. CONSTANT DEPTH EXTRUSION. The body, handle and bosses are one 2D silhouette
     pushed out to a single thickness. Printed flat on its back, every surface is
     either horizontal or vertical - zero overhangs, zero supports, nothing to
     glue, and the face detail sits on the top surface where an FDM printer
     resolves it best.
  2. HANDLE IS FUSED, NOT PIVOTED. It doubles as the split ring loop, so no
     separate keyring hole is needed. The ring passes through the handle.
  3. THE BOSSES BECOME THE STRUCTURAL JOINT. On the real device they are pivot
     knobs. Here they are the fillet-blended pad that carries the pull load from
     the handle into the body, which is exactly where a thin keyring snaps.
  4. FRONT FACE CARRIES THE REAL UI. The screen layout is engraved as raised
     cards standing on the glass floor, with element positions measured off the
     product render. The wordmark is TRACED from a logo crop rather than set in
     a substitute font - see trace_logo.py. The trace showed the mark is a wave
     over two straight bars, not three equal bars.
     No fabric weave: at 30 mm the true weave pitch is about 0.16 mm, far under
     a nozzle width. Use fuzzy skin on the back face if you want the texture.
  5. TRIM CAPS BECOME A WIDTH STEP ONLY. The caps really are wider than the
     fabric waist (measured, 11 px a side), and that step reads at this size.
     The front/back depth difference does not, so it is dropped.

TWO DELIBERATE OVERSIZES, BOTH REPORTED AT RUNTIME
--------------------------------------------------
At true proportion the handle rod is 0.90 mm and the logo bar stroke is 0.21 mm.
Both are below a 0.40 mm nozzle's resolution, so both are drawn oversize. These
are the only places this model knowingly departs from the render, and the script
prints the exact factor each time so you always know how far off you are.

DIMENSIONS  (all measured off the supplied 650x855 render, see rain_loop.py)
---------------------------------------------------------------------------
Default 30 mm body gives roughly 43.5 x 30 x 7 mm. That is where the glass side
bezel lands on exactly one extrusion width - go smaller and the screen bezel
stops resolving. Under 26 mm, drop the screen detail entirely.

PRINT SETTINGS
--------------
  orientation    as exported. Flat, back face on the bed. DO NOT ROTATE.
  layer height   0.12 mm. This is the whole point - the face detail is in Z.
  nozzle         0.40 mm
  material       PETG. A PLA keyring at this section will snap at the handle.
  walls          4, and set infill to 100%. It is 2 cm3, solid costs nothing
                 and a hollow keyring crushes.
  supports       none
  ironing        top surface only, if your slicer has it. Makes the bezel crisp.
  elephant foot  first-layer compensation 0.15 mm

USAGE
-----
  python3 rain_loop_keyring.py
  python3 rain_loop_keyring.py --width 36 --depth 8
  python3 rain_loop_keyring.py --logo none
"""

import argparse
import json
import math
import os

import cadquery as cq

# ---------------------------------------------------------------------------
# PIXEL MEASUREMENTS   source: supplied render, 650 x 855 px
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
BOSS_D_PX = 50

PLAN_CORNER_R_PX = 30          # assumption, invisible from a front view
LOGO_H_PX = 30                 # assumption
LOGO_CENTRE_Y_PX = 58          # assumption, px above the body bottom

# ---------------------------------------------------------------------------
# BUILD PARAMETERS
# ---------------------------------------------------------------------------

BODY_W_MM = 30.0        # overall body width across the trim caps
DEPTH_MM = 7.0          # single constant thickness of the whole part

NOZZLE_MM = 0.40
MIN_HANDLE_MM = 2.40    # thinnest handle section that survives a keychain
MIN_STROKE_MM = 0.45    # thinnest engraved or embossed line worth cutting
BOSS_MARGIN_MM = 1.00   # how far the boss must reach past the handle each side

# Deliberately deeper than true scale. At 30 mm a scale-correct 0.44 mm recess
# is geometrically right but visually dead - there is not enough depth to catch
# a shadow. 1.3 mm total is still under a fifth of the thickness and the screen
# actually reads as a screen.
RECESS_MM = 0.55        # module pocket depth, i.e. the bezel step
GLASS_MM = 0.75         # additional depth of the glass area inside the bezel
CAM_MM = 0.45           # camera dot depth

# Edge chamfers are ATTEMPTED and reverted if OCC produces an invalid solid,
# which it does on this silhouette. Set both to 0 to stop trying. For elephant
# foot use your slicer's first-layer compensation (0.15 mm), which is the
# correct fix anyway and costs no geometry.
FRONT_CHAMFER_MM = 0.40
BACK_CHAMFER_MM = 0.00

# The wordmark is traced from a real logo crop, not drawn from a font. See
# trace_logo.py. The tracing revealed that the mark is a WAVE over two straight
# bars, not three equal bars - worth knowing if you ever redraw it by hand.
LOGO_ON = True
LOGO_JSON = "loop_logo.json"
LOGO_W_FRAC = 0.185    # logo width as a fraction of the fabric waist width
LOGO_DEPTH_MM = 0.40   # engraved
LOGO_AUTOSCALE = True  # grow the logo until its thinnest stroke is printable

# Screen UI, engraved as raised cards on the glass floor. Element positions are
# measured off the product render in glass-relative pixels, glass = 212 x 388.
UI_ON = True
UI_RAISE_MM = 0.45     # how far the cards stand above the glass floor
UI_SHRINK_MM = 0.03    # shrink every element slightly to keep gaps printable
UI_GLASS_PX = (212, 388)
UI_ELEMENTS = [
    # (x0, y0, x1, y1, kind)  y measured DOWN from the glass top
    (9,   23, 120,  65, "card"),    # clock card
    # Menu toggle. LEAST CERTAIN ELEMENT: its left edge is green against a green
    # wallpaper so it will not segment. Two methods both give ~40x43 px, i.e.
    # squarish, though by eye it reads as a wider pill. If you have the real UI
    # asset, swap in (134, 23, 204, 65).
    (168, 23, 205,  65, "pill"),    # menu toggle
    (9,   73,  42, 167, "card"),    # weather
    (49,  73, 127, 167, "card"),    # 5G
    (130, 73, 192, 167, "card"),    # loopzone
    (10, 285, 198, 309, "pill"),    # search bar
    (15, 337,  40, 361, "dot"),     # dock icons
    (54, 337,  78, 361, "dot"),
    (92, 337, 117, 361, "dot"),
    (130, 337, 155, 361, "dot"),
    (169, 337, 194, 361, "dot"),
]
UI_CARD_R_PX = 10

OUT_DIR = os.path.dirname(os.path.abspath(__file__))

BODY_W_PX = BODY_R_PX - BODY_L_PX + 1
REPORT = []

# ---------------------------------------------------------------------------
# DERIVED
# ---------------------------------------------------------------------------


def load_logo():
    """Read the traced outlines and work out the thinnest stroke in them."""
    path = os.path.join(OUT_DIR, LOGO_JSON)
    if not os.path.exists(path):
        raise SystemExit("missing %s - run: python3 trace_logo.py <logo crop>" % LOGO_JSON)
    d = json.load(open(path))
    strokes = []
    for sh in d["shapes"]:
        if sh["hole"]:
            continue
        xs = [p[0] for p in sh["pts"]]
        ys = [p[1] for p in sh["pts"]]
        w, h = max(xs) - min(xs), max(ys) - min(ys)
        if h > 1e-6 and w / h > 2.5:     # a bar, so its height is the stroke
            strokes.append(h)
    d["stroke"] = min(strokes) if strokes else 0.10
    return d


def derive():
    g = globals()
    g["SCALE"] = BODY_W_MM / BODY_W_PX
    s = g["SCALE"]

    def px(v):
        return v * s

    g["px"] = px

    # model axes: X = device width, Y = device height, Z = device depth
    g["W"] = px(BODY_W_PX)
    g["H"] = px(BODY_B_PX - BODY_T_PX + 1)
    g["T"] = DEPTH_MM

    g["CAP_B_H"] = px(TRIM_BOT_ROWS[1] - TRIM_BOT_ROWS[0] + 1)
    g["CAP_T_H"] = px(TRIM_TOP_ROWS[1] - TRIM_TOP_ROWS[0] + 1)
    g["WAIST_W"] = px(WAIST_R_PX - WAIST_L_PX + 1)
    g["WAIST_Y0"] = g["CAP_B_H"]
    g["WAIST_Y1"] = g["H"] - g["CAP_T_H"]
    g["R_CAP"] = min(px(PLAN_CORNER_R_PX), g["CAP_B_H"] * 0.42)
    g["R_WAIST"] = px(PLAN_CORNER_R_PX)

    def y_of(row):
        return px(BODY_B_PX - row)

    g["y_of"] = y_of

    g["MODULE_W"] = px(MODULE_R_PX - MODULE_L_PX + 1)
    g["MODULE_Y0"] = y_of(MODULE_B_PX)
    g["MODULE_Y1"] = y_of(MODULE_T_PX)
    g["MODULE_R"] = px(MODULE_CORNER_R_PX)
    gw = px(GLASS_R_PX - GLASS_L_PX + 1)
    gy0, gy1 = y_of(GLASS_B_PX), y_of(GLASS_T_PX)
    # guard: keep the bezel at or above one extrusion width by pulling the glass
    # in. Costs a few hundredths of a mm and makes the difference between a
    # visible bezel and a smeared edge.
    short = NOZZLE_MM - (g["MODULE_W"] - gw) / 2.0
    if short > 0:
        gw -= 2 * short
        gy0 += short
        g["BEZEL_TRIM"] = short
    else:
        g["BEZEL_TRIM"] = 0.0
    g["GLASS_W"] = gw
    g["GLASS_Y0"] = gy0
    g["GLASS_Y1"] = gy1
    g["GLASS_R"] = max(g["MODULE_R"] - (g["MODULE_W"] - g["GLASS_W"]) / 2.0, 0.4)

    # handle: true-scale arc, oversized section
    true_rod = px(HANDLE_ROD_D_PX)
    g["ROD"] = max(true_rod, MIN_HANDLE_MM)
    g["ROD_FACTOR"] = g["ROD"] / true_rod

    g["PIVOT_Y"] = y_of(PIVOT_ROW)
    g["APEX_Y"] = y_of(HANDLE_APEX_ROW)
    rise = g["APEX_Y"] - g["PIVOT_Y"]
    # half-span taken straight from the render, the arc is fused not pivoted so
    # it needs no side clearance
    g["HALF_SPAN"] = px(285.5)
    c = g["HALF_SPAN"]
    g["ARC_R"] = (c * c + rise * rise) / (2 * rise)
    g["ARC_CY"] = g["APEX_Y"] - g["ARC_R"]
    g["RISE"] = rise

    true_boss = px(BOSS_D_PX)
    need = g["ROD"] + 2 * BOSS_MARGIN_MM
    g["BOSS_D"] = max(true_boss, need)
    g["BOSS_FACTOR"] = g["BOSS_D"] / true_boss

    # logo: width from the render's proportion, grown if the stroke is too fine
    g["LOGO_DATA"] = load_logo()
    want = LOGO_W_FRAC * g["WAIST_W"]
    stroke_norm = g["LOGO_DATA"]["stroke"]        # thinnest bar, normalised
    g["LOGO_FACTOR"] = 1.0
    if LOGO_AUTOSCALE and stroke_norm * want < MIN_STROKE_MM:
        g["LOGO_FACTOR"] = MIN_STROKE_MM / (stroke_norm * want)
    g["LOGO_W"] = want * g["LOGO_FACTOR"]
    g["LOGO_STROKE"] = stroke_norm * g["LOGO_W"]
    g["LOGO_CY"] = px(LOGO_CENTRE_Y_PX)


derive()


# ---------------------------------------------------------------------------
# HELPERS   every solid is a 2D profile in XY extruded +Z from 0
# ---------------------------------------------------------------------------

def rrect(w, h, r, y0, z0=0.0, t=None):
    """Rounded rectangle, centred in X, spanning y0..y0+h, z0..z0+t."""
    t = T if t is None else t
    s = cq.Workplane("XY").box(w, h, t, centered=(True, True, False))
    r = min(r, w / 2.0 - 0.01, h / 2.0 - 0.01)
    if r > 0.05:
        s = s.edges("|Z").fillet(r)
    return s.translate((0, y0 + h / 2.0, z0))


def disc(d, cx, cy, z0=0.0, t=None):
    t = T if t is None else t
    return cq.Workplane("XY", origin=(cx, cy, z0)).circle(d / 2.0).extrude(t)


def probe(solid):
    """
    Real usability test. isValid() returns True on solids that later blow up
    every boolean, so instead cut a throwaway sliver and see if OCC copes.
    """
    try:
        t = solid.cut(cq.Workplane("XY", origin=(W * 3, 0, 0)).box(1, 1, 1))
        t.val().Volume()
        return True
    except Exception:
        return False


def try_edge_op(solid, selector, kind, amount, label):
    """Apply a fillet or chamfer, revert if it corrupts the solid."""
    try:
        out = getattr(solid.edges(selector), kind)(amount)
        if out.val().isValid() and probe(out) and out.val().Volume() > 0:
            REPORT.append("%-22s %s %.2f mm" % (label, kind, amount))
            return out
        REPORT.append("%-22s SKIPPED, %s corrupted the solid" % (label, kind))
    except Exception:
        REPORT.append("%-22s SKIPPED, OCC rejected it" % label)
    return solid


def poly_prism(pts, scale, ox, oy, z0, t):
    """Closed polygon in normalised logo coords -> extruded prism."""
    wp = cq.Workplane("XY", origin=(0, 0, z0))
    wp = wp.moveTo(ox + pts[0][0] * scale, oy + pts[0][1] * scale)
    for x, y in pts[1:]:
        wp = wp.lineTo(ox + x * scale, oy + y * scale)
    return wp.close().extrude(t)


def clip_y(solid, y_max):
    """Trim a solid to y <= y_max. Used to square off rounded top corners."""
    box = cq.Workplane("XY").box(W * 4, H * 4, T * 4, centered=(True, True, True))
    return solid.intersect(box.translate((0, y_max - H * 2, 0)))


# ---------------------------------------------------------------------------
# THE PART
# ---------------------------------------------------------------------------

def build():
    ov = 0.30 * SCALE * 100  # small union overlap so booleans stay clean
    ov = max(ov, 0.05)

    # --- silhouette -------------------------------------------------------
    waist = rrect(WAIST_W, WAIST_Y1 - WAIST_Y0, R_WAIST, WAIST_Y0)
    cap_b = rrect(W, CAP_B_H + ov, R_CAP, 0.0)
    cap_t = rrect(W, CAP_T_H + ov, R_CAP, H - CAP_T_H - ov)
    part = waist.union(cap_b).union(cap_t)

    # handle: annulus clipped to the pivot line gives exactly the render's arc
    ring = (disc(2 * (ARC_R + ROD / 2.0), 0, ARC_CY)
            .cut(disc(2 * (ARC_R - ROD / 2.0), 0, ARC_CY)))
    keep = cq.Workplane("XY").box(W * 4, H * 4, T * 4, centered=(True, True, True))
    arc = ring.intersect(keep.translate((0, PIVOT_Y + H * 2, 0)))
    part = part.union(arc)

    # bosses carry the pull load from the handle into the body
    for sx in (-1, 1):
        part = part.union(disc(BOSS_D, sx * HALF_SPAN, PIVOT_Y))

    # blend the boss into the body: this is the joint that would otherwise fail
    part = try_edge_op(part, "|Z", "fillet", ROD * 0.30, "boss-to-body blend")

    # --- face detail ------------------------------------------------------
    # module pocket: rounded bottom corners, squared off flush with the waist top
    pocket = rrect(MODULE_W, (MODULE_Y1 - MODULE_Y0) + MODULE_R + 2.0, MODULE_R,
                   MODULE_Y0, z0=T - RECESS_MM, t=RECESS_MM + 1.0)
    part = part.cut(clip_y(pocket, MODULE_Y1))

    glass = rrect(GLASS_W, (GLASS_Y1 - GLASS_Y0) + GLASS_R + 2.0, GLASS_R,
                  GLASS_Y0, z0=T - RECESS_MM - GLASS_MM, t=GLASS_MM + 1.0)
    part = part.cut(clip_y(glass, GLASS_Y1))

    cam_y = GLASS_Y1 + px(18)
    if cam_y < MODULE_Y1 - px(10):
        part = part.cut(disc(max(px(14), NOZZLE_MM * 1.5), 0, cam_y,
                             z0=T - RECESS_MM - CAM_MM, t=CAM_MM + 1.0))

    # --- wordmark ---------------------------------------------------------
    if UI_ON:
        part = engrave_ui(part)
    if LOGO_ON:
        part = engrave_logo(part)

    # --- edge treatment LAST, so a failure here cannot break the detail ----
    part = try_edge_op(part, "<Z", "chamfer", BACK_CHAMFER_MM, "back edge")
    part = try_edge_op(part, ">Z", "chamfer", FRONT_CHAMFER_MM, "front edge")
    return part


def engrave_logo(part):
    """Cut the traced outlines into the front face, then restore the counters."""
    d = LOGO_DATA
    sc = LOGO_W
    ox = -sc / 2.0
    oy = LOGO_CY - d["aspect_h"] * sc / 2.0
    z0 = T - LOGO_DEPTH_MM
    t = LOGO_DEPTH_MM + 1.0

    cut = None
    for sh in d["shapes"]:
        if sh["hole"]:
            continue
        pr = poly_prism(sh["pts"], sc, ox, oy, z0, t)
        cut = pr if cut is None else cut.union(pr)
    part = part.cut(cut)

    # the counters of o, o and p: put the material back
    for sh in d["shapes"]:
        if not sh["hole"]:
            continue
        part = part.union(poly_prism(sh["pts"], sc, ox, oy, z0, LOGO_DEPTH_MM))
    return part


def engrave_ui(part):
    """Raised cards standing on the glass pocket floor, per the render."""
    gw, gh = UI_GLASS_PX
    ppx = GLASS_W / float(gw)
    ppy = (GLASS_Y1 - GLASS_Y0) / float(gh)
    floor = T - RECESS_MM - GLASS_MM
    sh = UI_SHRINK_MM

    add = None
    for x0, y0, x1, y1, kind in UI_ELEMENTS:
        mx0 = -GLASS_W / 2.0 + x0 * ppx + sh
        mx1 = -GLASS_W / 2.0 + x1 * ppx - sh
        my1 = GLASS_Y1 - y0 * ppy - sh
        my0 = GLASS_Y1 - y1 * ppy + sh
        w, h = mx1 - mx0, my1 - my0
        if w <= 0 or h <= 0:
            continue
        cx, cy = (mx0 + mx1) / 2.0, (my0 + my1) / 2.0
        if kind == "dot":
            e = (cq.Workplane("XY", origin=(cx, cy, floor))
                 .circle(min(w, h) / 2.0).extrude(UI_RAISE_MM))
        else:
            r = min(h / 2.0, w / 2.0) if kind == "pill" else UI_CARD_R_PX * ppx
            r = min(r, w / 2.0 - 0.03, h / 2.0 - 0.03)
            e = cq.Workplane("XY").box(w, h, UI_RAISE_MM, centered=(True, True, False))
            while r > 0.04:
                try:
                    e = e.edges("|Z").fillet(r)
                    break
                except Exception:
                    r *= 0.6
            e = e.translate((cx, cy, floor))
        add = e if add is None else add.union(e)
    return part.union(add)


# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--width", type=float, help="body width mm (default %.0f)" % BODY_W_MM)
    ap.add_argument("--depth", type=float, help="thickness mm (default %.0f)" % DEPTH_MM)
    ap.add_argument("--no-logo", action="store_true")
    ap.add_argument("--no-ui", action="store_true")
    a = ap.parse_args()
    if a.width:
        globals()["BODY_W_MM"] = a.width
    if a.depth:
        globals()["DEPTH_MM"] = a.depth
    if a.no_logo:
        globals()["LOGO_ON"] = False
    if a.no_ui:
        globals()["UI_ON"] = False
    derive()

    part = build()
    stl = os.path.join(OUT_DIR, "loop_keyring.stl")
    cq.exporters.export(part, stl, tolerance=0.005, angularTolerance=0.05)
    cq.exporters.export(part, os.path.join(OUT_DIR, "loop_keyring.step"))

    bb = part.val().BoundingBox()
    print("loop_keyring   %.2f x %.2f x %.2f mm   volume %.2f cm3"
          % (bb.xlen, bb.ylen, bb.zlen, part.val().Volume() / 1000))
    print("scale          %.4f mm/px" % SCALE)
    print()
    for line in REPORT:
        print("  " + line)
    print()
    print("DEPARTURES FROM TRUE SCALE")
    print("  handle section     %.2f mm, %.2fx oversize (true %.2f, min printable %.2f)"
          % (ROD, ROD_FACTOR, px(HANDLE_ROD_D_PX), MIN_HANDLE_MM))
    print("  boss diameter      %.2f mm, %.2fx oversize (needed to bridge the joint)"
          % (BOSS_D, BOSS_FACTOR))
    if BEZEL_TRIM > 0:
        print("  glass area         pulled in %.3f mm/side to keep the bezel printable"
              % BEZEL_TRIM)
    if LOGO_ON:
        print("  logo               %.2fx oversize, %.2f mm wide, stroke %.2f mm"
              % (LOGO_FACTOR, LOGO_W, LOGO_STROKE))
    print()
    print("FEATURE CHECK against a %.2f mm nozzle" % NOZZLE_MM)
    checks = [("glass side bezel", (MODULE_W - GLASS_W) / 2.0),
              ("glass bottom bezel", GLASS_Y0 - MODULE_Y0),
              ("trim cap band", CAP_B_H),
              ("waist/cap step", (W - WAIST_W) / 2.0),
              ("handle section", ROD),
              ("logo stroke", LOGO_STROKE if LOGO_ON else 99)]
    if UI_ON:
        gw, gh = UI_GLASS_PX
        ppx = GLASS_W / float(gw)
        sizes = [min((x1 - x0) * ppx, (y1 - y0) * (GLASS_Y1 - GLASS_Y0) / gh)
                 - 2 * UI_SHRINK_MM for x0, y0, x1, y1, k in UI_ELEMENTS]
        xs = sorted((x0, x1) for x0, y0, x1, y1, k in UI_ELEMENTS)
        gaps = [(b[0] - a[1]) * ppx + 2 * UI_SHRINK_MM
                for a, b in zip(xs, xs[1:]) if b[0] > a[1]]
        checks += [("smallest UI element", min(sizes)),
                   ("smallest UI gap", min(gaps) if gaps else 99)]
    for nm, v in checks:
        flag = "ok" if v >= NOZZLE_MM else "TOO FINE"
        print("  %-20s %6.2f mm   %s" % (nm, v, flag))
    print()
    print("split ring clearance under the handle: %.1f mm" % (APEX_Y - ROD - H))


if __name__ == "__main__":
    main()
