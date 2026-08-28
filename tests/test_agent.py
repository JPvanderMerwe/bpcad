"""
Phase 5: the agent loop and the bundle.

No daemon needed anywhere here. The model is stubbed, because the loop's
behaviour - what it retries, what it escalates, what it writes on failure - is
the thing under test, not the model's competence.
"""

from pathlib import Path

import pytest
import yaml

from bpcad.agent import bundle as bundle_mod
from bpcad.agent.loop import (
    STAGE_COMPILE,
    STAGE_PARSE,
    STAGE_VALIDATE,
    STAGE_VERIFY,
    RunRecord,
    SpecRejected,
    _hint,
    _verify_critique,
    attempt_to_dict,
    ask,
    compile_and_verify,
    validate_reply,
)
from bpcad.config import load_config
from bpcad.models.selector import Attempt, Profile
from bpcad.spec.schema import PartSpec

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config" / "default.toml"
VENT_SPEC = ROOT / "parts" / "vent" / "spec.yaml"


@pytest.fixture(scope="module")
def cfg():
    return load_config(CONFIG)


def profile(**kw) -> Profile:
    base = dict(
        name="test", backend_kind="ollama", host="http://127.0.0.1:11434",
        model_primary="big", model_small="small", num_ctx=2048,
        timeout_s=30, max_attempts_per_level=2,
    )
    base.update(kw)
    return Profile(**base)


class ScriptedBackend:
    """Returns canned replies in order, so the loop can be tested exactly."""

    def __init__(self, model, replies):
        self.model = model
        self.replies = list(replies)
        self.prompts = []
        self.calls = []

    def complete(self, system, user, schema):
        self.prompts.append(user)
        return self.replies.pop(0) if self.replies else "{}"

    def name(self):
        return self.model

    def available(self):
        return True

    def endpoint(self):
        return "http://127.0.0.1:11434"


def scripted(monkeypatch, replies):
    """Point the ladder at a scripted backend and hand it back for inspection."""
    holder = {}

    def make(profile, model=None):
        backend = ScriptedBackend(model or profile.model_primary, replies)
        holder.setdefault("first", backend)
        holder["last"] = backend
        return backend

    monkeypatch.setattr("bpcad.models.selector.make_backend", make)
    return holder


GOOD_VENT = '{"name": "v", "template": "louvre_vent", "params": {"frame_w_mm": 76}}'
BAD_WALL = '{"name": "v", "template": "louvre_vent", "params": {"wall_mm": 999}}'
BAD_CHORD = ('{"name": "v", "template": "louvre_vent", "params": '
             '{"frame_w_mm": 60, "wall_mm": 5, "n_blades": 4, "blade_chord_mm": 12.5}}')


# -- the loop ---------------------------------------------------------------


def test_a_good_reply_validates_first_time(monkeypatch):
    scripted(monkeypatch, [GOOD_VENT])
    result = ask("a vent", profile(), "petg", 0.4, 0.2)
    assert result.ok
    assert result.spec.template == "louvre_vent"
    assert len(result.ladder.attempts) == 1


def test_a_rejected_reply_is_retried_with_the_error_fed_back(monkeypatch):
    holder = scripted(monkeypatch, [BAD_WALL, GOOD_VENT])
    result = ask("a vent", profile(), "petg", 0.4, 0.2)
    assert result.ok
    assert len(result.ladder.attempts) == 2

    retry_prompt = holder["last"].prompts[1]
    assert "rejected" in retry_prompt
    assert "wall_mm" in retry_prompt, "the critique must name the offending field"


def test_the_critique_is_specific_not_vague(monkeypatch):
    holder = scripted(monkeypatch, [BAD_WALL, GOOD_VENT])
    ask("a vent", profile(), "petg", 0.4, 0.2)
    retry = holder["last"].prompts[1]
    assert "999" in retry, "must say what was sent"
    assert "<= 20" in retry, "must say what is legal"
    assert "try again" not in retry.lower()


def test_unparseable_output_is_retried_and_tagged(monkeypatch):
    holder = scripted(monkeypatch, ["I think you want a vent!", GOOD_VENT])
    result = ask("a vent", profile(), "petg", 0.4, 0.2)
    assert result.ok
    assert "single JSON object" in holder["last"].prompts[1]


def test_a_failing_build_is_retryable_not_fatal(monkeypatch):
    """
    Geometry that compiles but does not verify must come back as feedback, not
    as a crash. That is what makes step 5 of the loop worth having.
    """
    scripted(monkeypatch, [GOOD_VENT, GOOD_VENT])
    seen = {"n": 0}

    def verify(spec):
        seen["n"] += 1
        if seen["n"] == 1:
            raise SpecRejected("feature too fine", stage=STAGE_VERIFY,
                               hint="- make the wall thicker")
        return None

    result = ask("a vent", profile(), "petg", 0.4, 0.2, verify_fn=verify)
    assert result.ok
    assert seen["n"] == 2


def test_the_verify_critique_reaches_the_model(monkeypatch):
    holder = scripted(monkeypatch, [GOOD_VENT, GOOD_VENT])
    calls = {"n": 0}

    def verify(spec):
        calls["n"] += 1
        if calls["n"] == 1:
            raise SpecRejected("wall measures 0.2 mm", stage=STAGE_VERIFY,
                               hint="- make 'wall' at least 0.40 mm")
        return None

    ask("a vent", profile(), "petg", 0.4, 0.2, verify_fn=verify)
    retry = holder["last"].prompts[1]
    assert "0.40 mm" in retry


def test_fixed_settings_are_forced_not_trusted():
    """A model that changes the material was not asked to make that call."""
    spec = validate_reply(
        {"name": "v", "template": "louvre_vent", "material": "gold",
         "nozzle_mm": 9.9, "layer_mm": 9.9, "params": {}},
        {"material": "petg", "nozzle_mm": 0.4, "layer_mm": 0.2},
    )
    assert (spec.material, spec.nozzle_mm, spec.layer_mm) == ("petg", 0.4, 0.2)


def test_exhaustion_is_reported_not_silent(monkeypatch):
    scripted(monkeypatch, [BAD_WALL] * 8)
    result = ask("a vent", profile(), "petg", 0.4, 0.2)
    assert not result.ok
    assert result.ladder.exhausted
    assert result.problems, "the failure must carry field problems for the handoff"


def test_the_ladder_drops_to_the_small_model(monkeypatch):
    holder = scripted(monkeypatch, [BAD_WALL] * 8)
    result = ask("a vent", profile(), "petg", 0.4, 0.2)
    models = [a.model for a in result.ladder.attempts]
    assert models == ["big", "big", "small", "small"]


# -- critique construction --------------------------------------------------


def test_a_too_fine_feature_produces_a_numeric_critique():
    from bpcad.verify.features import check_features
    from bpcad.verify.mesh import MeshReport
    from bpcad.verify.overhang import OverhangReport
    from bpcad.verify.report import VerifyReport

    report = VerifyReport(
        path="x", nozzle_mm=0.4, print_axis="z",
        mesh=MeshReport("x", True, True, True, 1, 10, 10, 1.0, (1, 1, 1), (0, 0, 0), 0),
        overhang=OverhangReport(
            print_axis="z", max_deg=45.0, max_bridge_gap_mm=0.5,
            worst_overhang_deg=0.0, overhang_area_mm2=0.0, bridged_area_mm2=0.0,
            unsupported_area_mm2=0.0, max_drop_mm=0.0, downward_area_mm2=0.0,
            total_area_mm2=1.0, bed_area_mm2=1.0, overhang_face_count=0,
            unsupported_face_count=0,
        ),
        features=check_features({"hairline": 0.2}, nozzle_mm=0.4),
    )
    problem, hint = _verify_critique(report)
    assert "0.200" in problem and "0.400" in problem
    assert "hairline" in hint


def test_the_hint_names_the_field_the_value_and_the_range():
    from bpcad.agent.handoff import FieldProblem

    text = _hint([FieldProblem("params.wall_mm", "too big", 999, "<= 20")])
    assert "wall_mm" in text and "999" in text and "<= 20" in text


def test_a_misspelling_is_told_to_be_removed():
    from bpcad.agent.handoff import FieldProblem

    text = _hint([FieldProblem("params.wal_mm", "Extra inputs are not permitted", 4, "")])
    assert "remove" in text and "does not exist" in text


# -- compile and verify -----------------------------------------------------


def test_a_good_spec_compiles_and_verifies(cfg, tmp_path):
    from bpcad.build.compile import load_spec

    spec, base = load_spec(VENT_SPEC)
    result, report, stl = compile_and_verify(spec, cfg, base, tmp_path / "out")
    assert stl.is_file()
    assert report.mesh.watertight
    assert report.mesh.body_count == 6


def test_a_part_needing_supports_is_not_a_failure(cfg, tmp_path):
    """
    Plenty of good parts need support - the vent reference is one. Only broken
    meshes and unprintable features fail the loop.
    """
    from bpcad.build.compile import load_spec

    spec, base = load_spec(VENT_SPEC)
    _, report, _ = compile_and_verify(spec, cfg, base, tmp_path / "out")
    assert report.overhang.supports_needed
    # No exception raised - that is the assertion.


def test_geometry_that_cannot_be_built_comes_back_as_a_rejection(cfg, tmp_path):
    spec = PartSpec(
        name="x", level=3, material="petg", nozzle_mm=0.4, layer_mm=0.2,
        script="part = 1",
    )
    with pytest.raises(SpecRejected) as exc:
        compile_and_verify(spec, cfg, None, tmp_path / "out")
    assert exc.value.stage in (STAGE_COMPILE, STAGE_VERIFY)


# -- the bundle -------------------------------------------------------------


@pytest.fixture(scope="module")
def built(cfg, tmp_path_factory):
    from bpcad.build.compile import load_spec

    tmp = tmp_path_factory.mktemp("bundle")
    spec, base = load_spec(VENT_SPEC)
    result, report, stl = compile_and_verify(spec, cfg, base, tmp / "out")
    written = bundle_mod.write_bundle(
        spec=spec, result=result, report=report, stl=stl, part_dir=tmp,
        model_used="qwen2.5-coder:7b", machine="laptop", attempts=2,
        elapsed_s=170.6, render=False,
    )
    return {"dir": tmp, "written": written, "spec": spec, "report": report}


def test_the_bundle_writes_every_promised_artifact(built):
    w = built["written"]
    for key in ("spec", "model_py", "stl", "step", "3mf", "report", "regression"):
        assert key in w, "missing %s" % key
        assert Path(w[key]).is_file()


def test_the_written_spec_round_trips(built):
    """spec.yaml is the durable artifact. It must load back and build again."""
    from bpcad.build.compile import compile_spec, load_spec

    spec, base = load_spec(built["written"]["spec"])
    assert spec.template == "louvre_vent"
    assert compile_spec(spec, base_dir=base).solid is not None


def test_the_spec_has_no_empty_noise(built):
    """A file meant to be read and edited should not carry empty collections."""
    data = yaml.safe_load(Path(built["written"]["spec"]).read_text())
    for key in ("ops", "assumptions", "scale_departures"):
        assert key not in data or data[key]


def test_model_py_is_syntactically_valid(built):
    source = Path(built["written"]["model_py"]).read_text()
    compile(source, "model.py", "exec")
    assert "compile_spec" in source


def test_the_report_follows_the_required_order(built):
    """
    The order is set by the brief and it is not arbitrary: assumptions and
    departures come BEFORE slicer settings, because a reader who has what they
    came for stops reading.
    """
    text = Path(built["written"]["report"]).read_text()
    sections = [
        "## Envelope and volume",
        "## Filament estimate",
        "## Print orientation",
        "## Feature sizes",
        "## Assumptions",
        "## Departures from true scale",
        "## Recommended slicer settings",
        "## Provenance",
    ]
    positions = [text.index(s) for s in sections]
    assert positions == sorted(positions), "report.md sections are out of order"


def test_the_report_names_the_model_that_wrote_the_spec(built):
    text = Path(built["written"]["report"]).read_text()
    assert "qwen2.5-coder:7b" in text
    assert "laptop" in text
    assert "did not write" in text and "CAD code" in text


def test_the_report_carries_the_feature_table(built):
    text = Path(built["written"]["report"]).read_text()
    assert "blade thickness" in text and "PASS" in text


def test_the_report_says_whether_supports_are_needed(built):
    assert "Supports needed | YES" in Path(built["written"]["report"]).read_text()


def test_the_report_warns_that_a_drop_may_be_a_bridge(built):
    """
    The check measures fall, not span. Saying "needs support" without that
    caveat would send someone to add support under a perfectly good bridge.
    """
    assert "bridge" in Path(built["written"]["report"]).read_text()


def test_a_hand_written_spec_reports_no_model(cfg, tmp_path):
    from bpcad.build.compile import load_spec

    spec, base = load_spec(VENT_SPEC)
    result, report, stl = compile_and_verify(spec, cfg, base, tmp_path / "out")
    path = bundle_mod.write_report(spec, result, report, tmp_path / "report.md")
    assert "No model was involved" in path.read_text()


def test_a_level_3_part_is_marked_review_required(cfg, tmp_path):
    from bpcad.build.compile import compile_spec

    spec = PartSpec(
        name="raw", level=3, material="petg", nozzle_mm=0.4, layer_mm=0.2,
        script="part = cq.Workplane('XY').box(20, 20, 10)",
    )
    result = compile_spec(spec, allow_level_3=True)
    _, report, stl = compile_and_verify(
        spec, cfg, None, tmp_path / "out", allow_level_3=True
    )
    path = bundle_mod.write_report(
        spec, result, report, tmp_path / "report.md", review_required=True
    )
    assert "REVIEW REQUIRED" in path.read_text()


def test_the_filament_estimate_is_labelled_as_one(built):
    text = Path(built["written"]["report"]).read_text()
    assert "estimate" in text.lower()
    assert "upper bound" in text


def test_filament_estimate_scales_with_volume():
    a, _ = bundle_mod.filament_estimate(10.0, "petg")
    b, _ = bundle_mod.filament_estimate(20.0, "petg")
    assert b == pytest.approx(2 * a)


def test_an_unknown_material_gets_no_invented_density():
    assert bundle_mod.filament_estimate(10.0, "unobtainium") == (0.0, 0.0)


def test_the_regression_baseline_is_written(built):
    import json

    data = json.loads(Path(built["written"]["regression"]).read_text())
    assert "volume_cm3" in data and "face_count" in data and "digest" in data


# -- run.json ---------------------------------------------------------------


def test_run_json_records_the_full_history(tmp_path):
    record = RunRecord(
        request="a vent", machine="laptop", started_at="2026-08-27T00:00:00Z",
        elapsed_s=170.6, ok=True, level_reached=1,
        profile={"model_primary": "qwen2.5-coder:7b"},
        attempts=[
            attempt_to_dict(Attempt("m", "primary", 1, False, 118.1, error="rejected"), 1),
            attempt_to_dict(Attempt("m", "primary", 2, True, 51.2), 1),
        ],
    )
    import json

    data = json.loads(record.write(tmp_path / "run.json").read_text())
    assert data["ok"] is True
    assert len(data["attempts"]) == 2
    assert data["attempts"][0]["error"] == "rejected"
    assert data["attempts"][1]["elapsed_s"] == 51.2
    assert data["profile"]["model_primary"] == "qwen2.5-coder:7b"


def test_run_json_is_written_on_failure_too(tmp_path):
    """A failed run's history is the more interesting one."""
    import json

    record = RunRecord(
        request="a vent", machine="laptop", started_at="x", elapsed_s=300.0,
        ok=False, level_reached=1, handoff="parts/v/spec.draft.yaml",
    )
    data = json.loads(record.write(tmp_path / "run.json").read_text())
    assert data["ok"] is False
    assert data["handoff"].endswith("spec.draft.yaml")


def test_attempt_records_carry_the_token_counts():
    from bpcad.models.ollama import CallRecord

    a = Attempt("m", "primary", 1, True, 51.2,
                call=CallRecord("m", "schema", 51.2, 1.0, 1600, 90))
    d = attempt_to_dict(a, 1)
    assert d["call"]["prompt_tokens"] == 1600
    assert d["call"]["gen_tokens"] == 90
    assert d["call"]["mechanism"] == "schema"


def test_level_3_stays_blocked_without_the_flag(cfg, tmp_path):
    """The opt-in must still be an opt-in - see CLAUDE.md rule 12."""
    spec = PartSpec(
        name="raw", level=3, material="petg", nozzle_mm=0.4, layer_mm=0.2,
        script="part = cq.Workplane('XY').box(20, 20, 10)",
    )
    with pytest.raises(SpecRejected) as exc:
        compile_and_verify(spec, cfg, None, tmp_path / "out")
    assert "off by default" in str(exc.value)


# -- level 2 escalation -----------------------------------------------------


def test_a_level_2_reply_validates(monkeypatch):
    from bpcad.agent.loop import ask_level_2

    reply = ('{"name": "bracket", "ops": [{"op": "rounded_prism", "width_mm": 40, '
             '"depth_mm": 20, "height_mm": 8}]}')
    scripted(monkeypatch, [reply])
    result = ask_level_2("a bracket", profile(), "pla", 0.4, 0.2)
    assert result.ok
    assert result.spec.level == 2
    assert result.level == 2


def test_a_bad_op_is_rejected_at_parse_naming_the_index(monkeypatch):
    from bpcad.agent.loop import ask_level_2

    bad = ('{"name": "b", "ops": [{"op": "rounded_prism", "width_mm": 10, '
           '"depth_mm": 10, "height_mm": 5}, {"op": "pocket", "anchor": "lid", '
           '"width_mm": 5, "height_mm": 5, "depth_mm": 1}]}')
    good = ('{"name": "b", "ops": [{"op": "rounded_prism", "width_mm": 10, '
            '"depth_mm": 10, "height_mm": 5}]}')
    holder = scripted(monkeypatch, [bad, good])
    result = ask_level_2("a block", profile(), "pla", 0.4, 0.2)
    assert result.ok
    retry = holder["last"].prompts[1]
    assert "ops[1]" in retry
    assert "top_face" in retry, "the legal anchors must be named in the critique"


def test_level_2_rejects_an_empty_op_list(monkeypatch):
    from bpcad.agent.loop import ask_level_2

    scripted(monkeypatch, ['{"name": "b", "ops": []}'] * 8)
    result = ask_level_2("a block", profile(), "pla", 0.4, 0.2)
    assert not result.ok


def test_the_dsl_catalogue_names_anchors_not_selectors():
    from bpcad.agent import prompts

    text = prompts.dsl_catalogue()
    assert "top_face" in text and "front_face" in text
    assert "|Z" not in text and ">Z" not in text


def test_the_dsl_system_prompt_forbids_selectors():
    from bpcad.agent import prompts

    assert "selector" in prompts.DSL_SYSTEM.lower()
    assert "do NOT write CAD code" in prompts.DSL_SYSTEM


def test_the_dsl_schema_constrains_op_names():
    from bpcad.agent import prompts

    enum = prompts.dsl_schema()["properties"]["ops"]["items"]["properties"]["op"]["enum"]
    assert "rounded_prism" in enum and "pocket" in enum
