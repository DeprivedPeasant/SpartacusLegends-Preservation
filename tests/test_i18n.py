import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest
import unittest.mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from tools import gui_handoff, i18n


def load_message_checker():
    spec = importlib.util.spec_from_file_location(
        "i18n_messages", ROOT / "scripts" / "i18n_messages.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class LanguageEnvironment(unittest.TestCase):
    """Each test starts in English and leaves the variable as it found it."""

    def setUp(self):
        patcher = unittest.mock.patch.dict(os.environ)
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop(i18n.ENV_VAR, None)


class CatalogueTests(unittest.TestCase):
    def test_every_message_is_translated_with_the_same_placeholders(self):
        self.assertEqual(load_message_checker().problems(), [])

    def test_every_translation_formats_with_its_english_values(self):
        checker = load_message_checker()
        for code, catalogue in i18n.CATALOGUES.items():
            for text, translated in catalogue.items():
                names = checker.placeholders(text)
                if not names:
                    continue
                values = {name: 1234 for name in names}
                with self.subTest(language=code, text=text):
                    # Raises if a format spec ({x:,}, {x!r}) is broken.
                    self.assertIn("1", translated.format(**values))


class TranslateTests(LanguageEnvironment):
    def test_english_is_the_default_and_returns_the_source(self):
        self.assertEqual(i18n.current(), "en")
        self.assertEqual(i18n.tr("Start server"), "Start server")
        self.assertEqual(i18n.tr("Game {version}", version="01.06"),
                         "Game 01.06")

    def test_spanish_and_portuguese_are_used_when_chosen(self):
        i18n.set_language("es")
        self.assertEqual(i18n.tr("Start server"), "Iniciar servidor")
        self.assertEqual(i18n.tr("Game {version}", version="01.06"),
                         "Juego 01.06")
        i18n.set_language("pt_BR")
        self.assertEqual(i18n.tr("Start server"), "Iniciar servidor")
        self.assertEqual(i18n.tr("Stop server"), "Parar servidor")

    def test_unknown_text_falls_back_to_english(self):
        i18n.set_language("es")
        self.assertEqual(i18n.tr("not a catalogued message {x}", x=1),
                         "not a catalogued message 1")

    def test_a_broken_translation_still_shows_the_english_message(self):
        i18n.set_language("es")
        broken = {"Game {version}": "Juego {versión}"}
        with unittest.mock.patch.dict(i18n.CATALOGUES["es"], broken):
            self.assertEqual(i18n.tr("Game {version}", version="01.00"),
                             "Game 01.00")

    def test_tr_in_does_not_switch_the_language(self):
        self.assertEqual(i18n.tr_in("es", "Change language"),
                         "Cambiar idioma")
        self.assertNotIn(i18n.ENV_VAR, os.environ)
        i18n.set_language("pt_BR")
        self.assertEqual(i18n.tr_in("es", "Close"), "Cerrar")
        self.assertEqual(i18n.current(), "pt_BR")

    def test_locale_names_map_to_supported_languages(self):
        for name, code in (("es-MX", "es"), ("es_ES.UTF-8", "es"),
                           ("pt-BR", "pt_BR"), ("pt_PT", "pt_BR"),
                           ("en-GB", "en"), ("fr-FR", None), ("", None),
                           (None, None)):
            with self.subTest(name=name):
                self.assertEqual(i18n.normalise(name), code)
        self.assertEqual(i18n.language_from(["fr-FR", "pt-BR", "es"]),
                         "pt_BR")
        self.assertEqual(i18n.language_from(["de-DE"]), "en")

    def test_unsupported_choice_falls_back_to_english(self):
        self.assertEqual(i18n.set_language("de"), "en")
        self.assertEqual(i18n.current(), "en")

    def test_console_follows_windows_only_when_nothing_was_chosen(self):
        with unittest.mock.patch.object(i18n, "system_locale_names",
                                        return_value=["es-AR"]):
            self.assertEqual(i18n.use_system_language_if_unset(), "es")
            i18n.set_language("pt_BR")
            self.assertEqual(i18n.use_system_language_if_unset(), "pt_BR")

    def test_backend_messages_follow_the_language(self):
        from tools import patch_installer
        i18n.set_language("es")
        self.assertIn("NPUB30746", patch_installer.unused_folder_problem(
            Path(tempfile.gettempdir()) / "no-such-rpcs3-folder"))
        self.assertTrue(patch_installer.unused_folder_problem(
            Path(tempfile.gettempdir()) / "no-such-rpcs3-folder")
            .startswith("Probablemente"))
        os.environ.pop(i18n.ENV_VAR)
        self.assertEqual(
            patch_installer.unused_folder_problem(
                Path(tempfile.gettempdir()) / "no-such-rpcs3-folder"),
            patch_installer.UNUSED_FOLDER_MESSAGE)


class GuiHandoffTests(LanguageEnvironment):
    def setUp(self):
        super().setUp()
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.gui = self.base / gui_handoff.GUI_EXE_NAME
        self.gui.write_bytes(b"")
        self.launched = []

    def offer(self, answer="", arguments=(), frozen=True, interactive=True,
              launch_ok=True):
        def launch(gui, language):
            self.launched.append((gui, language))
            return launch_ok

        with unittest.mock.patch("builtins.print"):
            return gui_handoff.offer(
                "SpartacusLegendsServer.exe", self.base, arguments,
                frozen=frozen, interactive=interactive,
                ask=lambda _prompt: answer, launch=launch, language="en")

    def test_double_click_opens_the_app_by_default(self):
        self.assertTrue(self.offer(""))
        self.assertEqual(self.launched, [(self.gui, "en")])

    def test_typing_c_keeps_the_console(self):
        self.assertFalse(self.offer("c"))
        self.assertFalse(self.offer("  Continue"))
        self.assertEqual(self.launched, [])

    def test_no_offer_with_arguments_a_script_or_a_source_checkout(self):
        self.assertFalse(self.offer(arguments=["--console"]))
        self.assertFalse(self.offer(arguments=["--no-wait", "--check"]))
        self.assertFalse(self.offer(interactive=False))
        self.assertFalse(self.offer(frozen=False))
        self.assertEqual(self.launched, [])

    def test_no_offer_without_the_app_beside_it(self):
        self.gui.unlink()
        self.assertFalse(self.offer(""))
        self.assertEqual(self.launched, [])

    def test_a_failed_launch_continues_in_the_console(self):
        self.assertFalse(self.offer("", launch_ok=False))

    def test_the_offer_is_shown_in_the_windows_language(self):
        # gui_handoff may hold the bare-name copy of i18n; patch that one.
        with unittest.mock.patch.object(gui_handoff.i18n,
                                        "system_locale_names",
                                        return_value=["pt-BR"]):
            self.assertEqual(gui_handoff.offer_language(), "pt_BR")
            i18n.set_language("es")
            self.assertEqual(gui_handoff.offer_language(), "es")


class ConsoleFlagTests(unittest.TestCase):
    def test_server_and_installer_accept_the_console_flag(self):
        from tools.spartacus_server import parse_args
        self.assertTrue(parse_args(["--console"]).console)
        from tools import patch_installer
        with unittest.mock.patch.object(sys, "argv",
                                        ["installer", "--console"]):
            self.assertTrue(patch_installer.parse_args().console)


if __name__ == "__main__":
    unittest.main()
