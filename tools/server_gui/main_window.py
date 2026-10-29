#!/usr/bin/env python3
"""Main window: sidebar navigation over the Server, Player, Items and Patch
setup pages, a header with the live server status, and the theme toggle.

The window owns the server subprocess. All game-file logic lives in the Qt-free
modules (``save_editor``, ``patch_installer``, ``server_control``,
``user_events``); widgets only call them.
"""

from __future__ import annotations

from pathlib import Path
import sys

from PySide6.QtCore import QSettings, QSize, Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from . import theme
from .items_tab import ItemsTab
from .patch_tab import PatchTab
from .player_tab import PlayerTab
from .server_process import ServerProcess, application_base_dir
from .server_tab import ServerTab
from .widgets import button, label

try:
    import patch_installer
    import server_config
    from _version import __version__ as VERSION
except ImportError:  # Imported as tools.server_gui.main_window by tests.
    from tools import patch_installer, server_config
    from tools._version import __version__ as VERSION


APP_NAME = "Spartacus Legends Preservation Server"
APP_ORGANISATION = "SpartacusLegendsPreservation"
SETTINGS_FILE = "gui-settings.ini"
PATCH_PAGE = 3

# After the game logs in, the server reports ``patch_confirmed`` when the game
# starts loading its native saves - which it only does once RPCS3 applied the
# compatibility patch. Live logs show that within about a second of login, so
# a minute without it means the patch did not take effect.
PATCH_CONFIRM_TIMEOUT_MS = 60_000

# (navigation label, glyph, page subtitle)
PAGES = (
    ("Server", "⚔", "Start the server and follow what the game is doing."),
    ("Player", "◆", "Gold, silver and fame for your gladiator school."),
    ("Items", "▤", "Owned items, Boost uses and purchased Ludus slots."),
    ("Patch setup", "⚙", "Install and verify the RPCS3 patch and network "
                              "settings."),
)


def configured_title_version(base_dir: Path) -> str:
    """The version the patch installer recorded, or the 01.00 default."""
    try:
        configured = server_config.read_title_version(
            server_config.config_path(base_dir))
    except ValueError:
        return server_config.DEFAULT_TITLE_VERSION
    return configured or server_config.DEFAULT_TITLE_VERSION


class MainWindow(QMainWindow):
    """The application window; construct with a temp ``base_dir`` in tests."""

    def __init__(self, base_dir: Path | None = None, parent=None):
        super().__init__(parent)
        self.base_dir = (Path(base_dir) if base_dir is not None
                         else application_base_dir())
        self.title_version = configured_title_version(self.base_dir)
        self.process = ServerProcess(self)

        self.server_tab = ServerTab(self.process, self.base_dir,
                                    self.title_version)
        self.player_tab = PlayerTab(self.process, self.base_dir,
                                    self.title_version)
        self.items_tab = ItemsTab(self.process, self.base_dir,
                                  self.title_version)
        # Settings live beside the application (portable, like data/), which
        # also keeps a test's temporary base_dir away from the real ones.
        self._settings = QSettings(str(self.base_dir / SETTINGS_FILE),
                                   QSettings.Format.IniFormat)
        self.patch_tab = PatchTab(self._settings, self.base_dir)
        self._pages = (self.server_tab, self.player_tab, self.items_tab,
                       self.patch_tab)

        self.stack = QStackedWidget()
        for page in self._pages:
            self.stack.addWidget(page)

        self.nav = QListWidget()
        self.nav.setObjectName("nav")
        self.nav.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.nav.setIconSize(QSize(0, 0))
        for name, glyph, _subtitle in PAGES:
            item = QListWidgetItem(f"{glyph}   {name}")
            item.setData(Qt.ItemDataRole.UserRole, name)
            self.nav.addItem(item)

        self.page_title = label()
        self.page_title.setObjectName("pageTitle")
        self.page_subtitle = label()
        self.page_subtitle.setObjectName("pageSubtitle")
        self.status_pill = label()
        self.status_pill.setObjectName("statusPill")
        self.version_chip = label(role="chip")

        self.theme_toggle = button("")
        self.theme_toggle.setObjectName("themeToggle")

        self.setCentralWidget(self._build_shell())
        self.setWindowTitle(APP_NAME)
        self.resize(1120, 760)
        self.setMinimumSize(900, 620)
        self._last_server_running = None
        self._patch_confirmed = False
        self.patch_timer = QTimer(self)
        self.patch_timer.setSingleShot(True)
        self.patch_timer.setInterval(PATCH_CONFIRM_TIMEOUT_MS)

        self._theme_name = str(self._settings.value("theme", theme.DARK.name))
        if self._theme_name not in theme.THEMES:
            self._theme_name = theme.DARK.name

        self._connect_signals()
        self.nav.setCurrentRow(0)
        self._on_status_changed(self.process.current_status)
        self._show_title_version(self.title_version)
        self.apply_palette(self._theme_name == theme.DARK.name)
        if not self.patch_tab.setup_completed():
            self.nav.setCurrentRow(PATCH_PAGE)
            self.patch_tab.show_attention(
                "\u2694  Welcome - set up RPCS3 first",
                "Choose your RPCS3 folder. The game, its version and its "
                "executable are found and checked automatically; then press "
                "Install / repair setup. You only need to do this once.")
        low = patch_installer.low_integrity_problem()
        if low:
            # Shown before anything else: every write would be refused.
            self.nav.setCurrentRow(PATCH_PAGE)
            self.patch_tab.show_attention(
                "\u26a0  Windows is limiting this copy of the program", low)
        if self.patch_tab.rpcs3_root() is not None:
            self.patch_tab.recheck()

    # -------------------------------------------------------------- layout
    def _build_shell(self) -> QWidget:
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(220)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(0, 26, 0, 18)
        side.setSpacing(4)
        brand = label("SPARTACUS")
        brand.setObjectName("brandTitle")
        brand.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        subtitle = label("LEGENDS  ·  PRESERVATION")
        subtitle.setObjectName("brandSubtitle")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        side.addWidget(brand)
        side.addWidget(subtitle)
        side.addSpacing(26)
        side.addWidget(self.nav, 1)
        side.addWidget(self.theme_toggle)
        side.addSpacing(8)
        version = label(f"Server v{VERSION}", role="muted")
        version.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        side.addWidget(version)

        header = QWidget()
        header.setObjectName("header")
        head = QHBoxLayout(header)
        head.setContentsMargins(26, 18, 26, 16)
        titles = QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(self.page_title)
        titles.addWidget(self.page_subtitle)
        head.addLayout(titles, 1)
        head.addWidget(self.version_chip, 0, Qt.AlignmentFlag.AlignVCenter)
        head.addSpacing(8)
        head.addWidget(self.status_pill, 0, Qt.AlignmentFlag.AlignVCenter)

        content = QWidget()
        column = QVBoxLayout(content)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        column.addWidget(header)
        column.addWidget(self.stack, 1)

        shell = QWidget()
        root = QHBoxLayout(shell)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(sidebar)
        root.addWidget(content, 1)
        return shell

    def _connect_signals(self) -> None:
        self.nav.currentRowChanged.connect(self._show_page)
        self.process.status_changed.connect(self._on_status_changed)
        self.server_tab.title_version_changed.connect(
            self._on_title_version_changed)
        self.theme_toggle.clicked.connect(self._toggle_theme)
        self.process.event_received.connect(self._on_server_event)
        self.patch_timer.timeout.connect(self._patch_not_confirmed)
        self.patch_tab.setup_installed.connect(self._on_setup_installed)

    # ---------------------------------------------------------- navigation
    def page_names(self) -> list[str]:
        return [self.nav.item(index).data(Qt.ItemDataRole.UserRole)
                for index in range(self.nav.count())]

    def _show_page(self, index: int) -> None:
        if not 0 <= index < len(self._pages):
            return
        self.stack.setCurrentIndex(index)
        name, _glyph, subtitle = PAGES[index]
        self.page_title.setText(name)
        self.page_subtitle.setText(subtitle)

    # -------------------------------------------------------------- theme
    def apply_palette(self, dark: bool) -> None:
        app = QApplication.instance()
        if app is None:
            return
        selected = theme.DARK if dark else theme.LIGHT
        self._theme_name = selected.name
        theme.apply(app, selected)
        self.theme_toggle.setText(
            "☼  Light theme" if dark else "☾  Dark theme")
        self._settings.setValue("theme", selected.name)
        # Write now: a deferred write on destruction would recreate the
        # settings folder after its owner (for example a test) removed it.
        self._settings.sync()

    def _toggle_theme(self) -> None:
        self.apply_palette(self._theme_name != theme.DARK.name)

    # ------------------------------------------------------------- status
    def _show_title_version(self, title_version: str) -> None:
        self.version_chip.setText(f"Game {title_version}")

    def _on_title_version_changed(self, title_version: str) -> None:
        self.title_version = title_version
        self._show_title_version(title_version)
        self.player_tab.set_title_version(title_version)
        self.items_tab.set_title_version(title_version)

    def _on_setup_installed(self, title_version: str) -> None:
        if self.process.is_running():
            return
        combo = self.server_tab.version_combo
        if combo.findText(title_version) >= 0:
            combo.setCurrentText(title_version)

    # ------------------------------------------------- patch confirmation
    def _on_server_event(self, event: dict) -> None:
        kind = event.get("kind")
        if kind == "connected":
            self._patch_confirmed = False
        elif kind == "logged_in" and not self._patch_confirmed:
            self.patch_timer.start()
        elif kind == "patch_confirmed":
            self._patch_confirmed = True
            self.patch_timer.stop()
            self.patch_tab.mark_completed(True)
            self.patch_tab.clear_attention()
        elif kind == "disconnected":
            self.patch_timer.stop()

    def _patch_not_confirmed(self) -> None:
        """The game logged in but never started loading its saves."""
        if self._patch_confirmed:
            return
        self.server_tab._append_event({
            "kind": "warning",
            "message": "The game logged in but did not start loading its "
                       "saves - the compatibility patch is not active.",
        })
        self.nav.setCurrentRow(PATCH_PAGE)
        self.patch_tab.show_attention(
            "\u26a0  The compatibility patch did not take effect",
            "The game logged in but never started loading its saves, so "
            "RPCS3 did not apply the patch. Close RPCS3, press Check again to "
            "read its last boot, then Install / repair setup and cold-boot.")
        self.patch_tab.recheck()

    def _on_status_changed(self, status: str) -> None:
        self.status_pill.setText(theme.status_text(status))
        theme.set_props(self.status_pill, state=status)
        running = self.process.is_running()
        if running != self._last_server_running:
            self._last_server_running = running
            self.player_tab.set_server_running(running)
            self.items_tab.set_server_running(running)

    # ---------------------------------------------------------- lifecycle
    def closeEvent(self, event) -> None:
        if not self.process.is_running():
            self.patch_tab.wait_for_worker(5000)
            event.accept()
            return
        confirm = QMessageBox.question(
            self, "The server is still running",
            "The server is still running. Stop it and close the window?\n\n"
            "If the game is connected: return to the Ludus, wait about 20 "
            "seconds for the native autosave, then close RPCS3 first.",
            QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel)
        if confirm != QMessageBox.Yes:
            event.ignore()
            return
        self.process.request_stop()
        if not self.process.wait_for_finished(5000):
            self.process.kill()
            self.process.wait_for_finished(2000)
        event.accept()


def run(argv=None) -> int:
    """Create the application and show the window; returns the exit code."""
    app = QApplication.instance()
    if app is None:
        arguments = list(sys.argv if argv is None else [sys.argv[0], *argv])
        app = QApplication(arguments)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_ORGANISATION)
    theme.apply(app, theme.DARK)
    window = MainWindow()
    window.show()
    return app.exec()
