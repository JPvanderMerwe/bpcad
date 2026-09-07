"""
Which road a request takes: a template, or primitives.

WHY THIS IS DETERMINISTIC AND WHY IT EXISTS
-------------------------------------------
The ladder used to start at level 1 always, and escalate to level 2 only when
level 1 FAILED. A wrong template does not fail. Asked for "a flat plate 80 by
40 by 6 mm with two 5 mm holes 60 mm apart", the model chose the enclosure and
returned an 80 x 40 x 30 mm box with no holes at all. It was watertight, one
body, every feature check green, verdict PASS, and the report advised where to
glue the roof on. Level 2 was never reached, because nothing had gone wrong.

The escape hatch for this already existed - the model may answer
`none_of_these_fit` - and it is explained in both the system prompt and the
user prompt. It still did not fire, and that is not surprising: the model is
asked to name a template AND fill in forty parameters in one reply, from an
enum where five of six options are templates. A small model asked to classify
and extract in the same breath does the extraction.

So the road is chosen here instead, before any model call, by looking for the
words the templates themselves claim. No model, no network, and the same answer
every time.

THE ASYMMETRY THAT SETS THE BIAS
--------------------------------
The two mistakes this can make are not equal.

  Routed to primitives when a template would have done: costs a longer spec
  and a few more tokens. The DSL builds birdhouses, trays, hooks and phone
  stands already - `tests/test_dsl_coverage.py` builds all four from
  primitives - so the part still comes out right.

  Routed to a template that does not make the thing: produces a confident,
  fully-verified part that is not what was asked for. There is no check
  downstream that catches it, because nothing downstream knows what the
  request said.

The first is cheap and the second is the worst outcome this program has. So a
match has to be earned: the request must actually contain one of the phrases a
template claims. Anything else goes to primitives, which are general.

Level 1 exhaustion still escalates to level 2 exactly as before. This only
decides where to start.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from bpcad.spec import registry


@dataclass
class Route:
    """
    Where a request should start.

    `template_road` is False when no template claims any of the words in the
    request, and the request should go straight to level 2. It does NOT name
    the template to use - the model still chooses, from the same catalogue as
    before. Naming it here would be a second, worse template chooser.
    """

    template_road: bool
    matched: list[tuple[str, str]] = field(default_factory=list)
    request: str = ""

    @property
    def why(self) -> str:
        """One line for the run log and the progress feed."""
        if not self.template_road:
            return (
                "no template claims anything in this request, so it is built "
                "from primitives"
            )
        shown = ", ".join("%s (%s)" % (phrase, name) for phrase, name in self.matched[:3])
        return "a template may fit: %s" % shown


# Words that appear in a request for reasons that have nothing to do with the
# shape of the part. "mount" is in the bracket's list and "wall mount" is a
# real bracket, but "mounting holes" is a feature almost any part can have -
# and matching it sent a drilled plate to the bracket template.
NEVER_ALONE = {"mount", "support", "tag", "plate"}


def _normalise(text: str) -> str:
    """Lowercase, punctuation to spaces, runs of space collapsed."""
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", text.lower())).strip()


def _contains(haystack: str, phrase: str) -> bool:
    """
    Whole-word phrase match, tolerating a trailing plural.

    Substring matching is not good enough: "pot" is a vessel and "spot" is
    not, and "cup" would match "cupboard vent", which is a louvre.
    """
    pattern = r"(?<![a-z0-9])%s(?:s|es)?(?![a-z0-9])" % re.escape(phrase)
    return re.search(pattern, haystack) is not None


def route(request: str) -> Route:
    """
    Decide the road for one request, with no model and no network.

    A template road needs a phrase from some template's `makes` list to appear
    in the request as whole words. Phrases in NEVER_ALONE do not count on their
    own, because they are feature words as often as they are shape words.
    """
    text = _normalise(request or "")
    if not text:
        return Route(template_road=False, request=request or "")

    matched: list[tuple[str, str]] = []
    for name in registry.names():
        template = registry.get(name)
        for phrase in getattr(template, "makes", ()) or ():
            norm = _normalise(phrase)
            if not norm or not _contains(text, norm):
                continue
            if norm in NEVER_ALONE:
                continue
            matched.append((phrase, name))

    # Longest phrase first: "round bowl" is a better reason than "bowl", and
    # the log should say the specific thing that was recognised.
    matched.sort(key=lambda m: (-len(m[0]), m[0]))
    return Route(template_road=bool(matched), matched=matched, request=request or "")
