#!/usr/bin/env python3
"""Items tab: grouped owned-item lists.

Offline, item edits are part of :func:`save_editor.save` (both save files are
backed up).  Live, they go through the server's experimental control commands;
removing a purchased Ludus slot is blocked client-side because the server also
refuses it and a slot is a purchased entitlement.

No item names are invented: the groups are ID ranges only.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QMessageBox,
    QSpinBox,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .server_process import ServerProcess
from .widgets import Banner, Card, button, label

try:
    import save_editor
except ImportError:  # Imported as tools.server_gui.items_tab by tests.
    from tools import save_editor


SPIN_MAXIMUM = 2_147_483_647
EXPERIMENTAL_LIVE_TEXT = (
    "Experimental: live item edits are not live-proven yet. An added item or "
    "changed Boost quantity should appear at the next shop inventory request "
    "or at the next login's purchase replay.")
LIVE_SLOT_BLOCKED_TEXT = (
    "A purchased Ludus slot (IDs 80002-80007) cannot be removed while the "
    "server is running. It is a purchased entitlement that the server replays "
    "at login. Stop the server and remove it offline instead.")
OFFLINE_SLOT_WARNING = (
    "This is a purchased Ludus slot entitlement (IDs 80002-80007). Removing it "
    "changes your purchased Ludus capacity: the server replays only the saved "
    "slot purchases at login. Remove it?")


class ItemsTab(QWidget):
    """Grouped item ownership editing for offline and live modes."""

    def __init__(self, process: ServerProcess, base_dir: Path,
                 initial_title_version: str = "01.00", parent=None):
        super().__init__(parent)
        self.setObjectName("page")
        self.process = process
        self.base_dir = Path(base_dir)
        self.data_dir = self.base_dir / "data"
        self._title_version = initial_title_version
        self._server_running = False
        self._owned: list[int] = []
        self._quantities: dict[int, int] = {}

        self.mode_banner = Banner()
        self.experimental_label = label(
            "\u26a0  " + EXPERIMENTAL_LIVE_TEXT, role="muted", wrap=True)
        self.experimental_label.setVisible(False)
        self.legend_label = label(
            "Items are grouped by ID range only; no item names are asserted.",
            role="muted", wrap=True)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Item ID", "Uses"])
        self.tree.setRootIsDecorated(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
        header = self.tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)

        self.item_id = QSpinBox()
        self.item_id.setRange(0, SPIN_MAXIMUM)
        self.item_id.setToolTip("Item ID to add, for example 60006 for a Boost.")
        self.quantity = QSpinBox()
        self.quantity.setRange(0, save_editor.MAX_QUANTITY)
        self.add_button = button("+  Add item", "primary")
        self.remove_button = button("Remove selected", "danger")
        self.quantity_button = button("Set Boost uses")
        self.save_button = button("Save items to save files", "primary",
                                  "large")
        self.revert_button = button("Reload from disk")
        self.status_label = label(role="muted", wrap=True)
        self.selected_label = label("No item selected.", role="muted",
                                    wrap=True)

        self._build_layout()
        self._connect_signals()
        self.set_server_running(False)

    def _build_layout(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 22, 26, 22)
        layout.setSpacing(16)
        layout.addWidget(self.mode_banner)
        layout.addWidget(self.experimental_label)

        owned = Card("Owned items")
        owned.body.addWidget(self.tree, 1)
        owned.body.addWidget(self.legend_label)

        editor = Card("Edit", "Boosts are IDs 60000-60063 and keep a use "
                      "count (0-99). Ludus slots are 80002-80007.")
        editor.setMinimumWidth(300)
        editor.setMaximumWidth(380)
        form = QFormLayout()
        form.setSpacing(10)
        form.addRow(label("ITEM ID", role="statLabel"), self.item_id)
        form.addRow(label("USES", role="statLabel"), self.quantity)
        editor.body.addLayout(form)
        editor.body.addWidget(self.add_button)
        editor.body.addSpacing(8)
        editor.body.addWidget(label("SELECTED", role="statLabel"))
        editor.body.addWidget(self.selected_label)
        editor.body.addWidget(self.quantity_button)
        editor.body.addWidget(self.remove_button)
        editor.body.addStretch(1)

        columns = QHBoxLayout()
        columns.setSpacing(16)
        columns.addWidget(owned, 1)
        columns.addWidget(editor)
        layout.addLayout(columns, 1)

        save_row = QHBoxLayout()
        save_row.setSpacing(10)
        save_row.addWidget(self.save_button)
        save_row.addWidget(self.revert_button)
        save_row.addSpacing(12)
        save_row.addWidget(self.status_label, 1)
        layout.addLayout(save_row)

    def _connect_signals(self) -> None:
        self.add_button.clicked.connect(self._add)
        self.remove_button.clicked.connect(self._remove)
        self.quantity_button.clicked.connect(self._set_quantity)
        self.save_button.clicked.connect(self._save_offline)
        self.revert_button.clicked.connect(self.refresh_offline)
        self.tree.itemSelectionChanged.connect(self._selection_changed)
        self.process.reply_received.connect(self._on_reply)

    # ---------------------------------------------------------------- mode
    def set_title_version(self, title_version: str) -> None:
        if title_version == self._title_version:
            return
        self._title_version = title_version
        if self._server_running:
            self._request_live_state()
        else:
            self.refresh_offline()

    def set_server_running(self, running: bool) -> None:
        self._server_running = running
        self.experimental_label.setVisible(running)
        self.save_button.setEnabled(not running)
        self.revert_button.setText(
            "Reload live items" if running else "Reload from disk")
        if running:
            self.mode_banner.set_message(
                "\u21c4  Live editing (experimental)",
                "The server is running, so item edits go through the server. "
                "Saving to the save files is disabled while the server owns "
                "them.")
            self.status_label.setText("Live items from the server.")
            self._request_live_state()
        else:
            self.mode_banner.set_message(
                "\u270e  Offline editing",
                "The server is stopped. Changes are written only when you "
                "press Save, after the save files are backed up.")
            self.status_label.setText("")
            self.refresh_offline()

    def refresh_offline(self) -> None:
        try:
            state = save_editor.load(self.data_dir, self._title_version)
        except save_editor.SaveEditorError as error:
            self._owned = []
            self._quantities = {}
            self._rebuild_tree()
            self.status_label.setText(f"Error: {error}")
            self.save_button.setEnabled(False)
            return
        self._owned = list(state.owned_items)
        self._quantities = dict(state.item_quantities)
        self.save_button.setEnabled(not self._server_running)
        self._rebuild_tree()
        if not self._server_running:
            self.status_label.setText(
                f"Loaded {len(self._owned)} owned item(s) from the save files.")

    def _request_live_state(self) -> None:
        self.process.write_command({"cmd": "get_economy"})

    # --------------------------------------------------------------- tree
    def _quantity_text(self, item_id: int) -> str:
        if save_editor.is_boost(item_id):
            return str(save_editor.effective_quantity(
                self._owned, self._quantities, item_id))
        return ""

    def _rebuild_tree(self) -> None:
        selected = self._selected_item_id()
        self.tree.clear()
        bold = QFont()
        bold.setBold(True)
        for group, items in save_editor.group_items(self._owned).items():
            if not items:
                continue
            group_item = QTreeWidgetItem([f"{group}   \u00b7  {len(items)}",
                                          ""])
            group_item.setFont(0, bold)
            group_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.tree.addTopLevelItem(group_item)
            for item_id in items:
                child = QTreeWidgetItem([str(item_id),
                                         self._quantity_text(item_id)])
                child.setData(0, Qt.ItemDataRole.UserRole, item_id)
                group_item.addChild(child)
        self.tree.expandAll()
        if selected is not None:
            self._select_item(selected)
        self._selection_changed()

    def _selected_item_id(self) -> int | None:
        current = self.tree.currentItem()
        if current is None:
            return None
        value = current.data(0, Qt.ItemDataRole.UserRole)
        return int(value) if value is not None else None

    def _select_item(self, item_id: int) -> None:
        for index in range(self.tree.topLevelItemCount()):
            group = self.tree.topLevelItem(index)
            for child_index in range(group.childCount()):
                child = group.child(child_index)
                if child.data(0, Qt.ItemDataRole.UserRole) == item_id:
                    self.tree.setCurrentItem(child)
                    return

    def _selection_changed(self) -> None:
        item_id = self._selected_item_id()
        boost = item_id is not None and save_editor.is_boost(item_id)
        self.quantity_button.setEnabled(boost)
        self.quantity.setEnabled(True)
        if item_id is not None:
            self.quantity.setValue(
                save_editor.effective_quantity(
                    self._owned, self._quantities, item_id)
                if save_editor.is_boost(item_id) else 1)
        if item_id is None:
            self.selected_label.setText("No item selected.")
        elif save_editor.is_ludus_slot(item_id):
            self.selected_label.setText(
                f"Item {item_id} - purchased Ludus slot entitlement.")
        elif boost:
            uses = save_editor.effective_quantity(
                self._owned, self._quantities, item_id)
            self.selected_label.setText(
                f"Item {item_id} - Boost with {uses} use(s).")
        else:
            self.selected_label.setText(f"Item {item_id}.")
        if not boost:
            self.quantity_button.setToolTip(
                "Quantity is editable for Boost IDs 60000-60063 only.")
        else:
            self.quantity_button.setToolTip("")

    # ------------------------------------------------------------- actions
    def _add(self) -> None:
        item_id = self.item_id.value()
        if save_editor.is_boost(item_id):
            quantity = self.quantity.value()
        else:
            quantity = 1
        if self._server_running:
            command = {"cmd": "add_item", "item_id": item_id,
                       "quantity": quantity}
            self.process.write_command(command)
            self.status_label.setText(
                f"Sent live add of item {item_id} (experimental).")
            return
        try:
            self._owned = list(save_editor.add_owned_item(
                self._owned, item_id))
            if save_editor.is_boost(item_id):
                self._quantities = save_editor.set_item_quantity(
                    self._quantities, self._owned, item_id, quantity)
        except save_editor.SaveEditorError as error:
            QMessageBox.warning(self, "Item not added", str(error))
            return
        self._rebuild_tree()
        self.status_label.setText(
            f"Added item {item_id}. Press Save to write it to the save files.")

    def _remove(self) -> None:
        item_id = self._selected_item_id()
        if item_id is None:
            QMessageBox.information(
                self, "No item selected",
                "Select an item under one of the ranges first.")
            return
        if self._server_running:
            if save_editor.is_ludus_slot(item_id):
                QMessageBox.information(
                    self, "Ludus slot cannot be removed live",
                    LIVE_SLOT_BLOCKED_TEXT)
                return
            self.process.write_command(
                {"cmd": "remove_item", "item_id": item_id})
            self.status_label.setText(
                f"Sent live removal of item {item_id} (experimental).")
            return
        if save_editor.is_ludus_slot(item_id):
            confirm = QMessageBox.question(
                self, "Remove a purchased Ludus slot?",
                OFFLINE_SLOT_WARNING,
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel)
            if confirm != QMessageBox.StandardButton.Yes:
                return
        try:
            self._owned = list(save_editor.remove_owned_item(
                self._owned, item_id))
            self._quantities.pop(item_id, None)
        except save_editor.SaveEditorError as error:
            QMessageBox.warning(self, "Item not removed", str(error))
            return
        self._rebuild_tree()
        self.status_label.setText(
            f"Removed item {item_id}. Press Save to write it to the save "
            "files.")

    def _set_quantity(self) -> None:
        item_id = self._selected_item_id()
        if item_id is None or not save_editor.is_boost(item_id):
            QMessageBox.information(
                self, "Boost quantity only",
                "Quantity is editable for Boost IDs 60000-60063 only.")
            return
        quantity = self.quantity.value()
        if self._server_running:
            self.process.write_command({
                "cmd": "set_item_quantity",
                "item_id": item_id,
                "quantity": quantity,
            })
            self.status_label.setText(
                f"Sent live quantity {quantity} for item {item_id} "
                "(experimental).")
            return
        try:
            self._quantities = save_editor.set_item_quantity(
                self._quantities, self._owned, item_id, quantity)
        except save_editor.SaveEditorError as error:
            QMessageBox.warning(self, "Quantity not set", str(error))
            return
        self._rebuild_tree()
        self.status_label.setText(
            f"Set item {item_id} quantity to {quantity}. Press Save to write "
            "it to the save files.")

    def _save_offline(self) -> None:
        try:
            result = save_editor.save(
                self.data_dir,
                self._title_version,
                owned_items=self._owned,
                item_quantities=self._quantities,
                server_running=self.process.is_running(),
            )
        except save_editor.SaveEditorError as error:
            QMessageBox.critical(self, "Save refused", str(error))
            return
        lines = [f"Items saved. Pre-edit backup: {result.backup_dir}"]
        lines.extend(result.warnings)
        QMessageBox.information(self, "Save complete", "\n\n".join(lines))
        self.refresh_offline()

    # ------------------------------------------------------------ live data
    def _on_reply(self, reply: dict) -> None:
        if not self._server_running:
            return
        if not reply.get("ok"):
            self.status_label.setText(
                f"Error: {reply.get('error', 'unknown error')}")
            return
        if "owned_items" not in reply:
            return
        self._owned = [int(item) for item in reply["owned_items"]]
        quantities = reply.get("item_quantities", {})
        self._quantities = {
            int(item): int(quantity)
            for item, quantity in quantities.items()
        } if isinstance(quantities, dict) else {}
        self._rebuild_tree()
        self.status_label.setText(
            f"Live items from the server: {len(self._owned)} owned item(s).")
