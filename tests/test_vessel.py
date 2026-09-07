"""
The round vessel, and the reason it had to exist.

Asked for a bowl, this program produced a rectangular birdhouse - reliably,
every time. Not a model failure: the `enclosure` template claimed the words
"pot", "planter", "plant pot" and "tub" in its `makes` list, a model picking a
template matches on words, and it did exactly what it was told. The part passed
every check, because nothing downstream knows what a bowl looks like.
"""

from __future__ import annotations

import math

import pytest

from bpcad.build.helpers import BuildLog, probe
from bpcad.build.templates.vessel import VesselParams, build_core
from bpcad.spec import registry

PROFILES = ("flared", "straight", "belly", "cylinder")


def core(**params):
    p = VesselParams(**params)
    return p, build_core(p, BuildLog())


# ---------------------------------------------------------------------------
# the bug that started it
# ---------------------------------------------------------------------------


ROUND_WORDS = ("bowl", "pot", "plant pot", "planter", "vase", "dish", "cup", "tub")


@pytest.mark.parametrize("word", ROUND_WORDS)
def test_a_round_word_belongs_to_the_round_template(word):
    """
    THE ACTUAL COMPLAINT. Whoever claims "pot" is what a request for a plant
    pot gets built as, and the rectangular template used to claim it. Claiming
    a word you cannot make is worse than claiming nothing: falling through to
    primitives gives a rough bowl, being confidently handed a box gives a box.
    """
    claimants = [n for n in registry.names() if word in registry.get(n).makes]
    assert "enclosure" not in claimants, (
        "the rectangular enclosure template claims %r, so every request for one "
        "will be built as a square box" % word
    )
    assert "vessel" in claimants, "nothing round claims %r" % word


def test_the_enclosure_says_it_is_rectangular_in_its_summary():
    """The summary is what a model reads when the makes words do not decide it."""
    summary = registry.get("enclosure").summary.upper()
    assert "RECTANGULAR" in summary


# ---------------------------------------------------------------------------
# it has to be a vessel, not a lump
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("profile", PROFILES)
def test_every_profile_is_actually_hollow(profile):
    """
    THE ONE THAT MATTERS. The cavity used to be built by dropping the outer
    stations that fell below the floor - fine with 25 of them, silently fatal
    with two. A straight-sided pot has stations only at its base and its rim,
    the base one sits under the floor, one was left, and a length guard skipped
    the cut entirely. The pen pot came out at 502.5 cm3, which is exactly
    pi r^2 h, and it was watertight, one body, and reported PASS.
    """
    p, solid = core(profile=profile, outer_dia_mm=80, height_mm=100, wall_mm=2.4)
    volume = solid.val().Volume()
    solid_block = math.pi * (p.outer_dia_mm / 2.0) ** 2 * p.height_mm
    assert volume < solid_block * 0.35, (
        "%s came out at %.0f%% of a solid block of the same size - it is not "
        "hollow" % (profile, 100 * volume / solid_block)
    )
    assert volume > solid_block * 0.02, (
        "%s is %.1f%% of solid, which is too little to be a wall" % (
            profile, 100 * volume / solid_block)
    )


@pytest.mark.parametrize("profile", PROFILES)
def test_every_profile_is_one_sound_body(profile):
    """
    A straight profile lofts as 24 bands of the SAME cone, and CadQuery's
    clean() runs a shape upgrader that tries to sew coplanar faces together and
    dies with "Courbes non jointives". Straight profiles now use two stations
    and the loft does not clean.
    """
    _p, solid = core(profile=profile, outer_dia_mm=80, height_mm=100, wall_mm=2.4)
    assert len(solid.val().Solids()) == 1
    assert probe(solid), "%s produced a solid that fails a real boolean" % profile


def test_a_bowl_is_wider_than_it_is_tall_and_a_vase_is_not():
    """A shape test, because 'it built' says nothing about whether it is a bowl."""
    _p, bowl = core(profile="flared", outer_dia_mm=180, height_mm=70)
    bb = bowl.val().BoundingBox()
    assert bb.xlen > bb.zlen * 2, "that is not a bowl shape"

    _p, vase = core(profile="belly", outer_dia_mm=110, height_mm=180, wall_mm=2.0)
    vb = vase.val().BoundingBox()
    assert vb.zlen > vb.xlen, "that is not a vase shape"


def test_the_belly_profile_actually_has_a_belly():
    """Otherwise it is a cylinder wearing a different name."""
    p = VesselParams(profile="belly", outer_dia_mm=110, height_mm=180)
    from bpcad.build.templates.vessel import _outer_profile

    radii = [r for r, _z in _outer_profile(p)]
    assert max(radii) > radii[0] * 1.05, "no bulge"
    assert max(radii) > radii[-1] * 1.05, "does not draw back in at the neck"


def test_drainage_holes_remove_material():
    _p, dry = core(profile="straight", outer_dia_mm=120, height_mm=110, foot_mm=6)
    _p, drained = core(profile="straight", outer_dia_mm=120, height_mm=110,
                       foot_mm=6, drain_holes=4, drain_dia_mm=6.0)
    assert drained.val().Volume() < dry.val().Volume() - 100


# ---------------------------------------------------------------------------
# refusals
# ---------------------------------------------------------------------------


def test_a_bowl_too_flared_to_print_is_refused():
    """
    A wall that opens outward as it rises is extruding onto air past 45 degrees
    from vertical. Refused at the spec, not reported afterwards - "your bowl
    needs supports on the outside" is not something anybody can act on.
    """
    with pytest.raises(ValueError) as exc:
        VesselParams(profile="flared", outer_dia_mm=300, height_mm=40,
                     base_dia_mm=40, rim_dia_mm=300)
    assert "extruding onto air" in str(exc.value)


def test_the_default_bowl_is_printable_without_support():
    from bpcad.build.templates.vessel import MAX_LEAN_DEG

    assert VesselParams().worst_lean_deg() <= MAX_LEAN_DEG


def test_a_wall_thicker_than_the_vessel_is_refused():
    with pytest.raises(ValueError) as exc:
        VesselParams(outer_dia_mm=20, wall_mm=12.0)
    assert "no cavity" in str(exc.value)


def test_drainage_holes_too_big_for_the_base_are_refused():
    with pytest.raises(ValueError) as exc:
        VesselParams(outer_dia_mm=60, drain_holes=4, drain_dia_mm=40.0)
    assert "will not fit" in str(exc.value)


# ---------------------------------------------------------------------------
# THE NUMBER ASKED FOR IS THE NUMBER DELIVERED.
#
# nominal_mm claims (outer_dia_mm, outer_dia_mm, height_mm) and check_intent
# compares the REQUEST against that claim - never against the solid. So a
# template could under-deliver its own stated diameter and every layer above
# would agree the part was right. Two profiles did:
#
#   straight   119.465 for 120 asked - the 1.2 mm cosmetic rim rounding ate
#              the widest point, which on a cone IS the rim
#   belly       99.817 for 120 asked - outer_dia_mm/2 was used as a Bezier
#              CONTROL point, and a Bezier does not pass through its control
#              point, so the waist landed 17% short
#
# The first was visible in the corpus (plant_pot_drained, kept failing on
# purpose). The second was invisible: no corpus entry uses belly.
# ---------------------------------------------------------------------------

def widest_dia(body):
    bb = body.val().BoundingBox()
    return max(bb.xmax - bb.xmin, bb.ymax - bb.ymin)


@pytest.mark.parametrize("profile", PROFILES)
def test_every_profile_delivers_the_diameter_it_was_asked_for(profile):
    _, body = core(profile=profile, outer_dia_mm=120.0, height_mm=110.0,
                   wall_mm=2.4)
    got = widest_dia(body)
    assert abs(got - 120.0) <= 0.05, (
        "%s delivered %.3f mm across for 120.0 asked" % (profile, got)
    )


def test_the_belly_waist_reaches_the_stated_diameter():
    """The 20 mm error, pinned. It was 99.817 for 120 asked."""
    _, body = core(profile="belly", outer_dia_mm=120.0, height_mm=110.0,
                   wall_mm=2.4)
    assert widest_dia(body) > 119.5


def test_the_bezier_control_point_puts_the_peak_where_it_was_asked():
    """Exact, not iterated - so this is an equality assertion, not a band."""
    from bpcad.build.templates.vessel import _bezier_control_for_peak

    for base_r, rim_r, peak_r in ((34.8, 43.2, 60.0), (20.0, 30.0, 45.0),
                                  (5.0, 5.0, 25.0)):
        u = _bezier_control_for_peak(base_r, rim_r, peak_r)
        a = base_r - 2.0 * u + rim_r
        b = 2.0 * (u - base_r)
        assert a < 0, "no maximum between the ends"
        peak = base_r - b * b / (4.0 * a)
        assert peak == pytest.approx(peak_r, abs=1e-9)


def test_an_unreachable_peak_falls_back_rather_than_raising():
    """
    A waist narrower than one of the ends has no maximum between them. The
    plain control point is the honest answer there, not an exception.
    """
    from bpcad.build.templates.vessel import _bezier_control_for_peak

    assert _bezier_control_for_peak(60.0, 50.0, 40.0) == 40.0


def test_the_rim_correction_reports_its_own_factor():
    """
    CLAUDE.md 15: every deliberate departure from true scale is reported with
    its numeric factor. A silent correction is the same class of problem as
    the silent shortfall it fixes.
    """
    log = BuildLog()
    p = VesselParams(profile="straight", outer_dia_mm=120.0, height_mm=110.0,
                     wall_mm=2.4)
    build_core(p, log)
    widened = [n for n in log.notes if "rim widened" in n]
    assert widened, "the rim was corrected without saying so"
    assert "Residual after correction" in widened[0]


@pytest.mark.parametrize("profile", ("cylinder", "flared"))
def test_a_profile_that_is_already_right_is_not_rebuilt(profile):
    """
    The correction costs a whole second build, so it must fire only when it is
    needed. A cylinder loses nothing to the rim rounding, and flared loses
    0.032 mm - under the floor, and deliberately left alone so existing bowls
    keep their geometry to the micron.
    """
    log = BuildLog()
    core(profile=profile, outer_dia_mm=120.0, height_mm=110.0, wall_mm=2.4)
    p = VesselParams(profile=profile, outer_dia_mm=120.0, height_mm=110.0,
                     wall_mm=2.4)
    build_core(p, log)
    assert not [n for n in log.notes if "rim widened" in n]
