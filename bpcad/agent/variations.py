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
