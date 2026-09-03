"""
What this machine can actually do, and how long it will take.

WHY THIS IS NOT JUST "HAS GPU: TRUE/FALSE"
-------------------------------------------
Almost nothing in this program needs a GPU. Measured on the work laptop, which
has none:

    a full build, verify and export      15.9 s   CPU, no model involved
    one model call                      154   s   CPU, 7B model

The geometry - CadQuery, the boolean kernel, the mesh checks, the rasteriser -
is CPU work and always will be. A GPU would not speed it up by a second. The
only thing that wants one is the language model, and the only thing that would
REQUIRE one is a generative mesh model, which this does not have yet.

That distinction is the whole cost story, so it is measured and reported rather
than collapsed into one flag. A machine with no GPU is not "unsupported": it is
a machine where every template, every fitter, every import and every export
works exactly as well, and only the prompt step is slow.

WHAT AN HONEST MESSAGE LOOKS LIKE
----------------------------------
Not "GPU required". Not a spinner that runs for three minutes. A number, before
the person commits to waiting: "this machine has no GPU, so a prompt takes
around two and a half minutes - everything else is instant." Then they can
decide.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass, field

# Measured on this project's own hardware, and used only to set expectations -
# never to gate anything. A slow answer is still an answer.
CPU_PROMPT_SECONDS = 155
GPU_PROMPT_SECONDS = 15          # an order of magnitude, not a promise
GEOMETRY_SECONDS = 16


@dataclass
class Capability:
    """What this machine has, and what that means for waiting."""

    gpu: bool = False
    gpu_name: str = ""
    vram_gb: float = 0.0
    model_on_gpu: bool = False
    model_name: str = ""
    model_available: bool = False

    notes: list[str] = field(default_factory=list)

    @property
    def prompt_seconds(self) -> int:
        """Roughly how long a prompt takes here."""
        return GPU_PROMPT_SECONDS if self.model_on_gpu else CPU_PROMPT_SECONDS

    @property
    def tier(self) -> str:
        if not self.model_available:
            return "no-model"
        return "gpu" if self.model_on_gpu else "cpu"

    def headline(self) -> str:
        """
        One sentence, for the status line. No jargon, no false alarm.

        A machine with no GPU is not broken and must not be told it is. What it
        needs to know is the wait, and that everything except the wait is fine.
        """
        if not self.model_available:
            return (
                "No model running, so prompting is unavailable. Everything else "
                "works: open a spec, change any number, rebuild, export."
            )
        if self.model_on_gpu:
            return "%s on the GPU%s - a prompt takes around %d seconds." % (
                self.model_name,
                " (%s)" % self.gpu_name if self.gpu_name else "",
                self.prompt_seconds,
            )
        return (
            "%s on the CPU - no GPU on this machine, so a prompt takes around "
            "%d minutes. Building, checking and exporting are unaffected and "
            "take about %d seconds." % (
                self.model_name, round(self.prompt_seconds / 60), GEOMETRY_SECONDS
            )
        )

    def why_slow(self) -> str:
        """The honest explanation, for when somebody asks."""
        if self.model_on_gpu or not self.model_available:
            return ""
        return (
            "Only the prompt step wants a GPU. The geometry - the CAD kernel, "
            "the checks, the renders - is CPU work and a GPU would not make it "
            "any faster. On this machine that is %d seconds of geometry behind "
            "%d seconds of thinking." % (GEOMETRY_SECONDS, self.prompt_seconds)
        )

    def to_json(self) -> dict:
        return {
            "tier": self.tier,
            "gpu": self.gpu,
            "gpu_name": self.gpu_name,
            "vram_gb": self.vram_gb,
            "model_on_gpu": self.model_on_gpu,
            "model_name": self.model_name,
            "model_available": self.model_available,
            "prompt_seconds": self.prompt_seconds,
            "geometry_seconds": GEOMETRY_SECONDS,
            "headline": self.headline(),
            "why_slow": self.why_slow(),
            "notes": list(self.notes),
        }


def detect_gpu() -> tuple[bool, str, float]:
    """
    Is there an NVIDIA GPU, what is it, and how much memory has it got?

    Device nodes first, then nvidia-smi for the details. Never raises: the
    common case here is a machine with no NVIDIA driver at all, where
    `nvidia-smi` is simply absent, and that must be an answer rather than a
    traceback.
    """
    present = any(
        os.path.exists(path)
        for path in ("/dev/nvidiactl", "/dev/nvidia0", "/proc/driver/nvidia/version")
    )
    name, vram = "", 0.0

    smi = shutil.which("nvidia-smi")
    if smi:
        try:
            out = subprocess.run(
                [smi, "--query-gpu=name,memory.total",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=6,
            )
            line = (out.stdout or "").strip().splitlines()
            if line:
                parts = line[0].split(",")
                name = parts[0].strip()
                if len(parts) > 1:
                    vram = round(float(parts[1].strip()) / 1024.0, 1)
                present = True
        except Exception:
            pass
    return present, name, vram


def detect(cfg=None) -> Capability:
    """What this machine can do right now."""
    cap = Capability()
    cap.gpu, cap.gpu_name, cap.vram_gb = detect_gpu()

    try:
        from bpcad import api

        status = api.model_status(cfg=cfg) if cfg is not None else api.model_status()
    except Exception as exc:
        cap.notes.append("could not reach the model layer: %s" % str(exc)[:120])
        return cap

    cap.model_available = bool(status.get("available"))
    cap.model_name = status.get("model_primary") or ""

    # Ollama reports where each loaded model actually sits. "100% CPU" is the
    # answer that matters and it is not the same question as "is there a GPU" -
    # a machine can have one and still be running the model on the processor
    # because the model did not fit in its memory.
    for loaded in status.get("loaded", []) or []:
        processor = str(loaded.get("processor", "")).lower()
        if "gpu" in processor and "100% cpu" not in processor:
            cap.model_on_gpu = True
            cap.notes.append("%s is on the %s" % (loaded.get("name"), processor))
            break
    else:
        if cap.model_available and cap.gpu:
            cap.notes.append(
                "there is a GPU here but the model is on the CPU - it may be "
                "too large for the card's memory"
            )
    return cap


def require_gpu(what: str, cap: Capability | None = None) -> None:
    """
    Refuse a genuinely GPU-only feature, in words somebody can act on.

    Reserved for things that truly cannot run without one - a generative mesh
    model, when there is one. Nothing in the program today calls this, and
    nothing that merely runs SLOWLY on a CPU ever should: a two-minute answer
    is an answer, and refusing it would take away a working program from
    everyone without a graphics card.
    """
    cap = cap or detect()
    if cap.gpu:
        return
    raise RuntimeError(
        "%s needs a GPU and this machine has none. Everything else in bpcad "
        "works without one - templates, the fitters, importing, editing, "
        "checking and export are all CPU work. Run this step on a machine with "
        "an NVIDIA card, or point bpcad at one." % what
    )
