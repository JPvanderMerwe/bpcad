# bpcad

A fully local, fully offline text-and-image-to-3D-printable-part pipeline for
Bit Primitive. Input is a natural-language prompt, optionally plus a reference
photo. Output is a verified, printable STL/STEP bundle plus a report.

## The one architectural decision

**The model does not write CAD code.** It emits a validated spec; deterministic
Python turns that spec into geometry. Free-form CadQuery generation from a small
local model fails constantly. Structured extraction into a Pydantic schema is
something an 8B model does reliably, and when the model is wrong the schema
rejects it before any geometry exists.

## Local inference only

There is no cloud model, no API key, no hosted endpoint and no telemetry at any
tier. Inference is Ollama on local hardware or it does not happen. This is
enforced in `bpcad/models/base.py`: every backend asserts its host is loopback
at construction time and raises `NonLocalEndpointError` otherwise.

## Usable with zero model

`spec.yaml` is the durable artifact. The model is a convenience layer that
writes one. Everything downstream of the spec is deterministic Python, so all
of this works with no model loaded at all:

    bpcad build parts/vent/spec.yaml
    bpcad verify out/vent.stl
    bpcad render out/vent.stl --heightmap
    bpcad measure trace logo.png

With a local model running, `bpcad gen "..."` does the whole thing at once -
but it is a convenience layer over the commands above, never a dependency.

## Two ways in

A desktop app:

    bpcad-gui

and a command line:

    bpcad build parts/vent/spec.yaml

Both sit on `bpcad.api`, which is also the way to drive it from a script:

    from bpcad import api

    part = api.build("parts/vent/spec.yaml")
    print(part.volume_cm3, part.report.verdict)

The GUI owns no pipeline logic of its own - a test enforces that. When a GUI
grows its own copy of a workflow the two drift, and eventually they disagree
about what a part is.

## Install

    conda create -n bpcad python=3.12
    conda activate bpcad
    pip install -e ".[dev,gui]"

On a Wayland desktop the app moves itself onto XWayland at start-up, because
Qt runs natively on Wayland and VTK's OpenGL window does not, and the two
disagreeing produces `BadWindow` rather than anything that names the cause.
That needs `libxcb-cursor`, which is in the conda environment:

    conda install -c conda-forge xcb-util-cursor

Without it the app still runs; the interactive 3D view degrades and the
rendered images and height maps, which are produced on the CPU, do not.

## Status

Phase 0: scaffold, config, `bpcad config show`, local-only enforcement.
Phase 1: `bpcad verify` and `bpcad render` - mesh checks, feature linting,
ray-cast surface heights, height map, overhang with drop measurement,
regression baselines, and a CPU z-buffer rasteriser.
Phase 2: `bpcad measure` - colour and luminance segmentation, sub-pixel edges,
contour tracing, circle and arc fitting with residuals.
Phase 3: `bpcad build` and `bpcad spec` - the PartSpec schema, the template
registry, the level-2 DSL, and both reference templates. Both reproduce their
reference STL bit-identically from a hand-written spec.yaml.
Phase 4: `bpcad ask` and `bpcad models` - the Ollama and null backends, loopback
enforcement, machine profiles, the degradation ladder, and the annotated
spec.draft.yaml handoff for when the model cannot do the job.
Phase 5: `bpcad gen` - the full loop. Generate, validate, build, verify,
escalate level, render, and write the bundle. Every run leaves run.json with
the complete attempt history.

No model is involved in any of it.

Commands are registered phase by phase, so `bpcad --help` never advertises
something that does not work yet.

## Working rules

See `CLAUDE.md`.
