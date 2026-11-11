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

from PySide6.QtCore import (
    QLibraryInfo,
    QLocale,
    QProcess,
    QSettings,
    QSize,
    Qt,
    QTimer,
    QTranslator,
)
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
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
    import i18n
    import migration_coordinator
    import patch_installer
    import server_config
    from _version import __version__ as VERSION
    from i18n import N_, tr
except ImportError:  # Imported as tools.server_gui.main_window by tests.
    from tools import i18n, migration_coordinator, patch_installer, \
        server_config
    from tools._version import __version__ as VERSION
    from tools.i18n import N_, tr


APP_NAME = "Spartacus Legends Preservation Server"
APP_ORGANISATION = "SpartacusLegendsPreservation"
SETTINGS_FILE = "gui-settings.ini"
SETTING_LANGUAGE = "language"
PATCH_PAGE = 3

# After the game logs in, the server reports ``patch_confirmed`` when the game
# starts loading its native saves - which it only does once RPCS3 applied the
# compatibility patch. Live logs show that within about a second of login, so
# a minute without it means the patch did not take effect.
PATCH_CONFIRM_TIMEOUT_MS = 60_000

# (navigation label, glyph, page subtitle); English, translated when shown.
PAGES = (
    (N_("Server"), "⚔",
     N_("Start the server and follow what the game is doing.")),
    (N_("Player"), "◆",
     N_("Gold, silver and fame for your gladiator school.")),
    (N_("Items"), "▤",
     N_("Owned items, Boost uses and purchased Ludus slots.")),
    (N_("Patch setup"), "⚙",
     N_("Install and verify the RPCS3 patch and network settings.")),
)


def startup_language(saved, ui_languages) -> str:
    """The saved choice, else the first supported Windows UI language."""
    chosen = i18n.normalise(saved)
    if chosen is not None:
        return chosen
    return i18n.language_from(ui_languages)


def install_qt_translator(app, code: str):
    """Translate Qt's own buttons (Yes, Cancel...) and dialogs; None if absent."""
    if code == i18n.ENGLISH:
        return None
    folders = [QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)]
    try:
        import PySide6
        folders.append(str(Path(PySide6.__file__).resolve().parent
                           / "translations"))
    except (ImportError, OSError):
        pass
    translator = QTranslator(app)
    for folder in folders:
        if folder and translator.load(f"qtbase_{code}", folder):
            app.installTranslator(translator)
            return translator
    return None


def restart_command() -> tuple[str, list[str]]:
    """How to start this app again (frozen executable or source script)."""
    if getattr(sys, "frozen", False):
        return sys.executable, []
    script = Path(__file__).resolve().parents[1] / "spartacus_gui.py"
    return sys.executable, [str(script)]


def known_title_version(base_dir: Path) -> str | None:
    """The recorded version, else the one the saves prove, else None."""
    try:
        configured = server_config.read_title_version(
            server_config.config_path(base_dir))
    except ValueError:
        return None
    if configured is not None:
        return configured
    from_saves = migration_coordinator.title_version_from_saves(
        Path(base_dir) / "data")
    return from_saves.value if from_saves is not None else None


def configured_title_version(base_dir: Path) -> str:
    """The version to preselect; Start still refuses to run on this default."""
    return known_title_version(base_dir) or server_config.DEFAULT_TITLE_VERSION


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
        self.server_tab.start_guard = self._confirm_title_version
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
            item = QListWidgetItem(f"{glyph}   {tr(name)}")
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
        self.language_combo = QComboBox()
        self.language_combo.setObjectName("languageCombo")
        self.language_combo.setToolTip(tr("Language"))
        for code, name in i18n.LANGUAGES.items():
            self.language_combo.addItem(name, code)
        self.language_combo.setCurrentIndex(
            self.language_combo.findData(i18n.current()))

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
                "⚔  " + tr("Welcome - set up RPCS3 first"),
                tr("Choose your RPCS3 folder. The game, its version and its "
                   "executable are found and checked automatically; then "
                   "press Install / repair setup. You only need to do this "
                   "once."))
        low = patch_installer.low_integrity_problem()
        if low:
            # Shown before anything else: every write would be refused.
            self.nav.setCurrentRow(PATCH_PAGE)
            self.patch_tab.show_attention(
                "⚠  " + tr("Windows is limiting this copy of the "
                                "program"), low)
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
        language_row = QHBoxLayout()
        language_row.setContentsMargins(14, 0, 14, 0)
        language_row.addWidget(self.language_combo, 1)
        side.addLayout(language_row)
        side.addSpacing(6)
        side.addWidget(self.theme_toggle)
        side.addSpacing(8)
        version = label(tr("Server v{version}", version=VERSION),
                        role="muted")
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
        self.language_combo.activated.connect(self._on_language_chosen)
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
        self.page_title.setText(tr(name))
        self.page_subtitle.setText(tr(subtitle))

    # -------------------------------------------------------------- theme
    def apply_palette(self, dark: bool) -> None:
        app = QApplication.instance()
        if app is None:
            return
        selected = theme.DARK if dark else theme.LIGHT
        self._theme_name = selected.name
        theme.apply(app, selected)
        self.theme_toggle.setText(
            "☼  " + tr("Light theme") if dark else "☾  " + tr("Dark theme"))
        self._settings.setValue("theme", selected.name)
        # Write now: a deferred write on destruction would recreate the
        # settings folder after its owner (for example a test) removed it.
        self._settings.sync()

    def _toggle_theme(self) -> None:
        self.apply_palette(self._theme_name != theme.DARK.name)

    # ------------------------------------------------------------ language
    def _on_language_chosen(self, index: int) -> None:
        code = self.language_combo.itemData(index)
        if not code or code == i18n.current():
            return
        self._settings.setValue(SETTING_LANGUAGE, code)
        self._settings.sync()
        # Asked in the chosen language: that is the one the user reads.
        title = i18n.tr_in(code, "Change language")
        if self.process.is_running():
            QMessageBox.information(
                self, title, i18n.tr_in(
                    code, "The new language is used the next time you open "
                          "the app. The server keeps running."))
            return
        answer = QMessageBox.question(
            self, title, i18n.tr_in(
                code, "Restart the app now to use the new language?"),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if answer == QMessageBox.Yes:
            self.restart()

    def restart(self) -> bool:
        """Start a new copy of the app, then close this one."""
        program, arguments = restart_command()
        started, _pid = QProcess.startDetached(program, arguments,
                                               str(self.base_dir))
        if started:
            self.close()
        return started

    # ------------------------------------------------------------- status
    def _show_title_version(self, title_version: str) -> None:
        self.version_chip.setText(tr("Game {version}",
                                     version=title_version))

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

    # ------------------------------------------------------ version check
    def _detected_game_version(self) -> str | None:
        root = self.patch_tab.rpcs3_root()
        if root is None:
            return None
        try:
            return patch_installer.detected_game_version(root)
        except (OSError, ValueError):
            return None

    def _remember_title_version(self, title_version: str) -> None:
        self.server_tab.version_combo.setCurrentText(title_version)
        path = server_config.config_path(self.base_dir)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(server_config.encode_title_version(title_version),
                            encoding="utf-8")
        except OSError as error:
            # This start still uses the right version on its command line.
            self.server_tab._append_event({
                "kind": "warning",
                "message": tr("Could not record the game version: {error}",
                              error=error),
            })

    def _confirm_title_version(self, selected: str) -> bool:
        """Start only on a version something vouches for, never the default."""
        known = known_title_version(self.base_dir)
        detected = self._detected_game_version()
        if detected is None:
            if known is not None:
                return True
            self.nav.setCurrentRow(PATCH_PAGE)
            self.patch_tab.show_attention(
                "⚠  " + tr("Which version of the game do you have?"),
                tr("The server could not tell, and the wrong version puts "
                   "your saves in the wrong folder. Choose your RPCS3 folder "
                   "and press Install / repair setup, then start the "
                   "server."))
            return False
        if known is None:
            self._remember_title_version(detected)
            return True
        if detected == selected:
            return True
        answer = QMessageBox.question(
            self, tr("Game version mismatch"),
            tr("RPCS3 has game version {detected}, but the server is set to "
               "{selected}. Saves from the other version are refused, so "
               "progress would not be kept.\n\nSwitch the server to "
               "{detected}?\n\nEach version keeps its own saves.",
               detected=detected, selected=selected),
            QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
            QMessageBox.Yes)
        if answer == QMessageBox.Yes:
            self._remember_title_version(detected)
        return answer != QMessageBox.Cancel

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
            "message": tr("The game logged in but did not start loading its "
                          "saves - the compatibility patch is not active."),
        })
        self.nav.setCurrentRow(PATCH_PAGE)
        self.patch_tab.show_attention(
            "⚠  " + tr("The compatibility patch did not take effect"),
            tr("The game logged in but never started loading its saves, so "
               "RPCS3 did not apply the patch. Close RPCS3, press Check again "
               "to read its last boot, then Install / repair setup and "
               "cold-boot."))
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
            self, tr("The server is still running"),
            tr("The server is still running. Stop it and close the window?"
               "\n\nIf the game is connected: return to the Ludus, wait "
               "about 20 seconds for the native autosave, then close RPCS3 "
               "first."),
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
    settings = QSettings(str(application_base_dir() / SETTINGS_FILE),
                         QSettings.Format.IniFormat)
    language = i18n.set_language(startup_language(
        settings.value(SETTING_LANGUAGE), QLocale.system().uiLanguages()))
    install_qt_translator(app, language)
    theme.apply(app, theme.DARK)
    window = MainWindow()
    window.show()
    return app.exec()
