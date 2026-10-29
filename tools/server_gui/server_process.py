#!/usr/bin/env python3
"""Run the preservation server as a child process for the Qt frontend.

The server is deliberately a separate process: ``prudp_server`` reads its
environment once at import time, so restarting it in-process is unsafe.  This
module owns the :class:`QProcess`, forwards ordinary output to the detail-log
signal, and turns the server's machine-readable lines into Qt signals:

- ``@@EVENT <json>`` -- one user-view event (see ``tools/user_events.py``).
- ``@@REPLY <json>`` -- one control-channel reply (see
  ``tools/server_control.py``).

Widgets never scrape free-form log text: the plain event list is fed only by
``@@EVENT`` lines.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, Signal

try:
    import eboot_source
    import server_control
    import user_events
except ImportError:  # Imported as tools.server_gui.server_process by tests.
    from tools import eboot_source, server_control, user_events


EVENT_PREFIX = user_events.MACHINE_PREFIX
REPLY_PREFIX = server_control.REPLY_PREFIX

SERVER_EXE_NAME = "SpartacusLegendsServer.exe"
SERVER_SCRIPT_NAME = "spartacus_server.py"
STOP_TIMEOUT_MS = 15_000

STATUS_STOPPED = "Stopped"
STATUS_STARTING = "Starting"
STATUS_READY = "Ready"
STATUS_GAME_CONNECTED = "Game connected"
STATUS_STOPPING = "Stopping"
STATUS_ERROR = "Error"


def application_base_dir() -> Path:
    """Where ``data/``, ``logs/`` and ``backups/`` live.

    Frozen: beside the GUI executable, matching the server executable.  From
    source: the repository root (``tools/server_gui/`` is two levels down).
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def server_command(title_version: str) -> tuple[list[str], str]:
    """Return the command line and working directory for one server launch."""
    arguments = [
        "--no-wait",
        "--control-stdin",
        "--verbose",
        "--title-version",
        title_version,
    ]
    if getattr(sys, "frozen", False):
        base_dir = application_base_dir()
        return [str(base_dir / SERVER_EXE_NAME), *arguments], str(base_dir)
    tools_dir = Path(__file__).resolve().parents[1]
    return ([sys.executable, str(tools_dir / SERVER_SCRIPT_NAME), *arguments],
            str(application_base_dir()))


def parse_server_line(line: str):
    """Classify one stdout line as ``(kind, payload)``.

    ``plain`` lines are returned as ``(kind, text)``; malformed machine lines
    fall back to ``plain`` so no output is ever lost.
    """
    text = line.rstrip("\r\n")
    if text.startswith(EVENT_PREFIX):
        try:
            payload = json.loads(text[len(EVENT_PREFIX):])
        except json.JSONDecodeError:
            return "plain", text
        if isinstance(payload, dict):
            return "event", payload
        return "plain", text
    if text.startswith(REPLY_PREFIX):
        try:
            payload = json.loads(text[len(REPLY_PREFIX):])
        except json.JSONDecodeError:
            return "plain", text
        if isinstance(payload, dict):
            return "reply", payload
        return "plain", text
    return "plain", text


class ServerProcess(QObject):
    """One server subprocess, with parsed signals for the tabs to consume."""

    event_received = Signal(dict)
    reply_received = Signal(dict)
    detail_line = Signal(str)
    status_changed = Signal(str)
    # Emitted once when the server reports a startup failure.  The text is the
    # full stderr report, including the port-diagnostic block when present.
    startup_error = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._process = QProcess(self)
        self._process.setProcessChannelMode(
            QProcess.ProcessChannelMode.SeparateChannels)
        self._process.readyReadStandardOutput.connect(self._drain_stdout)
        self._process.readyReadStandardError.connect(self._drain_stderr)
        self._process.finished.connect(self._on_finished)
        self._process.errorOccurred.connect(self._on_error)
        self._status = STATUS_STOPPED
        self._next_command_id = 1
        self._startup_report: list[str] = []
        self._collecting_startup_error = False
        self._stop_requested = False
        self._stop_timer = QTimer(self)
        self._stop_timer.setSingleShot(True)
        self._stop_timer.setInterval(STOP_TIMEOUT_MS)
        self._stop_timer.timeout.connect(self._force_stop)

    @property
    def current_status(self) -> str:
        return self._status

    def is_running(self) -> bool:
        return self._process.state() != QProcess.ProcessState.NotRunning

    def start(self, title_version: str) -> bool:
        """Launch the server; returns False when one is already running."""
        if self.is_running():
            return False
        program, working_directory = server_command(title_version)
        self._startup_report = []
        self._collecting_startup_error = False
        self._stop_requested = False
        self._next_command_id = 1
        # The packaged server is its own PyInstaller program: it must not
        # inherit this GUI's Qt/PyInstaller variables or bundled DLL folder.
        environment = QProcessEnvironment()
        for name, value in eboot_source.rpcs3_environment().items():
            environment.insert(name, value)
        self._process.setProcessEnvironment(environment)
        self._process.setWorkingDirectory(working_directory)
        with eboot_source.outside_program_dll_search():
            self._process.start(program[0], program[1:])
        self._set_status(STATUS_STARTING)
        return True

    def write_command(self, command: dict) -> int:
        """Write one JSON control command and return the echoed id."""
        command_id = self._next_command_id
        self._next_command_id += 1
        payload = {"id": command_id, **command}
        if self.is_running():
            self._process.write(
                (json.dumps(payload, separators=(",", ":")) + "\n").encode(
                    "utf-8"))
        return command_id

    def request_stop(self) -> None:
        """Ask for the server's normal clean shutdown (never a restart)."""
        if not self.is_running():
            return
        self._stop_requested = True
        self._set_status(STATUS_STOPPING)
        self._process.write(b"stop\n")
        self._stop_timer.start()

    def kill(self) -> None:
        """Terminate the child immediately (last-resort cleanup)."""
        if self.is_running():
            self._process.kill()

    def wait_for_finished(self, timeout_ms: int = 5000) -> bool:
        """Block until the child exits, up to ``timeout_ms``.

        Only used while the window is closing; normal shutdown is asynchronous
        through :meth:`request_stop`.
        """
        if not self.is_running():
            return True
        return self._process.waitForFinished(timeout_ms)

    def _force_stop(self) -> None:
        if not self.is_running():
            return
        self.detail_line.emit(
            f"The server did not stop within {STOP_TIMEOUT_MS // 1000} "
            "seconds; terminating it now.")
        self._process.kill()

    # ----------------------------------------------------------- output
    def _drain_stdout(self) -> None:
        data = bytes(self._process.readAllStandardOutput())
        if not data:
            return
        for line in data.decode("utf-8", "replace").splitlines():
            kind, payload = parse_server_line(line)
            if kind == "event":
                self._handle_event(payload)
                self.event_received.emit(payload)
            elif kind == "reply":
                self.reply_received.emit(payload)
            else:
                self.detail_line.emit(payload)

    def _drain_stderr(self) -> None:
        data = bytes(self._process.readAllStandardError())
        if not data:
            return
        for line in data.decode("utf-8", "replace").splitlines():
            self.detail_line.emit(line)
            if "STARTUP ERROR" in line:
                self._collecting_startup_error = True
            if self._collecting_startup_error:
                self._startup_report.append(line)

    def _handle_event(self, event: dict) -> None:
        kind = event.get("kind")
        if kind == "ready":
            self._set_status(STATUS_READY)
        elif kind == "connected":
            self._set_status(STATUS_GAME_CONNECTED)
        elif kind == "disconnected":
            self._set_status(
                STATUS_READY if self.is_running() else STATUS_STOPPED)
        elif kind == "error":
            self._set_status(STATUS_ERROR)

    # ---------------------------------------------------------- lifecycle
    def _on_finished(self, exit_code: int, _exit_status) -> None:
        self._stop_timer.stop()
        # Flush any final output that arrived with the exit.
        self._drain_stdout()
        self._drain_stderr()
        report = "\n".join(self._startup_report).strip()
        self._startup_report = []
        self._collecting_startup_error = False
        if report:
            self._set_status(STATUS_ERROR)
            self.startup_error.emit(report)
        elif exit_code != 0 and not self._stop_requested:
            self._set_status(STATUS_ERROR)
            self.detail_line.emit(
                f"The server exited unexpectedly with code {exit_code}. Open "
                "the detailed log or the logs folder for the full trace.")
        else:
            self._set_status(STATUS_STOPPED)

    def _on_error(self, error) -> None:
        if error != QProcess.ProcessError.FailedToStart:
            return
        self._stop_timer.stop()
        self._set_status(STATUS_ERROR)
        self.startup_error.emit(
            "Could not start the server program: "
            f"{self._process.errorString()}\n"
            "If this is a packaged copy, make sure "
            f"{SERVER_EXE_NAME} is in the same folder as "
            "SpartacusLegendsServerGUI.exe.")

    def _set_status(self, status: str) -> None:
        if status == self._status:
            return
        self._status = status
        self.status_changed.emit(status)
