"""
TripoSR: one photograph to one mesh.

WHY THIS MODEL AND NOT ANOTHER
------------------------------
The licence decides it before the quality does, because this is going into a
product that charges money:

  TripoSR          code MIT, weights MIT. Commercial use unencumbered.
  Stable Fast 3D   better meshes, Stability Community Licence - restricted
                   above a revenue threshold. A licence that changes when the
                   business succeeds is not a licence to build on.
  InstantMesh      needs a multi-view diffusion pass first, which on a CPU is
                   tens of minutes rather than minutes.

TripoSR is also small enough to be honest about: roughly half a billion
parameters, one forward pass, no diffusion loop. On a 3060 Ti that is a second
or two. On a CPU it is minutes - slow, but the same order as this project's
existing prompt time, so a laptop can still develop against it.

WHAT IT PRODUCES, PRECISELY
---------------------------
A dimensionless triangle mesh of one object, with the unseen half invented
plausibly. It is not a measurement and it is not printable until bpcad's own
verify pass says so. Both facts travel with it in the Reconstruction, and the
fitters in bpcad/imports.py are what turn it into something editable - if they
can, with a residual either way.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from bpcad.reconstruct.base import (
    Reconstruction,
    ReconstructionError,
    ReconstructorUnavailable,
)

# The weights, by name, on Hugging Face. Pinned to the repo rather than a
# revision because Stability publish one release of this and a floating tag
# would be the same file - but if that ever changes, pin the revision here and
# record why.
MODEL_REPO = "stabilityai/TripoSR"
MODEL_FILE = "model.ckpt"
CONFIG_FILE = "config.yaml"

# Marching-cubes resolution. 256 is the model's own default and gives a mesh in
# the low hundreds of thousands of triangles; 128 halves the memory and loses
# small features, which on a part with a 5 mm hole in it is the wrong trade.
DEFAULT_MARCHING_RESOLUTION = 256


class TripoSRReconstructor:
    """
    A photograph in, a mesh out, on whatever hardware is here.

    Nothing is imported at construction: torch is a two-gigabyte dependency
    and importing it costs seconds, so a program that merely HAS this backend
    configured does not pay for it until a photograph arrives.
    """

    name = "triposr"

    def __init__(self, cfg: Any = None, device: str | None = None):
        self._cfg = cfg
        self._device_setting = (device or self._configured("device") or "auto").lower()
        self._model = None
        self._resolved_device: str | None = None

    # -- configuration -----------------------------------------------------

    def _configured(self, key: str, default: Any = None) -> Any:
        if self._cfg is None:
            return default
        try:
            return (self._cfg.data.get("reconstruct") or {}).get(key, default)
        except Exception:
            return default

    def device(self) -> str:
        """
        Where the forward pass runs.

        "auto" means CUDA when there is a CUDA device and CPU otherwise. The
        difference is not a detail: seconds against minutes, which is the
        difference between a photograph being a step in a workflow and being a
        thing you go and make tea during. The choice is reported in the
        Reconstruction so a slow run is never a mystery.
        """
        if self._resolved_device is not None:
            return self._resolved_device

        setting = self._device_setting
        if setting in ("cpu", "cuda"):
            self._resolved_device = setting
            return setting

        try:
            import torch

            self._resolved_device = "cuda" if torch.cuda.is_available() else "cpu"
        except ImportError:
            self._resolved_device = "cpu"
        return self._resolved_device

    # -- the model ---------------------------------------------------------

    def _load(self):
        """
        Load TripoSR once, and say plainly when it cannot be loaded.

        The two failures worth telling apart are "torch is not installed" and
        "the weights are not on this machine", because the first is a pip
        command and the second is a download that may take a while on a bad
        connection.
        """
        if self._model is not None:
            return self._model

        try:
            import torch  # noqa: F401
        except ImportError as exc:
            raise ReconstructorUnavailable(
                "torch is not installed, so TripoSR cannot run. "
                'Install the extra: pip install -e ".[reconstruct]"'
            ) from exc

        try:
            from tsr.system import TSR
        except ImportError as exc:
            raise ReconstructorUnavailable(
                "the TripoSR package (tsr) is not installed. It is not on "
                "PyPI as a wheel that carries the model code, so it is "
                'installed from source by the ".[reconstruct]" extra.'
            ) from exc

        try:
            model = TSR.from_pretrained(
                MODEL_REPO,
                config_name=CONFIG_FILE,
                weight_name=MODEL_FILE,
            )
        except Exception as exc:                      # network, disk, or hub
            raise ReconstructorUnavailable(
                "TripoSR's weights (%s, about 1.7 GB) could not be loaded: "
                "%s.\nThey are downloaded once into the Hugging Face cache; "
                "after that this works with no network."
                % (MODEL_REPO, str(exc).split("\n")[0][:200])
            ) from exc

        model.renderer.set_chunk_size(
            0 if self.device() == "cuda" else 8192
        )
        model.to(self.device())
        self._model = model
        return model

    # -- the work ----------------------------------------------------------

    def reconstruct(self, image: Path | str, out_dir: Path | str) -> Reconstruction:
        image = Path(image)
        out_dir = Path(out_dir)
        if not image.is_file():
            raise ReconstructionError("no image at %s" % image)
        out_dir.mkdir(parents=True, exist_ok=True)

        started = time.monotonic()
        model = self._load()
        prepared = self._prepare(image)

        import torch

        with torch.no_grad():
            codes = model([prepared], device=self.device())
            meshes = model.extract_mesh(
                codes,
                has_vertex_color=False,
                resolution=int(self._configured(
                    "marching_resolution", DEFAULT_MARCHING_RESOLUTION)),
            )
        if not meshes:
            raise ReconstructionError(
                "the reconstruction produced no surface. That usually means "
                "nothing separated from the background - try a plainer "
                "background, and get the whole object inside the frame."
            )

        mesh = meshes[0]
        target = out_dir / ("%s.glb" % image.stem)
        mesh.export(str(target))

        return self._measure(mesh, target, image, time.monotonic() - started)

    def _prepare(self, image: Path):
        """
        Background out, object centred, square.

        The model expects one object on nothing. Removing the background is
        not cosmetic: a photograph with a worktop in it reconstructs the
        worktop as part of the object, which is a whole extra body in the
        mesh and no fitter will make sense of it.
        """
        from PIL import Image

        picture = Image.open(image).convert("RGB")

        try:
            import rembg

            from tsr.utils import remove_background, resize_foreground

            session = rembg.new_session()
            picture = remove_background(picture, session)
            picture = resize_foreground(picture, 0.85)
        except ImportError:
            # Usable without rembg, and said so rather than silently worse: a
            # photograph already shot against a plain white sweep works fine.
            pass

        return picture

    def _measure(self, mesh, target: Path, image: Path, seconds: float) -> Reconstruction:
        """
        Everything measurable about the result, and nothing invented.

        The extent is in the model's own arbitrary units. It is recorded, not
        converted: scale_to_mm() is the only thing that turns it into
        millimetres, and it needs a real dimension from a person.
        """
        result = Reconstruction(
            mesh_path=target,
            source_image=image,
            backend=self.name,
            model="%s/%s" % (MODEL_REPO, MODEL_FILE),
            seconds=seconds,
        )
        result.notes.append(
            "reconstructed on the %s" % ("GPU" if self.device() == "cuda" else "CPU")
        )
        result.notes.append(
            "the half of the object the photograph could not see is inferred, "
            "not measured"
        )

        try:
            import trimesh

            loaded = trimesh.load(target, force="mesh")
            result.triangles = int(len(loaded.faces))
            result.watertight = bool(loaded.is_watertight)
            result.bodies = int(len(loaded.split(only_watertight=False)))
            low, high = loaded.bounds
            result.extent = tuple(float(h - l) for l, h in zip(low, high))
            if not result.watertight:
                result.problems.append(
                    "the mesh is not watertight as reconstructed - it needs "
                    "repair before it will slice"
                )
            if result.bodies > 1:
                result.problems.append(
                    "%d separate bodies came out of one photograph, which "
                    "usually means part of the background was reconstructed "
                    "too" % result.bodies
                )
        except Exception as exc:
            result.notes.append("could not measure the mesh: %s" % str(exc)[:120])

        return result
