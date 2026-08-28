"""
Colour and luminance segmentation, bounding boxes, run detection.

Measure, never estimate. Every dimension that ends up in a spec comes from
here, not from an eyeball read of a picture. The reference session's pixel
measurements - body 567 x 553, module 227 x 436, trim bands ten rows deep -
were all produced this way, and this module is the generalised version of it.

Pixel indices are INCLUSIVE at both ends, because that is how the reference
measurements are written: BODY_L_PX, BODY_R_PX = 43, 609 is 567 columns, not
566. Box.width does the +1 for you.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import numpy as np
from PIL import Image


@dataclass(frozen=True)
class Box:
    """An inclusive pixel bounding box."""

    left: int
    right: int
    top: int
    bottom: int

    @property
    def width(self) -> int:
        return self.right - self.left + 1

    @property
    def height(self) -> int:
        return self.bottom - self.top + 1

    @property
    def centre(self) -> tuple[float, float]:
        return ((self.left + self.right) / 2.0, (self.top + self.bottom) / 2.0)

    def as_tuple(self) -> tuple[int, int, int, int]:
        return (self.left, self.right, self.top, self.bottom)

    def slices(self) -> tuple[slice, slice]:
        """Row and column slices, ready for numpy indexing."""
        return (slice(self.top, self.bottom + 1), slice(self.left, self.right + 1))

    def __str__(self) -> str:
        return "L%d R%d T%d B%d  (%d x %d px)" % (
            self.left, self.right, self.top, self.bottom, self.width, self.height
        )


def as_array(img) -> np.ndarray:
    """
    Accept a path, a PIL image or an array, and return RGB uint8.

    Alpha is dropped rather than composited. A render exported with a
    transparency checkerboard baked in has an opaque alpha channel anyway, and
    silently compositing onto an assumed background colour would be exactly the
    kind of invented number this project refuses to produce.
    """
    if isinstance(img, np.ndarray):
        a = img
    elif isinstance(img, Image.Image):
        a = np.array(img)
    elif isinstance(img, (str, os.PathLike)):
        a = np.array(Image.open(img))
    else:
        raise TypeError(
            "expected a path, a PIL image or an array, got %s" % type(img).__name__
        )

    if a.ndim == 2:
        a = np.stack([a] * 3, axis=-1)
    if a.shape[2] == 4:
        a = a[:, :, :3]
    if a.shape[2] != 3:
        raise ValueError("expected 3 or 4 channels, got %d" % a.shape[2])
    return a.astype(np.uint8)


def luminance(img) -> np.ndarray:
    """Mean channel value, 0..255. Flat mean, not a perceptual weighting."""
    return as_array(img).astype(float).mean(axis=2)


def by_colour(img, target_rgb, tol: float) -> np.ndarray:
    """
    Pixels within `tol` of `target_rgb` by straight Euclidean distance in RGB.

    Euclidean rather than per-channel so one tolerance number means one thing.
    Pick the target by sampling the image, not by naming a colour.
    """
    a = as_array(img).astype(float)
    target = np.asarray(target_rgb, dtype=float)
    if target.shape != (3,):
        raise ValueError("target_rgb must be three numbers, got %r" % (target_rgb,))
    if tol < 0:
        raise ValueError("tol must not be negative, got %r" % tol)
    return np.sqrt(((a - target) ** 2).sum(axis=2)) <= tol


def by_luminance(img, lo: float, hi: float) -> np.ndarray:
    """Pixels whose mean channel value falls in [lo, hi], both ends inclusive."""
    if lo > hi:
        raise ValueError("lo must not exceed hi, got lo=%r hi=%r" % (lo, hi))
    lum = luminance(img)
    return (lum >= lo) & (lum <= hi)


def saturation(img) -> np.ndarray:
    """
    Channel spread, max(RGB) - min(RGB), 0..255.

    A cheap, robust "how colourful is this pixel" that does not care about
    brightness. On the reference render it separates the neutral grey display
    bezel (spread 0-1) from the green fabric around it and the green screen
    inside it (spread 38-46) with a margin nothing else comes close to -
    luminance cannot do it at all, because the bezel and the fabric overlap
    almost completely in brightness.
    """
    a = as_array(img).astype(int)
    return (a.max(axis=2) - a.min(axis=2)).astype(float)


def by_saturation(img, lo: float, hi: float) -> np.ndarray:
    """Pixels whose channel spread falls in [lo, hi], both ends inclusive."""
    if lo > hi:
        raise ValueError("lo must not exceed hi, got lo=%r hi=%r" % (lo, hi))
    sat = saturation(img)
    return (sat >= lo) & (sat <= hi)


def background_cut(img, border: int = 3) -> float:
    """
    Luminance at or above which a pixel is background, taken from the image
    border. Returns the darkest border pixel's luminance, minus a hair.

    Otsu's threshold is the right tool for separating a dark object from a light
    field, but it lands in the middle of the gap and therefore throws away the
    partly-covered pixels along an antialiased edge. For reading an object's
    EXTENT you want the other end of the gap: the last pixel that is darker than
    any background pixel still belongs to the object.

    This also handles a transparency checkerboard, which is what caught me on
    the reference render. Its two tile values are luminance 234 and 252, and a
    cut chosen by eye at 235 sits INSIDE the darker tile - so seven columns of
    background read as part of the device and the fabric waist came out 6 px too
    wide. Reading the darkest border pixel gets it right without a guess.

    Assumes the object does not touch the image border. If it does, this returns
    a cut based on the object and everything downstream is wrong, so check.
    """
    lum = luminance(img)
    if border < 1:
        raise ValueError("border must be at least 1 pixel, got %r" % border)
    ring = np.concatenate([
        lum[:border, :].ravel(),
        lum[-border:, :].ravel(),
        lum[:, :border].ravel(),
        lum[:, -border:].ravel(),
    ])
    return float(ring.min()) - 0.5


def auto_threshold(img) -> float:
    """
    Otsu's threshold on the image's luminance.

    Pick the threshold from the image, not by eye. On the reference render this
    lands at 169.9 and puts the body's bottom edge on row 835, which is the
    row the original measurement used - the edge is antialiased over about two
    pixels, so a threshold chosen by hand can land a pixel either side of it.
    """
    from skimage.filters import threshold_otsu

    return float(threshold_otsu(luminance(img)))


def fill_holes(mask: np.ndarray) -> np.ndarray:
    """
    Close any region of False fully enclosed by True.

    Needed more often than it looks. On the reference render the screen's white
    UI cards are the same colour as the white background, so a brightness
    threshold punches holes straight through the middle of the device. They are
    not background - they are surrounded by it on no side. Filling anything not
    connected to the image border fixes it without a single tuned number.
    """
    from skimage.measure import label

    mask = np.asarray(mask, dtype=bool)
    lab = label(~mask, connectivity=1, background=0)
    border = set(lab[0, :]) | set(lab[-1, :]) | set(lab[:, 0]) | set(lab[:, -1])
    border.discard(0)
    outside = np.isin(lab, list(border))
    return mask | (~mask & ~outside)


def largest_component(mask: np.ndarray, connectivity: int = 2) -> np.ndarray:
    """
    Keep only the biggest connected blob.

    A colour or brightness test finds every pixel of a kind, scattered across
    the whole image. When what you want is one OBJECT - the display module, not
    every neutral-grey pixel in the frame - this is the step that says so.
    Without it a stray highlight at the edge of the picture silently widens a
    bounding box and the measurement is quietly wrong.
    """
    from skimage.measure import label

    mask = np.asarray(mask, dtype=bool)
    if not mask.any():
        raise ValueError("the mask is empty, so it has no components")
    lab = label(mask, connectivity=connectivity)
    counts = np.bincount(lab.ravel())
    counts[0] = 0
    return lab == int(counts.argmax())


def edge_profile(mask: np.ndarray, side: str = "left") -> np.ndarray:
    """
    The first True column in each row (or row in each column), as a float array
    with NaN where that line is empty.

    This is how a corner radius gets measured: walk the silhouette edge down
    through the corner, then fit a circle to the points. `side` is "left",
    "right", "top" or "bottom".
    """
    mask = np.asarray(mask, dtype=bool)
    if side in ("left", "right"):
        out = np.full(mask.shape[0], np.nan)
        for i in range(mask.shape[0]):
            idx = np.flatnonzero(mask[i])
            if idx.size:
                out[i] = float(idx[0] if side == "left" else idx[-1])
        return out
    if side in ("top", "bottom"):
        out = np.full(mask.shape[1], np.nan)
        for j in range(mask.shape[1]):
            idx = np.flatnonzero(mask[:, j])
            if idx.size:
                out[j] = float(idx[0] if side == "top" else idx[-1])
        return out
    raise ValueError("side must be left, right, top or bottom, got %r" % side)


def foreground(img, border: int = 3) -> np.ndarray:
    """
    The object, whichever way round the picture is.

    An earlier version assumed a dark object on a light field, which is true of
    a product shot on white and false of every render this program produces -
    those are light parts on a near-black viewport, and the assumption selected
    nothing at all.

    So the polarity is read off the border rather than assumed: whichever side
    of the border's brightness the middle of the picture sits on is the object.
    """
    lum = luminance(img)
    if border < 1:
        raise ValueError("border must be at least 1 pixel, got %r" % border)

    ring = np.concatenate([
        lum[:border, :].ravel(), lum[-border:, :].ravel(),
        lum[:, :border].ravel(), lum[:, -border:].ravel(),
    ])
    lo, hi = float(ring.min()), float(ring.max())

    h, w = lum.shape
    middle = lum[h // 4: 3 * h // 4, w // 4: 3 * w // 4]
    centre = float(np.median(middle))

    if centre < lo:
        return lum <= lo - 0.5          # dark object on a light field
    if centre > hi:
        return lum >= hi + 0.5          # light object on a dark field
    # The middle sits inside the border's own range - fall back to whichever
    # side is further from it, and say so by returning the larger separation.
    return lum <= lo - 0.5 if (lo - centre) > (centre - hi) else lum >= hi + 0.5


def bbox(mask: np.ndarray) -> Box:
    """Inclusive bounding box of every True pixel."""
    mask = np.asarray(mask, dtype=bool)
    if mask.ndim != 2:
        raise ValueError("mask must be 2-D, got %d dimensions" % mask.ndim)
    rows = np.flatnonzero(mask.any(axis=1))
    cols = np.flatnonzero(mask.any(axis=0))
    if rows.size == 0:
        raise ValueError("the mask is empty, so it has no bounding box")
    return Box(
        left=int(cols[0]), right=int(cols[-1]), top=int(rows[0]), bottom=int(rows[-1])
    )


def coverage(mask: np.ndarray, axis: str = "row") -> np.ndarray:
    """
    Fraction of each row (or column) that is True. This is what run detection
    thresholds on, and it is worth having on its own for plotting a profile.
    """
    mask = np.asarray(mask, dtype=bool)
    if axis == "row":
        return mask.mean(axis=1)
    if axis in ("col", "column"):
        return mask.mean(axis=0)
    raise ValueError("axis must be 'row' or 'col', got %r" % axis)


def runs(mask: np.ndarray, axis: str = "row", min_frac: float = 0.5) -> list[tuple[int, int]]:
    """
    Contiguous bands of rows (or columns) where the mask covers at least
    `min_frac` of that line. Inclusive (start, end) pairs.

    This is how the trim bands were measured: the black trim covers nearly the
    full width of the body, so thresholding row coverage isolates it cleanly
    while ignoring dark pixels scattered elsewhere.
    """
    cov = coverage(mask, axis=axis)
    hot = cov >= min_frac
    if not hot.any():
        return []
    padded = np.concatenate([[False], hot, [False]])
    edges = np.flatnonzero(padded[1:] != padded[:-1])
    return [(int(s), int(e - 1)) for s, e in zip(edges[::2], edges[1::2])]
