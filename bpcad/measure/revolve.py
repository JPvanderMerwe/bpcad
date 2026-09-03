"""
Read a turned profile back OUT of a mesh.

WHY THIS IS THE INTERESTING HALF
---------------------------------
A generative 3D model - Hunyuan3D, Meshy, any of them - produces a MESH. A
mesh is a triangle soup: it has no wall thickness you can change, no rim
diameter you can type a new number into, and no way to ask for it 10 mm
taller. That is the whole reason a mesh generator is not a CAD tool, and it is
why "Meshy but editable" is a real gap rather than a marketing line.

The gap closes in one direction only. You cannot turn arbitrary sculpture into
CAD. But an enormous share of printed objects - bowls, pots, vases, cups,
shades, spouts, knobs - are SURFACES OF REVOLUTION, and a surface of revolution
is fully described by one 2D profile. That is recoverable from a mesh, exactly,
and once you have it you have a spec: parametric, editable, verifiable,
printable.

So this is the back half of a pipeline whose front half could be any mesh
generator at all. Feed it something grown or sculpted, get back a spec you can
still change.

MEASURE, NEVER ESTIMATE - AND SAY WHEN YOU CANNOT
--------------------------------------------------
Every number here is measured off the mesh and comes back with the evidence
that it was measured: `roundness` says how close the thing actually is to a
solid of revolution, and `residual_mm` says how far the fitted profile sits
from the real surface. A fit without its residual is just a number.

A shape that is not a revolve gets refused rather than approximated. A bowl
fitted out of a teapot is worse than no answer, because it looks like an
answer.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

# Below this, the cross-sections are not circles and the thing is not turned.
# Measured, on real parts: a turned bowl runs about 0.001, the wobbly organic
# vase 0.0007, a rectangular birdhouse 0.29. There is a lot of daylight
# between a revolve and anything that is not one, so this threshold does not
# have to be delicate.
MAX_ROUNDNESS_ERROR = 0.06

# Slices used up the height. Enough to catch a neck or a belly, few enough that
# each slice still has plenty of vertices in it.
SLICES = 48

# Angular bins per slice for the roundness test. 36 is one every 10 degrees:
# enough that a square's corners and its flats land in different bins, which is
# the whole point of the test.
ANGLE_BINS = 36


@dataclass
class RevolveFit:
    """A turned profile read off a mesh, with the evidence."""

    profile: list[tuple[float, float]] = field(default_factory=list)  # (r, z) mm
    height_mm: float = 0.0
    outer_dia_mm: float = 0.0
    rim_dia_mm: float = 0.0
    base_dia_mm: float = 0.0
    wall_mm: float | None = None
    floor_mm: float | None = None   # always None - see _measure_wall
    axis_xy: tuple[float, float] = (0.0, 0.0)

    # The evidence.
    roundness: float = 1.0        # 0 is a perfect circle at every height
    residual_mm: float = 0.0      # out-of-roundness within a slice
    axial_noise_mm: float = 0.0   # slice-to-slice jitter UP the profile
    hollow: bool = False
    open_top: bool = False
    reasons: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.reasons

    def summary(self) -> list[str]:
        if not self.ok:
            return ["not a turned shape: " + "; ".join(self.reasons)]
        out = [
            "turned profile fitted from the mesh",
            "  height        %.1f mm" % self.height_mm,
            "  widest        %.1f mm across" % self.outer_dia_mm,
            "  rim           %.1f mm across" % self.rim_dia_mm,
            "  base          %.1f mm across" % self.base_dia_mm,
            "  roundness     %.4f  (0 is a perfect circle at every height)" % self.roundness,
            "  out of round  %.3f mm within a slice" % self.residual_mm,
            "  axial noise   %.3f mm between slices" % self.axial_noise_mm,
        ]
        if self.wall_mm is not None:
            out.append("  wall          %.2f mm  (measured, not assumed)" % self.wall_mm)
        else:
            out.append("  wall          not measurable - the mesh reads as solid")
        return out


def fit_revolve(mesh, slices: int = SLICES) -> RevolveFit:
    """
    Fit a surface of revolution to a mesh.

    The axis is taken as vertical and found by centroid, because a generated
    object arrives standing up. Rotating an arbitrary mesh onto its own axis of
    symmetry is a different and much larger problem, and guessing at it would
    produce confident nonsense on anything that is not already upright.
    """
    fit = RevolveFit()

    verts = np.asarray(mesh.vertices, dtype=float)
    if len(verts) < 32:
        fit.reasons.append("only %d vertices - too coarse to measure" % len(verts))
        return fit

    z = verts[:, 2]
    z_lo, z_hi = float(z.min()), float(z.max())
    fit.height_mm = z_hi - z_lo
    if fit.height_mm <= 0.5:
        fit.reasons.append("flat - no height to turn a profile through")
        return fit

    # The axis: the centre of the widest slice, not the centroid of everything.
    # A bowl's vertices crowd near its rim, so a plain centroid is pulled off
    # centre by whatever the rim happens to be doing.
    cx, cy = _axis_from_widest_slice(verts, z_lo, z_hi, slices)
    fit.axis_xy = (cx, cy)

    radius = np.hypot(verts[:, 0] - cx, verts[:, 1] - cy)
    angle = np.arctan2(verts[:, 1] - cy, verts[:, 0] - cx)

    edges = np.linspace(z_lo, z_hi, slices + 1)
    idx = np.clip(np.digitize(z, edges) - 1, 0, slices - 1)

    profile: list[tuple[float, float]] = []
    spreads: list[float] = []
    residuals: list[float] = []

    for s in range(slices):
        here = idx == s
        if here.sum() < 8:
            continue
        r_here = radius[here]
        z_mid = float((edges[s] + edges[s + 1]) / 2.0)

        # The OUTER surface, not the mean of everything: a hollow vessel has an
        # inner wall in the same slice, and averaging the two gives a profile
        # that is neither.
        outer = float(np.percentile(r_here, 97))
        if outer <= 1e-6:
            continue
        profile.append((outer, z_mid))

        # ROUNDNESS IS MEASURED AROUND THE AXIS, BY ANGLE.
        #
        # The first version took the spread of the outermost band of radii in
        # the slice, and that is not a roundness test at all - on a SQUARE
        # cross-section the outermost band is just the four corners, whose
        # radii are all nearly identical. A rectangular birdhouse scored 0.015
        # and was fitted as a 314 mm bowl, which is precisely the confident
        # wrong answer this was written to refuse.
        #
        # Binning by angle and taking the furthest point in each bin measures
        # the thing that actually matters: does the outline stay the same
        # distance out all the way round. A square runs about 0.29 - half its
        # diagonal against half its width - and a turned shape runs near zero.
        ang = angle[here]
        bins = np.clip(((ang + math.pi) / (2 * math.pi) * ANGLE_BINS).astype(int),
                       0, ANGLE_BINS - 1)
        # -inf, not NaN. np.maximum against NaN propagates NaN, so every bin
        # came back NaN, every slice was skipped, and roundness stayed at its
        # 1.0 default - which refused every shape including a real bowl.
        far = np.full(ANGLE_BINS, -np.inf)
        np.maximum.at(far, bins, r_here)
        far = far[np.isfinite(far)]
        if len(far) >= ANGLE_BINS // 2:
            spreads.append(float(np.std(far) / max(float(np.mean(far)), 1e-6)))
            residuals.append(float(np.mean(np.abs(far - np.median(far)))))

    if len(profile) < 4:
        fit.reasons.append("too few usable slices - the mesh is not a vertical form")
        return fit

    fit.profile = profile
    fit.roundness = float(np.mean(spreads)) if spreads else 1.0
    fit.residual_mm = float(np.mean(residuals)) if residuals else 0.0

    radii = np.array([r for r, _z in profile])

    # AXIAL NOISE: how much each slice disagrees with its own neighbours.
    #
    # This is a DIFFERENT quantity from out-of-roundness, and conflating them
    # cost an afternoon. Out-of-roundness is zero on any turned shape, however
    # noisily it was measured, because every slice is still a circle - so using
    # it to decide how much to smooth meant never smoothing at all.
    #
    # The second difference is the honest estimate available here. It cannot
    # separate genuine fine detail from sampling jitter, which is exactly why
    # the smoothing that uses it stops the moment it would exceed it: whatever
    # this number contains, departing from the measurement by more than it is
    # no longer smoothing, it is inventing.
    if len(radii) >= 3:
        second = radii[1:-1] - (radii[:-2] + radii[2:]) / 2.0
        fit.axial_noise_mm = float(np.sqrt(np.mean(second ** 2)))

    fit.outer_dia_mm = float(radii.max() * 2.0)
    fit.base_dia_mm = float(profile[0][0] * 2.0)
    fit.rim_dia_mm = float(profile[-1][0] * 2.0)

    if fit.roundness > MAX_ROUNDNESS_ERROR:
        fit.reasons.append(
            "cross-sections vary by %.1f%% around the axis, so this is not a "
            "turned shape - fitting a bowl to it would produce a confident "
            "wrong answer" % (100 * fit.roundness)
        )
        return fit

    _measure_wall(fit, mesh, verts, radius, z, z_lo, z_hi)
    return fit


def _axis_from_widest_slice(verts, z_lo, z_hi, slices) -> tuple[float, float]:
    """Centre of the slice with the largest spread, which is the most reliable."""
    edges = np.linspace(z_lo, z_hi, slices + 1)
    idx = np.clip(np.digitize(verts[:, 2], edges) - 1, 0, slices - 1)
    best, best_span = None, -1.0
    for s in range(slices):
        here = idx == s
        if here.sum() < 8:
            continue
        xy = verts[here][:, :2]
        # np.ptp(), not ndarray.ptp() - the method was removed in numpy 2.
        span = float(np.ptp(xy[:, 0]) + np.ptp(xy[:, 1]))
        if span > best_span:
            best_span, best = span, xy
    if best is None:
        return float(verts[:, 0].mean()), float(verts[:, 1].mean())
    return float((best[:, 0].min() + best[:, 0].max()) / 2.0), \
           float((best[:, 1].min() + best[:, 1].max()) / 2.0)


def _measure_wall(fit: RevolveFit, mesh, verts, radius, z, z_lo, z_hi) -> None:
    """
    Wall thickness, measured SLICE BY SLICE and then taken as the median.

    The first version measured it across a band covering a third of the height,
    and that only works on a cylinder. On anything whose radius changes with
    height - which is every interesting vessel - the outer surface at the
    bottom of the band overlaps the inner surface at the top, the two clusters
    smear into each other, and the answer is whatever the smear happened to
    produce. It read 2.32 mm on a known 3.00 mm wall, and it invented a 0.75 mm
    wall on a SOLID cone, which is the worse of the two failures by far.

    A thin slice does not have that problem: the radius barely changes across
    it, so a hollow wall really is two tight clusters and a solid really is
    one. The median across slices then throws out the few that straddle a floor
    or a rim.
    """
    slices = 40
    edges = np.linspace(z_lo + (z_hi - z_lo) * 0.30, z_lo + (z_hi - z_lo) * 0.85,
                        slices + 1)
    walls: list[float] = []

    for i in range(slices):
        here = (z >= edges[i]) & (z < edges[i + 1])
        if here.sum() < 12:
            continue
        r_here = np.sort(radius[here])
        outer = float(np.percentile(r_here, 97))

        # An inner surface is a SEPARATE cluster, not merely smaller numbers.
        # Require a clear gap, or a solid shape's own surface scatter reads as
        # a wall.
        inner_pool = r_here[r_here < outer - 0.25]
        if len(inner_pool) < 6:
            continue
        inner = float(np.percentile(inner_pool, 98))
        wall = outer - inner
        if 0.3 < wall < outer * 0.4:
            walls.append(wall)

    if len(walls) < max(4, slices // 6):
        fit.hollow = False
        return

    wall = float(np.median(walls))
    # A "wall" under a third of a millimetre is not a wall. A perforated shell
    # - the Voronoi bowl - has holes where the two-cluster test expects an
    # inner surface, and the numbers it returns then describe the edge of a
    # hole rather than the thickness of anything. 0.33 mm on a 2.6 mm wall.
    if wall < 0.35:
        fit.hollow = False
        return
    fit.wall_mm = round(wall, 2)
    fit.hollow = True

    # Open at the top? The topmost slice having an inner surface says so.
    top = z >= z_hi - (z_hi - z_lo) * 0.06
    if top.sum() >= 16:
        r_top = radius[top]
        o = float(np.percentile(r_top, 97))
        fit.open_top = bool((r_top < o - fit.wall_mm * 0.5).sum() >= 8)

    # THE FLOOR IS NOT CLAIMED, BECAUSE IT COULD NOT BE MEASURED RELIABLY.
    #
    # Two goes at it, both wrong, in opposite directions. Walking up in thin
    # bands looking for "a radius well below the outer one" reported 22.68 mm
    # for a 4 mm floor - the ordinary scatter of a curved outer surface
    # satisfies that test. Requiring the gap to match the measured wall
    # reported 32.0 mm on one vessel and 2.5 mm on another, both with a true
    # floor of 4 mm. The rebuilt volumes were +73.6% and +128.2%.
    #
    # The signal is genuinely weak: near the base the slices are thin, the
    # vertex count is low, and the inner and outer surfaces are converging
    # anyway. Rule 29 - a value with no measured source is not substituted.
    # Left out, the template derives the floor from the wall and the report
    # says it was derived, which is true and useful. A confident wrong floor
    # is a solid slug of material and a part nobody asked for.


# Measured on a deliberately wiggly test vase, rebuilt volume against the
# source mesh: 12 points +3.6%, 20 +3.6%, 30 +0.50%, 42 +0.60%, and 60 refused
# outright because at that fidelity the slice-to-slice jitter reads as a wall
# leaning 56 degrees - which, as measured, it does. Thirty is where the curve
# flattens.
DEFAULT_PROFILE_POINTS = 30


def to_vessel_params(fit: RevolveFit, points: int = DEFAULT_PROFILE_POINTS) -> dict:
    """
    Turn a fit into vessel template parameters.

    The profile is resampled to a fixed number of points so the spec stays
    readable and rebuilds identically. Anything the mesh could not tell us is
    LEFT OUT rather than filled in - the template's own derivation is a better
    answer than a number invented here.
    """
    if not fit.ok:
        raise ValueError("cannot make a spec from a shape that is not turned: "
                         + "; ".join(fit.reasons))

    z0 = fit.profile[0][1]  # noqa: F841 - kept for readability below
    src_z = np.array([p[1] for p in fit.profile])
    src_r = np.array([p[0] for p in fit.profile])

    # RESAMPLED BY AVERAGING, NOT BY SAMPLING. `points` is the one control, and
    # it means what it looks like: how finely the silhouette is described.
    #
    # This replaces an attempt to smooth by exactly the measured noise, which
    # was a better idea than it was a method. The only noise estimate available
    # here is the second difference along the profile, and on an object with
    # genuine fine shape in it - which is most interesting objects - that
    # estimate is dominated by the shape rather than the noise. It read 2.05 mm
    # on a vase whose real detail is millimetric, chose a 19-wide window, and
    # flattened 4.6% of the volume away. Worse than doing nothing, and confident
    # about it.
    #
    # Bin averaging has no such pretension. Each output point is the mean of
    # the slices that fall in its band, so asking for fewer points genuinely
    # low-passes the profile and asking for more keeps what was measured. The
    # cost of either is visible in the rebuilt volume, which is reported.
    edges = np.linspace(src_z[0], src_z[-1], points + 1)
    which = np.clip(np.digitize(src_z, edges) - 1, 0, points - 1)
    zs, rs = [], []
    for i in range(points):
        here = which == i
        if not here.any():
            continue
        zs.append(float(np.mean(src_z[here])))
        rs.append(float(np.mean(src_r[here])))
    zs, rs = np.array(zs), np.array(rs)
    if len(zs) < 3:
        raise ValueError("resampling to %d points left too few to describe a profile" % points)

    params: dict = {
        "profile": "custom",
        "profile_points": [[round(float(r), 3), round(float(zz - z0), 3)]
                           for r, zz in zip(rs, zs)],
        "outer_dia_mm": round(fit.outer_dia_mm, 2),
        "height_mm": round(fit.height_mm, 2),
    }
    if fit.wall_mm is not None:
        params["wall_mm"] = fit.wall_mm
    if fit.floor_mm is not None:
        params["floor_mm"] = fit.floor_mm
    return params
