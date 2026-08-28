"""
PartSpec - the durable artifact of this whole project.

The model does not write CAD code. It fills THIS IN. Everything downstream of a
spec is deterministic Python, so a hand-written spec.yaml is a first-class
input and not a debugging fallback.

That makes the schema the user interface, and it is written accordingly:

  * every dimension field carries its unit in the name (`wall_mm`, not `wall`)
  * every field has bounds, so a wrong value is rejected here rather than
    becoming a broken solid or, worse, a plausible wrong one
  * every validation error names the field and its legal range, because when
    the model fails the fallback is a person editing YAML and that path has to
    be pleasant
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

PRINT_AXES = ("x", "y", "z")


class Assumption(BaseModel):
    """
    A dimension that could NOT be measured and had to be chosen.

    Measure, never estimate. When a dimension genuinely cannot be measured -
    depth from a front-on photo, a plan-view corner radius - it does not
    quietly become a number in the code. It becomes one of these, and it
    appears in the report under a heading that says so.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, description="Parameter this stands in for.")
    value: float | str = Field(..., description="The value used.")
    units: str = Field("mm", description="Units of `value`.")
    why: str = Field(
        ..., min_length=1, description="Why it could not be measured. Required."
    )


class ScaleDeparture(BaseModel):
    """
    A deliberate departure from true scale, with its numeric factor.

    Never silent. The reference keyring's handle is 2.67x oversize because true
    scale puts it at 0.90 mm, under a 0.40 mm nozzle's resolution. That is a
    sound decision and it is reported every single build.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1)
    factor: float = Field(..., gt=0, description="used / true. 2.67 means 2.67x oversize.")
    true_mm: float = Field(..., gt=0, description="What true scale would give, mm.")
    used_mm: float = Field(..., gt=0, description="What was actually built, mm.")
    why: str = Field(..., min_length=1, description="Why the departure was necessary.")


class PartSpec(BaseModel):
    """
    One part, completely described.

    Level 1 names a template and its parameters - no geometry risk at all.
    Level 2 composes named DSL primitives - still no geometry risk.
    Level 3 is raw CadQuery, off by default, one attempt, REVIEW REQUIRED.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(
        ..., min_length=1, max_length=64,
        description="Part name. Used for the bundle directory and file names.",
    )
    level: Literal[1, 2, 3] = Field(
        1, description="1 = template, 2 = DSL composition, 3 = raw CadQuery."
    )
    material: str = Field(..., min_length=1, description="Material name, must exist in config.")
    nozzle_mm: float = Field(
        ..., gt=0.05, le=2.0, description="Nozzle width in mm. Typical 0.4."
    )
    layer_mm: float = Field(
        ..., gt=0.01, le=1.0, description="Layer height in mm. Typical 0.12 to 0.28."
    )
    print_axis: Literal["x", "y", "z"] = Field(
        "z", description="Build direction. The part grows along this axis."
    )

    template: str | None = Field(None, description="Template name. Required at level 1.")
    params: dict[str, Any] = Field(
        default_factory=dict, description="Template parameters. Validated against the template."
    )
    ops: list[dict[str, Any]] = Field(
        default_factory=list, description="Level 2 only: DSL operations, in order."
    )
    script: str | None = Field(
        None, description="Level 3 only: raw CadQuery. Requires --allow-level-3."
    )

    assumptions: list[Assumption] = Field(default_factory=list)
    scale_departures: list[ScaleDeparture] = Field(default_factory=list)

    stl_tolerance: float | None = Field(
        None, gt=0, le=1.0,
        description=(
            "STL linear deflection. Leave unset to use config. Finer is NOT better - "
            "too fine produces tens of thousands of degenerate facets and a mesh that "
            "is no longer watertight."
        ),
    )
    stl_angular_tolerance: float | None = Field(
        None, gt=0, le=2.0, description="STL angular deflection. Leave unset to use config."
    )

    @field_validator("layer_mm")
    @classmethod
    def _layer_under_nozzle(cls, v: float, info) -> float:
        nozzle = info.data.get("nozzle_mm")
        if nozzle is not None and v > nozzle * 0.8:
            raise ValueError(
                "layer_mm %.3f is more than 80%% of nozzle_mm %.3f. Layers that "
                "thick do not bond reliably. Legal range here: 0.01 to %.3f mm."
                % (v, nozzle, nozzle * 0.8)
            )
        return v

    @model_validator(mode="after")
    def _level_matches_content(self) -> "PartSpec":
        if self.level == 1:
            if not self.template:
                raise ValueError(
                    "level 1 needs `template`. Run `bpcad spec explain <template>` "
                    "to see the templates available and their parameters."
                )
            if self.ops:
                raise ValueError("level 1 takes `params`, not `ops`. Use level 2 for ops.")
            if self.script:
                raise ValueError("level 1 must not carry `script`. That is level 3.")
        elif self.level == 2:
            if not self.ops:
                raise ValueError("level 2 needs at least one entry in `ops`.")
            if self.script:
                raise ValueError("level 2 must not carry `script`. That is level 3.")
        else:
            if not self.script:
                raise ValueError("level 3 needs `script`.")
            if self.ops:
                raise ValueError("level 3 takes `script`, not `ops`.")
        return self


class TemplateParams(BaseModel):
    """
    Base for every template's parameter model.

    extra="forbid" is deliberate and load-bearing. A misspelled parameter must
    be an error naming the field, not a value silently ignored while the part
    builds at its default and looks almost right.
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


def format_validation_error(exc: Exception, context: str = "") -> str:
    """
    Turn a pydantic ValidationError into something worth reading at 11pm.

    Names the offending field, what was given, and what would be legal. This is
    the primary interface when the model cannot do the job, so it gets the same
    care as anything user-facing.
    """
    from pydantic import ValidationError

    if not isinstance(exc, ValidationError):
        return str(exc)

    lines: list[str] = []
    if context:
        lines.append(context)
    for err in exc.errors():
        loc = ".".join(str(p) for p in err["loc"]) or "(root)"
        lines.append("  %s" % loc)
        lines.append("      problem : %s" % err["msg"])
        if "input" in err:
            lines.append("      given   : %r" % (err["input"],))
        ctx = err.get("ctx") or {}
        bounds = []
        for key, label in (
            ("ge", ">="), ("gt", ">"), ("le", "<="), ("lt", "<"),
            ("min_length", "min length"), ("max_length", "max length"),
        ):
            if key in ctx:
                bounds.append("%s %s" % (label, ctx[key]))
        if bounds:
            lines.append("      legal   : %s" % ", ".join(bounds))
    return "\n".join(lines)
