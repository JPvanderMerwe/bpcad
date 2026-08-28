"""
Changing a part you have already built, by describing the change.

THE IDEA
--------
A refinement does not touch geometry. It edits the SPEC, and the spec is rebuilt
from scratch. So "make it 10 mm wider" is an exact parameter change followed by
a deterministic build, not a re-roll that might come back different in ways you
did not ask for.

That also means every turn leaves a complete, valid spec.yaml. The history is a
sequence of specs: diffable, revertible, and each one printable on its own.

WHY A DIFF RATHER THAN A WHOLE SPEC
-----------------------------------
The model is asked for ONLY the parameters that change. Asking a small model to
restate a specification it was not asked to change is asking it to make mistakes
in the parts it was supposed to leave alone - a value gets rounded, a field it
did not understand gets dropped, and the part quietly moves in a direction
nobody requested.
"""

from __future__ import annotations

from typing import Any, Callable

from bpcad.agent import prompts
from bpcad.agent.handoff import FieldProblem, problems_from_validation_error
from bpcad.agent.loop import STAGE_PARSE, STAGE_VALIDATE, AskResult, SpecRejected
from bpcad.models.selector import Attempt, Profile, run_ladder
from bpcad.spec.schema import PartSpec


def apply_changes(spec: PartSpec, changes: dict[str, Any]) -> PartSpec:
    """
    Merge a parameter diff onto a spec, returning a new one.

    A null means "let this go back to being derived from the frame", which is
    how a refinement asks for the automatic behaviour it may have overridden
    earlier. Dropping the key entirely is what makes that work - the template's
    own derivation only runs for parameters that are absent.
    """
    params = dict(spec.params or {})
    for key, value in (changes or {}).items():
        if value is None:
            params.pop(key, None)
        else:
            params[key] = value

    data = spec.model_dump(exclude_none=True)
    data["params"] = params
    return PartSpec.model_validate(data)


def validate_changes(
    spec: PartSpec, changes: dict[str, Any]
) -> tuple[PartSpec, list[FieldProblem]]:
    """
    Apply a diff and check the result, returning per-field problems rather than
    raising, so a refinement can be critiqued the same way a first attempt is.
    """
    from pydantic import ValidationError

    from bpcad.build.compile import SpecError, validate_params

    try:
        merged = apply_changes(spec, changes)
    except ValidationError as exc:
        raise SpecRejected(
            "the change produced an invalid spec",
            stage=STAGE_VALIDATE,
            problems=problems_from_validation_error(exc),
        ) from exc

    if merged.level != 1 or not merged.template:
        return merged, []

    try:
        validate_params(merged)
    except SpecError as exc:
        problems: list[FieldProblem] = []
        from bpcad.spec import registry

        try:
            registry.get(merged.template).params_model.model_validate(merged.params)
        except ValidationError as pexc:
            for p in problems_from_validation_error(pexc):
                p.field = "params.%s" % p.field
                problems.append(p)
        raise SpecRejected(
            str(exc), stage=STAGE_VALIDATE, problems=problems, data=merged.model_dump()
        ) from exc

    return merged, []


def refine(
    spec: PartSpec,
    instruction: str,
    profile: Profile,
    report: Any = None,
    measurements: dict[str, Any] | None = None,
    on_attempt: Callable[[Attempt], None] | None = None,
    verify_fn: Callable[[PartSpec], Any] | None = None,
) -> AskResult:
    """
    Ask the model to change one thing about an existing part.

    Returns the same AskResult shape as a first generation, so the caller does
    not need a second code path for "this was a refinement".
    """
    from bpcad.agent.loop import _hint

    system = prompts.REFINE_SYSTEM
    base_user = prompts.build_refine_prompt(
        spec, instruction, report=report, measurements=measurements
    )
    schema = prompts.refine_schema(spec.template or "")

    state: dict[str, Any] = {"user": base_user, "best": {}, "problems": [], "note": ""}

    def one_attempt(backend) -> PartSpec:
        raw = backend.complete(system, state["user"], schema)
        try:
            data = prompts.parse_reply(raw)
        except ValueError as exc:
            state["user"] = prompts.critique_prompt(
                raw, str(exc), "- send a single JSON object with a params field"
            )
            raise SpecRejected(str(exc), stage=STAGE_PARSE, raw=raw) from exc

        changes = data.get("params")
        if not isinstance(changes, dict):
            problem = (
                "the reply had no `params` object. Send {\"params\": {...}} "
                "holding only the parameters that change."
            )
            state["user"] = prompts.critique_prompt(raw, problem, "- add a params object")
            raise SpecRejected(problem, stage=STAGE_VALIDATE, raw=raw)

        if not changes:
            problem = (
                "the reply changed nothing. If the instruction cannot be met by "
                "changing a parameter, change the closest one you can."
            )
            state["user"] = prompts.critique_prompt(raw, problem, "- change at least one parameter")
            raise SpecRejected(problem, stage=STAGE_VALIDATE, raw=raw)

        state["best"] = {"template": spec.template, "params": changes}
        state["note"] = data.get("note", "")

        try:
            merged, _ = validate_changes(spec, changes)
            if verify_fn is not None:
                verify_fn(merged)
        except SpecRejected as exc:
            exc.raw = raw
            state["problems"] = exc.problems
            state["user"] = prompts.critique_prompt(
                raw, str(exc), exc.hint or _hint(exc.problems)
            )
            raise
        state["problems"] = []
        return merged

    ladder = run_ladder(profile, one_attempt, on_attempt=on_attempt)

    result = AskResult(
        spec=ladder.value if ladder.ok else None,
        ladder=ladder,
        request=instruction,
        machine=profile.name,
        best_attempt_data=state["best"],
        problems=state["problems"],
        level=spec.level,
    )
    result.note = state["note"]           # what the model says it changed
    return result


def describe_changes(before: PartSpec, after: PartSpec) -> list[str]:
    """
    What actually changed between two specs, in plain language.

    Read off the specs rather than taken from the model's word for it - a model
    that says it made something wider and did not is exactly the case worth
    catching, and it is invisible if the interface only ever repeats the claim.
    """
    old = dict(before.params or {})
    new = dict(after.params or {})
    out: list[str] = []

    for key in sorted(set(old) | set(new)):
        a, b = old.get(key), new.get(key)
        if a == b:
            continue
        if key not in new:
            out.append("%s: %s -> derived from the frame" % (key, a))
        elif key not in old:
            out.append("%s: derived -> %s" % (key, b))
        elif isinstance(a, (int, float)) and isinstance(b, (int, float)):
            out.append("%s: %g -> %g (%+g)" % (key, a, b, b - a))
        else:
            out.append("%s: %s -> %s" % (key, a, b))

    for field in ("material", "nozzle_mm", "layer_mm", "print_axis"):
        a, b = getattr(before, field), getattr(after, field)
        if a != b:
            out.append("%s: %s -> %s" % (field, a, b))
    return out
