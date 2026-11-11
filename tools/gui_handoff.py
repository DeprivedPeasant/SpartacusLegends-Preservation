#!/usr/bin/env python3
"""Point players who double-click a console program at the app instead.

``SpartacusLegendsServer.exe`` and ``SpartacusLegendsPatchInstaller.exe`` stay
in the release for advanced and scripted use, but the app
(``SpartacusLegendsServerGUI.exe``) does everything they do and also keeps the
game version right and shows when progress is saved. When one of them is
started with no arguments from a real console - which is what a double-click
in File Explorer does - it offers to open the app and close itself.

Any argument (the GUI always passes several), a redirected stdin, a source
checkout, or ``--console`` skips the offer, so scripts and the GUI's own
server launch are never interrupted.

No Qt and no third-party imports.
"""

from __future__ import annotations

from pathlib import Path
import os
import subprocess
import sys

try:
    import eboot_source
    import i18n
except ImportError:  # Imported as tools.gui_handoff by the unit tests.
    from tools import eboot_source, i18n


GUI_EXE_NAME = "SpartacusLegendsServerGUI.exe"
CONSOLE_FLAG = "--console"


def gui_executable(base_dir: Path) -> Path | None:
    path = Path(base_dir) / GUI_EXE_NAME
    return path if path.is_file() else None


def should_offer(arguments, *, frozen: bool, interactive: bool,
                 gui: Path | None) -> bool:
    """Only a double-clicked packaged program with the app beside it."""
    return bool(frozen and interactive and gui is not None
                and not list(arguments))


def offer_language() -> str:
    """The language for the offer: the one set for this process, else
    Windows'. The console programs themselves stay English."""
    if i18n.normalise(os.environ.get(i18n.ENV_VAR)):
        return i18n.current()
    return i18n.language_from(i18n.system_locale_names())


def launch_gui(gui: Path, language: str = i18n.ENGLISH) -> bool:
    """Start the app detached from this console; False if Windows refused."""
    flags = 0
    if sys.platform == "win32":
        flags = (subprocess.DETACHED_PROCESS
                 | subprocess.CREATE_NEW_PROCESS_GROUP)
    try:
        # The app is its own PyInstaller program: it must not inherit this
        # one's unpack folder or private variables.
        subprocess.Popen([str(gui)], cwd=str(gui.parent),
                         env=eboot_source.rpcs3_environment(),
                         creationflags=flags, close_fds=True,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
    except OSError as error:
        print(i18n.tr_in(language, "Could not open the app: {error}",
                         error=error))
        return False
    return True


def offer(program: str, base_dir: Path, arguments=None, *,
          frozen: bool | None = None, interactive: bool | None = None,
          ask=input, launch=launch_gui, language: str | None = None) -> bool:
    """Offer the app; True when it was opened and this program should exit."""
    arguments = sys.argv[1:] if arguments is None else list(arguments)
    frozen = getattr(sys, "frozen", False) if frozen is None else frozen
    if interactive is None:
        try:
            interactive = sys.stdin.isatty()
        except (AttributeError, ValueError):
            interactive = False
    gui = gui_executable(base_dir)
    if not should_offer(arguments, frozen=frozen, interactive=interactive,
                        gui=gui):
        return False
    language = offer_language() if language is None else language

    def tr(text, **values):
        return i18n.tr_in(language, text, **values)

    rule = "=" * 70
    print(rule)
    print(tr("  Use the app instead: {app}", app=GUI_EXE_NAME))
    print(rule)
    print(tr(
        "{program} is the console version, for advanced and scripted use.\n"
        "The app in this folder runs the same server, and it also sets up "
        "RPCS3,\nkeeps the game version right, shows when your progress is "
        "saved,\nand edits gold, fame and items.", program=program))
    print()
    try:
        answer = ask(tr(
            "Press Enter to open the app (recommended), or type C and press "
            "Enter\nto keep using this console: "))
    except (EOFError, KeyboardInterrupt):
        return False
    if answer.strip().lower().startswith("c"):
        print(tr("Continuing in the console. Start it with {flag} to skip "
                 "this question.", flag=CONSOLE_FLAG))
        print()
        return False
    if launch(gui, language):
        print(tr("Opening the app. This window can be closed."))
        return True
    return False
