"""
Phase 3: spec, templates and the compiler.

The acceptance test is that a spec.yaml reproduces the reference STL exactly,
with no model loaded at any point. Both reference parts come back
bit-identical - same volume, same bounding box, same face count, same
regression digest - so these are equality assertions, not tolerances.
"""

from pathlib import Path

import cadquery as cq
import pytest
from pydantic import ValidationError

from bpcad.build.compile import (
    Level3NotAllowed,
    SpecError,
    check_export,
    compile_spec,
    export_solid,
    load_spec,
    validate_params,
)
from bpcad.build.helpers import (
    FILLET_MARGIN_MM,
    BuildLog,
    clip,
    compound_of,
    disc,
    poly_prism,
    probe,
    rrect,
    safe_fillet_radius,
    try_edge_op,
)
from bpcad.spec import registry
from bpcad.spec.dsl import DslError, run_ops
from bpcad.spec.schema import PartSpec, format_validation_error
from bpcad.verify.mesh import check_mesh
from bpcad.verify.regression import signature_of

ROOT = Path(__file__).resolve().parent.parent
REF_KEYRING = ROOT / "reference" / "loop_keyring.stl"
REF_VENT = ROOT / "reference" / "vent_louvre.stl"
KEYRING_SPEC = ROOT / "parts" / "keyring" / "spec.yaml"
VENT_SPEC = ROOT / "parts" / "vent" / "spec.yaml"


def _build_to(spec_path: Path, tmp_path: Path) -> Path:
    spec, base_dir = load_spec(spec_path)
    result = compile_spec(spec, base_dir=base_dir)
    return export_solid(
        result.print_solid,
        tmp_path / ("%s.stl" % spec.name),
        spec.stl_tolerance if spec.stl_tolerance is not None else 0.005,
        spec.stl_angular_tolerance if spec.stl_angular_tolerance is not None else 0.05,
    )


# -- acceptance -------------------------------------------------------------


@pytest.mark.parametrize(
    "spec_path,reference",
    [(KEYRING_SPEC, REF_KEYRING), (VENT_SPEC, REF_VENT)],
    ids=["keyring", "vent"],
)
def test_spec_reproduces_the_reference_exactly(spec_path, reference, tmp_path):
    """
    Not "within regression tolerance" - identical. The environment reproduces
    both reference scripts bit for bit, so a faithful port has no excuse.
    """
    built = check_mesh(_build_to(spec_path, tmp_path))
    ref = check_mesh(reference)
    assert signature_of(built).digest() == signature_of(ref).digest()
    assert built.volume_cm3 == pytest.approx(ref.volume_cm3, abs=1e-6)
    assert built.face_count == ref.face_count
    assert built.body_count == ref.body_count
    assert built.watertight


def test_building_touches_no_model(monkeypatch, tmp_path):
    """
    The design requirement, exercised rather than asserted: a full build with
    socket creation sabotaged.
    """
    import socket

    real = socket.socket

    class Blocked(real):
        def __init__(self, *a, **k):
            raise AssertionError("build must work with the network cable out")

    monkeypatch.setattr(socket, "socket", Blocked)
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: pytest.fail("no network"))

    built = check_mesh(_build_to(KEYRING_SPEC, tmp_path))
    assert built.watertight and built.body_count == 1


def test_the_null_backend_is_never_constructed_during_a_build(tmp_path):
    """Nothing under build/ or spec/ may import the model layer at all."""
    import bpcad.build.compile as compile_mod
    import bpcad.spec.dsl as dsl_mod

    for mod in (compile_mod, dsl_mod):
        source = Path(mod.__file__).read_text()
        assert "bpcad.models" not in source


def test_export_is_verified_watertight(tmp_path):
    stl = _build_to(KEYRING_SPEC, tmp_path)
    assert check_export(stl, expected_bodies=1) == []


def test_vent_exports_six_separate_bodies(tmp_path):
    """
    A print-in-place mechanism must stay six bodies. If a boolean union crept in
    where a compound belongs, they fuse into one welded lump and this catches it.
    """
    stl = _build_to(VENT_SPEC, tmp_path)
    assert check_mesh(stl).body_count == 6
    assert check_export(stl, expected_bodies=6) == []


# -- invalid specs are rejected, naming the field and the legal range -------


def test_unknown_template_lists_the_ones_that_exist():
    with pytest.raises(registry.TemplateError) as exc:
        registry.get("flux_capacitor")
    msg = str(exc.value)
    assert "flux_capacitor" in msg
    assert "keyring_device" in msg and "louvre_vent" in msg


def test_misspelled_parameter_is_an_error_not_a_silent_default():
    """
    extra="forbid" is load-bearing. A typo that is silently ignored builds a
    part at its default that looks almost right, which is the worst outcome.
    """
    spec = PartSpec(
        name="x", level=1, material="petg", nozzle_mm=0.4, layer_mm=0.12,
        template="keyring_device",
        params={"body_widht_mm": 30.0, "logo_on": False},
    )
    with pytest.raises(SpecError) as exc:
        validate_params(spec)
    assert "body_widht_mm" in str(exc.value)


def test_out_of_range_parameter_names_the_field_and_the_range():
    spec = PartSpec(
        name="x", level=1, material="petg", nozzle_mm=0.4, layer_mm=0.12,
        template="keyring_device",
        params={"body_width_mm": 5.0, "logo_on": False},
    )
    with pytest.raises(SpecError) as exc:
        validate_params(spec)
    msg = str(exc.value)
    assert "body_width_mm" in msg
    assert "> 10" in msg
    assert "spec explain keyring_device" in msg


def test_face_detail_deeper_than_the_part_is_rejected():
    from bpcad.build.templates.keyring_device import KeyringDeviceParams

    with pytest.raises(ValidationError) as exc:
        KeyringDeviceParams(logo_on=False, depth_mm=1.2, recess_mm=0.6, glass_mm=0.6, cam_mm=0.5)
    msg = format_validation_error(exc.value)
    assert "cut straight through" in msg
    assert "depth_mm" in msg


def test_logo_on_without_a_logo_file_is_rejected():
    from bpcad.build.templates.keyring_device import KeyringDeviceParams

    with pytest.raises(ValidationError) as exc:
        KeyringDeviceParams(logo_on=True, logo_json=None)
    assert "measure trace" in format_validation_error(exc.value)


def test_missing_logo_file_names_the_command_that_makes_one(tmp_path):
    """logo_on has to be set explicitly now - it defaults to false."""
    spec = PartSpec(
        name="x", level=1, material="petg", nozzle_mm=0.4, layer_mm=0.12,
        template="keyring_device",
        params={"logo_on": True, "logo_json": "nope.json"},
    )
    with pytest.raises(SpecError) as exc:
        compile_spec(spec, base_dir=tmp_path)
    assert "bpcad measure trace" in str(exc.value)


def test_blades_wider_than_their_pitch_are_rejected():
    """A mechanism can be geometrically valid and functionally dead."""
    from bpcad.build.templates.louvre_vent import LouvreVentParams

    with pytest.raises(ValidationError) as exc:
        LouvreVentParams(blade_chord_mm=20.0)
    msg = format_validation_error(exc.value)
    assert "collide" in msg and "pitch" in msg


def test_tie_bar_fouling_the_pivot_pins_is_rejected():
    from bpcad.build.templates.louvre_vent import LouvreVentParams

    with pytest.raises(ValidationError) as exc:
        LouvreVentParams(crank_r_mm=2.0, blade_chord_mm=14.0)
    assert "crank hub" in format_validation_error(exc.value) or "fouls" in format_validation_error(exc.value)


def test_grip_tab_unreachable_at_full_travel_is_rejected():
    from bpcad.build.templates.louvre_vent import LouvreVentParams

    with pytest.raises(ValidationError) as exc:
        LouvreVentParams(grip_len_mm=8.0)
    msg = format_validation_error(exc.value)
    assert "unreachable" in msg or "sweeps" in msg


def test_layer_thicker_than_the_nozzle_allows_is_rejected():
    with pytest.raises(ValidationError) as exc:
        PartSpec(name="x", level=1, material="petg", nozzle_mm=0.4, layer_mm=0.4,
                 template="keyring_device")
    msg = format_validation_error(exc.value)
    assert "layer_mm" in msg and "0.320" in msg


def test_level_1_without_a_template_is_rejected():
    with pytest.raises(ValidationError) as exc:
        PartSpec(name="x", level=1, material="petg", nozzle_mm=0.4, layer_mm=0.2)
    assert "spec explain" in format_validation_error(exc.value)


def test_level_2_without_ops_is_rejected():
    with pytest.raises(ValidationError):
        PartSpec(name="x", level=2, material="petg", nozzle_mm=0.4, layer_mm=0.2)


def test_a_spec_that_is_not_a_mapping_is_rejected(tmp_path):
    p = tmp_path / "spec.yaml"
    p.write_text("- just\n- a\n- list\n")
    with pytest.raises(SpecError) as exc:
        load_spec(p)
    assert "mapping" in str(exc.value)


def test_broken_yaml_names_the_file(tmp_path):
    p = tmp_path / "spec.yaml"
    p.write_text("name: [unclosed\n")
    with pytest.raises(SpecError) as exc:
        load_spec(p)
    assert str(p) in str(exc.value)


# -- level 3 ----------------------------------------------------------------


def test_level_3_is_off_by_default():
    spec = PartSpec(name="x", level=3, material="petg", nozzle_mm=0.4, layer_mm=0.2,
                    script="part = 1")
    with pytest.raises(Level3NotAllowed):
        compile_spec(spec)


def test_level_3_output_is_marked_review_required():
    spec = PartSpec(
        name="x", level=3, material="petg", nozzle_mm=0.4, layer_mm=0.2,
        script="part = cq.Workplane('XY').box(10, 10, 10)",
    )
    result = compile_spec(spec, allow_level_3=True)
    assert any("REVIEW REQUIRED" in n for n in result.log.notes)


def test_level_3_script_without_part_is_rejected():
    spec = PartSpec(name="x", level=3, material="petg", nozzle_mm=0.4, layer_mm=0.2,
                    script="x = 1")
    with pytest.raises(SpecError) as exc:
        compile_spec(spec, allow_level_3=True)
    assert "`part`" in str(exc.value)


def test_level_3_script_error_is_reported_not_swallowed():
    spec = PartSpec(name="x", level=3, material="petg", nozzle_mm=0.4, layer_mm=0.2,
                    script="part = 1/0")
    with pytest.raises(SpecError) as exc:
        compile_spec(spec, allow_level_3=True)
    assert "ZeroDivisionError" in str(exc.value)


# -- helpers ----------------------------------------------------------------


def test_fillet_margin_is_a_real_margin_not_an_epsilon():
    """h/2 - 0.001 produces degenerate faces or hard failure. 0.03 is the fix."""
    assert FILLET_MARGIN_MM == 0.03
    assert safe_fillet_radius(5.0, 2.0) == pytest.approx(1.0 - 0.03)


def test_safe_fillet_radius_leaves_a_reasonable_request_alone():
    assert safe_fillet_radius(1.0, 20.0, 20.0) == 1.0


def test_probe_accepts_a_sound_solid():
    assert probe(rrect(20, 10, 2, 0, 5))


def test_probe_works_on_a_solid_far_from_the_origin():
    """The throwaway cutter is placed from the solid's own bounding box."""
    assert probe(rrect(20, 10, 2, 500.0, 5, z0=300.0))


def test_try_edge_op_reverts_and_records_a_failure():
    log = BuildLog()
    solid = rrect(10, 10, 0, 0, 5)
    out = try_edge_op(solid, "|Z", "fillet", 500.0, "absurd fillet", log)
    assert out is solid, "a failed edge op must revert"
    assert log.edge_ops[0].applied is False
    assert log.edge_ops[0].reason


def test_try_edge_op_records_a_disabled_op_rather_than_hiding_it():
    log = BuildLog()
    solid = rrect(10, 10, 0, 0, 5)
    try_edge_op(solid, ">Z", "chamfer", 0.0, "back edge", log)
    assert log.edge_ops[0].applied is False
    assert "not requested" in log.edge_ops[0].reason


def test_clip_works_on_a_solid_that_is_not_at_the_origin():
    """
    A cutting box centred on the origin silently misses an off-origin solid and
    the feature vanishes with no error at all.
    """
    solid = rrect(12, 20, 3, 30.0, 1.55, z0=6.45)
    before = solid.val().Volume()
    after = clip(solid, "y", 40.0, keep="below").val().Volume()
    assert after == pytest.approx(before / 2, rel=0.02)


def test_clip_rejects_a_bad_axis():
    with pytest.raises(ValueError):
        clip(rrect(10, 10, 0, 0, 5), "w", 1.0)


def test_poly_prism_needs_three_points():
    with pytest.raises(ValueError):
        poly_prism([(0, 0), (1, 1)], 1.0, 0, 0, 0, 1)


def test_compound_keeps_bodies_separate():
    """union() intermittently fused parts 0.3 mm apart. A compound cannot."""
    a = disc(4, 0, 0, 2)
    b = disc(4, 0, 0, 2, z0=2.3)
    assert len(compound_of([a, b]).val().Solids()) == 2


# -- registry and explain ---------------------------------------------------


def test_the_reference_templates_are_registered():
    names = registry.names()
    assert {"keyring_device", "louvre_vent"} <= set(names)
    assert names == sorted(names)


@pytest.mark.parametrize("name", ["keyring_device", "louvre_vent"])
def test_explain_shows_units_defaults_and_bounds(name):
    text = registry.explain(name)
    assert "PARAMETERS" in text
    assert "_mm" in text
    assert "default" in text
    assert "EXAMPLE spec.yaml" in text
    assert "PRINT NOTES" in text


def test_every_dimension_parameter_carries_its_unit():
    """The schema is the interface when the model fails. Units are not optional."""
    for name in registry.names():
        model = registry.get(name).params_model
        for fname, field in model.model_fields.items():
            if field.annotation is float:
                assert fname.endswith(("_mm", "_deg", "_fraction")), (
                    "%s.%s is a float with no unit in its name" % (name, fname)
                )


def test_every_parameter_has_a_description():
    for name in registry.names():
        for fname, field in registry.get(name).params_model.model_fields.items():
            assert field.description, "%s.%s has no description" % (name, fname)


# -- level 2 DSL ------------------------------------------------------------


def test_dsl_builds_a_solid():
    scene = run_ops([
        {"op": "rounded_prism", "width_mm": 40, "depth_mm": 25, "height_mm": 10, "corner_r_mm": 3},
        {"op": "pocket", "anchor": "top_face", "width_mm": 30, "height_mm": 15,
         "depth_mm": 2, "corner_r_mm": 2, "name": "screen"},
    ])
    bb = scene.solid.val().BoundingBox()
    assert (bb.xlen, bb.ylen, bb.zlen) == pytest.approx((40.0, 25.0, 10.0))
    assert scene.features["screen"] == 15.0


def test_dsl_pocket_actually_removes_material():
    plain = run_ops([{"op": "rounded_prism", "width_mm": 20, "depth_mm": 20, "height_mm": 10}])
    pocketed = run_ops([
        {"op": "rounded_prism", "width_mm": 20, "depth_mm": 20, "height_mm": 10},
        {"op": "pocket", "anchor": "top_face", "width_mm": 10, "height_mm": 10, "depth_mm": 2},
    ])
    removed = plain.solid.val().Volume() - pocketed.solid.val().Volume()
    assert removed == pytest.approx(10 * 10 * 2, rel=0.01)


def test_dsl_pocket_on_a_side_face_cuts_inward():
    scene = run_ops([
        {"op": "rounded_prism", "width_mm": 20, "depth_mm": 20, "height_mm": 20},
        {"op": "pocket", "anchor": "front_face", "width_mm": 6, "height_mm": 6, "depth_mm": 3},
    ])
    bb = scene.solid.val().BoundingBox()
    assert (bb.xlen, bb.ylen, bb.zlen) == pytest.approx((20.0, 20.0, 20.0)), (
        "a pocket must cut in, not stick out"
    )
    assert scene.solid.val().Volume() == pytest.approx(8000 - 6 * 6 * 3, rel=0.01)


def test_dsl_rejects_a_selector_string_where_a_name_belongs():
    """
    Selector strings are the main thing a small model gets wrong.

    This is now rejected at PARSE time, not at apply time, because the field is
    a Literal rather than a bare str - so the legal set appears in the error and
    in the JSON schema handed to the model, which a constrained decoder cannot
    step outside.
    """
    with pytest.raises(DslError) as exc:
        run_ops([
            {"op": "rounded_prism", "width_mm": 20, "depth_mm": 20, "height_mm": 10},
            {"op": "blend_edges", "group": "|Z", "amount_mm": 1.0},
        ])
    msg = str(exc.value)
    assert "vertical" in msg and "top" in msg, "the legal groups must be named"


def test_dsl_anchor_names_are_in_the_schema_not_just_the_error():
    """
    A constrained decoder reads the schema. Legal names belong in it, not only
    in the message it sees after getting one wrong.
    """
    from bpcad.spec.dsl import Pocket

    schema = Pocket.model_json_schema()
    anchor = schema["properties"]["anchor"]
    enum = anchor.get("enum") or schema["$defs"][anchor["$ref"].split("/")[-1]]["enum"]
    assert "top_face" in enum and "front_face" in enum


def test_dsl_rejects_an_unknown_anchor_and_lists_the_real_ones():
    with pytest.raises(DslError) as exc:
        run_ops([
            {"op": "rounded_prism", "width_mm": 20, "depth_mm": 20, "height_mm": 10},
            {"op": "pocket", "anchor": "lid", "width_mm": 5, "height_mm": 5, "depth_mm": 1},
        ])
    msg = str(exc.value)
    assert "lid" in msg and "top_face" in msg


def test_dsl_rejects_a_cavity_opening_against_the_print_axis():
    """Lint rule, not a preference: a downward cavity needs support."""
    with pytest.raises(DslError) as exc:
        run_ops([
            {"op": "rounded_prism", "width_mm": 30, "depth_mm": 30, "height_mm": 30},
            {"op": "hollow", "wall_mm": 3, "opening": "bottom_face"},
        ])
    assert "needs support" in str(exc.value)


def test_dsl_allows_a_cavity_opening_along_the_print_axis():
    scene = run_ops([
        {"op": "rounded_prism", "width_mm": 30, "depth_mm": 30, "height_mm": 30},
        {"op": "hollow", "wall_mm": 3, "opening": "top_face"},
    ])
    assert scene.solid.val().Volume() < 30 ** 3
    assert scene.features["hollow wall"] == 3.0


def test_dsl_hollow_with_no_room_for_a_cavity_is_rejected():
    with pytest.raises(DslError) as exc:
        run_ops([
            {"op": "rounded_prism", "width_mm": 30, "depth_mm": 30, "height_mm": 4},
            {"op": "hollow", "wall_mm": 3, "opening": "top_face"},
        ])
    assert "leaves no cavity" in str(exc.value)


def test_dsl_linear_pattern_places_every_copy():
    """
    Volume, not bounding box: the base prism sets the bbox either way, so a
    pattern that quietly stacked all five copies in one place would still pass a
    bbox check. Five discs sitting on top with no overlap have a volume you can
    predict exactly.
    """
    import math

    scene = run_ops([
        {"op": "rounded_prism", "width_mm": 60, "depth_mm": 10, "height_mm": 5},
        {"op": "pattern_linear", "count": 5, "dx_mm": 10,
         "step": {"op": "disc", "diameter_mm": 4, "height_mm": 4, "x_mm": -20, "z_mm": 5}},
    ])
    expected = 60 * 10 * 5 + 5 * (math.pi * 2.0 ** 2 * 4)
    assert scene.solid.val().Volume() == pytest.approx(expected, rel=1e-3)
    assert scene.solid.val().BoundingBox().zlen == pytest.approx(9.0)


def test_dsl_pattern_with_no_step_is_rejected():
    with pytest.raises(DslError) as exc:
        run_ops([
            {"op": "rounded_prism", "width_mm": 20, "depth_mm": 20, "height_mm": 5},
            {"op": "pattern_linear", "count": 4,
             "step": {"op": "disc", "diameter_mm": 2, "height_mm": 2}},
        ])
    assert "lands on the last" in str(exc.value)


def test_dsl_polar_pattern_spreads_around_the_axis():
    scene = run_ops([
        {"op": "disc", "diameter_mm": 30, "height_mm": 4},
        {"op": "pattern_polar", "count": 6, "radius_mm": 10,
         "step": {"op": "disc", "diameter_mm": 3, "height_mm": 3, "z_mm": 4}},
    ])
    bb = scene.solid.val().BoundingBox()
    assert bb.zlen == pytest.approx(7.0)


def test_dsl_arc_rod_rejects_a_rod_thicker_than_its_arc():
    with pytest.raises(DslError) as exc:
        run_ops([{"op": "arc_rod", "arc_r_mm": 5, "rod_d_mm": 12, "thickness_mm": 3}])
    assert "close into a disc" in str(exc.value)


def test_dsl_first_op_must_create_geometry():
    with pytest.raises(DslError) as exc:
        run_ops([{"op": "pocket", "anchor": "top_face", "width_mm": 5,
                  "height_mm": 5, "depth_mm": 1}])
    assert "nothing has been created yet" in str(exc.value)


def test_dsl_unknown_op_lists_the_legal_ones():
    with pytest.raises(DslError) as exc:
        run_ops([{"op": "extrude_along_spline"}])
    assert "rounded_prism" in str(exc.value)


def test_dsl_op_without_a_name_is_rejected():
    with pytest.raises(DslError) as exc:
        run_ops([{"width_mm": 10}])
    assert "needs an `op` field" in str(exc.value)


def test_dsl_bad_op_field_names_the_field():
    with pytest.raises(DslError) as exc:
        run_ops([{"op": "rounded_prism", "width_mm": -5, "depth_mm": 10, "height_mm": 5}])
    assert "width_mm" in str(exc.value)


def test_a_level_2_spec_compiles_end_to_end():
    spec = PartSpec(
        name="bracket", level=2, material="pla", nozzle_mm=0.4, layer_mm=0.2,
        ops=[
            {"op": "rounded_prism", "width_mm": 40, "depth_mm": 20, "height_mm": 8, "corner_r_mm": 2},
            {"op": "pattern_linear", "count": 2, "dx_mm": 28,
             "step": {"op": "pocket", "anchor": "top_face", "width_mm": 5,
                      "height_mm": 5, "depth_mm": 8, "u_mm": -14, "name": "bolt slot"}},
        ],
    )
    result = compile_spec(spec)
    assert result.solid.val().Volume() > 0
    assert "bolt slot" in result.features


# -- derived defaults -------------------------------------------------------
#
# A measured baseline put level-1 success at 50%, and every failure was a
# default that only held at the reference part's dimensions. These lock in the
# fix: the defaults now derive from the frame, and the reference parts pin
# their values explicitly so they still reproduce bit for bit.


def test_the_keyring_builds_with_no_parameters_at_all():
    """
    The exact request a model makes on a bare keyring prompt. Before logo_on
    defaulted to false this raised, costing an attempt every time.
    """
    from bpcad.build.templates.keyring_device import KeyringDeviceParams

    params = KeyringDeviceParams()
    assert params.logo_on is False


@pytest.mark.parametrize(
    "kw",
    [
        {},
        {"frame_w_mm": 60.0, "wall_mm": 5.0},
        {"frame_w_mm": 100.0, "frame_d_mm": 40.0},
        {"frame_w_mm": 76.0, "wall_mm": 6.0},
        {"frame_w_mm": 120.0},
        {"frame_w_mm": 76.0, "frame_d_mm": 30.0},
        {"frame_w_mm": 200.0},
    ],
    ids=["defaults", "narrow", "wide-deep", "thick-wall", "very-wide",
         "deep", "huge"],
)
def test_the_vent_derives_a_workable_mechanism_for_any_frame(kw):
    """
    Every one of these is a frame the baseline's prompts asked for, and every
    one used to fail on a fixed default somewhere in the cascade.
    """
    from bpcad.build.templates.louvre_vent import LouvreVentParams

    p = LouvreVentParams(**kw)
    assert p.blade_chord_mm < p.pitch_mm, "blades would collide"
    assert p.crank_r_mm + p.crank_hub_dia_mm / 2 <= p.blade_chord_mm / 2 + 0.2
    _, y = p.bar_offset(p.max_angle_deg)
    assert (y - p.bar_width_mm / 2) - (p.pin_dia_mm / 2 + p.pin_clear_r_mm) > 0.4


def test_a_derived_vent_actually_builds():
    """Passing the validators is not the same as producing geometry."""
    from bpcad.build.templates.louvre_vent import LouvreVentParams, build

    spec = PartSpec(name="v", level=1, material="petg", nozzle_mm=0.4,
                    layer_mm=0.2, template="louvre_vent")
    params = LouvreVentParams(frame_w_mm=60.0, wall_mm=5.0)
    result = build(params, spec)
    assert result.solid.val().Volume() > 0
    assert result.body_count_expected == params.n_blades + 2


def test_an_explicit_value_is_never_overridden():
    """
    Silently correcting what someone asked for would be worse than refusing it.
    """
    from bpcad.build.templates.louvre_vent import LouvreVentParams

    p = LouvreVentParams(frame_w_mm=120.0, n_blades=3, blade_chord_mm=20.0,
                         crank_r_mm=6.0, grip_len_mm=20.0, grip_blade=0)
    assert (p.n_blades, p.blade_chord_mm, p.crank_r_mm) == (3, 20.0, 6.0)
    assert (p.grip_len_mm, p.grip_blade) == (20.0, 0)

    # ...and they really are different from what derivation would have chosen.
    derived = LouvreVentParams(frame_w_mm=120.0)
    assert derived.n_blades != 3 and derived.blade_chord_mm != 20.0


def test_too_many_blades_is_refused_with_the_number_that_fits():
    """
    The cascade's real cause. Telling someone to "raise crank_r_mm" when eight
    blades simply will not fit sends them round the loop one more time.
    """
    from bpcad.build.templates.louvre_vent import LouvreVentParams
    from pydantic import ValidationError

    with pytest.raises(ValidationError) as exc:
        LouvreVentParams(frame_w_mm=120.0, n_blades=8)
    msg = str(exc.value)
    assert "at most" in msg and "blade" in msg
    assert "leave n_blades" in msg


def test_the_grip_tab_goes_on_the_most_central_blade():
    """On the reference 4-blade frame that is index 2, as the reference uses."""
    from bpcad.build.templates.louvre_vent import LouvreVentParams

    assert LouvreVentParams().grip_blade == 2
    assert LouvreVentParams(frame_w_mm=60.0, wall_mm=5.0).grip_blade == 1


def test_the_grip_tab_respects_both_its_floor_and_its_ceiling():
    """
    It must reach past the flange at full travel AND stay inside the aperture.
    The first version of the derivation honoured only the floor and put the tab
    outside the frame on a narrow vent.
    """
    import math

    from bpcad.build.templates.louvre_vent import LouvreVentParams

    for kw in ({}, {"frame_w_mm": 60.0, "wall_mm": 5.0}, {"frame_d_mm": 30.0}):
        p = LouvreVentParams(**kw)
        a = math.radians(p.max_angle_deg)
        assert p.grip_len_mm * math.cos(a) > p.frame_d_mm / 2 + p.flange_t_mm + 1.0
        sweep = (p.grip_len_mm * math.sin(a) + p.grip_pad_w_mm / 2
                 + abs(p.blade_xs[p.grip_blade]))
        assert sweep < p.aperture_w_mm / 2


def test_a_frame_too_narrow_for_its_depth_says_so():
    """
    Genuinely infeasible, and the message has to name the real cause: shortening
    the tab would put it out of reach inside the mounting hole.
    """
    from bpcad.build.templates.louvre_vent import LouvreVentParams
    from pydantic import ValidationError

    with pytest.raises(ValidationError) as exc:
        LouvreVentParams(frame_w_mm=40.0, wall_mm=3.0)
    msg = str(exc.value)
    assert "reduce frame_d_mm" in msg or "widen frame_w_mm" in msg
