"""
The studio: describe a part, look at it, say what is wrong, look again.

THE UNIT OF WORK IS A PART, NOT A PROMPT.
You do not usually get what you want first time, and re-rolling from scratch
loses everything that was already right. So each turn edits the SPEC of the part
you are looking at, and the part is rebuilt from that. "Make it 10 mm wider" is
an exact parameter change followed by a deterministic build, not a fresh roll of
the dice - which is the whole reason this is worth building on a parametric
pipeline rather than a generative mesh one.

Every version stays. Because a version is a spec and not a mesh, going back is
exact, and any version in the strip is independently printable.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QFrame, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QProgressBar, QPushButton,
    QSizePolicy, QSplitter, QVBoxLayout, QWidget,
)

from bpcad.gui.panels.widgets import ImageDrop, Pill, VersionStrip
from bpcad.gui.theme import ACCENT, BAD, MONO, OK, TEXT_DIM, WARN


class StudioPanel(QWidget):
    """Prompt, reference image, version history, and the refinement box."""

    create_requested = Signal(str, dict)        # prompt, options
    refine_requested = Signal(str, dict)        # instruction, options
    cancel_requested = Signal()
    version_selected = Signal(int)
    build_version_requested = Signal(int)

    def __init__(self, cfg, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._cfg = cfg
        self._has_part = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        split = QSplitter(Qt.Vertical)
        split.addWidget(self._build_top())
        split.addWidget(self._build_log())
        split.setSizes([620, 190])
        outer.addWidget(split)

    # -- construction ------------------------------------------------------

    def _build_top(self) -> QWidget:
        holder = QWidget()
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(12, 12, 12, 8)
        layout.setSpacing(10)

        # --- describe it ---------------------------------------------------
        self.prompt = QPlainTextEdit()
        self.prompt.setPlaceholderText(
            "Describe the part you want.\n\n"
            "a louvre vent 90 mm wide for a garage door\n\n"
            "Give the dimensions you know and leave the rest - anything you do "
            "not mention is derived from what you did."
        )
        self.prompt.setFixedHeight(92)
        layout.addWidget(self.prompt)

        row = QHBoxLayout()
        row.setSpacing(10)

        self.image_drop = ImageDrop()
        self.image_drop.setFixedWidth(230)
        self.image_drop.image_chosen.connect(self._on_image)
        row.addWidget(self.image_drop)

        settings = QGroupBox("Settings")
        form = QFormLayout(settings)
        form.setSpacing(6)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("named from the prompt")

        self.material = QComboBox()
        self.material.addItems(self._cfg.material_names)
        if "petg" in self._cfg.material_names:
            self.material.setCurrentText("petg")

        self.machine = QComboBox()
        self.machine.addItems(["auto"] + self._cfg.machine_names)

        self.nozzle = QDoubleSpinBox()
        self.nozzle.setDecimals(2); self.nozzle.setRange(0.06, 2.0)
        self.nozzle.setSingleStep(0.05)
        self.nozzle.setValue(float(self._cfg.print_settings["nozzle_mm"]))

        self.layer = QDoubleSpinBox()
        self.layer.setDecimals(2); self.layer.setRange(0.02, 1.0)
        self.layer.setSingleStep(0.02)
        self.layer.setValue(float(self._cfg.print_settings["layer_mm"]))

        self.known_width = QDoubleSpinBox()
        self.known_width.setDecimals(1); self.known_width.setRange(0.0, 2000.0)
        self.known_width.setSpecialValueText("not stated")
        self.known_width.setValue(0.0)
        self.known_width.setToolTip(
            "An image gives proportions reliably and absolute size never.\n\n"
            "State how wide the real thing is and every measurement becomes "
            "millimetres. Leave it unstated and only the proportions are used."
        )
        self.known_width.valueChanged.connect(self._remeasure)

        form.addRow("name", self.name_edit)
        form.addRow("material", self.material)
        form.addRow("machine", self.machine)
        form.addRow("nozzle mm", self.nozzle)
        form.addRow("layer mm", self.layer)
        form.addRow("image is ? mm wide", self.known_width)
        row.addWidget(settings, 1)

        measured = QGroupBox("Measured from the image")
        m_layout = QVBoxLayout(measured)
        self.measured_label = QLabel("No reference image.")
        self.measured_label.setWordWrap(True)
        self.measured_label.setAlignment(Qt.AlignTop)
        self.measured_label.setStyleSheet(
            "color: %s; font-family: %s; font-size: 11px;" % (TEXT_DIM, MONO)
        )
        m_layout.addWidget(self.measured_label)
        measured.setFixedWidth(280)
        row.addWidget(measured)
        layout.addLayout(row)

        # --- go --------------------------------------------------------------
        controls = QHBoxLayout()
        self.status = Pill("Ready", TEXT_DIM)
        controls.addWidget(self.status)
        controls.addStretch(1)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setEnabled(False)
        self.create_btn = QPushButton("Create")
        self.create_btn.setProperty("primary", True)
        self.create_btn.setMinimumWidth(120)
        controls.addWidget(self.cancel_btn)
        controls.addWidget(self.create_btn)
        layout.addLayout(controls)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        # --- versions --------------------------------------------------------
        vlabel = QLabel("Versions")
        vlabel.setStyleSheet("color: %s; font-weight: 600;" % TEXT_DIM)
        layout.addWidget(vlabel)
        self.strip = VersionStrip()
        self.strip.version_selected.connect(self.version_selected.emit)
        layout.addWidget(self.strip)

        # --- change it -------------------------------------------------------
        self.refine_box = QGroupBox("Not right? Say what to change")
        rlayout = QVBoxLayout(self.refine_box)
        rlayout.setSpacing(7)

        self.refine_edit = QPlainTextEdit()
        self.refine_edit.setPlaceholderText(
            "make it 20 mm wider\n"
            "the blades are too thin\n"
            "use three blades instead\n"
            "thicker walls, this is going outdoors"
        )
        self.refine_edit.setFixedHeight(66)
        rlayout.addWidget(self.refine_edit)

        rrow = QHBoxLayout()
        self.changes_label = QLabel("")
        self.changes_label.setWordWrap(True)
        self.changes_label.setStyleSheet(
            "color: %s; font-family: %s; font-size: 11px;" % (TEXT_DIM, MONO)
        )
        rrow.addWidget(self.changes_label, 1)
        self.refine_btn = QPushButton("Apply change")
        self.refine_btn.setProperty("primary", True)
        self.refine_btn.setMinimumWidth(120)
        rrow.addWidget(self.refine_btn)
        rlayout.addLayout(rrow)

        self.refine_box.setEnabled(False)
        layout.addWidget(self.refine_box)

        self.create_btn.clicked.connect(self._on_create)
        self.refine_btn.clicked.connect(self._on_refine)
        self.cancel_btn.clicked.connect(self._on_cancel)
        return holder

    def _build_log(self) -> QWidget:
        holder = QWidget()
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(12, 4, 12, 10)
        layout.setSpacing(4)
        label = QLabel("What the model is doing")
        label.setStyleSheet("color: %s; font-weight: 600;" % TEXT_DIM)
        layout.addWidget(label)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setStyleSheet("font-family: %s; font-size: 12px;" % MONO)
        layout.addWidget(self.log, 1)
        return holder

    # -- image -------------------------------------------------------------

    def _on_image(self, path: Path | None) -> None:
        self._remeasure()

    def _remeasure(self) -> None:
        from bpcad import api

        path = self.image_drop.path
        if path is None:
            self.measured_label.setText("No reference image.")
            self._measurements = None
            return
        width = self.known_width.value() or None
        try:
            m = api.measure_reference(path, known_width_mm=width)
        except api.ApiError as exc:
            self.measured_label.setText(str(exc))
            self._measurements = None
            return
        self._measurements = m
        self.measured_label.setText(
            "\n".join("%-22s %s" % (k, v) for k, v in m.items() if k != "note")
            + "\n\n" + m.get("note", "")
        )

    @property
    def measurements(self) -> dict[str, Any] | None:
        return getattr(self, "_measurements", None)

    # -- options -----------------------------------------------------------

    def options(self) -> dict[str, Any]:
        machine = self.machine.currentText()
        return {
            "machine": None if machine == "auto" else machine,
            "material": self.material.currentText(),
            "nozzle_mm": self.nozzle.value(),
            "layer_mm": self.layer.value(),
        }

    # -- actions -----------------------------------------------------------

    def _on_create(self) -> None:
        text = self.prompt.toPlainText().strip()
        if not text:
            self.say("Describe what you want first", WARN)
            return
        self.log.clear()
        self.create_requested.emit(text, self.options())

    def _on_refine(self) -> None:
        text = self.refine_edit.toPlainText().strip()
        if not text:
            self.say("Say what should change", WARN)
            return
        self.refine_requested.emit(text, self.options())

    def _on_cancel(self) -> None:
        self.say("Stopping after this attempt", WARN)
        self.cancel_requested.emit()

    # -- state -------------------------------------------------------------

    def set_busy(self, busy: bool) -> None:
        self.create_btn.setEnabled(not busy)
        self.refine_btn.setEnabled(not busy and self._has_part)
        self.cancel_btn.setEnabled(busy)
        self.progress.setVisible(busy)
        self.prompt.setReadOnly(busy)
        self.refine_edit.setReadOnly(busy)

    def set_has_part(self, has: bool) -> None:
        self._has_part = has
        self.refine_box.setEnabled(has)
        self.refine_btn.setEnabled(has)
        self.create_btn.setText("Create" if not has else "Start over")

    def say(self, text: str, colour: str = TEXT_DIM) -> None:
        self.status.set(text, colour)

    def append(self, text: str) -> None:
        self.log.appendPlainText(text)
        self.log.moveCursor(QTextCursor.End)

    def set_versions(self, versions: list, selected: int = -1) -> None:
        self.strip.set_versions(versions, selected)

    def show_changes(self, changes: list[str], note: str = "") -> None:
        parts = list(changes)
        if note:
            parts.append('the model says: "%s"' % note.strip())
        self.changes_label.setText("\n".join(parts) if parts else "")

    # -- worker events -----------------------------------------------------

    def on_event(self, kind: str, payload: Any) -> None:
        if kind == "profile":
            self.append(payload.describe())
            self.append("")
            self.say("thinking", ACCENT)
        elif kind == "attempt":
            self.append(payload.summary())
            self.say(
                "attempt %d %s" % (payload.index, "ok" if payload.ok else "rejected"),
                OK if payload.ok else WARN,
            )
        elif kind == "escalate":
            self.append("")
            self.append("no template fits - trying primitive operations instead")
            self.say("escalating", WARN)
        elif kind == "building":
            self.say("building the geometry", ACCENT)
        elif kind == "cancelled":
            self.append("cancelled")
            self.say("cancelled", WARN)
