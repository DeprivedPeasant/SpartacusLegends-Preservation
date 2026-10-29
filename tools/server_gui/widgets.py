#!/usr/bin/env python3
"""Small styled building blocks shared by the pages."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .theme import set_props


class Card(QFrame):
    """A rounded surface with an optional title and muted subtitle."""

    def __init__(self, title: str | None = None,
                 subtitle: str | None = None, parent=None):
        super().__init__(parent)
        set_props(self, card=True)
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(18, 16, 18, 16)
        self.body.setSpacing(10)
        if title:
            self.title_label = label(title, role="cardTitle")
            self.body.addWidget(self.title_label)
        if subtitle:
            self.subtitle_label = label(subtitle, role="muted", wrap=True)
            self.body.addWidget(self.subtitle_label)


class Banner(QFrame):
    """An accent-edged notice used for the offline/live mode explanation."""

    def __init__(self, text: str = "", parent=None):
        super().__init__(parent)
        set_props(self, banner=True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        self.heading = label("", role="cardTitle")
        self.text = label(text, wrap=True)
        column = QVBoxLayout()
        column.setSpacing(2)
        column.addWidget(self.heading)
        column.addWidget(self.text)
        layout.addLayout(column, 1)

    def set_message(self, heading: str, text: str) -> None:
        self.heading.setText(heading)
        self.heading.setVisible(bool(heading))
        self.text.setText(text)


def label(text: str = "", *, role: str | None = None,
          wrap: bool = False, selectable: bool = False) -> QLabel:
    widget = QLabel(text)
    if role:
        set_props(widget, role=role)
    widget.setWordWrap(wrap)
    if selectable:
        widget.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
    return widget


def button(text: str, variant: str | None = None,
           size: str | None = None) -> QPushButton:
    widget = QPushButton(text)
    widget.setCursor(Qt.CursorShape.PointingHandCursor)
    props = {}
    if variant:
        props["variant"] = variant
    if size:
        props["size"] = size
    if props:
        set_props(widget, **props)
    return widget


def page(parent=None) -> tuple[QWidget, QVBoxLayout]:
    """A page container with the standard outer margins."""
    widget = QWidget(parent)
    widget.setObjectName("page")
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(26, 22, 26, 22)
    layout.setSpacing(16)
    return widget, layout


def hspacer() -> QWidget:
    spacer = QWidget()
    spacer.setSizePolicy(QSizePolicy.Policy.Expanding,
                         QSizePolicy.Policy.Preferred)
    return spacer
