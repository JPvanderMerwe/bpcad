"""
Template discovery, and `bpcad spec explain`.

A template is three things: a name, a Pydantic parameter model, and a builder.
The registry keeps them together so the CLI, the compiler and (later) the agent
all see the same catalogue and cannot drift apart.

`explain` exists because when the model cannot do the job the fallback is a
person editing YAML, and that person needs the full parameter list with units,
defaults and bounds without reading the source.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from pydantic import BaseModel


class TemplateError(KeyError):
    """No such template. The message lists the ones that do exist."""


@dataclass(frozen=True)
class Template:
    name: str
    summary: str
    params_model: type[BaseModel]
    builder: Callable
    anchors: tuple[str, ...] = ()
    print_notes: tuple[str, ...] = ()


_REGISTRY: dict[str, Template] = {}


def register(template: Template) -> Template:
    if template.name in _REGISTRY:
        raise ValueError("template %r is already registered" % template.name)
    _REGISTRY[template.name] = template
    return template


def _load_builtins() -> None:
    """Import the built-in templates so they self-register. Idempotent."""
    from bpcad.build.templates import keyring_device, louvre_vent  # noqa: F401


def names() -> list[str]:
    _load_builtins()
    return sorted(_REGISTRY)


def get(name: str) -> Template:
    _load_builtins()
    if name not in _REGISTRY:
        raise TemplateError(
            "no template named %r. Available: %s. Run "
            "`bpcad spec explain <name>` for a template's parameters."
            % (name, ", ".join(sorted(_REGISTRY)) or "(none)")
        )
    return _REGISTRY[name]


def _bounds_of(field) -> str:
    """Read the numeric bounds off a pydantic FieldInfo, as text."""
    parts: list[str] = []
    for meta in field.metadata:
        for attr, label in (("ge", ">="), ("gt", ">"), ("le", "<="), ("lt", "<")):
            value = getattr(meta, attr, None)
            if value is not None:
                parts.append("%s %g" % (label, value))
    return ", ".join(parts)


def explain(name: str) -> str:
    """
    The full parameter schema for a template: name, type, default, bounds and
    description, one row each.
    """
    t = get(name)
    lines: list[str] = []
    lines.append("template   %s" % t.name)
    lines.append("           %s" % t.summary)
    lines.append("")

    fields = t.params_model.model_fields
    width = max((len(n) for n in fields), default=10)
    lines.append("PARAMETERS  (%d)" % len(fields))
    for fname, field in fields.items():
        default = field.default
        if field.is_required():
            shown = "REQUIRED"
        elif default is None:
            shown = "none"
        elif isinstance(default, float):
            shown = "%g" % default
        else:
            shown = str(default)

        type_name = getattr(field.annotation, "__name__", str(field.annotation))
        lines.append("  %-*s  %-8s default %-10s %s"
                     % (width, fname, type_name, shown, _bounds_of(field)))
        if field.description:
            lines.append("  %-*s  %s" % (width, "", field.description))
    lines.append("")

    if t.anchors:
        lines.append("ANCHORS  (level-2 ops address these by name, never by CadQuery selector)")
        for a in t.anchors:
            lines.append("  %s" % a)
        lines.append("")

    if t.print_notes:
        lines.append("PRINT NOTES")
        for n in t.print_notes:
            lines.append("  %s" % n)
        lines.append("")

    lines.append("EXAMPLE spec.yaml")
    lines.append("  name: my_%s" % t.name)
    lines.append("  level: 1")
    lines.append("  material: petg")
    lines.append("  nozzle_mm: 0.4")
    lines.append("  layer_mm: 0.2")
    lines.append("  template: %s" % t.name)
    lines.append("  params:")
    shown = 0
    for fname, field in fields.items():
        if field.is_required() or shown < 3:
            default = field.default
            value = "REPLACE_ME" if field.is_required() else (
                "%g" % default if isinstance(default, float) else default
            )
            lines.append("    %s: %s" % (fname, value))
            shown += 1
    return "\n".join(lines)


def catalogue() -> str:
    """One line per template, for a prompt or a quick look."""
    return "\n".join("  %-16s %s" % (n, get(n).summary) for n in names())
