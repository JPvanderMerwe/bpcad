"""
The command line's parser. Design handoff, brief 6.4.

    parse("wall 3")        -> Command(kind="set", parameter="wall_mm", value=3.0)
    parse("hole m4 x4")    -> Command(kind="holes", standard="M4", count=4)
    parse("clearance ?")   -> Command(kind="ask", topic="clearance")
    parse("a pipe clamp")  -> Command(kind="prompt", text="a pipe clamp")

WHY THIS IS IN PYTHON AND NOT IN THE TWO CLIENTS
------------------------------------------------
The handoff is explicit that the command line must genuinely parse and must
use the same parser as the composer. Written in JavaScript it would have to be
written again in Dart, and then `wall 3` would mean one thing in the browser
and another on the phone - which is the same class of bug as a colour that
differs between clients, except that this one changes geometry.

So it lives here, both clients POST to it, and the vocabulary has exactly one
definition.

WHAT IT REFUSES TO DO
---------------------
It does not guess. `wall` with no number is not a wall of some default
thickness, it is an incomplete command and it says so - because the whole
point of the command line is that a maker types an exact number rather than
hunting for it with a thumb, and a command that silently invents one is worse
than a command that fails.

It also does not resolve a standard into a diameter. "M4 clearance hole" has a
real answer in the standards table (brief 4.5) and this module does not hold
it; it records that M4 was asked for and leaves the number to the layer that
owns it. A second table of fastener sizes is a second table to be wrong.

THE ECHO IS PART OF THE CONTRACT
--------------------------------
Brief 6.4: the echo uses the same words as the panel controls, both
directions. So every Command carries the sentence to print, written here
beside the parse rather than assembled in each client - two clients writing
their own echoes is how the phone ends up saying "wall thickness updated" and
the web saying "wall → 3.0 mm".
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# THE VOCABULARY, and it is deliberately small.
#
# Every word here is one a panel control already uses, because a command line
# whose words do not appear in the interface is a second interface. `help`
# prints this list, so it is also the documentation.
VOCABULARY = (
    "wall N",
    "bore N",
    "hole mN xN",
    "fillet N",
    "clearance ?",
    "motion",
    "help",
)

# Which parameter each word sets. The names on the right are the spec's own
# field names, so an echo can be checked against the part that comes back.
PARAMETERS = {
    "wall": "wall_mm",
    "bore": "bore_mm",
    "fillet": "fillet_mm",
    "corner": "corner_r_mm",
    "height": "height_mm",
    "width": "width_mm",
    "depth": "depth_mm",
    "clearance": "clearance_mm",
}

# What a bare number after each word means, for the echo's unit. Everything
# this vocabulary sets is a length in millimetres except the counts.
MILLIMETRES = set(PARAMETERS.values())


@dataclass(frozen=True)
class Command:
    """
    One parsed line.

    `kind` is what to do; `echo` is what to print. `refine` is the sentence to
    hand to the refine flow when the command changes geometry - the flow takes
    prose, and building that sentence here rather than in each client is what
    keeps the two clients asking for the same change.
    """

    kind: str
    echo: str
    text: str = ""
    parameter: str | None = None
    value: float | None = None
    unit: str = ""
    standard: str | None = None
    count: int | None = None
    topic: str | None = None
    refine: str | None = None
    problem: str | None = None
    options: tuple[str, ...] = field(default_factory=tuple)

    def to_json(self) -> dict[str, Any]:
        out = {
            "kind": self.kind,
            "echo": self.echo,
        }
        for name in ("text", "parameter", "unit", "standard", "topic",
                     "refine", "problem"):
            value = getattr(self, name)
            if value:
                out[name] = value
        if self.value is not None:
            out["value"] = self.value
        if self.count is not None:
            out["count"] = self.count
        if self.options:
            out["options"] = list(self.options)
        return out


def _number(raw: str) -> float | None:
    """A length, or None. Accepts 3, 3.0, .5 and a comma decimal."""
    try:
        return float(raw.replace(",", "."))
    except (TypeError, ValueError):
        return None


def _tidy(value: float) -> str:
    """
    3.0 -> "3.0", 0.28 -> "0.28", 4 -> "4.0".

    One decimal place minimum, because every number this product prints has a
    unit and a precision, and "wall 3 mm" reads as an integer measurement when
    it is a millimetre figure like every other.
    """
    text = ("%.2f" % value).rstrip("0")
    return text + "0" if text.endswith(".") else text


# ---------------------------------------------------------------------------
# the rules, in the order they are tried
# ---------------------------------------------------------------------------

# "hole m4 x4", "hole M4 x 4", "holes m3", "hole m4 ×4"
_HOLES = re.compile(
    r"^holes?\s+m\s*(?P<size>\d{1,2}(?:\.\d)?)"
    r"(?:\s*[x×]\s*(?P<count>\d{1,3}))?$",
    re.I,
)

# "wall 3", "wall 3.0", "wall = 3", "wall 3mm", "wall 3 mm", "wall 2,6"
#
# THE MINUS SIGN IS MATCHED ON PURPOSE, even though a negative length is
# always rejected. Left out, "wall -2" matched nothing and fell through to
# being read as a new prompt - so a typo silently started a two-minute
# generation instead of saying the number was wrong.
#
# The comma decimal is matched for the same reason: half the world writes
# 2,6 and it was falling through to a prompt too.
_SET = re.compile(
    r"^(?P<word>[a-z_]+)\s*=?\s*(?P<value>-?\d*[.,]?\d+)\s*(?:mm)?$",
    re.I,
)

# "clearance ?" and "clearance?"
_ASK = re.compile(r"^(?P<word>[a-z_]+)\s*\?$", re.I)

# A word on its own: "motion", "help", or an incomplete "wall".
_BARE = re.compile(r"^(?P<word>[a-z_]+)$", re.I)


def parse(line: str) -> Command:
    """
    One line in, one Command out. Never raises: an unparseable line is a
    prompt, which is the design's own rule - anything the vocabulary does not
    recognise is read as a new part.
    """
    text = (line or "").strip()
    if not text:
        return Command(kind="empty", echo="")

    # A leading ">" is the prompt character the interface draws. Somebody
    # copying a line out of the scrollback and back in should not have it
    # read as part of the command.
    text = text.lstrip("> ").strip()
    if not text:
        return Command(kind="empty", echo="")

    if match := _HOLES.match(text):
        return _holes(match)

    if match := _ASK.match(text):
        return _ask(match, text)

    if match := _BARE.match(text):
        bare = _bare(match, text)
        if bare is not None:
            return bare

    if match := _SET.match(text):
        setter = _set(match, text)
        if setter is not None:
            return setter

    # ANYTHING ELSE IS A NEW PART. Not an error - the design says a command
    # line that only accepts commands is a worse command line, because the
    # thing a maker most wants to type is a description.
    return Command(
        kind="prompt",
        text=text,
        echo="read as a new prompt - generating a fresh version",
    )


def _holes(match: re.Match) -> Command:
    size = match.group("size")
    count = int(match.group("count") or 1)
    standard = "M%s" % size.rstrip("0").rstrip(".") if "." in size else "M%s" % size

    # THE DIAMETER IS NOT COMPUTED HERE. "M4 clearance hole" has a real answer
    # in the standards table and this module does not hold it - a second table
    # of fastener sizes is a second table to be wrong. The echo says what was
    # asked for and the layer that owns the table fills in the number.
    plural = "holes" if count != 1 else "hole"
    return Command(
        kind="holes",
        standard=standard,
        count=count,
        echo="added %d × %s clearance %s" % (count, standard, plural),
        refine="add %d %s clearance %s" % (count, standard, plural),
    )


def _ask(match: re.Match, text: str) -> Command:
    word = match.group("word").lower()
    if word in PARAMETERS or word == "clearance":
        return Command(
            kind="ask",
            topic=word,
            echo="",           # the answer comes from the profile, not from here
        )
    return Command(
        kind="unknown",
        text=text,
        problem="nothing here answers %r" % word,
        echo="%s ? - not something this knows about" % word,
        options=VOCABULARY,
    )


def _bare(match: re.Match, text: str) -> Command | None:
    word = match.group("word").lower()

    if word == "help":
        return Command(
            kind="help",
            echo=" · ".join(VOCABULARY),
            options=VOCABULARY,
        )

    if word == "motion":
        return Command(
            kind="motion",
            echo="sweeping the joint through its declared range",
        )

    if word in PARAMETERS:
        # INCOMPLETE, AND IT SAYS SO RATHER THAN CHOOSING A NUMBER. The whole
        # point of the command line is an exact value typed rather than hunted
        # for, and a command that quietly invents one is worse than one that
        # fails.
        return Command(
            kind="incomplete",
            text=text,
            parameter=PARAMETERS[word],
            problem="%s needs a number" % word,
            echo="%s - needs a number, as in `%s 3`" % (word, word),
        )

    return None


def _set(match: re.Match, text: str) -> Command | None:
    word = match.group("word").lower()
    if word not in PARAMETERS:
        return None

    value = _number(match.group("value"))
    if value is None:
        return None

    # A NEGATIVE OR ZERO LENGTH IS NOT A SMALL LENGTH. Passed through it
    # becomes a boolean that reports valid and then fails three operations
    # later, which is the hardest kind of failure to trace back to its cause.
    if value <= 0:
        return Command(
            kind="rejected",
            text=text,
            parameter=PARAMETERS[word],
            value=value,
            problem="%s must be greater than 0" % word,
            echo="%s %s - not a length" % (word, _tidy(value)),
        )

    parameter = PARAMETERS[word]
    unit = "mm" if parameter in MILLIMETRES else ""
    shown = _tidy(value) + (" " + unit if unit else "")

    return Command(
        kind="set",
        parameter=parameter,
        value=value,
        unit=unit,
        # The echo uses the panel's words, both directions - brief 6.4. The
        # slider for this parameter is labelled with the same word.
        echo="%s → %s" % (_label(parameter), shown),
        refine="set %s to %s" % (_label(parameter), shown),
    )


def _label(parameter: str) -> str:
    """
    `wall_mm` -> "wall thickness". The words the panel uses.

    Spelled out rather than derived, because "wall_mm" -> "wall" loses the
    distinction between a wall's thickness and a wall, and the echo is
    supposed to read like the control it mirrors.
    """
    return {
        "wall_mm": "wall thickness",
        "bore_mm": "bore",
        "fillet_mm": "fillet radius",
        "corner_r_mm": "corner radius",
        "height_mm": "height",
        "width_mm": "width",
        "depth_mm": "depth",
        "clearance_mm": "joint clearance",
    }.get(parameter, parameter.removesuffix("_mm").replace("_", " "))
