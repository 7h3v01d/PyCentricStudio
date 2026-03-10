"""
pycentric.ui.common.theme
==========================
Single source of truth for the application's visual design.
"""

from __future__ import annotations
from PyQt5.QtGui import QColor, QFont, QPalette
from PyQt5.QtWidgets import QApplication


# ── Colour tokens ─────────────────────────────────────────────────────────────

BG     = "#1e1e1e"
BG2    = "#252526"
BG3    = "#2d2d30"
BORDER = "#3f3f46"
FG     = "#d4d4d4"
FG_DIM = "#858585"

# Syntax / accent
GREEN  = "#4ec994"
BLUE   = "#569cd6"
YELLOW = "#dcdcaa"
ORANGE = "#ce9178"
RED    = "#f44747"
PURPLE = "#c586c0"
CYAN   = "#4fc1ff"
ACCENT = "#007acc"


# ── Fonts ─────────────────────────────────────────────────────────────────────

def editor_font(size: int = 11) -> QFont:
    return QFont("Consolas", size)

def ui_font(size: int = 10) -> QFont:
    return QFont("Segoe UI", size)

def mono_font(size: int = 10) -> QFont:
    return QFont("Consolas", size)


# ── Dark palette ──────────────────────────────────────────────────────────────

def dark_palette() -> QPalette:
    pal = QPalette()
    pal.setColor(QPalette.Window,          QColor(BG))
    pal.setColor(QPalette.WindowText,      QColor(FG))
    pal.setColor(QPalette.Base,            QColor(BG2))
    pal.setColor(QPalette.AlternateBase,   QColor(BG3))
    pal.setColor(QPalette.Text,            QColor(FG))
    pal.setColor(QPalette.Button,          QColor(BG3))
    pal.setColor(QPalette.ButtonText,      QColor(FG))
    pal.setColor(QPalette.Highlight,       QColor(ACCENT))
    pal.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    pal.setColor(QPalette.ToolTipBase,     QColor(BG3))
    pal.setColor(QPalette.ToolTipText,     QColor(FG))
    pal.setColor(QPalette.PlaceholderText, QColor(FG_DIM))
    return pal


# ── Global QSS stylesheet ─────────────────────────────────────────────────────

APP_STYLESHEET = f"""
QMainWindow, QWidget, QDialog {{
    background: {BG}; color: {FG};
    font-family: 'Segoe UI'; font-size: 10pt;
}}
QSplitter::handle {{ background: {BORDER}; width: 1px; height: 1px; }}
QTabWidget::pane {{ border: 1px solid {BORDER}; background: {BG}; }}
QTabBar::tab {{
    background: {BG3}; color: {FG_DIM};
    padding: 5px 14px; border: 1px solid {BORDER};
    border-bottom: none; margin-right: 2px;
}}
QTabBar::tab:selected {{
    background: {BG}; color: {FG};
    border-bottom: 2px solid {ACCENT};
}}
QTabBar::tab:hover {{ background: {BG2}; color: {FG}; }}
QPushButton {{
    background: {BG3}; color: {FG}; border: 1px solid {BORDER};
    border-radius: 3px; padding: 4px 10px;
}}
QPushButton:hover   {{ background: #3a3d41; }}
QPushButton:pressed {{ background: {BG}; }}
QPushButton:disabled {{ color: {FG_DIM}; }}
QLineEdit, QPlainTextEdit, QTextEdit {{
    background: {BG2}; color: {FG}; border: 1px solid {BORDER};
    border-radius: 3px; padding: 2px 4px;
    selection-background-color: {ACCENT};
}}
QComboBox {{
    background: {BG3}; color: {FG}; border: 1px solid {BORDER};
    border-radius: 3px; padding: 3px;
}}
QComboBox QAbstractItemView {{ background: {BG3}; color: {FG}; }}
QTreeView, QTableView, QListWidget {{
    background: {BG2}; color: {FG}; border: 1px solid {BORDER};
    alternate-background-color: {BG3};
    selection-background-color: {ACCENT};
}}
QHeaderView::section {{
    background: {BG3}; color: {FG};
    border: 1px solid {BORDER}; padding: 4px;
}}
QScrollBar:vertical   {{ background: {BG2}; width: 10px; border-radius: 5px; }}
QScrollBar::handle:vertical   {{ background: {BORDER}; border-radius: 5px; min-height: 20px; }}
QScrollBar:horizontal {{ background: {BG2}; height: 10px; border-radius: 5px; }}
QScrollBar::handle:horizontal {{ background: {BORDER}; border-radius: 5px; min-width: 20px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ border: none; background: none; }}
QMenu {{ background: {BG3}; color: {FG}; border: 1px solid {BORDER}; }}
QMenu::item:selected {{ background: {ACCENT}; color: white; }}
QMenu::separator {{ height: 1px; background: {BORDER}; margin: 2px 0; }}
QStatusBar {{ background: {BG3}; color: {FG_DIM}; border-top: 1px solid {BORDER}; }}
QToolBar {{ background: {BG3}; border-bottom: 1px solid {BORDER}; spacing: 3px; padding: 2px; }}
QGroupBox {{
    border: 1px solid {BORDER}; border-radius: 4px;
    margin-top: 8px; padding-top: 4px; color: {FG_DIM};
}}
QGroupBox::title {{ subcontrol-origin: margin; left: 8px; color: {FG}; }}
QCheckBox {{ color: {FG}; spacing: 6px; }}
QLabel {{ color: {FG}; }}
QToolTip {{ background: {BG3}; color: {FG}; border: 1px solid {BORDER}; }}
"""


def apply(app: QApplication) -> None:
    """Apply the dark theme to a QApplication instance."""
    app.setStyle("Fusion")
    app.setFont(ui_font())
    app.setPalette(dark_palette())
    app.setStyleSheet(APP_STYLESHEET)
