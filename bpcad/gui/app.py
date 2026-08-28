"""
The main window.

Layout: parts on the left, the part itself in the middle, what verify found on
the right. The middle switches between the live 3D view and the rendered
images; the left switches between the library, a prompt, and a parameter form.

Nothing here computes anything. Every action goes to bpcad.api on a worker
thread, and the window's job is to show what came back.
"""

from __future__ import annotations

# The display-stack fix has to run before Qt is imported, and before the
# process is too far along to re-exec. See bpcad.gui.platform for why.
from bpcad.gui import platform as _platform

_platform.bootstrap()

import sys
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QAction, QKeySequence, QPixmap
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFileDialog, QHBoxLayout, QLabel, QMainWindow,
    QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QSplitter,
    QStackedWidget, QTabWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
    QWidget,
)

from bpcad import __version__, api
from bpcad.gui.panels.generate import GeneratePanel
from bpcad.gui.panels.studio import StudioPanel
from bpcad.gui.panels.report import ReportPanel
from bpcad.gui.panels.specform import SpecPanel
from bpcad.gui.theme import ACCENT, BAD, OK, STYLESHEET, TEXT_DIM, WARN
from bpcad.gui.viewer3d import VIEW_DIRECTIONS, Viewer3D
from bpcad.gui.workers import (
    TaskRunner, build_job, generate_job, model_status_job,
    session_create_job, session_refine_job,
)


class ImageView(QScrollArea):
    """A rendered PNG, scaled to fit and re-scaled when the panel resizes."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setAlignment(Qt.AlignCenter)
        self._label = QLabel("No image.")
        self._label.setAlignment(Qt.AlignCenter)
        self._label.setStyleSheet("color: %s;" % TEXT_DIM)
        self.setWidget(self._label)
        self._pixmap: QPixmap | None = None

    def show_image(self, path: str | Path | None) -> None:
        if path is None or not Path(path).is_file():
            self._pixmap = None
            self._label.setText("Not rendered yet.")
            self._label.setPixmap(QPixmap())
            return
        self._pixmap = QPixmap(str(path))
        self._rescale()

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().resizeEvent(event)
        self._rescale()

    def _rescale(self) -> None:
        if self._pixmap is None or self._pixmap.isNull():
            return
        size = self.viewport().size()
        self._label.setPixmap(
            self._pixmap.scaled(size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        )


class MainWindow(QMainWindow):
    """bpcad, with a face on it."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("bpcad %s" % __version__)
        self.resize(1500, 940)

        self.cfg = api.config()
        self.runner = TaskRunner(self)
        self.current: api.PartEntry | None = None
        self.current_report: Any = None
        self.session: api.Session | None = None
        self.viewing: int = -1

        self._build_ui()
        self._build_menu()
        self.refresh_library()
        self._poll_model()

        self._model_timer = QTimer(self)
        self._model_timer.setInterval(15000)
        self._model_timer.timeout.connect(self._poll_model)
        self._model_timer.start()

    # -- construction ------------------------------------------------------

    def _build_ui(self) -> None:
        splitter = QSplitter(Qt.Horizontal)

        # --- left: studio, library, parameters ---------------------------
        self.left_tabs = QTabWidget()

        # The studio comes first because it is the thing you do: describe a
        # part, look at it, say what is wrong, look again.
        self.studio = StudioPanel(self.cfg)
        self.left_tabs.addTab(self.studio, "Studio")

        library = QWidget()
        lib_layout = QVBoxLayout(library)
        lib_layout.setContentsMargins(8, 8, 8, 8)
        lib_layout.setSpacing(6)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Part", "State"])
        self.tree.setRootIsDecorated(False)
        self.tree.itemSelectionChanged.connect(self._on_part_selected)
        lib_layout.addWidget(self.tree, 1)
        row = QHBoxLayout()
        self.refresh_btn = QPushButton("Refresh")
        self.rebuild_btn = QPushButton("Rebuild")
        self.rebuild_btn.setEnabled(False)
        row.addWidget(self.refresh_btn)
        row.addWidget(self.rebuild_btn)
        lib_layout.addLayout(row)
        self.left_tabs.addTab(library, "Parts")

        self.generate_panel = GeneratePanel(self.cfg)
        self.left_tabs.addTab(self.generate_panel, "One-shot")

        self.spec_panel = SpecPanel(self.cfg)
        self.left_tabs.addTab(self.spec_panel, "Parameters")

        splitter.addWidget(self.left_tabs)

        # --- middle: the part --------------------------------------------
        middle = QWidget()
        mid_layout = QVBoxLayout(middle)
        mid_layout.setContentsMargins(8, 8, 8, 8)
        mid_layout.setSpacing(6)

        bar = QHBoxLayout()
        self.source_box = QComboBox()
        self.source_box.addItems(["Interactive 3D", "Rendered images"])
        self.source_box.currentIndexChanged.connect(self._on_source_changed)
        bar.addWidget(self.source_box)

        self.view_box = QComboBox()
        self.view_box.addItems(["3q", "front", "back", "left", "right", "above", "below"])
        self.view_box.currentTextChanged.connect(self._on_view_changed)
        bar.addWidget(self.view_box)

        self.shading_box = QComboBox()
        self.shading_box.addItems(["Shaded", "Colour by height"])
        self.shading_box.setToolTip(
            "Shading cannot show a recess whose floor faces the same way as the "
            "surface around it. Colouring by height can - that is what the height "
            "map is for, and this is its interactive twin."
        )
        self.shading_box.currentIndexChanged.connect(self._on_shading_changed)
        bar.addWidget(self.shading_box)

        self.image_box = QComboBox()
        self.image_box.addItems(["heightmap", "section", "3q", "front", "side", "above"])
        self.image_box.setVisible(False)
        self.image_box.currentTextChanged.connect(self._show_image)
        bar.addWidget(self.image_box)

        bar.addStretch(1)
        self.fit_btn = QPushButton("Fit")
        self.fit_btn.clicked.connect(lambda: self.viewer.reset_camera())
        bar.addWidget(self.fit_btn)
        mid_layout.addLayout(bar)

        self.stack = QStackedWidget()
        self.viewer = Viewer3D()
        self.images = ImageView()
        self.stack.addWidget(self.viewer)
        self.stack.addWidget(self.images)
        mid_layout.addWidget(self.stack, 1)

        self.part_line = QLabel("Select a part on the left, or generate one.")
        self.part_line.setStyleSheet("color: %s;" % TEXT_DIM)
        mid_layout.addWidget(self.part_line)
        splitter.addWidget(middle)

        # --- right: report and report.md ---------------------------------
        self.right_tabs = QTabWidget()
        self.report_panel = ReportPanel()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.report_panel)
        self.right_tabs.addTab(scroll, "Verify")

        self.markdown = QPlainTextEdit()
        self.markdown.setReadOnly(True)
        self.right_tabs.addTab(self.markdown, "report.md")

        self.spec_text = QPlainTextEdit()
        self.spec_text.setReadOnly(True)
        self.right_tabs.addTab(self.spec_text, "spec.yaml")
        splitter.addWidget(self.right_tabs)

        splitter.setSizes([420, 690, 390])
        self.setCentralWidget(splitter)

        # --- status bar ---------------------------------------------------
        self.model_label = QLabel("checking the model...")
        self.statusBar().addPermanentWidget(self.model_label)
        self.statusBar().showMessage("Ready.")

        self.studio.create_requested.connect(self._studio_create)
        self.studio.refine_requested.connect(self._studio_refine)
        self.studio.cancel_requested.connect(self.runner.cancel)
        self.studio.version_selected.connect(self._show_version)

        self.refresh_btn.clicked.connect(self.refresh_library)
        self.rebuild_btn.clicked.connect(self._rebuild_current)
        self.generate_panel.run_requested.connect(self._start_generate)
        self.generate_panel.cancel_requested.connect(self.runner.cancel)
        self.generate_panel.open_draft.connect(self._open_draft)
        self.spec_panel.build_requested.connect(self._build_from_form)

    def _build_menu(self) -> None:
        part_menu = self.menuBar().addMenu("&Part")
        open_action = QAction("&Open spec.yaml...", self)
        open_action.setShortcut(QKeySequence.Open)
        open_action.triggered.connect(self._open_spec)
        part_menu.addAction(open_action)

        open_stl = QAction("Open &STL...", self)
        open_stl.triggered.connect(self._open_stl)
        part_menu.addAction(open_stl)

        part_menu.addSeparator()
        refresh = QAction("&Refresh library", self)
        refresh.setShortcut(QKeySequence.Refresh)
        refresh.triggered.connect(self.refresh_library)
        part_menu.addAction(refresh)

        part_menu.addSeparator()
        quit_action = QAction("&Quit", self)
        quit_action.setShortcut(QKeySequence.Quit)
        quit_action.triggered.connect(self.close)
        part_menu.addAction(quit_action)

        model_menu = self.menuBar().addMenu("&Model")
        status = QAction("&Status...", self)
        status.triggered.connect(self._show_model_status)
        model_menu.addAction(status)

        help_menu = self.menuBar().addMenu("&Help")
        about = QAction("&About bpcad", self)
        about.triggered.connect(self._about)
        help_menu.addAction(about)

    # -- library -----------------------------------------------------------

    def refresh_library(self) -> None:
        self.tree.clear()
        for entry in api.parts():
            if entry.is_draft:
                state, colour = "needs editing", WARN
            elif entry.built:
                state, colour = "built", OK
            else:
                state, colour = "spec only", TEXT_DIM
            item = QTreeWidgetItem([entry.name, state])
            item.setForeground(1, Qt.NoBrush if colour is None else __import__(
                "PySide6.QtGui", fromlist=["QColor"]).QColor(colour))
            item.setData(0, Qt.UserRole, entry)
            self.tree.addTopLevelItem(item)
        self.tree.resizeColumnToContents(0)

    def _on_part_selected(self) -> None:
        items = self.tree.selectedItems()
        if not items:
            return
        entry: api.PartEntry = items[0].data(0, Qt.UserRole)
        self.load_part(entry)

    def load_part(self, entry: api.PartEntry) -> None:
        self.current = entry
        self.rebuild_btn.setEnabled(entry.spec_path is not None)

        if entry.spec_path and entry.spec_path.is_file():
            self.spec_text.setPlainText(entry.spec_path.read_text())
        elif entry.draft:
            self.spec_text.setPlainText(entry.draft.read_text())
        else:
            self.spec_text.setPlainText("")

        self.markdown.setPlainText(
            entry.report_md.read_text() if entry.report_md else ""
        )

        if entry.stl and entry.stl.is_file():
            self.viewer.load(entry.stl)
            self._show_image(self.image_box.currentText())
            self.part_line.setText(str(entry.stl))
            self.statusBar().showMessage("Verifying %s..." % entry.name)
            try:
                report = api.verify(entry.stl, cfg=self.cfg)
                self.current_report = report
                self.report_panel.show_report(report, entry.name)
                self.statusBar().showMessage(
                    "%s   %s" % (entry.name, report.verdict), 6000
                )
            except api.ApiError as exc:
                self.statusBar().showMessage(str(exc), 8000)
        else:
            self.viewer.clear()
            self.images.show_image(None)
            self.report_panel.clear()
            self.current_report = None
            if entry.is_draft:
                self.part_line.setText(
                    "This run handed off. Open the draft on the right - every "
                    "problem is marked inline with what is legal."
                )
                self.right_tabs.setCurrentIndex(2)
            else:
                self.part_line.setText("Not built yet. Press Rebuild.")

    # -- the middle panel --------------------------------------------------

    def _on_source_changed(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        self.view_box.setVisible(index == 0)
        self.shading_box.setVisible(index == 0)
        self.fit_btn.setVisible(index == 0)
        self.image_box.setVisible(index == 1)
        if index == 1:
            self._show_image(self.image_box.currentText())

    def _on_view_changed(self, name: str) -> None:
        if name in VIEW_DIRECTIONS:
            self.viewer.set_view(name)

    def _on_shading_changed(self, index: int) -> None:
        self.viewer.set_mode("height" if index == 1 else "shaded")

    def _show_image(self, key: str) -> None:
        if not self.current:
            return
        self.images.show_image(self.current.images.get(key))

    # -- running work ------------------------------------------------------

    def _busy(self, busy: bool, message: str = "") -> None:
        self.studio.set_busy(busy)
        self.generate_panel.set_busy(busy)
        self.rebuild_btn.setEnabled(not busy and self.current is not None
                                    and self.current.spec_path is not None)
        self.spec_panel.build_btn.setEnabled(not busy)
        if message:
            self.statusBar().showMessage(message)

    def _start_generate(self, prompt: str, options: dict) -> None:
        if self.runner.busy:
            return
        self._busy(True, "Generating...")
        self.runner.start(
            generate_job, prompt,
            on_event=self.generate_panel.on_event,
            on_result=self._on_generate_result,
            on_error=self._on_worker_error,
            on_done=lambda: self._busy(False),
            **options,
        )

    def _on_generate_result(self, result: Any) -> None:
        self.generate_panel.on_result(result)
        self.refresh_library()
        target = result.part.name if result.ok and result.part else None
        if target:
            for i in range(self.tree.topLevelItemCount()):
                item = self.tree.topLevelItem(i)
                if item.text(0) == target:
                    self.tree.setCurrentItem(item)
                    break
            self.statusBar().showMessage("%s built and verified." % target, 8000)

    # -- the studio --------------------------------------------------------

    def _studio_create(self, prompt: str, options: dict) -> None:
        """Start a new part. A fresh session, so the history starts clean."""
        if self.runner.busy:
            return
        name = self.studio.name_edit.text().strip() or api._slug(prompt)
        self.session = api.Session(Path("parts") / name, name=name)
        self.session.prompt = prompt
        self.session.image = self.studio.image_drop.path
        self.session.measurements = self.studio.measurements
        self.viewing = -1
        self.studio.set_versions([], -1)
        self.studio.show_changes([])

        self._busy(True, "Creating %s..." % name)
        self._pending_thumb = None
        self.runner.start(
            session_create_job, prompt,
            out_dir=str(self.session.root / "v01"),
            render=True, cfg=self.cfg,
            on_event=self._studio_event,
            on_result=lambda r: self._studio_result(r, instruction=""),
            on_error=self._on_worker_error,
            on_done=lambda: self._busy(False),
            **options,
        )

    def _studio_refine(self, instruction: str, options: dict) -> None:
        """Change the version currently on screen."""
        if self.runner.busy or not self.session:
            return
        base = self._viewed_version()
        if base is None or base.spec is None:
            self.studio.say("nothing to change yet", WARN)
            return

        index = len(self.session.versions)
        self._busy(True, "Applying: %s" % instruction[:50])
        self._pending_thumb = None
        self.studio.append("")
        self.studio.append("change: %s" % instruction)
        self.runner.start(
            session_refine_job, base.spec, instruction,
            report=base.part.report if base.part else None,
            measurements=self.session.measurements,
            out_dir=str(self.session.version_dir(index)),
            render=True, cfg=self.cfg,
            on_event=self._studio_event,
            on_result=lambda r: self._studio_result(r, instruction=instruction),
            on_error=self._on_worker_error,
            on_done=lambda: self._busy(False),
            **{k: v for k, v in options.items() if k in ("machine",)},
        )

    def _studio_event(self, kind: str, payload: Any) -> None:
        if kind == "thumbnail":
            self._pending_thumb = payload
            return
        self.studio.on_event(kind, payload)

    def _studio_result(self, result: Any, instruction: str) -> None:
        if self.session is None:
            return

        version = api.Version(
            index=len(self.session.versions),
            spec=result.spec,
            instruction=instruction,
            note=getattr(result, "note", ""),
            changes=list(getattr(result, "changes", [])),
            part=result.part,
            thumbnail=getattr(self, "_pending_thumb", None),
            elapsed_s=result.elapsed_s,
            attempts=result.attempt_count,
            error="" if result.ok else result.message,
        )
        self.session.add(version)
        self.session.save()

        self.studio.append("")
        if result.ok and result.part:
            p = result.part
            self.studio.append(
                "%s   %.2f x %.2f x %.2f mm   %.3f cm3   %d body(s)"
                % (p.name, *p.envelope_mm, p.volume_cm3, p.report.mesh.body_count)
            )
            for line in version.changes:
                self.studio.append("  %s" % line)
            self.studio.say("done in %.0fs" % result.elapsed_s, OK)
            self.studio.set_has_part(True)
            self.studio.show_changes(version.changes, version.note)
        else:
            self.studio.append(result.message)
            self.studio.say("could not do that", BAD)
            self.studio.show_changes([], "")

        self.studio.set_versions(self.session.versions, version.index)
        self._show_version(version.index)
        self.refresh_library()

    def _viewed_version(self):
        if not self.session or not self.session.versions:
            return None
        if 0 <= self.viewing < len(self.session.versions):
            return self.session.versions[self.viewing]
        return self.session.current

    def _show_version(self, index: int) -> None:
        """Put a version on screen. Everything about it, not just the mesh."""
        if not self.session or not 0 <= index < len(self.session.versions):
            return
        self.viewing = index
        version = self.session.versions[index]
        self.studio.strip.select(index)
        self.studio.show_changes(version.changes, version.note)

        if version.part is None:
            self.part_line.setText(version.error or "This version did not build.")
            return

        part = version.part
        self.viewer.load(part.stl)
        self.current = api.PartEntry(
            name=part.name, directory=part.part_dir,
            spec_path=part.part_dir / "spec.yaml",
            stl=part.stl,
            report_md=part.part_dir / "report.md",
            images={
                k: v for k, v in part.files.items()
                if str(v).endswith(".png")
            },
        )
        self.report_panel.show_report(part.report, version.label)
        self.current_report = part.report
        spec_file = part.part_dir / "spec.yaml"
        if spec_file.is_file():
            self.spec_text.setPlainText(spec_file.read_text())
        report_md = part.part_dir / "report.md"
        if report_md.is_file():
            self.markdown.setPlainText(report_md.read_text())
        self.part_line.setText(
            "%s   %s   %.3f cm3" % (version.label, part.report.verdict, part.volume_cm3)
        )

    def _rebuild_current(self) -> None:
        if not self.current or not self.current.spec_path or self.runner.busy:
            return
        self._busy(True, "Building %s..." % self.current.name)
        self.runner.start(
            build_job,
            spec_path=str(self.current.spec_path),
            out_dir=str(self.current.directory),
            cfg=self.cfg, render=True, bundle=True,
            on_result=self._on_build_result,
            on_error=self._on_worker_error,
            on_done=lambda: self._busy(False),
        )

    def _build_from_form(self, spec: Any) -> None:
        if self.runner.busy:
            return
        target = Path("parts") / spec.name
        self._busy(True, "Building %s..." % spec.name)
        self.runner.start(
            build_job, spec=spec, out_dir=str(target),
            cfg=self.cfg, render=True, bundle=True,
            on_result=self._on_build_result,
            on_error=self._on_worker_error,
            on_done=lambda: self._busy(False),
        )

    def _on_build_result(self, result: api.PartResult) -> None:
        self.refresh_library()
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            if item.text(0) == result.name:
                self.tree.setCurrentItem(item)
                break
        self.statusBar().showMessage(
            "%s  %.2f x %.2f x %.2f mm  %.3f cm3  %s"
            % (result.name, *result.envelope_mm, result.volume_cm3,
               "verified" if result.ok else "HAS PROBLEMS"), 10000
        )

    def _on_worker_error(self, message: str, trace: str) -> None:
        self.generate_panel.on_error(message, trace)
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("That did not work")
        box.setText(message.splitlines()[0][:200])
        box.setDetailedText(message + "\n\n" + trace)
        box.exec()

    # -- odds and ends -----------------------------------------------------

    def _open_spec(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open a spec", "parts", "Specs (*.yaml *.yml)"
        )
        if not path:
            return
        entry = api.PartEntry(
            name=Path(path).parent.name, directory=Path(path).parent,
            spec_path=Path(path),
        )
        stls = sorted((entry.directory / "out").glob("*.stl"))
        entry.stl = stls[0] if stls else None
        self.load_part(entry)

    def _open_stl(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open an STL", ".", "Meshes (*.stl)")
        if not path:
            return
        self.viewer.load(path)
        self.part_line.setText(path)
        try:
            report = api.verify(path, cfg=self.cfg)
            self.current_report = report
            self.report_panel.show_report(report, Path(path).name)
        except api.ApiError as exc:
            self.statusBar().showMessage(str(exc), 8000)

    def _open_draft(self, draft: Path | None) -> None:
        if draft and Path(draft).is_file():
            self.spec_text.setPlainText(Path(draft).read_text())
            self.right_tabs.setCurrentIndex(2)
            self.refresh_library()

    def _poll_model(self) -> None:
        if self.runner.busy:
            return
        status = api.model_status(cfg=self.cfg)
        if status.get("unset"):
            self.model_label.setText("model: not pinned for this machine")
            self.model_label.setStyleSheet("color: %s;" % WARN)
        elif status["available"]:
            loaded = status["loaded"][0]["processor"] if status["loaded"] else "idle"
            self.model_label.setText(
                "model: %s  (%s)" % (status.get("model_primary", "?"), loaded)
            )
            self.model_label.setStyleSheet("color: %s;" % OK)
        else:
            self.model_label.setText("model: not running")
            self.model_label.setStyleSheet("color: %s;" % BAD)
        self._model_status = status

    def _show_model_status(self) -> None:
        s = getattr(self, "_model_status", None) or api.model_status(cfg=self.cfg)
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
            lines.append("models on the daemon:")
            lines += ["  %-24s %5.1f GB" % (m["name"], m["gb"]) for m in s["models"]]
            if s["loaded"]:
                lines.append("")
                lines.append("loaded now:")
                lines += ["  %-24s %s" % (m["name"], m["processor"]) for m in s["loaded"]]
        QMessageBox.information(self, "Model status", "\n".join(lines))

    def _about(self) -> None:
        QMessageBox.information(
            self, "bpcad",
            "bpcad %s\n\n"
            "A local, offline text-and-image-to-3D-printable-part pipeline.\n\n"
            "The model does not write CAD code. It fills in a validated spec, "
            "and deterministic Python turns that spec into geometry. Everything "
            "downstream of a spec works with no model at all.\n\n"
            "Inference is local or it does not happen: every backend asserts its "
            "host is loopback at construction.\n\n"
            "Qt %s  |  interactive 3D by VTK\n%s"
            % (__version__,
               __import__("PySide6.QtCore", fromlist=["qVersion"]).qVersion(),
               _platform.describe()),
        )

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if self.runner.busy:
            answer = QMessageBox.question(
                self, "Still working",
                "A run is still going. Quit anyway?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                event.ignore()
                return
            self.runner.cancel()
            self.runner.wait(3000)
        self.viewer.shutdown()
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
    window.viewer.start()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
