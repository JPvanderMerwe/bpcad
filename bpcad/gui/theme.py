"""
One palette and one stylesheet, so every panel looks like the same program.

THE COLOURS ARE NOT INVENTED. They are the ones bitprimitive.com actually
renders, read off the live site rather than eyeballed from a screenshot:
zinc-950 ground, zinc borders, one cyan accent, one green for pass. The app and
the site are the same business, so they are the same colours, to the byte.

Dark by default. This is a tool for looking at renders and height maps, and a
light chrome around a dark viewport makes both harder to read - the eye keeps
re-adapting. The viewport background here is the same colour the CPU rasteriser
uses for its own background, so an embedded 3D view and a rendered PNG sit
together without a seam. Change one and you must change the other.

The chrome is deliberately terminal-flavoured - mono, uppercase, letter-spaced
labels on a near-black ground - because that is what the thing IS. It reports
measurements and refuses bad numbers. Dressing that up as a consumer app would
be lying about it.
"""

from __future__ import annotations

# Matches render.raster's background, deliberately. #09090b as floats.
VIEWPORT_BG = (0.035, 0.035, 0.043)

# bitprimitive.com's ground. Near-black rather than grey: a render is the
# brightest thing on screen and should stay that way.
BG = "#09090b"           # zinc-950, the site's body background
BG_RAISED = "#131316"    # white at 3% over the ground, as the site's cards
BG_INPUT = "#040405"
BORDER = "#27272a"       # zinc-800
BORDER_LIT = "#3f3f46"   # zinc-700, the site's own border colour
TEXT = "#fafafa"
TEXT_DIM = "#a1a1aa"     # zinc-400
TEXT_FAINT = "#71717a"   # zinc-500

# ONE accent, used only for "this is live" and "this is the primary action".
# Spending it on decoration is how an accent stops meaning anything.
ACCENT = "#06b6d4"       # cyan-500, the site's buttons
ACCENT_TEXT = "#22d3ee"  # cyan-400, the site's links and headings
ACCENT_DIM = "#164e5b"
ACCENT_WASH = "rgba(6, 182, 212, 0.10)"   # the site's tinted panels
OK = "#4ade80"           # the site's green, unchanged
WARN = "#fbbf24"
BAD = "#f87171"

MONO = "ui-monospace, 'JetBrains Mono', 'DejaVu Sans Mono', monospace"
UI = "Inter, system-ui, sans-serif"       # the site's typeface

# Terminal-panel labels: small, mono, spaced out, never shouting in white.
LABEL = f"font-family: {MONO}; font-size: 10px; letter-spacing: 1.4px;"

STATUS_COLOUR = {
    "PASS": OK, "ok": OK, "MARGINAL": WARN, "TOO FINE": BAD, "FAIL": BAD,
}

STYLESHEET = f"""
QWidget {{
    background: {BG};
    color: {TEXT};
    font-family: {UI};
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
    padding: 0 6px;
    color: {ACCENT_TEXT};
    font-family: {MONO};
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 1.4px;
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
    font-family: {MONO};
    font-size: 11px;
    letter-spacing: 0.8px;
}}
QPushButton:hover {{ border-color: {BORDER_LIT}; color: {TEXT}; }}
QPushButton:pressed {{ background: {BORDER}; }}
QPushButton:disabled {{ color: {TEXT_DIM}; border-color: {BORDER}; }}
QPushButton[primary="true"] {{
    /* background-color, not background: with a border-radius and a custom
       border Qt does not repaint the fill from the shorthand, so the main
       action rendered as an outline with dark text on a dark ground. */
    background-color: {ACCENT};
    border: 1px solid {ACCENT};
    color: #04141a;
    font-weight: 700;
    letter-spacing: 0.9px;
}}
QPushButton[primary="true"]:hover {{ background-color: {ACCENT_TEXT}; }}
QPushButton[primary="true"]:disabled {{
    background-color: {BORDER}; color: {TEXT_DIM}; border-color: {BORDER};
}}

QTabWidget::pane {{ border: 1px solid {BORDER}; border-radius: 6px; top: -1px; }}
QTabBar::tab {{
    background: transparent;
    padding: 7px 16px;
    border: 1px solid transparent;
    border-bottom: 2px solid transparent;
    color: {TEXT_DIM};
}}
QTabBar::tab:selected {{ color: {ACCENT_TEXT}; border-bottom: 2px solid {ACCENT}; }}
QTabBar::tab {{ font-family: {MONO}; font-size: 10px; letter-spacing: 1.4px; }}
QTabBar::tab:hover {{ color: {TEXT}; }}

QTreeWidget, QTableWidget, QListWidget {{
    background: {BG_INPUT};
    border: 1px solid {BORDER};
    border-radius: 6px;
    alternate-background-color: #0e0e11;
    gridline-color: {BORDER};
}}
QHeaderView::section {{
    background: {BG_RAISED};
    border: none;
    border-bottom: 1px solid {BORDER};
    padding: 6px;
    color: {TEXT_DIM};
    font-family: {MONO};
    font-size: 10px;
    letter-spacing: 1.2px;
    font-weight: 600;
}}
QTreeWidget::item, QTableWidget::item, QListWidget::item {{ padding: 4px; }}
QTreeWidget::item:selected, QTableWidget::item:selected,
QListWidget::item:selected {{ background: {ACCENT}; color: #04141a; }}

QScrollBar:vertical {{ background: transparent; width: 11px; margin: 0; }}
QScrollBar::handle:vertical {{
    background: {BORDER}; border-radius: 5px; min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background: {BORDER_LIT}; }}
QScrollBar:horizontal {{ background: transparent; height: 11px; margin: 0; }}
QScrollBar::handle:horizontal {{
    background: {BORDER}; border-radius: 5px; min-width: 30px;
}}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}

QStatusBar {{
    background: {BG_RAISED};
    border-top: 1px solid {BORDER};
    font-family: {MONO};
    font-size: 11px;
    color: {TEXT_DIM};
}}
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
QMenu::item:selected {{ background: {ACCENT}; color: #04141a; }}
QCheckBox::indicator {{
    width: 15px; height: 15px;
    border: 1px solid {BORDER}; border-radius: 3px; background: {BG_INPUT};
}}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}
"""


def mono(size: int = 12) -> str:
    return f"font-family: {MONO}; font-size: {size}px;"


def primary(button):
    """
    Mark a button as the main action, and make Qt notice.

    Setting a dynamic property does not re-evaluate the stylesheet on its own -
    the selector [primary="true"] is matched at polish time, so a property set
    afterwards leaves the button looking ordinary. Unpolish/polish is the fix,
    and doing it here means no call site has to remember.
    """
    button.setProperty("primary", True)
    button.style().unpolish(button)
    button.style().polish(button)
    return button
