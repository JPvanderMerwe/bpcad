"""
Bringing an STL in from outside, and what can honestly be said about it.

WHY AN IMPORTED MESH IS NOT THE SAME KIND OF THING AS A BUILT PART
------------------------------------------------------------------
A part this program built has a spec behind it. Every dimension is a number
somebody can change, the report says how each one was arrived at, and the mesh
can be thrown away and rebuilt. An STL downloaded from somewhere is a triangle
soup: it has a size and a volume and nothing else. There is no wall thickness
to edit, no rim diameter to retype, and no way to ask for it 10 mm taller.

Both belong in the same library - you want to find them in the same place - but
pretending they are the same kind of object is how a tool starts lying. So an
import is stored with `origin: imported`, it carries the measurements that can
actually be taken off a mesh, and the things that need a spec are absent rather
than guessed.

WHAT CAN BE RECOVERED
---------------------
For one large family it is better than that. A surface of revolution - bowls,
pots, vases, cups, shades, knobs - is fully described by a 2D profile, and that
IS recoverable from a mesh. So every import is offered to the revolve fitter,
and when it takes, the import gains a spec and becomes editable like anything
else. When it does not take, that is reported plainly and the file is stored as
what it is.

WHAT IS NEVER DONE
------------------
The file is not repaired, decimated, re-oriented or scaled on the way in. A
mesh that arrives non-watertight is stored non-watertight and SAID to be, since
that is a fact about the file somebody needs before they print it. Quietly
fixing it would mean the thing in the library is no longer the thing that was
downloaded, and the first time that mattered nobody would know it had happened.
"""

from __future__ import annotations

import json
import re
import shutil
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

IMPORT_ROOT = Path("library")
META_NAME = "import.json"

# Formats worth accepting. STEP is here because it is real CAD and keeping it
# is worthwhile even though nothing yet reads it back into a spec.
MESH_SUFFIXES = {".stl", ".3mf", ".obj", ".ply"}
CAD_SUFFIXES = {".step", ".stp"}
ACCEPTED = MESH_SUFFIXES | CAD_SUFFIXES

# Anything larger is refused rather than chewed on. A 200 MB mesh is minutes of
# tessellation and a browser that appears to have hung.
MAX_BYTES = 120 * 1024 * 1024

SAFE_SLUG = re.compile(r"[^a-z0-9._-]+")


class ImportError_(ValueError):
    """The file could not be taken in. The message says why."""


@dataclass
class ImportedPart:
    """An STL brought in from outside, and what was measured off it."""

    name: str
    directory: Path
    source_name: str = ""
    origin: str = "imported"
    bytes: int = 0
    imported_at: float = 0.0

    # Measured off the mesh. Absent where a mesh cannot answer.
    envelope_mm: tuple[float, float, float] | None = None
    volume_cm3: float | None = None
    triangles: int = 0
    bodies: int = 0
    watertight: bool | None = None

    # Organisation.
    tags: list[str] = field(default_factory=list)
    note: str = ""

    # What was recovered, if anything.
    editable: bool = False
    fit_note: str = ""

    problems: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        data = asdict(self)
        data["directory"] = str(self.directory)
        data["envelope_mm"] = list(self.envelope_mm) if self.envelope_mm else None
        return data


def slug(text: str) -> str:
    """A filesystem-safe name that still looks like what was uploaded."""
    stem = Path(text).stem.strip().lower().replace(" ", "_")
    cleaned = SAFE_SLUG.sub("", stem).strip("._-")
    return cleaned[:60] or "upload"


def unique_dir(root: Path, name: str) -> Path:
    """A directory for this import, never clobbering an existing one."""
    root.mkdir(parents=True, exist_ok=True)
    candidate = root / name
    if not candidate.exists():
        return candidate
    for n in range(2, 500):
        candidate = root / ("%s_%d" % (name, n))
        if not candidate.exists():
            return candidate
    raise ImportError_("too many imports called %r" % name)


def measure_mesh(path: Path) -> tuple[dict[str, Any], Any]:
    """
    What a mesh can be asked, and nothing else.

    No repair, no decimation, no re-orientation. If it is not watertight that
    is recorded, because it is a fact about the file that matters before
    printing - not a defect to be silently corrected on the way in.
    """
    import trimesh

    loaded = trimesh.load(path, force="mesh")
    if isinstance(loaded, trimesh.Scene):        # multi-object OBJ and friends
        loaded = trimesh.util.concatenate(list(loaded.geometry.values()))

    bounds = loaded.bounds
    envelope = tuple(round(float(v), 2) for v in (bounds[1] - bounds[0]))
    pieces = loaded.split(only_watertight=False)

    out: dict[str, Any] = {
        "envelope_mm": envelope,
        "triangles": int(len(loaded.faces)),
        "bodies": int(len(pieces)) or 1,
        "watertight": bool(loaded.is_watertight),
        "volume_cm3": None,
    }
    # A volume is only meaningful on a closed mesh. On an open one trimesh will
    # still return a number and that number means nothing.
    if loaded.is_watertight:
        out["volume_cm3"] = round(float(loaded.volume) / 1000.0, 3)
    return out, loaded


def take_in(
    source: Path | str,
    data: bytes | None = None,
    root: Path | str = IMPORT_ROOT,
    tags: list[str] | None = None,
    note: str = "",
    render: bool = True,
) -> ImportedPart:
    """
    Bring a file into the library, measure it, and try to recover a spec.

    `data` lets an upload be handed over without touching a temporary file
    first; `source` is then only used for its name.
    """
    source = Path(source)
    suffix = source.suffix.lower()
    if suffix not in ACCEPTED:
        raise ImportError_(
            "%s is not a format this takes. Accepted: %s."
            % (suffix or "that file", ", ".join(sorted(ACCEPTED)))
        )

    payload = data if data is not None else source.read_bytes()
    if not payload:
        raise ImportError_("that file is empty")
    if len(payload) > MAX_BYTES:
        raise ImportError_(
            "%.0f MB is over the %.0f MB limit - a mesh that size takes minutes "
            "to tessellate and looks like a hang"
            % (len(payload) / 1e6, MAX_BYTES / 1e6)
        )

    name = slug(source.name)
    directory = unique_dir(Path(root), name)
    (directory / "out").mkdir(parents=True, exist_ok=True)
    stored = directory / "out" / ("%s%s" % (name, suffix))
    stored.write_bytes(payload)

    part = ImportedPart(
        name=directory.name,
        directory=directory,
        source_name=source.name,
        bytes=len(payload),
        imported_at=time.time(),
        tags=sorted({t.strip().lower() for t in (tags or []) if t.strip()}),
        note=note.strip(),
    )

    if suffix in MESH_SUFFIXES:
        try:
            measured, mesh = measure_mesh(stored)
            part.envelope_mm = measured["envelope_mm"]
            part.volume_cm3 = measured["volume_cm3"]
            part.triangles = measured["triangles"]
            part.bodies = measured["bodies"]
            part.watertight = measured["watertight"]
            if not part.watertight:
                part.problems.append(
                    "the mesh is not closed, so it has no meaningful volume and "
                    "a slicer may refuse it or fill it strangely. Stored as it "
                    "arrived - repairing it here would mean this is no longer "
                    "the file you downloaded."
                )
            if render:
                _render(mesh, directory / "out")
            _try_recover_spec(part, mesh, directory)
        except ImportError_:
            raise
        except Exception as exc:
            part.problems.append("could not read the mesh: %s" % str(exc)[:200])
    else:
        part.fit_note = "STEP is stored as-is; nothing here reads it back yet."

    write_meta(part)
    return part


def _render(mesh, out_dir: Path) -> None:
    """A thumbnail, with the same rasteriser everything else uses."""
    import numpy as np
    from PIL import Image

    from bpcad.gui import theme
    from bpcad.render.raster import render

    for stem, azim, size in (("thumb", 45.0, 340), ("preview", 45.0, 900)):
        img = render(
            np.asarray(mesh.vertices, dtype=float),
            np.asarray(mesh.faces),
            np.asarray(mesh.face_normals, dtype=float),
            width=size, height=int(size * 0.78), elev_deg=26.0, azim_deg=azim,
            background=theme.VIEWPORT_BG,
        )
        arr = img if img.dtype == np.uint8 else (np.clip(img, 0, 1) * 255).astype(np.uint8)
        Image.fromarray(arr[:, :, :3]).save(out_dir / ("%s.png" % stem))


def _try_recover_spec(part: ImportedPart, mesh, directory: Path) -> None:
    """
    Offer the mesh to BOTH fitters. If either takes, the import gains a spec.

    This is the whole reason importing is worth more here than on a model
    sharing site: a downloaded bowl comes back as something you can make 30 mm
    taller, and a downloaded bracket comes back as something you can make
    thicker. Turned shapes go to `measure/revolve`, extruded ones to
    `measure/prism`, and between them they cover most of what people print.

    When neither takes, BOTH reasons are recorded. "Not a turned shape" alone
    is only half an answer when the thing was never going to be turned.
    """
    from bpcad.measure.revolve import fit_revolve, to_vessel_params

    notes = []
    try:
        fit = fit_revolve(mesh)
        if not fit.ok:
            notes.append(fit.summary()[0])
    except Exception as exc:
        fit = None
        notes.append("could not test for a turned profile: %s" % str(exc)[:100])

    if fit is None or not fit.ok:
        if _try_prism(part, mesh, directory, notes):
            return
        part.fit_note = " | ".join(notes)
        return

    # From here the shape IS turned. Whatever happens next, it must not be
    # handed to the extrusion fitter: a turned shape is not a prism, and a bowl
    # described as an extrusion along Y is nonsense that builds.

    try:
        params = to_vessel_params(fit)
        spec = {
            "name": part.name,
            "level": 1,
            "material": "petg",
            "nozzle_mm": 0.4,
            "layer_mm": 0.24,
            "template": "vessel",
            "params": params,
        }
        from bpcad import api

        validated = api.validate_spec(spec)
        api.write_spec(validated, directory / "spec.yaml")
        part.editable = True
        part.fit_note = (
            "turned profile recovered - wall %s mm, roundness %.4f. This is "
            "editable: change any number and rebuild."
            % (fit.wall_mm if fit.wall_mm is not None else "not measurable",
               fit.roundness)
        )
    except Exception as exc:
        # A profile that fits the mesh but not the template's own rules is a
        # real answer - usually "this would need supports" - and is reported.
        # The prism fitter still gets its turn: a shape can read as turned and
        # be better described as extruded.
        # NO FALLING THROUGH TO THE PRISM FITTER. The shape is turned; the
        # profile simply will not make a legal part, which is a real answer
        # and a useful one. Trying the extrusion fitter here is how a bowl
        # ended up fitted as an extrusion along Y.
        part.fit_note = (
            "this is a turned shape, but the profile measured off it will not "
            "make a legal part: %s"
            % str(exc).split("problem : Value error, ")[-1].split(".")[0][:160]
        )


def _try_prism(part: ImportedPart, mesh, directory: Path, notes: list) -> bool:
    """The extruded fitter. Returns whether it took."""
    from bpcad.measure.prism import fit_prism, to_dsl_ops

    try:
        fit = fit_prism(mesh)
    except Exception as exc:
        notes.append("could not test for an extrusion: %s" % str(exc)[:100])
        return False

    if not fit.ok:
        notes.append(fit.summary()[0])
        return False

    try:
        from bpcad import api

        spec = api.validate_spec({
            "name": part.name, "level": 2, "material": "petg",
            "nozzle_mm": 0.4, "layer_mm": 0.24, "ops": to_dsl_ops(fit),
        })
        api.write_spec(spec, directory / "spec.yaml")
    except Exception as exc:
        notes.append("an extruded profile was found but will not build: %s"
                     % str(exc)[:140])
        return False

    part.editable = True
    part.fit_note = (
        "extruded profile recovered along %s - %d-point outline, %d cut-outs, "
        "constancy %.4f. This is editable: change any number and rebuild."
        % (fit.axis.upper(), len(fit.profile), len(fit.cutouts), fit.constancy)
    )
    return True


def write_meta(part: ImportedPart) -> Path:
    path = part.directory / META_NAME
    path.write_text(json.dumps(part.to_json(), indent=1))
    return path


def read_meta(directory: Path) -> ImportedPart | None:
    path = Path(directory) / META_NAME
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text())
    except Exception:
        return None
    data["directory"] = Path(data.get("directory", directory))
    envelope = data.get("envelope_mm")
    data["envelope_mm"] = tuple(envelope) if envelope else None
    known = {f for f in ImportedPart.__dataclass_fields__}
    return ImportedPart(**{k: v for k, v in data.items() if k in known})


def set_tags(directory: Path, tags: list[str], note: str | None = None) -> ImportedPart:
    """Re-tag an import. Tags are lowercased and de-duplicated, always."""
    part = read_meta(directory)
    if part is None:
        raise ImportError_("%s is not an imported part" % directory)
    part.tags = sorted({t.strip().lower() for t in tags if t.strip()})
    if note is not None:
        part.note = note.strip()
    write_meta(part)
    return part


def all_tags(root: Path | str = IMPORT_ROOT) -> dict[str, int]:
    """Every tag in use, and how many things carry it."""
    counts: dict[str, int] = {}
    base = Path(root)
    if not base.is_dir():
        return counts
    for directory in base.iterdir():
        part = read_meta(directory) if directory.is_dir() else None
        if part is None:
            continue
        for tag in part.tags:
            counts[tag] = counts.get(tag, 0) + 1
    return dict(sorted(counts.items()))
