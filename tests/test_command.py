"""
The command line's parser. Design handoff, brief 6.4.

The handoff says the command line "must genuinely parse" and must share the
composer's parser rather than carry its own. So the thing worth testing is not
that `wall 3` returns something - it is the boundary: what the vocabulary
accepts, what it refuses to guess at, and what falls through to being read as
a new part.

The falling-through matters most. A command line that only accepts commands is
a worse command line, because the thing a maker most wants to type is a
description of a part - so an unrecognised line is a prompt, not an error, and
that has to stay true as the vocabulary grows.
"""

from __future__ import annotations

import pytest

from bpcad.agent.command import VOCABULARY, parse


# ---------------------------------------------------------------------------
# setting a value
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("line,value", [
    ("wall 3", 3.0),
    ("wall 3.0", 3.0),
    ("wall 3mm", 3.0),
    ("wall 3 mm", 3.0),
    ("wall = 3", 3.0),
    ("WALL 3", 3.0),
    ("wall .5", 0.5),
    ("wall 2,6", 2.6),          # a comma decimal, as half the world writes it
])
def test_a_wall_is_set_however_it_is_typed(line, value):
    command = parse(line)
    assert command.kind == "set"
    assert command.parameter == "wall_mm"
    assert command.value == value


def test_the_echo_uses_the_panels_own_words():
    """
    Brief 6.4: the echo uses the same words as the panel controls, both
    directions. A command line whose vocabulary does not appear in the
    interface is a second interface.
    """
    assert parse("wall 3").echo == "wall thickness → 3.0 mm"
    assert parse("fillet 2").echo == "fillet radius → 2.0 mm"
    assert parse("clearance 0.28").echo == "joint clearance → 0.28 mm"


def test_a_change_carries_the_sentence_that_applies_it():
    """
    The refine flow takes prose. Building that sentence here rather than in
    each client is what stops the phone and the browser asking for subtly
    different changes from the same command.
    """
    command = parse("wall 3")
    assert command.refine == "set wall thickness to 3.0 mm"


def test_every_length_carries_its_unit():
    """Tone rule from COPY.md: numbers always with their unit."""
    for line in ("wall 3", "bore 32", "fillet 2", "height 46"):
        assert parse(line).unit == "mm"
        assert "mm" in parse(line).echo


# ---------------------------------------------------------------------------
# what it refuses to guess
# ---------------------------------------------------------------------------

def test_a_word_with_no_number_is_incomplete_and_not_a_default():
    """
    THE RULE THIS PARSER EXISTS FOR. The command line's whole point is that a
    maker types an exact number rather than hunting for it with a thumb. A
    bare `wall` that quietly became 3 mm would be worse than one that fails,
    because the part would build and be wrong.
    """
    command = parse("wall")
    assert command.kind == "incomplete"
    assert command.value is None
    assert "needs a number" in command.problem
    # And it says how, rather than just refusing.
    assert "wall 3" in command.echo


@pytest.mark.parametrize("line", ["wall 0", "wall -2", "bore 0"])
def test_a_zero_or_negative_length_is_rejected_not_passed_through(line):
    """
    Zero is not a small number here. Passed into the geometry it becomes a
    boolean that reports valid and then fails three operations later, which
    is the hardest kind of failure to trace back to what caused it.
    """
    command = parse(line)
    assert command.kind == "rejected"
    assert "greater than 0" in command.problem


def test_a_standard_is_recorded_and_not_resolved_to_a_diameter():
    """
    "M4 clearance hole" has a real answer in the standards table (brief 4.5)
    and this module does not hold it. A second table of fastener sizes is a
    second table to be wrong, and the wrong one would be the one nobody is
    looking at.
    """
    command = parse("hole m4 x4")
    assert command.kind == "holes"
    assert command.standard == "M4"
    assert command.count == 4
    assert command.value is None, "the parser resolved a diameter it does not own"


# ---------------------------------------------------------------------------
# holes
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("line,standard,count", [
    ("hole m4 x4", "M4", 4),
    ("hole M4 x 4", "M4", 4),
    ("hole m4 ×4", "M4", 4),        # the multiplication sign, as designed
    ("holes m3 x2", "M3", 2),
    ("hole m5", "M5", 1),           # no count is one hole, not zero
    ("hole m2.5 x6", "M2.5", 6),
])
def test_holes_parse_in_every_form_the_design_shows(line, standard, count):
    command = parse(line)
    assert command.kind == "holes"
    assert command.standard == standard
    assert command.count == count


def test_one_hole_is_singular_in_the_echo():
    """A maker reading "1 × M5 clearance holes" learns the echo is generated
    rather than written, and stops trusting it."""
    assert parse("hole m5").echo == "added 1 × M5 clearance hole"
    assert parse("hole m5 x2").echo == "added 2 × M5 clearance holes"


# ---------------------------------------------------------------------------
# asking, and the two bare words
# ---------------------------------------------------------------------------

def test_a_question_asks_rather_than_sets():
    command = parse("clearance ?")
    assert command.kind == "ask"
    assert command.topic == "clearance"
    # No echo: the answer comes from the printer profile, and inventing one
    # here would be a hardcoded clearance figure stated as if calibrated -
    # which brief 4.3 forbids by name.
    assert command.echo == ""


def test_help_lists_the_vocabulary_and_is_therefore_the_documentation():
    command = parse("help")
    assert command.kind == "help"
    assert command.options == VOCABULARY
    for word in ("wall N", "clearance ?", "motion"):
        assert word in command.echo


def test_motion_is_a_viewport_command_and_changes_no_geometry():
    command = parse("motion")
    assert command.kind == "motion"
    assert command.refine is None, "motion asked for a rebuild"


# ---------------------------------------------------------------------------
# everything else is a part
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("line", [
    "a hinged clamp for a 32 mm pipe, wall 3 mm, four M4 tabs",
    "bracket to hold an 8 mm rod to a wall",
    "make it 20 mm taller",
    "wobble 3",                     # a word the vocabulary does not have
    "wall thickness 3",             # two words: not the terse form
])
def test_anything_the_vocabulary_does_not_know_is_read_as_a_new_part(line):
    command = parse(line)
    assert command.kind == "prompt"
    assert command.text == line
    assert command.echo == "read as a new prompt - generating a fresh version"


def test_a_pasted_prompt_character_is_not_part_of_the_command():
    """
    The interface draws a `>` before the input and the scrollback keeps it.
    Somebody copying a line back in should get the command, not a prompt
    beginning with a chevron.
    """
    assert parse("> wall 3").kind == "set"
    assert parse(">wall 3").kind == "set"
    assert parse("> ").kind == "empty"


def test_an_empty_line_does_nothing_at_all():
    for line in ("", "   ", None):
        command = parse(line)
        assert command.kind == "empty"
        assert command.echo == ""


def test_the_parser_never_raises():
    """
    It runs on every keystroke-committed line a user types, including whatever
    they paste. An exception here would take out the one control that is
    always on screen.
    """
    for line in ("m4", "??", "wall wall", "×", "0", "-", "hole m", "wall 3 4 5",
                 "🙂", "wall 999999999999999999999", "." * 500):
        assert parse(line).kind  # it returned something, whatever it was


# ---------------------------------------------------------------------------
# the wire shape
# ---------------------------------------------------------------------------

def test_the_json_omits_what_it_does_not_know():
    """
    Both clients read this. A `parameter: null` in the payload is a field a
    client has to test for, and it will be tested for in one client and not
    the other.
    """
    payload = parse("motion").to_json()
    assert payload["kind"] == "motion"
    assert "parameter" not in payload
    assert "value" not in payload
    assert "count" not in payload


def test_the_json_carries_everything_a_client_needs_to_act():
    payload = parse("wall 3").to_json()
    assert payload == {
        "kind": "set",
        "echo": "wall thickness → 3.0 mm",
        "parameter": "wall_mm",
        "unit": "mm",
        "refine": "set wall thickness to 3.0 mm",
        "value": 3.0,
    }
