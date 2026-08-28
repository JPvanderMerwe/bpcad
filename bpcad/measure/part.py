"""
Reading a part out of a photograph.

WHAT THIS DOES THAT measure_reference DID NOT
---------------------------------------------
The earlier version reported a silhouette and an aspect ratio. True, but thin:
it told a model the picture was 0.71 as wide as it was tall, which is not
enough to design anything. This finds the FEATURES - where the entrance is, how
big it is, where the roof line sits, how far the roof overhangs - and reports
each with the evidence for it.

MEASURE, NEVER ESTIMATE, AND SAY WHICH IS WHICH
-----------------------------------------------
Every number here carries a confidence and, where one exists, a residual. A
circle fitted to an entrance hole with a 0.4 px residual really was a circle;
one fitted at 6 px was something else and is reported as unfound rather than
guessed at. Anything not found is absent from the result, never defaulted -
a plausible number nobody measured is worse than a gap.

An image still cannot give absolute size. Everything is in pixels, and in
millimetres only once a real dimension anchors the scale.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from bpcad.measure.fit import circle
from bpcad.measure.segment import (
    Box, as_array, background_cut, bbox, by_luminance, foreground, luminance,
)

# A hole has to be at least this fraction of the body width to be the entrance
# rather than a screw hole, a knot or a shadow.
MIN_HOLE_FRACTION = 0.06

# A circle fit worse than this, relative to its own radius, is not a circle.
MAX_HOLE_RESIDUAL_FRACTION = 0.12


@dataclass
class Measurement:
    """One measured quantity, with what backs it up."""

    name: str
    value: float
    units: str
    confidence: str          # "measured" | "fitted" | "inferred"
    evidence: str = ""

    def __str__(self) -> str:
        out = "%s = %.2f %s (%s)" % (self.name, self.value, self.units, self.confidence)
        return out + ("  %s" % self.evidence if self.evidence else "")


@dataclass
class PartMeasurement:
    """Everything that could be read out of one picture."""

    source: str
    silhouette: Box
    scale_mm_per_px: float | None = None
    view: str = "auto"
    items: list[Measurement] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def add(self, name: str, value: float, units: str, confidence: str,
            evidence: str = "") -> None:
        self.items.append(Measurement(name, value, units, confidence, evidence))

    def get(self, name: str) -> Measurement | None:
        for m in self.items:
            if m.name == name:
                return m
        return None

    def in_mm(self, name: str) -> float | None:
        """A measurement converted to mm, or None if there is no scale."""
        m = self.get(name)
        if m is None:
            return None
        if m.units == "mm":
            return m.value
        if m.units == "px" and self.scale_mm_per_px:
            return m.value * self.scale_mm_per_px
        return None

    def as_facts(self) -> dict[str, Any]:
        """
        A flat dict for a prompt. Millimetres where the scale allows, otherwise
        proportions - never raw pixels, which mean nothing to a reader.
        """
        out: dict[str, Any] = {}
        for m in self.items:
            if m.units == "px" and self.scale_mm_per_px:
                out["%s_mm" % m.name] = round(m.value * self.scale_mm_per_px, 1)
            elif m.units in ("deg", "fraction", "mm"):
                out["%s_%s" % (m.name, m.units)] = round(m.value, 3)
        if not self.scale_mm_per_px:
            out["note"] = (
                "proportions only - state how wide the real thing is to get "
                "millimetres"
            )
        return out

    def summary(self) -> list[str]:
        lines = ["measured from %s" % Path(self.source).name,
                 "  silhouette  %d x %d px" % (self.silhouette.width,
                                               self.silhouette.height)]
        if self.scale_mm_per_px:
            lines.append("  scale       %.4f mm/px" % self.scale_mm_per_px)
        for m in self.items:
            if m.units == "px" and self.scale_mm_per_px:
                lines.append("  %-22s %.1f mm   %s" % (
                    m.name, m.value * self.scale_mm_per_px, m.confidence))
            else:
                lines.append("  %-22s %.2f %s   %s" % (
                    m.name, m.value, m.units, m.confidence))
        lines += ["  %s" % n for n in self.notes]
        return lines


def _holes(mask: np.ndarray) -> list[tuple[np.ndarray, Box]]:
    """
    Enclosed regions of background inside the silhouette - candidate holes.

    A hole is background that the object completely surrounds. Anything
    connected to the border of the picture is the background itself.
    """
    from skimage.measure import label

    lab = label(~mask, connectivity=1, background=0)
    border = set(lab[0, :]) | set(lab[-1, :]) | set(lab[:, 0]) | set(lab[:, -1])
    border.discard(0)

    out = []
    for value in np.unique(lab):
        if value == 0 or value in border:
            continue
        blob = lab == value
        try:
            out.append((blob, bbox(blob)))
        except ValueError:
            continue
    return out


def find_entrance(mask: np.ndarray, body: Box) -> dict[str, Any] | None:
    """
    The entrance: the largest round hole in the upper half of the body.

    Roundness is tested by fitting a circle to the hole's boundary and looking
    at the residual. A hole that fits at a few percent of its radius really is
    round; one that does not is a window, a slot or a shadow, and is reported
    as not found rather than measured wrongly.
    """
    best = None
    for blob, box in _holes(mask):
        if box.width < body.width * MIN_HOLE_FRACTION:
            continue
        # Trace the hole's boundary and fit a circle to it.
        ys, xs = np.nonzero(blob)
        pts = []
        for y in np.unique(ys):
            row = xs[ys == y]
            pts.append((float(row.min()), float(y)))
            pts.append((float(row.max()), float(y)))
        if len(pts) < 12:
            continue
        try:
            fit = circle(pts)
        except ValueError:
            continue
        if fit.r <= 0 or fit.rms_residual / fit.r > MAX_HOLE_RESIDUAL_FRACTION:
            continue
        if best is None or fit.r > best["fit"].r:
            best = {"fit": fit, "box": box}
    return best


def roof_line(mask: np.ndarray, body: Box) -> dict[str, Any] | None:
    """
    The top edge of the object, and how steeply it slopes.

    Read as the highest filled pixel in each column across the middle of the
    body, then a straight line fitted through them. The slope is the roof
    pitch; the spread about the line says whether it really is a straight
    slope or something else, and a poor fit reports nothing.
    """
    top = np.full(mask.shape[1], np.nan)
    for x in range(body.left, body.right + 1):
        col = np.nonzero(mask[:, x])[0]
        if col.size:
            top[x] = col.min()

    xs = np.arange(mask.shape[1])
    keep = np.isfinite(top)
    # Ignore the outer eighth each side: corners and fillets are not the roof.
    # Trim a fifth off each end. The outer part of a roof silhouette is its
    # overhang and its rounded corners, neither of which is the slope; fitting
    # through them flattens the answer.
    margin = max(int(body.width * 0.20), 2)
    keep &= (xs >= body.left + margin) & (xs <= body.right - margin)
    if keep.sum() < 12:
        return None

    x, y = xs[keep].astype(float), top[keep]
    slope, intercept = np.polyfit(x, y, 1)
    residual = float(np.sqrt(np.mean((y - (slope * x + intercept)) ** 2)))

    if residual > max(body.height * 0.02, 2.0):
        return None            # not a straight roof line
    return {
        "slope": float(slope),
        "pitch_deg": float(abs(np.degrees(np.arctan(slope)))),
        "residual_px": residual,
        "n": int(keep.sum()),
    }


# What a given view can honestly tell you. A front photograph cannot see a roof
# that slopes front-to-back - it reports the pitch as zero, correctly and
# uselessly. A side photograph sees the slope but mistakes a ventilation slot
# for the entrance. Naming the view suppresses the measurements it cannot make,
# which is the difference between a gap and a wrong number.
VIEW_CAPABILITIES = {
    "front": {"entrance", "width", "height"},
    "back": {"width", "height"},
    "side": {"roof_pitch", "depth", "height"},
    "left": {"roof_pitch", "depth", "height"},
    "right": {"roof_pitch", "depth", "height"},
    "auto": {"entrance", "width", "height", "roof_pitch", "depth"},
}


def measure_part(
    image: str | Path,
    known_width_mm: float | None = None,
    cut: float | None = None,
    view: str = "auto",
) -> PartMeasurement:
    """
    Read a part out of a picture: its outline, its entrance, its roof.

    `view` says what the picture is of, so measurements that view cannot make
    are not attempted. With "auto" everything is tried and the caller has to
    judge - which is why naming the view is worth doing.

    Anything not found is left out. A missing measurement is a gap the prompt
    can fill; a wrong one is a part built to the wrong size.
    """
    path = Path(image)
    if not path.is_file():
        raise FileNotFoundError("no image at %s" % path)

    array = as_array(path)
    if cut is not None:
        mask = by_luminance(array, 0, cut)
    else:
        # Polarity read off the border, not assumed. A render is a light part
        # on a near-black viewport; a product shot is a dark part on white.
        mask = foreground(array)
    if not mask.any():
        raise ValueError(
            "nothing separated from the background - the object may touch the "
            "border of the picture, or fill the whole frame"
        )

    can = VIEW_CAPABILITIES.get(view, VIEW_CAPABILITIES["auto"])
    body = bbox(mask)
    out = PartMeasurement(source=str(path), silhouette=body)
    out.view = view

    if known_width_mm:
        out.scale_mm_per_px = known_width_mm / body.width
        out.notes.append(
            "scaled from a stated width of %.1f mm - every millimetre figure "
            "depends on that being right" % known_width_mm
        )
    else:
        out.notes.append(
            "no scale stated, so proportions only. An image cannot give "
            "absolute size."
        )

    out.add("overall_width", body.width, "px", "measured",
            "silhouette, columns %d to %d" % (body.left, body.right))
    out.add("overall_height", body.height, "px", "measured",
            "silhouette, rows %d to %d" % (body.top, body.bottom))
    out.add("aspect", body.width / body.height, "fraction", "measured")

    entrance = find_entrance(mask, body) if "entrance" in can else None
    if entrance is None and "entrance" not in can:
        out.notes.append(
            "a %s view cannot show the entrance, so it was not looked for" % view
        )
    if entrance:
        fit = entrance["fit"]
        out.add("entrance_diameter", 2 * fit.r, "px", "fitted",
                "circle fit, residual %.2f px over %d points"
                % (fit.rms_residual, fit.n))
        # Height of the hole's centre above the bottom of the object.
        out.add("entrance_height", body.bottom - fit.cy, "px", "fitted",
                "centre at row %.1f, body bottom at row %d" % (fit.cy, body.bottom))
        out.add("entrance_from_left", fit.cx - body.left, "px", "fitted")
    else:
        out.notes.append("no round entrance found")

    roof = roof_line(mask, body) if "roof_pitch" in can else None
    if roof and roof["pitch_deg"] > 1.0:
        out.add("roof_pitch", roof["pitch_deg"], "deg", "fitted",
                "top edge over %d columns, residual %.2f px - a silhouette "
                "flattens a slope slightly, so read this as approximate"
                % (roof["n"], roof["residual_px"]))
    elif "roof_pitch" not in can:
        out.notes.append(
            "a %s view looks along the roof slope, so the pitch is not "
            "measurable from it - photograph the side for that" % view
        )
    else:
        out.notes.append("no sloping roof line found")

    return out
