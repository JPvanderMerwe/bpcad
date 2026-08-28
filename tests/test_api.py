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
    assert api.templates() == ["keyring_device", "louvre_vent"]


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
