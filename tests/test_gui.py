"""
The desktop app.

Everything here runs headless with Qt's offscreen platform, so the suite needs
no display and no graphics driver. What is tested is the WIRING - that the form
generates from the schema, that nothing slow runs on the UI thread, that the
panels read the same data the CLI does. Pixels are not tested; they are looked
at.
"""

import os

import pytest

pytest.importorskip("PySide6", reason="the GUI is an optional extra")

# Must be set before QApplication exists.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from bpcad import api  # noqa: E402


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app


def test_the_form_generates_itself_from_the_schema(qt_app):
    """
    No per-template GUI code. A new template appears complete, or the form has
    quietly become a second description of the schema that can drift from it.
    """
    from bpcad.gui.panels.specform import SpecForm

    form = SpecForm()
    for name in api.templates():
        form.set_template(name)
        expected = len(api.template_info(name)["params"])
        assert len(form._rows) == expected, "%s: form has %d rows, schema has %d" % (
            name, len(form._rows), expected
        )


def test_every_row_carries_its_units_and_description(qt_app):
    from bpcad.gui.panels.specform import SpecForm

    form = SpecForm()
    form.set_template("louvre_vent")
    row = form._rows["frame_w_mm"]

    # The unit is stripped from the label and shown beside the input, so the
    # label reads "frame w" and the row still says mm. `field` is the wrapper
    # holding both; `widget` is the input alone. Conflating them is how the
    # units vanished from every row the first time.
    assert row.label.text() == "frame w"
    assert row.meta["units"] == "mm"
    assert row.field is not row.widget, "a row with units needs its unit label"
    assert "legal" in row.widget.toolTip()
    assert row.meta["name"] in row.widget.toolTip()

    # Marking and clearing an error must not eat the tooltip.
    row.mark("something is wrong")
    assert "something is wrong" in row.widget.toolTip()
    assert "legal" in row.widget.toolTip()
    row.mark(None)
    assert "legal" in row.widget.toolTip()


def test_a_derived_parameter_offers_auto(qt_app):
    """
    The four derived defaults must be settable back to "unset", or the form
    forces a fixed value and undoes the fix that took level-1 success from 50%
    to 100%.
    """
    from bpcad.gui.panels.specform import SpecForm

    form = SpecForm()
    form.set_template("louvre_vent")
    for name in ("n_blades", "blade_chord_mm", "crank_r_mm"):
        widget = form._rows[name].widget
        assert widget.specialValueText() == "auto"
        assert widget.value() == widget.minimum()
    assert "n_blades" not in form.params(), "auto must mean omitted"


def test_the_widgets_cannot_be_pushed_outside_the_schema(qt_app):
    """
    The strongest form of field validation is making the bad value
    unreachable. Each spin box takes its range from the schema, so a
    single-field error mostly cannot be entered at all - which is why the
    errors that DO occur are the cross-field ones.
    """
    from bpcad.gui.panels.specform import SpecForm

    form = SpecForm()
    form.set_template("louvre_vent")
    wall = form._rows["wall_mm"].widget

    wall.setValue(999.0)
    assert wall.value() <= 20.0, "the schema says wall_mm <= 20"
    wall.setValue(-5.0)
    assert wall.value() > 0.0, "the schema says wall_mm > 0.4"


def test_a_field_problem_marks_that_field(qt_app):
    """When a per-field problem does arise, the field itself is marked."""
    from bpcad.gui.panels.specform import ParamRow, SpecForm

    form = SpecForm()
    form.set_template("louvre_vent")
    row = form._rows["wall_mm"]
    row.mark("wall_mm is too thick")
    assert row.widget.property("invalid") is True
    assert "too thick" in row.widget.toolTip()
    row.mark(None)
    assert row.widget.property("invalid") is False


def test_a_cross_field_problem_goes_in_the_banner_not_on_a_field(qt_app):
    """
    "The blades must be narrower than their pitch" belongs to no single widget.
    Marking one of them red would point at the wrong thing.
    """
    from bpcad.gui.panels.specform import SpecForm

    form = SpecForm()
    form.set_template("louvre_vent")
    form._rows["frame_w_mm"].widget.setValue(60.0)
    form._rows["n_blades"].widget.setValue(8)
    form._validate()

    # isVisible() is False for anything whose window was never shown, so the
    # question to ask is whether the banner was TOLD to show, and what it says.
    assert not form._banner.isHidden()
    assert "blade" in form._banner.text().lower()
    assert not any(
        r.widget.property("invalid") for r in form._rows.values()
    ), "a cross-field problem must not point at one field"


def test_the_viewer_reports_whether_it_can_run(qt_app):
    """
    Constructing a real VTK render window under the offscreen platform can take
    the whole process down inside the driver, which no amount of Python
    try/except will catch. So this checks the CONTRACT without building one:
    the widget must expose `available`, and every method must be safe to call
    when it is False, because that is the path a machine with no GL takes.
    """
    from bpcad.gui import viewer3d

    for name in ("available", "load", "clear", "set_view", "set_mode",
                 "start", "shutdown", "reset_camera"):
        assert hasattr(viewer3d.Viewer3D, name)

    class Unavailable(viewer3d.Viewer3D):
        def __init__(self):            # deliberately does not build VTK
            self._ok = False
            self._actors = []
            self._path = None
            self._mode = "shaded"

    v = Unavailable()
    assert v.available is False
    assert v.load("anything.stl") is False
    v.clear(); v.set_view("3q"); v.set_mode("height")
    v.start(); v.reset_camera(); v.shutdown()


def test_the_named_views_match_the_renderer(qt_app):
    """
    "3q" must mean the same thing in the live view and in the rendered PNG, or
    comparing them is comparing two different things.
    """
    from bpcad.gui.viewer3d import VIEW_DIRECTIONS
    from bpcad.render.views import VIEWS

    shared = set(VIEW_DIRECTIONS) & set(VIEWS)
    assert {"3q", "front", "above"} <= shared


def test_the_report_panel_shows_three_states(qt_app):
    from bpcad.gui.panels.report import ReportPanel
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    panel = ReportPanel()

    panel.show_report(api.verify(root / "reference" / "loop_keyring.stl"), "keyring")
    assert panel.verdict.text().startswith("PASS")
    assert "with warnings" not in panel.verdict.text()

    panel.show_report(api.verify(root / "reference" / "vent_louvre.stl"), "vent")
    assert "with warnings" in panel.verdict.text()

    panel.clear()
    assert "No part" in panel.verdict.text()


def test_the_gui_owns_no_pipeline_logic():
    """
    The rule that keeps the CLI and the GUI from drifting: every panel goes
    through bpcad.api, and none of them reaches past it into the internals.
    """
    from pathlib import Path

    gui = Path(__file__).resolve().parent.parent / "bpcad" / "gui"
    offenders = []
    for path in gui.rglob("*.py"):
        source = path.read_text()
        for forbidden in ("from bpcad.build", "from bpcad.agent.loop",
                          "from bpcad.models.ollama", "import cadquery"):
            if forbidden in source:
                offenders.append("%s imports %r" % (path.name, forbidden))
    assert not offenders, "the GUI must go through bpcad.api: " + "; ".join(offenders)


def test_long_work_has_somewhere_to_run(qt_app):
    """A ninety-second generate may not run on the UI thread."""
    from bpcad.gui.workers import TaskRunner

    from PySide6.QtCore import QEventLoop, QTimer

    runner = TaskRunner()
    assert not runner.busy

    def job(report, should_cancel):
        # Not `report(...) or "done"`: Signal.emit() returns True in PySide6,
        # so the `or` short-circuits and the job returns True instead.
        report("tick", 1)
        return "done"

    seen = {}
    loop = QEventLoop()
    runner.start(
        job,
        on_event=lambda k, p: seen.setdefault(k, p),
        on_result=lambda r: seen.setdefault("result", r),
        on_done=loop.quit,
    )
    QTimer.singleShot(5000, loop.quit)      # never hang the suite
    loop.exec()

    assert seen.get("result") == "done"
    assert seen.get("tick") == 1
    assert not runner.busy, "the runner must free itself when the work ends"


def test_the_platform_bootstrap_never_loops():
    from bpcad.gui import platform

    os.environ[platform.GUARD] = "1"
    platform.bootstrap()          # must return immediately, not re-exec
    assert platform.describe()


def test_the_bootstrap_refuses_to_reexec_what_it_cannot_rebuild(monkeypatch):
    """
    `python -c "..."` has no recoverable script path. Re-execing it produces
    "Argument expected for the -c option", which says nothing about the display
    server that actually needed fixing.
    """
    import sys

    from bpcad.gui import platform

    monkeypatch.setattr(sys, "argv", ["-c"])
    assert platform.can_reexec() is False


def test_no_job_takes_an_argument_the_worker_injects():
    """
    The worker injects `report` and `should_cancel` into every job, so no job
    may accept a caller-supplied argument of either name. One did: api.refine
    takes a `report` - the verify report of the part being changed - and the
    refine job passed it straight through, so Python saw two values for the
    same keyword and refinement died with a TypeError before any work started.

    That is invisible until someone presses the button, which is why it is
    checked here rather than trusted.
    """
    import inspect

    from bpcad.gui import workers

    injected = {"report", "should_cancel"}
    for name in dir(workers):
        if not name.endswith("_job"):
            continue
        fn = getattr(workers, name)
        params = inspect.signature(fn).parameters
        for bad in injected:
            if bad in params:
                kind = params[bad].kind
                assert kind is inspect.Parameter.POSITIONAL_OR_KEYWORD, name
                # It must be the injected one, never a passthrough with a
                # default that a caller could also supply.
                assert params[bad].default is inspect.Parameter.empty, (
                    "%s takes %r with a default - a caller supplying it would "
                    "collide with the one the worker injects" % (name, bad)
                )


def test_the_refine_job_forwards_the_verify_report(qt_app, monkeypatch):
    """The report still has to reach api.refine, under its own name."""
    from bpcad import api
    from bpcad.gui import workers

    seen = {}

    def fake_refine(spec, instruction, **kwargs):
        seen.update(kwargs)
        return api.GenerateResult(ok=False, message="stub")

    monkeypatch.setattr(api, "refine", fake_refine)
    result = workers.session_refine_job(
        "spec", "wider", report=lambda *a: None, should_cancel=lambda: False,
        base_report="THE-REPORT", cfg=None,
    )
    assert result.message == "stub"
    assert seen["report"] == "THE-REPORT", "the verify report must still arrive"
    assert seen["cfg"] is None
