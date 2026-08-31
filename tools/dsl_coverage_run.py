"""
Can the LOCAL model actually compose the primitive layer?

The unit tests prove the DSL can express these parts. They prove nothing about
whether a 7B model running on this laptop can find the answer, and that is the
only question that decides whether the app is usable. So this asks the real
model, on the real prompts, and writes down what came back - including the
failures, which are the useful half.

  python tools/dsl_coverage_run.py [out.json] [--only N] [--prompt "..."]

Deliberately NOT a pytest: it needs a running Ollama and takes minutes, and a
test suite that needs a model is a test suite that stops being run.

RUN IT ON ITS OWN. The first run of this took 31 minutes and reported 0 of 8,
and both numbers were lies. The failures were a typo in this file - AskResult
has no `.attempts` - which threw AFTER the model had answered correctly, so
every prompt was scored as a failure on the strength of a crash in the marking.
And half the wall clock was a pytest run competing for the same eight cores.
Inference here is CPU-only; anything else running doubles these times.
"""

from __future__ import annotations

import json
import sys
import time
import traceback
from pathlib import Path

from bpcad import api
from bpcad.agent.loop import ask_level_2
from bpcad.build.helpers import probe
from bpcad.models.selector import load_profile
from bpcad.spec.dsl import run_ops

# Ordinary things somebody would ask a 3D printer for. None of them matches a
# template, so every one of them has to come out of the primitive layer.
PROMPTS = [
    "a wall hook for a coat, screwed to the wall through two holes",
    "a phone stand that holds the phone at about 60 degrees",
    "a desk tray 160 mm long divided into three compartments",
    "a funnel with a 60 mm mouth and a spout that fits a 20 mm neck",
    "a round knob 40 mm across with a 6 mm hole for a shaft",
    "a rectangular plate 80 by 40 by 6 mm with two countersunk screw holes",
    "a cable clip that screws to a desk and holds two 5 mm cables",
    "a plant pot 100 mm across with drainage holes in the bottom",
]


def main() -> int:
    argv = sys.argv[1:]
    prompts = list(PROMPTS)
    if "--only" in argv:
        prompts = prompts[: int(argv[argv.index("--only") + 1])]
    if "--prompt" in argv:
        prompts = [argv[argv.index("--prompt") + 1]]
    positional = [a for a in argv if not a.startswith("--")]
    skip = set()
    for flag in ("--only", "--prompt"):
        if flag in argv:
            skip.add(argv[argv.index(flag) + 1])
    positional = [a for a in positional if a not in skip]
    out_path = Path(positional[0] if positional else "dsl_coverage.json")
    cfg = api.config()
    profile = load_profile(cfg, None)
    nozzle = float(cfg.print_settings["nozzle_mm"])
    layer = float(cfg.print_settings["layer_mm"])

    print("model: %s   machine: %s" % (profile.model_primary, profile.name))
    print("=" * 74)

    rows = []
    for prompt in prompts:
        row = {"prompt": prompt, "ok": False, "why": "", "ops": [], "seconds": 0.0}
        started = time.monotonic()
        try:
            asked = time.monotonic()
            result = ask_level_2(prompt, profile, "petg", nozzle, layer)
            row["model_seconds"] = round(time.monotonic() - asked, 1)

            spec = result.spec
            if spec is None:
                raise RuntimeError("the model produced no usable spec")
            row["ops"] = [dict(o) for o in (spec.ops or [])]
            # AskResult carries a ladder, not an attempts list. Reading a field
            # that does not exist threw here - after the model had already got
            # it right - and scored the answer as a failure.
            ladder = getattr(result, "ladder", None)
            row["attempts"] = len(getattr(ladder, "attempts", []) or []) if ladder else 0

            scene = run_ops(spec.ops, print_axis=spec.print_axis)
            solid = scene.solid.val()
            bodies = len(solid.Solids())
            missed = [n for n in scene.log.notes if "removed nothing" in n]

            problems = []
            if not probe(scene.solid):
                problems.append("fails a real boolean")
            if bodies != 1:
                problems.append("came out as %d separate pieces" % bodies)
            if missed:
                problems.append("has a cut that misses the part")
            if solid.Volume() < 100:
                problems.append("only %.0f mm3 - too small to be the part asked for"
                                % solid.Volume())

            bb = solid.BoundingBox()
            row["size_mm"] = [round(bb.xlen, 1), round(bb.ylen, 1), round(bb.zlen, 1)]
            row["volume_mm3"] = round(solid.Volume(), 1)
            row["bodies"] = bodies
            row["ok"] = not problems
            row["why"] = "; ".join(problems)
        except Exception as exc:
            row["why"] = "%s: %s" % (type(exc).__name__, str(exc).split("\n")[0][:160])
            row["traceback"] = traceback.format_exc()[-800:]

        row["seconds"] = round(time.monotonic() - started, 1)
        rows.append(row)

        mark = "PASS" if row["ok"] else "FAIL"
        size = ("%.0f x %.0f x %.0f mm" % tuple(row["size_mm"])) if row.get("size_mm") else "-"
        print("%-4s %5.0fs (%4ss model)  %-46s %s"
              % (mark, row["seconds"], row.get("model_seconds", "?"), prompt[:46], size))
        if row["why"]:
            print("            %s" % row["why"])
        if row["ops"]:
            print("            ops: %s" % ", ".join(o.get("op", "?") for o in row["ops"]))

    passed = sum(1 for r in rows if r["ok"])
    times = [r["model_seconds"] for r in rows if r.get("model_seconds")]
    print("=" * 74)
    print("%d of %d built as one sound piece" % (passed, len(rows)))
    if times:
        print("model time: median %.0fs, worst %.0fs, over %d prompts"
              % (sorted(times)[len(times) // 2], max(times), len(times)))
    out_path.write_text(json.dumps(
        {"model": profile.model_primary, "machine": profile.name, "rows": rows}, indent=1
    ))
    print("written to %s" % out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
