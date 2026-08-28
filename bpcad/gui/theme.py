"""
One palette and one stylesheet, so every panel looks like the same program.

Dark by default. This is a tool for looking at renders and height maps, and a
light chrome around a dark viewport makes both harder to read - the eye keeps
re-adapting. The viewport background here is the same colour the CPU rasteriser
uses for its own background, so an embedded 3D view and a rendered PNG sit
together without a seam.
"""

from __future__ import annotations

# Matches render.raster's background, deliberately.
VIEWPORT_BG = (0.078, 0.086, 0.102)

BG = "#14161a"
BG_RAISED = "#1b1e24"
BG_INPUT = "#0f1114"
BORDER = "#2a2f38"
TEXT = "#e6e8ec"
TEXT_DIM = "#9aa0aa"
ACCENT = "#4aa3df"
OK = "#5bc98c"
WARN = "#e0b050"
BAD = "#e06c6c"
MONO = "ui-monospace, 'JetBrains Mono', 'DejaVu Sans Mono', monospace"

STATUS_COLOUR = {
    "PASS": OK, "ok": OK, "MARGINAL": WARN, "TOO FINE": BAD, "FAIL": BAD,
}

STYLESHEET = f"""
QWidget {{
    background: {BG};
    color: {TEXT};
    font-size: 13px;
}}
QMainWindow::separator {{ background: {BORDER}; width: 1px; height: 1px; }}

QGroupBox {{
    border: 1px solid {BORDER};
    border-radius: 6px;
    margin-top: 10px;
    padding-top: 10px;
    font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
    color: {TEXT_DIM};
    font-weight: 600;
}}

QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background: {BG_INPUT};
    border: 1px solid {BORDER};
    border-radius: 5px;
    padding: 5px 7px;
    selection-background-color: {ACCENT};
}}
QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus,
QDoubleSpinBox:focus, QComboBox:focus {{
    border: 1px solid {ACCENT};
}}
QLineEdit[invalid="true"], QSpinBox[invalid="true"], QDoubleSpinBox[invalid="true"] {{
    border: 1px solid {BAD};
}}
QComboBox::drop-down {{ border: none; width: 18px; }}
QComboBox QAbstractItemView {{
    background: {BG_RAISED};
    border: 1px solid {BORDER};
    selection-background-color: {ACCENT};
}}

QPushButton {{
    background: {BG_RAISED};
    border: 1px solid {BORDER};
    border-radius: 5px;
    padding: 6px 14px;
}}
QPushButton:hover {{ border-color: {ACCENT}; }}
QPushButton:pressed {{ background: {BORDER}; }}
QPushButton:disabled {{ color: {TEXT_DIM}; border-color: {BORDER}; }}
QPushButton[primary="true"] {{
    background: {ACCENT};
    border-color: {ACCENT};
    color: #08121a;
    font-weight: 600;
}}
QPushButton[primary="true"]:hover {{ background: #5fb2e8; }}
QPushButton[primary="true"]:disabled {{ background: {BORDER}; color: {TEXT_DIM}; }}

QTabWidget::pane {{ border: 1px solid {BORDER}; border-radius: 6px; top: -1px; }}
QTabBar::tab {{
    background: transparent;
    padding: 7px 16px;
    border: 1px solid transparent;
    border-bottom: 2px solid transparent;
    color: {TEXT_DIM};
}}
QTabBar::tab:selected {{ color: {TEXT}; border-bottom: 2px solid {ACCENT}; }}
QTabBar::tab:hover {{ color: {TEXT}; }}

QTreeWidget, QTableWidget, QListWidget {{
    background: {BG_INPUT};
    border: 1px solid {BORDER};
    border-radius: 6px;
    alternate-background-color: #12141a;
    gridline-color: {BORDER};
}}
QHeaderView::section {{
    background: {BG_RAISED};
    border: none;
    border-bottom: 1px solid {BORDER};
    padding: 6px;
    color: {TEXT_DIM};
    font-weight: 600;
}}
QTreeWidget::item, QTableWidget::item, QListWidget::item {{ padding: 4px; }}
QTreeWidget::item:selected, QTableWidget::item:selected,
QListWidget::item:selected {{ background: {ACCENT}; color: #08121a; }}

QScrollBar:vertical {{ background: transparent; width: 11px; margin: 0; }}
QScrollBar::handle:vertical {{
    background: {BORDER}; border-radius: 5px; min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background: #3b424e; }}
QScrollBar:horizontal {{ background: transparent; height: 11px; margin: 0; }}
QScrollBar::handle:horizontal {{
    background: {BORDER}; border-radius: 5px; min-width: 30px;
}}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}

QStatusBar {{ background: {BG_RAISED}; border-top: 1px solid {BORDER}; }}
QStatusBar::item {{ border: none; }}
QToolTip {{
    background: {BG_RAISED};
    color: {TEXT};
    border: 1px solid {BORDER};
    padding: 5px;
}}
QProgressBar {{
    background: {BG_INPUT};
    border: 1px solid {BORDER};
    border-radius: 5px;
    text-align: center;
    height: 6px;
}}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 4px; }}
QSplitter::handle {{ background: {BORDER}; }}
QSplitter::handle:horizontal {{ width: 1px; }}
QSplitter::handle:vertical {{ height: 1px; }}
QMenuBar {{ background: {BG_RAISED}; border-bottom: 1px solid {BORDER}; }}
QMenuBar::item:selected {{ background: {BORDER}; }}
QMenu {{ background: {BG_RAISED}; border: 1px solid {BORDER}; }}
QMenu::item:selected {{ background: {ACCENT}; color: #08121a; }}
QCheckBox::indicator {{
    width: 15px; height: 15px;
    border: 1px solid {BORDER}; border-radius: 3px; background: {BG_INPUT};
}}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}
"""


def mono(size: int = 12) -> str:
    return f"font-family: {MONO}; font-size: {size}px;"
