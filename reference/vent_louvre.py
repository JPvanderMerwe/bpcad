"""
Print-in-place adjustable louvre vent with working parallel-crank linkage.
Parametric CadQuery model - Bit Primitive.

Mechanism
---------
Blades are VERTICAL and pivot about Z, so the part prints flat and every pin is
a vertical cylinder: no overhangs, no round features printed in mid-air.

The blades are ganged by a PARALLEL CRANK linkage, not a clamp. Each blade has
a crank socket at radius CRANK_R from its pivot. A single tie bar carries a
crank pin for each blade. Because every crank arm is the same length and
parallel, the pin spacing never changes as the blades swing - the bar simply
translates bodily. Slide the knob, all four blades turn together.

Travel is limited to +/-MAX_ANGLE. Beyond about 40 deg the bar fouls the fixed
pivot pins, and approaching 90 deg the crank reaches a dead point where pushing
the bar can no longer rotate a blade.

Z layer stack (bottom to top, all print-in-place)
------------------------------------------------
  0        .. WALL          bottom rail. Pivot pins rise from its top face.
  +GAP     .. +BAR_THICK    tie bar, free to slide. Crank pins rise from it.
  +GAP     .. BLADE_Z1      blades. Sockets in their undersides.
  +GAP     .. FRAME_H       top rail. Sockets receive the blade top pins.

Every pin points UP. Each air gap is PIN_GAP_Z and is bridged by the first
layer of whatever prints above it.

Mounting
--------
A front flange sits proud of the body so the vent pushes into a rectangular
cutout of APERTURE_W x APERTURE_H plus BODY_CLEAR and stops against the face.
Two M3 holes in the flange ears for screw fixing.

Print notes
-----------
  layer height : 0.20 mm
  nozzle       : 0.40 mm
  material     : PETG or ABS. PLA creeps and the blades go slack.
  supports     : none
  orientation  : as modelled, flange edge-on, frame flat on the bed
  after print  : work the knob back and forth a few times to free the pins

Usage
-----
  python3 vent_louvre.py
"""

import math
import cadquery as cq

# ----------------------------------------------------------------------------
# PARAMETERS
# ----------------------------------------------------------------------------

# Envelope
FRAME_W = 76.0          # X, outside width of the body
FRAME_D = 22.0          # Y, body depth (insertion direction)
FRAME_H = 30.0          # Z, outside height and print height
WALL = 4.0
BEZEL_R = 1.5

# Mounting flange
FLANGE_T = 2.0          # thickness in Y
FLANGE_OVER = 5.0       # how far it stands proud of the body, all round
SCREW_DIA = 3.4         # M3 clearance
BODY_CLEAR = 0.3        # advisory: cut your hole this much over body size

# Blades
N_BLADES = 4
BLADE_CHORD = 14.0
BLADE_THICK = 1.8
BLADE_ANGLE = 0.0       # as printed and as rendered. 0 = straight through
MAX_ANGLE = 38.0        # mechanism limit, enforced by assert
BLADE_TIP_R = 0.7

# Pivot pins (blade to frame)
PIN_DIA = 2.6
PIN_CLEAR_R = 0.30      # radial clearance
PIN_ENGAGE = 2.6
PIN_GAP_Z = 0.30        # vertical air gap at every shoulder
SOCKET_EXTRA = 0.40
HUB_WALL = 1.2

# Crank linkage
CRANK_R = 5.0           # crank arm length, pivot to crank pin
CRANK_PIN_DIA = 1.8
CRANK_ENGAGE = 2.4
CRANK_HUB_WALL = 0.9

# Tie bar (fully enclosed inside the body, behind the flange)
BAR_THICK = 2.4         # Z
BAR_WIDTH = 3.2         # Y
BAR_TAIL = 3.0          # material beyond the outermost crank pin

# Front grip tab. Everything behind the flange plane ends up inside the
# mounting hole, so the only reachable control is one forward of the flange.
# One blade carries a tab; the tie bar drags the other three along.
GRIP_BLADE = 2          # index into BLADE_XS
GRIP_LEN = 20.0         # radius from pivot to tab tip. Must stay proud of the
                        # flange at MAX_ANGLE, not just at rest.
GRIP_W = 3.6            # tab thickness in X, a little fatter than the blade
GRIP_PAD_W = 8.0        # thumb paddle width in X
GRIP_PAD_D = 3.0        # thumb paddle depth in Y

# ----------------------------------------------------------------------------
# DERIVED
# ----------------------------------------------------------------------------

APERTURE_W = FRAME_W - 2 * WALL
APERTURE_H = FRAME_H - 2 * WALL

RAIL_BOT_TOP = WALL
RAIL_TOP_BOT = FRAME_H - WALL

BAR_Z0 = RAIL_BOT_TOP + PIN_GAP_Z
BAR_Z1 = BAR_Z0 + BAR_THICK
BLADE_Z0 = BAR_Z1 + PIN_GAP_Z
BLADE_Z1 = RAIL_TOP_BOT - PIN_GAP_Z
BLADE_H = BLADE_Z1 - BLADE_Z0

SOCKET_DIA = PIN_DIA + 2 * PIN_CLEAR_R
SOCKET_DEPTH = PIN_ENGAGE + SOCKET_EXTRA
HUB_DIA = SOCKET_DIA + 2 * HUB_WALL

CRANK_SOCKET_DIA = CRANK_PIN_DIA + 2 * PIN_CLEAR_R
CRANK_SOCKET_DEPTH = CRANK_ENGAGE + SOCKET_EXTRA
CRANK_HUB_DIA = CRANK_SOCKET_DIA + 2 * CRANK_HUB_WALL

PITCH = APERTURE_W / N_BLADES
BLADE_XS = [-APERTURE_W / 2 + PITCH * (i + 0.5) for i in range(N_BLADES)]

BODY_FRONT = -FRAME_D / 2            # face the flange attaches to
FLANGE_Y0 = BODY_FRONT - FLANGE_T
FLANGE_W = FRAME_W + 2 * FLANGE_OVER
# Flush with the bed at the bottom - a symmetric flange would need the lower
# lip to print in mid-air. Overhangs left, right and top only.
FLANGE_H = FRAME_H + FLANGE_OVER

# Where the tie bar sits for a given blade angle (parallel crank kinematics)
def bar_offset(angle_deg):
    # A blade rotated by +angle about Z carries its crank socket from (0, R)
    # to (-R sin, R cos). The bar must follow exactly that, hence the minus.
    t = math.radians(angle_deg)
    return -CRANK_R * math.sin(t), CRANK_R * math.cos(t)

# ---- sanity checks: fail loudly rather than export a broken part -----------
assert HUB_DIA < PITCH, "pivot hub %.2f exceeds pitch %.2f" % (HUB_DIA, PITCH)
assert BLADE_CHORD < PITCH, "chord %.2f >= pitch %.2f, blades will collide" % (
    BLADE_CHORD, PITCH)
assert CRANK_R + CRANK_HUB_DIA / 2 <= BLADE_CHORD / 2 + 0.2, (
    "crank hub pokes past the blade trailing edge")
assert abs(BLADE_ANGLE) <= MAX_ANGLE, (
    "BLADE_ANGLE %.1f exceeds mechanism limit %.1f" % (BLADE_ANGLE, MAX_ANGLE))
_, _y = bar_offset(MAX_ANGLE)
assert (_y - BAR_WIDTH / 2) - (PIN_DIA / 2 + PIN_CLEAR_R) > 0.4, (
    "tie bar fouls the pivot pins at MAX_ANGLE; raise CRANK_R or narrow "
    "BAR_WIDTH")
_gy = -GRIP_LEN * math.cos(math.radians(MAX_ANGLE))
assert _gy < BODY_FRONT - FLANGE_T - 1.0, (
    "grip tab retracts behind the flange at MAX_ANGLE and would be "
    "unreachable inside the mounting hole; raise GRIP_LEN")
assert 0 <= GRIP_BLADE < N_BLADES, "GRIP_BLADE out of range"
assert GRIP_LEN * math.sin(math.radians(MAX_ANGLE)) + GRIP_PAD_W / 2 \
    + abs(BLADE_XS[GRIP_BLADE]) < APERTURE_W / 2, (
    "grip tab sweeps outside the flange aperture; move GRIP_BLADE inboard "
    "or shorten GRIP_LEN")


# ----------------------------------------------------------------------------
# GEOMETRY
# ----------------------------------------------------------------------------

def make_frame():
    """Body + flange, with the airflow aperture and the knob slot."""
    body = (cq.Workplane("XY").rect(FRAME_W, FRAME_D).extrude(FRAME_H)
            .edges("|Z").fillet(BEZEL_R))

    # XZ workplane extrudes along -Y, so start at the body front face and the
    # flange grows forward, fusing to the body.
    flange = (cq.Workplane("XZ").workplane(offset=-BODY_FRONT)
              .center(0, FLANGE_H / 2)
              .rect(FLANGE_W, FLANGE_H).extrude(FLANGE_T)
              .edges("|Y").fillet(BEZEL_R * 2))
    frame = body.union(flange)

    # Airflow aperture, straight through body and flange
    aperture = (cq.Workplane("XY").workplane(offset=WALL)
                .rect(APERTURE_W, FRAME_D + 2 * FLANGE_T + 4)
                .extrude(APERTURE_H))
    frame = frame.cut(aperture)

    # No wall slot: the tie bar is now fully enclosed. The only control that
    # crosses the flange plane is the grip tab on one blade.

    # Screw holes in the flange ears
    x_screw = FRAME_W / 2 + FLANGE_OVER / 2
    for sx in (-x_screw, x_screw):
        hole = (cq.Workplane("XZ").workplane(offset=-FLANGE_Y0 - 1)
                .center(sx, FRAME_H / 2)
                .circle(SCREW_DIA / 2).extrude(FLANGE_T + 2))
        frame = frame.cut(hole)

    # Integral pivot pins rising from the bottom rail
    for x in BLADE_XS:
        pin = (cq.Workplane("XY").workplane(offset=RAIL_BOT_TOP)
               .center(x, 0).circle(PIN_DIA / 2)
               .extrude(BLADE_Z0 - RAIL_BOT_TOP + PIN_ENGAGE))
        frame = frame.union(pin)

    # Sockets bored up into the top rail
    for x in BLADE_XS:
        sk = (cq.Workplane("XY").workplane(offset=RAIL_TOP_BOT - 0.01)
              .center(x, 0).circle(SOCKET_DIA / 2).extrude(SOCKET_DEPTH))
        frame = frame.cut(sk)

    return frame


def make_blade(x_pos, angle, grip=False):
    """Plate + pivot hub + crank hub, sockets under, pivot pin on top.
    If grip=True, also carries the forward thumb tab."""
    plate = (cq.Workplane("XY").workplane(offset=BLADE_Z0)
             .rect(BLADE_THICK, BLADE_CHORD).extrude(BLADE_H)
             .edges("|Z").fillet(min(BLADE_TIP_R, BLADE_THICK / 2 - 0.05)))

    hub = (cq.Workplane("XY").workplane(offset=BLADE_Z0)
           .circle(HUB_DIA / 2).extrude(BLADE_H))
    crank_hub = (cq.Workplane("XY").workplane(offset=BLADE_Z0)
                 .center(0, CRANK_R).circle(CRANK_HUB_DIA / 2)
                 .extrude(BLADE_H))
    blade = plate.union(hub).union(crank_hub)

    if grip:
        # Stem reaching forward from the leading edge, out past the flange
        stem_len = GRIP_LEN - BLADE_CHORD / 2
        stem = (cq.Workplane("XY").workplane(offset=BLADE_Z0)
                .center(0, -(BLADE_CHORD / 2 + stem_len / 2))
                .rect(GRIP_W, stem_len).extrude(BLADE_H))
        # Thumb paddle at the tip
        pad = (cq.Workplane("XY").workplane(offset=BLADE_Z0)
               .center(0, -(GRIP_LEN - GRIP_PAD_D / 2))
               .rect(GRIP_PAD_W, GRIP_PAD_D).extrude(BLADE_H)
               .edges("|Z").fillet(GRIP_PAD_D / 2.5))
        blade = blade.union(stem).union(pad)

    blade = blade.cut(cq.Workplane("XY").workplane(offset=BLADE_Z0 - 0.01)
                      .circle(SOCKET_DIA / 2).extrude(SOCKET_DEPTH))
    blade = blade.cut(cq.Workplane("XY").workplane(offset=BLADE_Z0 - 0.01)
                      .center(0, CRANK_R).circle(CRANK_SOCKET_DIA / 2)
                      .extrude(CRANK_SOCKET_DEPTH))
    blade = blade.union(cq.Workplane("XY").workplane(offset=BLADE_Z1)
                        .circle(PIN_DIA / 2)
                        .extrude(PIN_GAP_Z + PIN_ENGAGE))

    blade = blade.rotate((0, 0, 0), (0, 0, 1), angle)
    return blade.translate((x_pos, 0, 0))


def make_tie_bar(angle):
    """Tie bar with one crank pin per blade. Fully enclosed, no exit knob."""
    dx, y = bar_offset(angle)
    x_lo = BLADE_XS[0] - BAR_TAIL
    x_hi = BLADE_XS[-1] + BAR_TAIL
    length = x_hi - x_lo

    bar = (cq.Workplane("XY")
           .workplane(offset=BAR_Z0)
           .center((x_lo + x_hi) / 2, 0)
           .rect(length, BAR_WIDTH).extrude(BAR_THICK)
           .edges("|Z").fillet(BAR_WIDTH / 3))

    for x in BLADE_XS:
        pin = (cq.Workplane("XY").workplane(offset=BAR_Z1)
               .center(x, 0).circle(CRANK_PIN_DIA / 2)
               .extrude(PIN_GAP_Z + CRANK_ENGAGE))
        bar = bar.union(pin)

    return bar.translate((dx, y, 0))


def build(angle=None):
    """
    Assemble as a COMPOUND, not a boolean union. The bodies are deliberately
    disjoint, so union() is both semantically wrong and numerically fragile -
    it intermittently fused parts that are 0.3 mm apart.
    """
    a = BLADE_ANGLE if angle is None else angle
    parts = [make_frame()]
    parts += [make_blade(x, a, grip=(i == GRIP_BLADE))
              for i, x in enumerate(BLADE_XS)]
    parts.append(make_tie_bar(a))
    solids = []
    for p in parts:
        solids.extend(p.val().Solids())
    return cq.Workplane("XY").newObject(
        [cq.Compound.makeCompound(solids)])


# ----------------------------------------------------------------------------
# EXPORT
# ----------------------------------------------------------------------------

if __name__ == "__main__":
    import os
    here = os.path.dirname(os.path.abspath(__file__))
    model = build()

    cq.exporters.export(model, os.path.join(here, "vent_louvre.stl"))
    cq.exporters.export(model, os.path.join(here, "vent_louvre.step"))
    try:
        cq.exporters.export(model, os.path.join(here, "vent_louvre.3mf"))
    except Exception as exc:
        print("3mf export skipped:", exc)

    n = len(model.val().Solids())
    print("body           : %.1f x %.1f x %.1f mm" % (FRAME_W, FRAME_D, FRAME_H))
    print("flange         : %.1f x %.1f x %.1f mm" % (FLANGE_W, FLANGE_H, FLANGE_T))
    print("cut hole       : %.1f x %.1f mm" % (FRAME_W + BODY_CLEAR,
                                               FRAME_H + BODY_CLEAR))
    print("aperture       : %.1f x %.1f mm" % (APERTURE_W, APERTURE_H))
    print("blades         : %d, pitch %.2f, chord %.1f" % (
        N_BLADES, PITCH, BLADE_CHORD))
    print("travel         : +/- %.0f deg" % MAX_ANGLE)
    print("crank arm      : %.1f mm, bar throw +/- %.2f mm" % (
        CRANK_R, abs(bar_offset(MAX_ANGLE)[0])))
    print("grip tab       : blade %d, length %.1f mm" % (GRIP_BLADE, GRIP_LEN))
    print("  proud of flange: %.2f mm at rest, %.2f mm at full travel" % (
        (BODY_FRONT - FLANGE_T) - (-GRIP_LEN),
        (BODY_FRONT - FLANGE_T) - _gy))
    print("pivot pin/skt  : %.2f / %.2f mm" % (PIN_DIA, SOCKET_DIA))
    print("crank pin/skt  : %.2f / %.2f mm" % (CRANK_PIN_DIA, CRANK_SOCKET_DIA))
    print("volume         : %.1f cm^3" % (model.val().Volume() / 1000))
    print("free solids    : %d  (expect %d: frame + %d blades + tie bar)" % (
        n, N_BLADES + 2, N_BLADES))
