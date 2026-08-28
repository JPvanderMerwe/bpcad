"""
Standard views, the height map, and sections.

All of it goes through the z-buffer rasteriser. No matplotlib figures, no Agg
backend, no OpenGL - matplotlib is used here only to look up a colour map.

THE HEIGHT MAP IS THE PRIMARY GEOMETRY-VERIFICATION VISUAL.
A flat-shaded render cannot show a recess whose floor shares a normal with the
surrounding face: both faces point the same way, so both take the same shade
and the recess is invisible. Colouring by surface height makes it obvious.
Look at the height map, not the pretty render.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import trimesh
from PIL import Image, ImageDraw

from bpcad.render.raster import Bounds, render, view_basis
from bpcad.verify.probe import height_map, surface_levels

# (elev, azim). azim is measured about +Z from +X toward +Y; the camera sits in
# that direction and looks back at the part. See raster.view_basis.
VIEWS: dict[str, tuple[float, float]] = {
    "front": (0.0, 270.0),      # camera on -Y
    "back": (0.0, 90.0),        # camera on +Y
    "side": (0.0, 0.0),         # camera on +X
    "left": (0.0, 180.0),       # camera on -X
    "above": (90.0, 270.0),     # camera on +Z
    "below": (-90.0, 270.0),    # camera on -Z
    "3q": (25.0, 315.0),        # three-quarter, above and to the front-right
}

DEFAULT_VIEWS = ("front", "3q", "side", "above")


def _save(img: np.ndarray, path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(img).save(p)
    return p


def render_view(
    mesh: trimesh.Trimesh,
    view: str = "3q",
    width: int = 900,
    height: int = 700,
    **kwargs,
) -> np.ndarray:
    if view not in VIEWS:
        raise ValueError(
            "unknown view %r. Known views: %s" % (view, ", ".join(sorted(VIEWS)))
        )
    elev, azim = VIEWS[view]
    return render(
        np.asarray(mesh.vertices, dtype=float),
        np.asarray(mesh.faces),
        np.asarray(mesh.face_normals, dtype=float),
        width=width,
        height=height,
        elev_deg=elev,
        azim_deg=azim,
        **kwargs,
    )


def render_view_to(
    mesh: trimesh.Trimesh,
    out_path: str | Path,
    view: str = "3q",
    width: int = 900,
    height: int = 700,
    **kwargs,
) -> Path:
    """Render one named view straight to a file."""
    return _save(render_view(mesh, view, width=width, height=height, **kwargs), out_path)


def standard_views(
    mesh: trimesh.Trimesh,
    out_dir: str | Path,
    which=DEFAULT_VIEWS,
    stem: str = "view",
    width: int = 900,
    height: int = 700,
    **kwargs,
) -> dict[str, Path]:
    """Render each named view to <out_dir>/<stem>_<name>.png."""
    out: dict[str, Path] = {}
    for name in which:
        img = render_view(mesh, name, width=width, height=height, **kwargs)
        out[name] = _save(img, Path(out_dir) / ("%s_%s.png" % (stem, name)))
    return out


def colourise(
    hmap: np.ndarray,
    cmap_name: str = "inferno",
    background: tuple[float, float, float] = (0.078, 0.086, 0.102),
) -> np.ndarray:
    """Height map array -> RGB image, flipped so row 0 is the top."""
    from matplotlib import colormaps

    finite = np.isfinite(hmap)
    img = np.empty(hmap.shape + (3,), dtype=float)
    img[:, :] = np.asarray(background, dtype=float)

    if finite.any():
        vals = hmap[finite]
        lo, hi = float(vals.min()), float(vals.max())
        span = hi - lo if hi > lo else 1.0
        norm = (vals - lo) / span
        img[finite] = colormaps[cmap_name](norm)[:, :3]

    return (np.flipud(img) * 255.0 + 0.5).astype(np.uint8)


def _scale_strip(
    img: np.ndarray,
    lo: float,
    hi: float,
    cmap_name: str,
    background: tuple[float, float, float],
) -> np.ndarray:
    """
    A narrow gradient bar with the height range on it.

    A height map with no scale tells you there are steps but not how deep they
    are, and depth is usually the thing being checked.
    """
    from matplotlib import colormaps

    h, w = img.shape[:2]
    bar_w, pad = 26, 64
    strip = np.empty((h, bar_w + pad, 3), dtype=float)
    strip[:, :] = np.asarray(background, dtype=float)

    top, bot = int(0.08 * h), int(0.92 * h)
    ramp = np.linspace(1.0, 0.0, bot - top)
    strip[top:bot, :bar_w] = colormaps[cmap_name](ramp)[:, None, :3]

    out = np.concatenate(
        [img, (strip * 255.0 + 0.5).astype(np.uint8)], axis=1
    )
    pil = Image.fromarray(out)
    draw = ImageDraw.Draw(pil)
    x = w + bar_w + 4
    draw.text((x, top - 6), "%.2f" % hi, fill=(230, 232, 236))
    draw.text((x, bot - 6), "%.2f" % lo, fill=(230, 232, 236))
    draw.text((x, (top + bot) // 2 - 6), "mm", fill=(150, 154, 160))
    return np.asarray(pil)


def height_map_image(
    mesh: trimesh.Trimesh,
    out_path: str | Path,
    axis: str = "z",
    nx: int = 900,
    ny: int = 900,
    cmap_name: str = "inferno",
    background: tuple[float, float, float] = (0.078, 0.086, 0.102),
    scale_bar: bool = True,
) -> Path:
    """
    Write the height map. Pixel aspect matches the part, so a square part comes
    out square.
    """
    tri = np.asarray(mesh.vertices, dtype=float)
    from bpcad.render.raster import AXIS_COLUMNS

    cu, cv, _ = AXIS_COLUMNS[axis]
    u0, u1 = float(tri[:, cu].min()), float(tri[:, cu].max())
    v0, v1 = float(tri[:, cv].min()), float(tri[:, cv].max())

    span_u, span_v = max(u1 - u0, 1e-9), max(v1 - v0, 1e-9)
    if span_u >= span_v:
        nx, ny = nx, max(2, int(round(nx * span_v / span_u)))
    else:
        nx, ny = max(2, int(round(ny * span_u / span_v))), ny

    hmap = height_map(mesh, nx=nx, ny=ny, axis=axis, bounds=Bounds(u0, u1, v0, v1))
    img = colourise(hmap, cmap_name=cmap_name, background=background)

    if scale_bar and np.isfinite(hmap).any():
        vals = hmap[np.isfinite(hmap)]
        img = _scale_strip(img, float(vals.min()), float(vals.max()), cmap_name, background)

    return _save(img, out_path)


def cutaway_mask(
    mesh: trimesh.Trimesh,
    axis: str = "y",
    position: float | None = None,
    view: str = "3q",
    keep: str = "auto",
) -> np.ndarray:
    """
    Which faces survive a cutaway, as a boolean mask over mesh.faces.

    Split out from section() so the rule can be asserted directly. Getting the
    side backwards renders the outside of the part again and looks exactly like
    a cutaway that quietly did nothing, which is not a failure you notice.

    keep="auto" discards the half between the camera and the cut plane.
    "low" and "high" keep the half below or above `position` regardless of
    where the camera is.
    """
    if view not in VIEWS:
        raise ValueError(
            "unknown view %r. Known views: %s" % (view, ", ".join(sorted(VIEWS)))
        )
    if axis not in "xyz":
        raise ValueError("axis must be x, y or z, got %r" % axis)

    col = "xyz".index(axis)
    if position is None:
        position = float(mesh.bounds[:, col].mean())

    if keep == "auto":
        # view_vec points from the scene toward the camera, so its component
        # along the cut axis says which side the camera is on. Discard that side.
        _, _, view_vec = view_basis(*VIEWS[view])
        keep_low = view_vec[col] > 0
    elif keep in ("low", "high"):
        keep_low = keep == "low"
    else:
        raise ValueError("keep must be 'auto', 'low' or 'high', got %r" % keep)

    centres = np.asarray(mesh.triangles_center, dtype=float)[:, col]
    return centres <= position if keep_low else centres >= position


def section(
    mesh: trimesh.Trimesh,
    out_path: str | Path,
    axis: str = "y",
    position: float | None = None,
    view: str = "3q",
    keep: str = "auto",
    width: int = 900,
    height: int = 700,
    **kwargs,
) -> Path:
    """
    Cutaway view: drop the half of the part between the camera and the cut
    plane, and render what is left, so interior surfaces become visible.

    This is how you check a hollow, a cavity floor or a pocket that no external
    view can show. See cutaway_mask for which half goes.

    The cut face is OPEN, not capped. Capping means triangulating the
    cross-section polygon, and the only library in reach for that is shapely,
    which is not in this project's dependency list. An open cut shows the
    interior surfaces perfectly well, which is the whole reason to take a
    section. Say the word if a capped section is ever worth a dependency.

    Triangles straddling the plane are kept or dropped whole rather than being
    clipped, so the cut edge is ragged by up to one triangle. At the mesh
    densities this project exports that is well under a pixel.
    """
    mask = cutaway_mask(mesh, axis=axis, position=position, view=view, keep=keep)
    if not mask.any():
        col = "xyz".index(axis)
        raise ValueError(
            "the section plane leaves nothing to render on axis %s. "
            "The part spans %.3f to %.3f there."
            % (axis, mesh.bounds[0][col], mesh.bounds[1][col])
        )

    elev, azim = VIEWS[view]
    img = render(
        np.asarray(mesh.vertices, dtype=float),
        np.asarray(mesh.faces)[mask],
        np.asarray(mesh.face_normals, dtype=float)[mask],
        width=width,
        height=height,
        elev_deg=elev,
        azim_deg=azim,
        **kwargs,
    )
    return _save(img, out_path)


def level_summary(mesh: trimesh.Trimesh, axis: str = "z") -> list[str]:
    """One line per flat surface, for printing next to the height map."""
    return [
        "%8.3f mm   %10.2f mm2" % (lv.height_mm, lv.area_mm2)
        for lv in surface_levels(mesh, axis=axis)
    ]
