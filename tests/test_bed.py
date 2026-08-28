"""
Does it fit on the printer?

The most basic printability question there is, and it was missing. A refinement
asked for "a more complex birdhouse" and produced a 1248 x 590 x 600 mm print
layout - eighteen kilograms of filament - and every other check passed it,
because it was a sound object that simply could not be made on any machine in
the building.
"""

import pytest

from bpcad import api
from bpcad.verify.bed import check_bed

BED = (220.0, 220.0, 250.0)


def test_a_normal_part_fits():
    assert check_bed((86.0, 31.0, 35.0), BED).ok


def test_an_oversized_part_is_a_failure_not_a_warning():
    """
    A part that cannot be made is not a part, however sound its geometry. This
    is the one printability check that has to fail rather than warn.
    """
    r = check_bed((1248.0, 590.0, 600.0), BED)
    assert not r.ok
    assert not r.fits
    assert "does not fit the printer" in r.problems[0]


def test_the_message_says_which_dimension_is_over():
    r = check_bed((1248.0, 590.0, 600.0), BED)
    assert "footprint" in r.problems[0]
    assert "tall" in r.problems[0]


def test_too_tall_alone_is_caught():
    r = check_bed((100.0, 100.0, 400.0), BED)
    assert not r.ok
    assert "tall" in r.problems[0]
    assert "footprint" not in r.problems[0]


def test_a_part_that_only_fits_turned_is_allowed_and_flagged():
    """
    A 210 x 90 part fits a 220 x 220 bed either way; a checker that tries only
    one orientation is wrong half the time. But you have to be told to turn it.
    """
    # 100 x 215 on a 220 x 120 bed: too deep as it stands, fine turned.
    r = check_bed((100.0, 215.0, 50.0), (220.0, 120.0, 250.0))
    assert r.ok and r.rotated
    assert any("turned 90 degrees" in w for w in r.warnings)


def test_height_is_not_rotated_away():
    """
    Print orientation is deliberate in this project. A part is not silently
    laid on its side to make it fit.
    """
    r = check_bed((50.0, 50.0, 400.0), BED)
    assert not r.ok


def test_a_snug_fit_is_flagged():
    r = check_bed((215.0, 100.0, 50.0), BED)
    assert r.ok
    assert any("usable area" in w for w in r.warnings)


def test_the_bed_is_configured_and_readable():
    cfg = api.config()
    w, d, h = cfg.bed_mm
    assert w > 50 and d > 50 and h > 50


def test_an_oversized_part_fails_verification():
    """End to end: the check has to reach the verdict, not just exist."""
    from pathlib import Path

    stl = Path("parts/threadtest/v03/out/birdhouse.stl")
    if not stl.is_file():
        pytest.skip("the oversized part is not on disk")
    report = api.verify(stl)
    assert report.verdict == "FAIL"
    assert any("does not fit the printer" in p for p in report.problems)


def test_the_reference_parts_still_fit():
    """A check that fails good parts gets switched off."""
    for path in ("reference/vent_louvre.stl", "reference/loop_keyring.stl"):
        report = api.verify(path)
        assert report.bed.ok, path
        assert not report.problems, path


def test_pieces_that_each_fit_are_a_warning_not_a_failure():
    """
    A birdhouse and its roof laid side by side are 288 mm across, over a 220 mm
    bed - but they are two pieces and each fits easily. "Print them in two
    goes" is the answer; "impossible" is not.
    """
    r = check_bed(
        (288.0, 140.0, 160.0), BED,
        body_sizes=[(120.0, 100.0, 160.0), (160.0, 140.0, 6.0)],
    )
    assert r.ok, "each piece fits on its own"
    assert r.fits
    assert any("separate runs" in w for w in r.warnings)


def test_a_single_oversized_body_is_still_a_failure():
    r = check_bed((600.0, 100.0, 100.0), BED, body_sizes=[(600.0, 100.0, 100.0)])
    assert not r.ok


def test_pieces_that_do_not_individually_fit_still_fail():
    r = check_bed(
        (900.0, 500.0, 400.0), BED,
        body_sizes=[(450.0, 500.0, 400.0), (450.0, 300.0, 20.0)],
    )
    assert not r.ok, "a 400 mm tall piece does not fit a 250 mm build height"
