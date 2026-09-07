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
# "120 x 140 x 100" AND "120 by 140 by 100". The word was missing and it is at
# least as common as the symbol in anything a person types: "a flat plate 80 by
# 40 by 6 mm" yielded NOTHING from this module, so check_intent - the guard
# that exists to catch a 573 cm3 slab being handed over as a birdhouse - had
# nothing to check and stayed quiet for every request written that way.
_TRIPLE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:[x×]|by)\s*(\d+(?:\.\d+)?)\s*(?:[x×]|by)\s*"
    r"(\d+(?:\.\d+)?)",
    re.IGNORECASE,
)

# Words that mean a number is NOT an outside dimension, so it should not be
# matched against the envelope. A 32 mm entrance hole is inside a 120 mm wall.
_INNER = (
    "hole", "bore", "entrance", "opening", "aperture", "slot", "gap",
    "clearance", "thick", "wall", "radius", "diameter", "pitch", "nozzle",
    "layer", "tolerance",
    # THINGS THE PART RECEIVES. A number that names something going INTO or
    # THROUGH the part is a bore, never the envelope - and every one of these
    # was read as an envelope dimension the moment the extractor started
    # working. "a clamp that holds an 8 mm rod, 40 mm wide" wanted its 8 mm
    # found somewhere in a 40 x 34 x 12 part; "holds two 5 mm cables" and "a
    # spout that fits a 20 mm neck" did the same. Three corpus entries whose
    # own specs are correct, reported as the wrong size.
    "rod", "shaft", "pin", "axle", "dowel", "cable", "wire", "cord",
    "neck", "spigot", "tube", "pipe", "bar", "screw", "bolt", "rail",
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


# NOUNS AND ADJECTIVES THAT MEAN THE PART IS ROUND.
#
# Asked for "a round knob 40 mm across with a 6 mm hole for a shaft", the model
# emitted `rounded_prism 40 x 40 x 20, corner_r 5` - a square knob with its
# corners taken off - and every check passed. It is the pot/planter mistake
# from enclosure.py all over again, one level down: at level 2 there is no
# template routing to catch a shape word, so nothing did.
#
# Words naming something the part RECEIVES are deliberately absent: a clamp for
# an 8 mm ROD is not itself round, and _INNER already carries that list. "ring"
# is here and does not match "keyring", because the test is on word boundaries.
ROUND_WORDS = (
    "round", "circular", "cylindrical",
    "bowl", "pot", "ring", "knob", "disc", "disk", "cylinder", "funnel",
    "cup", "wheel", "pulley", "washer", "spool", "dish", "vase", "jar",
    "canister", "basin", "plate round", "turntable",
)

# A circle fills pi/4 = 0.785 of its bounding box and a square fills 1.000.
# MEASURED over the whole fit-rate corpus: every round entry - bowl, plant pot,
# pen pot, spacer ring, knob, funnel - comes out at exactly 0.785, and the
# roundest thing that is NOT round is the birdhouse at 0.930. This sits between
# them with room on both sides, and no corpus entry is flagged by it.
ROUND_FILL_LIMIT = 0.86


def _hull_area_xy(points) -> float:
    """
    Area of the convex hull of a point cloud projected onto XY.

    Andrew's monotone chain and the shoelace formula, rather than scipy: this
    runs inside a verify pass on every generated part and the hull of a few
    thousand points does not need a QHull call.
    """
    pts = sorted({(round(float(x), 4), round(float(y), 4)) for x, y in points})
    if len(pts) < 3:
        return 0.0

    def half(seq):
        out: list[tuple[float, float]] = []
        for p in seq:
            while len(out) >= 2:
                (x1, y1), (x2, y2) = out[-2], out[-1]
                if (x2 - x1) * (p[1] - y1) - (y2 - y1) * (p[0] - x1) > 0:
                    break
                out.pop()
            out.append(p)
        return out

    hull = half(pts)[:-1] + half(reversed(pts))[:-1]
    area = 0.0
    for i, (x1, y1) in enumerate(hull):
        x2, y2 = hull[(i + 1) % len(hull)]
        area += x1 * y2 - x2 * y1
    return abs(area) / 2.0


def footprint_fill(vertices) -> float:
    """
    How much of its own bounding box the part's plan view fills.

    0.785 is a circle, 1.000 a rectangle. Returns 0.0 when it cannot be
    measured, which reads as "no evidence" rather than "not round".

    FEED IT THE MESH, NOT THE CAD SOLID. A cylinder's B-rep carries two
    vertices and a couple of circular edges, so the hull of its vertices is
    nothing at all - the first version of this scored a perfectly round knob
    0.000 and let it through. The exported mesh is the tessellated truth and
    the verify pass already has it in hand.
    """
    import numpy as np

    v = np.asarray(vertices, dtype=float)
    if v.ndim != 2 or len(v) < 3:
        return 0.0
    xy = v[:, :2]
    box = (xy[:, 0].max() - xy[:, 0].min()) * (xy[:, 1].max() - xy[:, 1].min())
    if box <= 1e-9:
        return 0.0
    return _hull_area_xy(xy) / box


def round_words_in(request: str) -> list[str]:
    """Which roundness words the request used, if any."""
    text = _normalise_words(request)
    return [w for w in ROUND_WORDS if re.search(r"(?<![a-z])%s(?![a-z])" % w, text)]


def _normalise_words(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower())


# Words that mean the part has to hold something INSIDE it.
#
# "holder" and "case" are absent: a phone holder holds a phone against itself
# and a case can be a plain plate. These are the words that promise a cavity.
HOLLOW_WORDS = (
    "pot", "planter", "bowl", "cup", "mug", "vase", "jar", "canister",
    "tray", "box", "enclosure", "bin", "basket", "container", "tub", "caddy",
)

# Fraction of its own convex hull the material fills. MEASURED over the
# corpus: every container - enclosure 0.200, tray 0.192, pen pot 0.148, plant
# pot 0.135, bowl 0.081 - comes in at or under 0.20, and the nearest thing
# that is not a container is the funnel at 0.244. A solid slab is 0.99.
#
# The limit is set at 0.50 rather than halfway, because the failure being
# caught is not a thin-walled pot that is slightly too thick: it is a SOLID
# BLOCK handed over as a pot. Leaving that much room means the check can only
# fire on something that is plainly not hollow at all.
HOLLOW_FILL_LIMIT = 0.50


def check_hollowness(request: str, mesh) -> str | None:
    """
    A part the request called a container has to have something inside it.

    Asked for "a plant pot 100 mm across with drainage holes in the bottom",
    the model emitted `rounded_prism 100 x 100 x 20` and one `disc` cut: a
    solid square slab with a hole in it. It built, it was watertight, it was
    one sound body, and it is a coaster.

    Judged only when the request names a container, and only against a part
    that is plainly solid. `hollow` is the op it is missing.
    """
    text = _normalise_words(request)
    words = [w for w in HOLLOW_WORDS
             if re.search(r"(?<![a-z])%s(?![a-z])" % w, text)]
    if not words:
        return None
    try:
        hull = float(mesh.convex_hull.volume)
        if hull <= 0.0:
            return None
        fill = float(mesh.volume) / hull
    except Exception:
        return None
    if fill <= HOLLOW_FILL_LIMIT:
        return None
    return (
        "the request asked for a %s, which holds something, and this part is "
        "solid: its material fills %.0f%% of its own outline, where a real "
        "one fills under 20%%. Add a `hollow` op after the body - "
        "{\"op\": \"hollow\", \"wall_mm\": 2.4, \"opening\": \"top_face\", "
        "\"floor_mm\": 3} - or turn a profile with `profile_extrude`. A block "
        "with a hole in it is a coaster."
        % (words[0], 100.0 * fill)
    )


def check_hole_counts(request: str, solid) -> str | None:
    """
    As many holes as the request asked for. Returns a problem or None.

    ONE-SIDED, DELIBERATELY. Only "fewer than asked" is a definite miss: a
    part may carry holes the request never mentioned - a drain, a vent, a
    fixing - and complaining about those would be noise.

    When the request gave a diameter the check is exact, against the same
    0.05 mm tolerance the fit-rate assertions use. When it did not - "two
    countersunk screw holes" - it asks whether ANY single diameter accounts
    for that many bores. A vertical fillet is a cylindrical face too, so that
    weaker form can be satisfied by something that is not a hole; it fails
    toward saying nothing, which is the right direction for a check that
    rejects a model's work.
    """
    wanted = stated_holes(request)
    if not wanted:
        return None

    from bpcad.verify.assertions import (
        HOLE_TOLERANCE_MM, _holes_of_diameter, cylindrical_faces,
    )

    try:
        cylinders = list(cylindrical_faces(solid))
    except Exception:
        return None

    # A BORE WRAPS THE CIRCLE; A ROUNDED CORNER COVERS A QUARTER OF IT. Both
    # are cylindrical faces of some radius, and without this filter a plate
    # with corner_r_mm 2 reads as having four 4 mm holes in its corners - which
    # is how a part with no holes at all satisfied a request for two. 179
    # rather than 360 because a boolean often leaves a bore as two half-faces,
    # and _holes_of_diameter then merges them by axis.
    BORE_ARC_DEG = 179.0

    for count, dia in wanted:
        if dia is not None:
            found = len(_holes_of_diameter(solid, dia, HOLE_TOLERANCE_MM,
                                           min_arc_deg=BORE_ARC_DEG))
            if found < count:
                return (
                    "the request asked for %d holes of %g mm and the part has "
                    "%s. A hole is a `disc` in cut mode that starts outside "
                    "one face and ends outside the other; for more than one, "
                    "wrap it in `pattern_linear` or repeat it."
                    % (count, dia, "%d" % found if found else "none")
                )
            continue

        # No diameter given: is there any one diameter with that many bores?
        best = 0
        bores = [c for c in cylinders if c.get("arc_deg", 360.0) >= BORE_ARC_DEG]
        for candidate in {round(c["diameter_mm"], 2) for c in bores}:
            best = max(best, len(_holes_of_diameter(solid, candidate,
                                                    HOLE_TOLERANCE_MM,
                                                    min_arc_deg=BORE_ARC_DEG)))
        if best < count:
            return (
                "the request asked for %d holes and the part has no %d bores "
                "of any one size - the most of a single diameter is %d. A "
                "countersunk hole is TWO ops: a `disc` in cut mode all the way "
                "through, and a `cone` in cut mode at the face it is driven "
                "from, widening outward. A cone on its own is a dimple."
                % (count, count, best)
            )
    return None


def check_roundness(request: str, vertices) -> str | None:
    """
    A part the request called round has to BE round. Returns a problem or None.

    Cheap and one-sided: it only speaks when the request named a round thing
    AND the plan view is squarer than any round part measured. A part with no
    roundness word in its request is never judged.
    """
    words = round_words_in(request)
    if not words:
        return None
    fill = footprint_fill(vertices)
    if fill <= 0.0 or fill <= ROUND_FILL_LIMIT:
        return None
    return (
        "the request describes a round part (%s) and this one is not: its plan "
        "view fills %.0f%% of its bounding box, where a round part fills 79%% "
        "and a square one 100%%. Build the body from `disc`, `cone` or "
        "`profile_extrude`, not from `rounded_prism` - taking the corners off "
        "a square with corner_r_mm does not make it round."
        % (", ".join("'%s'" % w for w in words[:3]), 100.0 * fill)
    )


# "two", "four", "a pair of". Written-out numbers are how people count holes;
# digits are how they give dimensions.
_COUNT_WORDS = {
    "one": 1, "a": 1, "an": 1, "two": 2, "a pair of": 2, "pair of": 2,
    "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "twelve": 12,
}

# What counts as a hole for this purpose: a round bore through or into the
# part. "slot" and "pocket" are deliberately absent - they are not round and
# the hole finder looks for cylindrical faces.
_HOLE_NOUNS = ("hole", "holes", "bore", "bores", "perforation", "perforations")

_STATED_HOLES = re.compile(
    r"(?P<count>\d+|%s)\s+"
    r"(?:[a-z]+\s+){0,2}?"
    r"(?:(?P<dia>\d+(?:\.\d+)?)\s*(?:mm\b|millimet(?:re|er)s?\b)\s*)?"
    r"(?:[a-z]+\s+){0,2}?"
    r"(?P<noun>%s)\b"
    % ("|".join(sorted(_COUNT_WORDS, key=len, reverse=True)),
       "|".join(_HOLE_NOUNS)),
    re.IGNORECASE,
)


def stated_holes(request: str) -> list[tuple[int, float | None]]:
    """
    Hole counts the request asked for, as (count, diameter or None).

    WHY THIS EXISTS. Asked for "a rectangular plate 80 by 40 by 6 mm with two
    countersunk screw holes", the model emitted ONE cone, 3 mm deep, pointed,
    that went nowhere near through - a conical dimple - and the part passed
    every check. Asked for two 5 mm holes on an earlier run it delivered
    none, then one. Nothing in this program compared the number of holes
    asked for against the number delivered, so a part with the wrong number
    of holes was indistinguishable from a correct one.

    A count with no diameter is still worth having: "two mounting holes" says
    two, and the finder can be asked for whatever diameter it can see.
    """
    text = _normalise_words(request)
    out: list[tuple[int, float | None]] = []
    for match in _STATED_HOLES.finditer(text):
        raw = match.group("count").lower()
        count = _COUNT_WORDS.get(raw)
        if count is None:
            try:
                count = int(raw)
            except ValueError:
                continue
        if count < 1 or count > 100:
            continue
        dia = match.group("dia")
        out.append((count, float(dia) if dia else None))
    return out


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
        # THE WINDOW STOPS AT THE NEXT NUMBER, both ways.
        #
        # It used to be a flat 26 characters either side, which reaches into
        # the number NEXT DOOR and takes its qualifier as its own: in "a hinge
        # 40 mm wide and 5 mm thick" the word "thick" belongs to the 5, and it
        # threw away the 40 as well. One inner-feature word poisoned every
        # dimension near it.
        #
        # labelled_dimensions() has cut its window at the next digit from the
        # start, for this exact reason. This one never got the same treatment.
        before = text[max(0, match.start() - 26): match.start()]
        # Backward, stop at the previous NUMBER and at the clause boundary,
        # whichever is closer. Cutting only at the digit is not enough: in
        # "holds an 8 mm rod, 40 mm wide" the word "rod" qualifies the 8 and
        # sits between the two, so it reached back and disqualified the 40.
        # A comma, a semicolon, an "and" or a "with" ends the previous
        # number's business.
        starts = [m.end() for m in re.finditer(r"\d", before)]
        starts += [m.end() for m in re.finditer(r"[,;]|\band\b|\bwith\b", before)]
        if starts:
            before = before[max(starts):]

        after = text[match.end(): match.end() + 26]
        cut_fwd = re.search(r"\d", after)
        if cut_fwd:
            after = after[: cut_fwd.start()]

        if any(word in before + after for word in _INNER):
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
            # "DEEP" MEANS TWO DIFFERENT THINGS AND BOTH ARE ORDINARY ENGLISH.
            # A shelf 70 mm deep is 70 front to back; a bowl 70 mm deep is 70
            # top to bottom. AXIS_WORDS has to pick one, it picks depth, and a
            # perfectly correct 180 x 180 x 70 bowl was reported as having its
            # dimensions on the wrong axes. So a depth-labelled figure is
            # allowed to land on the height axis too. Nothing else is
            # ambiguous: "wide" and "tall" mean what they say.
            allowed = (1, 2) if axis == 1 else (axis,)
            if any(abs(envelope_mm[a] - value) <= max(value * tolerance_fraction, 1.0)
                   for a in allowed):
                continue
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
