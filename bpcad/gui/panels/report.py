"""
The verify report, shown as tables rather than a wall of text.

Same data as `report.md`, same order, but sortable and colour-coded. The order
is the brief's and it is not arbitrary: envelope first because it answers "will
this fit on the bed", and assumptions and scale departures before the slicer
settings, because a reader who has got what they came for stops reading.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QHeaderView, QLabel, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from bpcad.gui.theme import BAD, OK, STATUS_COLOUR, TEXT_DIM, WARN


def _table(headers: list[str]) -> QTableWidget:
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.verticalHeader().setVisible(False)
    t.setAlternatingRowColors(True)
    t.setEditTriggers(QAbstractItemView.NoEditTriggers)
    t.setSelectionMode(QAbstractItemView.NoSelection)
    t.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
    for i in range(1, len(headers)):
        t.horizontalHeader().setSectionResizeMode(i, QHeaderView.ResizeToContents)
    return t


def _fit(table: QTableWidget) -> None:
    """Size a table to its rows - these are short and should not scroll."""
    rows = table.rowCount()
    height = table.horizontalHeader().height() + 2
    for i in range(rows):
        height += table.rowHeight(i)
    table.setFixedHeight(max(height + 2, 40))


class ReportPanel(QWidget):
    """Everything verify found about the current part."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        self.verdict = QLabel("No part loaded.")
        self.verdict.setStyleSheet("font-size: 15px; font-weight: 600;")
        layout.addWidget(self.verdict)

        self.envelope = _table(["", ""])
        self.envelope.horizontalHeader().setVisible(False)
        layout.addWidget(self._titled("Envelope and volume", self.envelope))

        self.orientation = _table(["", ""])
        self.orientation.horizontalHeader().setVisible(False)
        layout.addWidget(self._titled("Print orientation", self.orientation))

        self.features = _table(["Feature", "Size (mm)", "Status"])
        layout.addWidget(self._titled("Feature sizes against the nozzle", self.features))

        # A bare mesh carries no named features - they come from the template
        # that built it. Say so, rather than showing an empty table that looks
        # like a part with nothing worth checking.
        self.features_note = QLabel(
            "Named feature sizes come from the template that built the part, "
            "not from the mesh. Build from a spec to see them checked against "
            "the nozzle."
        )
        self.features_note.setWordWrap(True)
        self.features_note.setStyleSheet("color: %s;" % TEXT_DIM)
        layout.addWidget(self.features_note)

        self.levels = _table(["Height (mm)", "Area (mm2)"])
        layout.addWidget(self._titled("Surface levels", self.levels))

        self.notes = QLabel("")
        self.notes.setWordWrap(True)
        self.notes.setStyleSheet("color: %s;" % TEXT_DIM)
        layout.addWidget(self.notes)
        layout.addStretch(1)

    def _titled(self, title: str, widget: QWidget) -> QWidget:
        holder = QWidget()
        box = QVBoxLayout(holder)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(4)
        label = QLabel(title)
        label.setStyleSheet("color: %s; font-weight: 600;" % TEXT_DIM)
        box.addWidget(label)
        box.addWidget(widget)
        return holder

    def clear(self) -> None:
        self.verdict.setText("No part loaded.")
        self.verdict.setStyleSheet("font-size: 15px; font-weight: 600;")
        for t in (self.envelope, self.orientation, self.features, self.levels):
            t.setRowCount(0)
            _fit(t)
        self.notes.setText("")

    def show_report(self, report: Any, name: str = "") -> None:
        """Fill every table from a VerifyReport."""
        # Three states, not two. A part that needs support is not broken, and
        # colouring it the same red as a mesh with holes teaches you to ignore
        # the colour.
        if report.problems:
            colour = BAD
        elif report.warnings:
            colour = WARN
        else:
            colour = OK
        self.verdict.setText("%s   %s" % (report.verdict, name or report.path))
        self.verdict.setStyleSheet(
            "font-size: 15px; font-weight: 600; color: %s;" % colour
        )

        m = report.mesh
        self._pairs(self.envelope, [
            ("Envelope", "%.2f x %.2f x %.2f mm" % m.bbox_mm),
            ("Volume", "%.3f cm3" % m.volume_cm3),
            ("Watertight", "yes" if m.watertight else "NO"),
            ("Separate bodies", str(m.body_count)),
            ("Triangles", "%d" % m.face_count),
            ("Degenerate faces", str(m.degenerate_faces)),
        ], flag_rows={2: m.watertight, 5: m.degenerate_faces == 0})

        o = report.overhang
        self._pairs(self.orientation, [
            ("Build direction", report.print_axis.upper()),
            ("Supports needed", "YES" if o.supports_needed else "no"),
            ("Worst overhang", "%.1f deg from vertical" % o.worst_overhang_deg),
            ("Underside past %.0f deg" % o.max_deg, "%.1f mm2" % o.overhang_area_mm2),
            ("...bridged by the layer above", "%.1f mm2" % o.bridged_area_mm2),
            ("...falling further", "%.1f mm2" % o.unsupported_area_mm2),
            ("Bed contact", "%.1f mm2" % o.bed_area_mm2),
        ], flag_rows={1: not o.supports_needed})

        self.features.setRowCount(0)
        self.features_note.setVisible(report.features is None)
        if report.features is not None:
            for c in report.features.checks:
                row = self.features.rowCount()
                self.features.insertRow(row)
                self.features.setItem(row, 0, QTableWidgetItem(c.name))
                value = QTableWidgetItem("%.3f" % c.value_mm)
                value.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.features.setItem(row, 1, value)
                status = QTableWidgetItem(c.status)
                status.setForeground(QColor(STATUS_COLOUR.get(c.status, TEXT_DIM)))
                self.features.setItem(row, 2, status)
        _fit(self.features)

        self.levels.setRowCount(0)
        for lv in report.levels:
            row = self.levels.rowCount()
            self.levels.insertRow(row)
            for col, text in enumerate(("%.3f" % lv.height_mm, "%.2f" % lv.area_mm2)):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.levels.setItem(row, col, item)
        _fit(self.levels)

        notes = list(report.notes)
        if o.unsupported_area_mm2 > 0:
            notes.append(
                "A long drop may still be a bridge anchored on both sides, which "
                "prints fine. This check measures the fall, not the span - look at "
                "the section view before adding supports."
            )
        blocks = []
        if report.problems:
            blocks += ["PROBLEM: " + p for p in report.problems]
        if report.warnings:
            blocks += ["WARNING: " + w for w in report.warnings]
        blocks += notes
        self.notes.setText("\n\n".join(blocks))
        self.notes.setStyleSheet(
            "color: %s;" % (BAD if report.problems else
                            (WARN if report.warnings else TEXT_DIM))
        )

    def _pairs(
        self, table: QTableWidget, rows: list[tuple[str, str]],
        flag_rows: dict[int, bool] | None = None,
    ) -> None:
        flag_rows = flag_rows or {}
        table.setRowCount(0)
        for i, (key, value) in enumerate(rows):
            table.insertRow(i)
            k = QTableWidgetItem(key)
            k.setForeground(QColor(TEXT_DIM))
            table.setItem(i, 0, k)
            v = QTableWidgetItem(value)
            if i in flag_rows:
                v.setForeground(QColor(OK if flag_rows[i] else WARN))
            table.setItem(i, 1, v)
        _fit(table)
