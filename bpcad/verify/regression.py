"""
Regression baselines.

A part that silently changes shape between builds is the failure this catches.
The signature is deliberately coarse - volume, bounding box and face count,
each rounded - so that harmless floating-point drift does not cry wolf while a
real geometry change always does.

Face count is included because it is the one field that moves when a fillet
starts or stops applying, which is exactly the failure mode that matters here.
It also makes the signature sensitive to a CadQuery or OCC version change,
which is a real change to the output and should be acknowledged deliberately
with --update-baseline rather than ignored.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from bpcad.verify.mesh import MeshReport

# Rounding applied before hashing. Loose enough to absorb noise, tight enough
# that a change you would care about always trips it.
VOLUME_DP = 3          # cm3, so 0.001 cm3 = 1 mm3
BBOX_DP = 2            # mm, so 0.01 mm

BASELINE_NAME = "regression.json"


@dataclass
class Signature:
    volume_cm3: float
    bbox_mm: list[float]
    face_count: int

    def digest(self) -> str:
        payload = json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


@dataclass
class RegressionResult:
    status: str                       # "new" | "match" | "changed"
    signature: Signature
    baseline: Signature | None
    baseline_path: str
    differences: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status in ("new", "match")


def signature_of(report: MeshReport) -> Signature:
    """Coarsen a mesh report down to the fields worth comparing."""
    return Signature(
        volume_cm3=round(report.volume_cm3, VOLUME_DP),
        bbox_mm=[round(v, BBOX_DP) for v in report.bbox_mm],
        face_count=report.face_count,
    )


def baseline_path_for(stl_path: str | Path, part_dir: str | Path | None = None) -> Path:
    """
    Where the baseline lives: parts/<name>/regression.json.

    If the STL already sits inside a part bundle (parts/<name>/out/x.stl) the
    baseline goes beside the spec, not beside the STL.
    """
    if part_dir is not None:
        return Path(part_dir) / BASELINE_NAME

    p = Path(stl_path).resolve()
    if p.parent.name == "out":
        return p.parent.parent / BASELINE_NAME
    return p.parent / BASELINE_NAME


def load_baseline(path: str | Path) -> Signature | None:
    p = Path(path)
    if not p.is_file():
        return None
    data = json.loads(p.read_text())
    return Signature(
        volume_cm3=float(data["volume_cm3"]),
        bbox_mm=[float(v) for v in data["bbox_mm"]],
        face_count=int(data["face_count"]),
    )


def save_baseline(path: str | Path, sig: Signature) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(asdict(sig))
    payload["digest"] = sig.digest()
    p.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return p


def check_regression(
    report: MeshReport,
    baseline_path: str | Path,
    update: bool = False,
) -> RegressionResult:
    """
    Compare against the stored baseline. With update=True the current geometry
    becomes the new baseline - that is how a change gets accepted deliberately.
    """
    sig = signature_of(report)
    path = Path(baseline_path)
    baseline = load_baseline(path)

    if baseline is None:
        save_baseline(path, sig)
        return RegressionResult("new", sig, None, str(path),
                                ["no baseline existed, wrote one"])

    diffs: list[str] = []
    if sig.volume_cm3 != baseline.volume_cm3:
        diffs.append("volume %.3f -> %.3f cm3 (%+.3f)"
                     % (baseline.volume_cm3, sig.volume_cm3,
                        sig.volume_cm3 - baseline.volume_cm3))
    for i, name in enumerate("XYZ"):
        if sig.bbox_mm[i] != baseline.bbox_mm[i]:
            diffs.append("bbox %s %.2f -> %.2f mm (%+.2f)"
                         % (name, baseline.bbox_mm[i], sig.bbox_mm[i],
                            sig.bbox_mm[i] - baseline.bbox_mm[i]))
    if sig.face_count != baseline.face_count:
        diffs.append("face count %d -> %d (%+d)"
                     % (baseline.face_count, sig.face_count,
                        sig.face_count - baseline.face_count))

    if not diffs:
        return RegressionResult("match", sig, baseline, str(path))

    if update:
        save_baseline(path, sig)
        return RegressionResult("new", sig, baseline, str(path),
                                ["baseline updated deliberately"] + diffs)

    return RegressionResult("changed", sig, baseline, str(path), diffs)
