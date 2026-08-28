"""
Parameter forms generated from the schema, not written by hand.

WHY GENERATED
-------------
Every template already declares each parameter's type, units, default, bounds
and description, because the schema is the interface when the model cannot do
the job. Hand-writing a form on top of that would create a second description
of the same thing, and the two would drift the first time a bound changed.

So there is no per-template GUI code. A new template appears here complete, with
its bounds enforced by the spin boxes and its descriptions as tooltips, the
moment it is registered.

Validation is live and per-field: the form asks bpcad.api on every edit and
marks each offending field, rather than stopping at the first problem. A
cross-field rule - "the blades must be narrower than their pitch" - belongs to
no single widget, so it is shown in its own banner underneath.
"""

from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QFrame, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea, QSizePolicy,
    QSpinBox, QVBoxLayout, QWidget,
)

from bpcad import api
from bpcad.gui.theme import ACCENT, BAD, BG_RAISED, OK, TEXT_DIM, WARN, primary

# A spin box needs finite limits even where the schema states none.
FALLBACK_MIN = -1e6
FALLBACK_MAX = 1e6


class ParamRow:
    """
    One parameter: its widget, and how to read and mark it.

    `widget` is the thing that holds the value; `field` is what goes into the
    layout. They differ when the parameter has units, because the unit label
    sits beside the input in a wrapper. Conflating the two is how the units
    silently vanished from every row the first time.
    """

    def __init__(
        self, meta: dict[str, Any], widget: QWidget, label: QLabel,
        field: QWidget | None = None,
    ) -> None:
        self.meta = meta
        self.widget = widget
        self.label = label
        self.field = field if field is not None else widget
        self.name = meta["name"]
        # The full tooltip - description, legal range, real field name - is kept
        # here so that clearing an error restores it. Rebuilding it from the
        # description alone silently threw the bounds away on first validation.
        self.help = widget.toolTip()

    def value(self) -> Any:
        w = self.widget
        if isinstance(w, QCheckBox):
            return w.isChecked()
        if isinstance(w, (QSpinBox, QDoubleSpinBox)):
            # An optional numeric sitting at its minimum means "leave it unset",
            # which is how a derived default gets requested from a spin box.
            if self.meta["optional"] and w.value() == w.minimum():
                return None
            return w.value()
        if isinstance(w, QComboBox):
            return w.currentText()
        text = w.text().strip()
        return text or None

    def mark(self, problem: str | None) -> None:
        self.widget.setProperty("invalid", bool(problem))
        self.widget.style().unpolish(self.widget)
        self.widget.style().polish(self.widget)
        if problem:
            self.label.setStyleSheet("color: %s;" % BAD)
            self.widget.setToolTip("%s\n\n%s" % (problem, self.help))
        else:
            self.label.setStyleSheet("")
            self.widget.setToolTip(self.help)


class SpecForm(QWidget):
    """
    A live-validated form for one template's parameters.

    Emits `changed` whenever the spec would differ, and `validity` with the
    current problem list so a parent can enable or disable a Build button.
    """

    changed = Signal()
    validity = Signal(bool, list)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._rows: dict[str, ParamRow] = {}
        self._template: str | None = None
        self._info: dict[str, Any] | None = None
        self._suspend = False

        # Validation runs on a short delay: revalidating on every keystroke of
        # a four-digit number flashes the field red three times on the way in.
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(180)
        self._debounce.timeout.connect(self._validate)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)

        self._summary = QLabel()
        self._summary.setWordWrap(True)
        self._summary.setStyleSheet("color: %s;" % TEXT_DIM)
        outer.addWidget(self._summary)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        self._holder = QWidget()
        self._form = QFormLayout(self._holder)
        self._form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self._form.setSpacing(7)
        scroll.setWidget(self._holder)
        outer.addWidget(scroll, 1)

        self._banner = QLabel()
        self._banner.setWordWrap(True)
        self._banner.setVisible(False)
        self._banner.setStyleSheet(
            "background: %s; border: 1px solid %s; border-radius: 5px;"
            "padding: 8px; color: %s;" % (BG_RAISED, BAD, BAD)
        )
        outer.addWidget(self._banner)

    # -- building the form -------------------------------------------------

    def set_template(self, name: str) -> None:
        """Rebuild the form for a template. Safe to call repeatedly."""
        if name == self._template:
            return
        self._template = name
        try:
            self._info = api.template_info(name)
        except api.ApiError as exc:
            self._summary.setText(str(exc))
            return

        self._summary.setText(self._info["summary"])
        self._clear()

        for meta in self._info["params"]:
            row = self._make_row(meta)
            self._rows[meta["name"]] = row
            self._form.addRow(row.label, row.field)

        self._validate()

    def _clear(self) -> None:
        self._rows.clear()
        while self._form.count():
            item = self._form.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _make_row(self, meta: dict[str, Any]) -> ParamRow:
        units = meta["units"]
        label_text = meta["name"].removesuffix("_" + units) if units else meta["name"]
        label = QLabel(label_text.replace("_", " "))
        label.setToolTip(meta["name"])

        widget = self._make_widget(meta)
        widget.setToolTip(self._tooltip(meta))

        if units:
            wrapper = QWidget()
            row = QHBoxLayout(wrapper)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(6)
            row.addWidget(widget, 1)
            unit_label = QLabel(units)
            unit_label.setStyleSheet("color: %s;" % TEXT_DIM)
            unit_label.setFixedWidth(26)
            row.addWidget(unit_label)
            wrapper.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            return ParamRow(meta, widget, label, field=wrapper)
        return ParamRow(meta, widget, label)

    def _make_widget(self, meta: dict[str, Any]) -> QWidget:
        bounds = meta["bounds"]
        kind = meta["type"]
        default = meta["default"]

        if kind == "bool":
            box = QCheckBox()
            box.setChecked(bool(default))
            box.toggled.connect(self._touched)
            return box

        if kind in ("int", "float"):
            spin = QSpinBox() if kind == "int" else QDoubleSpinBox()
            lo = bounds.get("ge", bounds.get("gt", FALLBACK_MIN))
            hi = bounds.get("le", bounds.get("lt", FALLBACK_MAX))
            if kind == "float":
                spin.setDecimals(3)
                spin.setSingleStep(0.1)
                # `gt` is exclusive, so step just inside it.
                if "gt" in bounds:
                    lo = bounds["gt"] + 0.001
                if "lt" in bounds:
                    hi = bounds["lt"] - 0.001
            else:
                if "gt" in bounds:
                    lo = bounds["gt"] + 1
                if "lt" in bounds:
                    hi = bounds["lt"] - 1

            if meta["optional"]:
                # One step below the legal floor means "unset, derive it".
                lo = lo - (1 if kind == "int" else 0.001)
                spin.setSpecialValueText("auto")
            spin.setRange(float(lo), float(hi))
            spin.setValue(float(default) if default is not None else float(lo))
            spin.valueChanged.connect(self._touched)
            return spin

        field = QLineEdit()
        if default not in (None, ""):
            field.setText(str(default))
        field.textChanged.connect(self._touched)
        return field

    def _tooltip(self, meta: dict[str, Any]) -> str:
        parts = [meta["description"]] if meta["description"] else []
        bounds = meta["bounds"]
        if bounds:
            shown = ", ".join(
                "%s %g" % ({"ge": ">=", "gt": ">", "le": "<=", "lt": "<"}[k], v)
                for k, v in bounds.items()
            )
            parts.append("legal: %s" % shown)
        if meta["optional"]:
            parts.append("Leave on 'auto' to derive it from the other values.")
        parts.append("field name: %s" % meta["name"])
        return "\n\n".join(parts)

    # -- reading and validating -------------------------------------------

    def params(self) -> dict[str, Any]:
        """Only what the user actually set. Omitted means 'use the default'."""
        out: dict[str, Any] = {}
        for name, row in self._rows.items():
            value = row.value()
            if value is None:
                continue
            if not row.meta["required"] and value == row.meta["default"]:
                continue
            out[name] = value
        return out

    def set_params(self, values: dict[str, Any]) -> None:
        """Load values in from a spec without firing a validation per field."""
        self._suspend = True
        try:
            for name, value in (values or {}).items():
                row = self._rows.get(name)
                if row is None:
                    continue
                w = row.widget
                if isinstance(w, QCheckBox):
                    w.setChecked(bool(value))
                elif isinstance(w, (QSpinBox, QDoubleSpinBox)):
                    w.setValue(float(value))
                elif isinstance(w, QComboBox):
                    w.setCurrentText(str(value))
                else:
                    w.setText("" if value is None else str(value))
        finally:
            self._suspend = False
        self._validate()

    def _touched(self, *_args) -> None:
        if self._suspend:
            return
        self.changed.emit()
        self._debounce.start()

    def _validate(self) -> None:
        if not self._template:
            return
        spec = {
            "name": "preview", "level": 1, "material": "petg",
            "nozzle_mm": 0.4, "layer_mm": 0.2,
            "template": self._template, "params": self.params(),
        }
        problems = api.spec_problems(spec)

        by_field: dict[str, str] = {}
        cross: list[str] = []
        for p in problems:
            field = p.field.removeprefix("params.")
            if field in self._rows:
                by_field[field] = p.problem + (
                    "\n\nlegal: %s" % p.legal if p.legal else ""
                )
            else:
                cross.append(p.problem.replace("Value error, ", ""))

        for name, row in self._rows.items():
            row.mark(by_field.get(name))

        if cross:
            self._banner.setText("\n\n".join(cross))
            self._banner.setVisible(True)
        else:
            self._banner.setVisible(False)

        self.validity.emit(not problems, problems)


class SpecPanel(QWidget):
    """
    The whole no-model path with a face on it: pick a template, fill the form,
    build. This is what makes `bpcad build` usable without touching YAML.
    """

    build_requested = Signal(object)      # PartSpec
    spec_changed = Signal(object)

    def __init__(self, cfg, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._cfg = cfg
        self._valid = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        head = QGroupBox("Part")
        head_form = QFormLayout(head)
        head_form.setSpacing(7)

        self.name_edit = QLineEdit("my_part")
        self.template_box = QComboBox()
        self.template_box.addItems(api.templates())
        self.material_box = QComboBox()
        self.material_box.addItems(cfg.material_names)
        if "petg" in cfg.material_names:
            self.material_box.setCurrentText("petg")

        self.nozzle_spin = QDoubleSpinBox()
        self.nozzle_spin.setDecimals(2)
        self.nozzle_spin.setRange(0.06, 2.0)
        self.nozzle_spin.setSingleStep(0.05)
        self.nozzle_spin.setValue(float(cfg.print_settings["nozzle_mm"]))

        self.layer_spin = QDoubleSpinBox()
        self.layer_spin.setDecimals(2)
        self.layer_spin.setRange(0.02, 1.0)
        self.layer_spin.setSingleStep(0.02)
        self.layer_spin.setValue(float(cfg.print_settings["layer_mm"]))

        head_form.addRow("name", self.name_edit)
        head_form.addRow("template", self.template_box)
        head_form.addRow("material", self.material_box)
        head_form.addRow("nozzle mm", self.nozzle_spin)
        head_form.addRow("layer mm", self.layer_spin)
        layout.addWidget(head)

        params = QGroupBox("Parameters")
        params_layout = QVBoxLayout(params)
        params_layout.setContentsMargins(8, 8, 8, 8)
        self.form = SpecForm()
        params_layout.addWidget(self.form)
        layout.addWidget(params, 1)

        buttons = QHBoxLayout()
        self.status = QLabel("")
        self.status.setStyleSheet("color: %s;" % TEXT_DIM)
        buttons.addWidget(self.status, 1)

        self.explain_btn = QPushButton("Copy as YAML")
        self.build_btn = primary(QPushButton("Build"))
        buttons.addWidget(self.explain_btn)
        buttons.addWidget(self.build_btn)
        layout.addLayout(buttons)

        self.template_box.currentTextChanged.connect(self.form.set_template)
        self.form.validity.connect(self._on_validity)
        self.form.changed.connect(lambda: self.spec_changed.emit(self.spec_dict()))
        self.build_btn.clicked.connect(self._on_build)
        self.explain_btn.clicked.connect(self._copy_yaml)
        for w in (self.name_edit, self.material_box, self.nozzle_spin, self.layer_spin):
            sig = getattr(w, "textChanged", None) or getattr(w, "currentTextChanged", None) \
                or getattr(w, "valueChanged", None)
            sig.connect(lambda *_: self.spec_changed.emit(self.spec_dict()))

        self.form.set_template(self.template_box.currentText())

    def spec_dict(self) -> dict[str, Any]:
        return {
            "name": self.name_edit.text().strip() or "my_part",
            "level": 1,
            "material": self.material_box.currentText(),
            "nozzle_mm": self.nozzle_spin.value(),
            "layer_mm": self.layer_spin.value(),
            "template": self.template_box.currentText(),
            "params": self.form.params(),
        }

    def _on_validity(self, ok: bool, problems: list) -> None:
        self._valid = ok
        self.build_btn.setEnabled(ok)
        if ok:
            self.status.setText("valid")
            self.status.setStyleSheet("color: %s;" % OK)
        else:
            n = len(problems)
            self.status.setText("%d problem%s" % (n, "" if n == 1 else "s"))
            self.status.setStyleSheet("color: %s;" % BAD)

    def _on_build(self) -> None:
        try:
            spec = api.validate_spec(self.spec_dict())
        except api.ApiError as exc:
            self.status.setText(str(exc).splitlines()[0][:80])
            self.status.setStyleSheet("color: %s;" % BAD)
            return
        self.build_requested.emit(spec)

    def _copy_yaml(self) -> None:
        import yaml

        from PySide6.QtWidgets import QApplication

        data = self.spec_dict()
        data["params"] = {k: v for k, v in data["params"].items()}
        QApplication.clipboard().setText(
            yaml.safe_dump(data, sort_keys=False, default_flow_style=False)
        )
        self.status.setText("spec.yaml copied to the clipboard")
        self.status.setStyleSheet("color: %s;" % ACCENT)
