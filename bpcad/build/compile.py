"""
PartSpec -> geometry.

This is the seam the whole project turns on. Everything above it - the model,
the agent, the CLI - exists to produce a PartSpec. Everything below it is
deterministic Python that never touches a model, so a hand-written spec.yaml
gets exactly the same treatment as one a model wrote.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from bpcad.build.helpers import BuildResult, BuildLog
from bpcad.spec import registry
from bpcad.spec.dsl import DslError, run_ops
from bpcad.spec.schema import PartSpec, format_validation_error


class SpecError(ValueError):
    """A spec could not be read, validated or compiled. The message says which."""


class Level3NotAllowed(SpecError):
    """
    A level-3 spec was compiled without --allow-level-3.

    Level 3 is raw CadQuery. With no frontier fallback there is no model in this
    system that should be trusted to write it, and spending retries on it wastes
    wall-clock for a result that needs human review anyway.
    """


REVIEW_REQUIRED = "REVIEW REQUIRED: produced by raw CadQuery (level 3), not a validated template"


def _count_bodies(solid) -> int:
    """
    How many separate solids a scene ended up with.

    `vals()` is not this: a compound of two disjoint solids is ONE val. The
    solids selector walks into the compound, which is what the exporter and
    the slicer both see.
    """
    try:
        return max(len(solid.solids().vals()), 1)
    except Exception:
        return 1


def load_spec(path: str | Path) -> tuple[PartSpec, Path]:
    """
    Read a spec.yaml. Returns the spec and the directory it came from, because
    relative paths inside a spec resolve against the spec file, not the shell's
    working directory.
    """
    p = Path(path)
    if not p.is_file():
        raise SpecError("no spec at %s" % p)

    try:
        data = yaml.safe_load(p.read_text())
    except yaml.YAMLError as exc:
        raise SpecError("could not parse %s as YAML: %s" % (p, exc)) from exc

    if not isinstance(data, dict):
        raise SpecError(
            "%s should contain a mapping of fields, got %s"
            % (p, type(data).__name__)
        )

    try:
        spec = PartSpec.model_validate(data)
    except ValidationError as exc:
        raise SpecError(format_validation_error(exc, "%s is not a valid spec:" % p)) from exc

    return spec, p.parent


def validate_params(spec: PartSpec) -> Any:
    """
    Check a level-1 spec's params against its template's parameter model.

    extra="forbid" on the model means a misspelled parameter is an error naming
    the field, rather than a value silently ignored while the part builds at its
    default and looks almost right.
    """
    template = registry.get(spec.template)
    try:
        return template.params_model.model_validate(spec.params)
    except ValidationError as exc:
        raise SpecError(
            format_validation_error(
                exc,
                "template %r rejected these params. Run "
                "`bpcad spec explain %s` for the full schema with units, "
                "defaults and bounds:" % (spec.template, spec.template),
            )
        ) from exc


def _compile_level_3(spec: PartSpec) -> BuildResult:
    """
    Run a raw CadQuery script.

    This is arbitrary code by design and by opt-in. The script must leave its
    finished part in a variable called `part`.
    """
    import cadquery as cq

    namespace: dict[str, Any] = {"cq": cq, "cadquery": cq, "spec": spec}
    try:
        exec(compile(spec.script, "<level-3 script>", "exec"), namespace)
    except Exception as exc:
        raise SpecError(
            "the level-3 script raised %s: %s" % (type(exc).__name__, exc)
        ) from exc

    part = namespace.get("part")
    if part is None:
        raise SpecError(
            "the level-3 script finished without setting `part`. Assign the "
            "finished solid to a variable named `part`."
        )

    log = BuildLog()
    log.notes.append(REVIEW_REQUIRED)
    return BuildResult(solid=part, print_solid=part, features={}, log=log)


def compile_spec(
    spec: PartSpec,
    base_dir: str | Path | None = None,
    allow_level_3: bool = False,
) -> BuildResult:
    """
    Turn a validated PartSpec into solids, named features and a report.

    No model is involved at any point. A spec written by hand and a spec written
    by a model take the identical path through here.
    """
    if spec.level == 1:
        params = validate_params(spec)
        template = registry.get(spec.template)
        try:
            return template.builder(params, spec, base_dir)
        except FileNotFoundError as exc:
            raise SpecError(str(exc)) from exc

    if spec.level == 2:
        try:
            scene = run_ops(spec.ops, print_axis=spec.print_axis)
        except DslError as exc:
            raise SpecError(str(exc)) from exc
        return BuildResult(
            solid=scene.solid,
            print_solid=scene.solid,
            features=dict(scene.features),
            log=scene.log,
            # COUNT THE BODIES, DO NOT ASSUME ONE.
            #
            # This defaulted to 1, and the export check compares against it, so
            # every level-2 part that came out as more than one body was
            # rejected with "exported 2 separate bodies, expected 1". That
            # rules out every print-in-place mechanism there is: a hinge, a
            # captive washer, a spinner, anything with a moving part is TWO
            # bodies with a gap between them, and being two bodies is the
            # whole point of it.
            #
            # This is not the check being weakened. Its job is to confirm the
            # EXPORT preserved what the geometry had - it still catches a mesh
            # that shattered or fused on the way out. A template knows its own
            # body count; at level 2 the scene is the only thing that knows.
            body_count_expected=_count_bodies(scene.solid),
        )

    if not allow_level_3:
        raise Level3NotAllowed(
            "spec %r is level 3 (raw CadQuery), which is off by default. There "
            "is no model in this system that should be trusted to write raw "
            "CadQuery, and anything produced this way needs human review. Pass "
            "--allow-level-3 if you wrote the script yourself." % spec.name
        )
    return _compile_level_3(spec)


def export_solid(
    solid,
    path: str | Path,
    tolerance: float | None = None,
    angular_tolerance: float | None = None,
) -> Path:
    """
    Export a solid, then check the result is still watertight.

    An export tolerance that is too FINE produces tens of thousands of
    degenerate facets and a mesh that is no longer watertight. It is not a
    quality dial - finer is not better. Whatever is used, the result is checked
    rather than assumed.
    """
    import cadquery as cq

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)

    kwargs: dict[str, Any] = {}
    if tolerance is not None:
        kwargs["tolerance"] = tolerance
    if angular_tolerance is not None:
        kwargs["angularTolerance"] = angular_tolerance

    cq.exporters.export(solid, str(p), **kwargs)
    return p


def check_export(path: str | Path, expected_bodies: int = 1) -> list[str]:
    """Post-export sanity. Returns a list of problems, empty if all is well."""
    from bpcad.verify.mesh import check_mesh

    report = check_mesh(path)
    problems = list(report.problems)
    if report.body_count != expected_bodies:
        problems.append(
            "exported %d separate bodies, expected %d"
            % (report.body_count, expected_bodies)
        )
    return problems
