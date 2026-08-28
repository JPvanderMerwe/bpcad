"""
Prompt construction.

WHAT THE MODEL IS ASKED TO DO, AND WHAT IT IS NOT
--------------------------------------------------
It is asked to fill in a form. It is never asked to write CAD code, choose a
CadQuery selector, or reason about geometry. Structured extraction into a schema
is something an 8B model does reliably; the rest is not, and the architecture is
built so it never has to.

The template catalogue goes into the prompt WITH its parameter schema, because a
model that cannot see the legal parameter names invents plausible ones, and a
model that cannot see the bounds picks round numbers that fail validation.
"""

from __future__ import annotations

import json
from typing import Any

NO_TEMPLATE = "none_of_these_fit"

SYSTEM = """You fill in a part specification for a 3D printing pipeline.

You do NOT write CAD code. You choose a template and fill in its parameters.
Deterministic Python turns your specification into geometry.

Rules:
- Reply with JSON only. No prose, no explanation, no markdown fences.
- `template` MUST be one of the template names listed. Never invent one, and
  never put a material or a description there.
- If NONE of the templates makes the part that was asked for, answer
  "none_of_these_fit". Do not bend an unrelated template to the dimensions -
  a birdhouse is not a keyring with different numbers, and a wrong template
  silently produces a part that passes every check and is not what was wanted.
  Saying it does not fit is a correct and useful answer.
- Use only the parameter names listed for the template you chose. A name that
  is not on the list is rejected.
- Every dimension is in millimetres and every angle is in degrees.
- Respect the stated bounds. A value outside them is rejected.
- Omit any parameter you have no information about; it will take its default.
  Guessing is worse than omitting.
"""


def template_catalogue(max_params: int = 40) -> str:
    """Every template with its parameters, units, defaults and bounds."""
    from bpcad.spec import registry

    blocks: list[str] = []
    for name in registry.names():
        t = registry.get(name)
        lines = ["TEMPLATE %s" % name, "  %s" % t.summary, "  parameters:"]
        for i, (fname, field) in enumerate(t.params_model.model_fields.items()):
            if i >= max_params:
                lines.append("    ... %d more, see `bpcad spec explain %s`"
                             % (len(t.params_model.model_fields) - max_params, name))
                break
            bounds = []
            for meta in field.metadata:
                for attr, label in (("ge", ">="), ("gt", ">"), ("le", "<="), ("lt", "<")):
                    v = getattr(meta, attr, None)
                    if v is not None:
                        bounds.append("%s %g" % (label, v))
            default = field.default
            shown = "required" if field.is_required() else (
                "%g" % default if isinstance(default, float) else str(default)
            )
            lines.append(
                "    %-22s default %-8s %-18s %s"
                % (fname, shown, ", ".join(bounds), (field.description or "").split(".")[0])
            )
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def build_user_prompt(
    request: str,
    material: str,
    nozzle_mm: float,
    layer_mm: float,
    measurements: dict[str, Any] | None = None,
) -> str:
    """The task, the catalogue, and any measurements taken from a reference image."""
    parts = [
        "Requested part:",
        "  %s" % request.strip(),
        "",
        "Fixed settings - copy these into your answer unchanged:",
        "  material: %s" % material,
        "  nozzle_mm: %g" % nozzle_mm,
        "  layer_mm: %g" % layer_mm,
        "",
    ]

    if measurements:
        parts.append("MEASURED FROM THE REFERENCE IMAGE. These are measurements,")
        parts.append("not estimates. Where one of these covers a parameter, USE IT -")
        parts.append("it beats anything implied by the request text, and it beats")
        parts.append("a default:")
        for k, v in measurements.items():
            parts.append("  %s: %s" % (k, v))
        parts.append("")
        parts.append("Anything the image could not show is simply absent above.")
        parts.append("Take those from the request, or leave them to default.")
        parts.append("")

    parts.append("Templates available:")
    parts.append("")
    parts.append(template_catalogue())
    parts.append("")
    parts.append(
        "If none of these makes the part that was asked for, set template to "
        "%r. That is a correct answer, not a failure - the request will be "
        "built from primitive shapes instead." % NO_TEMPLATE
    )
    return "\n".join(parts)


def critique_prompt(previous: str, problem: str, hint: str = "") -> str:
    """
    Feed a failure back.

    ORDER MATTERS MORE THAN CONTENT HERE. The first version of this put the
    instruction last, behind the full validator dump and a line telling the
    reader to run `bpcad spec explain` - advice aimed at a person, useless to a
    model. Given that, a 7B model moved blade_chord_mm from 12.5 to 15 when it
    had been told in as many words to set it to 10.2: it had the answer and
    buried it.

    So the correction leads, in the imperative, and the raw validator text is
    demoted to context underneath. Human-facing CLI suggestions are stripped -
    the model cannot run a command.
    """
    # Strip lines that are PURELY advice to a human - "Run `bpcad spec explain
    # x`" - which a model cannot act on. Do NOT strip every line that mentions
    # bpcad: the keyring's own message is "...or set logo_on: false" on the
    # same line as a `bpcad measure trace` suggestion, and dropping the whole
    # line throws away the answer along with the noise.
    clean = "\n".join(
        line for line in problem.strip().splitlines()
        if not line.strip().startswith("Run `bpcad")
        and not line.strip().startswith("bpcad ")
    ).strip()

    lines = ["Your previous answer was rejected. Fix exactly this and resend:", ""]
    if hint:
        lines += [hint.strip(), ""]
    lines += [
        "Change ONLY what is listed above. Keep every other value you sent.",
        "",
        "For reference, the validator said:",
        clean,
        "",
        "You previously sent:",
        previous.strip()[:1500],
        "",
        "Send the corrected JSON object. JSON only, no prose.",
    ]
    return "\n".join(lines)


def ask_schema() -> dict:
    """
    The JSON schema handed to the daemon for constrained generation.

    Deliberately FLAT rather than mirroring PartSpec exactly: `params` is a free
    object here because a small model handles a flat form far better than a
    discriminated union, and the real PartSpec validation happens afterwards in
    Python where the errors are good. The `template` enum is the important part
    - without it, models reliably put a material or a description in that field.
    """
    from bpcad.spec import registry

    return {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Short lowercase identifier, words separated by underscores.",
            },
            # NO_TEMPLATE is in the enum deliberately. A constrained decoder
            # cannot emit anything outside it, so without this the model is
            # FORCED to name a template even when none makes the requested part.
            # Asked for a birdhouse with only a keyring and a vent available, it
            # produced a 573 cm3 solid slab with a keyring handle - and every
            # downstream check passed, because the part was manufacturable. It
            # was simply not a birdhouse.
            "template": {"type": "string", "enum": registry.names() + [NO_TEMPLATE]},
            "material": {"type": "string"},
            "nozzle_mm": {"type": "number"},
            "layer_mm": {"type": "number"},
            "print_axis": {"type": "string", "enum": ["x", "y", "z"]},
            "params": {
                "type": "object",
                "description": "Parameters for the chosen template, names exactly as listed.",
            },
        },
        "required": ["name", "template", "material", "nozzle_mm", "layer_mm", "params"],
    }


def parse_reply(raw: str) -> dict:
    """
    Turn a model's reply into a dict, forgiving the usual decorations.

    Even under schema constraint a model occasionally wraps its answer in a
    markdown fence or adds a sentence. Stripping that here is not encouraging
    sloppiness; it is refusing to fail a run over punctuation.
    """
    text = (raw or "").strip()
    if not text:
        raise ValueError("the model returned nothing at all")

    if text.startswith("```"):
        text = text.split("```")[1] if "```" in text[3:] else text[3:]
        if text.lstrip().startswith("json"):
            text = text.lstrip()[4:]
        text = text.strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise ValueError(
                "the reply is not JSON and contains no JSON object. It began: %r"
                % text[:200]
            )
        try:
            data = json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            raise ValueError("the reply is not valid JSON: %s" % exc) from exc

    if not isinstance(data, dict):
        raise ValueError(
            "the reply is a %s, but a spec must be a JSON object" % type(data).__name__
        )
    return data


DSL_SYSTEM = """You describe a 3D part as a list of primitive operations.

You do NOT write CAD code and you do NOT write CadQuery selector strings.
You choose operations from a fixed list and give each one its numbers.

Rules:
- Reply with JSON only. No prose, no markdown fences.
- `ops` is a list. Each entry has an `op` field naming the operation.
- The FIRST op must create geometry: rounded_prism, disc or arc_rod.
- Faces are addressed by NAME - top_face, front_face and so on. Never by a
  selector like ">Z" or "|Z".
- Every dimension is in millimetres and every angle is in degrees.
- A cavity must open along the print direction, never against it.
"""


WORKED_EXAMPLE = """{
  "name": "hollow_box",
  "ops": [
    {"op": "rounded_prism", "width_mm": 80, "depth_mm": 50,
     "height_mm": 60, "corner_r_mm": 3},
    {"op": "hollow", "wall_mm": 3, "opening": "top_face"},
    {"op": "pocket", "anchor": "front_face", "width_mm": 20,
     "height_mm": 20, "depth_mm": 4, "corner_r_mm": 10}
  ],
  "print_axis": "z"
}"""


def dsl_catalogue() -> str:
    """Every level-2 op with its fields, plus the legal anchors and edge groups."""
    from bpcad.spec.dsl import EDGE_GROUPS, FACE_FRAMES, OP_NAMES, AnyOp
    from pydantic import TypeAdapter

    import typing

    blocks: list[str] = []
    for member in typing.get_args(typing.get_args(AnyOp)[0]):
        fields = member.model_fields
        name = fields["op"].annotation
        literal = typing.get_args(name)[0] if typing.get_args(name) else str(name)
        lines = ["OP %s" % literal, "  %s" % (member.__doc__ or "").strip().split("\n")[0]]
        for fname, field in fields.items():
            if fname == "op":
                continue
            bounds = []
            for meta in field.metadata:
                for attr, label in (("ge", ">="), ("gt", ">"), ("le", "<="), ("lt", "<")):
                    v = getattr(meta, attr, None)
                    if v is not None:
                        bounds.append("%s %g" % (label, v))
            default = field.default
            shown = "required" if field.is_required() else (
                "%g" % default if isinstance(default, float) else str(default)
            )
            lines.append("    %-18s default %-8s %-14s %s"
                         % (fname, shown, ", ".join(bounds),
                            (field.description or "").split(".")[0]))
        blocks.append("\n".join(lines))

    return "\n\n".join(blocks) + (
        "\n\nANCHOR NAMES: %s"
        "\nEDGE GROUPS:  %s"
        % (", ".join(sorted(FACE_FRAMES)), ", ".join(sorted(EDGE_GROUPS)))
    )


def build_dsl_prompt(
    request: str,
    material: str,
    nozzle_mm: float,
    layer_mm: float,
    why_escalated: str = "",
) -> str:
    """The level-2 task: compose ops, because no template fitted."""
    parts = ["Requested part:", "  %s" % request.strip(), ""]
    if why_escalated:
        parts += [
            "No template could be made to fit. The last attempt failed with:",
            "  %s" % why_escalated.split("\n")[0][:300],
            "",
        ]
    parts += [
        "Build it from primitive operations instead.",
        "",
        "Fixed settings - copy these into your answer unchanged:",
        "  material: %s" % material,
        "  nozzle_mm: %g" % nozzle_mm,
        "  layer_mm: %g" % layer_mm,
        "",
        # A worked example, not a description of one. Ollama does not enforce
        # the per-op fields even when the schema declares them, so a model given
        # only the catalogue reliably answers {"op": "rounded_prism"} with no
        # numbers at all. Showing one complete valid answer fixes that far more
        # reliably than any amount of instruction.
        "EVERY op needs its numbers. An op with only its name is rejected.",
        "",
        "Here is a complete, valid answer for a different part - a hollow box",
        "80 mm wide, 60 mm tall and 50 mm deep with a 20 mm hole in the front:",
        "",
        WORKED_EXAMPLE,
        "",
        "Now do the same for the part requested above.",
        "",
        "Operations available:",
        "",
        dsl_catalogue(),
    ]
    return "\n".join(parts)


def dsl_schema() -> dict:
    """Constrained shape for a level-2 answer."""
    from bpcad.spec.dsl import OP_NAMES

    return {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "material": {"type": "string"},
            "nozzle_mm": {"type": "number"},
            "layer_mm": {"type": "number"},
            "print_axis": {"type": "string", "enum": ["x", "y", "z"]},
            "ops": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "properties": {"op": {"type": "string", "enum": list(OP_NAMES)}},
                    "required": ["op"],
                },
            },
        },
        "required": ["name", "ops"],
    }


# ---------------------------------------------------------------------------
# refinement: changing a part you have already built
# ---------------------------------------------------------------------------

REFINE_OPS_SYSTEM = """You adjust an existing 3D part built from primitive operations.

You do NOT write CAD code. You are given a list of operations that already
builds, and one instruction about what to change. You reply with the COMPLETE
updated list.

Rules:
- Reply with JSON only. No prose, no markdown fences.
- Return {"ops": [...]} holding the whole list, in order, with every operation
  carrying all of its numbers. An operation with only its name is rejected.
- Keep the operations that were already right. Change, add or remove only what
  the instruction asks for.
- The FIRST operation must create geometry: rounded_prism, disc or arc_rod.
- Faces are addressed by NAME - top_face, front_face and so on. Never by a
  selector like ">Z".
- A cavity must open along the print direction, never against it.
- Every dimension is in millimetres and every angle is in degrees.
"""


REFINE_SYSTEM = """You adjust an existing 3D part specification.

You do NOT write CAD code and you do NOT rewrite the whole specification. You
are given a part that already builds, and one instruction about what to change.
You reply with ONLY the parameters that must change.

Rules:
- Reply with JSON only. No prose, no markdown fences.
- Return a "params" object holding ONLY the parameters you are changing.
  Everything you leave out keeps its current value.
- To let a parameter go back to being derived from the frame, set it to null.
- Never change a parameter the instruction did not ask about. Changing
  everything "to be safe" is the wrong answer - it throws away values that
  were derived to fit and were already right.
- If the instruction asks for a FEATURE that no parameter can express - a
  perch, a feeding tray, a second compartment - do NOT approximate it by
  changing sizes. Answer {"cannot": "what you were asked for"} and say so.
  Making the part bigger is not a feeding area.
- Every dimension is in millimetres and every angle is in degrees.
- Respect the stated bounds.
"""


def build_refine_ops_prompt(
    spec,
    instruction: str,
    report=None,
) -> str:
    """
    Refining a part built from primitives.

    The WHOLE operation list is asked for rather than a diff. Operations are
    ordered and they compose - a pocket cuts whatever is under it at the time -
    so "change op 2" is ambiguous in a way that "change wall_mm" is not. Asking
    for the full list costs tokens and removes the ambiguity.
    """
    import json

    lines = ["The part is currently built from these operations:", ""]
    lines.append(json.dumps({"ops": [dict(o) for o in (spec.ops or [])]}, indent=2))
    lines.append("")

    if report is not None:
        m = report.mesh
        lines += [
            "What that actually built:",
            "  envelope   %.1f x %.1f x %.1f mm" % m.bbox_mm,
            "  volume     %.1f cm3" % m.volume_cm3,
            "  solid      %.0f%% of its own bounding box" % (100 * m.solidity),
        ]
        for w in getattr(m, "warnings", []):
            lines.append("  NOTE       %s" % w.split(".")[0])
        lines.append("")

    lines += [
        "Change requested:",
        "  %s" % instruction.strip(),
        "",
        "Operations available:",
        "",
        dsl_catalogue(),
        "",
        "Reply with {\"ops\": [...]} - the complete updated list, every operation",
        "carrying all of its numbers.",
    ]
    return "\n".join(lines)


def build_refine_prompt(
    spec,
    instruction: str,
    template_info: dict | None = None,
    report=None,
    measurements: dict | None = None,
) -> str:
    """
    The current part, what it measured, and the one thing to change.

    Showing the MEASURED result rather than only the parameters matters: an
    instruction like "make it thinner" is about the part that came out, and the
    model needs to see what came out to know which parameter moves it.
    """
    import yaml

    from bpcad.spec import registry

    lines: list[str] = ["The current specification:", ""]
    current = {
        "template": spec.template,
        "params": dict(spec.params or {}),
    }
    lines.append(yaml.safe_dump(current, sort_keys=False).rstrip())
    lines.append("")

    if report is not None:
        m = report.mesh
        lines += [
            "What that actually built:",
            "  envelope   %.2f x %.2f x %.2f mm" % m.bbox_mm,
            "  volume     %.3f cm3" % m.volume_cm3,
            "  bodies     %d" % m.body_count,
            "  supports   %s" % ("needed" if report.overhang.supports_needed else "none"),
        ]
        if report.features is not None:
            smallest = report.features.checks[:3]
            for c in smallest:
                lines.append("  %-24s %.3f mm  %s" % (c.name, c.value_mm, c.status))
        lines.append("")

    if measurements:
        lines.append("Measured from the reference image. These are MEASURED, not")
        lines.append("estimated - prefer them over anything in the instruction text:")
        for k, v in measurements.items():
            lines.append("  %s: %s" % (k, v))
        lines.append("")

    lines += ["Change requested:", "  %s" % instruction.strip(), ""]

    if template_info is None and spec.template:
        try:
            t = registry.get(spec.template)
            template_info = {"params": t.params_model.model_fields}
        except Exception:
            template_info = None

    if spec.template:
        lines.append("Parameters you may change on template %r:" % spec.template)
        lines.append("")
        lines.append(_param_lines(spec.template))

    lines.append("")
    lines.append("Reply with the parameters that change, and nothing else.")
    return "\n".join(lines)


def _param_lines(template: str) -> str:
    """One line per parameter: name, current bounds, and what it does."""
    from bpcad.spec import registry

    try:
        model = registry.get(template).params_model
    except Exception:
        return "(unknown template)"

    out = []
    for fname, field in model.model_fields.items():
        bounds = []
        for meta in field.metadata:
            for attr, label in (("ge", ">="), ("gt", ">"), ("le", "<="), ("lt", "<")):
                v = getattr(meta, attr, None)
                if v is not None:
                    bounds.append("%s %g" % (label, v))
        out.append(
            "  %-22s %-18s %s"
            % (fname, ", ".join(bounds), (field.description or "").split(".")[0])
        )
    return "\n".join(out)


def refine_schema(template: str) -> dict:
    """
    Constrain a refinement to a params object.

    Deliberately NOT the whole spec: asking a small model to restate a
    specification it was not asked to change is asking it to make mistakes in
    the parts it was supposed to leave alone.
    """
    return {
        "type": "object",
        "properties": {
            "params": {
                "type": "object",
                "description": "Only the parameters that change.",
            },
            "note": {
                "type": "string",
                "description": "One short sentence on what you changed and why.",
            },
            "cannot": {
                "type": "string",
                "description": (
                    "Set this INSTEAD of params if no parameter can express what "
                    "was asked for. Say what was asked for."
                ),
            },
        },
    }
