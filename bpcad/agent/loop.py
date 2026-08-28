"""
The agent loop: prompt in, verified bundle out.

Not clever. Disciplined:

  1. Build context: the request, any measurements, the template catalogue with
     parameter schemas.
  2. Ask for a PartSpec. Start at level 1.
  3. Validate against Pydantic. On failure, feed the exact error back and retry
     to the cap.
  4. Compile geometry. On exception, feed the traceback back and retry.
  5. Verify mesh, features and overhang. On failure, feed the failing rows back.
  6. Escalate level 1 -> 2 only when a level is exhausted. Level 3 only with
     --allow-level-3.
  7. On exhaustion, hand off with an annotated draft. Never fail silently.
  8. Render, write the bundle and the report.

Every run writes run.json with the full attempt history, the model used per
call and the elapsed time per call. That history is training data if it is ever
wanted, so it is kept clean.

CRITIQUE FEEDBACK IS STRUCTURED AND SPECIFIC, ALWAYS.
Never "it failed, try again": the failing check, the measured value, the
threshold, and the parameter most likely responsible. A small model given a
vague complaint changes something at random.
"""

from __future__ import annotations

import json
import time
import traceback
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from pydantic import ValidationError

from bpcad.agent import prompts
from bpcad.agent.handoff import FieldProblem, problems_from_validation_error
from bpcad.models.selector import Attempt, LadderResult, Profile, run_ladder
from bpcad.spec.schema import PartSpec

# Stage names, used in the run log and in the critique.
STAGE_PARSE = "parse"
STAGE_VALIDATE = "validate"
STAGE_COMPILE = "compile"
STAGE_VERIFY = "verify"


class NoTemplateFits(Exception):
    """
    The model said, correctly, that no template makes this part.

    Not a failure. It is the signal to go to level 2 and build the thing from
    primitives, and it arrives far cheaper than discovering the same fact by
    watching a wrong template pass every check.
    """


class SpecRejected(Exception):
    """
    One attempt produced something that did not survive to a verified part.

    Carries the stage it died at, the raw reply, and per-field problems, so the
    next prompt can be specific and the handoff can annotate the draft.
    """

    def __init__(
        self,
        message: str,
        stage: str = STAGE_VALIDATE,
        raw: str = "",
        problems: list[FieldProblem] | None = None,
        data: dict | None = None,
        hint: str = "",
    ) -> None:
        super().__init__(message)
        self.stage = stage
        self.raw = raw
        self.problems = problems or []
        self.data = data or {}
        self.hint = hint


@dataclass
class AskResult:
    """What the generation half produced, plus everything it took."""

    spec: PartSpec | None = None
    ladder: LadderResult | None = None
    request: str = ""
    machine: str = ""
    best_attempt_data: dict = field(default_factory=dict)
    problems: list[FieldProblem] = field(default_factory=list)
    level: int = 1
    note: str = ""          # what a refinement says it changed, in its words
    no_template_fits: bool = False

    @property
    def ok(self) -> bool:
        return self.spec is not None

    @property
    def models_tried(self) -> list[str]:
        if not self.ladder:
            return []
        seen: list[str] = []
        for a in self.ladder.attempts:
            if a.model not in seen:
                seen.append(a.model)
        return seen


def _problems_for(data: dict, exc: Exception, template: str | None) -> list[FieldProblem]:
    """
    Per-field problems from the spec schema and the template's own model.

    PartSpec keeps `params` as a free dict, so the template decides what is
    legal there and its errors are the ones worth showing.
    """
    problems = problems_from_validation_error(exc)
    if not template:
        return problems

    from bpcad.spec import registry

    try:
        model = registry.get(template).params_model
    except Exception:
        return problems
    try:
        model.model_validate(data.get("params") or {})
    except ValidationError as param_exc:
        for p in problems_from_validation_error(param_exc):
            p.field = "params.%s" % p.field
            problems.append(p)
    return problems


def validate_reply(data: dict, defaults: dict[str, Any]) -> PartSpec:
    """
    Turn a model's JSON into a PartSpec, or raise SpecRejected with detail.

    Fixed settings are FORCED rather than trusted: material, nozzle and layer
    come from config and the command line, and a model that helpfully changes
    them is overruled silently. It was not asked to make that judgement.
    """
    from bpcad.spec.schema import format_validation_error

    merged = dict(data)
    merged.update(defaults)
    merged.setdefault("level", 1)
    template = merged.get("template")

    if template == prompts.NO_TEMPLATE:
        raise NoTemplateFits(
            "no template makes this part - going to primitive shapes instead"
        )

    try:
        spec = PartSpec.model_validate(merged)
    except ValidationError as exc:
        raise SpecRejected(
            format_validation_error(exc, "the spec was rejected:"),
            stage=STAGE_VALIDATE,
            problems=_problems_for(merged, exc, template),
            data=merged,
        ) from exc

    if spec.level == 1:
        from bpcad.build.compile import SpecError, validate_params

        try:
            validate_params(spec)
        except SpecError as exc:
            problems: list[FieldProblem] = []
            from bpcad.spec import registry

            try:
                registry.get(spec.template).params_model.model_validate(spec.params)
            except ValidationError as pexc:
                for p in problems_from_validation_error(pexc):
                    p.field = "params.%s" % p.field
                    problems.append(p)
            raise SpecRejected(
                str(exc), stage=STAGE_VALIDATE, problems=problems, data=merged
            ) from exc

    return spec


def validate_dsl_reply(data: dict, defaults: dict[str, Any]) -> PartSpec:
    """
    Turn a level-2 reply into a PartSpec, checking every op before returning.

    The ops are parsed here rather than at compile time so a bad op comes back
    as a retryable rejection naming the operation, not as a build failure.
    """
    from bpcad.spec.dsl import DslError, parse_op
    from bpcad.spec.schema import format_validation_error

    merged = dict(data)
    merged.update(defaults)
    merged["level"] = 2
    merged.pop("template", None)
    merged.pop("params", None)

    ops = merged.get("ops") or []
    if not ops:
        raise SpecRejected(
            "a level-2 spec needs at least one entry in `ops`.",
            stage=STAGE_VALIDATE, data=merged,
        )

    for i, op in enumerate(ops):
        if not isinstance(op, dict):
            raise SpecRejected(
                "ops[%d] is a %s, but every op must be an object with an `op` field."
                % (i, type(op).__name__),
                stage=STAGE_VALIDATE, data=merged,
            )
        try:
            parse_op(op)
        except DslError as exc:
            raise SpecRejected(
                "ops[%d] is invalid: %s" % (i, exc),
                stage=STAGE_VALIDATE, data=merged,
                hint="- fix ops[%d]. %s" % (i, str(exc).split("\n")[0]),
            ) from exc

    try:
        return PartSpec.model_validate(merged)
    except ValidationError as exc:
        raise SpecRejected(
            format_validation_error(exc, "the level-2 spec was rejected:"),
            stage=STAGE_VALIDATE,
            problems=problems_from_validation_error(exc),
            data=merged,
        ) from exc


def _hint(problems: list[FieldProblem]) -> str:
    """
    The specific change to make, per field.

    Never "it failed, try again" - that is the feedback that makes a small
    model thrash. Name the field, the value and the legal range.
    """
    from bpcad.agent.handoff import WHOLE_SECTION

    if not problems:
        return ""
    lines: list[str] = []
    for p in problems[:8]:
        if p.field.endswith(WHOLE_SECTION):
            # A cross-field validator. "Fix (root)" is useless; the message
            # itself names the fields. Where it suggested a concrete value,
            # lead with that sentence - a model acts on "Set x to about 10.2"
            # and ignores the same instruction placed after two lines of why.
            text = p.problem.replace("Value error, ", "")
            sentences = [s.strip() for s in text.split(". ") if s.strip()]
            action = next((s for s in sentences if s.lower().startswith("set ")), "")
            if action:
                lines.append("- %s." % action.rstrip("."))
                lines.append("  (why: %s)" % ". ".join(s for s in sentences if s != action))
            else:
                lines.append("- %s" % text)
        elif "Extra inputs" in p.problem:
            lines.append(
                "- remove %r: that parameter does not exist. Check the spelling "
                "against the template's parameter list." % p.field
            )
        elif "required" in p.problem.lower():
            lines.append("- add %r%s" % (p.field, ", legal: %s" % p.legal if p.legal else ""))
        elif p.legal:
            lines.append("- change %r to a value %s (you sent %r)" % (p.field, p.legal, p.given))
        else:
            lines.append("- fix %r: %s" % (p.field, p.problem))
    return "\n".join(lines)


def _verify_critique(report) -> tuple[str, str]:
    """
    Turn a failing verify report into a problem and a hint.

    The failing check, the measured value, the threshold, and the parameter
    most likely responsible. Anything less and the next attempt is a guess.
    """
    problems: list[str] = []
    hints: list[str] = []

    if report.features is not None:
        for c in report.features.too_fine:
            problems.append(
                "feature %r measures %.3f mm, below the %.3f mm a %.2f mm nozzle "
                "can resolve" % (c.name, c.value_mm, c.threshold_mm, report.nozzle_mm)
            )
            hints.append(
                "- make %r at least %.2f mm. It is currently %.3f mm, which will "
                "not print." % (c.name, c.threshold_mm, c.value_mm)
            )

    if not report.mesh.watertight:
        problems.append("the exported mesh is not watertight, so it will not slice")
        hints.append("- simplify the part: some feature is producing broken geometry.")

    o = report.overhang
    if o.unsupported_area_mm2 > 0:
        problems.append(
            "%.1f mm2 of underside overhangs past %.0f degrees and falls up to "
            "%.2f mm, so the part needs support as oriented"
            % (o.unsupported_area_mm2, o.max_deg, o.max_drop_mm)
        )
        hints.append(
            "- reduce the overhangs, or accept that this part needs support."
        )

    return ("\n".join(problems), "\n".join(hints))


def ask(
    request: str,
    profile: Profile,
    material: str,
    nozzle_mm: float,
    layer_mm: float,
    measurements: dict[str, Any] | None = None,
    on_attempt: Callable[[Attempt], None] | None = None,
    level: int = 1,
    verify_fn: Callable[[PartSpec], Any] | None = None,
    base_dir: Path | None = None,
) -> AskResult:
    """
    Ask the model for a PartSpec, retrying with structured feedback.

    When `verify_fn` is supplied it is called with each validated spec and must
    raise SpecRejected if the geometry does not survive compiling or verifying.
    That is what makes a failed BUILD retryable rather than fatal - the model
    gets told the part did not hold up, and why.
    """
    defaults = {"material": material, "nozzle_mm": nozzle_mm, "layer_mm": layer_mm}
    system = prompts.SYSTEM
    base_user = prompts.build_user_prompt(request, material, nozzle_mm, layer_mm, measurements)
    schema = prompts.ask_schema()

    state: dict[str, Any] = {"user": base_user, "best": {}, "problems": []}

    def one_attempt(backend) -> PartSpec:
        raw = backend.complete(system, state["user"], schema)
        try:
            data = prompts.parse_reply(raw)
        except ValueError as exc:
            state["user"] = prompts.critique_prompt(
                raw, str(exc), "- send a single JSON object and nothing else"
            )
            raise SpecRejected(str(exc), stage=STAGE_PARSE, raw=raw) from exc

        state["best"] = data
        try:
            spec = validate_reply(data, defaults)
        except NoTemplateFits:
            # Retrying will only produce the same correct answer more slowly.
            state["declined"] = True
            raise
        except SpecRejected as exc:
            exc.raw = raw
            state["problems"] = exc.problems
            state["user"] = prompts.critique_prompt(raw, str(exc), _hint(exc.problems))
            raise

        if verify_fn is not None:
            try:
                verify_fn(spec)
            except NoTemplateFits:
                raise
            except SpecRejected as exc:
                exc.raw = raw
                state["problems"] = exc.problems
                state["user"] = prompts.critique_prompt(
                    raw, str(exc), exc.hint or _hint(exc.problems)
                )
                raise

        state["problems"] = []
        return spec

    ladder = run_ladder(profile, one_attempt, on_attempt=on_attempt)

    result = AskResult(
        spec=ladder.value if ladder.ok else None,
        ladder=ladder,
        request=request,
        machine=profile.name,
        best_attempt_data=state["best"],
        problems=state["problems"],
        level=level,
    )
    result.no_template_fits = state.get("declined", False)
    return result


def ask_level_2(
    request: str,
    profile: Profile,
    material: str,
    nozzle_mm: float,
    layer_mm: float,
    why_escalated: str = "",
    on_attempt: Callable[[Attempt], None] | None = None,
    verify_fn: Callable[[PartSpec], Any] | None = None,
) -> AskResult:
    """
    Level 2: ask for a composition of DSL primitives instead of a template.

    Reached ONLY when level 1 is exhausted. Composing primitives is a harder
    task than filling a form, so this is a step down in reliability, not up -
    it is here because a part no template covers has no other route that does
    not involve raw CadQuery.
    """
    defaults = {"material": material, "nozzle_mm": nozzle_mm, "layer_mm": layer_mm}
    system = prompts.DSL_SYSTEM
    base_user = prompts.build_dsl_prompt(
        request, material, nozzle_mm, layer_mm, why_escalated
    )
    # JSON MODE, NOT A SCHEMA. See models.ollama.JSON_ONLY: a schema with a
    # discriminated union in it makes this model emit ops with no dimensions,
    # while plain JSON mode on the identical prompt gets it right first time.
    # The shape is carried by the prompt's worked example instead.
    from bpcad.models.ollama import JSON_ONLY

    schema = JSON_ONLY
    state: dict[str, Any] = {"user": base_user, "best": {}, "problems": []}

    def one_attempt(backend) -> PartSpec:
        raw = backend.complete(system, state["user"], schema)
        try:
            data = prompts.parse_reply(raw)
        except ValueError as exc:
            state["user"] = prompts.critique_prompt(
                raw, str(exc), "- send a single JSON object and nothing else"
            )
            raise SpecRejected(str(exc), stage=STAGE_PARSE, raw=raw) from exc

        state["best"] = data
        try:
            spec = validate_dsl_reply(data, defaults)
            if verify_fn is not None:
                verify_fn(spec)
        except SpecRejected as exc:
            exc.raw = raw
            state["problems"] = exc.problems
            state["user"] = prompts.critique_prompt(
                raw, str(exc), exc.hint or _hint(exc.problems)
            )
            raise
        state["problems"] = []
        return spec

    ladder = run_ladder(profile, one_attempt, on_attempt=on_attempt)
    return AskResult(
        spec=ladder.value if ladder.ok else None,
        ladder=ladder,
        request=request,
        machine=profile.name,
        best_attempt_data=state["best"],
        problems=state["problems"],
        level=2,
    )


def compile_and_verify(
    spec: PartSpec,
    cfg,
    base_dir: Path | None,
    out_dir: Path,
    allow_level_3: bool = False,
    request: str = "",
):
    """
    Compile a spec, export it, and verify the result.

    Raises SpecRejected with a structured critique if anything fails, so the
    caller can feed it back to the model rather than giving up.

    `allow_level_3` has to be threaded through rather than defaulted here: a
    level-3 spec the person wrote themselves must be buildable, and hardcoding
    False made `bpcad gen --allow-level-3` refuse its own opt-in.
    """
    from bpcad.build.compile import SpecError, check_export, compile_spec, export_solid
    from bpcad.verify.features import check_features
    from bpcad.verify.mesh import check_mesh, load_mesh
    from bpcad.verify.overhang import overhang_report
    from bpcad.verify.probe import surface_levels
    from bpcad.verify.report import VerifyReport

    try:
        result = compile_spec(spec, base_dir=base_dir, allow_level_3=allow_level_3)
    except SpecError as exc:
        raise SpecRejected(str(exc), stage=STAGE_COMPILE) from exc
    except Exception as exc:
        raise SpecRejected(
            "building the geometry raised %s: %s\n%s"
            % (type(exc).__name__, exc, traceback.format_exc(limit=3)),
            stage=STAGE_COMPILE,
            hint="- the parameters are individually legal but produce impossible "
                 "geometry together. Try more conservative values.",
        ) from exc

    tol = spec.stl_tolerance if spec.stl_tolerance is not None else float(cfg.export["stl_tolerance"])
    ang = (
        spec.stl_angular_tolerance
        if spec.stl_angular_tolerance is not None
        else float(cfg.export["stl_angular_tolerance"])
    )
    stl = export_solid(result.print_solid, out_dir / ("%s.stl" % spec.name), tol, ang)

    problems = check_export(stl, expected_bodies=result.body_count_expected)
    mesh = load_mesh(stl)

    report = VerifyReport(
        path=str(stl),
        nozzle_mm=spec.nozzle_mm,
        print_axis=spec.print_axis,
        material=spec.material,
        mesh=check_mesh(stl),
        overhang=overhang_report(
            mesh,
            print_axis=spec.print_axis,
            max_deg=float(cfg.limits["max_overhang_deg"]),
            max_bridge_gap_mm=float(cfg.limits["max_bridge_gap_mm"]),
        ),
        levels=surface_levels(mesh, axis=spec.print_axis),
        features=check_features(
            result.features,
            nozzle_mm=spec.nozzle_mm,
            min_feature_multiple=float(cfg.limits["min_feature_multiple"]),
        ) if result.features else None,
        notes=list(result.log.notes),
    )

    if problems:
        raise SpecRejected(
            "the exported mesh failed its checks: %s" % "; ".join(problems),
            stage=STAGE_VERIFY,
            hint="- the geometry is broken. Try more conservative parameters.",
        )

    # A part that needs support is NOT a failure - plenty of good parts do, and
    # the vent reference is one. Only feature sizes and broken meshes fail here.
    if report.features is not None and report.features.too_fine:
        problem, hint = _verify_critique(report)
        raise SpecRejected(problem, stage=STAGE_VERIFY, hint=hint)

    # Does it resemble what was asked for? Everything above answers "can this be
    # made?", which a 573 cm3 solid slab answers perfectly well while not being
    # the birdhouse that was requested. This compares the numbers the request
    # stated against the numbers the part came out with.
    if request:
        from bpcad.verify.intent import check_intent

        # Measure the ASSEMBLED part, not the print layout. A part that prints
        # as two pieces side by side has a bounding box that describes the bed,
        # not the object: the enclosure's box is 120 mm wide and its print
        # layout is 288, because the roof lies next to it. Checking the layout
        # rejected a correct birdhouse for not being 100 mm deep when it was.
        if getattr(result, "nominal_mm", None):
            measured = result.nominal_mm
        else:
            try:
                bb = result.solid.val().BoundingBox()
                measured = (bb.xlen, bb.ylen, bb.zlen)
            except Exception:
                measured = report.mesh.bbox_mm

        intent = check_intent(request, measured)
        report.intent = intent
        if intent.problems:
            raise SpecRejected(
                intent.problems[0],
                stage=STAGE_VERIFY,
                hint=(
                    "- the part must actually be the size that was asked for. "
                    "Set the parameter that controls the missing dimension, or "
                    "answer 'none_of_these_fit' if no template can make this."
                ),
            )

    return result, report, stl


@dataclass
class RunRecord:
    """
    The full history of one `bpcad gen` run.

    Written to run.json every time, successful or not. Kept clean because it is
    training data if fine-tuning is ever wanted.
    """

    request: str
    machine: str
    started_at: str
    elapsed_s: float
    ok: bool
    level_reached: int
    profile: dict = field(default_factory=dict)
    attempts: list[dict] = field(default_factory=list)
    spec: dict | None = None
    report: dict | None = None
    budget: dict = field(default_factory=dict)
    handoff: str | None = None

    def write(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2, sort_keys=True, default=str))
        return path


def attempt_to_dict(a: Attempt, level: int) -> dict:
    """One attempt, flattened for run.json."""
    out = {
        "index": a.index,
        "level": level,
        "model": a.model,
        "step": a.step,
        "ok": a.ok,
        "elapsed_s": round(a.elapsed_s, 3),
        "error": a.error,
    }
    if a.call:
        out["call"] = {
            "mechanism": a.call.mechanism,
            "load_s": round(a.call.load_s, 3),
            "prompt_tokens": a.call.prompt_tokens,
            "gen_tokens": a.call.gen_tokens,
            "tokens_per_s": round(a.call.tokens_per_s, 2),
        }
    return out
