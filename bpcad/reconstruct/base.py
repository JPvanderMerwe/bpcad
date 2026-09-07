"""
Photo to mesh: the seam, and what it promises.

WHAT THIS ADDS TO BPCAD, AND WHAT IT DOES NOT CHANGE
----------------------------------------------------
Until now a photograph could only be MEASURED - a silhouette, an entrance, a
roof pitch, each with a residual - and a person or a model turned those numbers
into a spec. That is accurate and it cannot invent a shape it has no template
for.

This is the other direction: a neural reconstruction that produces a MESH from
one image, the way meshy.ai does. It is a new way IN, and it changes nothing
downstream. In particular it does not touch the founding decision, because a
reconstructed mesh is not a spec and is never treated as one:

    photo -> mesh          (this module: neural, approximate, no dimensions)
    mesh  -> spec          (bpcad/imports.py: the revolve and prism fitters,
                            already written, with residuals)
    spec  -> geometry      (deterministic Python, as always)

So a reconstruction arrives in the library as an IMPORT - origin `imported`,
editable only if a fitter recovered a profile from it - and everything that
already refuses to lie about an imported mesh keeps refusing.

THE THREE HONEST LIMITS, WRITTEN HERE SO NO UI HAS TO REMEMBER THEM
-------------------------------------------------------------------
1. NO PHOTOGRAPH CONTAINS SCALE. A picture of a bracket and a picture of a
   bridge are the same pixels. Every reconstruction comes out in arbitrary
   units and is reported that way; a real dimension has to come from the
   person, or from a known object in the frame. `scale_to_mm` exists for
   exactly that and refuses to guess.

2. A RECONSTRUCTION IS A GUESS ABOUT THE UNSEEN HALF. One photograph shows one
   side. The back is invented, plausibly, by a network trained on other
   objects - which is fine for a figurine and is not a measurement. Anything
   built from it carries that.

3. IT IS NOT PRINTABLE UNTIL IT HAS BEEN CHECKED. Neural meshes are commonly
   non-manifold, self-intersecting, or hollow in ways a slicer will not
   forgive - meshy publishes 55% fully watertight. bpcad's own verify pass is
   the gate, and it is not skipped for these.

LOCAL BY DEFAULT, AS EVERYWHERE ELSE
------------------------------------
The default backend is `null`, which refuses and explains. A real
reconstructor is opted into in config, exactly as a model host is, and bpcad
keeps working with no network and no weights on disk - every part in `parts/`
still rebuilds from its `spec.yaml`. See CLAUDE.md rule 10.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


class ReconstructionError(RuntimeError):
    """
    A photo could not be turned into a mesh. The message says why.

    Distinct from a bug: an unusable photograph is the ordinary case - the
    object touching the frame edge, no separation from the background, three
    objects in shot - and the caller shows the reason rather than a traceback.
    """


class ReconstructorUnavailable(ReconstructionError):
    """
    No reconstructor is configured, or its weights are not on this machine.

    Its own class because the fix is different in kind: not a better photo, but
    a decision to install a model. The message names what to do.
    """


@dataclass
class Reconstruction:
    """
    What came out of a photograph, and how much to trust it.

    `units` is the point of this dataclass. A reconstruction is dimensionless
    until somebody supplies a real measurement, and every field below is
    honest about that: `scale_mm_per_unit` is None until it is known, and
    `printable` stays False until bpcad's own verify pass has run - not until
    the mesh merely exists.
    """

    mesh_path: Path
    source_image: Path
    backend: str
    model: str = ""
    seconds: float = 0.0

    triangles: int = 0
    watertight: bool | None = None
    bodies: int = 0

    # ARBITRARY UNITS UNTIL PROVEN OTHERWISE. The bounding box is in whatever
    # the network produced; scale_mm_per_unit is the one number that turns it
    # into millimetres, and nothing here invents it.
    extent: tuple[float, float, float] = (0.0, 0.0, 0.0)
    scale_mm_per_unit: float | None = None
    scale_source: str = ""

    # Set only by the geometry side of the house, never by a reconstructor.
    printable: bool = False
    problems: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def has_scale(self) -> bool:
        return self.scale_mm_per_unit is not None

    def extent_mm(self) -> tuple[float, float, float] | None:
        """The size in millimetres, or None while the scale is unknown."""
        if self.scale_mm_per_unit is None:
            return None
        k = self.scale_mm_per_unit
        return (self.extent[0] * k, self.extent[1] * k, self.extent[2] * k)

    def to_json(self) -> dict[str, Any]:
        data = {
            "mesh_path": str(self.mesh_path),
            "source_image": str(self.source_image),
            "backend": self.backend,
            "model": self.model,
            "seconds": round(self.seconds, 1),
            "triangles": self.triangles,
            "watertight": self.watertight,
            "bodies": self.bodies,
            "extent": list(self.extent),
            "scale_mm_per_unit": self.scale_mm_per_unit,
            "scale_source": self.scale_source,
            "printable": self.printable,
            "problems": list(self.problems),
            "notes": list(self.notes),
        }
        extent_mm = self.extent_mm()
        data["extent_mm"] = list(extent_mm) if extent_mm else None
        return data


@runtime_checkable
class Reconstructor(Protocol):
    """One photograph in, one mesh out. Nothing about specs or printing."""

    name: str

    def reconstruct(self, image: Path | str, out_dir: Path | str) -> Reconstruction:
        ...


def scale_to_mm(
    reconstruction: Reconstruction,
    known_mm: float,
    axis: str = "longest",
) -> Reconstruction:
    """
    Give a dimensionless reconstruction its scale, from ONE real measurement.

    THIS IS THE STEP THAT CANNOT BE AUTOMATED. A photograph carries no absolute
    size; a network trained on furniture will happily hand back a chair-shaped
    thing whether it was photographed at 40 mm or 400. So one dimension comes
    from the person holding the object - calipers on the widest point, or the
    diameter of the rod it has to fit - and everything else follows from it
    proportionally.

    `axis` says which dimension was measured: "longest", "x", "y", "z". The
    default is the longest because that is the one a person reaches for with
    calipers without being asked which way round the model is.
    """
    if known_mm <= 0:
        raise ReconstructionError(
            "a known dimension has to be a positive number of millimetres, "
            "got %r" % known_mm
        )

    extents = reconstruction.extent
    if not any(extents):
        raise ReconstructionError(
            "this reconstruction has no measured extent, so a scale cannot be "
            "applied to it"
        )

    index = {"x": 0, "y": 1, "z": 2}.get(axis.lower())
    if index is None:
        if axis.lower() != "longest":
            raise ReconstructionError(
                "axis must be longest, x, y or z, got %r" % axis
            )
        index = max(range(3), key=lambda i: extents[i])

    if extents[index] <= 0:
        raise ReconstructionError(
            "the %s extent of this reconstruction is zero, so %g mm cannot be "
            "matched to it" % (axis, known_mm)
        )

    reconstruction.scale_mm_per_unit = known_mm / extents[index]
    reconstruction.scale_source = "%g mm measured on the %s axis" % (known_mm, axis)
    return reconstruction
