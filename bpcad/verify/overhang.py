"""
Face-normal overhang against the print axis, and how far each overhang falls.

Convention, stated once so it is not re-derived wrongly later:

    Overhang is measured FROM VERTICAL, the way a slicer measures it.
    A wall parallel to the print axis is 0 degrees and needs nothing.
    A horizontal ceiling is 90 degrees and is an underside.
    The threshold is the angle beyond which the lean matters, 45 by default.

Faces sitting on the bed are excluded. They point straight down and would score
90 degrees, but the bed is holding them up, so flagging them is noise.

WHY THE DROP IS MEASURED TOO
----------------------------
A face normal says an underside exists. It says nothing about what is beneath
it. On a print-in-place mechanism every deliberate air gap is a 90-degree
underside: the louvre vent reference has 2072 mm2 of them and prints with no
support at all, because each gap is PIN_GAP_Z = 0.30 mm and the layer above
sags straight onto the surface below. A 0.30 mm shoulder gap and a 26 mm fall
into open air are identical to a normal test and completely different to print.

So every flagged face gets a ray cast straight down. Anything falling less than
max_bridge_gap_mm is a gap the next layer closes by itself.

WHAT THIS STILL DOES NOT DO
---------------------------
It does not analyse horizontal span, so it cannot tell a genuine BRIDGE - a
ceiling anchored on both sides, which FDM prints happily across tens of mm -
from a cantilever hanging over nothing. Both show up as a large drop. Read
`unsupported_area_mm2` as "needs support OR is a bridge", and look at the
cutaway render before believing it. Span analysis is a slicer's job and is not
attempted here.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import trimesh

from bpcad.render.raster import AXIS_COLUMNS

# How close to the lowest point a face has to be to count as sitting on the bed.
BED_TOL_MM = 1e-3

# Default largest fall the layer above closes on its own.
# Source: PIN_GAP_Z = 0.30 mm in reference/vent_louvre.py, which prints with no
# support at 0.20 mm layers. Padded to 0.50 so a proven 0.30 gap passes with
# margin rather than sitting on the boundary. Overridable, and exposed in
# config as [limits].max_bridge_gap_mm.
MAX_BRIDGE_GAP_MM = 0.50


@dataclass
class OverhangReport:
    print_axis: str
    max_deg: float
    max_bridge_gap_mm: float
    worst_overhang_deg: float
    overhang_area_mm2: float          # every underside past the angle threshold
    bridged_area_mm2: float           # ...of which falls less than the gap
    unsupported_area_mm2: float       # ...of which falls further
    max_drop_mm: float
    downward_area_mm2: float
    total_area_mm2: float
    bed_area_mm2: float
    overhang_face_count: int
    unsupported_face_count: int
    problems: list[str] = field(default_factory=list)

    @property
    def supports_needed(self) -> bool:
        return self.unsupported_area_mm2 > 0.0

    @property
    def overhang_fraction(self) -> float:
        if self.total_area_mm2 <= 0:
            return 0.0
        return self.overhang_area_mm2 / self.total_area_mm2

    @property
    def unsupported_fraction(self) -> float:
        if self.total_area_mm2 <= 0:
            return 0.0
        return self.unsupported_area_mm2 / self.total_area_mm2

    @property
    def ok(self) -> bool:
        return not self.problems


def overhang_report(
    mesh: trimesh.Trimesh,
    print_axis: str = "z",
    max_deg: float = 45.0,
    max_bridge_gap_mm: float = MAX_BRIDGE_GAP_MM,
) -> OverhangReport:
    """
    Every downward-facing face, how far past vertical it leans, how far it
    falls, and whether the part therefore needs support.
    """
    if print_axis not in AXIS_COLUMNS:
        raise ValueError(
            "print_axis must be one of %s, got %r"
            % (", ".join(sorted(AXIS_COLUMNS)), print_axis)
        )
    cu, cv, cw = AXIS_COLUMNS[print_axis]

    normals = np.asarray(mesh.face_normals, dtype=float)
    areas = np.asarray(mesh.area_faces, dtype=float)
    centres = np.asarray(mesh.triangles_center, dtype=float)

    # Positive where the face looks downward, i.e. it is an underside.
    down = np.clip(-normals[:, cw], 0.0, 1.0)
    # sin of the lean from vertical: 0 for a wall, 1 for a flat ceiling.
    angles = np.degrees(np.arcsin(down))

    bed_level = float(mesh.bounds[0][cw])
    on_bed = (centres[:, cw] - bed_level) <= BED_TOL_MM
    downward = (down > 0.0) & ~on_bed
    flagged = downward & (angles > max_deg)

    worst = float(angles[downward].max()) if downward.any() else 0.0
    overhang_area = float(areas[flagged].sum())

    drops = _drops(mesh, flagged, centres, cu, cv, cw, bed_level, print_axis)
    bridged = flagged.copy()
    bridged[flagged] = drops <= max_bridge_gap_mm
    unsupported = flagged & ~bridged

    problems: list[str] = []
    if unsupported.any():
        problems.append(
            "%d faces totalling %.2f mm2 overhang past %.0f degrees and fall "
            "more than %.2f mm (worst drop %.2f mm) - this part needs support "
            "as oriented, unless those undersides are bridges anchored both "
            "sides, which this check cannot tell apart"
            % (int(unsupported.sum()), float(areas[unsupported].sum()), max_deg,
               max_bridge_gap_mm, float(drops.max()) if len(drops) else 0.0)
        )

    return OverhangReport(
        print_axis=print_axis,
        max_deg=max_deg,
        max_bridge_gap_mm=max_bridge_gap_mm,
        worst_overhang_deg=worst,
        overhang_area_mm2=overhang_area,
        bridged_area_mm2=float(areas[bridged].sum()),
        unsupported_area_mm2=float(areas[unsupported].sum()),
        max_drop_mm=float(drops.max()) if len(drops) else 0.0,
        downward_area_mm2=float(areas[downward].sum()),
        total_area_mm2=float(areas.sum()),
        bed_area_mm2=float(areas[on_bed].sum()),
        overhang_face_count=int(flagged.sum()),
        unsupported_face_count=int(unsupported.sum()),
        problems=problems,
    )


def _drops(
    mesh: trimesh.Trimesh,
    flagged: np.ndarray,
    centres: np.ndarray,
    cu: int,
    cv: int,
    cw: int,
    bed_level: float,
    print_axis: str,
) -> np.ndarray:
    """
    How far each flagged face falls before it meets something.

    Sampled at the face centroid - one ray per triangle. On the meshes this
    project exports a triangle is a fraction of a millimetre across, so a
    single sample per face is not a meaningful approximation. Nothing beneath
    means it falls all the way to the bed.
    """
    from bpcad.verify.probe import surface_below

    if not flagged.any():
        return np.array([])

    pts = centres[flagged][:, [cu, cv]]
    tops = centres[flagged][:, cw]
    below = np.asarray(surface_below(mesh, pts, tops, axis=print_axis), dtype=float)
    below = np.where(np.isfinite(below), below, bed_level)
    return tops - below
