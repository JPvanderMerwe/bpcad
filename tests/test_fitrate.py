"""
The fit-rate harness, and the floor it must not drop below.

BRIEF 12.6: "The eval harness is load-bearing. A corpus of realistic part specs
with known-correct dimensions, executed automatically, reporting first-try fit
rate as one number. Build it early. Regressions block merges."

This is the merge gate. It runs the REACHABLE half - the corpus's own specs,
built and asserted, no model - because that takes about ten seconds and can
therefore run on every change. The first-try number needs a model and tens of
minutes, so it lives in tools/fitrate.py and is run deliberately.

THE FLOOR IS A RECORDED MEASUREMENT, NOT A TARGET.
It is whatever the corpus actually achieved when last measured. If a change
takes it down, that is a regression and this fails. If a change takes it up,
raise the floor in the same commit and say why.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools import fitrate  # noqa: E402

# Measured 2026-09-04: 19 of 19 measurable entries. Raised from 16 in the same
# change that earned it, as the header above requires.
#
# WHAT MOVED, AND WHY.
#
#   plant_pot_drained  was failing because the vessel delivered 119.441 mm for
#                      the 120.0 it was asked for: on a cone the widest point
#                      IS the rim, and the 1.2 mm rim rounding ate 0.56 mm off
#                      it. The template now measures its own widest point and
#                      corrects, reporting the factor and the residual. That
#                      turned up a second one no entry covered: the belly
#                      profile used outer_dia_mm/2 as a Bezier CONTROL point,
#                      so a belly asked for 120 mm across delivered 99.8.
#   rod_clamp_8mm      was STALE, not unreachable. Its comment - "nothing in
#                      the vocabulary makes a split clamp with a bore and a
#                      flange" - was true when `disc` could only add material
#                      and no op could be rotated. Both arrived later and
#                      nobody revisited it.
#   snap_over_cable_clip  added on the evidence of the coverage test at the
#                      bottom of this file, not to move the number.
FLOOR_FITTED = 19
FLOOR_MEASURABLE = 19


@pytest.fixture(scope="module")
def measured(tmp_path_factory):
    entries = fitrate.load_corpus()
    root = tmp_path_factory.mktemp("fitrate")
    return [fitrate.run_reachable(entry, root) for entry in entries]


def test_the_corpus_is_the_size_the_brief_asks_for():
    """Brief 13 Phase 1: a fit rate on twenty real part requests."""
    entries = fitrate.load_corpus()
    assert len(entries) >= 20, "only %d entries" % len(entries)
    ids = [e["id"] for e in entries]
    assert len(set(ids)) == len(ids), "duplicate ids in the corpus"
    for entry in entries:
        assert entry.get("request"), "%s has no request" % entry["id"]
        assert entry.get("expect"), "%s asserts nothing" % entry["id"]


def test_the_reachable_fit_rate_has_not_regressed(measured):
    measurable = [o for o in measured if o.measurable]
    fitted = [o for o in measurable if o.fits]
    assert len(measurable) >= FLOOR_MEASURABLE, (
        "the corpus lost measurable entries: %d, was %d"
        % (len(measurable), FLOOR_MEASURABLE)
    )
    assert len(fitted) >= FLOOR_FITTED, (
        "reachable fit rate regressed: %d of %d fit, floor is %d. Failing: %s"
        % (len(fitted), len(measurable), FLOOR_FITTED,
           ", ".join(o.id for o in measurable if not o.fits))
    )


def test_every_assertion_kind_in_the_corpus_is_understood(measured):
    """
    A typo in an `expect` key is silent - the assertion simply never runs, and
    the entry passes for the wrong reason. This catches that.
    """
    known = {"extent_x_mm", "extent_y_mm", "extent_z_mm", "extent_any_mm",
             "hole_dia_mm", "hole_count", "hole_spacing_mm", "wall_mm", "bodies"}
    for entry in fitrate.load_corpus():
        unknown = set(entry.get("expect") or {}) - known
        assert not unknown, "%s asserts unknown keys: %s" % (entry["id"], unknown)


def test_a_part_that_is_wrong_is_reported_wrong(tmp_path):
    """
    The harness must be able to FAIL. A gate that cannot fail is not a gate.

    This used to lean on the plant pot: a real outstanding defect served as
    the standing proof that the assertions bite. Fixing the pot took the last
    failing entry with it and this test went red - correctly, because the gate
    had lost its evidence. Leaning on a live bug means the proof disappears
    the day the bug is fixed, and re-breaking a part to keep a test honest is
    not a trade anybody should take.

    So the proof is a negative control instead: a spec that really does build
    an 80 mm plate, asserted to be 95 mm. It must build, and it must not fit.
    """
    entry = {
        "id": "negative_control",
        "request": "a plate whose stated width is deliberately wrong",
        "expect": {"extent_x_mm": 95.0, "extent_y_mm": 40.0, "bodies": 1},
        "spec": {
            "level": 2,
            "ops": [{"op": "rounded_prism", "width_mm": 80.0,
                     "depth_mm": 40.0, "height_mm": 6.0}],
        },
    }
    outcome = fitrate.run_reachable(entry, tmp_path)

    assert outcome.built, "the control must build, or it proves nothing"
    assert outcome.measurable
    assert not outcome.fits, "an 80 mm plate asserted at 95 mm was reported as fitting"
    assert any("95" in line for line in outcome.lines)


def test_the_negative_control_passes_when_it_is_told_the_truth(tmp_path):
    """
    The other half of the control. If `fits` were hardcoded False the test
    above would pass for the wrong reason, so the same spec with the right
    number has to come back fitting.
    """
    entry = {
        "id": "positive_control",
        "request": "a plate whose stated width is right",
        "expect": {"extent_x_mm": 80.0, "extent_y_mm": 40.0, "bodies": 1},
        "spec": {
            "level": 2,
            "ops": [{"op": "rounded_prism", "width_mm": 80.0,
                     "depth_mm": 40.0, "height_mm": 6.0}],
        },
    }
    outcome = fitrate.run_reachable(entry, tmp_path)
    assert outcome.built and outcome.fits, outcome.lines


def test_an_unmeasurable_entry_is_not_counted_either_way(measured):
    """
    Brief 5 counts parts whose dimensions match. An entry asserting only
    "bodies: 1" cannot match or fail to match, and padding the denominator
    with them would move the number without moving the product.
    """
    trivial = [o for o in measured if not o.measurable]
    assert trivial, "the corpus has no deliberately-underspecified entries"
    for outcome in trivial:
        assert not outcome.fits, (
            "%s counted as a fit on a trivial assertion" % outcome.id
        )


def test_the_corpus_exercises_the_geometry_that_makes_a_part_look_designed():
    """
    THE NUMBER ABOVE IS ONLY WORTH WHAT THE CORPUS ASKS FOR.

    Nine of the fifteen level-2 ops were never exercised by any entry:
    arc_rod, blend_edges, profile_extrude, pattern_polar, mirror, pocket,
    sphere, emboss_polygon, emboss_text. Every one of them is a curve, a
    blend, a sweep or a pattern - the things that separate a designed part
    from a block with holes. A reachable rate of 100% against a corpus of
    prisms and discs says nothing about whether this program can make
    something that looks made.

    Compared side by side with Prusa's Extruder-cable-clip, which ships on
    every MK3S: 874 triangles, watertight, an arched snap-over section blended
    into a mounting foot. bpcad's mesh quality beat it comfortably - finer
    tessellation, no slivers - and the SHAPE was a rectangular block.

    This floor rises as entries are added. It is deliberately not a demand for
    all fifteen: emboss_text needs a font and the two embosses belong to a
    logo-tracing workflow the corpus does not cover.
    """
    import yaml

    from bpcad.spec.dsl import OP_NAMES

    def ops_in(obj, seen):
        if isinstance(obj, dict):
            if "op" in obj:
                seen.add(obj["op"])
            for value in obj.values():
                ops_in(value, seen)
        elif isinstance(obj, list):
            for value in obj:
                ops_in(value, seen)

    entries = fitrate.load_corpus()
    used = set()
    for entry in entries:
        ops_in(entry.get("spec") or {}, used)

    shaping = {"arc_rod", "blend_edges"}
    missing = shaping - used
    assert not missing, (
        "the corpus no longer exercises %s, so nothing measures whether this "
        "program can make a curved or blended part" % ", ".join(sorted(missing))
    )
    assert len(used & set(OP_NAMES)) >= 8, (
        "only %d of %d ops are exercised: %s"
        % (len(used), len(OP_NAMES), ", ".join(sorted(used)))
    )
