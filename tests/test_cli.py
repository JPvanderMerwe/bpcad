"""
The CLI owns no pipeline logic, and one command proves it the hard way.

`bpcad gen` used to drive its own copy of the escalation ladder: its own
level-1 call, its own escalation to level 2, its own wall-clock budget, its own
run record. api.generate had the other copy.

That is not a tidiness complaint. The deterministic router was wired into
api.generate first, the whole test suite passed, and `bpcad gen` carried on
handing drilled plates to the enclosure template - correctly, by its own
lights, for as long as it took somebody to run the CLI and notice. Two paths
also measure differently, so no fit-rate number means anything while both
exist.

The GUI has had this rule enforced since it was written
(test_gui.test_the_gui_owns_no_pipeline_logic). This is the same rule for the
command line.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

CLI = Path(__file__).resolve().parent.parent / "bpcad" / "cli.py"


def _command_source(name: str) -> str:
    """The source of one @app.command function, by its command name."""
    tree = ast.parse(CLI.read_text())
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call):
                continue
            args = [a for a in decorator.args if isinstance(a, ast.Constant)]
            if args and args[0].value == name:
                return ast.get_source_segment(CLI.read_text(), node) or ""
    raise AssertionError("no @app.command(%r) in cli.py" % name)


# The ladder: the pieces that decide what to ask for, when to escalate, and
# whether the geometry survived. A front end that touches any of these has its
# own pipeline.
LADDER = (
    "run_ask",
    "ask_level_2",
    "compile_and_verify",
    "running_clearance_mm",
    "RunRecord",
    "write_bundle",
)


def test_gen_drives_no_ladder_of_its_own():
    source = _command_source("gen")
    offenders = [name for name in LADDER if name in source]
    assert not offenders, (
        "bpcad gen reaches into the pipeline (%s). It must call api.generate "
        "and nothing else, or a fix lands in one path and not the other - "
        "which is exactly how the router shipped working in the web app and "
        "broken in the CLI." % ", ".join(offenders)
    )


def test_gen_calls_api_generate():
    source = _command_source("gen")
    assert "api.generate(" in source, "gen must go through bpcad.api"


def test_the_budget_lives_in_the_api_not_the_command():
    """
    `--max-seconds` was the CLI's own feature, enforced inside its own verify
    callback, and it is half the reason the duplicate ladder existed. A budget
    is a pipeline concern - a web request wants one too - so it belongs to
    api.generate, and the command only passes the number along.
    """
    import inspect

    from bpcad import api

    assert "max_seconds" in inspect.signature(api.generate).parameters
    source = _command_source("gen")
    assert "max_seconds=max_seconds" in source


def test_every_command_is_registered_before_the_entry_point():
    """
    `if __name__ == "__main__": app()` runs at import time, so a command
    registered BELOW it does not exist when app() is called. `web` was in that
    position: `python -m bpcad.cli web` answered "No such command 'web'" while
    the installed console script worked, because that imports the module fully
    before calling app(). A difference that appears in only one of two ways of
    starting the same program is the worst kind to leave lying about.
    """
    lines = CLI.read_text().splitlines()
    main_at = next(i for i, line in enumerate(lines)
                   if line.startswith('if __name__ == "__main__"'))
    after = [i + 1 for i, line in enumerate(lines[main_at:], start=main_at)
             if line.startswith("@app.command") or line.startswith("@spec_app.command")]
    assert not after, (
        "commands are registered after the entry point, at lines %s - they "
        "will not exist under `python -m bpcad.cli`" % after
    )


def test_python_dash_m_can_reach_every_command():
    """
    The regression itself, exercised rather than asserted about. Runs the
    module the way that used to fail.
    """
    import subprocess
    import sys

    for command in ("gen", "build", "verify", "render", "web"):
        done = subprocess.run(
            [sys.executable, "-m", "bpcad.cli", command, "--help"],
            capture_output=True, text=True, timeout=120,
            cwd=str(CLI.parent.parent),
        )
        assert done.returncode == 0, (
            "python -m bpcad.cli %s --help failed: %s"
            % (command, (done.stderr or done.stdout)[-300:])
        )


def test_render_output_is_ignored():
    """
    `bpcad render` writes to ./out relative to the working directory. Every
    other generated mesh is ignored under parts/; this one was not, and sat
    staged waiting to be committed by accident.
    """
    ignore = (CLI.parent.parent / ".gitignore").read_text().splitlines()
    assert "/out/" in [line.strip() for line in ignore]


@pytest.mark.parametrize("front_end", ["cli", "web"])
def test_both_front_ends_reach_the_same_router(front_end):
    """
    The acceptance criterion in one assertion: whatever routes a request, both
    front ends get there through api.generate, so neither can be given a
    routing fix the other misses.
    """
    source = {
        "cli": _command_source("gen"),
        "web": (CLI.parent / "web" / "server.py").read_text(),
    }[front_end]
    assert "api.generate(" in source or "_generate_work" in source
    assert "ask_level_2" not in source, (
        "%s escalates on its own instead of leaving it to api.generate"
        % front_end
    )
