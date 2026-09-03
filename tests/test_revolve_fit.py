"""
Reading a turned profile back out of a mesh.

This is the half that makes a mesh generator worth attaching to a CAD tool: a
mesh has no wall thickness you can change and no rim you can retype, and this
recovers a spec from one. It only works for surfaces of revolution, so most of
this file is about it saying so honestly when the shape is not one.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
import trimesh

from bpcad import api
from bpcad.measure.revolve import fit_revolve, to_vessel_params


def turned_mesh(profile, height=120.0, sections=64, wall=3.0):
    """A hollow turned shape built WITHOUT the vessel template, as a mesh."""
    import cadquery as cq

    from bpcad.verify.fit import mesh_of_solid

    def loft(fn, z0=0.0):
        wp, last = cq.Workplane("XY"), 0.0
        for i in range(sections + 1):
            z = z0 + (height - z0) * i / sections
            wp = wp.workplane(offset=z - last).circle(max(fn(z), 1.0))
            last = z
        return wp.loft(ruled=True, clean=False)

    solid = loft(profile).cut(loft(lambda z: profile(z) - wall, 4.0))
    return mesh_of_solid(solid)


WOBBLY = lambda z: 26 + 12 * math.sin(z / 120.0 * 2.6 + 0.4) + 4 * math.sin(z / 120.0 * 7.1)


# ---------------------------------------------------------------------------
# it has to refuse what it cannot do
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("stl,what", [
    ("parts/birdhouse/out/birdhouse.stl", "a rectangular box"),
    ("parts/vent/out/vent_louvre.stl", "a rectangular vent"),
    ("parts/keyring/out/loop_keyring.stl", "a flat keyring"),
])
def test_a_shape_that_is_not_turned_is_refused(stl, what):
    """
    THE PROMISE. A bowl fitted out of a box is worse than no answer, because it
    looks like an answer - and the first version of the roundness test gave
    exactly that. It measured the spread of the outermost band of radii, which
    on a SQUARE section is only the four corners, whose radii barely differ.
    The birdhouse scored 0.015 and came back as a 314 mm bowl. Roundness is now
    measured by angle around the axis, where a square runs about 0.3.
    """
    from pathlib import Path

    if not Path(stl).is_file():
        pytest.skip("%s has not been built" % stl)
    fit = fit_revolve(trimesh.load(stl))
    assert not fit.ok, "%s was accepted as a turned shape" % what
    assert "not a turned shape" in fit.summary()[0]


def test_a_turned_shape_is_accepted():
    fit = fit_revolve(turned_mesh(WOBBLY))
    assert fit.ok, fit.reasons
    assert fit.roundness < 0.01


# ---------------------------------------------------------------------------
# the measurements have to be right
# ---------------------------------------------------------------------------


def test_the_fitted_size_matches_the_mesh():
    mesh = turned_mesh(WOBBLY)
    fit = fit_revolve(mesh)
    box = mesh.bounds[1] - mesh.bounds[0]
    assert fit.height_mm == pytest.approx(box[2], rel=0.02)
    assert fit.outer_dia_mm == pytest.approx(max(box[0], box[1]), rel=0.03)


def test_the_wall_is_measured_not_assumed():
    fit = fit_revolve(turned_mesh(WOBBLY, wall=3.0))
    assert fit.wall_mm is not None, "the wall came back unmeasurable on a hollow vessel"
    assert fit.wall_mm == pytest.approx(3.0, abs=0.6)


def test_a_solid_shape_reports_no_wall_rather_than_inventing_one():
    """bpcad does not substitute a plausible number. See rule 29."""
    import cadquery as cq

    from bpcad.verify.fit import mesh_of_solid

    cone = cq.Workplane("XY").circle(30).workplane(offset=80).circle(18).loft(ruled=True)
    fit = fit_revolve(mesh_of_solid(cone))
    assert fit.ok
    assert fit.wall_mm is None
    assert "not measurable" in " ".join(fit.summary())


# ---------------------------------------------------------------------------
# and it has to come back as a real, editable part
# ---------------------------------------------------------------------------


def test_a_mesh_becomes_a_spec_that_rebuilds_to_the_same_object():
    mesh = turned_mesh(WOBBLY)
    fit = fit_revolve(mesh)
    params = to_vessel_params(fit)

    spec = api.validate_spec({
        "name": "fitted", "level": 1, "material": "petg", "nozzle_mm": 0.4,
        "layer_mm": 0.24, "template": "vessel", "params": params,
    })
    result = api.build(spec=spec, out_dir="/tmp/bpcad_fit_test", render=False)
    rebuilt = result.report.mesh

    assert rebuilt.body_count == 1
    assert rebuilt.watertight
    assert rebuilt.volume_cm3 == pytest.approx(mesh.volume / 1000.0, rel=0.08), (
        "rebuilt %.1f cm3 against a %.1f cm3 mesh" % (rebuilt.volume_cm3, mesh.volume / 1000)
    )


def test_the_fitted_part_is_then_editable_which_is_the_whole_point():
    """
    A mesh cannot be made 200 mm tall. A spec can. This nearly shipped broken:
    with a custom profile the points carried the height, so height_mm was
    accepted, stored, and silently ignored - a fitted vase asked to be 200 mm
    tall came back 147. A parameter that does nothing is worse than one that
    is missing.
    """
    fit = fit_revolve(turned_mesh(WOBBLY))
    params = to_vessel_params(fit)

    for field, value in (("height_mm", 200.0), ("outer_dia_mm", 120.0)):
        changed = dict(params)
        changed[field] = value
        spec = api.validate_spec({
            "name": "e", "level": 1, "material": "petg", "nozzle_mm": 0.4,
            "layer_mm": 0.24, "template": "vessel", "params": changed,
        })
        built = api.build(spec=spec, out_dir="/tmp/bpcad_fit_edit", render=False)
        box = built.report.mesh.bbox_mm
        got = box[2] if field == "height_mm" else max(box[0], box[1])
        assert got == pytest.approx(value, rel=0.03), (
            "asked for %s=%s and got %.1f" % (field, value, got)
        )


def test_the_profile_must_climb():
    from bpcad.build.templates.vessel import VesselParams

    with pytest.raises(ValueError) as exc:
        VesselParams(profile="custom", profile_points=[(20, 0), (25, 10), (22, 5)])
    assert "climb" in str(exc.value)


def test_points_on_a_named_profile_are_refused_rather_than_ignored():
    from bpcad.build.templates.vessel import VesselParams

    with pytest.raises(ValueError) as exc:
        VesselParams(profile="flared", profile_points=[(10, 0), (12, 5), (14, 9)])
    assert "silently ignored" in str(exc.value)
