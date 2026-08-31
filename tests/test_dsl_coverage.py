"""
Coverage: can the primitive layer actually build the things people ask for?

WHY THIS FILE IS A LIST OF WHOLE PARTS AND NOT A LIST OF OPS
-------------------------------------------------------------
Testing each op in isolation proves the ops work and proves nothing about
whether the DSL is any use. The old layer passed every one of its own unit
tests while being unable to put a round hole in anything - the birdhouse
entrance, the most obvious feature on the most obvious test part, needed a
hand-written template. Op tests could not see that, because no op was broken.
The gap was in what the ops COULD NOT BE COMBINED INTO.

So each case here is a complete, plausible request - a tray, a wall hook, a
phone stand, a funnel - built end to end and checked as a real part: it builds,
it is one closed body, and it has volume. Every one of them was impossible
before, and each names the reason in its own docstring so a future change that
breaks it says which capability it took away.
"""

from __future__ import annotations

import pytest

from bpcad.build.helpers import probe
from bpcad.spec.dsl import DslError, run_ops

# ---------------------------------------------------------------------------
# Whole parts. Each was unbuildable before placement, rotation and cut mode.
# ---------------------------------------------------------------------------

BIRDHOUSE_BOX = [
    # Impossible before: no round hole. `disc` could only ADD material and
    # `pocket` cuts rectangles, so the entrance had to come from a template.
    {"op": "rounded_prism", "width_mm": 120, "depth_mm": 100, "height_mm": 160,
     "corner_r_mm": 6},
    {"op": "hollow", "wall_mm": 4, "opening": "top_face", "floor_mm": 4},
    # Rotating +90 about X points the disc's axis along -Y, so it grows from
    # the placement point towards the front. y_mm -40 spans -60..-40 and takes
    # the 4 mm front wall at -50 with it. Getting this wrong put the hole in
    # mid-air 10 mm clear of the box, and the part still built.
    {"op": "disc", "diameter_mm": 32, "height_mm": 20,
     "y_mm": -40, "z_mm": 100, "rotate_axis": "x", "rotate_deg": 90, "mode": "cut"},
]

DIVIDED_TRAY = [
    # Impossible before: rounded_prism had no position, so a part could never
    # contain two boxes in different places. No dividers, ever.
    {"op": "rounded_prism", "width_mm": 160, "depth_mm": 100, "height_mm": 40,
     "corner_r_mm": 4},
    {"op": "hollow", "wall_mm": 3, "opening": "top_face", "floor_mm": 3},
    {"op": "pattern_linear", "count": 3, "dx_mm": 50,
     "step": {"op": "rounded_prism", "width_mm": 3, "depth_mm": 94,
              "height_mm": 34, "x_mm": -50, "z_mm": 3}},
]

WALL_HOOK = [
    # Impossible before: same reason. A hook is three blocks in three places.
    {"op": "rounded_prism", "width_mm": 40, "depth_mm": 6, "height_mm": 80,
     "corner_r_mm": 3},
    {"op": "rounded_prism", "width_mm": 40, "depth_mm": 40, "height_mm": 8,
     "y_mm": -20, "z_mm": 10},
    {"op": "rounded_prism", "width_mm": 40, "depth_mm": 6, "height_mm": 22,
     "y_mm": -37, "z_mm": 18},
    {"op": "disc", "diameter_mm": 5, "height_mm": 10, "z_mm": 66,
     "y_mm": 5, "rotate_axis": "x", "rotate_deg": 90, "mode": "cut"},
]

PHONE_STAND = [
    # Impossible before: no sloped anything. There was no wedge and no way to
    # turn a block, so every part had to be made of axis-aligned boxes.
    {"op": "wedge", "width_mm": 80, "depth_mm": 70, "height_mm": 45},
    {"op": "rounded_prism", "width_mm": 80, "depth_mm": 8, "height_mm": 14,
     "y_mm": -31, "corner_r_mm": 2},
    {"op": "rounded_prism", "width_mm": 30, "depth_mm": 30, "height_mm": 60,
     "y_mm": 10, "z_mm": -5, "mode": "cut"},
]

COUNTERSUNK_PLATE = [
    # Impossible before: no holes, and no countersinks even in principle -
    # there was no cone.
    {"op": "rounded_prism", "width_mm": 80, "depth_mm": 40, "height_mm": 6,
     "corner_r_mm": 3},
    {"op": "pattern_linear", "count": 2, "dx_mm": 50,
     "step": {"op": "disc", "diameter_mm": 4.5, "height_mm": 10,
              "x_mm": -25, "z_mm": -2, "mode": "cut"}},
    {"op": "pattern_linear", "count": 2, "dx_mm": 50,
     "step": {"op": "cone", "bottom_d_mm": 4.5, "top_d_mm": 9.5, "height_mm": 2.6,
              "x_mm": -25, "z_mm": 3.5, "mode": "cut"}},
]

FUNNEL = [
    # Impossible before: no cone, so nothing could taper. Funnels, spouts,
    # draft angles and chamfered posts were all out of reach.
    {"op": "disc", "diameter_mm": 20, "height_mm": 25},
    {"op": "cone", "bottom_d_mm": 20, "top_d_mm": 60, "height_mm": 50, "z_mm": 25},
    {"op": "disc", "diameter_mm": 13, "height_mm": 27, "z_mm": -1, "mode": "cut"},
    {"op": "cone", "bottom_d_mm": 13, "top_d_mm": 53, "height_mm": 52,
     "z_mm": 24, "mode": "cut"},
]

BOTTLE_OPENER = [
    # Impossible before: no way to make an arbitrary silhouette as a BODY.
    # emboss_polygon could only decorate a face of something that already
    # existed, so the outline of a part could only ever be a rectangle, a
    # circle or an arc.
    {"op": "profile_extrude", "height_mm": 4,
     "points": [[0, -12], [70, -18], [95, -8], [95, 8], [70, 18], [0, 12]]},
    {"op": "disc", "diameter_mm": 19, "height_mm": 6, "x_mm": 74, "z_mm": -1,
     "mode": "cut"},
    {"op": "disc", "diameter_mm": 6, "height_mm": 6, "x_mm": 10, "z_mm": -1,
     "mode": "cut"},
]

FLUTED_KNOB = [
    # Impossible before: pattern_polar could place copies but not TURN them, so
    # every flute pointed the same way instead of radially.
    {"op": "disc", "diameter_mm": 40, "height_mm": 15},
    {"op": "pattern_polar", "count": 12, "radius_mm": 20, "turn_with_angle": True,
     "step": {"op": "rounded_prism", "width_mm": 4, "depth_mm": 12,
              "height_mm": 17, "z_mm": -1, "mode": "cut"}},
    {"op": "disc", "diameter_mm": 6, "height_mm": 12, "z_mm": -1, "mode": "cut"},
]

MIRRORED_BRACKET = [
    # Impossible before: no mirror. Symmetrical parts had to be described twice
    # and could be subtly lopsided without anything noticing.
    # The base has to be wide enough to REACH the uprights. At 20 mm wide it
    # spanned -10..10 and the uprights sat at 17..31, so the part came out as
    # three pieces floating apart - and it built, and it was watertight, and
    # every check passed. That is what the body count below is for.
    {"op": "rounded_prism", "width_mm": 70, "depth_mm": 60, "height_mm": 6},
    {"op": "rounded_prism", "width_mm": 14, "depth_mm": 6, "height_mm": 40,
     "x_mm": 24, "y_mm": -24},
    {"op": "mirror", "plane": "yz"},
]

CASES = [
    ("birdhouse box with an entrance", BIRDHOUSE_BOX),
    ("divided tray", DIVIDED_TRAY),
    ("wall hook", WALL_HOOK),
    ("phone stand", PHONE_STAND),
    ("countersunk plate", COUNTERSUNK_PLATE),
    ("funnel", FUNNEL),
    ("bottle opener", BOTTLE_OPENER),
    ("fluted knob", FLUTED_KNOB),
    ("mirrored bracket", MIRRORED_BRACKET),
]


@pytest.mark.parametrize("label,ops", CASES, ids=[c[0] for c in CASES])
def test_the_dsl_can_build_an_ordinary_request(label, ops):
    scene = run_ops(ops)
    assert scene.solid is not None, "%s produced no solid" % label
    solid = scene.solid.val()
    assert solid.Volume() > 1.0, "%s came out with no volume" % label
    # probe(), not isValid(). A chamfer once produced a solid that reported
    # valid and then broke every subsequent boolean.
    assert probe(scene.solid), "%s produced a solid that fails a real boolean" % label

    # THE ONE THAT MATTERS. A cut that misses the part builds perfectly and is
    # wrong, and no amount of looking at a volume figure reveals it. Two of
    # these cases shipped with a hole floating 10 mm clear of the wall until
    # this line existed.
    missed = [n for n in scene.log.notes if "removed nothing" in n]
    assert not missed, "%s has a cut that misses the part: %s" % (label, missed)

    # ONE BODY. A part that has quietly fallen into three pieces is valid,
    # watertight and printable - as three pieces, in three places on the bed,
    # which is not what anybody asked for. The mirrored bracket did exactly
    # this and nothing said a word until the render was looked at.
    bodies = len(scene.solid.val().Solids())
    assert bodies == 1, "%s came out as %d separate pieces, not one part" % (label, bodies)


def test_the_entrance_hole_actually_removes_material():
    """
    A cut that does nothing is the failure mode to fear here, because it looks
    exactly like a cut that worked until someone opens the render.
    """
    solid_box = run_ops(BIRDHOUSE_BOX[:2]).solid.val().Volume()
    with_hole = run_ops(BIRDHOUSE_BOX).solid.val().Volume()
    assert with_hole < solid_box - 500, (
        "the entrance removed %.1f mm3, which is not a 32 mm hole through a "
        "4 mm wall" % (solid_box - with_hole)
    )


# ---------------------------------------------------------------------------
# The refusals. Coverage is only worth having if the wrong answer still fails.
# ---------------------------------------------------------------------------


def test_a_cut_that_removes_everything_is_refused():
    with pytest.raises(DslError) as exc:
        run_ops([
            {"op": "rounded_prism", "width_mm": 10, "depth_mm": 10, "height_mm": 10},
            {"op": "rounded_prism", "width_mm": 200, "depth_mm": 200,
             "height_mm": 200, "z_mm": -50, "mode": "cut"},
        ])
    assert "entire part" in str(exc.value)


def test_a_cut_with_nothing_to_cut_from_is_refused():
    with pytest.raises(DslError) as exc:
        run_ops([{"op": "disc", "diameter_mm": 5, "height_mm": 5, "mode": "cut"}])
    assert "nothing has been created yet" in str(exc.value)


def test_a_cut_that_misses_is_reported_but_not_fatal():
    """
    Missing the part is usually a mistake, but it is not a broken part, and
    killing the build would lose everything else that was right about it.
    """
    scene = run_ops([
        {"op": "rounded_prism", "width_mm": 10, "depth_mm": 10, "height_mm": 10},
        {"op": "disc", "diameter_mm": 2, "height_mm": 2, "x_mm": 500, "mode": "cut"},
    ])
    assert any("removed nothing" in n for n in scene.log.notes)


def test_a_cone_with_two_zero_ends_is_refused():
    with pytest.raises(DslError) as exc:
        run_ops([{"op": "cone", "bottom_d_mm": 0, "top_d_mm": 0, "height_mm": 10}])
    assert "not a solid" in str(exc.value)


def test_turning_a_pattern_needs_something_turnable():
    with pytest.raises(DslError) as exc:
        run_ops([
            {"op": "rounded_prism", "width_mm": 40, "depth_mm": 40, "height_mm": 10},
            {"op": "pattern_polar", "count": 4, "radius_mm": 10,
             "turn_with_angle": True,
             "step": {"op": "blend_edges", "group": "vertical", "amount_mm": 1}},
        ])
    assert "not one" in str(exc.value)


def test_rotation_happens_before_placement_not_after():
    """
    Move-then-rotate swings the body around the world origin on a long arm and
    lands it somewhere nobody predicted. This pins the order by measuring where
    a far-out block actually ends up.
    """
    scene = run_ops([{
        "op": "rounded_prism", "width_mm": 10, "depth_mm": 10, "height_mm": 10,
        "x_mm": 100, "rotate_axis": "z", "rotate_deg": 90,
    }])
    bb = scene.solid.val().BoundingBox()
    # Rotated in place, then moved to x=100: still centred on x=100.
    assert abs((bb.xmin + bb.xmax) / 2.0 - 100.0) < 1e-6
    assert abs((bb.ymin + bb.ymax) / 2.0) < 1e-6


def test_every_creator_can_cut_as_well_as_add():
    """
    The whole coverage argument rests on this: shapes times modes. If a creator
    quietly ignored `mode` it would silently add material where a hole was
    asked for, which is the worst possible failure - a part that builds, passes
    and is wrong.
    """
    base = {"op": "rounded_prism", "width_mm": 60, "depth_mm": 60, "height_mm": 30}
    cutters = [
        {"op": "rounded_prism", "width_mm": 8, "depth_mm": 8, "height_mm": 40, "z_mm": -5},
        {"op": "disc", "diameter_mm": 8, "height_mm": 40, "z_mm": -5},
        {"op": "cone", "bottom_d_mm": 12, "top_d_mm": 2, "height_mm": 20, "z_mm": 12},
        {"op": "sphere", "diameter_mm": 14, "z_mm": 30},
        {"op": "wedge", "width_mm": 70, "depth_mm": 20, "height_mm": 20, "y_mm": 22, "z_mm": 14},
        {"op": "profile_extrude", "height_mm": 40, "z_mm": -5,
         "points": [[-4, -4], [4, -4], [4, 4], [-4, 4]]},
        {"op": "arc_rod", "arc_r_mm": 20, "rod_d_mm": 4, "thickness_mm": 40, "z_mm": -5},
    ]
    whole = run_ops([base]).solid.val().Volume()
    for cutter in cutters:
        cut = dict(cutter, mode="cut")
        after = run_ops([base, cut]).solid.val().Volume()
        assert after < whole - 1.0, (
            "%r in cut mode removed only %.3f mm3 - it is not cutting"
            % (cutter["op"], whole - after)
        )
