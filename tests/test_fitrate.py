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

# Measured 2026-09-03: 16 of 18 measurable entries.
#
# The two that fail, and why they are allowed to:
#   plant_pot_drained  120 mm asked, 119.441 delivered - the vessel template's
#                      1.2 mm rim fillet eats 0.56 mm off its own stated
#                      diameter. A real defect, left visible.
#   rod_clamp_8mm      no vocabulary expresses a split clamp with a bore and a
#                      flange. A real gap, left visible.
FLOOR_FITTED = 16
FLOOR_MEASURABLE = 18


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


def test_a_part_that_is_wrong_is_reported_wrong(measured):
    """
    The harness must be able to FAIL. A gate that cannot fail is not a gate,
    and the plant pot is the standing proof that this one can.
    """
    failing = [o for o in measured if o.measurable and o.built and not o.fits]
    assert failing, (
        "every measurable entry passed, so this gate has not been shown to "
        "detect anything. Either the corpus needs a harder entry or the "
        "assertions are not being run."
    )


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
