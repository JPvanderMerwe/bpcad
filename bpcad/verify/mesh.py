"""
Mesh-level checks: is this thing actually a solid, and how big is it.

Everything here is pure CPU and offline. It is the first gate a part passes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import trimesh


@dataclass
class MeshReport:
    """What check_mesh found. Feeds verify.report and verify.regression."""

    path: str
    watertight: bool
    is_volume: bool
    winding_consistent: bool
    body_count: int
    face_count: int
    vertex_count: int
    volume_cm3: float
    bbox_mm: tuple[float, float, float]
    bbox_min_mm: tuple[float, float, float]
    degenerate_faces: int
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


def load_mesh(stl_path: str | Path) -> trimesh.Trimesh:
    """
    Load an STL as a single Trimesh.

    trimesh hands back a Scene for some files. Concatenating is correct here:
    body_count still reports the separate shells afterwards, so nothing is
    hidden by doing it.
    """
    p = Path(stl_path)
    if not p.is_file():
        raise FileNotFoundError("no mesh at %s" % p)

    loaded = trimesh.load_mesh(str(p))
    if isinstance(loaded, trimesh.Scene):
        geoms = list(loaded.geometry.values())
        if not geoms:
            raise ValueError("%s contains no geometry" % p)
        loaded = trimesh.util.concatenate(geoms)
    return loaded


def count_degenerate(mesh: trimesh.Trimesh) -> int:
    """
    Zero-area facets. An STL export tolerance that is too fine produces tens of
    thousands of these and the mesh stops being watertight, which is exactly
    why the export tolerance is pinned at 0.005 in config.
    """
    try:
        return int((~mesh.nondegenerate_faces()).sum())
    except Exception:
        # Fall back to measuring the areas directly rather than reporting a
        # number we did not actually compute.
        tris = mesh.vertices[mesh.faces]
        cross = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
        return int((np.linalg.norm(cross, axis=1) <= 1e-12).sum())


def check_mesh(stl_path: str | Path) -> MeshReport:
    """Run every mesh-level check and collect the failures in one place."""
    mesh = load_mesh(stl_path)
    return report_for(mesh, str(stl_path))


def report_for(mesh: trimesh.Trimesh, path: str = "<mesh>") -> MeshReport:
    """The same checks against an already-loaded mesh."""
    extents = mesh.bounds[1] - mesh.bounds[0]
    degenerate = count_degenerate(mesh)

    problems: list[str] = []
    if not mesh.is_watertight:
        problems.append(
            "not watertight - the mesh has holes and will not slice reliably"
        )
    if not mesh.is_volume:
        problems.append(
            "not a volume - watertight but self-intersecting or badly wound, "
            "so it encloses no well-defined solid"
        )
    if not mesh.is_winding_consistent:
        problems.append("winding is inconsistent - some faces point inward")
    if degenerate:
        problems.append(
            "%d degenerate (zero-area) faces - lower the STL export tolerance "
            "is NOT the fix, raise it. See config [export]." % degenerate
        )

    return MeshReport(
        path=path,
        watertight=bool(mesh.is_watertight),
        is_volume=bool(mesh.is_volume),
        winding_consistent=bool(mesh.is_winding_consistent),
        body_count=int(mesh.body_count),
        face_count=int(len(mesh.faces)),
        vertex_count=int(len(mesh.vertices)),
        volume_cm3=float(mesh.volume) / 1000.0,
        bbox_mm=tuple(float(v) for v in extents),
        bbox_min_mm=tuple(float(v) for v in mesh.bounds[0]),
        degenerate_faces=degenerate,
        problems=problems,
    )
