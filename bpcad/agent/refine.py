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


def apply_ops(spec: PartSpec, ops: list) -> PartSpec:
    """Replace a level-2 spec's operation list, returning a new spec."""
    data = spec.model_dump(exclude_none=True)
    data["ops"] = ops
    data["level"] = 2
    return PartSpec.model_validate(data)


def refine_ops(
    spec: PartSpec,
    instruction: str,
    profile: Profile,
    report: Any = None,
    on_attempt: Callable[[Attempt], None] | None = None,
    verify_fn: Callable[[PartSpec], Any] | None = None,
) -> AskResult:
    """
    Change a part built from primitives.

    JSON mode, not a schema: the operation list is a discriminated union and
    Ollama does not enforce those, so constraining it makes the model emit
    operations with no numbers. See models.ollama.JSON_ONLY.
    """
    from bpcad.agent.loop import _hint
    from bpcad.models.ollama import JSON_ONLY
    from bpcad.spec.dsl import DslError, parse_op

    system = prompts.REFINE_OPS_SYSTEM
    base_user = prompts.build_refine_ops_prompt(spec, instruction, report=report)
    state: dict[str, Any] = {"user": base_user, "best": {}, "problems": [], "note": ""}

    def one_attempt(backend) -> PartSpec:
        raw = backend.complete(system, state["user"], JSON_ONLY)
        try:
            data = prompts.parse_reply(raw)
        except ValueError as exc:
            state["user"] = prompts.critique_prompt(
                raw, str(exc), '- send a single JSON object with an "ops" list'
            )
            raise SpecRejected(str(exc), stage=STAGE_PARSE, raw=raw) from exc

        ops = data.get("ops")
        if not isinstance(ops, list) or not ops:
            problem = 'the reply had no "ops" list. Send {"ops": [...]}.'
            state["user"] = prompts.critique_prompt(raw, problem, "- add an ops list")
            raise SpecRejected(problem, stage=STAGE_VALIDATE, raw=raw)

        state["best"] = {"ops": ops}
        state["note"] = data.get("note", "")

        for i, op in enumerate(ops):
            if not isinstance(op, dict):
                problem = "ops[%d] is not an object" % i
                state["user"] = prompts.critique_prompt(raw, problem, "- fix ops[%d]" % i)
                raise SpecRejected(problem, stage=STAGE_VALIDATE, raw=raw)
            try:
                parse_op(op)
            except DslError as exc:
                problem = "ops[%d] is invalid: %s" % (i, exc)
                state["user"] = prompts.critique_prompt(
                    raw, problem,
                    "- fix ops[%d]. %s" % (i, str(exc).split(chr(10))[0]),
                )
                raise SpecRejected(problem, stage=STAGE_VALIDATE, raw=raw) from exc

        try:
            merged = apply_ops(spec, ops)
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
        spec=ladder.value if ladder.ok else None, ladder=ladder,
        request=instruction, machine=profile.name,
        best_attempt_data=state["best"], problems=state["problems"], level=2,
    )
    result.note = state["note"]
    return result


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

    # A part built from primitives has no template and no params, so the
    # parameter-diff path has nothing to show the model. Send it to the
    # operations path instead.
    if spec.level == 2 or not spec.template:
        return refine_ops(
            spec, instruction, profile, report=report,
            on_attempt=on_attempt, verify_fn=verify_fn,
        )

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


def describe_op_changes(before: PartSpec, after: PartSpec) -> list[str]:
    """What changed in an operation list, read off the two specs."""
    old = [dict(o) for o in (before.ops or [])]
    new = [dict(o) for o in (after.ops or [])]
    out: list[str] = []

    old_names = [o.get("op") for o in old]
    new_names = [o.get("op") for o in new]
    for name in set(new_names) - set(old_names):
        out.append("added %s" % name)
    for name in set(old_names) - set(new_names):
        out.append("removed %s" % name)

    for i, (a, b) in enumerate(zip(old, new)):
        if a.get("op") != b.get("op"):
            out.append("op %d: %s -> %s" % (i, a.get("op"), b.get("op")))
            continue
        for key in sorted(set(a) | set(b)):
            if key == "op" or a.get(key) == b.get(key):
                continue
            out.append("%s.%s: %s -> %s" % (b.get("op"), key, a.get(key), b.get(key)))

    if len(new) != len(old):
        out.append("%d operations -> %d" % (len(old), len(new)))
    return out or ["no change to the operations"]


def describe_changes(before: PartSpec, after: PartSpec) -> list[str]:
    """
    What actually changed between two specs, in plain language.

    Read off the specs rather than taken from the model's word for it - a model
    that says it made something wider and did not is exactly the case worth
    catching, and it is invisible if the interface only ever repeats the claim.
    """
    if before.level == 2 or after.level == 2:
        return describe_op_changes(before, after)

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
