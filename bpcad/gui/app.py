"""
The main window: two views, and nothing else.

  HOME    one prompt, and everything you have made as cards
  PART    one part, large, with its versions and a box to change it

That is the whole navigation. Every technical panel - the checks, the spec, the
model's working - lives in a drawer on the part view, closed by default.

Nothing here computes anything. Every action goes through bpcad.api on a worker
thread; this file decides what to show.
"""

from __future__ import annotations

# The display-stack fix runs before Qt is imported. See bpcad.gui.platform.
from bpcad.gui import platform as _platform

_platform.bootstrap()

import sys
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QLabel, QMainWindow, QMessageBox,
    QStackedWidget, QWidget,
)

from bpcad import __version__, api
from bpcad.gui.panels.gallery import GalleryPanel
from bpcad.gui.panels.partview import PartView
from bpcad.gui.theme import ACCENT, BAD, OK, STYLESHEET, TEXT_DIM, WARN
from bpcad.gui.workers import (
    TaskRunner, build_job, session_create_job, session_refine_job, thumbnails_job,
)

HOME, PART = 0, 1


class MainWindow(QMainWindow):
    """bpcad."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("bpcad")
        self.resize(1500, 960)

        self.cfg = api.config()
        self.runner = TaskRunner(self)
        # A separate runner, so rendering thumbnails in the background can never
        # be what stops you starting a part.
        self.thumbs = TaskRunner(self)
        self.session: api.Session | None = None
        self.viewing = -1
        self._pending_thumb: Path | None = None

        self.stack = QStackedWidget()
        self.gallery = GalleryPanel(self.cfg)
        self.part_view = PartView()
        self.stack.addWidget(self.gallery)
        self.stack.addWidget(self.part_view)
        self.setCentralWidget(self.stack)

        self.gallery.create_requested.connect(self._create)
        self.gallery.cancel_requested.connect(self.runner.cancel)
        self.gallery.part_opened.connect(self._open_entry)
        self.part_view.back_requested.connect(self._go_home)
        self.part_view.refine_requested.connect(self._refine)
        self.part_view.cancel_requested.connect(self.runner.cancel)
        self.part_view.version_selected.connect(self._show_version)
        self.part_view.export_requested.connect(self._export)

        self._build_menu()

        self.model_label = QLabel("")
        self.statusBar().addPermanentWidget(self.model_label)
        self._poll_model()
        self._timer = QTimer(self)
        self._timer.setInterval(15000)
        self._timer.timeout.connect(self._poll_model)
        self._timer.start()

        self.refresh()

    # -- navigation --------------------------------------------------------

    def refresh(self) -> None:
        entries = api.library()
        self.gallery.set_parts(entries)

        missing = [e for e in entries if e.built and not e.images]
        if missing and not self.thumbs.busy:
            self.thumbs.start(
                thumbnails_job, missing,
                on_event=lambda kind, payload: (
                    self.gallery.refresh_card(*payload)
                    if kind == "thumbnail_for" else None
                ),
            )

    def _go_home(self) -> None:
        self.refresh()
        self.stack.setCurrentIndex(HOME)

    def _open_entry(self, entry) -> None:
        """Open a part from the gallery, rebuilding its session from disk."""
        entry = self._as_part_entry(entry)
        self.session = self._session_for(entry)
        self.viewing = len(self.session.versions) - 1 if self.session.versions else -1
        self.part_view.set_versions(self.session.versions, self.viewing)
        self.part_view.show_changes([])
        self.part_view.log.clear()

        if self.session.versions:
            self._show_version(self.viewing)
        else:
            self.part_view.show_part(
                entry.name, None, entry.images,
                spec_text=(entry.spec_path or entry.draft).read_text()
                if (entry.spec_path or entry.draft) else "",
            )
            if entry.is_draft:
                self.part_view.say(
                    "this run handed off - the draft has every problem marked inline",
                    WARN,
                )
                self.part_view.open_drawer(1)
        self.stack.setCurrentIndex(PART)

    def _as_part_entry(self, entry):
        """
        A LibraryEntry carries more than the rest of the window needs. This
        narrows it to the shape the part view and the session already take,
        rather than teaching every one of them about a second type.
        """
        if isinstance(entry, api.PartEntry):
            return entry
        return api.PartEntry(
            name=entry.name, directory=entry.directory,
            spec_path=entry.spec_path, stl=entry.stl,
            report_md=(entry.directory / "report.md")
            if (entry.directory / "report.md").is_file() else None,
            run_json=(entry.directory / "run.json")
            if (entry.directory / "run.json").is_file() else None,
            draft=entry.draft_path, images=dict(entry.images),
        )

    def _session_for(self, entry) -> api.Session:
        """
        Rebuild a session from what is on disk.

        A part opened from the gallery has no in-memory history, but its spec
        and its render are enough to make version one - which is what a
        refinement needs to work from.
        """
        session = api.Session(entry.directory, name=entry.name)
        if not entry.spec_path or not entry.stl or not entry.stl.is_file():
            return session
        try:
            spec, base = api.load_spec(entry.spec_path)
            report = api.verify(entry.stl, cfg=self.cfg)
        except api.ApiError:
            return session

        part = api.PartResult(
            name=entry.name, spec=spec, build=None, report=report,
            stl=entry.stl, part_dir=entry.directory,
            files=dict(entry.images),
        )
        thumb = (entry.images.get("thumb") or entry.images.get("3q")
                 or entry.images.get("preview")
                 or (next(iter(entry.images.values())) if entry.images else None))
        session.add(api.Version(index=0, spec=spec, part=part, thumbnail=thumb))
        return session

    # -- creating and changing ---------------------------------------------

    def _create(self, prompt: str, options: dict) -> None:
        if self.runner.busy:
            return
        name = self.gallery.name_edit.text().strip() or api._slug(prompt)
        self.session = api.Session(Path("parts") / name, name=name)
        self.session.prompt = prompt
        self.session.image = self.gallery.image_drop.path
        self.session.measurements = self.gallery.measurements
        self.viewing = -1
        self._pending_thumb = None

        self.part_view.set_versions([], -1)
        self.part_view.show_changes([])
        self.part_view.log.clear()
        self.part_view.title.setText(name)
        self.part_view.say("starting", ACCENT)
        self.stack.setCurrentIndex(PART)

        self._busy(True)
        self.runner.start(
            session_create_job, prompt,
            measurement=self.gallery.measurements,
            out_dir=str(self.session.root / "v01"),
            render=True, cfg=self.cfg,
            on_event=self._event,
            on_result=lambda r: self._result(r, ""),
            on_error=self._error,
            on_done=lambda: self._busy(False),
            **options,
        )

    def _refine(self, instruction: str) -> None:
        if self.runner.busy or not self.session:
            return
        base = self._viewed()
        if base is None or base.spec is None:
            self.part_view.say("nothing to change yet", WARN)
            return

        index = len(self.session.versions)
        self._pending_thumb = None
        self.part_view.append("")
        self.part_view.append("change: %s" % instruction)
        self._busy(True)
        self.runner.start(
            session_refine_job, base.spec, instruction,
            base_report=base.part.report if base.part else None,
            measurements=self.session.measurements,
            out_dir=str(self.session.version_dir(index)),
            render=True, cfg=self.cfg,
            on_event=self._event,
            on_result=lambda r: self._result(r, instruction),
            on_error=self._error,
            on_done=lambda: self._busy(False),
        )

    def _event(self, kind: str, payload: Any) -> None:
        if kind == "thumbnail":
            self._pending_thumb = payload
            return
        self.part_view.on_event(kind, payload)
        self.gallery.stage(kind, payload)

    def _result(self, result: Any, instruction: str) -> None:
        if self.session is None:
            return
        version = api.Version(
            index=len(self.session.versions),
            spec=result.spec,
            instruction=instruction,
            note=getattr(result, "note", ""),
            changes=list(getattr(result, "changes", [])),
            part=result.part,
            thumbnail=self._pending_thumb,
            elapsed_s=result.elapsed_s,
            attempts=result.attempt_count,
            error="" if result.ok else result.message,
        )
        self.session.add(version)
        self.session.save()

        if result.ok and result.part:
            self.part_view.say(
                "done in %.0fs, %d attempt(s)" % (result.elapsed_s, result.attempt_count),
                OK,
            )
            self.part_view.refine_edit.clear()
        else:
            self.part_view.append("")
            self.part_view.append(result.message)
            self.part_view.say("could not do that - see Model", BAD)
            self.part_view.open_drawer(3)

        self.part_view.set_versions(self.session.versions, version.index)
        self._show_version(version.index)
        self.refresh()

    def _viewed(self):
        if not self.session or not self.session.versions:
            return None
        if 0 <= self.viewing < len(self.session.versions):
            return self.session.versions[self.viewing]
        return self.session.current

    def _show_version(self, index: int) -> None:
        if not self.session or not 0 <= index < len(self.session.versions):
            return
        self.viewing = index
        v = self.session.versions[index]
        self.part_view.strip.select(index)
        self.part_view.show_changes(v.changes, v.note)

        if v.part is None:
            self.part_view.show_part(
                self.session.name, None, {},
                spec_text=v.error or "This version did not build.",
            )
            return

        spec_file = v.part.part_dir / "spec.yaml"
        report_md = v.part.part_dir / "report.md"
        images = {k: p for k, p in v.part.files.items() if str(p).endswith(".png")}
        self.part_view.show_part(
            "%s  %s" % (self.session.name, v.label.split("  ", 1)[0]),
            v.part, images,
            spec_text=spec_file.read_text() if spec_file.is_file() else "",
            report_md=report_md.read_text() if report_md.is_file() else "",
        )

    def _busy(self, busy: bool) -> None:
        self.gallery.set_busy(busy)
        self.part_view.set_busy(busy)

    def _error(self, message: str, trace: str) -> None:
        self.part_view.append(message)
        self.part_view.say(message.splitlines()[0][:100], BAD)
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("That did not work")
        box.setText(message.splitlines()[0][:200])
        box.setDetailedText(message + "\n\n" + trace)
        box.exec()

    # -- odds and ends -----------------------------------------------------

    def _export(self) -> None:
        v = self._viewed()
        if v is None or v.part is None:
            return
        target = QFileDialog.getExistingDirectory(self, "Export the bundle to")
        if not target:
            return
        import shutil

        out = Path(target) / self.session.name
        out.mkdir(parents=True, exist_ok=True)
        copied = 0
        for path in v.part.part_dir.rglob("*"):
            if path.is_file():
                dest = out / path.relative_to(v.part.part_dir)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, dest)
                copied += 1
        self.statusBar().showMessage("exported %d files to %s" % (copied, out), 8000)

    def _build_menu(self) -> None:
        part = self.menuBar().addMenu("&Part")
        act = QAction("Open an &STL...", self)
        act.setShortcut(QKeySequence.Open)
        act.triggered.connect(self._open_stl)
        part.addAction(act)
        part.addSeparator()

        act = QAction("&Import a spec...", self)
        act.triggered.connect(self._import_spec)
        part.addAction(act)

        act = QAction("&Share this part...", self)
        act.triggered.connect(self._export_spec)
        part.addAction(act)
        act = QAction("&Refresh", self)
        act.setShortcut(QKeySequence.Refresh)
        act.triggered.connect(self.refresh)
        part.addAction(act)
        part.addSeparator()
        act = QAction("&Quit", self)
        act.setShortcut(QKeySequence.Quit)
        act.triggered.connect(self.close)
        part.addAction(act)

        model = self.menuBar().addMenu("&Model")
        act = QAction("&Status...", self)
        act.triggered.connect(self._model_status)
        model.addAction(act)

        helpm = self.menuBar().addMenu("&Help")
        act = QAction("&About", self)
        act.triggered.connect(self._about)
        helpm.addAction(act)

    def _import_spec(self) -> None:
        """Take a spec someone sent and put it in the library."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Import a spec", "", "Specs (*.yaml *.yml)"
        )
        if not path:
            return
        try:
            entry = api.import_spec(path)
        except api.ApiError as exc:
            QMessageBox.warning(self, "That spec could not be imported", str(exc))
            return
        self.refresh()
        self.statusBar().showMessage(
            "imported %s - open it and press Apply to build it here" % entry.name, 10000
        )

    def _export_spec(self) -> None:
        """
        Share the SPEC, not the mesh.

        The recipient rebuilds it at their size, in their material, for their
        nozzle. A mesh would give them one frozen object instead.
        """
        entry = None
        if self.session is not None:
            v = self._viewed()
            if v is not None and v.part is not None:
                entry = api.library([v.part.part_dir.parent])
                entry = next((e for e in entry if e.name == v.part.name), None)
        if entry is None and self.current is not None:
            entry = next(
                (e for e in api.library() if e.name == self.current.name), None
            )
        if entry is None:
            QMessageBox.information(
                self, "Nothing to share", "Open a part first."
            )
            return

        target, _ = QFileDialog.getSaveFileName(
            self, "Share this part", "%s.spec.yaml" % entry.name,
            "Specs (*.yaml)",
        )
        if not target:
            return
        try:
            written = api.export_spec(entry, target)
        except api.ApiError as exc:
            QMessageBox.warning(self, "Could not share it", str(exc))
            return
        self.statusBar().showMessage(
            "wrote %s - twenty lines of text, and it rebuilds at any size" % written,
            10000,
        )

    def _open_stl(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open an STL", ".", "Meshes (*.stl)")
        if not path:
            return
        try:
            report = api.verify(path, cfg=self.cfg)
        except api.ApiError as exc:
            self.statusBar().showMessage(str(exc), 8000)
            return
        part = api.PartResult(
            name=Path(path).stem, spec=None, build=None, report=report,
            stl=Path(path), part_dir=Path(path).parent, files={},
        )
        self.session = None
        self.part_view.set_versions([], -1)
        self.part_view.show_part(Path(path).name, part, {})
        self.stack.setCurrentIndex(PART)

    def _poll_model(self) -> None:
        if self.runner.busy:
            return
        s = api.model_status(cfg=self.cfg)
        self._status = s
        if s.get("unset"):
            self.model_label.setText("● model not pinned")
            self.model_label.setStyleSheet("color: %s;" % WARN)
        elif s["available"]:
            where = s["loaded"][0]["processor"] if s["loaded"] else "idle"
            self.model_label.setText("● %s  %s" % (s.get("model_primary", "?"), where))
            self.model_label.setStyleSheet("color: %s;" % OK)
        else:
            self.model_label.setText("● model offline")
            self.model_label.setStyleSheet("color: %s;" % BAD)

    def _model_status(self) -> None:
        s = getattr(self, "_status", None) or api.model_status(cfg=self.cfg)
        lines = [
            "machine   %s" % s.get("machine", "?"),
            "host      %s" % s.get("host", "?"),
            "primary   %s" % s.get("model_primary", "?"),
            "small     %s" % s.get("model_small", "?"),
            "CUDA      %s" % ("present" if s.get("cuda") else "none"),
            "",
        ]
        if s.get("error"):
            lines.append(s["error"])
        else:
            lines += ["  %-24s %5.1f GB" % (m["name"], m["gb"]) for m in s["models"]]
            if s["loaded"]:
                lines.append("")
                lines += ["  %-24s %s" % (m["name"], m["processor"]) for m in s["loaded"]]
        QMessageBox.information(self, "Model", "\n".join(lines))

    def _about(self) -> None:
        from PySide6.QtCore import qVersion

        QMessageBox.information(
            self, "bpcad",
            "bpcad %s\n\n"
            "Local, offline text-and-image to printable part.\n\n"
            "The model does not write CAD code. It fills in a validated "
            "specification, and deterministic Python turns that into geometry - "
            "so a part is dimensioned and editable, and asking for it 10 mm "
            "wider is exact rather than a re-roll.\n\n"
            "Inference is local or it does not happen.\n\n"
            "Qt %s, VTK for the 3D view\n%s"
            % (__version__, qVersion(), _platform.describe()),
        )

    def closeEvent(self, event) -> None:  # noqa: N802
        if self.runner.busy:
            answer = QMessageBox.question(
                self, "Still working", "A run is still going. Quit anyway?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                event.ignore()
                return
            self.runner.cancel()
            self.runner.wait(3000)
        self.thumbs.cancel()
        self.thumbs.wait(2000)
        self.part_view.viewer.shutdown()
        super().closeEvent(event)


def main(argv: list[str] | None = None) -> int:
    """Entry point for `bpcad-gui` and `python -m bpcad.gui`."""
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("bpcad")
    app.setOrganizationName("Bit Primitive")
    app.setStyleSheet(STYLESHEET)

    try:
        window = MainWindow()
    except api.ApiError as exc:
        QMessageBox.critical(None, "bpcad cannot start", str(exc))
        return 1

    window.show()
    window.part_view.viewer.start()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
