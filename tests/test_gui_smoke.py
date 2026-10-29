"""GUI smoke test: construct the main window offscreen.

The window is constructed against a temporary ``base_dir`` and the server is
never started: this test must not bind a port or read real save data.  The
whole module is skipped when PySide6 is not installed, so the console test run
still works on a bare Python install.
"""

import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))

try:
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QApplication
except ImportError:  # PySide6 is optional for a headless test run.
    QApplication = None
    QColor = None


@unittest.skipIf(QApplication is None, "PySide6 is not installed")
class GuiSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyle("Fusion")

    def setUp(self):
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from test_patch_installer import pin_medium_integrity
        pin_medium_integrity(self)

    def test_low_integrity_copy_says_so_at_startup(self):
        from server_gui.main_window import MainWindow, PATCH_PAGE
        import patch_installer

        with tempfile.TemporaryDirectory() as temp, \
                mock.patch.object(
                    patch_installer, "low_integrity_problem",
                    return_value=patch_installer.LOW_INTEGRITY_HELP):
            window = MainWindow(base_dir=Path(temp))
            try:
                self.assertEqual(window.nav.currentRow(), PATCH_PAGE)
                self.assertIn("limiting",
                              window.patch_tab.attention.heading.text())
                self.assertIn("Low integrity",
                              window.patch_tab.attention.text.text())
            finally:
                window.close()

    def test_main_window_constructs_offline_with_all_four_pages(self):
        from server_gui.main_window import MainWindow

        with tempfile.TemporaryDirectory() as temp:
            window = MainWindow(base_dir=Path(temp))
            try:
                self.assertEqual(window.stack.count(), 4)
                self.assertEqual(
                    window.page_names(),
                    ["Server", "Player", "Items", "Patch setup"])
                window.nav.setCurrentRow(2)
                self.assertIs(window.stack.currentWidget(), window.items_tab)
                self.assertEqual(window.page_title.text(), "Items")
                self.assertEqual(
                    window.server_tab.status_label.text(), "Stopped")
                # Status is a glyph plus the word, never colour alone.
                self.assertIn("Stopped", window.status_pill.text())
                self.assertFalse(window.process.is_running())
                self.assertTrue(window.server_tab.start_button.isEnabled())
                self.assertFalse(window.server_tab.stop_button.isEnabled())
                self.assertEqual(
                    window.server_tab.selected_title_version(), "01.00")
                self.assertIn("agree",
                              window.player_tab.mismatch_label.text())
                self.assertTrue(window.player_tab.gold.isEnabled())
                # Nothing to install until an RPCS3 folder is chosen.
                self.assertFalse(window.patch_tab.install_button.isEnabled())
            finally:
                window.close()

    def test_first_run_opens_patch_setup_until_setup_is_completed(self):
        from server_gui.main_window import MainWindow, PATCH_PAGE

        with tempfile.TemporaryDirectory() as temp:
            window = MainWindow(base_dir=Path(temp))
            try:
                self.assertEqual(window.nav.currentRow(), PATCH_PAGE)
                self.assertIs(window.stack.currentWidget(), window.patch_tab)
                self.assertTrue(window.patch_tab.attention.isVisibleTo(
                    window.patch_tab))
                self.assertIn("Welcome",
                              window.patch_tab.attention.heading.text())
                window.patch_tab.mark_completed(True)
            finally:
                window.close()
            # Settings live beside the app; a completed setup opens normally.
            self.assertTrue((Path(temp) / "gui-settings.ini").is_file())
            window = MainWindow(base_dir=Path(temp))
            try:
                self.assertEqual(window.nav.currentRow(), 0)
                self.assertFalse(window.patch_tab.attention.isVisibleTo(
                    window.patch_tab))
            finally:
                window.close()

    def test_patch_setup_returns_when_the_server_never_confirms_it(self):
        from server_gui.main_window import MainWindow, PATCH_PAGE

        with tempfile.TemporaryDirectory() as temp:
            window = MainWindow(base_dir=Path(temp))
            try:
                window.patch_tab.mark_completed(True)
                window.patch_tab.clear_attention()
                window.nav.setCurrentRow(0)
                # Confirmed: the watchdog stops and setup stays complete.
                window._on_server_event({"kind": "connected"})
                window._on_server_event({"kind": "logged_in"})
                self.assertTrue(window.patch_timer.isActive())
                window._on_server_event({"kind": "patch_confirmed"})
                self.assertFalse(window.patch_timer.isActive())
                self.assertEqual(window.nav.currentRow(), 0)
                # A new session that logs in but never loads its saves.
                window._on_server_event({"kind": "connected"})
                window._on_server_event({"kind": "logged_in"})
                self.assertTrue(window.patch_timer.isActive())
                window.patch_timer.stop()
                window._patch_not_confirmed()
                self.assertEqual(window.nav.currentRow(), PATCH_PAGE)
                self.assertIn("did not take effect",
                              window.patch_tab.attention.heading.text())
                feed = window.server_tab.events
                self.assertIn("compatibility patch is not active",
                              feed.item(feed.count() - 1).text())
            finally:
                window.close()

    def test_patch_page_flags_an_unused_rpcs3_and_writes_nothing(self):
        import sys as _sys
        _sys.path.insert(0, str(Path(__file__).resolve().parent))
        from test_adaptive_patch import TITLE_ID, make_rpcs3_tree
        from server_gui.main_window import MainWindow
        from server_gui import patch_tab as patch_module

        with tempfile.TemporaryDirectory() as temp:
            root = make_rpcs3_tree(Path(temp) / "PS3. NEW")
            (root / "dev_hdd0" / "game" / TITLE_ID / "PARAM.SFO").unlink()
            (root / "config" / "rpcn.yml").unlink()
            app = Path(temp) / "app"
            config = app / "data" / "server-config.json"
            config.parent.mkdir(parents=True)
            config.write_text('{"title_version":"01.06"}\n',
                              encoding="utf-8")
            before = {path: path.read_bytes()
                      for path in root.rglob("*") if path.is_file()}
            window = MainWindow(base_dir=app)
            page = window.patch_tab
            try:
                page.rpcs3_folder.setText(str(root))
                page.recheck()
                self.assertTrue(page.wait_for_worker())
                self.app.processEvents()
                self.assertIn("never been used to play",
                              page.game_label.text())
                self.assertIn("right RPCS3 folder",
                              page.attention.heading.text())
                checks = [page.checklist.topLevelItem(index).text(1)
                          for index in range(page.checklist.topLevelItemCount())]
                self.assertEqual(len(checks), 1)
                buttons = patch_module.QMessageBox.StandardButton
                with mock.patch.object(
                        patch_module.patch_installer, "rpcs3_is_running",
                        return_value=False):
                    # Cancel: nothing is written anywhere.
                    with mock.patch.object(patch_module.QMessageBox,
                                           "question",
                                           return_value=buttons.Cancel):
                        page._install()
                    self.assertEqual(
                        {path: path.read_bytes() for path in root.rglob("*")
                         if path.is_file()}, before)
                    # Confirmed: installs, but the version stays unguessed.
                    with mock.patch.object(
                            patch_module.QMessageBox, "question",
                            return_value=buttons.Yes), \
                            mock.patch.object(
                                patch_module.QInputDialog, "getItem",
                                return_value=(patch_module.LEAVE_VERSION,
                                              True)):
                        page._install()
                        self.assertTrue(page.wait_for_worker())
                        self.app.processEvents()
                        self.assertTrue(page.wait_for_worker())
                        self.app.processEvents()
                self.assertTrue((root / "patches" /
                                 "imported_patch.yml").is_file())
                self.assertEqual(config.read_text(encoding="utf-8"),
                                 '{"title_version":"01.06"}\n')
                self.assertIn("left unchanged", page.result_detail.text())
            finally:
                window.close()

    def test_patch_page_detects_and_installs_a_different_dump(self):
        import sys as _sys
        _sys.path.insert(0, str(Path(__file__).resolve().parent))
        from test_adaptive_patch import (
            TITLE_ID, make_rpcs3_tree, unprotected_variant_elf)
        from server_gui.main_window import MainWindow
        from server_gui import patch_tab as patch_module
        import ppu_hash

        variant = unprotected_variant_elf()
        if variant is None:
            self.skipTest("decrypted reference ELF absent")
        with tempfile.TemporaryDirectory() as temp:
            root = make_rpcs3_tree(Path(temp) / "RPCS3")
            usrdir = root / "dev_hdd0" / "game" / TITLE_ID / "USRDIR"
            usrdir.mkdir()
            (usrdir / "EBOOT.BIN").write_bytes(variant)
            window = MainWindow(base_dir=Path(temp) / "app")
            page = window.patch_tab
            try:
                page.rpcs3_folder.setText(str(root))
                page.recheck()
                self.assertTrue(page.wait_for_worker())
                self.app.processEvents()
                variant_hash = ppu_hash.ppu_hash(variant)
                self.assertIn("version 01.00", page.game_label.text())
                self.assertIn(variant_hash, page.exe_label.text())
                self.assertIn("generate", page.exe_label.text())
                self.assertTrue(page.install_button.isEnabled())
                answers = iter([patch_module.QMessageBox.StandardButton.Yes])
                with mock.patch.object(
                        patch_module.QMessageBox, "question",
                        side_effect=lambda *a, **k: next(answers)), \
                        mock.patch.object(
                            patch_module.patch_installer,
                            "rpcs3_is_running", return_value=False):
                    page._install()
                    self.assertTrue(page.wait_for_worker())
                    self.app.processEvents()
                    self.assertTrue(page.wait_for_worker())
                    self.app.processEvents()
                imported = (root / "patches" / "imported_patch.yml") \
                    .read_text(encoding="utf-8")
                self.assertEqual(imported.count(f"{variant_hash}:"), 1)
                self.assertTrue(page.setup_completed())
                self.assertIn("generated", page.exe_label.text())
                # The server's version setting went to the app folder only.
                self.assertTrue((Path(temp) / "app" / "data" /
                                 "server-config.json").is_file())
            finally:
                window.close()

    def test_light_and_dark_themes_apply(self):
        from server_gui import theme
        from server_gui.main_window import MainWindow

        with tempfile.TemporaryDirectory() as temp:
            window = MainWindow(base_dir=Path(temp))
            try:
                window.apply_palette(True)
                self.assertEqual(self.app.palette().window().color(),
                                 QColor(theme.DARK.window))
                self.assertIn(theme.DARK.accent, self.app.styleSheet())
                window.apply_palette(False)
                self.assertEqual(self.app.palette().window().color(),
                                 QColor(theme.LIGHT.window))
                self.assertIn(theme.LIGHT.accent, self.app.styleSheet())
            finally:
                window.apply_palette(True)
                window.close()

    def test_every_status_has_a_distinct_glyph_and_its_word(self):
        from server_gui import server_process, theme

        statuses = [server_process.STATUS_STOPPED,
                    server_process.STATUS_STARTING,
                    server_process.STATUS_READY,
                    server_process.STATUS_GAME_CONNECTED,
                    server_process.STATUS_STOPPING,
                    server_process.STATUS_ERROR]
        glyphs = [theme.STATUS_GLYPHS[status] for status in statuses]
        self.assertEqual(len(set(glyphs)), len(glyphs))
        for status in statuses:
            self.assertIn(status, theme.status_text(status))

    def test_player_page_edits_01_06_balances_on_the_server_copy(self):
        import json
        from server_gui.main_window import MainWindow

        with tempfile.TemporaryDirectory() as temp:
            data = Path(temp) / "data"
            native = data / "usercontent" / "01.06" / "80000001" / "1.bin"
            native.parent.mkdir(parents=True)
            native.write_bytes(bytes(0x15B8))
            (data / "profile-01.06.json").write_text(json.dumps(
                {"gold": 12, "silver": 34, "fame": 56, "owned_items": []}),
                encoding="utf-8")
            window = MainWindow(base_dir=Path(temp))
            try:
                window.server_tab.version_combo.setCurrentText("01.06")
                player = window.player_tab
                self.assertEqual(
                    (player.gold.value(), player.silver.value(),
                     player.fame.value()), (12, 34, 56))
                self.assertIn("server only", player.native_label.text())
                self.assertTrue(player.save_button.isEnabled())
                # Live fame is allowed on 01.06, refused on 01.00.
                player.set_server_running(True)
                self.assertTrue(player.fame.isEnabled())
                self.assertFalse(player.fame_reason.isVisibleTo(player))
                player.set_title_version("01.00")
                self.assertFalse(player.fame.isEnabled())
                player.set_server_running(False)
            finally:
                window.close()

    def test_machine_lines_are_parsed_without_a_running_server(self):
        from server_gui.server_process import (
            EVENT_PREFIX,
            REPLY_PREFIX,
            parse_server_line,
        )

        kind, payload = parse_server_line(
            EVENT_PREFIX + '{"kind":"ready","message":"Server ready"}')
        self.assertEqual(kind, "event")
        self.assertEqual(payload["kind"], "ready")
        kind, payload = parse_server_line(
            REPLY_PREFIX + '{"id":1,"ok":true,"gold":5}')
        self.assertEqual(kind, "reply")
        self.assertEqual(payload["gold"], 5)
        self.assertEqual(parse_server_line("ordinary detail line"),
                         ("plain", "ordinary detail line"))


if __name__ == "__main__":
    unittest.main()
