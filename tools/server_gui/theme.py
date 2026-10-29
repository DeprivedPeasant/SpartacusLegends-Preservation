#!/usr/bin/env python3
"""Visual theme: colour tokens, the application stylesheet, and status glyphs.

Two themes share one stylesheet template: a dark charcoal-and-bronze "arena"
theme (the default) and a light parchment variant. Widgets opt into styles
through Qt properties (``card``, ``role``, ``variant``) instead of hard-coded
colours, so every page stays consistent.

Status is never conveyed by colour alone: each server state has its own glyph
shape and its own word, and the word is always shown.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication, QWidget


@dataclass(frozen=True)
class Theme:
    name: str
    window: str
    sidebar: str
    surface: str
    surface_alt: str
    border: str
    text: str
    muted: str
    accent: str
    accent_hover: str
    accent_text: str
    danger: str
    danger_hover: str
    selection: str
    field: str
    log: str


DARK = Theme(
    name="dark",
    window="#15171c",
    sidebar="#101216",
    surface="#1e2128",
    surface_alt="#252933",
    border="#323745",
    text="#ece8e1",
    muted="#9ba1ad",
    accent="#c8963e",
    accent_hover="#dcab52",
    accent_text="#16130d",
    danger="#a8453f",
    danger_hover="#bf5650",
    selection="#3a3226",
    field="#171a20",
    log="#0f1115",
)

LIGHT = Theme(
    name="light",
    window="#f3efe7",
    sidebar="#e7e0d3",
    surface="#fffdf9",
    surface_alt="#f6f1e8",
    border="#d8cfbf",
    text="#2a2620",
    muted="#6f675b",
    accent="#a8741f",
    accent_hover="#8f6219",
    accent_text="#fffdf9",
    danger="#a33b35",
    danger_hover="#8a302b",
    selection="#ecdcbf",
    field="#ffffff",
    log="#faf7f1",
)

THEMES = {DARK.name: DARK, LIGHT.name: LIGHT}

UI_FONT = "Segoe UI"
DISPLAY_FONT = "Georgia"
MONO_FONT = "Cascadia Mono, Consolas, Courier New"


# Server states: a distinct shape per state, always paired with its word.
STATUS_GLYPHS = {
    "Stopped": "○",         # white circle
    "Starting": "◔",        # circle with upper-right quadrant
    "Ready": "●",           # black circle
    "Game connected": "⚔",  # crossed swords
    "Stopping": "◑",        # circle with right half black
    "Error": "✖",           # heavy multiplication x
}

# Activity feed: one glyph per user-event kind.
EVENT_GLYPHS = {
    "ready": "✓",           # check mark
    "connected": "⇄",       # arrows left/right
    "disconnected": "⇠",    # dashed left arrow
    "logged_in": "⚑",       # flag
    "save_restored": "⤓",   # down arrow to bar
    "save_uploaded": "⤒",   # up arrow to bar
    "purchase": "◈",        # diamond in diamond
    "balance_synced": "⟳",  # clockwise gapped circle arrow
    "warning": "⚠",         # warning sign
    "error": "✖",
}
DEFAULT_EVENT_GLYPH = "•"


def status_text(status: str) -> str:
    """The pill text: glyph plus the status word (never the glyph alone)."""
    return f"{STATUS_GLYPHS.get(status, DEFAULT_EVENT_GLYPH)}  {status}"


def stylesheet(theme: Theme) -> str:
    t = theme
    return f"""
* {{
    font-family: "{UI_FONT}";
    font-size: 10pt;
    color: {t.text};
}}
QMainWindow, QWidget#page, QStackedWidget {{
    background: {t.window};
}}
QWidget#sidebar {{
    background: {t.sidebar};
    border-right: 1px solid {t.border};
}}
QLabel#brandTitle {{
    font-family: "{DISPLAY_FONT}";
    font-size: 19pt;
    font-weight: bold;
    letter-spacing: 3px;
    color: {t.accent};
}}
QLabel#brandSubtitle {{
    font-size: 8.5pt;
    letter-spacing: 2px;
    color: {t.muted};
}}
QListWidget#nav {{
    background: transparent;
    border: none;
    outline: none;
}}
QListWidget#nav::item {{
    padding: 10px 14px;
    margin: 2px 10px;
    border-radius: 8px;
    color: {t.muted};
}}
QListWidget#nav::item:hover {{
    background: {t.surface};
    color: {t.text};
}}
QListWidget#nav::item:selected {{
    background: {t.selection};
    color: {t.text};
    border-left: 3px solid {t.accent};
}}
QWidget#header {{
    background: {t.window};
    border-bottom: 1px solid {t.border};
}}
QLabel#pageTitle {{
    font-family: "{DISPLAY_FONT}";
    font-size: 17pt;
    font-weight: bold;
}}
QLabel#pageSubtitle {{
    color: {t.muted};
}}
QLabel#statusPill {{
    background: {t.surface};
    border: 1px solid {t.border};
    border-radius: 13px;
    padding: 4px 14px;
    font-weight: 600;
}}
QLabel#statusPill[state="Ready"], QLabel#statusPill[state="Game connected"] {{
    border: 1px solid {t.accent};
    color: {t.accent};
}}
QLabel#statusPill[state="Error"] {{
    border: 1px solid {t.danger};
}}
QFrame[card="true"], QGroupBox {{
    background: {t.surface};
    border: 1px solid {t.border};
    border-radius: 12px;
}}
QGroupBox {{
    margin-top: 0;
    padding: 44px 16px 14px 16px;
    font-size: 11pt;
    font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: padding;
    subcontrol-position: top left;
    left: 18px;
    top: 14px;
    color: {t.text};
    background: transparent;
}}
QGroupBox * {{
    font-size: 10pt;
    font-weight: normal;
}}
QFrame[banner="true"] {{
    background: {t.surface_alt};
    border: 1px solid {t.border};
    border-left: 4px solid {t.accent};
    border-radius: 8px;
}}
QLabel {{
    background: transparent;
}}
QLabel[role="cardTitle"] {{
    font-size: 11pt;
    font-weight: 600;
}}
QLabel[role="muted"] {{
    color: {t.muted};
}}
QLabel[role="statGlyph"] {{
    font-size: 22pt;
    color: {t.accent};
}}
QLabel[role="statLabel"] {{
    font-size: 9pt;
    font-weight: 600;
    letter-spacing: 2px;
    color: {t.muted};
}}
QLabel[role="bigStatus"] {{
    font-family: "{DISPLAY_FONT}";
    font-size: 20pt;
    font-weight: bold;
}}
QLabel[role="bigGlyph"] {{
    font-size: 30pt;
    color: {t.accent};
}}
QLabel[role="chip"] {{
    background: {t.surface_alt};
    border: 1px solid {t.border};
    border-radius: 10px;
    padding: 3px 10px;
    color: {t.muted};
}}
QPushButton {{
    background: {t.surface_alt};
    border: 1px solid {t.border};
    border-radius: 8px;
    padding: 7px 16px;
}}
QPushButton:hover {{
    border-color: {t.accent};
}}
QPushButton:pressed {{
    background: {t.selection};
}}
QPushButton:disabled {{
    color: {t.muted};
    background: {t.surface};
    border-color: {t.border};
}}
QPushButton[variant="primary"] {{
    background: {t.accent};
    border: 1px solid {t.accent};
    color: {t.accent_text};
    font-weight: 600;
}}
QPushButton[variant="primary"]:hover {{
    background: {t.accent_hover};
}}
QPushButton[variant="primary"]:disabled {{
    background: {t.surface_alt};
    border-color: {t.border};
    color: {t.muted};
}}
QPushButton[variant="danger"] {{
    background: {t.danger};
    border: 1px solid {t.danger};
    color: #ffffff;
    font-weight: 600;
}}
QPushButton[variant="danger"]:hover {{
    background: {t.danger_hover};
}}
QPushButton[variant="danger"]:disabled {{
    background: {t.surface_alt};
    border-color: {t.border};
    color: {t.muted};
}}
QPushButton[size="large"] {{
    padding: 11px 26px;
    font-size: 11pt;
}}
QPushButton#themeToggle {{
    background: transparent;
    border: 1px solid {t.border};
    color: {t.muted};
    margin: 0 12px;
}}
QLineEdit, QSpinBox, QComboBox {{
    background: {t.field};
    border: 1px solid {t.border};
    border-radius: 7px;
    padding: 6px 8px;
    selection-background-color: {t.accent};
    selection-color: {t.accent_text};
}}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{
    border-color: {t.accent};
}}
QLineEdit:disabled, QSpinBox:disabled, QComboBox:disabled {{
    color: {t.muted};
}}
QSpinBox[role="statValue"] {{
    font-family: "{DISPLAY_FONT}";
    font-size: 18pt;
    font-weight: bold;
    padding: 6px 10px 6px 14px;
}}
QSpinBox::up-button, QSpinBox::down-button {{
    width: 18px;
    border: none;
    background: transparent;
}}
QComboBox::drop-down {{
    border: none;
    width: 22px;
}}
QComboBox QAbstractItemView {{
    background: {t.surface};
    border: 1px solid {t.border};
    selection-background-color: {t.selection};
    selection-color: {t.text};
}}
QTreeWidget, QListWidget#events {{
    background: {t.field};
    border: 1px solid {t.border};
    border-radius: 8px;
    alternate-background-color: {t.surface_alt};
}}
QListWidget#events::item {{
    padding: 6px 8px;
    border-bottom: 1px solid {t.border};
}}
QTreeWidget::item {{
    padding: 4px 2px;
}}
QTreeWidget::item:selected, QListWidget::item:selected {{
    background: {t.selection};
    color: {t.text};
}}
QHeaderView::section {{
    background: {t.surface_alt};
    color: {t.muted};
    border: none;
    border-bottom: 1px solid {t.border};
    padding: 6px 8px;
    font-weight: 600;
}}
QPlainTextEdit#detailLog {{
    background: {t.log};
    border: 1px solid {t.border};
    border-radius: 8px;
    font-family: {MONO_FONT};
    font-size: 9pt;
    color: {t.muted};
}}
QPlainTextEdit {{
    background: {t.field};
    border: 1px solid {t.border};
    border-radius: 8px;
}}
QCheckBox {{
    spacing: 8px;
}}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid {t.border};
    border-radius: 4px;
    background: {t.field};
}}
QCheckBox::indicator:checked {{
    background: {t.accent};
    border-color: {t.accent};
}}
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: {t.border};
    border-radius: 4px;
    min-height: 28px;
}}
QScrollBar::handle:vertical:hover {{
    background: {t.muted};
}}
QScrollBar::add-line, QScrollBar::sub-line {{
    height: 0;
    width: 0;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
    margin: 2px;
}}
QScrollBar::handle:horizontal {{
    background: {t.border};
    border-radius: 4px;
    min-width: 28px;
}}
QToolTip {{
    background: {t.surface_alt};
    color: {t.text};
    border: 1px solid {t.border};
    padding: 5px;
}}
QMessageBox, QDialog, QInputDialog {{
    background: {t.window};
}}
QScrollArea {{
    background: transparent;
    border: none;
}}
"""


def palette(theme: Theme) -> QPalette:
    """A palette matching the stylesheet, for the parts QSS does not reach."""
    result = QPalette()
    window = QColor(theme.window)
    text = QColor(theme.text)
    result.setColor(QPalette.Window, window)
    result.setColor(QPalette.WindowText, text)
    result.setColor(QPalette.Base, QColor(theme.field))
    result.setColor(QPalette.AlternateBase, QColor(theme.surface_alt))
    result.setColor(QPalette.ToolTipBase, QColor(theme.surface_alt))
    result.setColor(QPalette.ToolTipText, text)
    result.setColor(QPalette.Text, text)
    result.setColor(QPalette.Button, QColor(theme.surface_alt))
    result.setColor(QPalette.ButtonText, text)
    result.setColor(QPalette.Highlight, QColor(theme.accent))
    result.setColor(QPalette.HighlightedText, QColor(theme.accent_text))
    result.setColor(QPalette.Link, QColor(theme.accent))
    result.setColor(QPalette.PlaceholderText, QColor(theme.muted))
    for role in (QPalette.Text, QPalette.ButtonText, QPalette.WindowText):
        result.setColor(QPalette.Disabled, role, QColor(theme.muted))
    return result


def apply(app: QApplication, theme: Theme) -> None:
    app.setStyle("Fusion")
    app.setFont(QFont(UI_FONT, 10))
    app.setPalette(palette(theme))
    app.setStyleSheet(stylesheet(theme))


def set_props(widget: QWidget, **props) -> QWidget:
    """Set styling properties and re-polish so a change takes effect."""
    for name, value in props.items():
        widget.setProperty(name, value)
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    return widget
