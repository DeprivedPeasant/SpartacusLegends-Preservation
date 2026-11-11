#!/usr/bin/env python3
"""Player page: offline balance editing, or live edits through the server.

The page decides which mode is safe from the server process state:

- Server stopped: edit the save files through :mod:`save_editor` (which backs
  them up first).
- Server running: balances go through the server's control channel and show
  "Pending" until the server reports a ``balance_synced`` event.

Where the balances live depends on the build. 01.00 keeps them in the native
profile (plus the server's companion copy). 01.06 keeps them only on the
server, which sends them to the game at login (Shop method 19) and after each
fight (method 20); fame can therefore be edited live on 01.06 but not 01.00.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QHBoxLayout,
    QInputDialog,
    QMessageBox,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from . import theme
from .server_process import ServerProcess
from .widgets import Banner, Card, button, label

try:
    import save_editor
    import server_control
    from i18n import N_, tr
except ImportError:  # Imported as tools.server_gui.player_tab by tests.
    from tools import save_editor, server_control
    from tools.i18n import N_, tr


SPIN_MAXIMUM = 2_147_483_647  # QSpinBox is a signed 32-bit int widget.
LIVE_PENDING_TEXT = N_(
    "Pending - appears after your next fight or shop purchase")
LIVE_PENDING_TEXT_V106 = N_(
    "Pending - appears after your next fight, shop purchase or login")
LIVE_SYNCED_TEXT = N_("Synced - the game has received these values")
FAME_LIVE_REASON = N_(
    "Fame is offline-only on 01.00: no live fame update is known for that "
    "client. Stop the server and edit fame offline.")

BALANCES = (
    ("gold", N_("GOLD"), "◆"),
    ("silver", N_("SILVER"), "◇"),
    ("fame", N_("FAME"), "★"),
)


class StatCard(Card):
    """One balance: glyph, caption, an editable value and its saved value."""

    def __init__(self, caption: str, glyph: str, parent=None):
        super().__init__(parent=parent)
        top = QHBoxLayout()
        top.addWidget(label(glyph, role="statGlyph"))
        top.addSpacing(6)
        top.addWidget(label(tr(caption), role="statLabel"))
        top.addStretch(1)
        self.body.addLayout(top)
        self.spin = QSpinBox()
        self.spin.setRange(0, SPIN_MAXIMUM)
        self.spin.setGroupSeparatorShown(True)
        self.spin.setToolTip(tr(
            "The save format stores a 32-bit value; this field accepts up to "
            "{maximum:,}.", maximum=SPIN_MAXIMUM))
        theme.set_props(self.spin, role="statValue")
        self.body.addWidget(self.spin)
        self.saved = label(role="muted", wrap=True)
        self.body.addWidget(self.saved)
        self.reason = label(role="muted", wrap=True)
        self.reason.setVisible(False)
        self.body.addWidget(self.reason)


class PlayerTab(QWidget):
    """Gold/silver/fame editing with an explicit offline/live mode."""

    def __init__(self, process: ServerProcess, base_dir: Path,
                 initial_title_version: str = "01.00", parent=None):
        super().__init__(parent)
        self.setObjectName("page")
        self.process = process
        self.base_dir = Path(base_dir)
        self.data_dir = self.base_dir / "data"
        self._title_version = initial_title_version
        self._server_running = False
        self._state = None
        self._pending_live_balances = False

        self.mode_banner = Banner()
        self.cards = {name: StatCard(caption, glyph)
                      for name, caption, glyph in BALANCES}
        self.gold = self.cards["gold"].spin
        self.silver = self.cards["silver"].spin
        self.fame = self.cards["fame"].spin
        self.fame_reason = self.cards["fame"].reason
        self.fame_reason.setText(tr(FAME_LIVE_REASON))
        self.live_status = label(role="muted", wrap=True)

        self.source_card = Card(tr("Where these values are stored"))
        self.native_label = label(wrap=True, selectable=True)
        self.companion_label = label(wrap=True, selectable=True)
        self.mismatch_label = label(role="muted", wrap=True)
        for widget in (self.native_label, self.companion_label,
                       self.mismatch_label):
            self.source_card.body.addWidget(widget)

        self.save_button = button(tr("Save to save files"), "primary",
                                  "large")
        self.revert_button = button(tr("Reload from disk"))
        self.restore_button = button(tr("Restore backup..."))

        self._build_layout()
        self._connect_signals()
        self.set_server_running(False)

    def _build_layout(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 22, 26, 22)
        layout.setSpacing(16)
        layout.addWidget(self.mode_banner)

        stats = QHBoxLayout()
        stats.setSpacing(16)
        for name, _caption, _glyph in BALANCES:
            stats.addWidget(self.cards[name], 1)
        layout.addLayout(stats)

        actions = QHBoxLayout()
        actions.setSpacing(10)
        actions.addWidget(self.save_button)
        actions.addWidget(self.revert_button)
        actions.addWidget(self.restore_button)
        actions.addSpacing(12)
        actions.addWidget(self.live_status, 1)
        layout.addLayout(actions)

        layout.addWidget(self.source_card)
        layout.addStretch(1)

    def _connect_signals(self) -> None:
        self.save_button.clicked.connect(self._save)
        self.revert_button.clicked.connect(self._revert)
        self.restore_button.clicked.connect(self._restore_backup)
        self.process.reply_received.connect(self._on_reply)
        self.process.event_received.connect(self._on_event)

    # ---------------------------------------------------------------- mode
    def _live_fame(self) -> bool:
        return server_control.live_fame_supported(self._title_version)

    def set_title_version(self, title_version: str) -> None:
        if title_version == self._title_version:
            return
        self._title_version = title_version
        self.set_server_running(self._server_running)

    def set_server_running(self, running: bool) -> None:
        self._server_running = running
        live_fame = self._live_fame()
        self.gold.setEnabled(True)
        self.silver.setEnabled(True)
        self.fame.setEnabled(not running or live_fame)
        self.fame_reason.setVisible(running and not live_fame)
        self.restore_button.setEnabled(not running)
        self.revert_button.setText(
            tr("Reload live values") if running else tr("Reload from disk"))
        self.save_button.setText(
            tr("Send to server") if running else tr("Save to save files"))
        self.save_button.setEnabled(True)
        if running:
            self.mode_banner.set_message(
                "⇄  " + tr("Live editing"),
                tr("The server is running, so gold, silver and fame are "
                   "changed through the server itself. The game picks them "
                   "up at its next fight, shop purchase or login.")
                if live_fame else
                tr("The server is running, so gold and silver are changed "
                   "through the server itself. The game picks them up at its "
                   "next fight or shop purchase."))
            self.live_status.setText(tr("Live values from the server."))
            self._refresh_source_from_disk(last_saved=True)
            self._request_live_state()
        else:
            self.mode_banner.set_message(
                "✎  " + tr("Offline editing"),
                tr("The server is stopped, so the save files are edited "
                   "directly. They are backed up before anything is "
                   "changed."))
            self.live_status.setText("")
            self.refresh_offline()

    def refresh_offline(self) -> None:
        state = self._refresh_source_from_disk(last_saved=False)
        if state is None:
            self.save_button.setEnabled(False)
            return
        self.save_button.setEnabled(True)
        self._show_balances(state.effective_balances)
        self.live_status.setText("")

    def _refresh_source_from_disk(self, last_saved: bool):
        """Describe the on-disk values; returns the state or None on error."""
        try:
            state = save_editor.load(self.data_dir, self._title_version)
        except save_editor.SaveEditorError as error:
            self._state = None
            self.native_label.setText(
                tr("Native profile: could not be read."))
            self.companion_label.setText(
                tr("Server economy file: could not be read."))
            self.mismatch_label.setText(tr("Error: {error}", error=error))
            for card in self.cards.values():
                card.saved.setText("")
            return None
        self._state = state
        for name, card in self.cards.items():
            value = state.effective_balances[name]
            card.saved.setText(
                tr("Last saved: {value:,}", value=value) if last_saved
                else tr("Saved: {value:,}", value=value))

        companion = state.companion_balances
        companion_name = state.paths.companion_path.name
        self.companion_label.setText("▪ " + tr(
            "Server economy ({file}): gold {gold:,}, silver {silver:,}, fame "
            "{fame:,}", file=companion_name, gold=companion["gold"],
            silver=companion["silver"], fame=companion["fame"]))
        if not state.native_holds_balances:
            size = (tr("{size:,} bytes", size=state.native_size)
                    if state.native_present else tr("not created yet"))
            self.native_label.setText("▪ " + tr(
                "Game {version} keeps balances on the server only. They are "
                "sent to the game at login and after each fight. The game's "
                "own profile ({size}) is never changed by this editor.",
                version=self._title_version, size=size))
            self.mismatch_label.setText("")
            return state
        if state.native_present:
            native = state.native_balances or {}
            self.native_label.setText("▪ " + tr(
                "Game profile (1.bin): gold {gold:,}, silver {silver:,}, "
                "fame {fame:,}", **native))
        else:
            self.native_label.setText("▪ " + tr(
                "Game profile (1.bin): not created yet (fresh player). Only "
                "the server economy file will be edited."))
        if state.mismatch:
            fields = ", ".join(tr(field) for field in state.mismatch_fields)
            self.mismatch_label.setText("⚠  " + (
                tr("The game profile and server economy differ ({fields}). "
                   "The running server uses its own in-memory values.",
                   fields=fields)
                if last_saved else
                tr("The game profile and server economy differ ({fields}). "
                   "Saving writes both so they agree.", fields=fields)))
        else:
            self.mismatch_label.setText("✓  " + (
                tr("The game profile and server economy agree.")
                if not last_saved else
                tr("The last saved game profile and server economy agree.")))
        return state

    def _show_balances(self, balances: dict) -> None:
        for name, spin in (("gold", self.gold), ("silver", self.silver),
                           ("fame", self.fame)):
            spin.setValue(max(0, min(SPIN_MAXIMUM, int(balances[name]))))

    # -------------------------------------------------------------- saving
    def _save(self) -> None:
        if self._server_running:
            self._save_live()
        else:
            self._save_offline()

    def _save_offline(self) -> None:
        try:
            result = save_editor.save(
                self.data_dir,
                self._title_version,
                gold=self.gold.value(),
                silver=self.silver.value(),
                fame=self.fame.value(),
                server_running=self.process.is_running(),
            )
        except save_editor.SaveEditorError as error:
            QMessageBox.critical(self, tr("Save refused"), str(error))
            return
        lines = [tr("Balances saved."),
                 tr("Pre-edit backup: {path}", path=result.backup_dir)]
        lines.extend(result.warnings)
        QMessageBox.information(self, tr("Save complete"),
                                "\n\n".join(lines))
        self.refresh_offline()

    def _save_live(self) -> None:
        command = {"cmd": "set_balances", "gold": self.gold.value(),
                   "silver": self.silver.value()}
        if self._live_fame():
            command["fame"] = self.fame.value()
        command_id = self.process.write_command(command)
        if not command_id:
            return
        self._pending_live_balances = True
        self.live_status.setText(
            "◔  " + tr(LIVE_PENDING_TEXT_V106 if self._live_fame()
                       else LIVE_PENDING_TEXT))

    def _revert(self) -> None:
        if self._server_running:
            self._request_live_state()
        else:
            self.refresh_offline()

    def _request_live_state(self) -> None:
        self.process.write_command({"cmd": "get_economy"})

    def _on_reply(self, reply: dict) -> None:
        if not self._server_running:
            return
        if not reply.get("ok"):
            error = reply.get("error", tr("unknown error"))
            self.live_status.setText("✖  " + tr("Error: {error}", error=error))
            return
        updated = False
        for name, spin in (("gold", self.gold), ("silver", self.silver),
                           ("fame", self.fame)):
            if name in reply:
                spin.setValue(max(0, min(SPIN_MAXIMUM, int(reply[name]))))
                updated = True
        if updated and not self._pending_live_balances:
            self.live_status.setText(tr("Live values from the server."))

    def _on_event(self, event: dict) -> None:
        if event.get("kind") != "balance_synced":
            return
        self._pending_live_balances = False
        self.live_status.setText("✓  " + tr(LIVE_SYNCED_TEXT))
        for name, spin in (("gold", self.gold), ("silver", self.silver),
                           ("fame", self.fame)):
            if name in event:
                spin.setValue(max(0, min(SPIN_MAXIMUM, int(event[name]))))

    # ------------------------------------------------------------- restore
    def _restore_backup(self) -> None:
        backups = save_editor.list_backups(self.data_dir)
        if not backups:
            QMessageBox.information(
                self, tr("No backups"),
                tr("There are no save-editor backups in data/backups yet."))
            return
        names = [backup.name for backup in backups]
        name, accepted = QInputDialog.getItem(
            self, tr("Restore backup"),
            tr("Choose a backup. Every file is checked against its SHA-256 "
               "manifest before anything is written."), names, 0, False)
        if not accepted or not name:
            return
        confirm = QMessageBox.question(
            self, tr("Restore this backup?"),
            tr("Replace the current save files with the backup {name}?\n\n"
               "The current files are not backed up again by this step.",
               name=name),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel)
        if confirm != QMessageBox.StandardButton.Yes:
            return
        try:
            result = save_editor.restore_backup(
                self.data_dir, name, server_running=self.process.is_running())
        except save_editor.SaveEditorError as error:
            QMessageBox.critical(self, tr("Restore refused"), str(error))
            return
        QMessageBox.information(
            self, tr("Restore complete"),
            tr("Restored: {files}", files=", ".join(result.restored_files)))
        if self._server_running:
            self._request_live_state()
        else:
            self.refresh_offline()
