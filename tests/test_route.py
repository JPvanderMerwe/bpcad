"""
Which road a request takes.

The case that produced this module is in test_a_drilled_plate_does_not_go_to_a
_template, and it is worth stating plainly because no other test in this suite
catches it: the pipeline was asked for "a flat plate 80 by 40 by 6 mm with two
5 mm holes 60 mm apart" and returned an 80 x 40 x 30 mm box with no holes,
watertight, one body, every check green, verdict PASS. Nothing downstream can
catch that, because nothing downstream knows what the request said. The only
place it can be caught is before the template is chosen.
"""

from __future__ import annotations

from bpcad.agent.route import route
from bpcad.spec import registry


# Requests the templates genuinely make. Each names a thing that is in some
# template's own `makes` list.
TEMPLATE_ROAD = [
    "a birdhouse with a 32 mm entrance",
    "an enclosure 100 by 60 by 30 mm with 2.5 mm walls",
    "a round bowl 180 mm across",
    "a pen pot 80 mm tall",
    "a keyring tag with my name on it",
    "a louvre vent for a cupboard door",
    "a shelf bracket for a 200 mm shelf, 6 mm thick",
]

# Requests no template makes. Every one of these has a hand-written level-2
# spec in eval/corpus.yaml, so primitives demonstrably build them.
PRIMITIVE_ROAD = [
    "a flat plate 80 by 40 by 6 mm with two 5 mm holes 60 mm apart",
    "a mounting plate 100 by 60 by 8 mm with four 4 mm holes 80 mm apart along the length",
    "a clamp to hold an 8 mm rod to a wall",
    "a wall hook 80 mm tall screwed through two 5 mm holes",
    "a phone stand at 60 degrees",
    "a funnel with a 20 mm neck",
    "a spacer ring 10 mm bore, 3 mm thick",
    "a knob for a 6 mm shaft",
]


def test_requests_a_template_makes_take_the_template_road():
    for request in TEMPLATE_ROAD:
        assert route(request).template_road, request


def test_requests_no_template_makes_go_to_primitives():
    for request in PRIMITIVE_ROAD:
        assert not route(request).template_road, request


def test_a_drilled_plate_does_not_go_to_a_template():
    """
    The regression this module exists for.

    `vessel` claims the bare word "plate", meaning a round one, and that claim
    alone used to be enough to put a rectangular drilled plate on the template
    road. A qualified round plate still belongs to the vessel.
    """
    assert not route("a flat plate 80 by 40 by 6 mm with two 5 mm holes").template_road
    assert route("a round plate 200 mm across with a raised rim").template_road


def test_feature_words_do_not_win_on_their_own():
    """
    "mount", "support" and "tag" are features as often as they are shapes.
    A plate with mounting holes is not a wall mount.
    """
    assert not route("a plate 60 mm square with mounting holes").template_road
    assert not route("a block with a support boss").template_road
    # Qualified, they are real parts and keep their template.
    assert route("a wall mount for a router").template_road
    assert route("a luggage tag 70 mm long").template_road


def test_matching_is_whole_words():
    """
    Substring matching sent "a spot welder jig" to the vessel, because "pot"
    is in "spot". It also read "cupboard vent" as a cup.
    """
    assert not route("a spot facing jig for a 12 mm boss").template_road
    assert route("a cupboard vent 90 mm wide").template_road


def test_plurals_still_match():
    assert route("two brackets for a 200 mm shelf").template_road


def test_an_empty_request_goes_to_primitives():
    """Not an error here. The model layer says what is wrong with an empty ask."""
    assert not route("").template_road
    assert not route("   ").template_road


def test_the_reason_names_what_was_recognised():
    """
    The run log has to say WHY a road was taken, or a wrong routing decision
    is invisible in the history.
    """
    plate = route("a flat plate 80 by 40 by 6 mm with two 5 mm holes")
    assert "no template claims anything" in plate.why

    bowl = route("a round bowl 180 mm across")
    assert "bowl" in bowl.why
    assert "vessel" in bowl.why


def test_the_most_specific_phrase_is_reported_first():
    """
    "round bowl" is a better reason than "bowl". The log should say the
    specific thing that was recognised, not the vaguest.
    """
    matched = route("a round bowl 180 mm across").matched
    assert matched[0][0] == "round bowl"


def test_every_template_claims_something_the_router_can_see():
    """
    A template whose whole `makes` list is filtered out by NEVER_ALONE can
    never be reached from a prompt, and that would be invisible without this.
    """
    for name in registry.names():
        template = registry.get(name)
        reachable = [
            phrase for phrase in (getattr(template, "makes", ()) or ())
            if route("a %s" % phrase).template_road
        ]
        assert reachable, "%s claims nothing the router can match" % name


# ---------------------------------------------------------------------------
# The decision has to be made where BOTH front ends see it.
# ---------------------------------------------------------------------------

def _profile():
    """
    The null backend, so nothing in this file opens a socket.

    It also makes the second assertion below meaningful: the null backend
    refuses every call, so "ask() did not decline on the route" is proved by
    the run getting far enough to be refused by the backend instead.
    """
    from bpcad.models.selector import Profile

    return Profile(
        name="test", backend_kind="null", host="http://127.0.0.1:11434",
        model_primary="big", model_small="small", num_ctx=2048,
        timeout_s=30, max_attempts_per_level=2,
    )


def test_ask_declines_a_plate_without_calling_a_model():
    """
    The first wiring of this put the decision in api.generate(), so the web app
    routed correctly and `bpcad gen` did not - it went on handing drilled
    plates to the enclosure template. The decision belongs in ask(), which both
    drivers call, and a decline must cost no model call at all.
    """
    from bpcad.agent.loop import ask

    def explode(*_args, **_kwargs):
        raise AssertionError("a model was called for a request no template makes")

    result = ask(
        request="a flat plate 80 by 40 by 6 mm with two 5 mm holes 60 mm apart",
        profile=_profile(), material="petg", nozzle_mm=0.4, layer_mm=0.2,
        verify_fn=explode,
    )

    assert result.no_template_fits
    assert not result.ok
    assert result.ladder.attempts == []
    # never_reached_a_model gates escalation in both drivers. An empty attempt
    # list must read as False or a decline would stop the run dead instead of
    # sending it to primitives.
    assert result.ladder.never_reached_a_model is False


def test_ask_still_asks_when_a_template_claims_the_request():
    """A decline must not swallow the requests templates genuinely serve."""
    from bpcad.agent.loop import ask

    result = ask(
        request="a birdhouse with a 32 mm entrance",
        profile=_profile(), material="petg", nozzle_mm=0.4, layer_mm=0.2,
    )
    assert not result.no_template_fits
    # It reached the backend and the null backend turned it down. That is the
    # proof it was not short-circuited on the route.
    assert result.ladder.attempts
