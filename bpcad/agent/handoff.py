"""
The handoff: what happens when the model cannot do the job.

THIS IS THE MOST IMPORTANT FILE IN THE AGENT LAYER.

On a CPU-only machine at seven tokens a second, failure is not an edge case -
it is a normal Tuesday. The difference between this system being useful and
being abandoned is whether a failed run leaves you with something you can fix
in ninety seconds, or with a stack trace and a shrug.

So a failed run writes spec.draft.yaml: the closest thing the model produced,
with EVERY field it got wrong annotated in place with what was wrong and what
would have been legal, plus the exact command to run once it is fixed. No
hunting through logs, no re-reading the schema.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

# Marks a problem that belongs to a combination of fields rather than to one -
# a cross-field validator. It is never a field you can add.
WHOLE_SECTION = "(combination of parameters)"

# Fields whose absence has an obvious right answer, so the draft can fill them.
CARRIED_FIELDS = ("name", "level", "material", "nozzle_mm", "layer_mm", "print_axis", "template")


@dataclass
class FieldProblem:
    """One thing wrong with one field, in terms a person can act on."""

    field: str
    problem: str
    given: Any = None
    legal: str = ""

    def comment_lines(self) -> list[str]:
        lines = ["# PROBLEM: %s" % self.problem]
        if self.given is not None:
            lines.append("#   you had: %r" % (self.given,))
        if self.legal:
            lines.append("#   legal  : %s" % self.legal)
        return lines


def problems_from_validation_error(exc: Exception) -> list[FieldProblem]:
    """Turn a pydantic ValidationError into per-field problems."""
    from pydantic import ValidationError

    if not isinstance(exc, ValidationError):
        return [FieldProblem(field="(spec)", problem=str(exc))]

    out: list[FieldProblem] = []
    for err in exc.errors():
        loc = [str(p) for p in err["loc"]]
        # params.wall_mm reads better than ('params', 'wall_mm').
        # A model-level validator - one checking two fields against each other,
        # like "the blades must be narrower than their pitch" - has an EMPTY
        # loc, because it belongs to no single field. Calling that "(root)" and
        # then listing it as a missing field, which is what happened first, is
        # nonsense: there is nothing to fill in. It gets its own marker and the
        # renderer treats it as a whole-section problem.
        name = ".".join(loc) if loc else WHOLE_SECTION
        ctx = err.get("ctx") or {}
        bounds = []
        for key, label in (
            ("ge", ">="), ("gt", ">"), ("le", "<="), ("lt", "<"),
            ("min_length", "min length"), ("max_length", "max length"),
        ):
            if key in ctx:
                bounds.append("%s %s" % (label, ctx[key]))
        out.append(
            FieldProblem(
                field=name,
                problem=err["msg"],
                given=err.get("input"),
                legal=", ".join(bounds),
            )
        )
    return out


def _wrap(text: str, width: int) -> list[str]:
    """Wrap a message so a long validator complaint stays readable in a comment."""
    import textwrap

    return textwrap.wrap(text.strip(), width=width) or [""]


def _yaml_value(value: Any) -> str:
    """One-line YAML for a scalar, so it can sit under its own comment."""
    return yaml.safe_dump(value, default_flow_style=True).strip().rstrip("...").strip()


def render_draft(
    request: str,
    attempt: dict[str, Any],
    problems: list[FieldProblem],
    machine: str,
    attempts_made: int,
    elapsed_s: float,
    models_tried: list[str],
    spec_path: Path,
) -> str:
    """
    Build the annotated spec.draft.yaml.

    Every problem appears BOTH in a summary block at the top and inline, right
    above the field it concerns. The summary is for deciding whether to bother;
    the inline comments are for actually fixing it without scrolling.
    """
    by_field: dict[str, list[FieldProblem]] = {}
    for p in problems:
        by_field.setdefault(p.field, []).append(p)

    L: list[str] = []
    L.append("# bpcad handoff - the model could not produce a valid spec.")
    L.append("#")
    L.append("# Requested:")
    for line in request.strip().splitlines():
        L.append("#   %s" % line)
    L.append("#")
    L.append("# Tried %d attempt(s) across %s on machine %r, %.1fs total."
             % (attempts_made, " then ".join(models_tried) or "no model", machine, elapsed_s))
    L.append("# Below is the closest attempt, with every problem marked inline.")
    L.append("#")

    if problems:
        L.append("# WHAT IS WRONG (%d):" % len(problems))
        for p in problems:
            head = p.field.replace("params." + WHOLE_SECTION, WHOLE_SECTION)
            wrapped = _wrap(p.problem, 60)
            L.append("#   %-28s %s" % (head, wrapped[0]))
            for extra in wrapped[1:]:
                L.append("#   %-28s %s" % ("", extra))
            if p.legal:
                L.append("#   %-28s legal: %s" % ("", p.legal))
    else:
        L.append("# No field-level problems were recorded - see the error below.")
    L.append("#")
    L.append("# WHEN YOU HAVE FIXED IT:")
    L.append("#   bpcad build %s" % spec_path)
    L.append("#")
    L.append("# Useful while editing:")
    template = attempt.get("template")
    if template:
        L.append("#   bpcad spec explain %s      # units, defaults and bounds" % template)
    else:
        L.append("#   bpcad spec list                 # what templates exist")
    L.append("#   bpcad spec ops                  # level-2 operations and anchors")
    L.append("")

    def emit(key: str, value: Any, indent: str = "") -> None:
        for p in by_field.get(key, []):
            for line in p.comment_lines():
                L.append("%s%s" % (indent, line))
        L.append("%s%s: %s" % (indent, key.split(".")[-1], _yaml_value(value)))

    for key in CARRIED_FIELDS:
        if key in attempt:
            emit(key, attempt[key])

    # A field can be wrong by being ABSENT, which no inline comment would ever
    # reach. Surface those as a to-do block rather than losing them.
    missing = [
        p for p in problems
        if p.field not in attempt
        and not p.field.startswith("params.")
        and p.field not in ("(spec)", WHOLE_SECTION)
        and "params." + WHOLE_SECTION != p.field
    ]
    if missing:
        L.append("")
        L.append("# MISSING - these were not in the model's answer at all:")
        for p in missing:
            L.append("#   %s: <%s>" % (p.field, p.legal or "required"))

    params = attempt.get("params") or {}
    L.append("")
    if params or any(k.startswith("params.") for k in by_field):
        L.append("params:")
        for key, value in params.items():
            for p in by_field.get("params.%s" % key, []):
                for line in p.comment_lines():
                    L.append("  %s" % line)
            L.append("  %s: %s" % (key, _yaml_value(value)))

        # Cross-field problems belong to the whole params block, so they go at
        # the end of it rather than pretending to be a field.
        for p in problems:
            if p.field in (WHOLE_SECTION, "params." + WHOLE_SECTION):
                L.append("")
                L.append("  # THESE PARAMETERS CONTRADICT EACH OTHER:")
                for line in ("  #   %s" % l for l in _wrap(p.problem, 68)):
                    L.append(line)

        missing_params = [
            p for p in problems
            if p.field.startswith("params.")
            and p.field != "params." + WHOLE_SECTION
            and p.field.split(".", 1)[1] not in params
        ]
        for p in missing_params:
            L.append("  # MISSING: %s" % p.problem)
            if p.legal:
                L.append("  #   legal: %s" % p.legal)
            L.append("  # %s: <fill this in>" % p.field.split(".", 1)[1])
    else:
        L.append("params: {}")

    return "\n".join(L) + "\n"


def write_handoff(
    out_dir: str | Path,
    request: str,
    attempt: dict[str, Any],
    problems: list[FieldProblem],
    machine: str,
    attempts_made: int,
    elapsed_s: float,
    models_tried: list[str],
    raw_error: str = "",
) -> Path:
    """
    Write spec.draft.yaml and return its path.

    The caller prints that path and the exact follow-up command. Nothing about
    a failed run should require reading source or scrollback.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    draft = out / "spec.draft.yaml"
    final = out / "spec.yaml"

    text = render_draft(
        request=request,
        attempt=attempt or {},
        problems=problems,
        machine=machine,
        attempts_made=attempts_made,
        elapsed_s=elapsed_s,
        models_tried=models_tried,
        spec_path=final,
    )
    if raw_error and not problems:
        text += "\n# The full error was:\n"
        for line in raw_error.strip().splitlines():
            text += "#   %s\n" % line

    draft.write_text(text)
    return draft


def no_model_steps(host: str, models: list[str]) -> str:
    """
    The message when nothing was reachable, which is a different problem.

    Telling someone their model "could not produce a valid spec" when the
    daemon simply is not running sends them to edit YAML instead of starting
    Ollama.
    """
    return "\n".join([
        "",
        "No model was reachable, so nothing was generated.",
        "",
        "  Daemon   %s" % host,
        "  Wanted   %s" % ", ".join(models),
        "",
        "  1. Is it running?   ollama serve",
        "  2. Does it have these models?   bpcad models list",
        "",
        "bpcad has no remote fallback by design - local inference or none.",
        "Everything downstream of a spec still works with no model at all:",
        "write parts/<name>/spec.yaml by hand and run bpcad build on it.",
        "`bpcad spec explain <template>` prints every parameter with its bounds.",
    ])


def next_steps(draft: Path) -> str:
    """The message printed after a handoff. Short, and every line actionable."""
    final = draft.parent / "spec.yaml"
    return "\n".join([
        "",
        "The model could not produce a valid spec, so it has handed off to you.",
        "",
        "  1. Edit      %s" % draft,
        "     Every problem is marked inline with what is legal.",
        "  2. Rename it %s" % final,
        "  3. Build     bpcad build %s" % final,
        "",
        "Nothing in the deterministic pipeline needs a model, so from here on it",
        "does not matter that the model failed.",
    ])
