"""
First-try fit rate. Brief sections 5, 12.6 and 13 Phase 1.

    python tools/fitrate.py --reachable          seconds, no model, gates merges
    python tools/fitrate.py --first-try          the brief's number, minutes
    python tools/fitrate.py --first-try --only 5

WHAT IS BEING MEASURED
----------------------
Brief 5: "of a corpus of realistic part requests with known-correct dimensions,
what fraction produce a part whose measured critical dimensions match the spec,
with no human editing?"

Two numbers come out, and separating them is the difference between knowing
what to fix and guessing:

  REACHABLE   the corpus's own hand-written specs, built and asserted. No
              model. Tests the GEOMETRY VOCABULARY - templates, primitives,
              fitters. Runs in seconds, so it can block a merge.

  FIRST-TRY   the prompt alone, through the whole pipeline. The brief's
              number. Tests the model on top of the vocabulary.

A low first-try with a high reachable is a prompting problem. Both low is a
vocabulary problem. Only measuring first-try tells you neither, and it is the
expensive one to run.

WHAT COUNTS AS A PASS
---------------------
Every assertion. Not most. A part with one wrong hole is a part that does not
fit, and averaging that away is how a fit rate stops meaning anything.

An entry with no assertions beyond "one body" cannot pass or fail meaningfully
and is reported SEPARATELY as unmeasurable rather than being counted either
way. Padding the denominator with requests nobody can check would move the
number without moving the product.

WHY THIS IS NOT A PYTEST
------------------------
--first-try needs a running model and takes tens of minutes; a test suite that
needs that is a test suite that stops being run. --reachable is fast and has a
pytest wrapper in tests/test_fitrate.py, which is what gates merges.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

CORPUS = Path("eval/corpus.yaml")

# An entry with nothing but `bodies` asserted is not a fit test - it is a
# reminder. Counted apart from the rate.
TRIVIAL_KEYS = {"bodies"}


@dataclass
class Outcome:
    """What happened to one corpus entry."""

    id: str
    request: str
    mode: str
    built: bool = False
    fits: bool = False
    measurable: bool = True
    passed_checks: int = 0
    total_checks: int = 0
    seconds: float = 0.0
    lines: list[str] = field(default_factory=list)
    error: str = ""
    template: str | None = None
    level: int | None = None

    # WHAT A RUN COST AND WHY IT FAILED. The first-try pass takes two hours of
    # CPU inference, so throwing the detail away and keeping a single
    # percentage means paying that price again to answer the next question.
    model_used: str = ""
    attempts: int = 0
    failure_class: str = ""
    run_record: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        data = dict(self.__dict__)
        return data


# WHY A TWO-HOUR RUN NEEDS A CHECKPOINT.
#
# The first-try pass is 22 prompts at 2-6 minutes of CPU inference each. Any
# interruption - a laptop lid, a Ctrl-C, a power cut, an edit to the source
# while it runs - threw away every completed entry and started again from the
# first. That is the mechanical reason this number had never been measured
# once in the project's life: it is not that it is slow, it is that it was
# not finishable.
#
# One JSON line per completed entry, appended the moment it finishes. A resumed
# run skips what is already there. The file is also the durable record: it
# carries the prompt, the level reached, the verdict, the failure class, the
# wall time, the model that answered and the whole run.json.
CHECKPOINT = Path("eval/firsttry-runs.jsonl")


def load_checkpoint(path: Path) -> dict[str, "Outcome"]:
    """Completed outcomes by entry id. A malformed line is skipped, not fatal."""
    done: dict[str, Outcome] = {}
    if not path.is_file():
        return done
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
            done[data["id"]] = Outcome(**data)
        except Exception:
            continue
    return done


def append_checkpoint(path: Path, outcome: "Outcome") -> None:
    """
    Append one result. Flushed immediately: a checkpoint that is still in a
    buffer when the process dies is not a checkpoint.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        handle.write(json.dumps(outcome.to_json(), default=str) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def classify(outcome: "Outcome") -> str:
    """
    One label for what happened, from the outcome alone.

    Ranked frequency across these is what decides where the next block of work
    goes. "53%" says the pipeline needs work and says nothing about which
    work; "five of nine failures never produced a valid spec" does.
    """
    # ORDER MATTERS. An entry with nothing to assert - a bare prompt from a
    # user, with no known-correct dimensions - still fails in a way worth
    # naming. Testing `measurable` first labelled every such failure
    # "unmeasurable" and threw away the reason, which is the one thing the
    # prompt file was added to find out.
    if not outcome.built:
        text = (outcome.error or "").lower()
        if "budget" in text:
            return "budget spent"
        if "no model" in text or "not answering" in text:
            return "no model reachable"
        if "valid spec" in text or "draft" in text:
            return "no valid spec produced"
        return "build error"

    if not outcome.measurable:
        return "built, nothing asserted"
    if outcome.fits:
        return "fit"

    # Built, but something measured wrong. Name the first failing assertion: a
    # part that is the wrong SIZE and a part missing a HOLE are different
    # problems with different fixes.
    for line in outcome.lines:
        if "FAIL" not in line and "NOT MEASURABLE" not in line:
            continue
        field_name = line.strip().split()[0]
        for prefix, label in (
            ("extent", "wrong size"),
            ("hole_count", "wrong hole count"),
            ("hole_dia", "hole missing or wrong diameter"),
            ("hole_spacing", "holes in the wrong place"),
            ("bodies", "wrong number of pieces"),
            ("wall", "wrong wall thickness"),
        ):
            if field_name.startswith(prefix):
                return label
        return "assertion failed: %s" % field_name
    return "did not fit, no assertion named"


def slugify(text: str) -> str:
    """An id for a bare prompt, so a checkpoint can key on it."""
    out = "".join(c if c.isalnum() else "_" for c in text.strip().lower())
    return "_".join(p for p in out.split("_") if p)[:48] or "prompt"


def load_corpus(path: Path = CORPUS) -> list[dict]:
    import yaml

    if not path.is_file():
        raise SystemExit("no corpus at %s" % path)
    data = yaml.safe_load(path.read_text()) or {}
    entries = data.get("entries") or []
    if not entries:
        raise SystemExit("%s has no entries" % path)
    return entries


def is_measurable(expect: dict) -> bool:
    return bool(set(expect or {}) - TRIVIAL_KEYS)


def assert_part(result, expect: dict) -> tuple[bool, int, int, list[str]]:
    """Run the corpus assertions against a built part."""
    from bpcad.verify import assertions

    report = assertions.check(
        result.build.solid,
        expect,
        features=dict(result.build.features or {}),
        bodies=result.report.mesh.body_count,
    )
    return report.fits, report.passed, report.total, report.summary()


def run_reachable(entry: dict, out_root: Path) -> Outcome:
    """
    Build the entry's own hand-written spec and assert it. No model.

    This is the vocabulary test. An entry with no spec is one the vocabulary
    cannot express, which is a real result and is reported as such.
    """
    from bpcad import api

    outcome = Outcome(id=entry["id"], request=entry.get("request", ""),
                      mode="reachable",
                      measurable=is_measurable(entry.get("expect")))
    spec_block = entry.get("spec")
    if not spec_block:
        outcome.error = "no spec - the vocabulary cannot express this request"
        return outcome

    started = time.monotonic()
    try:
        payload = {
            "name": entry["id"], "material": "petg",
            "nozzle_mm": 0.4, "layer_mm": 0.24,
            **spec_block,
        }
        payload.setdefault("level", 1)
        spec = api.validate_spec(payload)
        outcome.template = getattr(spec, "template", None)
        outcome.level = getattr(spec, "level", None)
        result = api.build(spec=spec, out_dir=str(out_root / entry["id"]),
                           render=False)
        outcome.built = True
        fits, passed, total, lines = assert_part(result, entry.get("expect") or {})
        outcome.fits, outcome.passed_checks = fits, passed
        outcome.total_checks, outcome.lines = total, lines
    except Exception as exc:
        outcome.error = "%s: %s" % (type(exc).__name__,
                                    str(exc).split("\n")[0][:220])
    outcome.seconds = round(time.monotonic() - started, 1)
    outcome.failure_class = classify(outcome)
    return outcome


def run_first_try(entry: dict, out_root: Path) -> Outcome:
    """
    The brief's number: the prompt alone, through the whole pipeline, once.

    ONCE. "First-try" means first try - no retry, no reroll, no human edit. The
    pipeline's own internal repair attempts are part of one try, because the
    user does not see them and is not charged for them.
    """
    from bpcad import api

    outcome = Outcome(id=entry["id"], request=entry.get("request", ""),
                      mode="first-try",
                      measurable=is_measurable(entry.get("expect")))
    started = time.monotonic()
    try:
        generated = api.generate(entry["request"], material="petg",
                                 out_dir=str(out_root / entry["id"]),
                                 render=False)
        # PROVENANCE FIRST, AND FOR FAILURES TOO. This used to sit inside the
        # success branch, so a run that produced nothing recorded no attempts,
        # no model and no run.json - the exact case where somebody needs the
        # history. A two-hour pass whose five failures were blank is a two-hour
        # pass that has to be run again.
        outcome.attempts = len(generated.attempts)
        outcome.model_used = next(
            (a.model for a in reversed(generated.attempts)
             if getattr(a, "ok", False)),
            next((a.model for a in reversed(generated.attempts)), ""),
        )
        if generated.run_record:
            try:
                outcome.run_record = json.loads(
                    Path(generated.run_record).read_text())
            except Exception:
                pass

        if not generated.ok or generated.part is None:
            outcome.error = (generated.message
                             or "no part passed verification")[:220]
        else:
            outcome.built = True
            outcome.template = getattr(generated.spec, "template", None)
            outcome.level = getattr(generated.spec, "level", None)
            fits, passed, total, lines = assert_part(generated.part,
                                                     entry.get("expect") or {})
            outcome.fits, outcome.passed_checks = fits, passed
            outcome.total_checks, outcome.lines = total, lines
    except Exception as exc:
        outcome.error = "%s: %s" % (type(exc).__name__,
                                    str(exc).split("\n")[0][:220])
        outcome.lines = traceback.format_exc().splitlines()[-3:]
    outcome.seconds = round(time.monotonic() - started, 1)
    outcome.failure_class = classify(outcome)
    return outcome


def report(outcomes: list[Outcome], mode: str) -> dict[str, Any]:
    """One number, and everything needed to argue with it."""
    measurable = [o for o in outcomes if o.measurable]
    trivial = [o for o in outcomes if not o.measurable]
    fitted = [o for o in measurable if o.fits]
    built_not_fitted = [o for o in measurable if o.built and not o.fits]
    failed_to_build = [o for o in measurable if not o.built]

    rate = (len(fitted) / len(measurable)) if measurable else 0.0

    print()
    print("=" * 78)
    print("%s FIT RATE   %d / %d = %.0f%%"
          % (mode.upper(), len(fitted), len(measurable), 100 * rate))
    print("=" * 78)
    print("  built and every dimension right   %d" % len(fitted))
    print("  built but a dimension wrong       %d" % len(built_not_fitted))
    print("  did not build at all              %d" % len(failed_to_build))
    print("  unmeasurable, not counted         %d   (%s)"
          % (len(trivial), ", ".join(o.id for o in trivial) or "none"))
    seconds = [o.seconds for o in outcomes if o.seconds]
    if seconds:
        print("  median %.1fs, total %.0fs"
              % (sorted(seconds)[len(seconds) // 2], sum(seconds)))
    print()
    for group, label in ((built_not_fitted, "WRONG DIMENSIONS"),
                         (failed_to_build, "DID NOT BUILD")):
        if not group:
            continue
        print("%s:" % label)
        for o in group:
            print("  %-26s %s" % (o.id, o.error or
                  "%d/%d assertions" % (o.passed_checks, o.total_checks)))
            for line in o.lines:
                if "FAIL" in line or "NOT MEASURABLE" in line:
                    print("      %s" % line.strip())
        print()

    # RANKED FAILURE CLASSES. This is the part that decides what to build
    # next, so it is printed even when everything passed - "no failures" is
    # itself the answer to the question.
    classes: dict[str, list[str]] = {}
    for o in outcomes:
        if o.fits or not o.measurable:
            continue
        classes.setdefault(o.failure_class or classify(o), []).append(o.id)
    print("FAILURE CLASSES, most common first:")
    if not classes:
        print("  none - every measurable entry fitted")
    for label, ids in sorted(classes.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        print("  %-32s %d   %s" % (label, len(ids), ", ".join(ids)))
    print()

    return {
        "mode": mode,
        "fit_rate": round(rate, 4),
        "failure_classes": {k: v for k, v in sorted(
            classes.items(), key=lambda kv: (-len(kv[1]), kv[0]))},
        "fitted": len(fitted),
        "measurable": len(measurable),
        "built_not_fitted": len(built_not_fitted),
        "failed_to_build": len(failed_to_build),
        "unmeasurable": [o.id for o in trivial],
        "rows": [o.to_json() for o in outcomes],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("--reachable", action="store_true",
                        help="build the corpus's own specs; no model; seconds")
    parser.add_argument("--first-try", action="store_true",
                        help="the brief's number: prompt only, whole pipeline")
    parser.add_argument("--only", type=int, default=0,
                        help="stop after this many entries")
    parser.add_argument("--id", default="", help="run one entry by id")
    parser.add_argument("--out", default="eval/fitrate.json")
    parser.add_argument("--checkpoint", default=str(CHECKPOINT),
                        help="JSONL of completed entries; a run resumes from it")
    parser.add_argument("--fresh", action="store_true",
                        help="ignore the checkpoint and re-run everything")
    parser.add_argument("--prompts", default="",
                        help="a file of one prompt per line, instead of the corpus")
    args = parser.parse_args(argv)

    if not args.reachable and not args.first_try:
        args.reachable = True          # the cheap one is the sane default

    if args.prompts:
        # A PROMPT FILE IS NOT A CORPUS. There are no known-correct dimensions
        # for a phrase somebody typed, so these entries assert nothing and are
        # reported as unmeasurable. What they measure is whether the pipeline
        # produces a part AT ALL, and by which route - which is the question
        # the 22 hand-written entries cannot answer, because their specs and
        # the checks were written against each other.
        entries = [
            {"id": slugify(line), "request": line.strip(), "expect": {}}
            for line in Path(args.prompts).read_text().splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        if not entries:
            raise SystemExit("no prompts in %s" % args.prompts)
    else:
        entries = load_corpus()
    if args.id:
        entries = [e for e in entries if e["id"] == args.id] or entries[:0]
        if not entries:
            raise SystemExit("no entry with id %r" % args.id)
    if args.only:
        entries = entries[:args.only]

    import tempfile

    written: dict[str, Any] = {}
    for mode, runner in (("reachable", run_reachable),
                         ("first-try", run_first_try)):
        if mode == "reachable" and not args.reachable:
            continue
        if mode == "first-try" and not args.first_try:
            continue

        # Only the expensive pass is worth checkpointing; --reachable takes
        # six seconds and a resume file would just be a stale hazard.
        checkpoint = Path(args.checkpoint) if mode == "first-try" else None
        done = {} if (checkpoint is None or args.fresh) else load_checkpoint(checkpoint)
        if done:
            print("\nresuming: %d of %d already done in %s"
                  % (len(done), len(entries), checkpoint))

        print("\n%s: %d entries" % (mode, len(entries)))
        print("-" * 78)
        outcomes = []
        with tempfile.TemporaryDirectory(prefix="bpcad-fitrate-") as scratch:
            for entry in entries:
                if entry["id"] in done:
                    outcome = done[entry["id"]]
                    print("kept %6.1fs  %-26s %s (from the checkpoint)"
                          % (outcome.seconds, outcome.id,
                             outcome.failure_class or "fit"))
                    outcomes.append(outcome)
                    continue
                outcome = runner(entry, Path(scratch))
                if checkpoint is not None:
                    append_checkpoint(checkpoint, outcome)
                outcomes.append(outcome)
                mark = ("FIT " if outcome.fits
                        else "----" if not outcome.measurable
                        else "MISS" if outcome.built else "DEAD")
                print("%s %6.1fs  %-26s %s"
                      % (mark, outcome.seconds, outcome.id,
                         ("%d/%d" % (outcome.passed_checks, outcome.total_checks))
                         if outcome.built else outcome.error[:44]))
        written[mode] = report(outcomes, mode)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(written, indent=1))
    print("written to %s" % out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
