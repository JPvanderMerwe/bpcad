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

## Where inference runs

Two pipelines, two answers, and the difference matters.

**Description to parametric part** is local. Ollama on local hardware or it
does not happen, enforced in `bpcad/models/base.py`: every backend asserts its
host is loopback at construction and raises `NonLocalEndpointError` otherwise.
A non-loopback host has to be named in `allowed_model_hosts` in config - never
reached by silent fallback.

**Photo to mesh** is a neural reconstruction and is opt-in, off by default.
`[reconstruct] backend = "null"` ships as the default, so bpcad installs and
runs with no torch, no model weights and no network. Turning it on is a
config change plus `pip install -e ".[reconstruct]"`.

Production is a self-hosted server on the owner's own machine with a GPU, not
a cloud API. `device = "auto"` takes CUDA when it is there and says which it
used, because the difference is seconds against minutes and a slow run should
never be a mystery.

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

## The library

Everything you make is indexed and searchable - by name, template, material,
the prompt that made it, or the words its template says it makes, so
"container" finds anything built from the enclosure.

Parts are shared as SPECS, not meshes. A downloaded STL is frozen: you cannot
make it 20 mm wider or change it for a different printer. A spec is about a
kilobyte of readable text that rebuilds the part exactly, at whatever size, in
whatever material, for whatever nozzle. Part > Share this part writes one;
Part > Import a spec takes one in and validates it on the way.

Entirely offline. It reads directories; there is a test asserting it never
opens a socket.

## Three ways in

A desktop app:

    bpcad-gui

a command line:

    bpcad build parts/vent/spec.yaml

and a phone, over the same HTTP API the web app uses:

    cd mobile && flutter run

All three sit on `bpcad.api`, which is also the way to drive it from a script:

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

Measured, not estimated. Both numbers come from `tools/fitrate.py`.

    reachable fit rate    19 / 19 = 100%    the corpus's own specs, no model
    first-try fit rate    10 / 19 =  53%    prompt through the whole pipeline
    test suite            765 passed, 1 skipped

The two numbers answer different questions. Reachable tests the geometry
vocabulary; first-try puts the model on top of it. A low first-try with a high
reachable is a prompting problem, and that is where this sits.

`--first-try` takes about two hours on a CPU and is checkpointed, so an
interrupted run resumes instead of starting again.

### What works

Phases 0 to 5, as before: `verify`, `render`, `measure`, `build`, `spec`,
`ask`, `models`, `gen`. Both reference parts still reproduce their reference
STL bit for bit from a hand-written `spec.yaml`.

Since then:

- **A deterministic router.** The ladder used to start at level 1 and escalate
  only when level 1 *failed* - and a wrong template does not fail, it returns
  a confident wrong part. A request now takes the template road only if it
  names something a template claims.
- **Shape checks that compare the part to the request.** Round things must be
  round, hole counts must match, containers must be hollow. Each was measured
  against the whole corpus for false positives before being switched on.
- **Print-in-place mechanisms.** Level 2 assumed one body, which rejected
  every mechanism as fragmentation. `parts/captive_washer` and
  `parts/hinge_pip` are hand-written proof: two bodies, watertight, and they
  move.
- **STL import with spec recovery**, and size variants of anything that has
  ops rather than named parameters.
- **A photo-to-mesh seam** (`bpcad/reconstruct/`) with the scale problem
  treated as first class: no photograph carries absolute size, so a
  reconstruction stays dimensionless until one real measurement is supplied.

### Two clients, one API

- **Web app** at `bpcad web`, installable, phone-first.
- **Native app** in `mobile/`, Flutter, Android and iOS from one codebase.

Neither contains geometry logic - CadQuery is Python and runs server-side
only. `tests/test_cli.py` and `tests/test_gui.py` both fail if a front end
reaches past `bpcad.api` into the pipeline.

### One 3D viewer, served by bpcad

Both clients turn a part in the same page: `/static/viewer.html`, which the
browser loads in an iframe and the phone loads in a WebView. The mesh is a
GLB from `/api/part/<name>/glb` and is drawn by the device's own GPU.

It is one page rather than one per client because two renderers is how two
clients end up showing a part slightly differently, and a viewport that
disagrees with itself is not much use on a measuring instrument. The renderer
is Google's `model-viewer`, vendored under `static/vendor/` with its Apache-2.0
licence - for the same reason the fonts are vendored: a viewer that needs a
CDN is a viewer that fails in a workshop with no signal.

Three things that had to be got right and were not obvious:

- **The GLB carries a material.** glTF's rule for a primitive with no material
  is not "pick something sensible" - it is white, `metallicFactor` 1.0, a
  mirror. The part rendered as a blown-out silhouette until the grey the
  turntable already uses was baked in as matte plastic.
- **Its URL carries `MESH_VERSION`.** The file is served `immutable` for a
  week, which was a lie the moment its contents could change for an unchanged
  part. Bump the constant and the URL changes with it.
- **Embedded, the page's ground is transparent** so the app's build plate
  shows through, and the contact shadow is turned off - with no floor to fall
  on, the shadow catcher itself becomes a dark rectangle beside the part.

Append `&debug=1` for the camera's own numbers on screen; the phone app does
this automatically in a debug build. There is no console on a phone, and this
viewer was twice diagnosed by guessing at screenshots.

### Design tokens

The palette, type scale, spacing and radii live in `design/tokens.json` and
are exported to CSS custom properties and Dart constants:

    python tools/tokens.py

Neither client hardcodes a colour, and `tests/test_tokens.py` fails if either
export is stale - so a token changed in one place cannot reach one client and
not the other.

### Brand assets

`bpcad_media/build_brand.py` generates 46 assets from one SVG: the icon at
every size both stores want, adaptive and monochrome Android layers, splash
images, the wordmark and the social card.

    python bpcad_media/build_brand.py

The generated tree is not tracked - a derived file in version control is a
file that will disagree with its source. What the clients ship is tracked,
because that is an input to a build rather than an output of one.

## Working rules

See `CLAUDE.md`.
