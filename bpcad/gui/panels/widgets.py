"""
Small widgets the studio is built from.

Nothing here knows anything about bpcad. They are a drop target, a card and a
strip of cards, and they are kept apart from the studio so the studio reads as
what it does rather than as widget plumbing.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QFileDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QSizePolicy, QVBoxLayout, QWidget,
)

from bpcad.gui.theme import ACCENT, BAD, BG_INPUT, BG_RAISED, BORDER, OK, TEXT_DIM, WARN

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}


class ImageDrop(QFrame):
    """
    Drop a reference image here, or click to browse.

    Shows the image once it has one, because a thumbnail is the only way to be
    sure you attached the picture you meant to.
    """

    image_chosen = Signal(object)      # Path or None

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setMinimumHeight(132)
        self.setCursor(Qt.PointingHandCursor)
        self._path: Path | None = None
        self._pixmap: QPixmap | None = None
        self._hover = False
        self.setStyleSheet(
            "QFrame { background: %s; border: 1px dashed %s; border-radius: 8px; }"
            % (BG_INPUT, BORDER)
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        self.label = QLabel("Drop a reference image here, or click to browse")
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setWordWrap(True)
        self.label.setStyleSheet("color: %s; border: none;" % TEXT_DIM)
        layout.addWidget(self.label)

        self.clear_btn = QPushButton("Remove")
        self.clear_btn.setVisible(False)
        self.clear_btn.setFixedWidth(80)
        self.clear_btn.clicked.connect(lambda: self.set_image(None))
        layout.addWidget(self.clear_btn, alignment=Qt.AlignRight)

    # -- interaction -------------------------------------------------------

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if event.button() == Qt.LeftButton:
            path, _ = QFileDialog.getOpenFileName(
                self, "Choose a reference image", "",
                "Images (%s)" % " ".join("*" + s for s in sorted(IMAGE_SUFFIXES)),
            )
            if path:
                self.set_image(Path(path))

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if self._urls(event):
            self._hover = True
            self._restyle()
            event.acceptProposedAction()

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self._hover = False
        self._restyle()

    def dropEvent(self, event) -> None:  # noqa: N802
        paths = self._urls(event)
        self._hover = False
        self._restyle()
        if paths:
            self.set_image(paths[0])
            event.acceptProposedAction()

    def _urls(self, event) -> list[Path]:
        data = event.mimeData()
        if not data.hasUrls():
            return []
        out = []
        for url in data.urls():
            p = Path(url.toLocalFile())
            if p.suffix.lower() in IMAGE_SUFFIXES and p.is_file():
                out.append(p)
        return out

    def _restyle(self) -> None:
        colour = ACCENT if self._hover else BORDER
        self.setStyleSheet(
            "QFrame { background: %s; border: 1px dashed %s; border-radius: 8px; }"
            % (BG_INPUT, colour)
        )

    # -- content -----------------------------------------------------------

    @property
    def path(self) -> Path | None:
        return self._path

    def set_image(self, path: Path | None) -> None:
        self._path = path
        if path is None:
            self._pixmap = None
            self.label.setText("Drop a reference image here, or click to browse")
            self.label.setPixmap(QPixmap())
            self.clear_btn.setVisible(False)
        else:
            self._pixmap = QPixmap(str(path))
            self.label.setText("")
            self._rescale()
            self.clear_btn.setVisible(True)
            self.setToolTip(str(path))
        self.image_chosen.emit(path)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._rescale()

    def _rescale(self) -> None:
        if self._pixmap is None or self._pixmap.isNull():
            return
        target = QSize(max(self.width() - 24, 40), max(self.height() - 48, 40))
        self.label.setPixmap(
            self._pixmap.scaled(target, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        )


class VersionCard(QFrame):
    """One version: a thumbnail, what was asked for, and whether it worked."""

    clicked = Signal(int)

    def __init__(self, index: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.index = index
        self._selected = False
        self.setFixedSize(168, 168)
        self.setCursor(Qt.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(7, 7, 7, 7)
        layout.setSpacing(5)

        self.thumb = QLabel()
        self.thumb.setAlignment(Qt.AlignCenter)
        self.thumb.setFixedHeight(104)
        self.thumb.setStyleSheet("border: none; background: transparent;")
        layout.addWidget(self.thumb)

        self.caption = QLabel()
        self.caption.setWordWrap(True)
        self.caption.setStyleSheet("border: none; font-size: 11px;")
        self.caption.setFixedHeight(34)
        layout.addWidget(self.caption)

        self._restyle()

    def set_version(self, version) -> None:
        if version.thumbnail and Path(version.thumbnail).is_file():
            pix = QPixmap(str(version.thumbnail))
            self.thumb.setPixmap(
                pix.scaled(QSize(150, 104), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )
        else:
            self.thumb.setPixmap(QPixmap())
            self.thumb.setText("no render" if version.ok else "failed")
            self.thumb.setStyleSheet(
                "border: none; color: %s;" % (TEXT_DIM if version.ok else BAD)
            )
        colour = OK if version.ok else BAD
        self.caption.setText(version.label)
        self.caption.setStyleSheet(
            "border: none; font-size: 11px; color: %s;" % colour
        )
        self.setToolTip(
            "%s\n\n%s" % (version.label, "\n".join(version.changes) or version.note
                          or version.error or "")
        )

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        self._restyle()

    def _restyle(self) -> None:
        self.setStyleSheet(
            "QFrame { background: %s; border: %s; border-radius: 8px; }"
            % (BG_RAISED,
               "2px solid %s" % ACCENT if self._selected else "1px solid %s" % BORDER)
        )

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.index)


class VersionStrip(QScrollArea):
    """
    The history, left to right, newest last.

    Every version stays: one you abandoned is still what you were looking at
    when you decided to abandon it, and removing it makes "actually, the one
    before" impossible.
    """

    version_selected = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFixedHeight(196)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.NoFrame)

        self._holder = QWidget()
        self._row = QHBoxLayout(self._holder)
        self._row.setContentsMargins(4, 4, 4, 4)
        self._row.setSpacing(9)
        self._row.addStretch(1)
        self.setWidget(self._holder)

        self._cards: list[VersionCard] = []
        self._empty = QLabel("Versions appear here as you go.")
        self._empty.setStyleSheet("color: %s;" % TEXT_DIM)
        self._row.insertWidget(0, self._empty)

    def set_versions(self, versions: list, selected: int = -1) -> None:
        for card in self._cards:
            self._row.removeWidget(card)
            card.deleteLater()
        self._cards.clear()
        self._empty.setVisible(not versions)

        for v in versions:
            card = VersionCard(v.index)
            card.set_version(v)
            card.set_selected(v.index == selected)
            card.clicked.connect(self.version_selected.emit)
            self._row.insertWidget(self._row.count() - 1, card)
            self._cards.append(card)

        if self._cards:
            self.ensureWidgetVisible(self._cards[-1])

    def select(self, index: int) -> None:
        for card in self._cards:
            card.set_selected(card.index == index)


class Pill(QLabel):
    """A small coloured status chip."""

    def __init__(self, text: str = "", colour: str = TEXT_DIM,
                 parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.set(text, colour)

    def set(self, text: str, colour: str = TEXT_DIM) -> None:
        self.setText(text)
        self.setStyleSheet(
            "background: %s; color: %s; border: 1px solid %s;"
            "border-radius: 9px; padding: 2px 9px; font-size: 11px;"
            % (BG_RAISED, colour, colour)
        )
        self.setVisible(bool(text))
