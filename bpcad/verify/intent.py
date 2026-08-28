"""
Does the part resemble what was asked for?

WHY THIS IS SEPARATE FROM verify/
---------------------------------
Everything else in verify/ answers "can this be made?" - watertight, feature
sizes against the nozzle, overhangs. That is a complete answer to a different
question, and a part can pass all of it while being the wrong object entirely.

Asked for a birdhouse 120 x 140 x 100 mm with a 32 mm entrance hole, and given
only a keyring and a vent template, the model produced a 573 cm3 solid slab with
a keyring handle on it. Watertight, one body, no overhangs, PASS. It was not a
birdhouse, and nothing in the pipeline was looking.

WHAT THIS CAN AND CANNOT DO
---------------------------
It cannot tell a birdhouse from a nesting box. Judging whether a shape is the
right shape needs something this system deliberately does not have.

What it CAN do is compare the numbers the request stated against the numbers the
part came out with, and notice that a request for 100 mm deep produced 40 mm.
That is cheap, exact, and catches the case above. It is a smoke alarm, not an
inspector: it finds a part that cannot possibly be right, and stays quiet about
one that merely might not be.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# "120 mm", "120mm", "120 millimetres", and the bare "120 x 140 x 100" form.
_DIM = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:mm\b|millimet(?:re|er)s?\b)", re.IGNORECASE
)
_TRIPLE = re.compile(
    r"(\d+(?:\.\d+)?)\s*[x×]\s*(\d+(?:\.\d+)?)\s*[x×]\s*(\d+(?:\.\d+)?)"
)

# Words that mean a number is NOT an outside dimension, so it should not be
# matched against the envelope. A 32 mm entrance hole is inside a 120 mm wall.
_INNER = (
    "hole", "bore", "entrance", "opening", "aperture", "slot", "gap",
    "clearance", "thick", "wall", "radius", "diameter", "pitch", "nozzle",
    "layer", "tolerance",
)

# How far a stated dimension may miss the envelope before it is worth saying.
# Generous on purpose: a flange, a chamfer or a lip legitimately adds a few mm,
# and a check that fires on those gets switched off.
TOLERANCE_FRACTION = 0.18


# Words that name which way a dimension runs. A request that says "120 mm wide,
# 140 mm tall" has told you the axes, and ignoring that lets a part come back
# with the right three numbers on the wrong three axes - which is what happened:
# a birdhouse asked for 120 wide and 140 tall came back 140 wide and 100 tall,
# and passed, because every number appeared somewhere.
AXIS_WORDS = {
    "wide": 0, "width": 0, "across": 0, "broad": 0,
    "deep": 1, "depth": 1, "front to back": 1,
    "tall": 2, "height": 2, "high": 2, "long": 2,
}


@dataclass
class IntentReport:
    """Which stated dimensions the part accounts for, and which it does not."""

    stated_mm: list[float] = field(default_factory=list)
    envelope_mm: tuple[float, float, float] = (0.0, 0.0, 0.0)
    matched: list[tuple[float, float]] = field(default_factory=list)
    missing: list[float] = field(default_factory=list)
    misplaced: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems

    @property
    def checked(self) -> bool:
        """False when the request stated no outside dimensions to check."""
        return bool(self.stated_mm)


def stated_dimensions(request: str) -> list[float]:
    """
    Outside dimensions the request asked for, in mm.

    Numbers described as holes, bores, wall thicknesses and the like are left
    out: they are real dimensions, but they are not the envelope, and matching
    them against it would produce noise instead of signal.
    """
    text = request.lower()
    found: list[float] = []

    for match in _TRIPLE.finditer(text):
        found.extend(float(g) for g in match.groups())

    for match in _DIM.finditer(text):
        value = float(match.group(1))
        # Look at the words either side; "32 mm entrance hole" is an inner
        # feature and belongs to the part, not to its envelope.
        window = text[max(0, match.start() - 26): match.end() + 26]
        if any(word in window for word in _INNER):
            continue
        found.append(value)

    # Anything under 3 mm is a thickness or a tolerance, not an envelope.
    return sorted({v for v in found if v >= 3.0}, reverse=True)


def labelled_dimensions(request: str) -> dict[int, float]:
    """
    Dimensions the request tied to a named axis: {0: width, 1: depth, 2: height}.

    Only counts a label within a few words of the number, so "120 mm wide" is
    read and "120 mm, and make the walls wide enough" is not.
    """
    text = request.lower()
    out: dict[int, float] = {}
    for match in _DIM.finditer(text):
        value = float(match.group(1))
        if value < 3.0:
            continue

        # Stop at the next number, so "140 mm tall, 100 mm deep" does not read
        # "deep" as the label for 140. Taking the first label BY POSITION rather
        # than by dictionary order matters for the same reason: iterating the
        # dict found "deep" before "tall" and put the height on the depth axis,
        # which is exactly the failure this function exists to catch.
        tail = text[match.end(): match.end() + 30]
        cut = re.search(r"\d", tail)
        window = tail[: cut.start()] if cut else tail

        if any(word in window for word in _INNER):
            continue

        best: tuple[int, int] | None = None
        for word, axis in AXIS_WORDS.items():
            at = window.find(word)
            if at >= 0 and (best is None or at < best[0]):
                best = (at, axis)
        if best is not None:
            out.setdefault(best[1], value)
    return out


def check_intent(
    request: str,
    envelope_mm: tuple[float, float, float],
    tolerance_fraction: float = TOLERANCE_FRACTION,
) -> IntentReport:
    """
    Compare the dimensions a request stated against the part that came out.

    Each stated dimension has to be accounted for by SOME axis of the envelope.
    Which axis is not checked - a request rarely says which way round it means,
    and guessing would invent failures.
    """
    stated = stated_dimensions(request)
    report = IntentReport(stated_mm=stated, envelope_mm=tuple(envelope_mm))
    if not stated:
        return report

    for value in stated:
        best = min(envelope_mm, key=lambda e: abs(e - value))
        if abs(best - value) <= max(value * tolerance_fraction, 1.0):
            report.matched.append((value, best))
        else:
            report.missing.append(value)

    # If the request named the axes, check they line up. Three right numbers on
    # three wrong axes is a different part, and it passes every other check.
    labelled = labelled_dimensions(request)
    if len(labelled) >= 2:
        for axis, value in labelled.items():
            got = envelope_mm[axis]
            if abs(got - value) > max(value * tolerance_fraction, 1.0):
                report.misplaced.append(
                    "%s should be %g mm and is %.1f mm"
                    % (("width", "depth", "height")[axis], value, got)
                )
        if report.misplaced and not report.missing:
            report.problems.append(
                "the dimensions are on the wrong axes: %s. The request said %s."
                % ("; ".join(report.misplaced),
                   ", ".join("%g mm %s" % (v, ("wide", "deep", "tall")[a])
                             for a, v in sorted(labelled.items())))
            )

    if report.missing:
        report.problems.append(
            "the request asked for %s mm, and the part is %s mm. Nothing in it "
            "is close to %s. Either a dimension was dropped, or this is not the "
            "part that was asked for."
            % (
                ", ".join("%g" % v for v in stated),
                " x ".join("%.1f" % e for e in envelope_mm),
                " or ".join("%g" % v for v in report.missing),
            )
        )
    return report


def summary(report: IntentReport) -> list[str]:
    """Lines for a report or a log."""
    if not report.checked:
        return ["the request stated no outside dimensions, so nothing to check"]
    out = [
        "asked for   %s mm" % ", ".join("%g" % v for v in report.stated_mm),
        "built       %.1f x %.1f x %.1f mm" % report.envelope_mm,
    ]
    for value, got in report.matched:
        out.append("  %-8g accounted for by %.1f mm" % (value, got))
    for value in report.missing:
        out.append("  %-8g NOT FOUND in the part" % value)
    for line in report.misplaced:
        out.append("  wrong axis: %s" % line)
    return out
