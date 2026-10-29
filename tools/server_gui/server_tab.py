#!/usr/bin/env python3
"""Server page: start/stop, title version, plain status, and the activity feed."""

from __future__ import annotations

import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from . import theme
from .server_process import (
    STATUS_ERROR,
    STATUS_GAME_CONNECTED,
    STATUS_READY,
    STATUS_STARTING,
    STATUS_STOPPED,
    STATUS_STOPPING,
    ServerProcess,
)
from .widgets import Card, button, label


STATUS_EXPLANATIONS = {
    STATUS_STOPPED: "The server is not running. Choose your game version and "
                    "press Start.",
    STATUS_STARTING: "Starting the server...",
    STATUS_READY: "Server ready - start the game in RPCS3 and log in.",
    STATUS_GAME_CONNECTED: "Game connected. Do not stop the server while you "
                           "are playing.",
    STATUS_STOPPING: "Stopping the server...",
    STATUS_ERROR: "The server could not start, or stopped unexpectedly. Turn "
                  "on the detailed log for the last error.",
}

EMPTY_FEED_TEXT = "Nothing yet - events appear here once the server starts."


class ServerTab(QWidget):
    """The first page; every visible event here comes from ``@@EVENT``."""

    title_version_changed = Signal(str)

    def __init__(self, process: ServerProcess, base_dir: Path,
                 initial_title_version: str = "01.00", parent=None):
        super().__init__(parent)
        self.setObjectName("page")
        self.process = process
        self.base_dir = Path(base_dir)

        self.version_combo = QComboBox()
        self.version_combo.addItems(["01.00", "01.06"])
        self.version_combo.setMinimumWidth(110)
        index = self.version_combo.findText(initial_title_version)
        if index >= 0:
            self.version_combo.setCurrentIndex(index)

        self.start_button = button("▶  Start server", "primary", "large")
        self.stop_button = button("■  Stop server", "danger", "large")
        self.stop_button.setEnabled(False)

        self.status_glyph = label(role="bigGlyph")
        self.status_label = label(role="bigStatus", selectable=True)
        self.status_explanation = label(role="muted", wrap=True)

        self.events = QListWidget()
        self.events.setObjectName("events")
        self.events.setSelectionMode(
            QAbstractItemView.SelectionMode.NoSelection)
        self.events.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.events.setWordWrap(True)
        self._add_placeholder()

        self.show_detail = QCheckBox("Show detailed log")
        self.detail = QPlainTextEdit()
        self.detail.setObjectName("detailLog")
        self.detail.setReadOnly(True)
        self.detail.setMaximumBlockCount(5000)
        self.detail.setVisible(False)

        self.open_logs = button("Open logs folder")
        self.clear_feed = button("Clear")

        self._build_layout()
        self._connect_signals()
        self._apply_status(STATUS_STOPPED)

    def _build_layout(self) -> None:
        control = Card()
        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(4)
        grid.addWidget(self.status_glyph, 0, 0, 2, 1,
                       Qt.AlignmentFlag.AlignVCenter)
        grid.addWidget(self.status_label, 0, 1)
        grid.addWidget(self.status_explanation, 1, 1)
        grid.setColumnStretch(1, 1)

        version_box = QVBoxLayout()
        version_box.setSpacing(4)
        version_box.addWidget(label("GAME VERSION", role="statLabel"))
        version_box.addWidget(self.version_combo)
        grid.addLayout(version_box, 0, 2, 2, 1)
        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        buttons.addWidget(self.start_button)
        buttons.addWidget(self.stop_button)
        grid.addLayout(buttons, 0, 3, 2, 1)
        control.body.addLayout(grid)

        chips = QHBoxLayout()
        chips.setSpacing(8)
        for text in ("Online config  TCP 80", "Quazal auth  UDP 21000",
                     "Quazal secure  UDP 21001"):
            chips.addWidget(label(text, role="chip"))
        chips.addStretch(1)
        chips.addWidget(label(
            "The game reaches these through RPCS3's IP swap.", role="muted"))
        control.body.addLayout(chips)

        feed = Card("Activity", "Plain-language events from the server. The "
                    "full protocol trace is always written to the logs "
                    "folder.")
        feed.body.addWidget(self.events, 1)
        feed_controls = QHBoxLayout()
        feed_controls.addWidget(self.show_detail)
        feed_controls.addStretch(1)
        feed_controls.addWidget(self.clear_feed)
        feed_controls.addWidget(self.open_logs)
        feed.body.addLayout(feed_controls)
        feed.body.addWidget(self.detail, 1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 22, 26, 22)
        layout.setSpacing(16)
        layout.addWidget(control)
        layout.addWidget(feed, 1)

    def _connect_signals(self) -> None:
        self.start_button.clicked.connect(self._start)
        self.stop_button.clicked.connect(self._stop)
        self.show_detail.toggled.connect(self.detail.setVisible)
        self.open_logs.clicked.connect(self._open_logs_folder)
        self.clear_feed.clicked.connect(self._clear_feed)
        self.version_combo.currentTextChanged.connect(
            self.title_version_changed.emit)
        self.process.status_changed.connect(self._apply_status)
        self.process.event_received.connect(self._append_event)
        self.process.detail_line.connect(self.detail.appendPlainText)
        self.process.startup_error.connect(self.show_startup_error)

    def selected_title_version(self) -> str:
        return self.version_combo.currentText()

    # ------------------------------------------------------------- actions
    def _start(self) -> None:
        self.process.start(self.selected_title_version())

    def _stop(self) -> None:
        if not self.process.is_running():
            return
        if self.process.current_status == STATUS_GAME_CONNECTED:
            if not self._confirm_stop_while_connected():
                return
        self.process.request_stop()

    def _confirm_stop_while_connected(self) -> bool:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Stop the server while the game is connected?")
        box.setText("The game is still connected to the server.")
        box.setInformativeText(
            "Before stopping:\n"
            "1. Return to the Ludus (main menu) in the game.\n"
            "2. Wait about 20 seconds so the game's native autosave finishes.\n"
            "3. Close RPCS3 first, then stop the server.\n\n"
            "Stopping now can lose your latest progress. The server is never "
            "restarted automatically.")
        box.setStandardButtons(QMessageBox.StandardButton.Yes
                               | QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(QMessageBox.StandardButton.Cancel)
        return box.exec() == QMessageBox.StandardButton.Yes

    def _open_logs_folder(self) -> None:
        logs_dir = self.base_dir / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(logs_dir)))

    def _clear_feed(self) -> None:
        self.events.clear()
        self._add_placeholder()

    def _add_placeholder(self) -> None:
        item = QListWidgetItem(EMPTY_FEED_TEXT)
        item.setData(Qt.ItemDataRole.UserRole, "placeholder")
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        self.events.addItem(item)

    # -------------------------------------------------------------- signals
    def _apply_status(self, status: str) -> None:
        self.status_glyph.setText(theme.STATUS_GLYPHS.get(status, ""))
        self.status_label.setText(status)
        self.status_explanation.setText(
            STATUS_EXPLANATIONS.get(status, ""))
        # A QProcess reports "not running" for a moment during startup, so the
        # word state is what decides the buttons here.
        running = self.process.is_running() or status in (
            STATUS_STARTING, STATUS_READY, STATUS_GAME_CONNECTED,
            STATUS_STOPPING)
        self.version_combo.setEnabled(not running)
        self.start_button.setEnabled(not running)
        self.stop_button.setEnabled(running)

    def _append_event(self, event: dict) -> None:
        message = event.get("message")
        if not message:
            return
        if self.events.count() == 1 and self.events.item(0).data(
                Qt.ItemDataRole.UserRole) == "placeholder":
            self.events.clear()
        glyph = theme.EVENT_GLYPHS.get(event.get("kind"),
                                       theme.DEFAULT_EVENT_GLYPH)
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        item = QListWidgetItem(f"{glyph}   {timestamp}    {message}")
        item.setData(Qt.ItemDataRole.UserRole, event.get("kind"))
        self.events.addItem(item)
        self.events.scrollToBottom()

    def show_startup_error(self, report: str) -> None:
        """Show the server's startup report, including port diagnostics."""
        dialog = QDialog(self)
        dialog.setWindowTitle("The server could not start")
        dialog.resize(760, 460)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)
        layout.addWidget(label("✖  The server could not start",
                               role="cardTitle"))
        layout.addWidget(label(
            "The server reported this problem. If another program is using "
            "port 80, the report below names it and suggests a fix.",
            role="muted", wrap=True))
        text = QPlainTextEdit()
        text.setObjectName("detailLog")
        text.setReadOnly(True)
        text.setPlainText(report)
        layout.addWidget(text, 1)
        buttons = QHBoxLayout()
        copy_button: QPushButton = button("Copy details")
        close_button = button("Close", "primary")
        buttons.addStretch(1)
        buttons.addWidget(copy_button)
        buttons.addWidget(close_button)
        layout.addLayout(buttons)

        def copy_details() -> None:
            QGuiApplication.clipboard().setText(report)
            copy_button.setText("Copied")

        copy_button.clicked.connect(copy_details)
        close_button.clicked.connect(dialog.accept)
        dialog.exec()
