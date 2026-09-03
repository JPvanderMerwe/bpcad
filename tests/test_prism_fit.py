"""
Reading an extruded profile back out of a mesh.

A template can only make what it was written to make; a fitter has no such
ceiling. This is the second of two - `revolve` handles turned shapes, this
handles extruded ones - and between them they cover most of what people print.

Most of this file is about the fitter REFUSING things, because a bracket fitted
out of a teapot looks like an answer and is worse than no answer.
"""

from __future__ import annotations

import math

import pytest
import trimesh

from bpcad import api
from bpcad.measure.prism import fit_prism, simplify, to_dsl_ops
from bpcad.verify.fit import mesh_of_solid


def solid_mesh(builder):
    import cadquery as cq

    return mesh_of_solid(builder(cq))


PLATE = lambda cq: (cq.Workplane("XY").rect(90, 50).extrude(6).faces(">Z")
                    .workplane().pushPoints([(-30, 0), (0, 0), (30, 0)]).hole(8))
POCKETED = lambda cq: (cq.Workplane("XY").rect(80, 60).extrude(10).faces(">Z")
                       .workplane().rect(50, 30).cutBlind(-3))
HOOK = lambda cq: (cq.Workplane("XY").moveTo(0, 0).lineTo(40, 0).lineTo(40, 10)
                   .lineTo(12, 10).lineTo(12, 45).lineTo(0, 45).close().extrude(8))
CONE = lambda cq: cq.Workplane("XY").circle(30).workplane(offset=60).circle(6).loft()


def rebuild(fit, name):
    spec = api.validate_spec({
        "name": name, "level": 2, "material": "petg",
        "nozzle_mm": 0.4, "layer_mm": 0.24, "ops": to_dsl_ops(fit),
    })
    return api.build(spec=spec, out_dir="/tmp/bpcad_prism_test_" + name, render=False)


# ---------------------------------------------------------------------------
# refusing what it cannot do
# ---------------------------------------------------------------------------


def test_a_turned_shape_is_not_an_extrusion():
    fit = fit_prism(solid_mesh(CONE))
    assert not fit.ok
    assert "cross-section changes" in fit.summary()[0]


def test_a_multi_body_mesh_is_refused_rather_than_misread():
    """
    A print layout has the lid lying beside the box. Sectioning that gives two
    outer outlines, and the smaller one would be read as a HOLE in the larger -
    a confident wrong answer about a part that is simply two parts.
    """
    from pathlib import Path

    stl = Path("parts/birdhouse/out/birdhouse.stl")
    if not stl.is_file():
        pytest.skip("the birdhouse has not been built")
    fit = fit_prism(trimesh.load(stl))
    assert not fit.ok
    assert "separate bodies" in fit.summary()[0]


def test_making_a_spec_from_a_refused_shape_raises():
    with pytest.raises(ValueError):
        to_dsl_ops(fit_prism(solid_mesh(CONE)))


# ---------------------------------------------------------------------------
# fitting what it can
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("builder,name", [(PLATE, "plate"), (HOOK, "hook"),
                                          (POCKETED, "pocketed")])
def test_an_extrusion_rebuilds_to_the_same_object(builder, name):
    mesh = solid_mesh(builder)
    fit = fit_prism(mesh)
    assert fit.ok, fit.reasons

    built = rebuild(fit, name)
    rebuilt = built.report.mesh
    assert rebuilt.body_count == 1
    assert rebuilt.watertight
    assert rebuilt.volume_cm3 == pytest.approx(mesh.volume / 1000.0, rel=0.05), (
        "%s rebuilt %.2f cm3 against a %.2f cm3 mesh"
        % (name, rebuilt.volume_cm3, mesh.volume / 1000)
    )
    for measured, actual in zip(rebuilt.bbox_mm, mesh.bounds[1] - mesh.bounds[0]):
        assert measured == pytest.approx(float(actual), rel=0.02)


def test_round_holes_are_found_where_they_actually_are():
    fit = fit_prism(solid_mesh(PLATE))
    assert fit.ok
    round_cuts = [c for c in fit.cutouts if c["round"]]
    assert len(round_cuts) == 3, "found %d round holes, not 3" % len(round_cuts)
    for cut in round_cuts:
        assert cut["diameter_mm"] == pytest.approx(8.0, abs=0.3)
        assert cut["through"], "a through hole was read as a pocket"
    centres = sorted(round(c["x_mm"]) for c in round_cuts)
    assert centres == [-30, 0, 30]


def test_a_pocket_keeps_its_depth_instead_of_going_through():
    """
    Cutting a 3 mm pocket all the way through a 10 mm plate is not a small
    error, it is a hole where there should be a recess. The first version
    assumed everything went through and the keyring rebuilt 32.75% heavy.
    """
    fit = fit_prism(solid_mesh(POCKETED))
    assert fit.ok
    pockets = [c for c in fit.cutouts if not c["through"]]
    assert pockets, "the pocket was read as a through hole"
    assert pockets[0]["depth_mm"] == pytest.approx(3.0, abs=1.2)


def test_a_shaped_cutout_is_kept_rather_than_discarded():
    """
    Only keeping ROUND inner loops meant every shaped pocket was filled in
    solid. The DSL has profile_extrude; a shaped cut-out is one, in cut mode.
    """
    fit = fit_prism(solid_mesh(POCKETED))
    shaped = [c for c in fit.cutouts if not c["round"]]
    assert shaped, "the rectangular pocket was thrown away"
    assert len(shaped[0]["points"]) >= 4


def test_a_fitted_part_is_then_editable():
    """The whole point. A mesh cannot be made 14 mm thick; a spec can."""
    fit = fit_prism(solid_mesh(PLATE))
    ops = to_dsl_ops(fit)
    ops[0]["height_mm"] = 14.0
    for op in ops[1:]:
        op["height_mm"] = 18.0
        op["z_mm"] = -2.0

    spec = api.validate_spec({"name": "thicker", "level": 2, "material": "petg",
                              "nozzle_mm": 0.4, "layer_mm": 0.24, "ops": ops})
    built = api.build(spec=spec, out_dir="/tmp/bpcad_prism_edit", render=False)
    assert built.report.mesh.bbox_mm[2] == pytest.approx(14.0, rel=0.02)
    assert built.report.mesh.body_count == 1


# ---------------------------------------------------------------------------
# the pieces
# ---------------------------------------------------------------------------


def test_simplify_keeps_the_corners_and_drops_the_rest():
    import numpy as np

    # A square walked at one-millimetre steps: four corners matter, the 396
    # points between them do not.
    side = np.linspace(0, 100, 100)
    loop = np.vstack([
        np.column_stack([side, np.zeros_like(side)]),
        np.column_stack([np.full_like(side, 100), side]),
        np.column_stack([side[::-1], np.full_like(side, 100)]),
        np.column_stack([np.zeros_like(side), side[::-1]]),
    ])
    out = simplify(loop, 0.5)
    assert 4 <= len(out) <= 8, "simplified to %d points" % len(out)


def test_the_outline_residual_reports_what_simplifying_cost():
    fit = fit_prism(solid_mesh(HOOK))
    assert fit.ok
    # Straight edges simplify exactly; this must not quietly report a big loss.
    assert fit.residual_mm < 0.2, "residual %.3f mm on a shape of flat faces" % fit.residual_mm
