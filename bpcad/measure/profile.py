"""
Row and column intensity profiles, and where they cross a threshold.

A scanline through a render is the cheapest honest measurement there is: it
gives edge positions in pixels with no fitting and no assumptions.
"""

from __future__ import annotations

import numpy as np

from bpcad.measure.segment import luminance


def profile(img, line: int, axis: str = "row") -> np.ndarray:
    """Luminance along one row or column, as a 1-D array."""
    lum = luminance(img)
    if axis == "row":
        if not 0 <= line < lum.shape[0]:
            raise IndexError(
                "row %d is outside the image, which has %d rows" % (line, lum.shape[0])
            )
        return lum[line, :]
    if axis in ("col", "column"):
        if not 0 <= line < lum.shape[1]:
            raise IndexError(
                "column %d is outside the image, which has %d columns"
                % (line, lum.shape[1])
            )
        return lum[:, line]
    raise ValueError("axis must be 'row' or 'col', got %r" % axis)


def transitions(img, line: int, threshold: float, axis: str = "row") -> list[int]:
    """
    Indices where the profile crosses `threshold`, in either direction.

    The index returned is the FIRST sample on the new side of the threshold, so
    a dark-to-light crossing reports the first light pixel. Consistency matters
    more than which side is chosen; measurements taken with one convention and
    compared under another are how off-by-one errors get into a part.
    """
    values = profile(img, line, axis=axis)
    above = values >= threshold
    return [int(i + 1) for i in np.flatnonzero(above[1:] != above[:-1])]


def spans(img, line: int, threshold: float, axis: str = "row", below: bool = True) -> list[tuple[int, int]]:
    """
    Inclusive runs along a scanline that sit below (or above) `threshold`.

    Handy for reading a silhouette straight off a row: on the reference render,
    row 100 comes back as two spans, which are the handle's two legs.
    """
    values = profile(img, line, axis=axis)
    hot = values < threshold if below else values >= threshold
    if not hot.any():
        return []
    padded = np.concatenate([[False], hot, [False]])
    edges = np.flatnonzero(padded[1:] != padded[:-1])
    return [(int(s), int(e - 1)) for s, e in zip(edges[::2], edges[1::2])]


def edges_subpixel(img, line: int, threshold: float, axis: str = "row") -> list[float]:
    """
    Threshold crossings to sub-pixel precision, by linear interpolation.

    An integer edge quantises to plus or minus half a pixel, and half a pixel of
    scatter is enough to bury the thing worth knowing. The reference handle fits
    a circle to 0.03 px; measured on integer edges the same arc comes out around
    0.3 px and looks like a curve that is only roughly circular. The extra
    precision is not decoration, it is the difference between proving the arc is
    a true circle and merely suspecting it.

    A render's edge is antialiased over about one pixel, so the luminance ramp
    across it really does carry sub-pixel information about where the true edge
    lies. This reads it back out.
    """
    values = profile(img, line, axis=axis)
    above = values >= threshold
    out: list[float] = []
    for i in np.flatnonzero(above[1:] != above[:-1]):
        v0, v1 = float(values[i]), float(values[i + 1])
        if v1 == v0:
            out.append(float(i) + 0.5)
        else:
            out.append(float(i) + (threshold - v0) / (v1 - v0))
    return out


def spans_subpixel(img, line: int, threshold: float, axis: str = "row") -> list[tuple[float, float]]:
    """
    Sub-pixel runs below `threshold` along a scanline, as (start, end) pairs.

    Only complete spans are returned - a run touching either end of the line has
    one edge missing and would report a boundary that is an artefact of where the
    image stops rather than where the object does.
    """
    values = profile(img, line, axis=axis)
    crossings = edges_subpixel(img, line, threshold, axis=axis)
    if not crossings:
        return []
    starts_dark = bool(values[0] < threshold)
    if starts_dark:
        crossings = crossings[1:]          # drop the clipped opening edge
    return [(a, b) for a, b in zip(crossings[::2], crossings[1::2])]
