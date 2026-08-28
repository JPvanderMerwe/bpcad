"""
The stable programmatic interface to bpcad.

WHY THIS EXISTS
---------------
The CLI and the GUI must not each grow their own copy of the workflow. When
they do, they drift: a fix lands in one and not the other, and eventually they
disagree about what a part is. So both sit on this module, and this module is
the only place that knows how the steps join up.

It is also the answer to "can I drive this from a script": everything here
takes plain arguments and returns plain objects, no Qt, no typer, no printing.

    from bpcad import api

    part = api.build("parts/vent/spec.yaml")
    print(part.report.mesh.volume_cm3, part.stl)

    for r in api.generate("a louvre vent 90 mm wide", on_event=print):
        ...

NOTHING HERE NEEDS A MODEL except generate() and ask(). That is the whole
design: build, verify, render and measure are deterministic Python and work
with the network cable out.
"""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

from bpcad.config import Config, load_config

# ---------------------------------------------------------------------------
# results
# ---------------------------------------------------------------------------


@dataclass
class PartResult:
    """A built part: where it is, what it measured, and how it was made."""

    name: str
    spec: Any                       # PartSpec
    build: Any                      # BuildResult
    report: Any                     # VerifyReport
    stl: Path
    part_dir: Path
    files: dict[str, Path] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.report.ok

    @property
    def volume_cm3(self) -> float:
        return self.report.mesh.volume_cm3

    @property
    def envelope_mm(self) -> tuple[float, float, float]:
        return self.report.mesh.bbox_mm

    @property
    def needs_supports(self) -> bool:
        return self.report.overhang.supports_needed


@dataclass
class GenerateResult:
    """What a model-driven run produced, successful or not."""

    ok: bool
    part: PartResult | None = None
    spec: Any = None
    attempts: list[Any] = field(default_factory=list)
    elapsed_s: float = 0.0
    machine: str = ""
    models_tried: list[str] = field(default_factory=list)
    draft_path: Path | None = None
    problems: list[Any] = field(default_factory=list)
    message: str = ""

    @property
    def attempt_count(self) -> int:
        return len(self.attempts)


class ApiError(RuntimeError):
    """Anything the caller can act on. Carries a message worth showing."""


# ---------------------------------------------------------------------------
# configuration and catalogue
# ---------------------------------------------------------------------------


def config(path: str | Path | None = None) -> Config:
    """Load the configuration, raising ApiError with a readable message."""
    from bpcad.config import ConfigError

    try:
        return load_config(path)
    except ConfigError as exc:
        raise ApiError(str(exc)) from exc


def templates() -> list[str]:
    """Every template name the registry knows."""
    from bpcad.spec import registry

    return registry.names()


def template_info(name: str) -> dict[str, Any]:
    """
    A template described as data: summary, print notes, and every parameter
    with its type, default, bounds, units and description.

    This is what lets a GUI generate a parameter form with no per-template code.
    A new template appears in the interface for free, which is the only way the
    form can be trusted to stay in step with the schema.
    """
    from bpcad.spec import registry

    try:
        t = registry.get(name)
    except registry.TemplateError as exc:
        raise ApiError(str(exc)) from exc

    params = []
    for fname, fld in t.params_model.model_fields.items():
        bounds: dict[str, float] = {}
        for meta in fld.metadata:
            for attr in ("ge", "gt", "le", "lt"):
                v = getattr(meta, attr, None)
                if v is not None:
                    bounds[attr] = v

        annotation = fld.annotation
        optional = False
        base = annotation
        args = getattr(annotation, "__args__", ())
        if args:
            non_none = [a for a in args if a is not type(None)]
            optional = len(non_none) < len(args)
            if non_none:
                base = non_none[0]

        params.append({
            "name": fname,
            "type": getattr(base, "__name__", str(base)),
            "optional": optional,
            "required": fld.is_required(),
            "default": None if fld.is_required() else fld.default,
            "bounds": bounds,
            "units": _units_of(fname),
            "description": fld.description or "",
        })

    return {
        "name": t.name,
        "summary": t.summary,
        "anchors": list(t.anchors),
        "print_notes": list(t.print_notes),
        "params": params,
    }


def _units_of(field_name: str) -> str:
    """Units live in the field name by convention, so read them back out."""
    if field_name.endswith("_mm"):
        return "mm"
    if field_name.endswith("_deg"):
        return "deg"
    if field_name.endswith("_pct"):
        return "%"
    if field_name.endswith("_fraction"):
        return "fraction"
    return ""


def dsl_ops() -> dict[str, Any]:
    """The level-2 operations, anchors and edge groups, as data."""
    from bpcad.spec.dsl import EDGE_GROUPS, FACE_FRAMES, OP_NAMES

    return {
        "ops": list(OP_NAMES),
        "anchors": sorted(FACE_FRAMES),
        "edge_groups": sorted(EDGE_GROUPS),
    }


# ---------------------------------------------------------------------------
# specs
# ---------------------------------------------------------------------------


def load_spec(path: str | Path):
    """Read and validate a spec.yaml. Returns (PartSpec, base_dir)."""
    from bpcad.build.compile import SpecError, load_spec as _load

    try:
        return _load(path)
    except SpecError as exc:
        raise ApiError(str(exc)) from exc


def validate_spec(data: dict[str, Any]) -> Any:
    """
    Validate a spec given as a plain dict, without building anything.

    A GUI form calls this on every edit, so the error has to be per-field and
    readable rather than a stack trace.
    """
    from pydantic import ValidationError

    from bpcad.build.compile import SpecError, validate_params
    from bpcad.spec.schema import PartSpec, format_validation_error

    try:
        spec = PartSpec.model_validate(data)
    except ValidationError as exc:
        raise ApiError(format_validation_error(exc, "this spec is not valid:")) from exc

    if spec.level == 1:
        try:
            validate_params(spec)
        except SpecError as exc:
            raise ApiError(str(exc)) from exc
    return spec


def spec_problems(data: dict[str, Any]) -> list[Any]:
    """
    Per-field problems for a spec, as a list rather than an exception.

    Live form validation wants to mark three fields red at once, not stop at
    the first one.
    """
    from pydantic import ValidationError

    from bpcad.agent.handoff import problems_from_validation_error
    from bpcad.spec.schema import PartSpec

    problems: list[Any] = []
    try:
        spec = PartSpec.model_validate(data)
    except ValidationError as exc:
        return problems_from_validation_error(exc)

    if spec.level == 1 and spec.template:
        from bpcad.spec import registry

        try:
            registry.get(spec.template).params_model.model_validate(spec.params)
        except registry.TemplateError:
            return problems
        except ValidationError as exc:
            for p in problems_from_validation_error(exc):
                p.field = "params.%s" % p.field
                problems.append(p)
    return problems


def write_spec(spec, path: str | Path) -> Path:
    """Write a spec.yaml. This is the durable artifact, so it is written plainly."""
    from bpcad.agent.bundle import write_spec as _write

    return _write(spec, Path(path))


# ---------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------


def build(
    spec_path: str | Path | None = None,
    spec=None,
    base_dir: str | Path | None = None,
    out_dir: str | Path | None = None,
    cfg: Config | None = None,
    allow_level_3: bool = False,
    render: bool = False,
    bundle: bool = False,
) -> PartResult:
    """
    Build a part from a spec file or a PartSpec. NO MODEL INVOLVED.

    With bundle=True it writes the full part directory - spec, model.py, STEP,
    3MF, previews, report.md, regression.json - exactly as `bpcad gen` does on
    success.
    """
    from bpcad.agent.loop import SpecRejected, compile_and_verify

    cfg = cfg or config()

    if spec is None:
        if spec_path is None:
            raise ApiError("build() needs either spec_path or spec")
        spec, resolved_base = load_spec(spec_path)
    else:
        resolved_base = Path(base_dir) if base_dir else None

    if base_dir is not None:
        resolved_base = Path(base_dir)

    part_dir = (
        Path(out_dir) if out_dir is not None
        else (Path(spec_path).parent if spec_path else Path("parts") / spec.name)
    )

    try:
        result, report, stl = compile_and_verify(
            spec, cfg, resolved_base, part_dir / "out", allow_level_3=allow_level_3
        )
    except SpecRejected as exc:
        raise ApiError(str(exc)) from exc

    files: dict[str, Path] = {"stl": stl}
    if bundle:
        from bpcad.agent import bundle as bundle_mod

        files = bundle_mod.write_bundle(
            spec=spec, result=result, report=report, stl=stl,
            part_dir=part_dir, render=render,
        )
    elif render:
        files.update(render_part(stl, part_dir / "out", print_axis=spec.print_axis))

    return PartResult(
        name=spec.name, spec=spec, build=result, report=report,
        stl=stl, part_dir=part_dir, files=files,
    )


def render_part(
    stl: str | Path,
    out_dir: str | Path,
    views: Iterable[str] = ("front", "3q", "side", "above"),
    heightmap: bool = True,
    section: bool = True,
    print_axis: str = "z",
) -> dict[str, Path]:
    """Render a mesh to images. Pure CPU, no GPU, no network."""
    from bpcad.render import views as V
    from bpcad.verify.mesh import load_mesh

    mesh = load_mesh(stl)
    out = Path(out_dir)
    stem = Path(stl).stem
    written: dict[str, Path] = {}

    for name in views:
        written[name] = V.render_view_to(mesh, out / ("%s_%s.png" % (stem, name)), view=name)
    if heightmap:
        written["heightmap"] = V.height_map_image(
            mesh, out / ("%s_heightmap.png" % stem), axis=print_axis
        )
    if section:
        cut = {"z": "y", "y": "x", "x": "z"}[print_axis]
        try:
            written["section"] = V.section(mesh, out / ("%s_section.png" % stem), axis=cut)
        except ValueError:
            pass
    return written


def verify(
    stl: str | Path,
    nozzle_mm: float | None = None,
    print_axis: str = "z",
    features: dict[str, float] | None = None,
    material: str | None = None,
    cfg: Config | None = None,
    baseline: str | Path | None = None,
    update_baseline: bool = False,
):
    """Check an existing mesh. Returns a VerifyReport."""
    from bpcad.verify.features import check_features
    from bpcad.verify.mesh import check_mesh, load_mesh
    from bpcad.verify.overhang import overhang_report
    from bpcad.verify.probe import surface_levels
    from bpcad.verify.regression import baseline_path_for, check_regression
    from bpcad.verify.report import VerifyReport

    cfg = cfg or config()
    nozzle = nozzle_mm if nozzle_mm is not None else float(cfg.print_settings["nozzle_mm"])

    try:
        mesh_report = check_mesh(stl)
        mesh = load_mesh(stl)
    except (FileNotFoundError, ValueError) as exc:
        raise ApiError(str(exc)) from exc

    regression = None
    if baseline is not None or update_baseline:
        regression = check_regression(
            mesh_report,
            Path(baseline) if baseline else baseline_path_for(stl),
            update=update_baseline,
        )

    return VerifyReport(
        path=str(stl),
        nozzle_mm=nozzle,
        print_axis=print_axis,
        material=material,
        mesh=mesh_report,
        overhang=overhang_report(
            mesh, print_axis=print_axis,
            max_deg=float(cfg.limits["max_overhang_deg"]),
            max_bridge_gap_mm=float(cfg.limits["max_bridge_gap_mm"]),
        ),
        levels=surface_levels(mesh, axis=print_axis),
        features=check_features(
            features, nozzle_mm=nozzle,
            min_feature_multiple=float(cfg.limits["min_feature_multiple"]),
        ) if features else None,
        regression=regression,
    )


# ---------------------------------------------------------------------------
# the part library
# ---------------------------------------------------------------------------


@dataclass
class PartEntry:
    """One part on disk, as far as it can be known without building it."""

    name: str
    directory: Path
    spec_path: Path | None = None
    stl: Path | None = None
    report_md: Path | None = None
    run_json: Path | None = None
    draft: Path | None = None
    images: dict[str, Path] = field(default_factory=dict)

    @property
    def is_draft(self) -> bool:
        """A handoff waiting to be fixed by hand, with no spec.yaml yet."""
        return self.spec_path is None and self.draft is not None

    @property
    def built(self) -> bool:
        return self.stl is not None and self.stl.is_file()


def parts(root: str | Path = "parts") -> list[PartEntry]:
    """Everything under parts/, including drafts that failed and need editing."""
    base = Path(root)
    if not base.is_dir():
        return []

    out: list[PartEntry] = []
    for d in sorted(p for p in base.iterdir() if p.is_dir()):
        spec = d / "spec.yaml"
        draft = d / "spec.draft.yaml"
        stls = sorted((d / "out").glob("*.stl")) if (d / "out").is_dir() else []
        images: dict[str, Path] = {}
        if (d / "out").is_dir():
            for png in sorted((d / "out").glob("*.png")):
                key = png.stem.split("_")[-1] if "_" in png.stem else png.stem
                images[key] = png
        out.append(PartEntry(
            name=d.name,
            directory=d,
            spec_path=spec if spec.is_file() else None,
            stl=stls[0] if stls else None,
            report_md=(d / "report.md") if (d / "report.md").is_file() else None,
            run_json=(d / "run.json") if (d / "run.json").is_file() else None,
            draft=draft if draft.is_file() else None,
            images=images,
        ))
    return out


# ---------------------------------------------------------------------------
# measurement
# ---------------------------------------------------------------------------


def measure_image(image: str | Path) -> dict[str, Any]:
    """Silhouette extent and the largest neutral region. Measured, not guessed."""
    from bpcad.measure.segment import (
        background_cut, bbox, by_luminance, by_saturation, largest_component,
    )

    cut = background_cut(image)
    fg = by_luminance(image, 0, cut)
    if not fg.any():
        raise ApiError(
            "nothing separated from the background at a cut of %.1f. The image "
            "may be inverted, or the object may touch the border." % cut
        )
    box = bbox(fg)
    out: dict[str, Any] = {
        "background_cut": round(cut, 2),
        "silhouette": box,
        "width_px": box.width,
        "height_px": box.height,
        "aspect": round(box.width / box.height, 5),
    }
    neutral = by_saturation(image, 0, 15) & fg
    if neutral.any():
        try:
            out["neutral_region"] = bbox(largest_component(neutral))
        except ValueError:
            pass
    return out


def scanline(image: str | Path, line: int, axis: str = "row", threshold: float | None = None):
    """Sub-pixel spans along one row or column."""
    from bpcad.measure.profile import spans, spans_subpixel
    from bpcad.measure.segment import background_cut

    thr = threshold if threshold is not None else background_cut(image)
    try:
        return {
            "threshold": round(thr, 2),
            "integer": spans(image, line, thr, axis=axis),
            "subpixel": spans_subpixel(image, line, thr, axis=axis),
        }
    except IndexError as exc:
        raise ApiError(str(exc)) from exc


def fit_circle(points):
    """Least-squares circle. Always returns the residual - that is the point."""
    from bpcad.measure.fit import circle

    try:
        return circle(points)
    except ValueError as exc:
        raise ApiError(str(exc)) from exc


def trace_logo(image: str | Path, **kwargs):
    """Trace an image to normalised polygon outlines with hole flags."""
    from bpcad.measure.contour import trace

    try:
        return trace(image, **kwargs)
    except ValueError as exc:
        raise ApiError(str(exc)) from exc


# ---------------------------------------------------------------------------
# the model layer
# ---------------------------------------------------------------------------


def machines(cfg: Config | None = None) -> list[str]:
    cfg = cfg or config()
    return cfg.machine_names


def detect_machine(cfg: Config | None = None) -> str:
    from bpcad.models.selector import ProfileError, detect_machine as _detect

    cfg = cfg or config()
    try:
        return _detect(cfg)
    except ProfileError as exc:
        raise ApiError(str(exc)) from exc


def model_status(machine: str | None = None, cfg: Config | None = None) -> dict[str, Any]:
    """
    Whether a model is reachable, and what the daemon has.

    Never raises for the ordinary "it is not running" case - a GUI asks this on
    a timer and must not have to guard it.
    """
    import httpx

    from bpcad.models.base import NonLocalEndpointError, assert_local_endpoint
    from bpcad.models.selector import ProfileError, has_cuda_device

    cfg = cfg or config()
    out: dict[str, Any] = {
        "available": False, "models": [], "loaded": [],
        "cuda": has_cuda_device(), "error": "",
    }
    try:
        name = machine or detect_machine(cfg)
    except ApiError as exc:
        out["error"] = str(exc)
        return out

    table = cfg.machine(name)
    out.update({
        "machine": name,
        "host": table["host"],
        "model_primary": table["model_primary"],
        "model_small": table["model_small"],
        "unset": table["model_primary"] == "UNSET",
    })

    try:
        assert_local_endpoint(table["host"], cfg.allowed_model_hosts)
    except NonLocalEndpointError as exc:
        out["error"] = str(exc)
        return out

    host = str(table["host"]).rstrip("/")
    try:
        with httpx.Client(timeout=4.0) as client:
            tags = client.get("%s/api/tags" % host).json()
            ps = client.get("%s/api/ps" % host).json()
    except Exception as exc:
        out["error"] = "daemon at %s is not answering (%s)" % (host, type(exc).__name__)
        return out

    out["available"] = True
    out["models"] = [
        {"name": m.get("name", "?"), "gb": round((m.get("size") or 0) / 1e9, 2)}
        for m in sorted(tags.get("models", []), key=lambda m: m.get("name", ""))
    ]
    for m in ps.get("models", []):
        total, vram = m.get("size") or 0, m.get("size_vram") or 0
        out["loaded"].append({
            "name": m.get("name", "?"),
            "gb": round(total / 1e9, 2),
            "processor": "100% CPU" if vram == 0 else (
                "100% GPU" if vram >= total else "%d%% GPU" % round(100 * vram / total)
            ),
        })
    return out


def ask(
    request: str,
    machine: str | None = None,
    material: str = "petg",
    nozzle_mm: float | None = None,
    layer_mm: float | None = None,
    cfg: Config | None = None,
    on_event: Callable[[str, Any], None] | None = None,
) -> GenerateResult:
    """Ask the local model for a spec. Generation only - see generate() to build."""
    return _run(request, machine, material, nozzle_mm, layer_mm, cfg,
                on_event, build_it=False, out_dir=None, allow_level_3=False,
                escalate=True, render=False)


def generate(
    request: str,
    machine: str | None = None,
    material: str = "petg",
    nozzle_mm: float | None = None,
    layer_mm: float | None = None,
    out_dir: str | Path | None = None,
    cfg: Config | None = None,
    allow_level_3: bool = False,
    escalate: bool = True,
    render: bool = True,
    on_event: Callable[[str, Any], None] | None = None,
) -> GenerateResult:
    """
    Prompt to verified, printable bundle.

    `on_event(kind, payload)` is called as the run proceeds - "attempt",
    "escalate", "building", "done" - so a caller can show progress during a run
    that takes minutes. It is the only way a GUI stays honest about what is
    happening.
    """
    return _run(request, machine, material, nozzle_mm, layer_mm, cfg,
                on_event, build_it=True, out_dir=out_dir,
                allow_level_3=allow_level_3, escalate=escalate, render=render)


def _run(
    request, machine, material, nozzle_mm, layer_mm, cfg, on_event,
    build_it, out_dir, allow_level_3, escalate, render,
) -> GenerateResult:
    """The shared body of ask() and generate()."""
    import time

    from bpcad.agent.handoff import write_handoff
    from bpcad.agent.loop import SpecRejected, ask as run_ask, ask_level_2, compile_and_verify
    from bpcad.models.base import NonLocalEndpointError
    from bpcad.models.selector import ProfileError, load_profile

    cfg = cfg or config()

    if material.strip().lower() not in cfg.data["materials"]:
        raise ApiError(
            "unknown material %r. Configured: %s."
            % (material, ", ".join(cfg.material_names))
        )

    try:
        profile = load_profile(cfg, machine)
    except (ProfileError, NonLocalEndpointError) as exc:
        raise ApiError(str(exc)) from exc

    nozzle = nozzle_mm if nozzle_mm is not None else float(cfg.print_settings["nozzle_mm"])
    layer = layer_mm if layer_mm is not None else float(cfg.print_settings["layer_mm"])

    emit = on_event or (lambda kind, payload: None)
    emit("profile", profile)

    scratch = Path(tempfile.mkdtemp(prefix="bpcad-api-"))
    holder: dict[str, Any] = {}
    started = time.monotonic()

    def verify_candidate(spec):
        if not build_it:
            return None
        emit("building", spec)
        result, report, stl = compile_and_verify(
            spec, cfg, None, scratch / "out", allow_level_3=allow_level_3
        )
        holder["result"], holder["report"], holder["stl"] = result, report, stl
        return None

    result = run_ask(
        request=request, profile=profile, material=material,
        nozzle_mm=nozzle, layer_mm=layer,
        on_attempt=lambda a: emit("attempt", a),
        verify_fn=verify_candidate if build_it else None,
    )

    if (escalate and not result.ok and not result.ladder.never_reached_a_model):
        emit("escalate", result.ladder.last_error)
        level_1 = result
        result = ask_level_2(
            request=request, profile=profile, material=material,
            nozzle_mm=nozzle, layer_mm=layer,
            why_escalated=level_1.ladder.last_error,
            on_attempt=lambda a: emit("attempt", a),
            verify_fn=verify_candidate if build_it else None,
        )
        result.ladder.attempts = level_1.ladder.attempts + result.ladder.attempts
        if not result.ok and not result.problems:
            result.problems = level_1.problems
            result.best_attempt_data = result.best_attempt_data or level_1.best_attempt_data

    elapsed = time.monotonic() - started

    out = GenerateResult(
        ok=result.ok, spec=result.spec, attempts=list(result.ladder.attempts),
        elapsed_s=elapsed, machine=profile.name,
        models_tried=result.models_tried, problems=list(result.problems),
    )

    if not result.ok:
        target = Path(out_dir) if out_dir else Path("parts") / _slug(request)
        if result.ladder.never_reached_a_model:
            out.message = (
                "No model was reachable at %s. bpcad has no remote fallback by "
                "design - start the daemon, or write a spec by hand and build it."
                % profile.host
            )
        else:
            out.draft_path = write_handoff(
                out_dir=target, request=request, attempt=result.best_attempt_data,
                problems=result.problems, machine=profile.name,
                attempts_made=len(result.ladder.attempts), elapsed_s=elapsed,
                models_tried=result.models_tried, raw_error=result.ladder.last_error,
            )
            out.message = (
                "The model could not produce a valid spec. Every problem is "
                "marked inline in %s." % out.draft_path
            )
        emit("done", out)
        return out

    if not build_it:
        emit("done", out)
        return out

    spec = result.spec
    target = Path(out_dir) if out_dir else Path("parts") / spec.name
    (target / "out").mkdir(parents=True, exist_ok=True)
    final_stl = target / "out" / ("%s.stl" % spec.name)
    shutil.copy2(holder["stl"], final_stl)

    from bpcad.agent import bundle as bundle_mod

    model_used = next((a.model for a in reversed(result.ladder.attempts) if a.ok), "")
    files = bundle_mod.write_bundle(
        spec=spec, result=holder["result"], report=holder["report"],
        stl=final_stl, part_dir=target, model_used=model_used,
        machine=profile.name, attempts=len(result.ladder.attempts),
        elapsed_s=elapsed, render=render,
    )

    out.part = PartResult(
        name=spec.name, spec=spec, build=holder["result"], report=holder["report"],
        stl=final_stl, part_dir=target, files=files,
    )
    emit("done", out)
    return out


def _slug(text: str) -> str:
    keep = [c.lower() if c.isalnum() else "_" for c in text.strip()[:40]]
    return "".join(keep).strip("_").replace("__", "_") or "part"
