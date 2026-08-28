"""
The home view: one prompt, and everything you have made.

WHAT THIS IS COPYING, AND WHAT IT IS NOT
----------------------------------------
The shape is the one every generative tool has settled on because it works: a
single prompt across the top, a grid of what you have made underneath, click a
card to open it. Nothing else on screen.

What it is NOT copying is the pretence that generation is instant. This runs on
a local CPU at roughly ninety seconds a part, and a spinner that implies
otherwise just makes ninety seconds feel like failure. So the progress readout
names the stage it is actually in - asking, building, verifying - and the log is
one click away rather than filling the window.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QPlainTextEdit, QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from bpcad.gui.panels.widgets import ImageDrop, Pill
from bpcad.gui.theme import (
    ACCENT, BAD, BG_INPUT, BG_RAISED, BORDER, MONO, OK, TEXT, TEXT_DIM, WARN,
    primary,
)


class PartCard(QFrame):
    """One part in the gallery: a render, a name, and how it went."""

    opened = Signal(object)

    def __init__(self, entry, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.entry = entry
        self.setFixedSize(244, 232)
        self.setCursor(Qt.PointingHandCursor)
        self._hover = False
        self._restyle()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(7)

        self.thumb = QLabel()
        self.thumb.setAlignment(Qt.AlignCenter)
        self.thumb.setFixedHeight(146)
        self.thumb.setStyleSheet("border: none; background: transparent;")
        layout.addWidget(self.thumb)

        self.title = QLabel(entry.name)
        self.title.setStyleSheet(
            "border: none; font-size: 14px; font-weight: 600; color: %s;" % TEXT
        )
        layout.addWidget(self.title)

        self.sub = QLabel()
        self.sub.setStyleSheet("border: none; font-size: 11px;")
        layout.addWidget(self.sub)

        self._load()

    def _load(self) -> None:
        e = self.entry
        # Prefer a shaded render, then any picture at all. Keying on a fixed
        # list meant a part rendered under a different name showed as having
        # no image when it had three.
        image = None
        for key in ("thumb", "3q", "preview", "front", "above"):
            if key in e.images:
                image = e.images[key]
                break
        if image is None and e.images:
            image = next(iter(e.images.values()))
        if image and Path(image).is_file():
            pix = QPixmap(str(image))
            self.thumb.setPixmap(
                pix.scaled(QSize(222, 146), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )
        else:
            # "not built" was a lie for a part built from the command line
            # without --render: the STL is there, the picture is not.
            self.thumb.setText("no preview yet" if e.built else "not built")
            self.thumb.setStyleSheet("border: none; color: %s;" % TEXT_DIM)

        if e.is_draft:
            self.sub.setText("needs editing")
            self.sub.setStyleSheet("border: none; font-size: 11px; color: %s;" % WARN)
        elif e.built:
            self.sub.setText("ready")
            self.sub.setStyleSheet("border: none; font-size: 11px; color: %s;" % OK)
        else:
            self.sub.setText("spec only")
            self.sub.setStyleSheet("border: none; font-size: 11px; color: %s;" % TEXT_DIM)

    def enterEvent(self, event) -> None:  # noqa: N802 - Qt naming
        self._hover = True
        self._restyle()

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover = False
        self._restyle()

    def _restyle(self) -> None:
        self.setStyleSheet(
            "QFrame { background: %s; border: 1px solid %s; border-radius: 12px; }"
            % (BG_RAISED, ACCENT if self._hover else BORDER)
        )

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self.opened.emit(self.entry)


class GalleryPanel(QWidget):
    """A prompt, and everything you have made."""

    create_requested = Signal(str, dict)
    cancel_requested = Signal()
    part_opened = Signal(object)

    def __init__(self, cfg, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._cfg = cfg
        self._cards: list[PartCard] = []
        self._measurements: dict[str, Any] | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._build_hero())
        outer.addWidget(self._build_gallery(), 1)

    # -- the prompt --------------------------------------------------------

    def _build_hero(self) -> QWidget:
        hero = QWidget()
        hero.setObjectName("hero")
        # Scoped with an object name on purpose. A stylesheet set on a
        # container applies to that container AND EVERY CHILD, and a
        # widget-level sheet outranks the application one - so an
        # unscoped "background: X" here silently repainted every button
        # inside, including the primary action, which lost its fill.
        hero.setStyleSheet("QWidget#hero { background: %s; }" % BG_RAISED)
        layout = QVBoxLayout(hero)
        layout.setContentsMargins(34, 26, 34, 22)
        layout.setSpacing(12)

        title = QLabel("What do you want to make?")
        title.setStyleSheet("font-size: 23px; font-weight: 600; color: %s;" % TEXT)
        layout.addWidget(title)

        sub = QLabel(
            "Plain language, with the dimensions you know. Everything you leave "
            "out is derived. You get a dimensioned, editable part - not a mesh - "
            "so you can change it afterwards by asking."
        )
        sub.setWordWrap(True)
        sub.setStyleSheet("color: %s; font-size: 12px;" % TEXT_DIM)
        layout.addWidget(sub)

        row = QHBoxLayout()
        row.setSpacing(10)

        self.prompt = QPlainTextEdit()
        self.prompt.setPlaceholderText(
            "a birdhouse 120 mm wide and 140 mm tall with a 32 mm entrance hole"
        )
        self.prompt.setFixedHeight(74)
        self.prompt.setStyleSheet(
            "QPlainTextEdit { background: %s; border: 1px solid %s;"
            "border-radius: 10px; padding: 10px; font-size: 14px; }"
            % (BG_INPUT, BORDER)
        )
        row.addWidget(self.prompt, 1)

        self.image_drop = ImageDrop()
        self.image_drop.setFixedSize(190, 74)
        self.image_drop.label.setText("+ reference image")
        self.image_drop.image_chosen.connect(self._on_image)
        row.addWidget(self.image_drop)

        side = QVBoxLayout()
        side.setSpacing(6)
        self.create_btn = primary(QPushButton("Create"))
        self.create_btn.setFixedSize(126, 40)
        # No inline stylesheet here. Setting one replaces the whole rule for
        # this widget, including the [primary="true"] fill from the app sheet,
        # so the main action silently rendered as an ordinary outlined button.
        side.addWidget(self.create_btn)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setFixedSize(126, 28)
        self.cancel_btn.setVisible(False)
        side.addWidget(self.cancel_btn)
        row.addLayout(side)
        layout.addLayout(row)

        opts = QHBoxLayout()
        opts.setSpacing(8)
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("name (optional)")
        self.name_edit.setFixedWidth(180)
        opts.addWidget(self.name_edit)

        self.material = QComboBox()
        self.material.addItems(self._cfg.material_names)
        if "petg" in self._cfg.material_names:
            self.material.setCurrentText("petg")
        self.material.setFixedWidth(96)
        opts.addWidget(self.material)

        self.view_box = QComboBox()
        self.view_box.addItems(["front view", "side view", "not sure"])
        self.view_box.setFixedWidth(112)
        self.view_box.setToolTip(
            "Which way the photo looks at the thing.\n\n"
            "A front view shows the entrance but looks along a roof slope, so "
            "it cannot measure the pitch. A side view measures the pitch and "
            "cannot see the entrance. Saying which stops it reporting a number "
            "the view could not give."
        )
        self.view_box.currentTextChanged.connect(self._on_image)
        opts.addWidget(self.view_box)

        self.scale_edit = QLineEdit()
        self.scale_edit.setPlaceholderText("image is ? mm wide")
        self.scale_edit.setFixedWidth(150)
        self.scale_edit.setToolTip(
            "An image gives proportions reliably and absolute size never.\n"
            "State how wide the real thing is and the measurements become mm."
        )
        self.scale_edit.editingFinished.connect(self._on_image)
        opts.addWidget(self.scale_edit)

        self.status = Pill("", TEXT_DIM)
        opts.addWidget(self.status)
        opts.addStretch(1)

        self.measured = QLabel("")
        self.measured.setStyleSheet(
            "color: %s; font-family: %s; font-size: 11px;" % (TEXT_DIM, MONO)
        )
        opts.addWidget(self.measured)
        layout.addLayout(opts)

        self.create_btn.clicked.connect(self._on_create)
        self.cancel_btn.clicked.connect(self.cancel_requested.emit)
        return hero

    # -- the gallery -------------------------------------------------------

    def _build_gallery(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        holder = QWidget()
        wrap = QVBoxLayout(holder)
        wrap.setContentsMargins(26, 20, 26, 26)
        wrap.setSpacing(12)

        self.heading = QLabel("Your parts")
        self.heading.setStyleSheet(
            "font-size: 15px; font-weight: 600; color: %s;" % TEXT_DIM
        )
        wrap.addWidget(self.heading)

        self.grid_holder = QWidget()
        self.grid = QGridLayout(self.grid_holder)
        self.grid.setSpacing(14)
        self.grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        wrap.addWidget(self.grid_holder)

        self.empty = QLabel(
            "Nothing yet. Describe something above and press Create.\n\n"
            "It takes about ninety seconds on this machine - local inference, "
            "no cloud, nothing leaves the computer."
        )
        self.empty.setStyleSheet("color: %s; font-size: 13px;" % TEXT_DIM)
        self.empty.setWordWrap(True)
        wrap.addWidget(self.empty)
        wrap.addStretch(1)

        scroll.setWidget(holder)
        return scroll

    def refresh_card(self, name: str, image) -> None:
        """A thumbnail finished rendering. Put it on its card."""
        for card in self._cards:
            if card.entry.name == name:
                card.entry.images["thumb"] = image
                card._load()
                return

    def set_parts(self, entries: list) -> None:
        for card in self._cards:
            self.grid.removeWidget(card)
            card.deleteLater()
        self._cards.clear()

        self.empty.setVisible(not entries)
        self.heading.setVisible(bool(entries))

        columns = 4
        for i, entry in enumerate(entries):
            card = PartCard(entry)
            card.opened.connect(self.part_opened.emit)
            self.grid.addWidget(card, i // columns, i % columns)
            self._cards.append(card)

    # -- state -------------------------------------------------------------

    def _on_image(self, *_args) -> None:
        from bpcad import api

        path = self.image_drop.path
        if path is None:
            self.measured.setText("")
            self._measurements = None
            return
        try:
            width = float(self.scale_edit.text() or 0) or None
        except ValueError:
            width = None
        view = {"front view": "front", "side view": "side"}.get(
            self.view_box.currentText(), "auto"
        )
        try:
            m = api.measure_for_design(path, known_width_mm=width, view=view)
        except api.ApiError as exc:
            self.measured.setText(str(exc)[:70])
            self._measurements = None
            return
        self._measurements = m

        found = [i.name for i in m.items if i.confidence == "fitted"]
        if m.scale_mm_per_px:
            head = "measured %.0f x %.0f mm" % (
                m.silhouette.width * m.scale_mm_per_px,
                m.silhouette.height * m.scale_mm_per_px,
            )
        else:
            head = "aspect %.2f - state a width for mm" % (
                m.silhouette.width / m.silhouette.height
            )
        self.measured.setText(
            head + ("   found: " + ", ".join(found) if found else "")
        )
        self.measured.setToolTip("\n".join(m.summary()))

    @property
    def measurements(self) -> dict[str, Any] | None:
        return self._measurements

    def options(self) -> dict[str, Any]:
        return {
            "material": self.material.currentText(),
            "nozzle_mm": float(self._cfg.print_settings["nozzle_mm"]),
            "layer_mm": float(self._cfg.print_settings["layer_mm"]),
        }

    def _on_create(self) -> None:
        text = self.prompt.toPlainText().strip()
        if not text:
            self.say("say what you want first", WARN)
            return
        self.create_requested.emit(text, self.options())

    def set_busy(self, busy: bool) -> None:
        self.create_btn.setEnabled(not busy)
        self.cancel_btn.setVisible(busy)
        self.prompt.setReadOnly(busy)

    def say(self, text: str, colour: str = TEXT_DIM) -> None:
        self.status.set(text, colour)

    def stage(self, kind: str, payload: Any) -> None:
        """
        Name the stage rather than spin.

        Ninety seconds of a spinner reads as a hang. Ninety seconds of
        "asking the model, attempt 2" reads as work.
        """
        if kind == "profile":
            self.say("asking %s" % payload.model_primary, ACCENT)
        elif kind == "attempt":
            self.say(
                "attempt %d - %s" % (payload.index, "accepted" if payload.ok else "retrying"),
                OK if payload.ok else WARN,
            )
        elif kind == "escalate":
            self.say("no template fits - building from primitives", WARN)
        elif kind == "building":
            self.say("building the geometry", ACCENT)
        elif kind == "cancelled":
            self.say("cancelled", WARN)
