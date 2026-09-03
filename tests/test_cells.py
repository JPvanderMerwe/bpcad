"""
The Voronoi cell shell.

A generative pattern in a program whose durable artifact is a spec file has one
non-negotiable property: the same spec must give the same part. Most of this
file is about that, and about the two ways the cutting went wrong - once
removing nothing, once removing the entire bowl - while reporting success.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from bpcad.build import cells
from bpcad.build.helpers import BuildLog, probe
from bpcad.build.templates.vessel import VesselParams, build_core

CELL_BOWL = dict(pattern="cells", profile="flared", outer_dia_mm=180.0,
                 height_mm=70.0, wall_mm=2.6, cell_count=60, strut_mm=3.2,
                 cell_seed=7)


def core(**overrides):
    p = VesselParams(**{**CELL_BOWL, **overrides})
    return p, build_core(p, BuildLog())


# ---------------------------------------------------------------------------
# it has to rebuild
# ---------------------------------------------------------------------------


def test_the_same_seed_gives_the_same_bowl():
    """
    The spec is the durable artifact. A pattern that came out different on
    every build would mean the spec no longer describes the part, and the
    regression digest would churn on every run for no reason.
    """
    a = core()[1].val().Volume()
    b = core()[1].val().Volume()
    assert a == pytest.approx(b, abs=1e-9), "the same spec built two different bowls"


def test_a_different_seed_gives_a_different_bowl():
    """Otherwise the seed is decoration and every bowl is the same bowl."""
    a = core(cell_seed=7)[1].val().Volume()
    b = core(cell_seed=99)[1].val().Volume()
    assert a != pytest.approx(b, abs=1e-6)


def test_the_seeds_themselves_are_reproducible():
    kw = dict(count=40, u_span=400.0, v_lo=10.0, v_hi=60.0, seed=3)
    assert np.allclose(cells.relaxed_seeds(**kw), cells.relaxed_seeds(**kw))


# ---------------------------------------------------------------------------
# the cut has to remove SOME of it
# ---------------------------------------------------------------------------


def test_the_cells_remove_material_but_not_the_bowl():
    """
    Both ends of this went wrong and both reported success.

    Lofting each cell between a non-planar inner and outer ring produced
    self-intersecting solids, several with NEGATIVE volume, which subtracted
    the whole bowl: one body, zero volume, no error. And a pattern whose
    struts have closed up removes nothing at all, which looks identical to a
    plain bowl and is equally silent.
    """
    _p, solid = core(pattern="solid")
    plain = solid.val().Volume()
    _p, holed = core()
    cut = holed.val().Volume()

    assert cut > plain * 0.25, (
        "the cells removed %.0f%% of the bowl - that is not a pattern, that is "
        "a demolition" % (100 * (1 - cut / plain))
    )
    assert cut < plain * 0.95, (
        "the cells removed only %.1f%% - the web has closed up and the wall is "
        "effectively solid" % (100 * (1 - cut / plain))
    )


def test_a_cell_bowl_is_one_sound_body():
    _p, holed = core()
    assert len(holed.val().Solids()) == 1, "the bowl fell apart into pieces"
    # probe(), not isValid(). A shell with a hundred holes in it is exactly the
    # kind of thing that reports valid and then breaks the next boolean.
    assert probe(holed)


def test_the_rim_and_the_base_stay_solid():
    """
    The rim is what holds a thin shell round, and the base is what it stands
    on. Perforating either gives a bowl that arrives as an oval.
    """
    p = VesselParams(**CELL_BOWL)
    lo, hi = p.pattern_z_range()
    assert lo >= p.foot_mm + p.floor_thickness_mm + p.base_band_mm - 1e-9
    assert hi <= p.height_mm - p.rim_band_mm + 1e-9

    polys = cells.cell_polygons(p.cell_count, p.pattern_span_mm(), lo, hi,
                               p.strut_mm, p.cell_seed)
    assert polys
    for poly in polys:
        assert poly[:, 1].min() >= lo - 1e-6, "a hole reaches below the base band"
        assert poly[:, 1].max() <= hi + 1e-6, "a hole reaches into the rim band"


def test_the_pattern_is_open_but_not_a_hole():
    p = VesselParams(**CELL_BOWL)
    lo, hi = p.pattern_z_range()
    polys = cells.cell_polygons(p.cell_count, p.pattern_span_mm(), lo, hi,
                               p.strut_mm, p.cell_seed)
    fraction = cells.open_fraction(polys, p.pattern_span_mm(), lo, hi)
    assert 0.25 < fraction < 0.85, "%.0f%% open is not a web" % (100 * fraction)


# ---------------------------------------------------------------------------
# the inset
# ---------------------------------------------------------------------------


def test_the_inset_is_a_true_offset_and_not_a_scaling():
    """
    Scaling a cell about its centroid is the easy version and it is wrong: a
    long thin cell loses far more width than length, so the struts around it
    come out uneven and the thin ones drop below the nozzle. This checks a
    deliberately elongated cell keeps its offset on the SHORT axis.
    """
    long_cell = np.array([[0.0, 0.0], [60.0, 0.0], [60.0, 8.0], [0.0, 8.0]])
    inset = cells.inset_convex(long_cell, 2.0)
    assert inset is not None
    width = inset[:, 1].max() - inset[:, 1].min()
    length = inset[:, 0].max() - inset[:, 0].min()
    assert width == pytest.approx(8.0 - 4.0, abs=1e-6), "short axis not offset by 2 mm"
    assert length == pytest.approx(60.0 - 4.0, abs=1e-6), "long axis not offset by 2 mm"


def test_a_cell_smaller_than_its_struts_disappears_rather_than_inverting():
    tiny = np.array([[0.0, 0.0], [2.0, 0.0], [2.0, 2.0], [0.0, 2.0]])
    assert cells.inset_convex(tiny, 5.0) is None


# ---------------------------------------------------------------------------
# refusals
# ---------------------------------------------------------------------------


def test_a_strut_thinner_than_two_extrusions_is_refused():
    with pytest.raises(ValueError) as exc:
        VesselParams(**{**CELL_BOWL, "strut_mm": 0.5})
    assert "two extrusions" in str(exc.value)


def test_too_many_cells_for_the_strut_is_refused():
    """Otherwise the web closes into a solid wall with dimples in it."""
    with pytest.raises(ValueError) as exc:
        VesselParams(**{**CELL_BOWL, "cell_count": 600, "strut_mm": 6.0})
    assert "close them up" in str(exc.value)


def test_bands_that_leave_no_wall_are_refused():
    with pytest.raises(ValueError) as exc:
        VesselParams(**{**CELL_BOWL, "rim_band_mm": 40.0, "base_band_mm": 40.0})
    assert "less than two struts" in str(exc.value)


def test_the_strut_is_recorded_so_the_nozzle_check_sees_it():
    from bpcad.build.templates.vessel import build
    from bpcad.spec.schema import PartSpec

    p = VesselParams(**CELL_BOWL)
    spec = PartSpec(name="x", level=1, material="petg", nozzle_mm=0.4,
                    layer_mm=0.24, template="vessel", params=dict(CELL_BOWL))
    assert build(p, spec).features["cell strut"] == p.strut_mm


def test_solid_is_still_the_default():
    assert VesselParams().pattern == "solid"


def test_a_pattern_that_will_not_cut_is_reverted_with_advice():
    """
    Each cell is cut on the surface's tangent plane, which stops following a
    strongly curved wall once the cell gets large. Measured on a fitted wobbly
    vase: 90 cells fails, 160 and 220 cut cleanly - so the fix is MORE cells,
    which is the opposite of the intuition. A revert that does not say that is
    a dead end.

    What must never happen is a corrupted part: the wall goes back to solid and
    the build carries on.
    """
    from bpcad.build.templates.vessel import VesselParams, build_core

    p = VesselParams(
        profile="custom", pattern="cells", cell_count=90, strut_mm=3.0,
        wall_mm=3.0, rim_band_mm=8.0, base_band_mm=8.0,
        outer_dia_mm=87.8, height_mm=150.0,
        profile_points=[(35.4, 0.0), (39.2, 12.6), (41.6, 25.3), (41.5, 37.9),
                        (42.2, 50.5), (43.2, 63.2), (42.0, 75.8), (38.5, 88.4),
                        (32.7, 101.1), (29.1, 116.9), (32.1, 129.5), (35.4, 148.4)],
    )
    log = BuildLog()
    solid = build_core(p, log)

    assert len(solid.val().Solids()) == 1, "a failed pattern corrupted the part"
    assert probe(solid)

    reverted = [n for n in log.notes if "reverted" in n]
    if reverted:
        assert "Try MORE cells" in reverted[0], "the revert gives no way forward"


def test_more_cells_succeed_where_fewer_failed():
    from bpcad.build.templates.vessel import VesselParams, build_core

    points = [(35.4, 0.0), (39.2, 12.6), (41.6, 25.3), (41.5, 37.9),
              (42.2, 50.5), (43.2, 63.2), (42.0, 75.8), (38.5, 88.4),
              (32.7, 101.1), (29.1, 116.9), (32.1, 129.5), (35.4, 148.4)]
    common = dict(profile="custom", pattern="cells", wall_mm=3.0, rim_band_mm=8.0,
                  base_band_mm=8.0, outer_dia_mm=87.8, height_mm=150.0,
                  profile_points=points)

    log = BuildLog()
    many = build_core(VesselParams(**common, cell_count=200, strut_mm=2.2), log)
    assert any("cells cut" in n for n in log.notes), (
        "200 cells did not cut either - the tangent-plane limit is not about "
        "cell size after all, and the advice in the revert note is wrong"
    )
    assert len(many.val().Solids()) == 1
