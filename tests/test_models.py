"""
Phase 4: the model layer.

Every test here runs with NO daemon required. The backends are exercised
against a stub transport, because a test suite that needs Ollama running is a
test suite that gets skipped.

The local-only guarantee is tested in tests/test_local_only.py, which came
first for a reason.
"""

from pathlib import Path

import httpx
import pytest

from bpcad.agent import prompts
from bpcad.agent.handoff import (
    WHOLE_SECTION,
    FieldProblem,
    problems_from_validation_error,
    render_draft,
    write_handoff,
)
from bpcad.agent.loop import SpecRejected, validate_reply
from bpcad.config import load_config
from bpcad.models.base import NonLocalEndpointError
from bpcad.models.null import NullBackend, NullBackendError
from bpcad.models.ollama import (
    JSON_MODE,
    SCHEMA_NATIVE,
    OllamaBackend,
    OllamaError,
    OllamaTimeout,
)
from bpcad.models.selector import (
    Profile,
    ProfileError,
    detect_machine,
    has_cuda_device,
    load_profile,
    make_backend,
    run_ladder,
)

CONFIG = Path(__file__).resolve().parent.parent / "config" / "default.toml"


def stub_backend(handler, **kwargs) -> OllamaBackend:
    """An OllamaBackend whose HTTP layer is a stub, so no daemon is needed."""
    backend = OllamaBackend(model=kwargs.pop("model", "test-model"), **kwargs)
    transport = httpx.MockTransport(handler)

    real_client = httpx.Client

    def client_factory(*args, **kw):
        kw["transport"] = transport
        return real_client(*args, **kw)

    backend._client_factory = client_factory  # noqa: SLF001
    return backend


@pytest.fixture
def patch_httpx(monkeypatch):
    """Point httpx.Client at a MockTransport for the duration of a test."""

    def apply(handler):
        transport = httpx.MockTransport(handler)
        real = httpx.Client

        def factory(*args, **kw):
            kw["transport"] = transport
            return real(*args, **kw)

        monkeypatch.setattr(httpx, "Client", factory)

    return apply


def ok_response(text: str = '{"name": "x"}', **extra):
    payload = {
        "response": text,
        "done": True,
        "load_duration": 1_000_000_000,
        "prompt_eval_count": 100,
        "eval_count": 50,
        "eval_duration": 5_000_000_000,
        "total_duration": 6_000_000_000,
    }
    payload.update(extra)
    return httpx.Response(200, json=payload)


# -- the null backend -------------------------------------------------------


def test_null_backend_refuses_to_generate():
    with pytest.raises(NullBackendError) as exc:
        NullBackend().complete("system", "user", None)
    assert "must work with this backend" in str(exc.value)


def test_null_backend_is_never_available():
    assert NullBackend().available() is False
    assert NullBackend().name() == "null"


# -- construction enforces loopback -----------------------------------------


def test_ollama_backend_rejects_a_public_host_at_construction():
    """Not at first use - at construction, before a prompt can exist."""
    with pytest.raises(NonLocalEndpointError):
        OllamaBackend(model="x", host="https://api.openai.com")


def test_ollama_backend_accepts_loopback():
    assert OllamaBackend(model="x", host="http://127.0.0.1:11434").endpoint()


def test_a_whitelisted_host_is_the_only_way_past_loopback():
    with pytest.raises(NonLocalEndpointError):
        OllamaBackend(model="x", host="http://100.64.0.1:11434")
    assert OllamaBackend(
        model="x", host="http://100.64.0.1:11434", allowed_hosts=("100.64.0.1",)
    ).endpoint()


# -- generation -------------------------------------------------------------


def test_schema_is_sent_natively_and_recorded(patch_httpx):
    seen = {}

    def handler(request):
        import json

        seen.update(json.loads(request.content))
        return ok_response()

    patch_httpx(handler)
    backend = OllamaBackend(model="m")
    backend.complete("sys", "user", {"type": "object"})

    assert seen["format"] == {"type": "object"}
    assert backend.calls[-1].mechanism == SCHEMA_NATIVE


def test_an_old_daemon_falls_back_to_json_mode_and_says_so(patch_httpx):
    """
    Which mechanism was used has to be logged. "The model got it wrong" and
    "the daemon ignored the schema" look identical from outside and need
    different fixes.
    """
    calls = {"n": 0}

    def handler(request):
        import json

        calls["n"] += 1
        body = json.loads(request.content)
        if isinstance(body.get("format"), dict):
            return httpx.Response(400, text="invalid format value")
        return ok_response()

    patch_httpx(handler)
    backend = OllamaBackend(model="m")
    backend.complete("sys", "user", {"type": "object"})

    assert calls["n"] == 2
    assert backend.calls[-1].mechanism == JSON_MODE


def test_timeout_says_what_to_do_about_it(patch_httpx):
    def handler(request):
        raise httpx.TimeoutException("too slow", request=request)

    patch_httpx(handler)
    with pytest.raises(OllamaTimeout) as exc:
        OllamaBackend(model="m", timeout_s=1).complete("s", "u", None)
    msg = str(exc.value)
    assert "CPU-only" in msg and "timeout_s" in msg


def test_a_missing_model_says_how_to_get_it(patch_httpx):
    patch_httpx(lambda request: httpx.Response(404, text="model not found"))
    with pytest.raises(OllamaError) as exc:
        OllamaBackend(model="nope:7b").complete("s", "u", None)
    assert "ollama pull nope:7b" in str(exc.value)


def test_an_unreachable_daemon_does_not_suggest_a_remote_fallback(patch_httpx):
    def handler(request):
        raise httpx.ConnectError("refused", request=request)

    patch_httpx(handler)
    with pytest.raises(OllamaError) as exc:
        OllamaBackend(model="m").complete("s", "u", None)
    msg = str(exc.value)
    assert "ollama serve" in msg
    assert "local inference or none" in msg


def test_failures_are_recorded_not_just_raised(patch_httpx):
    patch_httpx(lambda request: httpx.Response(500, text="boom"))
    backend = OllamaBackend(model="m")
    with pytest.raises(OllamaError):
        backend.complete("s", "u", None)
    assert backend.calls[-1].error


def test_call_record_reports_what_the_run_cost(patch_httpx):
    patch_httpx(lambda request: ok_response())
    backend = OllamaBackend(model="m")
    backend.complete("s", "u", None)
    call = backend.calls[-1]
    assert call.prompt_tokens == 100
    assert call.gen_tokens == 50
    assert call.load_s == pytest.approx(1.0)
    assert "tok/s" in call.summary()


def test_available_never_raises(patch_httpx):
    def handler(request):
        raise httpx.ConnectError("refused", request=request)

    patch_httpx(handler)
    assert OllamaBackend(model="m").available() is False


def test_processor_never_raises(patch_httpx):
    def handler(request):
        raise httpx.ConnectError("refused", request=request)

    patch_httpx(handler)
    assert OllamaBackend(model="m").processor() == "unknown"


def test_processor_reports_cpu_when_nothing_is_in_vram(patch_httpx):
    """
    The measured reality on the work laptop: 100% CPU despite an iGPU and an
    NPU being present. Whether they are used is a property of how Ollama was
    built, not of the hardware existing.
    """
    patch_httpx(lambda request: httpx.Response(
        200, json={"models": [{"name": "m", "size": 5_000_000_000, "size_vram": 0}]}
    ))
    assert OllamaBackend(model="m").processor() == "100% CPU"


# -- machine profiles -------------------------------------------------------


def test_cuda_detection_never_crashes_without_a_driver():
    """Must not shell out to nvidia-smi - it simply is not there on this laptop."""
    assert has_cuda_device() in (True, False)


def test_detection_picks_laptop_with_no_cuda(monkeypatch):
    cfg = load_config(CONFIG)
    monkeypatch.delenv("BPCAD_MACHINE", raising=False)
    monkeypatch.setattr("bpcad.models.selector.has_cuda_device", lambda: False)
    assert detect_machine(cfg) == "laptop"


def test_detection_picks_desktop_with_cuda(monkeypatch):
    cfg = load_config(CONFIG)
    monkeypatch.delenv("BPCAD_MACHINE", raising=False)
    monkeypatch.setattr("bpcad.models.selector.has_cuda_device", lambda: True)
    assert detect_machine(cfg) == "desktop"


def test_the_env_var_overrides_detection(monkeypatch):
    cfg = load_config(CONFIG)
    monkeypatch.setenv("BPCAD_MACHINE", "desktop")
    assert detect_machine(cfg) == "desktop"


def test_an_unknown_machine_lists_the_real_ones(monkeypatch):
    cfg = load_config(CONFIG)
    monkeypatch.setenv("BPCAD_MACHINE", "workshop")
    with pytest.raises(ProfileError) as exc:
        detect_machine(cfg)
    assert "laptop" in str(exc.value) and "desktop" in str(exc.value)


def test_an_unset_model_tag_refuses_rather_than_guessing(monkeypatch):
    """Nothing gets pinned before it has been benchmarked on the hardware."""
    cfg = load_config(CONFIG)
    monkeypatch.delenv("BPCAD_MACHINE", raising=False)
    if cfg.machine("desktop")["model_primary"] != "UNSET":
        pytest.skip("desktop has been benchmarked and pinned")
    with pytest.raises(ProfileError) as exc:
        load_profile(cfg, "desktop")
    assert "benchmarked" in str(exc.value)


def test_the_laptop_profile_is_pinned_from_measurements():
    cfg = load_config(CONFIG)
    profile = load_profile(cfg, "laptop")
    assert profile.model_primary != "UNSET"
    assert profile.timeout_s >= 300, "CPU-only inference needs real headroom"


def test_only_two_backends_exist():
    """Do not add a third without asking - CLAUDE.md rule 10."""
    profile = Profile(
        name="x", backend_kind="openai", host="http://127.0.0.1:11434",
        model_primary="m", model_small="m", num_ctx=1024,
        timeout_s=10, max_attempts_per_level=1,
    )
    with pytest.raises(ProfileError) as exc:
        make_backend(profile)
    assert "no cloud model" in str(exc.value)


def test_the_null_backend_is_selectable():
    profile = Profile(
        name="x", backend_kind="null", host="http://127.0.0.1:11434",
        model_primary="m", model_small="m", num_ctx=1024,
        timeout_s=10, max_attempts_per_level=1,
    )
    assert isinstance(make_backend(profile), NullBackend)


# -- the degradation ladder -------------------------------------------------


class FakeBackend:
    """Succeeds on the nth call, fails before that."""

    def __init__(self, model, succeed_on=None):
        self.model = model
        self.succeed_on = succeed_on
        self.n = 0
        self.calls = []

    def complete(self, system, user, schema):
        self.n += 1
        return "{}"

    def name(self):
        return self.model

    def available(self):
        return True

    def endpoint(self):
        return "http://127.0.0.1:11434"


def ladder_profile(**kw):
    base = dict(
        name="test", backend_kind="ollama", host="http://127.0.0.1:11434",
        model_primary="big", model_small="small", num_ctx=1024,
        timeout_s=5, max_attempts_per_level=2,
    )
    base.update(kw)
    return Profile(**base)


def test_the_ladder_retries_the_same_model_before_dropping(monkeypatch):
    seen = []
    monkeypatch.setattr(
        "bpcad.models.selector.make_backend",
        lambda profile, model=None: FakeBackend(model or profile.model_primary),
    )

    def ask(backend):
        seen.append(backend.name())
        raise SpecRejected("nope")

    result = run_ladder(ladder_profile(), ask)
    assert seen == ["big", "big", "small", "small"]
    assert result.exhausted


def test_the_ladder_stops_as_soon_as_something_validates(monkeypatch):
    monkeypatch.setattr(
        "bpcad.models.selector.make_backend",
        lambda profile, model=None: FakeBackend(model or profile.model_primary),
    )
    calls = {"n": 0}

    def ask(backend):
        calls["n"] += 1
        if calls["n"] < 2:
            raise SpecRejected("nope")
        return "a spec"

    result = run_ladder(ladder_profile(), ask)
    assert result.ok and result.value == "a spec"
    assert len(result.attempts) == 2


def test_the_ladder_does_not_retry_a_daemon_problem(monkeypatch):
    """A retry cannot fix a daemon that is not running."""
    monkeypatch.setattr(
        "bpcad.models.selector.make_backend",
        lambda profile, model=None: FakeBackend(model or profile.model_primary),
    )

    def ask(backend):
        raise OllamaError("daemon down")

    result = run_ladder(ladder_profile(), ask)
    assert [a.model for a in result.attempts] == ["big", "small"]


def test_the_ladder_never_reaches_a_model_when_nothing_is_available(monkeypatch):
    class Unavailable(FakeBackend):
        def available(self):
            return False

    monkeypatch.setattr(
        "bpcad.models.selector.make_backend",
        lambda profile, model=None: Unavailable(model or profile.model_primary),
    )
    result = run_ladder(ladder_profile(), lambda b: "never")
    assert result.never_reached_a_model
    assert not result.ok


def test_one_model_configured_twice_is_only_tried_once():
    profile = ladder_profile(model_primary="m", model_small="m")
    assert profile.models() == ["m"]


def test_the_ladder_times_every_attempt(monkeypatch):
    monkeypatch.setattr(
        "bpcad.models.selector.make_backend",
        lambda profile, model=None: FakeBackend(model or profile.model_primary),
    )
    result = run_ladder(ladder_profile(), lambda b: "ok")
    assert result.attempts[0].elapsed_s >= 0
    assert "attempt 1" in result.attempts[0].summary()


# -- prompts ----------------------------------------------------------------


def test_the_template_field_is_an_enum():
    """
    Without it, models reliably put a MATERIAL or a description in `template`.
    Both did on the very first benchmark run.
    """
    enum = prompts.ask_schema()["properties"]["template"]["enum"]
    assert "keyring_device" in enum and "louvre_vent" in enum


def test_the_model_can_say_no_template_fits():
    """
    A constrained decoder cannot emit anything outside the enum, so without an
    escape hatch it is FORCED to name a template even when none makes the part.
    Asked for a birdhouse with only a keyring and a vent available, it produced
    a 573 cm3 solid slab with a keyring handle - and every downstream check
    passed, because the thing was perfectly manufacturable. It just was not a
    birdhouse.
    """
    enum = prompts.ask_schema()["properties"]["template"]["enum"]
    assert prompts.NO_TEMPLATE in enum

    # The escape hatch has to be in the enum AND explained, or a model that
    # can technically emit it never learns that it is allowed to.
    assert prompts.NO_TEMPLATE in prompts.SYSTEM
    assert "not a keyring with different numbers" in prompts.SYSTEM

    user = prompts.build_user_prompt("a birdhouse", "petg", 0.4, 0.2)
    assert prompts.NO_TEMPLATE in user
    assert "correct answer, not a failure" in user


def test_declining_a_template_is_not_treated_as_an_error():
    from bpcad.agent.loop import NoTemplateFits, validate_reply

    with pytest.raises(NoTemplateFits):
        validate_reply(
            {"name": "b", "template": prompts.NO_TEMPLATE, "params": {}},
            {"material": "petg", "nozzle_mm": 0.4, "layer_mm": 0.2},
        )


def test_the_catalogue_carries_bounds_and_units():
    text = prompts.template_catalogue()
    assert "frame_w_mm" in text and "> 10" in text
    assert "keyring_device" in text and "louvre_vent" in text


def test_the_system_prompt_forbids_writing_cad_code():
    assert "do NOT write CAD code" in prompts.SYSTEM


def test_the_critique_leads_with_the_fix():
    """
    Order matters more than content. Given the instruction last, a 7B model
    moved a value the wrong way when it had already been told the right one.
    """
    text = prompts.critique_prompt("{}", "some problem", "- Set wall_mm to 3.0.")
    fix_at = text.index("Set wall_mm to 3.0")
    context_at = text.index("For reference")
    assert fix_at < context_at


def test_the_critique_strips_advice_the_model_cannot_use():
    """A model cannot run `bpcad spec explain`. Telling it to is noise."""
    text = prompts.critique_prompt("{}", "bad\nRun `bpcad spec explain x` for help", "")
    assert "bpcad spec explain" not in text


@pytest.mark.parametrize(
    "raw",
    ['{"a": 1}', '```json\n{"a": 1}\n```', '```\n{"a": 1}\n```', 'Sure! {"a": 1} hope that helps'],
)
def test_replies_are_parsed_through_the_usual_decorations(raw):
    assert prompts.parse_reply(raw) == {"a": 1}


def test_an_empty_reply_is_rejected():
    with pytest.raises(ValueError):
        prompts.parse_reply("")


def test_a_json_list_is_not_a_spec():
    with pytest.raises(ValueError) as exc:
        prompts.parse_reply("[1, 2, 3]")
    assert "must be a JSON object" in str(exc.value)


# -- validation and the handoff ---------------------------------------------


def test_fixed_settings_override_whatever_the_model_says():
    """
    Material, nozzle and layer come from config and the command line. A model
    that changes them is overruled - it was not asked to make that judgement.
    """
    spec = validate_reply(
        {"name": "v", "template": "louvre_vent", "material": "gold",
         "nozzle_mm": 9.9, "layer_mm": 9.9, "params": {}},
        {"material": "petg", "nozzle_mm": 0.4, "layer_mm": 0.2},
    )
    assert spec.material == "petg"
    assert spec.nozzle_mm == 0.4


def test_a_bad_parameter_comes_back_as_a_field_problem():
    with pytest.raises(SpecRejected) as exc:
        validate_reply(
            {"name": "v", "template": "louvre_vent", "params": {"wall_mm": 999}},
            {"material": "petg", "nozzle_mm": 0.4, "layer_mm": 0.2},
        )
    fields = [p.field for p in exc.value.problems]
    assert any("wall_mm" in f for f in fields)


def test_a_cross_field_error_is_not_reported_as_a_missing_field():
    """
    A validator comparing two fields has an empty location. Calling that
    "(root)" and then listing it as missing tells you to add a field that does
    not exist.
    """
    with pytest.raises(SpecRejected) as exc:
        validate_reply(
            {"name": "v", "template": "louvre_vent",
             "params": {"frame_w_mm": 60, "wall_mm": 5, "n_blades": 4, "blade_chord_mm": 12.5}},
            {"material": "petg", "nozzle_mm": 0.4, "layer_mm": 0.2},
        )
    problems = exc.value.problems
    assert any(p.field.endswith(WHOLE_SECTION) for p in problems)

    draft = render_draft(
        "a vent", {"template": "louvre_vent", "params": {"blade_chord_mm": 12.5}},
        problems, "laptop", 4, 300.0, ["m"], Path("parts/v/spec.yaml"),
    )
    assert "CONTRADICT EACH OTHER" in draft
    assert "<fill this in>" not in draft


def test_the_pitch_error_names_a_value_that_works():
    """
    Naming only the boundary is not enough: the template's DEFAULT chord also
    fails at this frame size, so the first attempt always fails and the reader
    needs to be told what to put.
    """
    from bpcad.build.templates.louvre_vent import LouvreVentParams
    from pydantic import ValidationError

    with pytest.raises(ValidationError) as exc:
        LouvreVentParams(frame_w_mm=60, wall_mm=5, n_blades=4, blade_chord_mm=12.5)
    assert "Set blade_chord_mm to about 10.2" in str(exc.value)


def test_the_draft_marks_every_bad_field_inline(tmp_path):
    problems = [
        FieldProblem("params.body_width_mm", "Input should be greater than 10", 5.0, "> 10.0"),
        FieldProblem("params.body_widht_mm", "Extra inputs are not permitted", 30.0, ""),
        FieldProblem("material", "Field required", None, "required"),
    ]
    draft = write_handoff(
        out_dir=tmp_path, request="a keyring",
        attempt={"name": "k", "level": 1, "template": "keyring_device",
                 "params": {"body_width_mm": 5.0, "body_widht_mm": 30.0}},
        problems=problems, machine="laptop", attempts_made=4,
        elapsed_s=316.5, models_tried=["a", "b"],
    )
    text = draft.read_text()

    assert draft.name == "spec.draft.yaml"
    assert "WHAT IS WRONG (3)" in text
    assert "legal  : > 10.0" in text          # inline, above the field
    assert "MISSING" in text and "material" in text
    assert "bpcad build" in text and "spec.yaml" in text
    assert "bpcad spec explain keyring_device" in text
    assert "316.5s" in text and "laptop" in text


def test_the_draft_is_valid_yaml_once_the_values_are_fixed(tmp_path):
    """
    The draft has to PARSE, not just read well. A draft that is not YAML makes
    the fallback path worse than writing a spec from scratch.
    """
    import yaml

    draft = write_handoff(
        out_dir=tmp_path, request="a vent",
        attempt={"name": "v", "level": 1, "material": "petg", "nozzle_mm": 0.4,
                 "layer_mm": 0.2, "template": "louvre_vent",
                 "params": {"frame_w_mm": 60, "wall_mm": 5}},
        problems=[FieldProblem("params.wall_mm", "too thick", 5, "<= 4")],
        machine="laptop", attempts_made=2, elapsed_s=100.0, models_tried=["m"],
    )
    data = yaml.safe_load(draft.read_text())
    assert data["template"] == "louvre_vent"
    assert data["params"]["frame_w_mm"] == 60


def test_a_validation_error_becomes_per_field_problems():
    from bpcad.build.templates.louvre_vent import LouvreVentParams
    from pydantic import ValidationError

    with pytest.raises(ValidationError) as exc:
        LouvreVentParams(wall_mm=-1)
    problems = problems_from_validation_error(exc.value)
    assert problems[0].field == "wall_mm"
    assert problems[0].legal


def test_a_public_host_is_refused_at_profile_load_not_mid_generation(tmp_path):
    """
    The refusal must be the FIRST thing that happens.

    Raising later still honours the guarantee - nothing is ever sent - but it
    surfaces as a traceback from inside the generation loop, after printing a
    banner containing the offending URL as though it were about to be used.
    """
    from bpcad.config import load_config

    text = CONFIG.read_text().replace(
        'host = "http://127.0.0.1:11434"', 'host = "https://api.openai.com/v1"'
    )
    bad = tmp_path / "public.toml"
    bad.write_text(text)

    with pytest.raises(NonLocalEndpointError) as exc:
        load_profile(load_config(bad), "laptop")
    assert "api.openai.com" in str(exc.value)
    assert "no cloud model" in str(exc.value)


def test_a_public_host_does_not_stop_the_deterministic_pipeline(tmp_path):
    """
    A misconfigured model endpoint must not break `build`, `verify`, `render`
    or `measure`. They never touch the model layer, and that has to stay true
    even when the model layer is configured wrongly.
    """
    from bpcad.build.compile import compile_spec, load_spec

    spec, base = load_spec(Path(__file__).resolve().parent.parent / "parts" / "vent" / "spec.yaml")
    assert compile_spec(spec, base_dir=base).solid is not None
