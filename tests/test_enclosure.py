"""
The enclosure template.

It exists because of a specific failure: asked for a birdhouse with only a
keyring and a vent available, the pipeline composed primitives one at a time and
produced a 96%-solid block. Correct on the outside, 2.1 kg of filament, and
useless as a birdhouse - because nothing in the system knew that a birdhouse is
a container and a container is hollow.

These tests pin down the knowledge the template carries, so it cannot quietly
be lost.
"""

import math

import pytest
from pydantic import ValidationError

from bpcad import api
from bpcad.build.templates.enclosure import EnclosureParams, build, derive
from bpcad.spec.schema import PartSpec, format_validation_error


def spec(**params) -> PartSpec:
    return PartSpec(
        name="box", level=1, material="petg", nozzle_mm=0.4, layer_mm=0.24,
        template="enclosure", params=params,
    )


# -- the point of the whole thing -------------------------------------------


def test_it_is_hollow_without_being_asked():
    """
    The failure this template exists to prevent. A birdhouse is a container,
    and a container that comes out solid is not a birdhouse.
    """
    result = build(EnclosureParams(), spec())
    box_cm3 = (120 * 100 * 160) / 1000.0
    assert result.solid.val().Volume() / 1000.0 < box_cm3 * 0.25


def test_a_plain_request_builds_a_printable_birdhouse(tmp_path):
    part = api.build(spec=spec(), out_dir=tmp_path)
    m = part.report.mesh
    assert m.watertight
    assert m.body_count == 2, "the box and its roof"
    assert m.solidity < 0.15
    assert not m.warnings, "a hollow part must not trip the bulk warning"


def test_the_cavity_opens_upward():
    """
    A box hollowed downward has a ceiling over its whole footprint, needing
    support inside a cavity nobody can reach to clean it out of.
    """
    result = build(EnclosureParams(roof=False), spec(roof=False))
    solid = result.print_solid
    bb = solid.val().BoundingBox()
    # A slice near the top is mostly air; a slice near the floor is not.
    import cadquery as cq

    def area_at(z):
        plate = cq.Workplane("XY").box(400, 400, 0.4, centered=(True, True, False))
        cut = solid.intersect(plate.translate((0, 0, z)))
        return cut.val().Volume() / 0.4

    assert area_at(bb.zmax - 6) < area_at(bb.zmin + 1) * 0.6


def test_the_roof_prints_flat():
    """
    A pitched roof modelled in place is an overhang across its entire area.
    In print orientation the roof must lie flat, whatever its pitch.
    """
    p = EnclosureParams(roof_pitch_deg=30.0)
    result = build(p, spec(roof_pitch_deg=30.0))
    bb = result.print_solid.val().BoundingBox()
    assert bb.zlen == pytest.approx(p.height_mm, abs=1.0), (
        "nothing may stand taller than the box - the roof is lying down"
    )


def test_the_assembled_view_does_pitch_the_roof():
    p = EnclosureParams(roof_pitch_deg=30.0)
    result = build(p, spec(roof_pitch_deg=30.0))
    bb = result.solid.val().BoundingBox()
    assert bb.zlen > p.height_mm + 5, "assembled, the roof sits on top at an angle"


def test_print_and_assembled_are_genuinely_different():
    """
    Never derive one from the other by rotation. There is no single rotation
    that puts a flat roof and an upright box where each needs to be.
    """
    result = build(EnclosureParams(), spec())
    assert result.solid is not result.print_solid
    a = result.solid.val().BoundingBox()
    b = result.print_solid.val().BoundingBox()
    assert (a.xlen, a.zlen) != (b.xlen, b.zlen)


def test_it_has_drainage():
    """A birdhouse without drainage holds water and rots."""
    with_holes = build(EnclosureParams(), spec()).solid.val().Volume()
    without = build(EnclosureParams(drain_holes=0), spec(drain_holes=0)).solid.val().Volume()
    assert with_holes < without


def test_the_entrance_goes_all_the_way_through():
    solid = build(EnclosureParams(), spec()).solid
    plain = build(EnclosureParams(entrance_dia_mm=0), spec(entrance_dia_mm=0)).solid
    assert solid.val().Volume() < plain.val().Volume()


def test_the_entrance_is_placed_out_of_a_cats_reach():
    """
    Not stated, so it goes in the upper third: high enough that a cat reaching
    in cannot get to chicks on the floor, low enough that the bird can.
    """
    p = EnclosureParams()
    assert p.entrance_z_mm > p.height_mm * 0.6
    assert p.entrance_z_mm < p.height_mm * 0.85


def test_an_unstated_entrance_height_is_declared_an_assumption():
    """Measure, never estimate. A chosen number is reported as chosen."""
    result = build(EnclosureParams(), spec())
    names = [a.name for a in result.assumptions]
    assert "entrance_height_mm" in names
    assert "cat" in result.assumptions[0].why


def test_a_stated_entrance_height_is_not_an_assumption():
    result = build(EnclosureParams(entrance_height_mm=100.0), spec(entrance_height_mm=100.0))
    assert not result.assumptions


# -- refusing what cannot be built ------------------------------------------


def test_walls_thicker_than_the_box_are_refused():
    with pytest.raises(ValidationError) as exc:
        EnclosureParams(width_mm=40.0, wall_mm=19.0)
    assert "leaves a cavity" in format_validation_error(exc.value)


def test_an_entrance_wider_than_the_wall_is_refused():
    with pytest.raises(ValidationError) as exc:
        EnclosureParams(width_mm=60.0, entrance_dia_mm=58.0)
    assert "corners" in format_validation_error(exc.value)


def test_an_entrance_that_breaks_through_the_top_is_refused():
    with pytest.raises(ValidationError) as exc:
        EnclosureParams(height_mm=100.0, entrance_dia_mm=32.0, entrance_height_mm=95.0)
    assert "through the top" in format_validation_error(exc.value)


def test_an_unknown_face_is_refused_and_lists_the_real_ones():
    with pytest.raises(ValidationError) as exc:
        EnclosureParams(entrance_face="roof")
    msg = format_validation_error(exc.value)
    assert "front, back, left, right" in msg


@pytest.mark.parametrize("face", ["front", "back", "left", "right"])
def test_every_face_can_take_the_entrance(face):
    result = build(EnclosureParams(entrance_face=face), spec(entrance_face=face))
    assert result.solid.val().Volume() > 0


# -- the family, not one object ---------------------------------------------


@pytest.mark.parametrize(
    "label,params",
    [
        ("blue tit box", {"width_mm": 110.0, "height_mm": 150.0, "entrance_dia_mm": 25.0}),
        ("storage box", {"entrance_dia_mm": 0.0, "roof": False, "drain_holes": 0}),
        ("planter", {"height_mm": 90.0, "entrance_dia_mm": 0.0, "roof": False,
                     "drain_holes": 4}),
        ("big nest box", {"width_mm": 200.0, "depth_mm": 180.0, "height_mm": 260.0,
                          "entrance_dia_mm": 45.0}),
        ("flat roof", {"roof_pitch_deg": 0.0}),
    ],
)
def test_the_template_covers_a_family(label, params, tmp_path):
    part = api.build(spec=spec(**params), out_dir=tmp_path / label.replace(" ", "_"))
    assert part.report.mesh.watertight, label
    assert part.report.mesh.solidity < 0.4, label


def test_the_catalogue_describes_what_it_is_for():
    """
    A model picks a template from this line. If it does not say "birdhouse",
    a birdhouse request will not find it.
    """
    info = api.template_info("enclosure")
    summary = info["summary"].lower()
    for word in ("hollow", "birdhouse", "box"):
        assert word in summary


def test_every_parameter_is_documented():
    for p in api.template_info("enclosure")["params"]:
        assert p["description"], p["name"]


def test_the_template_reports_its_nominal_size():
    """
    Neither bounding box answers "how big is it". The print layout is 288 mm
    wide because the roof lies beside the box; the assembled envelope is 160
    because the roof overhangs. The birdhouse is 120. Only the template knows.
    """
    p = EnclosureParams(width_mm=120.0, depth_mm=100.0, height_mm=140.0)
    result = build(p, spec(width_mm=120.0, depth_mm=100.0, height_mm=140.0))

    assert result.nominal_mm == (120.0, 100.0, 140.0)

    printed = result.print_solid.val().BoundingBox()
    assembled = result.solid.val().BoundingBox()
    assert printed.xlen > 250, "the print layout is the bed, not the part"
    assert assembled.xlen > 140, "the assembled envelope includes the roof overhang"


def test_the_intent_check_uses_the_nominal_size(tmp_path):
    """
    Checking the print layout rejected a correct birdhouse for not being 100 mm
    deep when it was.
    """
    from bpcad.agent.loop import compile_and_verify

    s = spec(width_mm=120.0, depth_mm=100.0, height_mm=140.0)
    request = "a birdhouse, 120 mm wide, 140 mm tall, 100 mm deep"
    result, report, stl = compile_and_verify(
        s, api.config(), None, tmp_path / "out", request=request
    )
    assert report.intent.ok
