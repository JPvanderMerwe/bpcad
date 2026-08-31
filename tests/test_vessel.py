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
