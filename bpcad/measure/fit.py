"""
Circle and arc fitting. Every fit returns its residual.

WHY THE RESIDUAL IS NOT OPTIONAL
--------------------------------
The single most valuable result of the reference session was the handle arc
fitting to 0.03 px. Not the radius - the residual. A radius on its own is just
a number that came out of some least squares; you get one whether the source is
a true circular arc, an ellipse or a freehand curve. The residual is what
proved the render's handle really was a circular arc, which is what made it
safe to reproduce exactly rather than approximate.

So there is no fit function here that hands back a radius alone, and the CLI
prints the residual every time.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class CircleFit:
    cx: float
    cy: float
    r: float
    max_residual: float
    rms_residual: float
    n: int

    def __str__(self) -> str:
        return (
            "circle  centre (%.3f, %.3f)  R %.3f px  "
            "residual max %.4f px, rms %.4f px, over %d points"
            % (self.cx, self.cy, self.r, self.max_residual, self.rms_residual, self.n)
        )


@dataclass(frozen=True)
class ArcFit:
    r: float
    cx: float
    cy: float
    sweep_deg: float
    residual: float

    @property
    def centre(self) -> tuple[float, float]:
        return (self.cx, self.cy)

    def __str__(self) -> str:
        return (
            "arc     centre (%.3f, %.3f)  R %.3f px  sweep %.3f deg  residual %.2e px"
            % (self.cx, self.cy, self.r, self.sweep_deg, self.residual)
        )


def _as_points(points) -> np.ndarray:
    pts = np.asarray(points, dtype=float)
    if pts.ndim != 2 or pts.shape[1] != 2:
        raise ValueError("points must be an (N, 2) array of (x, y), got shape %r" % (pts.shape,))
    return pts


def circle(points) -> CircleFit:
    """
    Least-squares circle through a set of (x, y) points.

    Algebraic (Kasa) fit: minimising the algebraic distance turns the problem
    into one linear solve, and for points that genuinely lie on an arc it lands
    in the same place as an iterative geometric fit to well under the precision
    that matters here. The geometric residuals are then measured against the
    result, so what is reported is real distance in pixels, not the algebraic
    quantity that was minimised.
    """
    pts = _as_points(points)
    if len(pts) < 4:
        raise ValueError(
            "a circle FIT needs at least 4 points, got %d. Three points determine "
            "a circle exactly, so a three-point 'fit' always has zero residual "
            "and proves nothing - which is the one thing this module exists to "
            "stop happening. Use arc_through for three points." % len(pts)
        )

    x, y = pts[:, 0], pts[:, 1]
    # x^2 + y^2 = 2*cx*x + 2*cy*y + (r^2 - cx^2 - cy^2)
    A = np.column_stack([2.0 * x, 2.0 * y, np.ones(len(pts))])
    b = x * x + y * y
    sol, _res, rank, _sv = np.linalg.lstsq(A, b, rcond=None)
    if rank < 3:
        raise ValueError(
            "the points are collinear, so no circle fits them. lstsq will "
            "happily return a least-norm answer for a singular system, so the "
            "rank has to be checked or this returns a confident nonsense radius."
        )
    cx, cy, c = float(sol[0]), float(sol[1]), float(sol[2])

    r2 = c + cx * cx + cy * cy
    if r2 <= 0:
        raise ValueError(
            "the points do not describe a circle - the fit produced a negative "
            "squared radius. They are probably collinear."
        )
    r = math.sqrt(r2)

    # No guard here on a very large radius relative to the point spread. A
    # shallow arc genuinely has one, and if the points really do lie on it the
    # residual will be small and the measurement is sound. If they do not, the
    # residual says so. Adding a heuristic that refuses large radii would
    # override the one signal this module exists to provide.

    dist = np.hypot(x - cx, y - cy)
    resid = np.abs(dist - r)
    return CircleFit(
        cx=cx,
        cy=cy,
        r=r,
        max_residual=float(resid.max()),
        rms_residual=float(np.sqrt((resid ** 2).mean())),
        n=len(pts),
    )


def arc_through(p1, p2, apex) -> ArcFit:
    """
    The exact circle through three points, plus the arc from p1 to p2 that
    passes through apex.

    Three points determine a circle exactly, so the residual here is a
    numerical sanity check rather than evidence of anything - it will be at the
    floating-point noise floor. To find out whether a curve really is circular,
    trace it and use circle() on the traced points; that residual means
    something.

    This is the shape of the reference handle measurement: two pivot centres
    and an apex give R = (half_span^2 + rise^2) / (2 * rise), which is this
    calculation written out longhand.
    """
    p1 = np.asarray(p1, dtype=float)
    p2 = np.asarray(p2, dtype=float)
    ap = np.asarray(apex, dtype=float)
    for name, p in (("p1", p1), ("p2", p2), ("apex", ap)):
        if p.shape != (2,):
            raise ValueError("%s must be an (x, y) pair, got shape %r" % (name, p.shape))

    ax, ay = p1
    bx, by = ap
    cx_, cy_ = p2

    d = 2.0 * (ax * (by - cy_) + bx * (cy_ - ay) + cx_ * (ay - by))
    if abs(d) < 1e-12:
        raise ValueError(
            "the three points are collinear, so no circle passes through them"
        )

    ux = (
        (ax * ax + ay * ay) * (by - cy_)
        + (bx * bx + by * by) * (cy_ - ay)
        + (cx_ * cx_ + cy_ * cy_) * (ay - by)
    ) / d
    uy = (
        (ax * ax + ay * ay) * (cx_ - bx)
        + (bx * bx + by * by) * (ax - cx_)
        + (cx_ * cx_ + cy_ * cy_) * (bx - ax)
    ) / d

    r = float(np.hypot(ax - ux, ay - uy))
    resid = float(
        max(abs(np.hypot(p[0] - ux, p[1] - uy) - r) for p in (p1, p2, ap))
    )

    a1 = math.atan2(ay - uy, ax - ux)
    a2 = math.atan2(cy_ - uy, cx_ - ux)
    aa = math.atan2(by - uy, bx - ux)

    def _norm(t: float) -> float:
        while t < 0:
            t += 2 * math.pi
        while t >= 2 * math.pi:
            t -= 2 * math.pi
        return t

    forward = _norm(a2 - a1)
    apex_fwd = _norm(aa - a1)
    sweep = forward if apex_fwd <= forward else 2 * math.pi - forward

    return ArcFit(r=r, cx=float(ux), cy=float(uy), sweep_deg=math.degrees(sweep), residual=resid)
