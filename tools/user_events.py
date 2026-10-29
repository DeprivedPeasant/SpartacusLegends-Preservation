#!/usr/bin/env python3
"""Short, plain-language event stream for the preservation server.

The detail log (``prudp_server.log`` / ``online_config.log``) keeps the full
protocol trace for bug reports.  This module is the *user view*: a handful of
plain sentences a player can act on.  The Qt frontend consumes the same events
through the optional machine-readable line, so the console server and the GUI
never disagree about what happened.

No Qt and no third-party imports: the console server must keep working on a
bare Python install.
"""

from __future__ import annotations

import datetime
import json
import os
import threading

# Fixed vocabulary. Keeping this closed is what stops free-form log text from
# leaking into the user view: a new event needs an explicit kind here first.
KINDS = frozenset({
    "ready",
    "connected",
    "disconnected",
    "logged_in",
    "patch_confirmed",
    "save_restored",
    "save_uploaded",
    "purchase",
    "balance_synced",
    "warning",
    "error",
})

MACHINE_PREFIX = "@@EVENT "

# The launcher enables this for --control-stdin (and therefore for the GUI),
# and a test may toggle it directly.  Environment support keeps a standalone
# `python tools/prudp_server.py` usable for protocol probes.
MACHINE_OUTPUT = os.environ.get("SPARTACUS_MACHINE_OUTPUT", "") not in ("", "0")

_PRINT_LOCK = threading.Lock()


def set_machine_output(enabled: bool) -> None:
    """Turn the ``@@EVENT`` line on or off for the rest of the process."""
    global MACHINE_OUTPUT
    MACHINE_OUTPUT = bool(enabled)


def machine_output_enabled() -> bool:
    return MACHINE_OUTPUT


def emit(kind: str, message: str, **fields) -> None:
    """Print one timestamped user line, plus the optional machine copy.

    ``fields`` are merged into the ``@@EVENT`` JSON object for the GUI; they
    never appear in the human-readable line.  The kind is validated so a typo
    cannot silently create an event the GUI does not know how to display.
    """
    if kind not in KINDS:
        raise ValueError(f"unknown user event kind {kind!r}")
    timestamp = datetime.datetime.now().strftime("%H:%M:%S")
    line = f"[{timestamp}] {message}"
    payload = {"kind": kind, "message": message}
    payload.update(fields)
    machine_line = None
    if MACHINE_OUTPUT:
        machine_line = MACHINE_PREFIX + json.dumps(
            payload, separators=(",", ":"), sort_keys=True, default=str
        )
    with _PRINT_LOCK:
        print(line, flush=True)
        if machine_line is not None:
            print(machine_line, flush=True)
