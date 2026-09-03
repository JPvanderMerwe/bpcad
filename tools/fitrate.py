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

    def to_json(self) -> dict[str, Any]:
        data = dict(self.__dict__)
        return data


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

    return {
        "mode": mode,
        "fit_rate": round(rate, 4),
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
    args = parser.parse_args(argv)

    if not args.reachable and not args.first_try:
        args.reachable = True          # the cheap one is the sane default

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

        print("\n%s: %d entries" % (mode, len(entries)))
        print("-" * 78)
        outcomes = []
        with tempfile.TemporaryDirectory(prefix="bpcad-fitrate-") as scratch:
            for entry in entries:
                outcome = runner(entry, Path(scratch))
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
