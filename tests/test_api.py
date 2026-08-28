"""
The programmatic API.

This is what both the CLI and the GUI sit on, so it carries the weight: if the
two ever disagree about what a part is, it will be because something bypassed
this module.
"""

from pathlib import Path

import pytest

from bpcad import api

ROOT = Path(__file__).resolve().parent.parent
VENT_SPEC = ROOT / "parts" / "vent" / "spec.yaml"
KEYRING_SPEC = ROOT / "parts" / "keyring" / "spec.yaml"
REF_VENT = ROOT / "reference" / "vent_louvre.stl"


def test_templates_are_discoverable():
    """
    Asserts the contract, not a snapshot of the list. Adding a template is the
    normal way this project grows and must not break a test that was only ever
    checking that discovery works.
    """
    names = api.templates()
    assert names == sorted(names), "the catalogue is shown to a model in order"
    assert {"keyring_device", "louvre_vent", "enclosure"} <= set(names)
    for name in names:
        assert api.template_info(name)["summary"]


def test_template_info_carries_everything_a_form_needs():
    """
    A GUI generates its parameter form from this. If a field is missing here,
    that field silently disappears from the interface.
    """
    info = api.template_info("louvre_vent")
    assert info["summary"]
    assert info["print_notes"]
    assert len(info["params"]) > 20

    by_name = {p["name"]: p for p in info["params"]}
    frame = by_name["frame_w_mm"]
    assert frame["type"] == "float"
    assert frame["units"] == "mm"
    assert frame["bounds"] == {"gt": 10.0, "le": 400.0}
    assert frame["description"]


def test_derived_parameters_are_marked_optional():
    """
    The four that derive from the frame must come through as optional, or the
    form has no way to offer "auto" and every part is built at a fixed default.
    """
    by_name = {p["name"]: p for p in api.template_info("louvre_vent")["params"]}
    for name in ("n_blades", "blade_chord_mm", "crank_r_mm", "grip_len_mm"):
        assert by_name[name]["optional"], "%s should be derivable" % name
        assert by_name[name]["default"] is None


def test_unknown_template_is_an_api_error():
    with pytest.raises(api.ApiError):
        api.template_info("flux_capacitor")


def test_build_needs_no_model(tmp_path, monkeypatch):
    import socket

    real = socket.socket

    class Blocked(real):
        def __init__(self, *a, **k):
            raise AssertionError("api.build must not touch the network")

    monkeypatch.setattr(socket, "socket", Blocked)
    part = api.build(VENT_SPEC, out_dir=tmp_path)
    assert part.ok
    assert part.report.mesh.body_count == 6
    assert part.stl.is_file()


def test_build_reproduces_the_reference(tmp_path):
    from bpcad.verify.regression import signature_of

    part = api.build(VENT_SPEC, out_dir=tmp_path)
    reference = api.verify(REF_VENT)
    assert signature_of(part.report.mesh).digest() == signature_of(reference.mesh).digest()


def test_build_can_write_the_whole_bundle(tmp_path):
    part = api.build(KEYRING_SPEC, out_dir=tmp_path, bundle=True, render=False)
    for key in ("spec", "model_py", "stl", "step", "report", "regression"):
        assert key in part.files and part.files[key].is_file()


def test_spec_problems_returns_every_field_not_just_the_first():
    """A form marks three fields red at once; it does not stop at the first."""
    problems = api.spec_problems({
        "name": "x", "level": 1, "material": "petg",
        "nozzle_mm": 0.4, "layer_mm": 0.2, "template": "louvre_vent",
        "params": {"wall_mm": 999, "frame_w_mm": 1},
    })
    fields = {p.field for p in problems}
    assert len(fields) >= 2


def test_a_valid_spec_has_no_problems():
    assert api.spec_problems({
        "name": "x", "level": 1, "material": "petg",
        "nozzle_mm": 0.4, "layer_mm": 0.2, "template": "louvre_vent",
        "params": {"frame_w_mm": 90.0},
    }) == []


def test_parts_lists_what_is_on_disk():
    names = {e.name for e in api.parts(ROOT / "parts")}
    assert {"vent", "keyring"} <= names


def test_a_part_entry_knows_whether_it_is_built():
    entries = {e.name: e for e in api.parts(ROOT / "parts")}
    assert entries["vent"].spec_path is not None
    assert not entries["vent"].is_draft


def test_verify_reports_supports_as_a_warning_not_a_failure():
    """
    The vent's top rail bridges the aperture by design. Calling that FAIL is
    untrue, and a verdict that cries wolf on a known-good part teaches you to
    ignore the verdict.
    """
    report = api.verify(REF_VENT)
    assert report.problems == []
    assert report.warnings
    assert report.verdict == "PASS, with warnings"
    assert report.overhang.supports_needed


def test_a_clean_part_passes_without_warnings():
    report = api.verify(ROOT / "reference" / "loop_keyring.stl")
    assert report.verdict == "PASS"
    assert not report.warnings


def test_model_status_never_raises_when_the_daemon_is_down(monkeypatch):
    """A GUI polls this on a timer and must not have to guard it."""
    import httpx

    def explode(*a, **k):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx, "Client", explode)
    status = api.model_status()
    assert status["available"] is False
    assert status["error"]


def test_measure_image_returns_pixel_measurements():
    result = api.measure_image(ROOT / "reference" / "loop_render_650x855.png")
    assert result["width_px"] > 500
    assert "silhouette" in result


def test_render_part_writes_images(tmp_path):
    written = api.render_part(REF_VENT, tmp_path, views=("3q",))
    assert written["3q"].is_file()
    assert written["heightmap"].is_file()


# -- refinement -------------------------------------------------------------


def test_a_change_edits_the_spec_not_the_mesh():
    """
    "10 mm wider" has to be exact. Editing the spec and rebuilding gives that;
    re-rolling a mesh gives something else that is also 10 mm wider, along with
    every other difference nobody asked for.
    """
    from bpcad.agent.refine import apply_changes

    spec, _ = api.load_spec(VENT_SPEC)
    wider = apply_changes(spec, {"frame_w_mm": 120.0})
    assert wider.params["frame_w_mm"] == 120.0
    assert wider.params["frame_d_mm"] == spec.params["frame_d_mm"]
    assert spec.params["frame_w_mm"] == 76.0, "the original must not be mutated"


def test_null_returns_a_parameter_to_being_derived():
    from bpcad.agent.refine import apply_changes

    spec, _ = api.load_spec(VENT_SPEC)
    assert "n_blades" in spec.params
    freed = apply_changes(spec, {"frame_w_mm": 120.0, "n_blades": None})
    assert "n_blades" not in freed.params

    from bpcad.build.templates.louvre_vent import LouvreVentParams

    assert LouvreVentParams(**freed.params).n_blades == 6


def test_changes_are_read_off_the_specs_not_taken_on_trust():
    """
    A model that says it made something wider and did not is exactly the case
    worth catching, and it is invisible if the interface only repeats the claim.
    """
    from bpcad.agent.refine import apply_changes, describe_changes

    spec, _ = api.load_spec(VENT_SPEC)
    after = apply_changes(spec, {"frame_w_mm": 120.0, "n_blades": None})
    lines = describe_changes(spec, after)
    assert any("frame_w_mm: 76 -> 120 (+44)" in l for l in lines)
    assert any("n_blades" in l and "derived" in l for l in lines)


def test_a_refined_spec_still_builds(tmp_path):
    from bpcad.agent.refine import apply_changes

    spec, base = api.load_spec(VENT_SPEC)
    wider = apply_changes(spec, {"frame_w_mm": 120.0, "n_blades": None})
    part = api.build(spec=wider, base_dir=base, out_dir=tmp_path)
    assert part.ok
    assert part.envelope_mm[0] == pytest.approx(130.0)   # 120 plus the flange


def test_an_impossible_change_is_refused_with_field_problems():
    from bpcad.agent.loop import SpecRejected
    from bpcad.agent.refine import validate_changes

    spec, _ = api.load_spec(VENT_SPEC)
    with pytest.raises(SpecRejected) as exc:
        validate_changes(spec, {"frame_w_mm": 60.0, "n_blades": 8})
    assert "blade" in str(exc.value).lower()


# -- sessions and images ----------------------------------------------------


def test_a_session_keeps_every_version(tmp_path):
    """
    A version you abandoned is still what you were looking at when you decided
    to abandon it. Removing it makes "actually, the one before" impossible.
    """
    spec, _ = api.load_spec(VENT_SPEC)
    s = api.Session(tmp_path, name="demo")
    for i in range(3):
        s.add(api.Version(index=i, spec=spec, instruction="change %d" % i))
    assert len(s.versions) == 3
    assert s.revert_to(0).instruction == "change 0"
    assert len(s.versions) == 3, "reverting must not delete anything"


def test_a_session_survives_being_written_out(tmp_path):
    import json

    spec, _ = api.load_spec(VENT_SPEC)
    s = api.Session(tmp_path, name="demo")
    s.prompt = "a vent"
    s.add(api.Version(index=0, spec=spec, instruction=""))
    data = json.loads(s.save().read_text())
    assert data["prompt"] == "a vent"
    assert data["versions"][0]["spec"]["template"] == "louvre_vent"


def test_an_image_gives_proportions_without_a_scale():
    m = api.measure_reference(ROOT / "reference" / "loop_render_650x855.png")
    assert "aspect_ratio" in m
    assert "width_mm" not in m, "no absolute size without an anchor"
    assert "cannot give absolute size" in m["note"]


def test_stating_a_real_width_turns_pixels_into_millimetres():
    """
    An image gives proportions reliably and absolute size never. One stated
    dimension anchors it - and the scale it derives is reported back, because
    a wrong anchor is the one way to make this lie.
    """
    m = api.measure_reference(
        ROOT / "reference" / "loop_render_650x855.png", known_width_mm=195.4
    )
    assert m["width_mm"] == 195.4
    assert m["scale_mm_per_px"] == pytest.approx(0.32785, abs=1e-4)
    assert m["height_mm"] == pytest.approx(274.7, abs=0.5)
    assert "depends on that being right" in m["note"]


def test_a_thumbnail_is_rendered_on_the_cpu(tmp_path):
    """
    A version card needs a picture whether or not the 3D view is on screen, has
    a GL context, or is showing something else.
    """
    out = api.thumbnail(REF_VENT, tmp_path / "t.png", size=200)
    assert out.is_file() and out.stat().st_size > 500
