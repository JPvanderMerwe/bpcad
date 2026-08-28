"""
The part view: one part, large, with everything else out of the way.

The viewer takes the window. The version history sits under it as a strip of
renders, the "what should change" box sits under that, and the technical
detail - the report, the spec, the model's working - is behind a drawer you
open when you want it.

That ordering is the argument. What you are doing is looking at a part and
deciding whether it is right. Feature-size tables and validator output matter
when the answer is no, and are noise when the answer is yes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QProgressBar, QPushButton,
    QScrollArea, QSizePolicy, QSplitter, QStackedWidget, QTabWidget,
    QVBoxLayout, QWidget,
)

from bpcad.gui.panels.report import ReportPanel
from bpcad.gui.panels.widgets import Pill, VersionStrip
from bpcad.gui.theme import (
    ACCENT, BAD, BG, BG_INPUT, BG_RAISED, BORDER, MONO, OK, TEXT, TEXT_DIM, WARN,
    primary,
)
from bpcad.gui.viewer3d import VIEW_DIRECTIONS, Viewer3D


class ImageView(QScrollArea):
    """A rendered PNG, scaled to fit and re-scaled when the panel resizes."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setAlignment(Qt.AlignCenter)
        self.setFrameShape(QFrame.NoFrame)
        self._label = QLabel("No image.")
        self._label.setAlignment(Qt.AlignCenter)
        self._label.setStyleSheet("color: %s;" % TEXT_DIM)
        self.setWidget(self._label)
        self._pixmap = None

    def show_image(self, path) -> None:
        from PySide6.QtGui import QPixmap

        if path is None or not Path(path).is_file():
            self._pixmap = None
            self._label.setText("Not rendered.")
            self._label.setPixmap(QPixmap())
            return
        self._pixmap = QPixmap(str(path))
        self._rescale()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._rescale()

    def _rescale(self) -> None:
        if self._pixmap is None or self._pixmap.isNull():
            return
        self._label.setPixmap(
            self._pixmap.scaled(
                self.viewport().size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
        )


class PartView(QWidget):
    """One part, its versions, and a box to say what should change."""

    back_requested = Signal()
    refine_requested = Signal(str)
    cancel_requested = Signal()
    version_selected = Signal(int)
    export_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._drawer_open = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._build_bar())

        split = QSplitter(Qt.Horizontal)
        split.addWidget(self._build_stage())
        split.addWidget(self._build_drawer())
        split.setSizes([1080, 0])
        self._split = split
        outer.addWidget(split, 1)

    # -- the top bar -------------------------------------------------------

    def _build_bar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("topbar")
        bar.setFixedHeight(52)
        # Scoped with an object name on purpose. A stylesheet set on a
        # container applies to that container AND EVERY CHILD, and a
        # widget-level sheet outranks the application one - so an
        # unscoped "background: X" here silently repainted every button
        # inside, including the primary action, which lost its fill.
        bar.setStyleSheet(
            "QWidget#topbar { background: %s; border-bottom: 1px solid %s; }"
            % (BG_RAISED, BORDER)
        )
        row = QHBoxLayout(bar)
        row.setContentsMargins(14, 8, 14, 8)
        row.setSpacing(10)

        self.back_btn = QPushButton("←  All parts")
        self.back_btn.setFixedWidth(112)
        self.back_btn.clicked.connect(self.back_requested.emit)
        row.addWidget(self.back_btn)

        self.title = QLabel("")
        self.title.setStyleSheet("font-size: 16px; font-weight: 600; color: %s;" % TEXT)
        row.addWidget(self.title)

        self.verdict = Pill("", TEXT_DIM)
        row.addWidget(self.verdict)

        self.facts = QLabel("")
        self.facts.setStyleSheet(
            "color: %s; font-family: %s; font-size: 11px;" % (TEXT_DIM, MONO)
        )
        row.addWidget(self.facts)
        row.addStretch(1)

        self.mode_btn = QPushButton("Shaded")
        self.mode_btn.setFixedWidth(120)
        self.mode_btn.setToolTip(
            "Shading cannot show a recess whose floor faces the same way as the "
            "surface around it. Colour by height can."
        )
        row.addWidget(self.mode_btn)

        self.source_btn = QPushButton("Renders")
        self.source_btn.setFixedWidth(96)
        row.addWidget(self.source_btn)

        self.export_btn = QPushButton("Export")
        self.export_btn.clicked.connect(self.export_requested.emit)
        row.addWidget(self.export_btn)

        self.drawer_btn = QPushButton("Details  ›")
        self.drawer_btn.setFixedWidth(104)
        self.drawer_btn.clicked.connect(self.toggle_drawer)
        row.addWidget(self.drawer_btn)

        self.mode_btn.clicked.connect(self._toggle_mode)
        self.source_btn.clicked.connect(self._toggle_source)
        return bar

    # -- the stage ---------------------------------------------------------

    def _build_stage(self) -> QWidget:
        stage = QWidget()
        layout = QVBoxLayout(stage)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.stack = QStackedWidget()
        self.viewer = Viewer3D()
        self.images = ImageView()
        self.stack.addWidget(self.viewer)
        self.stack.addWidget(self.images)
        layout.addWidget(self.stack, 1)

        views = QWidget()
        views.setObjectName("viewbar")
        views.setFixedHeight(38)
        views.setStyleSheet("QWidget#viewbar { background: %s; }" % BG)
        vrow = QHBoxLayout(views)
        vrow.setContentsMargins(14, 4, 14, 4)
        vrow.setSpacing(6)
        self._view_buttons = {}
        for name in ("3q", "front", "right", "above"):
            b = QPushButton(name)
            b.setFixedWidth(66)
            b.clicked.connect(lambda _=False, n=name: self._set_view(n))
            vrow.addWidget(b)
            self._view_buttons[name] = b
        fit = QPushButton("fit")
        fit.setFixedWidth(52)
        fit.clicked.connect(lambda: self.viewer.reset_camera())
        vrow.addWidget(fit)
        vrow.addStretch(1)

        self.image_label = QLabel("")
        self.image_label.setStyleSheet("color: %s; font-size: 11px;" % TEXT_DIM)
        vrow.addWidget(self.image_label)
        layout.addWidget(views)

        strip_label = QLabel("VERSIONS")
        strip_label.setStyleSheet(
            "color: %s; font-size: 10px; font-weight: 700; letter-spacing: 1px;"
            "padding: 8px 14px 2px 14px; background: %s;" % (TEXT_DIM, BG)
        )
        layout.addWidget(strip_label)

        self.strip = VersionStrip()
        self.strip.setObjectName("strip")
        self.strip.setStyleSheet("QScrollArea#strip { background: %s; }" % BG)
        self.strip.version_selected.connect(self.version_selected.emit)
        layout.addWidget(self.strip)

        layout.addWidget(self._build_refine())
        return stage

    def _build_refine(self) -> QWidget:
        holder = QWidget()
        holder.setObjectName("refinebar")
        holder.setStyleSheet(
            "QWidget#refinebar { background: %s; border-top: 1px solid %s; }"
            % (BG_RAISED, BORDER)
        )
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(14, 10, 14, 12)
        layout.setSpacing(7)

        self.changes = QLabel("")
        self.changes.setWordWrap(True)
        self.changes.setStyleSheet(
            "color: %s; font-family: %s; font-size: 11px;" % (TEXT_DIM, MONO)
        )
        layout.addWidget(self.changes)

        row = QHBoxLayout()
        row.setSpacing(9)
        self.refine_edit = QPlainTextEdit()
        self.refine_edit.setPlaceholderText(
            "Not right? Say what to change  -  make the walls 4 mm  /  "
            "raise the entrance  /  taller roof overhang"
        )
        self.refine_edit.setFixedHeight(58)
        self.refine_edit.setStyleSheet(
            "QPlainTextEdit { background: %s; border: 1px solid %s;"
            "border-radius: 9px; padding: 8px; font-size: 13px; }"
            % (BG_INPUT, BORDER)
        )
        row.addWidget(self.refine_edit, 1)

        side = QVBoxLayout()
        side.setSpacing(5)
        self.refine_btn = primary(QPushButton("Apply"))
        self.refine_btn.setFixedSize(112, 34)
        # No inline stylesheet - see gallery.py. It would replace the fill.
        self.refine_btn.clicked.connect(self._on_refine)
        side.addWidget(self.refine_btn)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setFixedSize(112, 22)
        self.cancel_btn.setVisible(False)
        self.cancel_btn.clicked.connect(self.cancel_requested.emit)
        side.addWidget(self.cancel_btn)
        row.addLayout(side)
        layout.addLayout(row)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        self.status = QLabel("")
        self.status.setStyleSheet("color: %s; font-size: 11px;" % TEXT_DIM)
        layout.addWidget(self.status)
        return holder

    # -- the drawer --------------------------------------------------------

    def _build_drawer(self) -> QWidget:
        self.tabs = QTabWidget()
        self.tabs.setMinimumWidth(0)

        self.report = ReportPanel()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(self.report)
        self.tabs.addTab(scroll, "Checks")

        self.spec_text = QPlainTextEdit()
        self.spec_text.setReadOnly(True)
        self.spec_text.setStyleSheet("font-family: %s; font-size: 12px;" % MONO)
        self.tabs.addTab(self.spec_text, "spec.yaml")

        self.markdown = QPlainTextEdit()
        self.markdown.setReadOnly(True)
        self.tabs.addTab(self.markdown, "report.md")

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setStyleSheet("font-family: %s; font-size: 11px;" % MONO)
        self.tabs.addTab(self.log, "Model")
        return self.tabs

    def toggle_drawer(self) -> None:
        self._drawer_open = not self._drawer_open
        total = max(self._split.width(), 900)
        if self._drawer_open:
            self._split.setSizes([int(total * 0.63), int(total * 0.37)])
            self.drawer_btn.setText("Details  ‹")
        else:
            self._split.setSizes([total, 0])
            self.drawer_btn.setText("Details  ›")

    def open_drawer(self, tab: int = 0) -> None:
        if not self._drawer_open:
            self.toggle_drawer()
        self.tabs.setCurrentIndex(tab)

    # -- viewing -----------------------------------------------------------

    def _set_view(self, name: str) -> None:
        if name in VIEW_DIRECTIONS:
            self.viewer.set_view(name)

    def _toggle_mode(self) -> None:
        height = self.viewer.mode != "height"
        self.viewer.set_mode("height" if height else "shaded")
        self.mode_btn.setText("Colour by height" if height else "Shaded")

    def _toggle_source(self) -> None:
        showing_images = self.stack.currentIndex() == 0
        self.stack.setCurrentIndex(1 if showing_images else 0)
        self.source_btn.setText("3D" if showing_images else "Renders")
        for b in self._view_buttons.values():
            b.setVisible(not showing_images)
        if showing_images:
            self._cycle_image()

    def _cycle_image(self) -> None:
        if not self._images:
            self.images.show_image(None)
            self.image_label.setText("nothing rendered")
            return
        keys = list(self._images)
        self._image_index = (getattr(self, "_image_index", -1) + 1) % len(keys)
        key = keys[self._image_index]
        self.images.show_image(self._images[key])
        self.image_label.setText("%s  (click Renders again to cycle)" % key)

    # -- content -----------------------------------------------------------

    def show_part(self, name: str, part, images: dict, spec_text: str = "",
                  report_md: str = "") -> None:
        self._images = dict(images or {})
        self._image_index = -1
        self.title.setText(name)

        if part is None:
            self.viewer.clear()
            self.report.clear()
            self.facts.setText("")
            self.verdict.set("not built", WARN)
            self.spec_text.setPlainText(spec_text)
            return

        self.viewer.load(part.stl)
        m = part.report.mesh
        self.facts.setText(
            "%.0f x %.0f x %.0f mm    %.0f cm3    %d %s    %.0f%% solid"
            % (*m.bbox_mm, m.volume_cm3, m.body_count,
               "body" if m.body_count == 1 else "bodies", 100 * m.solidity)
        )
        if part.report.problems:
            self.verdict.set("FAIL", BAD)
        elif part.report.warnings:
            self.verdict.set("pass, with warnings", WARN)
        else:
            self.verdict.set("pass", OK)

        self.report.show_report(part.report, name)
        self.spec_text.setPlainText(spec_text)
        self.markdown.setPlainText(report_md)

    def set_versions(self, versions: list, selected: int = -1) -> None:
        self.strip.set_versions(versions, selected)

    def show_changes(self, changes: list, note: str = "") -> None:
        parts = list(changes)
        if note:
            parts.append('model: "%s"' % note.strip())
        self.changes.setText("   ".join(parts) if parts else "")

    def set_busy(self, busy: bool) -> None:
        self.refine_btn.setEnabled(not busy)
        self.cancel_btn.setVisible(busy)
        self.progress.setVisible(busy)
        self.refine_edit.setReadOnly(busy)

    def say(self, text: str, colour: str = TEXT_DIM) -> None:
        self.status.setText(text)
        self.status.setStyleSheet("color: %s; font-size: 11px;" % colour)

    def append(self, text: str) -> None:
        self.log.appendPlainText(text)
        self.log.moveCursor(QTextCursor.End)

    def _on_refine(self) -> None:
        text = self.refine_edit.toPlainText().strip()
        if not text:
            self.say("say what should change", WARN)
            return
        self.refine_requested.emit(text)

    def on_event(self, kind: str, payload: Any) -> None:
        if kind == "profile":
            self.append(payload.describe())
            self.say("asking %s" % payload.model_primary, ACCENT)
        elif kind == "attempt":
            self.append(payload.summary())
            self.say(
                "attempt %d - %s" % (payload.index, "accepted" if payload.ok else "retrying"),
                OK if payload.ok else WARN,
            )
        elif kind == "building":
            self.say("building the geometry", ACCENT)
        elif kind == "escalate":
            self.append("no template fits - building from primitives")
            self.say("building from primitives", WARN)
        elif kind == "cancelled":
            self.say("cancelled", WARN)
