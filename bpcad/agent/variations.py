"""
One prompt, several genuinely different parts to choose from.

WHY THIS IS NOT "RUN THE MODEL FOUR TIMES"
------------------------------------------
The obvious way to offer options is to ask the model four times and hope it
answers differently. On this hardware that is four times two and a half
minutes, and small models are not diverse - asked the same question four times
they mostly give the same answer with one number nudged. Ten minutes for four
near-identical bowls.

So the model is asked ONCE, for the part. The options come from walking the
template's own axes afterwards, deterministically, in Python. That is instant,
it is reproducible, and the variants differ in ways the template guarantees are
buildable rather than in ways a model guessed at.

WHAT COUNTS AS A DIFFERENT OPTION
----------------------------------
Not a different number - a different OBJECT. A bowl and the same bowl 4 mm
taller are one option shown twice, and offering that is how a tool teaches you
it has nothing to say. Variants are therefore ranked by how far apart they
actually are, measured on the built geometry, and any that land on top of
another are dropped rather than padded out to a round number.

The axes are declared per template because only the template knows which of its
parameters change the CHARACTER of the thing and which merely resize it.
Changing `width_mm` gives you the same box; changing `finish` gives you a
different object.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

# Per template: the parameters worth varying, and the values worth trying.
#
# Deliberately hand-written rather than derived from the schema. Every Literal
# field is NOT automatically a good variation axis - `print_axis` is an enum and
# varying it produces the same part lying on its side - and no numeric field is
# a good one without knowing what it means. This is a short list because it is
# a judged list.
# Axes whose values change the CHARACTER of the part rather than its size.
# Two variants that differ on one of these are different by definition and are
# never culled by the measured test - a board finish and a slat finish differ
# by 1.7% of volume and not at all in bounding box, and look nothing like each
# other. Measuring volume to decide whether a surface finish is interesting is
# measuring the wrong thing.
STYLE_AXES = {"profile", "pattern", "finish", "gusset"}

AXES: dict[str, list[tuple[str, list[Any]]]] = {
    "vessel": [
        ("profile", ["flared", "straight", "belly", "cylinder"]),
        ("pattern", ["solid", "cells"]),
        ("cell_seed", [7, 23, 61, 104]),
    ],
    "enclosure": [
        ("finish", ["plain", "board", "slat"]),
        ("roof_pitch_deg", [18.0, 0.0, 32.0]),
        ("corner_r_mm", [3.0, 10.0]),
    ],
    "bracket": [
        ("gusset", [True, False]),
    ],
    "louvre_vent": [
        ("blade_count", [4, 3, 6]),
    ],
    "keyring_device": [
        ("corner_r_mm", [2.0, 6.0]),
    ],
}

# How different two variants have to be to both be worth showing. A fraction of
# the larger of the two volumes, plus a check on the envelope, because a bowl
# and a bowl with a hole pattern differ hugely by volume while looking related,
# and two profiles can differ in shape at nearly equal volume.
MIN_VOLUME_APART = 0.04
MIN_ENVELOPE_APART_MM = 2.0


@dataclass
class Variant:
    """One option: the spec that makes it, and what it measured."""

    label: str
    params: dict[str, Any]
    changed: dict[str, Any] = field(default_factory=dict)
    volume_cm3: float = 0.0
    envelope_mm: tuple[float, float, float] = (0.0, 0.0, 0.0)
    verdict: str = ""
    ok: bool = False
    name: str = ""
    note: str = ""


def resolved_base(template: str, base_params: dict) -> dict:
    """
    The base parameters with the template's own defaults filled in.

    Without this, "is this value already the base?" is answered against a dict
    that is usually nearly empty, so the default value of every axis is offered
    as a variation of itself. A birdhouse was offered "roof pitch 18" as an
    alternative to a roof pitched 18 degrees.
    """
    from bpcad.spec import registry

    try:
        model = registry.get(template).params_model
        return model.model_validate(base_params).model_dump()
    except Exception:
        return dict(base_params)


def plan(template: str, base_params: dict, count: int = 4) -> list[dict]:
    """
    Parameter sets to try, base first, then one axis moved at a time.

    ONE AXIS AT A TIME, not a random draw across all of them. Moving three
    things at once gives four options that are all different from the base and
    all indistinguishable from each other, and none of them tells you which
    change did what. Moving one thing means the options line up along axes a
    person can then ask for more of.
    """
    out = [dict(base_params)]
    axes = AXES.get(template, [])
    resolved = resolved_base(template, base_params)

    for name, values in axes:
        current = resolved.get(name)
        for value in values:
            if value == current:
                continue
            candidate = dict(base_params)
            candidate[name] = value
            if candidate in out:
                continue
            out.append(candidate)
            if len(out) >= count * 3:      # over-generate; most will be culled
                return out
    return out


def _distinct(new: Variant, kept: list[Variant]) -> bool:
    """
    Is this variant worth showing next to the ones already chosen?

    A change on a STYLE axis is distinct by definition. Everything else has to
    prove it on the measured geometry.
    """
    if any(key in STYLE_AXES for key in new.changed):
        return all(other.changed != new.changed for other in kept)

    for other in kept:
        bigger = max(new.volume_cm3, other.volume_cm3, 1e-9)
        volume_apart = abs(new.volume_cm3 - other.volume_cm3) / bigger
        envelope_apart = max(
            abs(a - b) for a, b in zip(new.envelope_mm, other.envelope_mm)
        )
        if volume_apart < MIN_VOLUME_APART and envelope_apart < MIN_ENVELOPE_APART_MM:
            return False
    return True


# Scale steps for a part with no named parameters. A spread either side of
# what was asked for, close enough to be useful and far enough apart to be
# told apart on a bed.
SCALE_STEPS = (0.8, 0.9, 1.1, 1.25)


def _scaled_op(op: dict, factor: float) -> dict:
    """
    One op with every length multiplied, and nothing else touched.

    ALMOST every length in the DSL ends in `_mm`, which makes this mostly exact
    rather than a list of field names that would rot the first time an op
    gained one. Counts, angles and modes do not end in _mm and are carried
    through untouched - scaling `rotate_deg` would turn a variant into a
    different part, and scaling `count` is not even meaningful.

    `points` IS THE EXCEPTION AND IT CAUGHT ME. A profile_extrude's outline is
    a list of bare (x, y) pairs, and with the default scale_mm of 1.0 those
    pairs ARE millimetres. Trusting the suffix rule scaled the height and left
    the outline alone: a 90 x 90 x 70 pot came back as 90 x 90 x 56, taller
    and shorter but never narrower. So points are scaled here, and `scale_mm`
    is then left alone - doing both would scale the outline twice.
    """
    out: dict = {}
    for key, value in op.items():
        if key == "step" and isinstance(value, dict):
            out[key] = _scaled_op(value, factor)
        elif key == "points" and isinstance(value, list):
            out[key] = [[round(float(x) * factor, 4), round(float(y) * factor, 4)]
                        for x, y in value]
        elif key == "scale_mm":
            out[key] = value
        elif key.endswith("_mm") and isinstance(value, (int, float)):
            out[key] = round(float(value) * factor, 4)
        else:
            out[key] = value
    return out


def scale_plan(ops: list[dict], count: int = 4) -> list[tuple[str, float, list[dict]]]:
    """
    (label, factor, ops) for a part that has ops instead of parameters.

    WHY SCALE AND NOTHING ELSE. Varying a level-1 part means nudging named
    parameters - wall thickness, blade count, rim diameter - and the template
    says what those mean. A level-2 composition has no such names: it is a
    list of primitives, and there is no field in it that means "wall". The one
    change that is unambiguously right for any of them is size.

    That matters most for an imported mesh, which is exactly the case with no
    parameters: somebody uploads an STL, the fitter recovers an outline, and
    "more versions of this" can honestly mean a bigger one and a smaller one.
    Anything cleverer would be inventing intent that is not in the file.
    """
    out = []
    for factor in SCALE_STEPS[:count]:
        label = "%d%% of the original" % round(factor * 100)
        out.append((label, factor, [_scaled_op(op, factor) for op in ops]))
    return out


def build_scale_variants(spec, cfg, count: int = 4, out_root: str = "",
                         on_event=None) -> list[Variant]:
    """
    Build size variants of a spec that carries ops rather than parameters.

    Same discipline as build_variants: one that fails to build is dropped, not
    offered. An option that turns out broken when clicked is worse than one
    fewer option.
    """
    from bpcad import api

    emit = on_event or (lambda kind, payload: None)
    ops = list(getattr(spec, "ops", []) or [])
    if not ops:
        return []

    kept: list[Variant] = []
    for index, (label, factor, scaled) in enumerate(scale_plan(ops, count)):
        digest = hashlib.sha1(
            ("%s:%.3f" % (spec.name, factor)).encode()
        ).hexdigest()[:6]
        name = "%s_%s" % (spec.name, digest)
        emit("variant", {"index": index, "label": label})
        try:
            candidate = spec.model_copy(update={"name": name, "ops": scaled})
            built = api.build(
                spec=candidate,
                out_dir="%s/%s" % (out_root.rstrip("/"), name) if out_root else None,
                render=False,
            )
        except Exception as exc:
            emit("variant_dropped",
                 {"label": label, "why": str(exc).split("\n")[0][:160]})
            continue

        mesh = built.report.mesh
        kept.append(Variant(
            label=label,
            params={"scale": factor},
            changed={"scale": factor},
            volume_cm3=float(mesh.volume_cm3),
            envelope_mm=tuple(round(float(v), 2) for v in mesh.bbox_mm),
            verdict=built.report.verdict,
            ok=bool(built.report.ok),
            name=name,
        ))
        emit("variant_built", {"label": label, "name": name,
                               "volume_cm3": float(mesh.volume_cm3)})
    return kept


def build_variants(
    spec,
    cfg,
    count: int = 4,
    out_root: str = "",
    on_event=None,
) -> list[Variant]:
    """
    Build the options and return the distinct ones, best first.

    A variant that fails to build is DROPPED, not reported as an option. The
    whole point is a set of things you can actually print, and an option that
    turns out to be broken when clicked is worse than one fewer option.
    """
    from bpcad import api

    emit = on_event or (lambda kind, payload: None)
    template = getattr(spec, "template", None)
    base = dict(getattr(spec, "params", {}) or {})
    if not template:
        return []

    kept: list[Variant] = []
    for index, params in enumerate(plan(template, base, count)):
        if len(kept) >= count:
            break

        changed = {k: v for k, v in params.items() if base.get(k) != v}
        label = _label(changed) if changed else "as asked"
        digest = hashlib.sha1(
            json.dumps(params, sort_keys=True, default=str).encode()
        ).hexdigest()[:6]
        name = "%s_%s" % (spec.name, digest)

        emit("variant", {"index": index, "label": label})
        try:
            candidate = api.validate_spec({
                "name": name,
                "level": 1,
                "material": spec.material,
                "nozzle_mm": spec.nozzle_mm,
                "layer_mm": spec.layer_mm,
                "template": template,
                "params": params,
            })
            built = api.build(
                spec=candidate,
                out_dir="%s/%s" % (out_root.rstrip("/"), name) if out_root else None,
                render=False,
            )
        except Exception as exc:
            # Not every combination is legal, and that is the templates doing
            # their job. A refused variant is one fewer option, not a failure.
            emit("variant_dropped", {"label": label, "why": str(exc).split("\n")[0][:160]})
            continue

        mesh = built.report.mesh
        variant = Variant(
            label=label,
            params=params,
            changed=changed,
            volume_cm3=float(mesh.volume_cm3),
            envelope_mm=tuple(round(float(v), 2) for v in mesh.bbox_mm),
            verdict=built.report.verdict,
            ok=bool(built.report.ok),
            name=name,
        )
        if not _distinct(variant, kept):
            emit("variant_dropped", {"label": label, "why": "same as one already offered"})
            continue

        kept.append(variant)
        emit("variant_built", {
            "label": label, "name": name, "verdict": variant.verdict,
            "volume_cm3": variant.volume_cm3, "envelope_mm": list(variant.envelope_mm),
        })

    return kept


def _label(changed: dict) -> str:
    """A short human name for what makes this option different."""
    parts = []
    for key, value in changed.items():
        key = key.replace("_mm", "").replace("_deg", "").replace("_", " ")
        if isinstance(value, bool):
            parts.append(key if value else "no %s" % key)
        elif isinstance(value, float):
            parts.append("%s %g" % (key, value))
        else:
            parts.append(str(value))
    return ", ".join(parts) or "as asked"
