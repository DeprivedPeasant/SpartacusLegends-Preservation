#!/usr/bin/env python3
"""Patch setup page: point at RPCS3, and everything else is found and checked.

From the RPCS3 folder alone the page finds Spartacus Legends, reads RPCS3's
log for the last boot, decrypts a temporary copy of the game's EBOOT with that
RPCS3, and hashes it. One button then installs (or repairs) the setup,
generating a matching patch for a different dump of the game when needed.

The page only orchestrates; inspection and writes are done by the Qt-free
:mod:`game_detect`, :mod:`patch_installer`, :mod:`eboot_source` and
:mod:`adaptive_patch` modules. Slow work (decrypting, hashing, installing)
runs on a worker thread so the window stays responsive.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings, QThread, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLineEdit,
    QMessageBox,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .widgets import Banner, Card, button, label

try:
    import adaptive_patch
    import eboot_source
    import game_detect
    import patch_installer
except ImportError:  # Imported as tools.server_gui.patch_tab by tests.
    from tools import adaptive_patch, eboot_source, game_detect, \
        patch_installer


SETTING_FOLDER = "setup/rpcs3_folder"
SETTING_COMPLETED = "setup/completed"

OK = "✓"
WARN = "⚠"
BAD = "✖"
BUSY = "◔"

LEAVE_VERSION = "Leave the server's version unchanged"
UNUSED_CONFIRM = (
    "{problem}\n\nInstalling here writes the patch and network settings into "
    "this RPCS3 only - the RPCS3 you play from would still be unpatched (on "
    "01.06 the game then hangs on \"Updating Game Data\").\n\n"
    "Install into this folder anyway?")
VERSION_QUESTION = (
    "The game's version could not be detected from this RPCS3 folder, so the "
    "server's version setting will not be guessed. It decides which saves "
    "the server uses.\n\nWhich version of Spartacus Legends do you play?")

ADAPTIVE_CONFIRM = (
    "Your game is a different dump of Spartacus Legends, so the shipped "
    "patch does not match its executable ({hash}).\n\n"
    "The installer can generate a matching patch by locating the same "
    "instructions in your executable. This is EXPERIMENTAL: every patch site "
    "was found exactly once and checked, but it has only been proven on one "
    "other dump so far. Nothing is written if any site is uncertain.\n\n"
    "Generate and install the patch for this dump?")


class _SettingsCache:
    """Executable check results remembered in the GUI settings file."""

    GROUP = "executables"

    def __init__(self, settings: QSettings | None):
        self.settings = settings

    def get(self, key, default=None):
        if self.settings is None:
            return default
        value = self.settings.value(f"{self.GROUP}/{self._safe(key)}")
        return default if value is None else str(value)

    def __setitem__(self, key, value) -> None:
        if self.settings is not None:
            self.settings.setValue(f"{self.GROUP}/{self._safe(key)}", value)
            self.settings.sync()

    @staticmethod
    def _safe(key: str) -> str:
        # QSettings treats '/' as a group separator and ':' is awkward in
        # INI keys; the key is hex digests and a version, so this is lossless.
        return key.replace(":", "_").replace("/", "_")


class _Worker(QThread):
    """Run one callable off the GUI thread and hand back its result."""

    done = Signal(object, object)  # (result, error)

    def __init__(self, function, parent=None):
        super().__init__(parent)
        self._function = function

    def run(self) -> None:
        try:
            result = self._function()
        except Exception as error:  # reported to the user, never swallowed
            self.done.emit(None, error)
        else:
            self.done.emit(result, None)


class PatchTab(QWidget):
    """Detect, check, install and verify the RPCS3 setup."""

    setup_installed = Signal(str)  # title version written for the server

    def __init__(self, settings: QSettings | None = None,
                 server_base_dir: Path | None = None, parent=None):
        super().__init__(parent)
        self.setObjectName("page")
        self.settings = settings
        self.server_base_dir = server_base_dir
        self._worker: _Worker | None = None
        self._game = None
        self._check = None
        self._boot = None
        self._unused = None
        self._detected_version = None

        self.attention = Banner()
        self.attention.setVisible(False)

        self.rpcs3_folder = QLineEdit()
        self.rpcs3_folder.setPlaceholderText(
            "The RPCS3 folder - the one containing rpcs3.exe")
        self.rpcs3_browse = button("Browse...")
        self.recheck_button = button("Check again")

        self.game_label = label(role="muted", wrap=True, selectable=True)
        self.exe_label = label(role="muted", wrap=True, selectable=True)
        self.boot_label = label(role="muted", wrap=True, selectable=True)

        self.install_button = button("Install / repair setup", "primary",
                                     "large")
        self.summary = label(role="muted", wrap=True)

        self.checklist = QTreeWidget()
        self.checklist.setHeaderLabels(["Result", "Check"])
        self.checklist.setColumnWidth(0, 120)
        self.checklist.setRootIsDecorated(False)
        self.result_detail = label(role="muted", wrap=True, selectable=True)

        self.manual_elf = QCheckBox(
            "Automatic decryption does not work for me - use a decrypted "
            ".elf instead (RPCS3 Utilities > Decrypt PS3 Binaries)")
        self.elf_path = QLineEdit()
        self.elf_path.setPlaceholderText("Decrypted EBOOT .elf")
        self.elf_browse = button("Browse...")
        self.elf_row = QWidget()

        self._build_layout()
        self._connect_signals()
        self._set_unchecked("Choose your RPCS3 folder to begin.")

        folder = self._setting(SETTING_FOLDER, "")
        if folder:
            self.rpcs3_folder.setText(str(folder))

    # -------------------------------------------------------------- layout
    def _build_layout(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 22, 26, 22)
        layout.setSpacing(16)
        layout.addWidget(self.attention)

        folder = Card("RPCS3", "Everything else - the game, its version "
                      "and its executable - is found from this folder.")
        row = QHBoxLayout()
        row.addWidget(self.rpcs3_folder, 1)
        row.addWidget(self.rpcs3_browse)
        row.addWidget(self.recheck_button)
        folder.body.addLayout(row)
        layout.addWidget(folder)

        game = Card("Your game")
        form = QFormLayout()
        form.setSpacing(10)
        form.addRow(label("GAME", role="statLabel"), self.game_label)
        form.addRow(label("EXECUTABLE", role="statLabel"), self.exe_label)
        form.addRow(label("LAST BOOT", role="statLabel"), self.boot_label)
        game.body.addLayout(form)
        actions = QHBoxLayout()
        actions.setSpacing(12)
        actions.addWidget(self.install_button)
        actions.addWidget(self.summary, 1)
        game.body.addLayout(actions)
        layout.addWidget(game)

        checks = Card("Setup checklist")
        checks.body.addWidget(self.checklist, 1)
        checks.body.addWidget(self.result_detail)
        checks.body.addWidget(self.manual_elf)
        elf_layout = QHBoxLayout(self.elf_row)
        elf_layout.setContentsMargins(0, 0, 0, 0)
        elf_layout.addWidget(self.elf_path, 1)
        elf_layout.addWidget(self.elf_browse)
        self.elf_row.setVisible(False)
        checks.body.addWidget(self.elf_row)
        layout.addWidget(checks, 1)

    def _connect_signals(self) -> None:
        self.rpcs3_browse.clicked.connect(self._browse_rpcs3)
        self.rpcs3_folder.editingFinished.connect(self.recheck)
        self.recheck_button.clicked.connect(self.recheck)
        self.install_button.clicked.connect(self._install)
        self.manual_elf.toggled.connect(self.elf_row.setVisible)
        self.manual_elf.toggled.connect(lambda _on: self.recheck())
        self.elf_browse.clicked.connect(self._browse_elf)

    # ------------------------------------------------------------ settings
    def _setting(self, key, default=None):
        if self.settings is None:
            return default
        return self.settings.value(key, default)

    def _set_setting(self, key, value) -> None:
        if self.settings is not None:
            self.settings.setValue(key, value)
            self.settings.sync()

    def setup_completed(self) -> bool:
        value = self._setting(SETTING_COMPLETED, False)
        return str(value).lower() in ("true", "1")

    def mark_completed(self, completed: bool = True) -> None:
        self._set_setting(SETTING_COMPLETED, bool(completed))

    # -------------------------------------------------------------- public
    def show_attention(self, heading: str, text: str) -> None:
        self.attention.set_message(heading, text)
        self.attention.setVisible(True)

    def clear_attention(self) -> None:
        self.attention.setVisible(False)

    def rpcs3_root(self) -> Path | None:
        text = self.rpcs3_folder.text().strip().strip('"')
        return Path(text) if text else None

    def recheck(self) -> None:
        """Re-detect the game and re-check its executable in the background."""
        root = self.rpcs3_root()
        if root is None:
            self._set_unchecked("Choose your RPCS3 folder to begin.")
            return
        if self._worker is not None and self._worker.isRunning():
            return
        try:
            root = patch_installer.find_rpcs3_root(root)
        except (OSError, ValueError) as error:
            self._set_unchecked(f"{BAD}  {error}")
            return
        self._set_setting(SETTING_FOLDER, str(root))
        elf = self._manual_elf()
        cache = _SettingsCache(self.settings)
        self._set_busy("Finding the game and checking its executable...")

        def work():
            # The boot log is read first: it is the user's evidence of the
            # last game boot (decrypting restores it, but order is cheap).
            boot = game_detect.last_boot_status(root)
            game = game_detect.detect_game(root)
            check = None
            check_error = None
            if game is not None and (game.eboot_path or elf):
                try:
                    check = game_detect.check_executable(
                        game, source=elf, cache=cache, boot=boot)
                except (OSError, ValueError, eboot_source.EbootSourceError,
                        game_detect.DetectionError) as error:
                    check_error = str(error)
            unused = patch_installer.unused_folder_problem(root)
            detected = patch_installer.detected_game_version(root)
            return root, game, check, check_error, boot, unused, detected

        self._start(work, self._on_checked)

    # ------------------------------------------------------------- display
    def _set_unchecked(self, text: str) -> None:
        self._game = self._check = self._boot = None
        self._unused = self._detected_version = None
        self.game_label.setText(text)
        self.exe_label.setText("-")
        self.boot_label.setText("-")
        self.install_button.setEnabled(False)
        self.summary.setText("")

    def _set_busy(self, text: str) -> None:
        self.game_label.setText(f"{BUSY}  {text}")
        self.install_button.setEnabled(False)
        self.recheck_button.setEnabled(False)

    def _on_checked(self, result, error) -> None:
        self.recheck_button.setEnabled(True)
        if error is not None:
            self._set_unchecked(f"{BAD}  {error}")
            return
        root, game, check, check_error, boot, unused, detected = result
        self._game, self._check, self._boot = game, check, boot
        self._unused, self._detected_version = unused, detected
        if unused:
            # One plain message, not separate "no game" and "no RPCN" lines.
            self.game_label.setText(f"{BAD}  {unused}")
            self.exe_label.setText("-")
            self.boot_label.setText("-")
            self.show_attention("\u26a0  Is this the right RPCS3 folder?",
                                unused)
            self.install_button.setEnabled(True)
            self._verify()
            return
        if game is None:
            self.game_label.setText(
                f"{BAD}  Spartacus Legends was not found in {root}. Install "
                f"the USA release ({patch_installer.TITLE_ID}) in this RPCS3 "
                "and let RPCS3 list it, then check again.")
            self.exe_label.setText("-")
            self.boot_label.setText("-")
            self.install_button.setEnabled(True)
            self._verify()
            return
        mark = OK if game.supported_version else WARN
        text = f"{mark}  {game.describe()}"
        if not game.supported_version:
            text += (" - only 01.00 and 01.06 are supported, so the patch "
                     "will not apply.")
        self.game_label.setText(text)

        if check is not None:
            if check.status == game_detect.STATUS_SUPPORTED:
                self.exe_label.setText(f"{OK}  {check.summary()}")
            elif check.status == game_detect.STATUS_GENERATED:
                self.exe_label.setText(f"{OK}  {check.summary()}")
            elif check.can_generate:
                self.exe_label.setText(f"{WARN}  {check.summary()}")
            else:
                self.exe_label.setText(f"{BAD}  {check.summary()}")
        elif check_error and "RPCS3 is open" in check_error:
            self.exe_label.setText(f"{WARN}  {check_error}")
        elif check_error:
            self.exe_label.setText(
                f"{WARN}  Could not check the executable: {check_error} "
                "Tick the option below to use a decrypted .elf instead.")
        else:
            self.exe_label.setText(f"{WARN}  No EBOOT.BIN was found in "
                                   f"{game.game_dir}.")

        if boot is None:
            self.boot_label.setText(
                "No Spartacus Legends boot in RPCS3's log yet.")
        elif boot.unreadable:
            self.boot_label.setText(f"{WARN}  {boot.summary()}")
        elif boot.compatibility_applied:
            self.boot_label.setText(f"{OK}  {boot.summary()}")
        else:
            self.boot_label.setText(f"{BAD}  {boot.summary()}")

        self.install_button.setEnabled(True)
        self._verify()

    def _show_checks(self, checks) -> bool:
        self.checklist.clear()
        required_ok = True
        advisory_ok = True
        for passed, message, required in checks:
            if passed:
                result = f"{OK}  OK"
            elif required:
                result = f"{BAD}  MISSING"
                required_ok = False
            else:
                result = f"{WARN}  WARNING"
                advisory_ok = False
            item = QTreeWidgetItem([result, message])
            item.setToolTip(1, message)
            self.checklist.addTopLevelItem(item)
        if not required_ok:
            self.summary.setText(
                f"{BAD}  Setup incomplete - press Install / repair setup.")
        elif not advisory_ok:
            self.summary.setText(
                f"{WARN}  Installed, but the WARNING items can still stop "
                "the game from reaching the main menu.")
        else:
            self.summary.setText(
                f"{OK}  Setup OK - start the server, then cold-boot the game.")
        return required_ok

    # ------------------------------------------------------------- actions
    def _browse_rpcs3(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Select the RPCS3 folder (containing rpcs3.exe)",
            self.rpcs3_folder.text())
        if folder:
            self.rpcs3_folder.setText(folder)
            self.recheck()

    def _browse_elf(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(
            self, "Select the decrypted EBOOT .elf", "",
            "ELF files (*.elf *.ELF);;All files (*)")
        if path:
            self.elf_path.setText(path)
            self.recheck()

    def _manual_elf(self) -> Path | None:
        if not self.manual_elf.isChecked():
            return None
        text = self.elf_path.text().strip().strip('"')
        return Path(text) if text else None

    def _verify(self) -> bool:
        root = self.rpcs3_root()
        if root is None:
            return False
        try:
            checks = patch_installer.verify_setup(
                root, self.server_base_dir,
                executable_hash=(self._check.ppu_hash
                                 if self._check is not None else None),
                boot_status=self._boot)
        except (OSError, ValueError) as error:
            self.result_detail.setText(f"Verification failed: {error}")
            return False
        return self._show_checks(checks)

    def _install(self) -> None:
        root = self.rpcs3_root()
        if root is None:
            return
        if patch_installer.rpcs3_is_running():
            QMessageBox.warning(
                self, "Close RPCS3 first",
                "Close RPCS3 before installing the setup. RPCS3 rewrites its "
                "configuration when it closes, which would undo the change.")
            return
        allow_unused = False
        if self._unused:
            answer = QMessageBox.question(
                self, "Is this the right RPCS3 folder?",
                UNUSED_CONFIRM.format(problem=self._unused),
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel)
            if answer != QMessageBox.StandardButton.Yes:
                return
            allow_unused = True
        title_version = None
        if self._detected_version is None:
            choices = [LEAVE_VERSION,
                       *sorted(patch_installer.SUPPORTED_BUILDS)]
            choice, accepted = QInputDialog.getItem(
                self, "Which game version?", VERSION_QUESTION, choices, 0,
                False)
            if not accepted:
                return
            if choice != LEAVE_VERSION:
                title_version = choice
        check = self._check
        adaptive = False
        if check is not None and check.status == game_detect.STATUS_UNKNOWN:
            if not check.can_generate:
                answer = QMessageBox.question(
                    self, "This dump cannot be patched automatically",
                    "Your game's executable is a different dump and the "
                    f"patch sites could not be located safely:\n\n"
                    f"{check.problem}\n\nThe network settings can still be "
                    "installed, but the compatibility patch will not apply "
                    "to this executable. Continue anyway?",
                    QMessageBox.StandardButton.Yes
                    | QMessageBox.StandardButton.Cancel,
                    QMessageBox.StandardButton.Cancel)
                if answer != QMessageBox.StandardButton.Yes:
                    return
            else:
                answer = QMessageBox.question(
                    self, "Generate a patch for your dump?",
                    ADAPTIVE_CONFIRM.format(hash=check.ppu_hash),
                    QMessageBox.StandardButton.Yes
                    | QMessageBox.StandardButton.Cancel,
                    QMessageBox.StandardButton.Cancel)
                if answer != QMessageBox.StandardButton.Yes:
                    return
                adaptive = True
        elif check is not None and check.status == game_detect.STATUS_GENERATED:
            adaptive = True  # keep the generated section current
        source = self._manual_elf() or (
            self._game.eboot_path if self._game is not None else None)
        server_base_dir = self.server_base_dir

        def work():
            return patch_installer.install_setup(
                root, server_base_dir,
                eboot=source if adaptive else None,
                adaptive=adaptive, allow_decrypt=True,
                allow_unused_folder=allow_unused,
                title_version=title_version)

        self._set_busy("Installing the setup...")
        self._start(work, self._on_installed)

    def _on_installed(self, result, error) -> None:
        self.recheck_button.setEnabled(True)
        self.install_button.setEnabled(True)
        if error is not None:
            refused = isinstance(error, adaptive_patch.PatchResolutionError)
            if isinstance(error, patch_installer.InstallWriteError):
                # Its message already says whether anything changed.
                outcome = ""
            elif refused or isinstance(
                    error, patch_installer.UnusedRPCS3FolderError):
                outcome = "\n\nNothing was changed."
            else:
                outcome = ("\n\nSome files may have been changed; each "
                           "changed file has a dated .bak copy beside it.")
            self.result_detail.setText(
                "Install failed; nothing was guessed."
                if refused else f"Install failed: {error}")
            QMessageBox.critical(self, "Install failed", f"{error}{outcome}")
            self.recheck()
            return
        lines = [f"Installed the patches in {result.imported_patch}",
                 f"Server set to game version {result.title_version}"
                 if result.server_config_written else
                 f"Server version left unchanged in {result.server_config}",
                 "PPU cache cleared" if result.cache_cleared
                 else "PPU cache was already clear"]
        if result.adaptive_report is not None:
            lines.append(f"Generated a patch for {result.adaptive_hash} "
                         f"(experimental). Report: {result.adaptive_report}")
        lines.extend(f"Backup: {path}" for path in result.backups)
        self.result_detail.setText("\n".join(lines))
        self.mark_completed(True)
        self.clear_attention()
        if result.server_config_written and result.title_version:
            self.setup_installed.emit(result.title_version)
        self.recheck()

    # -------------------------------------------------------------- worker
    def _start(self, function, on_done) -> None:
        worker = _Worker(function, self)
        worker.done.connect(on_done)
        worker.finished.connect(worker.deleteLater)
        self._worker = worker
        worker.start()

    def wait_for_worker(self, timeout_ms: int = 30000) -> bool:
        """Block until background work finishes (tests and shutdown)."""
        worker = self._worker
        if worker is None:
            return True
        try:
            return worker.wait(timeout_ms)
        except RuntimeError:  # already deleted after finishing
            return True
