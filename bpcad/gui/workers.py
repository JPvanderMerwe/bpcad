"""
Background work, so the window never freezes.

A generate takes about ninety seconds on CPU-only inference and a build takes
four. Neither may run on the UI thread. Every long call goes through a Worker,
which runs it in a QThread and reports back with signals.

CANCELLATION IS HONEST HERE. Python cannot safely kill a thread mid-call, so
`cancel()` sets a flag that is checked between steps - between model attempts,
before a build - rather than pretending to abort an OpenCascade boolean. The
UI says "finishing the current attempt" instead of claiming it stopped, because
a progress bar that lies is worse than one that waits.
"""

from __future__ import annotations

import traceback
from typing import Any, Callable

from PySide6.QtCore import QObject, QThread, Signal


class Cancelled(Exception):
    """Raised inside a worker when the user asked it to stop."""


class Worker(QObject):
    """
    Runs one callable on a thread and reports what happens.

    The callable is handed a `report(kind, payload)` function and a
    `should_cancel()` predicate, both safe to call from the worker thread.
    """

    started_work = Signal()
    event = Signal(str, object)      # kind, payload
    finished_ok = Signal(object)     # result
    failed = Signal(str, str)        # message, traceback
    done = Signal()                  # always, success or not

    def __init__(self, fn: Callable[..., Any], *args, **kwargs) -> None:
        super().__init__()
        self._fn = fn
        self._args = args
        self._kwargs = kwargs
        self._cancel = False

    def cancel(self) -> None:
        """Ask the work to stop at its next checkpoint."""
        self._cancel = True

    @property
    def cancelled(self) -> bool:
        return self._cancel

    def run(self) -> None:
        self.started_work.emit()
        try:
            result = self._fn(
                *self._args,
                report=lambda kind, payload=None: self.event.emit(kind, payload),
                should_cancel=lambda: self._cancel,
                **self._kwargs,
            )
            self.finished_ok.emit(result)
        except Cancelled:
            self.event.emit("cancelled", None)
        except Exception as exc:
            self.failed.emit(str(exc), traceback.format_exc())
        finally:
            self.done.emit()


class TaskRunner(QObject):
    """
    Owns a worker and its thread, and keeps them alive long enough.

    A QThread whose only reference is a local goes out of scope and takes the
    running work with it, in a way that looks like a random crash. Keeping the
    pair on `self` and only clearing it in the finished handler is the fix.
    """

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._thread: QThread | None = None
        self._worker: Worker | None = None

    @property
    def busy(self) -> bool:
        return self._thread is not None and self._thread.isRunning()

    def start(
        self,
        fn: Callable[..., Any],
        *args,
        on_event: Callable[[str, Any], None] | None = None,
        on_result: Callable[[Any], None] | None = None,
        on_error: Callable[[str, str], None] | None = None,
        on_done: Callable[[], None] | None = None,
        **kwargs,
    ) -> Worker:
        if self.busy:
            raise RuntimeError("this runner is already busy")

        thread = QThread()
        worker = Worker(fn, *args, **kwargs)
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        if on_event:
            worker.event.connect(on_event)
        if on_result:
            worker.finished_ok.connect(on_result)
        if on_error:
            worker.failed.connect(on_error)

        # worker.done is emitted ON THE WORKER THREAD, so it may only ask the
        # thread to quit - calling wait() there is a thread waiting on itself,
        # which Qt refuses and which leaves the runner permanently "busy".
        # The tidy-up belongs on thread.finished, which arrives on this thread.
        worker.done.connect(thread.quit)

        def finished() -> None:
            self._thread = None
            self._worker = None
            if on_done:
                on_done()

        thread.finished.connect(finished)

        self._thread = thread
        self._worker = worker
        thread.start()
        return worker

    def cancel(self) -> None:
        if self._worker is not None:
            self._worker.cancel()

    def wait(self, ms: int = 10000) -> None:
        """Block until the current work finishes. For clean shutdown only."""
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait(ms)


# ---------------------------------------------------------------------------
# the jobs themselves
# ---------------------------------------------------------------------------


def generate_job(request: str, report, should_cancel, **options):
    """A full prompt-to-bundle run, reporting each attempt as it lands."""
    from bpcad import api

    def on_event(kind: str, payload: Any) -> None:
        if should_cancel():
            raise Cancelled()
        report(kind, payload)

    return api.generate(request, on_event=on_event, **options)


def ask_job(request: str, report, should_cancel, **options):
    """Generation only - stops at the spec."""
    from bpcad import api

    def on_event(kind: str, payload: Any) -> None:
        if should_cancel():
            raise Cancelled()
        report(kind, payload)

    return api.ask(request, on_event=on_event, **options)


def build_job(report, should_cancel, spec=None, spec_path=None, **options):
    """Build a spec. Four seconds or so, but still off the UI thread."""
    from bpcad import api

    report("building", spec_path or (spec.name if spec else "spec"))
    if should_cancel():
        raise Cancelled()
    result = api.build(spec_path=spec_path, spec=spec, **options)
    report("built", result)
    return result


def render_job(stl, out_dir, report, should_cancel, **options):
    """Render the standard views, the height map and a section."""
    from bpcad import api

    report("rendering", str(stl))
    if should_cancel():
        raise Cancelled()
    return api.render_part(stl, out_dir, **options)


def model_status_job(report, should_cancel, machine=None):
    """Poll the daemon. Never raises - the caller shows a dot, not a dialog."""
    from bpcad import api

    return api.model_status(machine=machine)
