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


# ---------------------------------------------------------------------------
# The run record. It lived only in the CLI, so a part made through the web app
# or the desktop app had no run.json at all: no attempt history, no model
# named, no timings, nothing to audit a bad part with. It is also, deliberately,
# the same data a metered product needs to count against a quota.
# ---------------------------------------------------------------------------

def _unreachable_config():
    """
    A config whose machine points at a port nothing listens on.

    This reaches the no-model exit path in under a second, so the record can be
    tested without waiting minutes for inference - and it exercises the branch
    where write_handoff is NOT called, which is the one that would break if
    RunRecord.write stopped creating its own parent directory.
    """
    cfg = api.config(ROOT / "config" / "default.toml")
    for machine in cfg.data["machines"].values():
        machine["host"] = "http://127.0.0.1:1"
    return cfg


def test_a_run_writes_its_record_even_when_no_model_answers(tmp_path):
    import json

    result = api.generate("a flat plate 80 by 40 by 6 mm",
                          cfg=_unreachable_config(), out_dir=str(tmp_path),
                          render=False, max_seconds=30)

    assert not result.ok
    assert result.run_record is not None, "no run.json was written"
    record = json.loads(Path(result.run_record).read_text())

    assert record["ok"] is False
    assert record["handoff"] == "no model reachable"
    assert record["machine"]
    assert record["elapsed_s"] >= 0
    # What a meter and an audit both need.
    assert record["budget"]["max_seconds"] == 30
    assert record["profile"]["model_primary"]
    assert "attempts" in record


def test_the_budget_is_part_of_the_api_not_a_cli_flag():
    """
    `--max-seconds` was enforced inside the CLI's own verify callback, which is
    half the reason a second copy of the ladder existed. A web request wants a
    budget too.
    """
    import inspect

    assert "max_seconds" in inspect.signature(api.generate).parameters


def test_image_facts_reach_the_model_without_being_mapped_to_parameters():
    """
    Two different measurement inputs, kept apart on purpose.

    `measurement` is an object whose values are APPLIED to matching parameters.
    `facts` is what the CLI's --image produces: pixel extents and ratios that
    cannot honestly be mapped to a named parameter, handed over as context
    only. Collapsing them would mean asserting that a silhouette width IS some
    template's width_mm, which is a guess, and a wrong mapping is worse than
    no mapping.
    """
    import inspect

    params = inspect.signature(api.generate).parameters
    assert "facts" in params and "measurement" in params

def test_a_new_part_never_overwrites_one_that_is_already_there(tmp_path,
                                                               monkeypatch):
    """
    THE BUG THIS PINS DESTROYED A VERIFIED PART.

    generate and refine both wrote to parts/<spec.name> unconditionally, so
    asking for the same thing twice replaced the first one's spec, report, run
    record and mesh. A petg flat plate silently became a pla one and the
    original survived only because it happened to be in git.

    Brief 6.7 - "editing never destroys the last good result" - was true only
    while the model happened to pick a different name each time, which is luck
    and not a guarantee.
    """
    monkeypatch.chdir(tmp_path)
    built = tmp_path / "parts" / "flat_plate"
    (built / "out").mkdir(parents=True)
    (built / "spec.yaml").write_text("name: flat_plate\n")

    second = api._free_part_dir("flat_plate")
    assert second.resolve() != built, (
        "a second part of the same name landed on the first"
    )
    assert second.name == "flat_plate_2"
    assert not second.exists()

    # And a third goes somewhere else again.
    second.mkdir(parents=True)
    (second / "spec.yaml").write_text("name: flat_plate\n")
    assert api._free_part_dir("flat_plate").name == "flat_plate_3"


def test_a_failed_run_may_replace_another_failed_run_but_never_a_part(
        tmp_path, monkeypatch):
    """
    Failing at the same words twice should not leave draft_2, draft_3 behind -
    there is nothing in the first handoff worth keeping that is not in the
    second. And a retry that finally SUCCEEDS lands on the handoff it was
    retrying, so the library ends up with the part rather than the part and
    its own gravestone.

    But nothing lands on a directory with something to lose: a spec.yaml,
    which is the durable artifact, or a mesh with no spec, which is an import
    and the one kind of part that cannot be rebuilt from anything.
    """
    monkeypatch.chdir(tmp_path)

    draft = tmp_path / "parts" / "a_hinge"
    draft.mkdir(parents=True)
    (draft / "spec.draft.yaml").write_text("# handoff\n")
    # Resolved, because _free_part_dir returns a path relative to the working
    # directory - which is the point of it, parts/ is relative to where bpcad
    # is run.
    assert api._free_part_dir("a_hinge").resolve() == draft, (
        "a second failed run refused to reuse the first one's handoff"
    )

    part = tmp_path / "parts" / "vent"
    part.mkdir(parents=True)
    (part / "spec.yaml").write_text("name: vent\n")

    imported = tmp_path / "parts" / "scan"
    (imported / "out").mkdir(parents=True)
    (imported / "out" / "scan.stl").write_text("solid\n")
    assert api._free_part_dir("scan").resolve() != imported, (
        "an imported mesh, which cannot be rebuilt from anything, was about "
        "to be written over"
    )
    assert api._free_part_dir("vent").resolve() != part, (
        "a failed run was about to write its handoff over a built part"
    )


def test_a_free_name_is_not_invented_for_ever(tmp_path, monkeypatch):
    """
    A thousand parts of one name is a runaway loop, not a collision, and
    quietly making the thousand-and-first would hide it.
    """
    monkeypatch.chdir(tmp_path)
    root = tmp_path / "parts"
    root.mkdir()
    (root / "loop").mkdir()
    (root / "loop" / "spec.yaml").write_text("name: loop\n")
    for n in range(2, 1000):
        d = root / ("loop_%d" % n)
        d.mkdir()
        (d / "spec.yaml").write_text("name: loop\n")

    with pytest.raises(api.ApiError) as caught:
        api._free_part_dir("loop")
    assert "loop" in str(caught.value)
