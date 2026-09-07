"""
One prompt, several genuinely different parts.

The model is asked ONCE and the options come from walking the template's own
axes in Python. Four model calls would be ten minutes on this hardware and
would mostly return the same answer with one number nudged.
"""

from __future__ import annotations

import pytest

from bpcad import api
from bpcad.agent import variations


def spec_for(template, params=None):
    return api.validate_spec({
        "name": "v_" + template, "level": 1, "material": "petg",
        "nozzle_mm": 0.4, "layer_mm": 0.24,
        "template": template, "params": params or {},
    })


# ---------------------------------------------------------------------------
# planning
# ---------------------------------------------------------------------------


def test_the_base_is_always_the_first_option():
    """What was asked for is an option, and it is the first one."""
    plan = variations.plan("vessel", {"outer_dia_mm": 180.0})
    assert plan[0] == {"outer_dia_mm": 180.0}


def test_only_one_axis_moves_at_a_time():
    """
    Moving three things at once gives four options all different from the base
    and all indistinguishable from each other, and none of them says which
    change did what.
    """
    base = {"profile": "flared", "pattern": "solid", "cell_seed": 7}
    for params in variations.plan("vessel", base)[1:]:
        differing = [k for k in params if base.get(k) != params[k]]
        assert len(differing) == 1, "%s changed %d axes at once" % (params, len(differing))


def test_the_default_value_of_an_axis_is_not_offered_as_a_change():
    """
    A birdhouse was offered "roof pitch 18" as an alternative to a roof
    already pitched 18 degrees, because the base dict was empty and the
    template's own defaults were never consulted.
    """
    plan = variations.plan("enclosure", {})
    default_pitch = variations.resolved_base("enclosure", {})["roof_pitch_deg"]
    for params in plan[1:]:
        assert params.get("roof_pitch_deg") != default_pitch


def test_resolving_the_base_fills_in_template_defaults():
    resolved = variations.resolved_base("enclosure", {})
    assert resolved["finish"] == "plain"
    assert resolved["roof_pitch_deg"] == 18.0


def test_an_unknown_template_plans_only_the_base():
    assert variations.plan("nothing_like_this", {"a": 1}) == [{"a": 1}]


# ---------------------------------------------------------------------------
# distinctness
# ---------------------------------------------------------------------------


def test_a_style_change_counts_as_distinct_however_little_volume_moves():
    """
    THE ONE THAT MATTERS. A board finish and a slat finish differ by 1.7% of
    volume and not at all in bounding box, and look nothing like each other.
    Judging a surface finish by volume culled every one of them and left a
    birdhouse with exactly one "option".
    """
    board = variations.Variant(label="board", params={}, changed={"finish": "board"},
                               volume_cm3=354.6, envelope_mm=(288.0, 140.0, 160.0))
    slat = variations.Variant(label="slat", params={}, changed={"finish": "slat"},
                              volume_cm3=357.8, envelope_mm=(288.0, 140.0, 160.0))
    assert variations._distinct(slat, [board])


def test_the_same_style_change_twice_is_not_distinct():
    a = variations.Variant(label="board", params={}, changed={"finish": "board"})
    assert not variations._distinct(a, [a])


def test_a_size_change_has_to_prove_itself_on_the_geometry():
    """A bowl and the same bowl 1 mm taller is one option shown twice."""
    base = variations.Variant(label="a", params={}, changed={"height_mm": 70.0},
                              volume_cm3=100.0, envelope_mm=(180.0, 180.0, 70.0))
    nearly = variations.Variant(label="b", params={}, changed={"height_mm": 71.0},
                                volume_cm3=101.0, envelope_mm=(180.0, 180.0, 71.0))
    apart = variations.Variant(label="c", params={}, changed={"height_mm": 120.0},
                               volume_cm3=170.0, envelope_mm=(180.0, 180.0, 120.0))
    assert not variations._distinct(nearly, [base])
    assert variations._distinct(apart, [base])


# ---------------------------------------------------------------------------
# building, end to end
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("template,params,least", [
    ("vessel", {"profile": "flared", "outer_dia_mm": 180.0,
                "height_mm": 70.0, "wall_mm": 2.6}, 3),
    ("enclosure", {}, 2),
])
def test_a_prompt_yields_several_buildable_options(template, params, least):
    built = variations.build_variants(spec_for(template, params), api.config(),
                                      count=4, out_root="/tmp/bpcad_var_test")
    assert len(built) >= least, "only %d options for %s" % (len(built), template)
    for variant in built:
        assert variant.verdict, "%s has no verdict" % variant.label
        assert variant.volume_cm3 > 0
        assert variant.name


def test_every_option_offered_actually_builds():
    """
    A variant that fails is DROPPED, never offered. An option that turns out to
    be broken when you click it is worse than one fewer option.
    """
    built = variations.build_variants(
        spec_for("vessel", {"profile": "flared", "outer_dia_mm": 180.0,
                            "height_mm": 70.0, "wall_mm": 2.6}),
        api.config(), count=4, out_root="/tmp/bpcad_var_test2")
    for variant in built:
        assert not variant.verdict.upper().startswith("FAIL")


def test_the_options_are_not_all_the_same_object():
    built = variations.build_variants(
        spec_for("vessel", {"profile": "flared", "outer_dia_mm": 180.0,
                            "height_mm": 70.0, "wall_mm": 2.6}),
        api.config(), count=4, out_root="/tmp/bpcad_var_test3")
    volumes = [round(v.volume_cm3, 1) for v in built]
    assert len(set(volumes)) == len(volumes), "two options measured identically: %s" % volumes


# ---------------------------------------------------------------------------
# Variants of a part that has ops instead of parameters - which is every part
# that arrived as an uploaded mesh.
# ---------------------------------------------------------------------------

LEVEL_2_POT = dict(
    name="imported_pot", level=2, material="petg", nozzle_mm=0.4, layer_mm=0.2,
    ops=[
        # A 90 mm square outline, 70 tall - the shape a fitter recovers from
        # an uploaded mesh: an outline and a height, and no named parameters
        # anywhere in it.
        {"op": "profile_extrude",
         "points": [[-45.0, -45.0], [45.0, -45.0], [45.0, 45.0], [-45.0, 45.0]],
         "height_mm": 70.0},
    ],
)


def test_a_scaled_op_scales_the_outline_too():
    """
    THE SUFFIX RULE IS NOT ENOUGH. Almost every length in the DSL ends in
    `_mm`, but a profile_extrude's `points` are bare (x, y) pairs and with the
    default scale_mm of 1.0 those pairs ARE millimetres. Trusting the suffix
    scaled the height and left the outline alone: a 90 x 90 x 70 pot came back
    90 x 90 x 56 - shorter, and never narrower.
    """
    from bpcad.agent.variations import _scaled_op

    scaled = _scaled_op({"op": "profile_extrude",
                         "points": [[10.0, 0.0], [10.0, 20.0]],
                         "height_mm": 50.0}, 0.5)
    assert scaled["height_mm"] == 25.0
    assert scaled["points"] == [[5.0, 0.0], [5.0, 10.0]]


def test_scaling_leaves_counts_and_angles_alone():
    """Scaling `rotate_deg` makes a different part; scaling `count` is not
    even meaningful."""
    from bpcad.agent.variations import _scaled_op

    scaled = _scaled_op({"op": "pattern_polar", "count": 6, "radius_mm": 20.0,
                         "start_deg": 45.0,
                         "step": {"op": "disc", "diameter_mm": 4.0,
                                  "height_mm": 10.0}}, 2.0)
    assert scaled["count"] == 6
    assert scaled["start_deg"] == 45.0
    assert scaled["radius_mm"] == 40.0
    assert scaled["step"]["diameter_mm"] == 8.0, "nested ops scale too"


def test_more_versions_of_a_part_with_no_template(tmp_path):
    """
    An uploaded mesh never has a template - the fitter recovers an outline,
    not a wall thickness - so this is the path that makes "more versions of
    what I uploaded" mean anything at all. build_variants returns nothing for
    these, by design.
    """
    from bpcad import api
    from bpcad.agent.variations import build_scale_variants, build_variants
    from bpcad.spec.schema import PartSpec

    spec = PartSpec(**LEVEL_2_POT)
    assert build_variants(spec, api.config()) == [], "no parameters to vary"

    made = build_scale_variants(spec, api.config(), count=4,
                                out_root=str(tmp_path))
    assert len(made) >= 3, [v.label for v in made]
    widths = sorted(round(v.envelope_mm[0], 1) for v in made)
    assert len(set(widths)) == len(widths), "the variants are all different sizes"
    assert widths[0] < 90.0 < widths[-1], "a smaller one and a bigger one"
