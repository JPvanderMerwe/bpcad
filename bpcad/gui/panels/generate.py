"""
The prompt panel: ask, watch it work, get a part.

A run takes about ninety seconds on CPU-only inference, so the important thing
here is not the prompt box - it is the LOG. A progress bar that only spins tells
you nothing; a line per attempt, with the model and the elapsed time and the
reason the last one was rejected, tells you whether to wait or to go and edit
the YAML yourself.

When a run fails it does not just say so. It offers the annotated draft, because
that is the whole point of the handoff: one number usually needs changing.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QTextCursor
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout,
    QLabel, QPlainTextEdit, QProgressBar, QPushButton, QVBoxLayout, QWidget,
)

from bpcad.gui.theme import ACCENT, BAD, MONO, OK, TEXT_DIM, WARN, primary


class GeneratePanel(QWidget):
    """Prompt in, verified bundle out - with the working shown."""

    run_requested = Signal(str, dict)
    cancel_requested = Signal()
    open_draft = Signal(object)

    def __init__(self, cfg, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._cfg = cfg
        self._busy = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        self.prompt = QPlainTextEdit()
        self.prompt.setPlaceholderText(
            "a louvre vent 90 mm wide for a garage door\n\n"
            "Plain language. Give the dimensions you know and leave the rest - "
            "anything you omit is derived from what you did say."
        )
        self.prompt.setFixedHeight(88)
        layout.addWidget(self.prompt)

        options = QGroupBox("Settings")
        grid = QHBoxLayout(options)
        grid.setSpacing(16)

        left = QFormLayout()
        left.setSpacing(6)
        self.material = QComboBox()
        self.material.addItems(cfg.material_names)
        if "petg" in cfg.material_names:
            self.material.setCurrentText("petg")
        self.machine = QComboBox()
        self.machine.addItems(["auto"] + cfg.machine_names)
        left.addRow("material", self.material)
        left.addRow("machine", self.machine)
        grid.addLayout(left)

        right = QFormLayout()
        right.setSpacing(6)
        self.nozzle = QDoubleSpinBox()
        self.nozzle.setDecimals(2)
        self.nozzle.setRange(0.06, 2.0)
        self.nozzle.setSingleStep(0.05)
        self.nozzle.setValue(float(cfg.print_settings["nozzle_mm"]))
        self.layer = QDoubleSpinBox()
        self.layer.setDecimals(2)
        self.layer.setRange(0.02, 1.0)
        self.layer.setSingleStep(0.02)
        self.layer.setValue(float(cfg.print_settings["layer_mm"]))
        right.addRow("nozzle mm", self.nozzle)
        right.addRow("layer mm", self.layer)
        grid.addLayout(right)

        far = QVBoxLayout()
        far.setSpacing(6)
        self.escalate = QCheckBox("Escalate to level 2 if no template fits")
        self.escalate.setChecked(True)
        self.escalate.setToolTip(
            "Composing DSL primitives is a harder job for a small model than "
            "filling in a template, so this is a step down in reliability. It is "
            "worth taking when no template covers the part."
        )
        self.level3 = QCheckBox("Allow raw CadQuery (level 3)")
        self.level3.setToolTip(
            "Off by default. There is no model here that should be trusted to "
            "write raw CadQuery, and anything produced this way is marked "
            "REVIEW REQUIRED."
        )
        far.addWidget(self.escalate)
        far.addWidget(self.level3)
        far.addStretch(1)
        grid.addLayout(far)
        grid.addStretch(1)
        layout.addWidget(options)

        controls = QHBoxLayout()
        self.status = QLabel("Ready.")
        self.status.setStyleSheet("color: %s;" % TEXT_DIM)
        controls.addWidget(self.status, 1)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setEnabled(False)
        self.run_btn = primary(QPushButton("Generate"))
        controls.addWidget(self.cancel_btn)
        controls.addWidget(self.run_btn)
        layout.addLayout(controls)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setStyleSheet("font-family: %s; font-size: 12px;" % MONO)
        layout.addWidget(self.log, 1)

        self.draft_btn = QPushButton("Open the annotated draft")
        self.draft_btn.setVisible(False)
        layout.addWidget(self.draft_btn)

        self.run_btn.clicked.connect(self._on_run)
        self.cancel_btn.clicked.connect(self._on_cancel)
        self.draft_btn.clicked.connect(lambda: self.open_draft.emit(self._draft))
        self._draft: Path | None = None

    # -- options -----------------------------------------------------------

    def options(self) -> dict[str, Any]:
        machine = self.machine.currentText()
        return {
            "machine": None if machine == "auto" else machine,
            "material": self.material.currentText(),
            "nozzle_mm": self.nozzle.value(),
            "layer_mm": self.layer.value(),
            "escalate": self.escalate.isChecked(),
            "allow_level_3": self.level3.isChecked(),
            "render": True,
        }

    # -- running -----------------------------------------------------------

    def _on_run(self) -> None:
        text = self.prompt.toPlainText().strip()
        if not text:
            self.say("Type what you want first.", WARN)
            return
        self.log.clear()
        self._draft = None
        self.draft_btn.setVisible(False)
        self.run_requested.emit(text, self.options())

    def _on_cancel(self) -> None:
        self.say("Stopping after the current attempt...", WARN)
        self.cancel_requested.emit()

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.run_btn.setEnabled(not busy)
        self.cancel_btn.setEnabled(busy)
        self.progress.setVisible(busy)
        self.prompt.setReadOnly(busy)

    def say(self, text: str, colour: str = TEXT_DIM) -> None:
        self.status.setText(text)
        self.status.setStyleSheet("color: %s;" % colour)

    def append(self, text: str) -> None:
        self.log.appendPlainText(text)
        self.log.moveCursor(QTextCursor.End)

    # -- events from the worker -------------------------------------------

    def on_event(self, kind: str, payload: Any) -> None:
        if kind == "profile":
            self.append(payload.describe())
            self.append("")
            self.say("Asking %s..." % payload.model_primary, ACCENT)
        elif kind == "attempt":
            self.append(payload.summary())
            self.say(
                "attempt %d %s (%.0fs)"
                % (payload.index, "ok" if payload.ok else "rejected", payload.elapsed_s),
                OK if payload.ok else WARN,
            )
        elif kind == "escalate":
            self.append("")
            self.append("level 1 exhausted - escalating to level 2 (DSL primitives)")
            self.append("")
            self.say("Escalating to level 2...", WARN)
        elif kind == "building":
            self.say("Building geometry...", ACCENT)
        elif kind == "cancelled":
            self.append("")
            self.append("cancelled")
            self.say("Cancelled.", WARN)

    def on_result(self, result: Any) -> None:
        self.append("")
        self.append("%d attempt(s), %.1fs total" % (result.attempt_count, result.elapsed_s))
        if result.ok and result.part:
            p = result.part
            self.append("")
            self.append("%s   %.2f x %.2f x %.2f mm   %.3f cm3   %d body(s)"
                        % (p.name, *p.envelope_mm, p.volume_cm3, p.report.mesh.body_count))
            self.append("supports needed: %s" % ("YES" if p.needs_supports else "no"))
            self.say("Done - %s built and verified." % p.name, OK)
        else:
            self.append("")
            self.append(result.message)
            self.say("The model could not do it.", BAD)
            if result.draft_path:
                self._draft = Path(result.draft_path)
                self.draft_btn.setText(
                    "Open %s - every problem is marked inline"
                    % self._draft.name
                )
                self.draft_btn.setVisible(True)

    def on_error(self, message: str, trace: str) -> None:
        self.append("")
        self.append(message)
        self.say(message.splitlines()[0][:90], BAD)
