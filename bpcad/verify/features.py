"""
Named feature sizes against the nozzle.

The contract that makes this generic: every template returns a dict of named
feature sizes in mm. This module never needs to know what the part is. Give it
{"glass side bezel": 0.41, "logo stroke": 0.45} and it will tell you which ones
an FDM printer cannot resolve.
"""

from __future__ import annotations

from dataclasses import dataclass, field

PASS = "PASS"
MARGINAL = "MARGINAL"
TOO_FINE = "TOO FINE"

# A feature at or above the threshold but within this fraction of it is
# MARGINAL: it will print, but it is one tuning change away from not printing.
# Below the threshold it is TOO FINE - never merely marginal, because a feature
# thinner than the nozzle does not exist in the print.
MARGINAL_FRACTION = 0.10


@dataclass
class FeatureCheck:
    name: str
    value_mm: float
    threshold_mm: float
    status: str

    @property
    def ratio(self) -> float:
        return self.value_mm / self.threshold_mm if self.threshold_mm else float("inf")


@dataclass
class FeatureReport:
    nozzle_mm: float
    threshold_mm: float
    checks: list[FeatureCheck] = field(default_factory=list)

    @property
    def too_fine(self) -> list[FeatureCheck]:
        return [c for c in self.checks if c.status == TOO_FINE]

    @property
    def marginal(self) -> list[FeatureCheck]:
        return [c for c in self.checks if c.status == MARGINAL]

    @property
    def ok(self) -> bool:
        return not self.too_fine


def classify(value_mm: float, threshold_mm: float, marginal_fraction: float = MARGINAL_FRACTION) -> str:
    if value_mm < threshold_mm:
        return TOO_FINE
    if value_mm < threshold_mm * (1.0 + marginal_fraction):
        return MARGINAL
    return PASS


def check_features(
    features: dict[str, float],
    nozzle_mm: float,
    min_feature_multiple: float = 1.0,
    marginal_fraction: float = MARGINAL_FRACTION,
) -> FeatureReport:
    """
    Classify every named feature. Sorted smallest first, because the smallest
    is the one that decides whether the part is printable.
    """
    threshold = nozzle_mm * min_feature_multiple
    checks = [
        FeatureCheck(
            name=name,
            value_mm=float(value),
            threshold_mm=threshold,
            status=classify(float(value), threshold, marginal_fraction),
        )
        for name, value in features.items()
    ]
    checks.sort(key=lambda c: c.value_mm)
    return FeatureReport(nozzle_mm=nozzle_mm, threshold_mm=threshold, checks=checks)
