"""
Mesh-level checks: is this thing actually a solid, and how big is it.

Everything here is pure CPU and offline. It is the first gate a part passes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import trimesh

# A part at least this big, and at least this proportion of its own bounding
# box, is flagged as suspiciously solid. Both thresholds are deliberately high:
# small parts are legitimately solid, and so is a spacer or a wedge.
BULK_CM3 = 150.0
BULK_SOLIDITY = 0.80


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
    warnings: list[str] = field(default_factory=list)
    body_sizes: list = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems

    @property
    def solidity(self) -> float:
        """
        How much of its own bounding box the part actually fills, 0 to 1.

        Near 1 on a large part means a solid block, which is almost never what
        was wanted and is expensive enough to be worth saying out loud.
        """
        x, y, z = self.bbox_mm
        box_cm3 = (x * y * z) / 1000.0
        return self.volume_cm3 / box_cm3 if box_cm3 > 0 else 0.0


# Below this a triangle has no area worth the name. Generous next to a 0.005
# mm export tolerance, and far below anything a 0.4 mm nozzle could print.
ZERO_AREA_MM2 = 1e-9

# A pole triangle per sphere, and a little room for the odd seam. Above
# this and it is the export tolerance, not the tessellator.
DEGENERATE_FLOOR = 16


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
    return _without_zero_area_facets(loaded)


def _without_zero_area_facets(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    """
    Drop facets with no area, and remember how many there were.

    A SPHERE HAS NEVER PRODUCED A PRINTABLE MESH, and this is why. OpenCASCADE
    tessellates a sphere with a triangle fan at each pole, and writes one
    zero-area triangle at each of the two poles. Those two facets leave two
    unmatched edges, so trimesh reports the mesh as not watertight - at EVERY
    export tolerance, because the poles are a topology artifact and not a
    density one. Measured on a plain r=4.5 ball: 2 degenerate faces and 2 open
    edges at 0.005, at 0.01, at 0.05 and at 0.1.

    The consequence was that `sphere` - one of the fifteen primitives - failed
    verification every single time it was used, and so did anything unioned
    with one. "not watertight - the mesh has holes and will not slice" was one
    of the recurring failures in the eval.

    A ZERO-AREA TRIANGLE IS NOT GEOMETRY, so removing it cannot change the
    part: measured either way, the volume of that ball is 381.5284 mm3 before
    and 381.5284 mm3 after, to every digit trimesh prints. What it changes is
    whether the mesh is manifold, and it is the mesh that gets sliced.

    The count is kept on the mesh rather than thrown away, because the export
    tolerance being too fine ALSO produces degenerate facets - thousands of
    them - and that is a real fault worth reporting. See count_degenerate,
    which reads this back so the report says what was found rather than what
    survived.
    """
    try:
        keep = trimesh.triangles.area(mesh.triangles) > ZERO_AREA_MM2
        removed = int((~keep).sum())
        if removed:
            mesh.update_faces(keep)
            mesh.merge_vertices()
            mesh.remove_unreferenced_vertices()
        mesh.metadata["degenerate_removed"] = removed
    except Exception:
        # A mesh that cannot be measured is not made better by guessing at it.
        mesh.metadata["degenerate_removed"] = 0
    return mesh


def count_degenerate(mesh: trimesh.Trimesh) -> int:
    """
    Zero-area facets. An STL export tolerance that is too fine produces tens of
    thousands of these and the mesh stops being watertight, which is exactly
    why the export tolerance is pinned at 0.005 in config.
    """
    # What was FOUND, not what survived. load_mesh strips zero-area facets so
    # the two at a sphere's poles cannot fail an otherwise sound part, and it
    # records how many it removed - a tolerance set too fine produces them in
    # thousands, which is a real fault and still has to be reported.
    removed = int(mesh.metadata.get("degenerate_removed", 0) or 0)
    try:
        return removed + int((~mesh.nondegenerate_faces()).sum())
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
    # A HANDFUL IS THE TESSELLATOR, THOUSANDS IS THE TOLERANCE.
    #
    # OpenCASCADE writes one zero-area triangle at each pole of every sphere,
    # so a ball is always two and a part with four balls on it is always
    # eight. Those are removed on load and cannot make a mesh unwatertight any
    # more, and calling two of them a problem would fail every part with a
    # sphere in it for something that has no area and no consequence.
    #
    # An export tolerance set too fine produces them in the thousands, and
    # that IS the fault this check was written for. So the threshold is scaled
    # to the part rather than fixed: more than one facet in a thousand having
    # no area is a tessellation that has gone wrong.
    faces = max(len(mesh.faces), 1)
    if degenerate > max(DEGENERATE_FLOOR, faces // 1000):
        problems.append(
            "%d degenerate (zero-area) faces out of %d - lowering the STL "
            "export tolerance is NOT the fix, raise it. See config [export]."
            % (degenerate, faces)
        )

    # A part that is nearly its own bounding box, and big, is almost certainly
    # missing a hollow. Asked for a birdhouse, the level-2 path produced a
    # 120 x 100 x 145 mm block that was 96% solid - correct on the outside,
    # 2.1 kg of filament, and useless as a birdhouse. Nothing was looking.
    #
    # A warning, never a failure: a solid block is sometimes exactly right, and
    # a check that refuses one would be wrong. But at this size you should have
    # to mean it.
    warnings: list[str] = []
    extents = mesh.bounds[1] - mesh.bounds[0]
    box_cm3 = float(extents[0] * extents[1] * extents[2]) / 1000.0
    volume_cm3 = float(mesh.volume) / 1000.0
    if box_cm3 > 0:
        solidity = volume_cm3 / box_cm3
        if volume_cm3 >= BULK_CM3 and solidity >= BULK_SOLIDITY:
            warnings.append(
                "this part is %.0f%% of its own bounding box and %.0f cm3 of "
                "solid material. Nothing is hollow. If it was meant to be a "
                "shell, a container or an enclosure, a hollow operation is "
                "missing - as built it is roughly %.1f kg of filament."
                % (100 * solidity, volume_cm3, volume_cm3 * 1.27 / 1000.0)
            )

    # Per-body extents, so the bed check can tell "print it in two goes" from
    # "this cannot be made".
    body_sizes: list[tuple[float, float, float]] = []
    try:
        if mesh.body_count > 1:
            for piece in mesh.split(only_watertight=False):
                e = piece.bounds[1] - piece.bounds[0]
                body_sizes.append(tuple(float(v) for v in e))
    except Exception:
        body_sizes = []

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
        warnings=warnings,
        body_sizes=body_sizes,
    )
