"""
The bpcad command line. Single entry point.

Commands are registered phase by phase. Right now that is `config`, `verify`
and `render`; `measure` arrives at Phase 2, `build` and `spec` at Phase 3,
`ask` at Phase 4 and `gen` at Phase 5. A command is not registered until the
code behind it actually works, so `--help` never advertises something that
will fail.

Nothing in here touches a model. `verify` and `render` are pure CPU and work
with the network cable out, which is the point.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer

from bpcad.config import ConfigError, format_config, load_config

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help=(
        "bpcad - local, offline text-and-image-to-3D-printable-part pipeline. "
        "Bit Primitive. No cloud model, no API key, no hosted endpoint, ever."
    ),
)

config_app = typer.Typer(
    no_args_is_help=True,
    help="Inspect the bpcad configuration.",
)
app.add_typer(config_app, name="config")

models_app = typer.Typer(
    no_args_is_help=True,
    help="Inspect the local model layer. Local inference only, always.",
)
app.add_typer(models_app, name="models")

spec_app = typer.Typer(
    no_args_is_help=True,
    help="Inspect the spec schema and the template catalogue.",
)
app.add_typer(spec_app, name="spec")

measure_app = typer.Typer(
    no_args_is_help=True,
    help="Measure dimensions off an image. Measure, never estimate.",
)
app.add_typer(measure_app, name="measure")


def _fail(message: str) -> None:
    """One place for user-facing failures, so they all look the same."""
    typer.secho("bpcad: %s" % message, fg=typer.colors.RED, err=True)
    raise typer.Exit(code=1)


def _load_config_or_fail(path: Optional[Path] = None):
    try:
        return load_config(path)
    except ConfigError as exc:
        _fail(str(exc))


# ---------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------


@config_app.command("show")
def config_show(
    path: Optional[Path] = typer.Option(
        None,
        "--path",
        help="Config file to read. Defaults to $BPCAD_CONFIG, then ./config/default.toml.",
    ),
    machine: Optional[str] = typer.Option(
        None,
        "--machine",
        help="Show only this machine profile. Default shows all of them.",
    ),
) -> None:
    """Show the resolved configuration and everything still marked UNSET."""
    cfg = _load_config_or_fail(path)
    try:
        typer.echo(format_config(cfg, machine=machine))
    except ConfigError as exc:
        _fail(str(exc))


# ---------------------------------------------------------------------------
# models
# ---------------------------------------------------------------------------


@models_app.command("list")
def models_list(
    machine: Optional[str] = typer.Option(None, "--machine", help="Machine profile to use."),
) -> None:
    """
    Show the machine profile and what the local daemon actually has.

    Nothing here reaches past loopback. If the daemon is not running, this says
    so and stops - there is no remote fallback to try.
    """
    import httpx

    from bpcad.models.base import NonLocalEndpointError, assert_local_endpoint
    from bpcad.models.selector import ProfileError, detect_machine, has_cuda_device

    cfg = _load_config_or_fail()

    try:
        name = machine or detect_machine(cfg)
    except ProfileError as exc:
        _fail(str(exc))
        return

    table = cfg.machine(name)
    try:
        assert_local_endpoint(table["host"], cfg.allowed_model_hosts)
    except NonLocalEndpointError as exc:
        _fail(str(exc))
        return
    typer.echo("machine profile   %s%s"
               % (name, "" if machine else "  (auto-detected)"))
    typer.echo("  CUDA device     %s" % ("present" if has_cuda_device() else "none"))
    for key in ("backend", "host", "model_primary", "model_small", "num_ctx",
                "timeout_s", "max_attempts_per_level"):
        value = table[key]
        suffix = "   <- UNSET, benchmark before pinning" if value == "UNSET" else ""
        typer.echo("  %-15s %s%s" % (key, value, suffix))
    typer.echo("")

    host = table["host"]
    try:
        with httpx.Client(timeout=5.0) as client:
            tags = client.get("%s/api/tags" % host.rstrip("/")).json()
            running = client.get("%s/api/ps" % host.rstrip("/")).json()
    except Exception as exc:
        typer.echo("daemon at %s is not answering (%s)." % (host, type(exc).__name__))
        typer.echo("Start it with `ollama serve`. bpcad has no remote fallback.")
        return

    typer.echo("models on the daemon at %s:" % host)
    for m in sorted(tags.get("models", []), key=lambda m: m.get("name", "")):
        size = (m.get("size") or 0) / 1e9
        typer.echo("  %-24s %5.1f GB" % (m.get("name", "?"), size))

    loaded = running.get("models", [])
    typer.echo("")
    if not loaded:
        typer.echo("nothing loaded right now.")
    else:
        typer.echo("loaded right now:")
        for m in loaded:
            total = m.get("size") or 0
            vram = m.get("size_vram") or 0
            where = "100% CPU" if vram == 0 else (
                "100% GPU" if vram >= total else "%d%% GPU" % round(100 * vram / total)
            )
            typer.echo("  %-24s %5.1f GB   %s" % (m.get("name", "?"), total / 1e9, where))


@models_app.command("bench")
def models_bench(
    model: str = typer.Argument(..., help="Model tag to time, e.g. hermes3:latest."),
    machine: Optional[str] = typer.Option(None, "--machine", help="Machine profile to use."),
    num_ctx: Optional[int] = typer.Option(None, "--num-ctx", help="Context size for the run."),
) -> None:
    """
    Time one schema-constrained generation, and report CPU or GPU.

    Measure before pinning a model tag. Whether a machine's iGPU or NPU is used
    at all is a property of how Ollama was built, not of the hardware being
    present, and it has to be established rather than assumed.
    """
    from bpcad.agent import prompts
    from bpcad.models.base import NonLocalEndpointError
    from bpcad.models.ollama import OllamaBackend, OllamaError

    cfg = _load_config_or_fail()
    from bpcad.models.selector import ProfileError, detect_machine

    try:
        name = machine or detect_machine(cfg)
    except ProfileError as exc:
        _fail(str(exc))
        return
    table = cfg.machine(name)

    try:
        backend = OllamaBackend(
            model=model,
            host=table["host"],
            timeout_s=float(table["timeout_s"]),
            num_ctx=num_ctx or int(table["num_ctx"]),
            allowed_hosts=tuple(cfg.allowed_model_hosts),
        )
    except NonLocalEndpointError as exc:
        _fail(str(exc))
        return
    if not backend.available():
        _fail(
            "model %r is not on the daemon at %s. `bpcad models list` shows what is."
            % (model, table["host"])
        )

    request = "A wall vent 60 mm wide and 40 mm tall with 5 mm walls and four blades."
    typer.echo("machine %s, model %s, num_ctx %d" % (name, model, backend.num_ctx))
    typer.echo("generating...")

    try:
        raw = backend.complete(
            prompts.SYSTEM,
            prompts.build_user_prompt(request, "petg", 0.4, 0.2),
            prompts.ask_schema(),
        )
    except OllamaError as exc:
        _fail(str(exc))
        return

    call = backend.calls[-1]
    typer.echo("")
    typer.echo("  %s" % call.summary())
    typer.echo("  processor        %s" % backend.processor())
    typer.echo("")

    try:
        data = prompts.parse_reply(raw)
        typer.echo("  parsed OK, template=%r, %d params"
                   % (data.get("template"), len(data.get("params") or {})))
    except ValueError as exc:
        typer.echo("  reply did not parse: %s" % exc)


# ---------------------------------------------------------------------------
# ask
# ---------------------------------------------------------------------------


@app.command("ask")
def ask_cmd(
    request: str = typer.Argument(..., help="What you want, in plain language."),
    machine: Optional[str] = typer.Option(None, "--machine", help="Machine profile: desktop or laptop."),
    material: str = typer.Option("petg", "--material", help="Material for the part."),
    nozzle: Optional[float] = typer.Option(None, "--nozzle", help="Nozzle width in mm."),
    layer: Optional[float] = typer.Option(None, "--layer", help="Layer height in mm."),
    out: Optional[Path] = typer.Option(None, "--out", help="Where to write spec.yaml. Default parts/<name>."),
    write: bool = typer.Option(True, "--write/--no-write", help="Write the spec to disk."),
) -> None:
    """
    Ask the local model for a spec.yaml. Generation only - `gen` builds it too.

    On failure this does NOT just report an error: it writes an annotated
    spec.draft.yaml with every bad field marked inline, and prints the exact
    command to run once you have fixed it.
    """
    import yaml

    from bpcad.agent.handoff import next_steps, write_handoff  # noqa: F401
    from bpcad.agent.loop import ask as run_ask
    from bpcad.models.base import NonLocalEndpointError
    from bpcad.models.selector import ProfileError, load_profile

    cfg = _load_config_or_fail()

    if material.strip().lower() not in cfg.data["materials"]:
        _fail("unknown material %r. Configured: %s."
              % (material, ", ".join(cfg.material_names)))

    try:
        profile = load_profile(cfg, machine)
    except NonLocalEndpointError as exc:
        _fail(str(exc))
        return
    except ProfileError as exc:
        _fail(str(exc))
        return

    nozzle_mm = nozzle if nozzle is not None else float(cfg.print_settings["nozzle_mm"])
    layer_mm = layer if layer is not None else float(cfg.print_settings["layer_mm"])

    typer.echo(profile.describe())
    typer.echo("")

    def report(attempt) -> None:
        typer.echo("  " + attempt.summary())

    result = run_ask(
        request=request,
        profile=profile,
        material=material,
        nozzle_mm=nozzle_mm,
        layer_mm=layer_mm,
        on_attempt=report,
    )

    typer.echo("")
    typer.echo("%d attempt(s), %.1fs total"
               % (len(result.ladder.attempts), result.ladder.total_elapsed_s))
    typer.echo("")

    if not result.ok and result.ladder.never_reached_a_model:
        from bpcad.agent.handoff import no_model_steps

        typer.echo(no_model_steps(profile.host, profile.models()))
        raise typer.Exit(code=1)

    if not result.ok:
        target = out if out is not None else Path("parts") / _slug(request)
        draft = write_handoff(
            out_dir=target,
            request=request,
            attempt=result.best_attempt_data,
            problems=result.problems,
            machine=result.machine,
            attempts_made=len(result.ladder.attempts),
            elapsed_s=result.ladder.total_elapsed_s,
            models_tried=result.models_tried,
            raw_error=result.ladder.last_error,
        )
        typer.echo(next_steps(draft))
        raise typer.Exit(code=1)

    spec = result.spec
    typer.echo("template   %s" % spec.template)
    typer.echo("params     %s" % (spec.params or "(all defaults)"))
    typer.echo("")

    if write:
        target = out if out is not None else Path("parts") / spec.name
        target.mkdir(parents=True, exist_ok=True)
        path = target / "spec.yaml"
        path.write_text(
            yaml.safe_dump(
                spec.model_dump(exclude_none=True, exclude_defaults=False),
                sort_keys=False,
            )
        )
        typer.echo(str(path))
        typer.echo("")
        typer.echo("  bpcad build %s" % path)
    else:
        typer.echo(yaml.safe_dump(spec.model_dump(exclude_none=True), sort_keys=False))


def _slug(text: str) -> str:
    """A directory name from a request, for the handoff when there is no spec."""
    keep = [c.lower() if c.isalnum() else "_" for c in text.strip()[:40]]
    return "".join(keep).strip("_").replace("__", "_") or "part"


# ---------------------------------------------------------------------------
# gen
# ---------------------------------------------------------------------------


@app.command("gen")
def gen_cmd(
    request: str = typer.Argument(..., help="What you want, in plain language."),
    image: Optional[Path] = typer.Option(
        None, "--image", help="Reference image to measure. Measurements beat prose."
    ),
    machine: Optional[str] = typer.Option(None, "--machine", help="Machine profile: desktop or laptop."),
    material: str = typer.Option("petg", "--material", help="Material for the part."),
    nozzle: Optional[float] = typer.Option(None, "--nozzle", help="Nozzle width in mm."),
    layer: Optional[float] = typer.Option(None, "--layer", help="Layer height in mm."),
    out: Optional[Path] = typer.Option(None, "--out", help="Bundle directory. Default parts/<name>."),
    allow_level_3: bool = typer.Option(
        False, "--allow-level-3",
        help="Permit raw CadQuery as a last resort. One attempt, marked REVIEW REQUIRED.",
    ),
    max_seconds: Optional[float] = typer.Option(
        None, "--max-seconds", help="Hard wall-clock budget for the whole run."
    ),
    render: bool = typer.Option(True, "--render/--no-render", help="Render preview and height map."),
) -> None:
    """
    Prompt to verified, printable bundle. The whole pipeline in one command.

    Generate, validate, build, verify, render, write the bundle. On failure it
    hands off with an annotated spec.draft.yaml rather than just reporting an
    error - everything downstream of a spec works with no model at all.
    """
    import time
    from datetime import datetime, timezone

    from bpcad.agent import bundle as bundle_mod
    from bpcad.agent.handoff import next_steps, no_model_steps, write_handoff
    from bpcad.agent.loop import (
        RunRecord,
        SpecRejected,
        attempt_to_dict,
        ask as run_ask,
        compile_and_verify,
    )
    from bpcad.models.base import NonLocalEndpointError
    from bpcad.models.selector import ProfileError, load_profile

    cfg = _load_config_or_fail()

    if material.strip().lower() not in cfg.data["materials"]:
        _fail("unknown material %r. Configured: %s."
              % (material, ", ".join(cfg.material_names)))

    try:
        profile = load_profile(cfg, machine)
    except NonLocalEndpointError as exc:
        _fail(str(exc))
        return
    except ProfileError as exc:
        _fail(str(exc))
        return

    nozzle_mm = nozzle if nozzle is not None else float(cfg.print_settings["nozzle_mm"])
    layer_mm = layer if layer is not None else float(cfg.print_settings["layer_mm"])

    measurements = None
    if image is not None:
        if not image.is_file():
            _fail("no image at %s" % image)
        measurements = _measure_reference(image)
        typer.echo("measured %s:" % image)
        for k, v in measurements.items():
            typer.echo("   %-24s %s" % (k, v))
        typer.echo("")

    typer.echo(profile.describe())
    if max_seconds:
        typer.echo("wall-clock budget %.0fs" % max_seconds)
    typer.echo("")

    started = time.monotonic()
    started_at = datetime.now(timezone.utc).isoformat()
    staging = Path(out) if out is not None else None

    def report_attempt(attempt) -> None:
        typer.echo("  " + attempt.summary())

    # The scratch directory for a candidate build. A part only reaches its final
    # home once it has verified, so a failed attempt cannot leave a broken STL
    # sitting where a good one used to be.
    import tempfile

    scratch = Path(tempfile.mkdtemp(prefix="bpcad-gen-"))
    holder: dict[str, Any] = {}

    def verify_candidate(spec) -> None:
        if max_seconds and (time.monotonic() - started) > max_seconds:
            raise SpecRejected(
                "the wall-clock budget of %.0fs is spent" % max_seconds,
                stage="budget",
            )
        result, report, stl = compile_and_verify(
            spec, cfg, None, scratch / "out", allow_level_3=allow_level_3
        )
        holder["result"] = result
        holder["report"] = report
        holder["stl"] = stl

    result = run_ask(
        request=request,
        profile=profile,
        material=material,
        nozzle_mm=nozzle_mm,
        layer_mm=layer_mm,
        measurements=measurements,
        on_attempt=report_attempt,
        verify_fn=verify_candidate,
    )

    # Escalate 1 -> 2 ONLY when level 1 is exhausted, and only if a model was
    # actually reached. Composing DSL primitives is a harder task than filling
    # a form, so this is a step down in reliability - worth taking when no
    # template fits, pointless when the daemon is simply not running.
    if (
        not result.ok
        and not result.ladder.never_reached_a_model
        and not (max_seconds and (time.monotonic() - started) > max_seconds)
    ):
        from bpcad.agent.loop import ask_level_2

        typer.echo("")
        typer.echo("level 1 exhausted - escalating to level 2 (DSL primitives)")
        typer.echo("")
        level_1 = result
        result = ask_level_2(
            request=request,
            profile=profile,
            material=material,
            nozzle_mm=nozzle_mm,
            layer_mm=layer_mm,
            why_escalated=level_1.ladder.last_error,
            on_attempt=report_attempt,
            verify_fn=verify_candidate,
        )
        # Keep the whole history, both levels, in the order it happened.
        result.ladder.attempts = level_1.ladder.attempts + result.ladder.attempts
        if not result.ok and not result.problems:
            result.problems = level_1.problems
            result.best_attempt_data = result.best_attempt_data or level_1.best_attempt_data

    elapsed = time.monotonic() - started
    typer.echo("")
    typer.echo("%d attempt(s), %.1fs total" % (len(result.ladder.attempts), elapsed))
    typer.echo("")

    record = RunRecord(
        request=request,
        machine=profile.name,
        started_at=started_at,
        elapsed_s=round(elapsed, 2),
        ok=result.ok,
        level_reached=result.level,
        profile={
            "name": profile.name,
            "host": profile.host,
            "model_primary": profile.model_primary,
            "model_small": profile.model_small,
            "num_ctx": profile.num_ctx,
            "timeout_s": profile.timeout_s,
            "max_attempts_per_level": profile.max_attempts_per_level,
        },
        attempts=[attempt_to_dict(a, result.level) for a in result.ladder.attempts],
        budget={"max_seconds": max_seconds,
                "attempts_per_level": profile.max_attempts_per_level},
    )

    if not result.ok:
        if result.ladder.never_reached_a_model:
            typer.echo(no_model_steps(profile.host, profile.models()))
            target = staging or Path("parts") / _slug(request)
            record.handoff = "no model reachable"
            record.write(target / "run.json")
            raise typer.Exit(code=1)

        target = staging or Path("parts") / _slug(request)
        draft = write_handoff(
            out_dir=target,
            request=request,
            attempt=result.best_attempt_data,
            problems=result.problems,
            machine=result.machine,
            attempts_made=len(result.ladder.attempts),
            elapsed_s=elapsed,
            models_tried=result.models_tried,
            raw_error=result.ladder.last_error,
        )
        record.handoff = str(draft)
        record.write(target / "run.json")
        typer.echo(next_steps(draft))
        typer.echo("")
        typer.echo("Full history: %s" % (target / "run.json"))
        raise typer.Exit(code=1)

    spec = result.spec
    target = staging or Path("parts") / spec.name
    model_used = next(
        (a.model for a in reversed(result.ladder.attempts) if a.ok), ""
    )

    import shutil

    (target / "out").mkdir(parents=True, exist_ok=True)
    final_stl = target / "out" / ("%s.stl" % spec.name)
    shutil.copy2(holder["stl"], final_stl)

    written = bundle_mod.write_bundle(
        spec=spec,
        result=holder["result"],
        report=holder["report"],
        stl=final_stl,
        part_dir=target,
        model_used=model_used,
        machine=profile.name,
        attempts=len(result.ladder.attempts),
        elapsed_s=elapsed,
        render=render,
    )

    record.spec = spec.model_dump(exclude_none=True)
    record.report = holder["report"].to_dict()
    record.write(target / "run.json")

    rep = holder["report"]
    typer.echo("%s   %.2f x %.2f x %.2f mm   %.3f cm3   %d body(s)"
               % (spec.name, *rep.mesh.bbox_mm, rep.mesh.volume_cm3, rep.mesh.body_count))
    typer.echo("supports needed: %s" % ("YES" if rep.overhang.supports_needed else "no"))
    typer.echo("")
    for key in ("spec", "model_py", "stl", "step", "3mf", "preview", "heightmap",
                "section", "report", "regression"):
        if key in written:
            typer.echo("  %s" % written[key])
    typer.echo("  %s" % (target / "run.json"))
    typer.echo("")
    typer.echo("Look at the height map before printing: %s"
               % written.get("heightmap", "(not rendered)"))


def _measure_reference(image: Path) -> dict[str, Any]:
    """
    Measure what can be measured off a reference image.

    Deliberately conservative: silhouette extent and the neutral-grey region,
    both of which are reliable. It does NOT try to guess which measurement
    corresponds to which template parameter - that is the model's job, and a
    wrong mapping asserted here would be worse than no mapping.
    """
    from bpcad.measure.segment import (
        background_cut,
        bbox,
        by_luminance,
        by_saturation,
        largest_component,
    )

    out: dict[str, Any] = {}
    cut = background_cut(image)
    fg = by_luminance(image, 0, cut)
    if not fg.any():
        return {"note": "nothing separated from the background"}

    box = bbox(fg)
    out["silhouette_px"] = "%d wide x %d tall" % (box.width, box.height)
    out["aspect_ratio"] = round(box.width / box.height, 4)

    neutral = by_saturation(image, 0, 15) & fg
    if neutral.any():
        try:
            n = bbox(largest_component(neutral))
            out["largest_neutral_region_px"] = "%d x %d" % (n.width, n.height)
            out["neutral_fraction_of_width"] = round(n.width / box.width, 4)
        except ValueError:
            pass
    out["note"] = "pixel measurements - scale them with a known real dimension"
    return out


# ---------------------------------------------------------------------------
# spec
# ---------------------------------------------------------------------------


@spec_app.command("list")
def spec_list() -> None:
    """List the templates available."""
    from bpcad.spec import registry

    typer.echo("templates:")
    typer.echo(registry.catalogue())


@spec_app.command("explain")
def spec_explain(
    template: str = typer.Argument(..., help="Template name."),
) -> None:
    """
    Print a template's full parameter schema: units, defaults and bounds.

    This is the primary interface when the model cannot do the job. The fallback
    for a failed generation is a person editing YAML, and that path has to be
    pleasant.
    """
    from bpcad.spec import registry

    try:
        typer.echo(registry.explain(template))
    except registry.TemplateError as exc:
        _fail(str(exc))


@spec_app.command("ops")
def spec_ops() -> None:
    """List the level-2 DSL operations and the anchors they address."""
    from bpcad.spec.dsl import EDGE_GROUPS, FACE_FRAMES, OP_NAMES

    typer.echo("level-2 operations:")
    for name in OP_NAMES:
        typer.echo("   %s" % name)
    typer.echo("")
    typer.echo("anchors (ops address faces by these names, never by CadQuery selector):")
    for name in sorted(FACE_FRAMES):
        typer.echo("   %s" % name)
    typer.echo("")
    typer.echo("edge groups:")
    for name in sorted(EDGE_GROUPS):
        typer.echo("   %s" % name)


# ---------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------


@app.command("build")
def build_cmd(
    spec_path: Path = typer.Argument(..., help="Path to a spec.yaml."),
    out: Optional[Path] = typer.Option(
        None, "--out", help="Output directory. Defaults to <spec dir>/out."
    ),
    allow_level_3: bool = typer.Option(
        False, "--allow-level-3",
        help="Permit raw CadQuery. Off by default; output is marked REVIEW REQUIRED.",
    ),
    step: bool = typer.Option(True, "--step/--no-step", help="Also write a STEP file."),
    verify: bool = typer.Option(
        True, "--verify/--no-verify", help="Check the exported mesh afterwards."
    ),
) -> None:
    """
    Build a part from a spec file. No model involved at any point.

    A hand-written spec and a model-written spec take the identical path
    through here, which is what makes the model a convenience layer rather than
    a dependency.
    """
    from bpcad.build.compile import (
        Level3NotAllowed,
        SpecError,
        check_export,
        compile_spec,
        export_solid,
        load_spec,
    )

    cfg = _load_config_or_fail()

    try:
        spec, base_dir = load_spec(spec_path)
    except SpecError as exc:
        _fail(str(exc))
        return

    if spec.material.strip().lower() not in cfg.data["materials"]:
        _fail(
            "spec names material %r, which is not configured. Configured: %s."
            % (spec.material, ", ".join(cfg.material_names))
        )

    try:
        result = compile_spec(spec, base_dir=base_dir, allow_level_3=allow_level_3)
    except Level3NotAllowed as exc:
        _fail(str(exc))
        return
    except SpecError as exc:
        _fail(str(exc))
        return

    out_dir = out if out is not None else Path(base_dir) / "out"
    tol = spec.stl_tolerance if spec.stl_tolerance is not None else float(cfg.export["stl_tolerance"])
    ang = (
        spec.stl_angular_tolerance
        if spec.stl_angular_tolerance is not None
        else float(cfg.export["stl_angular_tolerance"])
    )

    stl = export_solid(result.print_solid, Path(out_dir) / ("%s.stl" % spec.name), tol, ang)
    written = [stl]
    if step:
        written.append(
            export_solid(result.print_solid, Path(out_dir) / ("%s.step" % spec.name))
        )

    typer.echo("built %s  (level %d%s)"
               % (spec.name, spec.level,
                  ", template %s" % spec.template if spec.template else ""))
    typer.echo("")

    if result.log.lines():
        typer.echo("BUILD LOG")
        for line in result.log.lines():
            typer.echo("   %s" % line)
        typer.echo("")

    if result.derived:
        typer.echo("DERIVED")
        for k, v in result.derived.items():
            typer.echo("   %-32s %.4f" % (k, v))
        typer.echo("")

    if result.features:
        from bpcad.verify.features import check_features

        fr = check_features(
            result.features,
            nozzle_mm=spec.nozzle_mm,
            min_feature_multiple=float(cfg.limits["min_feature_multiple"]),
        )
        typer.echo("FEATURE SIZES against a %.2f mm nozzle (threshold %.2f mm)"
                   % (fr.nozzle_mm, fr.threshold_mm))
        for c in fr.checks:
            typer.echo("   %-30s %7.3f mm   %s" % (c.name, c.value_mm, c.status))
        typer.echo("")

    if result.assumptions:
        typer.echo("ASSUMPTIONS - these could NOT be measured")
        for a in result.assumptions:
            typer.echo("   %s = %s %s" % (a.name, a.value, a.units))
            typer.echo("      %s" % a.why)
        typer.echo("")

    if result.scale_departures:
        typer.echo("DELIBERATE DEPARTURES FROM TRUE SCALE")
        for sd in result.scale_departures:
            typer.echo("   %-22s %.2fx  (true %.3f mm, built %.3f mm)"
                       % (sd.name, sd.factor, sd.true_mm, sd.used_mm))
            typer.echo("      %s" % sd.why)
        typer.echo("")

    for p in written:
        typer.echo(str(p))

    if verify:
        problems = check_export(stl, expected_bodies=result.body_count_expected)
        typer.echo("")
        if problems:
            typer.secho("EXPORT PROBLEMS", fg=typer.colors.RED)
            for prob in problems:
                typer.echo("   - %s" % prob)
            raise typer.Exit(code=1)
        typer.echo("export verified: watertight, %d body(s)" % result.body_count_expected)


# ---------------------------------------------------------------------------
# measure
# ---------------------------------------------------------------------------


@measure_app.command("box")
def measure_box(
    image: Path = typer.Argument(..., help="Image to measure."),
    threshold: Optional[float] = typer.Option(
        None,
        "--threshold",
        help="Luminance cut for foreground. Default is Otsu, chosen from the image.",
    ),
    saturation_max: float = typer.Option(
        15.0, "--saturation-max", help="Channel spread below which a pixel counts as neutral."
    ),
    min_frac: float = typer.Option(
        0.5, "--min-frac", help="Line coverage needed for a row or column to count."
    ),
) -> None:
    """
    Silhouette extent, wide row and column bands, and the neutral-grey regions.

    Everything here is a measurement, not a guess. The threshold defaults to
    Otsu's, picked from the image, because a threshold chosen by eye lands a
    pixel either side of an antialiased edge.
    """
    import numpy as np

    from bpcad.measure.segment import (
        auto_threshold,
        bbox,
        by_luminance,
        by_saturation,
        largest_component,
        runs,
    )

    if not image.is_file():
        _fail("no image at %s" % image)

    thr = threshold if threshold is not None else auto_threshold(image)
    fg = by_luminance(image, 0, thr)
    if not fg.any():
        _fail("nothing is below the threshold %.1f - the image may be inverted" % thr)

    typer.echo("image           %s" % image)
    typer.echo("threshold       %.1f%s" % (thr, "" if threshold is not None else "  (Otsu, from the image)"))
    typer.echo("silhouette      %s" % bbox(fg))
    typer.echo("")

    row_bands = runs(fg, "row", min_frac)
    col_bands = runs(fg, "col", min_frac)
    typer.echo("row bands covering >= %.0f%% of the width:" % (100 * min_frac))
    for s_, e_ in row_bands:
        typer.echo("   rows %4d - %4d   (%d px)" % (s_, e_, e_ - s_ + 1))
    typer.echo("column bands covering >= %.0f%% of the height:" % (100 * min_frac))
    for s_, e_ in col_bands:
        typer.echo("   cols %4d - %4d   (%d px)" % (s_, e_, e_ - s_ + 1))

    neutral = by_saturation(image, 0, saturation_max) & fg
    if neutral.any():
        typer.echo("")
        typer.echo("neutral (spread <= %.0f) largest region:" % saturation_max)
        typer.echo("   %s" % bbox(largest_component(neutral)))


@measure_app.command("scan")
def measure_scan(
    image: Path = typer.Argument(..., help="Image to measure."),
    line: int = typer.Option(..., "--line", help="Row or column index to scan."),
    axis: str = typer.Option("row", "--axis", help="'row' or 'col'."),
    threshold: Optional[float] = typer.Option(
        None, "--threshold", help="Luminance cut. Default is Otsu."
    ),
) -> None:
    """
    Sub-pixel spans along one scanline.

    An integer edge quantises to half a pixel. On an antialiased render the
    luminance ramp across an edge carries real sub-pixel information, and this
    reads it out - which is what makes a residual worth quoting.
    """
    from bpcad.measure.profile import spans, spans_subpixel
    from bpcad.measure.segment import auto_threshold

    if not image.is_file():
        _fail("no image at %s" % image)
    if axis not in ("row", "col", "column"):
        _fail("axis must be 'row' or 'col', got %r" % axis)

    thr = threshold if threshold is not None else auto_threshold(image)
    try:
        whole = spans(image, line, thr, axis=axis)
        sub = spans_subpixel(image, line, thr, axis=axis)
    except IndexError as exc:
        _fail(str(exc))
        return

    typer.echo("%s %d, threshold %.1f" % (axis, line, thr))
    typer.echo("")
    typer.echo("   integer spans                sub-pixel spans              width")
    for i, (a_, b_) in enumerate(whole):
        if i < len(sub):
            sa, sb = sub[i]
            typer.echo("   %6d - %-6d            %10.3f - %-10.3f   %8.3f px"
                       % (a_, b_, sa, sb, sb - sa))
        else:
            typer.echo("   %6d - %-6d            (edge clipped by the image)" % (a_, b_))


@measure_app.command("trace")
def measure_trace(
    image: Path = typer.Argument(..., help="Image to trace to polygon outlines."),
    out: Optional[Path] = typer.Option(
        None, "--out", help="Write the normalised outlines as JSON."
    ),
    upsample: int = typer.Option(10, "--upsample", help="Upsample factor for sub-pixel contours."),
    level: float = typer.Option(0.55, "--level", help="Iso level on the normalised luminance."),
    blur: Optional[float] = typer.Option(None, "--blur", help="Gaussian blur. Default 1.1 x upsample."),
    simplify: Optional[float] = typer.Option(
        None, "--simplify", help="Polygon tolerance. Default 0.055 x upsample."
    ),
) -> None:
    """
    Trace an image to simplified polygon outlines with hole flags.

    The output is the format the keyring template consumes: coordinates
    normalised so the total WIDTH is 1.0, x right, y up, origin at the
    bottom-left of the bounding box.
    """
    import json as _json

    from bpcad.measure.contour import trace

    if not image.is_file():
        _fail("no image at %s" % image)

    try:
        result = trace(image, upsample=upsample, level=level, blur=blur, simplify=simplify)
    except ValueError as exc:
        _fail(str(exc))
        return

    if not result.shapes:
        _fail(
            "nothing traced. Try a different --level, or --blur 0 if the source "
            "is already clean line art."
        )

    data = result.normalised(source=str(image))
    typer.echo("outers %d   holes %d   height/width %.5f"
               % (len(result.outers), len(result.holes), data["aspect_h"]))
    typer.echo("thinnest bar stroke %.5f of total width" % result.min_stroke())
    for i, sh in enumerate(result.shapes):
        typer.echo("   shape %2d  %-5s  %3d vertices" % (i, "hole" if sh.hole else "outer", len(sh.pts)))

    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(_json.dumps(data))
        typer.echo("")
        typer.echo(str(out))


# ---------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------


@app.command("verify")
def verify_cmd(
    stl: Path = typer.Argument(..., help="STL file to verify."),
    nozzle: Optional[float] = typer.Option(
        None, "--nozzle", help="Nozzle width in mm. Defaults to config [print].nozzle_mm."
    ),
    material: Optional[str] = typer.Option(
        None, "--material", help="Material name, recorded in the report."
    ),
    print_axis: str = typer.Option(
        "z", "--print-axis", help="Build direction: x, y or z."
    ),
    max_overhang: Optional[float] = typer.Option(
        None, "--max-overhang", help="Overhang threshold in degrees from vertical."
    ),
    max_bridge_gap: Optional[float] = typer.Option(
        None,
        "--max-bridge-gap",
        help="Largest fall an underside may have and still be closed by the layer above, mm.",
    ),
    features: Optional[Path] = typer.Option(
        None,
        "--features",
        help=(
            "JSON file of {\"name\": size_mm} to lint against the nozzle. "
            "From Phase 3 a template supplies these itself."
        ),
    ),
    baseline: Optional[Path] = typer.Option(
        None, "--baseline", help="Regression baseline file. Defaults beside the part."
    ),
    update_baseline: bool = typer.Option(
        False, "--update-baseline", help="Accept the current geometry as the new baseline."
    ),
    as_json: bool = typer.Option(False, "--json", help="Emit the report as JSON."),
    markdown: bool = typer.Option(False, "--markdown", help="Emit the report as Markdown."),
) -> None:
    """
    Check a mesh: watertight, single body, feature sizes, overhangs, and
    whether the geometry changed since the last accepted build.

    Exits 1 if anything failed, so this is usable in a script.
    """
    from bpcad.verify.features import check_features
    from bpcad.verify.mesh import check_mesh
    from bpcad.verify.overhang import overhang_report
    from bpcad.verify.mesh import load_mesh
    from bpcad.verify.probe import surface_levels
    from bpcad.verify.regression import baseline_path_for, check_regression
    from bpcad.verify.report import VerifyReport

    cfg = _load_config_or_fail()

    if material is not None:
        try:
            # Validate the NAME only. Phase 1 needs no material numbers, so an
            # UNSET clearance must not block a mesh check.
            if material.strip().lower() not in cfg.data["materials"]:
                raise ConfigError(
                    "unknown material %r. Configured materials are: %s"
                    % (material, ", ".join(cfg.material_names))
                )
        except ConfigError as exc:
            _fail(str(exc))

    nozzle_mm = nozzle if nozzle is not None else float(cfg.print_settings["nozzle_mm"])
    max_deg = (
        max_overhang if max_overhang is not None else float(cfg.limits["max_overhang_deg"])
    )
    bridge_gap = (
        max_bridge_gap
        if max_bridge_gap is not None
        else float(cfg.limits["max_bridge_gap_mm"])
    )

    try:
        mesh_report = check_mesh(stl)
        mesh = load_mesh(stl)
    except (FileNotFoundError, ValueError) as exc:
        _fail(str(exc))
        return

    feature_report = None
    if features is not None:
        if not features.is_file():
            _fail("no feature file at %s" % features)
        try:
            data = json.loads(features.read_text())
        except json.JSONDecodeError as exc:
            _fail("could not parse %s: %s" % (features, exc))
            return
        feature_report = check_features(
            {str(k): float(v) for k, v in data.items()},
            nozzle_mm=nozzle_mm,
            min_feature_multiple=float(cfg.limits["min_feature_multiple"]),
        )

    path = baseline if baseline is not None else baseline_path_for(stl)
    regression = check_regression(mesh_report, path, update=update_baseline)

    report = VerifyReport(
        path=str(stl),
        nozzle_mm=nozzle_mm,
        print_axis=print_axis,
        material=material,
        mesh=mesh_report,
        overhang=overhang_report(
            mesh, print_axis=print_axis, max_deg=max_deg, max_bridge_gap_mm=bridge_gap
        ),
        levels=surface_levels(mesh, axis=print_axis),
        features=feature_report,
        regression=regression,
    )

    if as_json:
        typer.echo(report.as_json())
    elif markdown:
        typer.echo(report.as_markdown())
    else:
        typer.echo(report.as_text())

    if not report.ok:
        raise typer.Exit(code=1)


# ---------------------------------------------------------------------------
# render
# ---------------------------------------------------------------------------


@app.command("render")
def render_cmd(
    stl: Path = typer.Argument(..., help="STL file to render."),
    views: str = typer.Option(
        "front,3q,side,above", "--views", help="Comma-separated view names, or 'none'."
    ),
    heightmap: bool = typer.Option(
        False, "--heightmap", help="Also write the surface height map."
    ),
    section: bool = typer.Option(
        False, "--section", help="Also write a cutaway through the middle."
    ),
    axis: str = typer.Option(
        "z", "--axis", help="Height map axis, and the axis the section cuts across."
    ),
    out: Path = typer.Option(Path("out"), "--out", help="Output directory."),
    width: int = typer.Option(900, "--width", help="Image width in pixels."),
    height: int = typer.Option(700, "--height", help="Image height in pixels."),
) -> None:
    """
    Render standard views, the height map and a cutaway.

    The height map is the one to look at. A flat-shaded render cannot show a
    recess whose floor shares a normal with the surface around it; colouring by
    height can.
    """
    from bpcad.render import views as V
    from bpcad.verify.mesh import load_mesh
    from bpcad.verify.probe import surface_levels

    try:
        mesh = load_mesh(stl)
    except (FileNotFoundError, ValueError) as exc:
        _fail(str(exc))
        return

    stem = Path(stl).stem
    wanted = [v.strip() for v in views.split(",") if v.strip() and v.strip() != "none"]
    unknown = [v for v in wanted if v not in V.VIEWS]
    if unknown:
        _fail(
            "unknown view(s) %s. Known views: %s"
            % (", ".join(unknown), ", ".join(sorted(V.VIEWS)))
        )

    written: list[Path] = []
    if wanted:
        paths = V.standard_views(mesh, out, which=wanted, stem=stem, width=width, height=height)
        written.extend(paths[v] for v in wanted)

    if heightmap:
        written.append(
            V.height_map_image(mesh, Path(out) / ("%s_heightmap.png" % stem), axis=axis)
        )

    if section:
        cut_axis = {"z": "y", "y": "x", "x": "z"}[axis]
        try:
            written.append(
                V.section(mesh, Path(out) / ("%s_section.png" % stem), axis=cut_axis)
            )
        except ValueError as exc:
            _fail(str(exc))

    for p in written:
        typer.echo(str(p))

    if heightmap:
        levels = surface_levels(mesh, axis=axis)
        typer.echo("")
        typer.echo("%d distinct surface levels facing +%s:" % (len(levels), axis))
        for lv in levels:
            typer.echo("   %8.3f mm   %10.2f mm2" % (lv.height_mm, lv.area_mm2))


if __name__ == "__main__":
    app()
