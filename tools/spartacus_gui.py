#!/usr/bin/env python3
"""Spartacus Legends Preservation Server GUI entry point.

Packaged as ``SpartacusLegendsServerGUI.exe`` beside
``SpartacusLegendsServer.exe``; from source it runs as
``python tools/spartacus_gui.py``.
"""

from __future__ import annotations

try:
    from server_gui.main_window import run
except ImportError:  # Imported as tools.spartacus_gui (repository-root tests).
    from tools.server_gui.main_window import run


if __name__ == "__main__":
    raise SystemExit(run())
