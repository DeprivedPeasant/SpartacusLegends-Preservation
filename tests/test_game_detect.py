"""Game detection, executable checks, RPCS3 boot-log parsing, log preservation.

Every test builds its own temporary RPCS3 tree. The reference-ELF tests skip
when decrypted/ is absent; no test runs rpcs3.exe.
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import eboot_source  # noqa: E402
import game_detect  # noqa: E402
import ppu_hash  # noqa: E402
from test_adaptive_patch import (  # noqa: E402
    ELVES, TITLE_ID, make_rpcs3_tree, unprotected_variant_elf)

V100 = "PPU-81471d050c14f4d20b4027686f8b571dafd32394"
V106 = "PPU-131aece6ae8526d13307be925f48c87f73c43799"
VARIANT = "PPU-af74addba068e9fd8ac2636ecca9bcdfb991ab4c"


def boot(path_hash: str, *, applied: str | None, title: str = TITLE_ID,
         writes: int = 4) -> str:
    """One RPCS3 boot section, shaped like the real v0.0.42 log lines."""
    lines = [
        "\u00b7! 0:01:37.486443 SYS: Emulator::BootGame: path='C:/RPCS3/"
        f"dev_hdd0/game/{title}', title_id='{title}', direct=0",
        "\u00b7! 0:01:37.522183 PAT: Loading patch config file C:/RPCS3/"
        "config/patch_config.yml",
    ]
    if applied is not None:
        lines.append(
            f"\u00b7S 0:01:37.624326 PAT: Applied patch (hash='{applied}', "
            "description='Spartacus Legends - Server emulator compatibility',"
            " author='Spartacus Legends preservation project', "
            f"patch_version='4.2', file_version='1.2') (<- {writes})")
    lines.append(
        "\u00b7S 0:01:37.624423 ppu_loader: PPU executable hash: "
        f"{path_hash} (<- {writes if applied else 0})")
    return "\n".join(lines) + "\n"


class BootLogTests(unittest.TestCase):
    def parse(self, text):
        return game_detect.parse_boot_log(text, Path("RPCS3.log"))

    def test_no_spartacus_boot_is_none(self):
        self.assertIsNone(self.parse("RPCS3 v0.0.42 started\n"))
        self.assertIsNone(self.parse(boot(V100, applied=V100,
                                          title="BLUS00000")))

    def test_applied_patch_is_reported_with_its_write_count(self):
        status = self.parse(boot(V106, applied=V106, writes=6))
        self.assertEqual(status.executable_hash, V106)
        self.assertTrue(status.compatibility_applied)
        self.assertEqual(status.compatibility_writes, 6)
        self.assertIn("6 writes", status.summary())

    def test_boot_without_the_patch_names_the_executable(self):
        status = self.parse(boot(VARIANT, applied=None))
        self.assertEqual(status.executable_hash, VARIANT)
        self.assertFalse(status.compatibility_applied)
        self.assertIn("WITHOUT", status.summary())
        self.assertIn(VARIANT, status.summary())

    def test_only_the_last_spartacus_boot_counts(self):
        text = (boot(V100, applied=V100)
                + boot(VARIANT, applied=None)
                + boot("PPU-" + "0" * 40, applied=None, title="BLUS00000"))
        status = self.parse(text)
        self.assertEqual(status.executable_hash, VARIANT)
        self.assertFalse(status.compatibility_applied)

    def test_patch_for_another_hash_is_not_counted(self):
        status = self.parse(boot(VARIANT, applied=V100))
        self.assertFalse(status.compatibility_applied)

    def test_log_is_found_in_the_log_folder(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "log").mkdir()
            (root / "log" / "RPCS3.log").write_bytes(
                boot(V100, applied=V100).encode("utf-8"))
            status = game_detect.last_boot_status(root)
            self.assertTrue(status.compatibility_applied)
            self.assertIsNone(game_detect.last_boot_status(root / "missing"))


class GameDetectionTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.workspace = Path(self._temp.name)

    def tree(self, app_version="01.00", eboot: bytes | None = None):
        root = make_rpcs3_tree(self.workspace / "RPCS3",
                               app_version=app_version)
        if eboot is not None:
            usrdir = root / "dev_hdd0" / "game" / TITLE_ID / "USRDIR"
            usrdir.mkdir()
            (usrdir / "EBOOT.BIN").write_bytes(eboot)
        return root

    def test_detects_the_game_and_its_eboot_from_the_rpcs3_folder(self):
        root = self.tree("01.06", eboot=b"SCE\0placeholder")
        game = game_detect.detect_game(root)
        self.assertEqual(game.title_id, TITLE_ID)
        self.assertEqual(game.app_version, "01.06")
        self.assertTrue(game.supported_version)
        self.assertEqual(game.eboot_path.name, "EBOOT.BIN")
        self.assertIn("version 01.06", game.describe())

    def test_patches_folder_is_accepted_and_missing_game_is_none(self):
        root = self.tree()
        self.assertIsNotNone(game_detect.detect_game(root / "patches"))
        empty = make_rpcs3_tree(self.workspace / "Empty")
        for child in (empty / "dev_hdd0").rglob("PARAM.SFO"):
            child.unlink()
        self.assertIsNone(game_detect.detect_game(empty))

    def test_missing_eboot_is_reported(self):
        game = game_detect.detect_game(self.tree())
        self.assertIsNone(game.eboot_path)
        with self.assertRaises(game_detect.DetectionError):
            game_detect.check_executable(game)

    def test_supported_executable(self):
        if not ELVES["01.00"].is_file():
            self.skipTest("decrypted reference ELF absent")
        game = game_detect.detect_game(
            self.tree(eboot=ELVES["01.00"].read_bytes()))
        check = game_detect.check_executable(game)
        self.assertEqual(check.ppu_hash, V100)
        self.assertEqual(check.status, game_detect.STATUS_SUPPORTED)
        self.assertEqual(check.supported_version, "01.00")
        self.assertIn("supported 01.00", check.summary())

    def test_different_dump_is_unknown_but_patchable(self):
        variant = unprotected_variant_elf()
        if variant is None:
            self.skipTest("decrypted reference ELF absent")
        root = self.tree(eboot=variant)
        check = game_detect.check_executable(game_detect.detect_game(root))
        self.assertEqual(check.status, game_detect.STATUS_UNKNOWN)
        self.assertTrue(check.can_generate)
        self.assertIsNone(check.problem)
        self.assertIn("will generate", check.summary())
        # Once its section exists the dump is reported as generated.
        imported = root / "patches" / "imported_patch.yml"
        imported.write_text(f"{ppu_hash.ppu_hash(variant)}:\n",
                            encoding="utf-8")
        check = game_detect.check_executable(game_detect.detect_game(root))
        self.assertEqual(check.status, game_detect.STATUS_GENERATED)

    def test_unpatchable_dump_says_why(self):
        if not ELVES["01.00"].is_file():
            self.skipTest("decrypted reference ELF absent")
        import adaptive_patch
        data = bytearray(ELVES["01.00"].read_bytes())
        # Corrupt the readiness site itself: a new hash, and no exact match.
        elf = adaptive_patch.ElfImage(bytes(data))
        site = 0x00105710
        for segment in elf.segments:
            if segment.vaddr <= site < segment.vaddr + segment.filesz:
                data[segment.offset + (site - segment.vaddr)] ^= 0x01
                break
        root = self.tree("01.00", eboot=bytes(data))
        check = game_detect.check_executable(game_detect.detect_game(root))
        self.assertEqual(check.status, game_detect.STATUS_UNKNOWN)
        self.assertFalse(check.can_generate)
        self.assertTrue(check.problem)
        self.assertIn("cannot be patched", check.summary())


class NoDecryptTests(unittest.TestCase):
    """Known EBOOTs and RPCS3's own log answer without running rpcs3.exe."""

    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.root = make_rpcs3_tree(Path(self._temp.name) / "RPCS3")
        usrdir = self.root / "dev_hdd0" / "game" / TITLE_ID / "USRDIR"
        usrdir.mkdir()
        self.eboot = usrdir / "EBOOT.BIN"
        self.eboot.write_bytes(b"SCE\0" + b"encrypted" * 8)
        self.game = game_detect.detect_game(self.root)
        no_decrypt = mock.patch.object(
            game_detect.eboot_source, "decrypt_with_rpcs3",
            side_effect=AssertionError("rpcs3.exe must not be started"))
        no_decrypt.start()
        self.addCleanup(no_decrypt.stop)

    def boot_for(self, ppu: str, *, path=None, newer=True):
        mtime = self.eboot.stat().st_mtime + (60 if newer else -60)
        return game_detect.BootStatus(
            Path("RPCS3.log"), ppu, 6, True, 6,
            eboot_path=str(path or self.eboot), log_mtime=mtime)

    def test_known_eboot_is_recognised_by_its_file_hash(self):
        import hashlib
        digest = hashlib.sha256(self.eboot.read_bytes()).hexdigest()
        with mock.patch.dict(game_detect.KNOWN_EBOOTS,
                             {digest: (V106, False)}):
            check = game_detect.check_executable(self.game)
        self.assertEqual(check.ppu_hash, V106)
        self.assertEqual(check.status, game_detect.STATUS_SUPPORTED)
        self.assertEqual(check.basis, "known EBOOT")

    def test_known_variant_is_patchable_without_decrypting(self):
        import hashlib
        digest = hashlib.sha256(self.eboot.read_bytes()).hexdigest()
        with mock.patch.dict(game_detect.KNOWN_EBOOTS,
                             {digest: (VARIANT, True)}):
            check = game_detect.check_executable(self.game)
        self.assertEqual(check.status, game_detect.STATUS_UNKNOWN)
        self.assertTrue(check.can_generate)

    def test_rpcs3_log_hash_is_used_for_the_same_unchanged_eboot(self):
        check = game_detect.check_executable(
            self.game, boot=self.boot_for(V100))
        self.assertEqual(check.status, game_detect.STATUS_SUPPORTED)
        self.assertEqual(check.basis, "RPCS3's last boot")

    def test_log_hash_is_ignored_when_it_cannot_vouch_for_this_file(self):
        cases = {
            "another EBOOT": self.boot_for(V100, path=self.root / "x.BIN"),
            "EBOOT changed after the boot": self.boot_for(V100, newer=False),
            "a new dump still needs its code": self.boot_for(VARIANT),
        }
        for name, boot in cases.items():
            with self.subTest(name):
                with mock.patch.object(game_detect.patch_installer,
                                       "rpcs3_is_running",
                                       return_value=False):
                    with self.assertRaises(AssertionError):
                        game_detect.check_executable(self.game, boot=boot)

    def test_log_records_which_eboot_booted(self):
        text = boot(V106, applied=V106, writes=6) + (
            "\u00b7! 0:01:37.487286 SYS: Path: C:/RPCS3/dev_hdd0/game/"
            f"{TITLE_ID}/USRDIR/EBOOT.BIN\n")
        status = game_detect.parse_boot_log(text, Path("RPCS3.log"))
        self.assertEqual(status.eboot_path,
                         f"C:/RPCS3/dev_hdd0/game/{TITLE_ID}/USRDIR/EBOOT.BIN")

    def test_known_table_agrees_with_the_reference_executables(self):
        supported = set(game_detect.known_hashes())
        for digest, (ppu, can_generate) in game_detect.KNOWN_EBOOTS.items():
            self.assertEqual(len(digest), 64)
            self.assertEqual(ppu in supported, not can_generate, ppu)


class PreservedLogTests(unittest.TestCase):
    def test_decrypt_restores_rpcs3_logs_it_overwrote(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "RPCS3"
            (root / "log").mkdir(parents=True)
            (root / "rpcs3.exe").write_bytes(b"")
            originals = {
                root / "log" / "RPCS3.log": b"last game boot",
                root / "log" / "RPCS3.log.gz": b"gz",
                root / "RPCS3.buf": b"buffer",
            }
            for path, payload in originals.items():
                path.write_bytes(payload)
            eboot = Path(temp) / "EBOOT.BIN"
            eboot.write_bytes(b"SCE\0encrypted")

            def fake_rpcs3(command, **_kwargs):
                # Behave like rpcs3.exe --decrypt: rewrite the logs, then
                # write the decrypted ELF beside the copy.
                for path in originals:
                    path.write_bytes(b"decrypt run")
                (root / "log" / "TTY.log").write_bytes(b"")
                Path(command[-1]).with_suffix(".elf").write_bytes(
                    b"\x7fELF decrypted")
                return subprocess.CompletedProcess(command, 0, b"", b"")

            with mock.patch.object(eboot_source.subprocess, "run",
                                   side_effect=fake_rpcs3):
                with eboot_source.open_eboot(eboot, root,
                                             allow_decrypt=True) as data:
                    self.assertTrue(data.startswith(b"\x7fELF"))
            for path, payload in originals.items():
                self.assertEqual(path.read_bytes(), payload, path)

    def test_rpcs3_never_inherits_qt_settings(self):
        environment = eboot_source.rpcs3_environment({
            "PATH": "C:/Windows",
            "QT_QPA_PLATFORM": "offscreen",
            "QT_PLUGIN_PATH": "C:/frozen/PySide6/plugins",
            "qt_qpa_fontdir": "C:/Windows/Fonts",
            "QML2_IMPORT_PATH": "C:/frozen/qml",
        })
        self.assertEqual(environment, {"PATH": "C:/Windows"})

    def test_rpcs3_never_sees_the_frozen_apps_bundle(self):
        bundle = r"C:\Users\Jake\AppData\Local\Temp\_MEI219602"
        environment = eboot_source.rpcs3_environment({
            "Path": ";".join([bundle, bundle + r"\PySide6",
                              r"C:\Windows\System32", r"C:\Tools"]),
            "_PYI_APPLICATION_HOME_DIR": bundle,
            "_MEIPASS2": bundle,
            "USERNAME": "Jake",
        }, bundle_dir=bundle)
        self.assertEqual(environment, {
            "Path": r"C:\Windows\System32;C:\Tools",
            "USERNAME": "Jake",
        })

    def test_dll_directory_is_reset_for_the_launch_and_restored(self):
        calls = []
        kernel32 = mock.Mock()
        kernel32.SetDllDirectoryW.side_effect = calls.append
        fake_ctypes = mock.Mock()
        fake_ctypes.windll.kernel32 = kernel32
        with mock.patch.object(eboot_source.sys, "frozen", True,
                               create=True), \
                mock.patch.object(eboot_source.sys, "_MEIPASS", "C:/_MEI1",
                                  create=True), \
                mock.patch.object(eboot_source.os, "name", "nt"), \
                mock.patch.dict(sys.modules, {"ctypes": fake_ctypes}):
            with eboot_source.outside_program_dll_search():
                self.assertEqual(calls, [None])
        self.assertEqual(calls, [None, "C:/_MEI1"])
        # From source (not frozen) nothing is touched.
        calls.clear()
        with mock.patch.dict(sys.modules, {"ctypes": fake_ctypes}):
            with eboot_source.outside_program_dll_search():
                pass
        self.assertEqual(calls, [])

    def _preserve_with_copy(self, copy):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "RPCS3"
            (root / "log").mkdir(parents=True)
            log = root / "log" / "RPCS3.log"
            log.write_bytes(b"last game boot")
            real_copy = eboot_source.shutil.copy2
            with mock.patch.object(eboot_source.time, "sleep"), \
                    mock.patch.object(eboot_source.shutil, "copy2",
                                      side_effect=copy(real_copy, log)):
                try:
                    with eboot_source.preserved_run_files(
                            root, Path(temp) / "saved"):
                        log.write_bytes(b"decrypt run")
                except eboot_source.EbootSourceError as error:
                    return log.read_bytes(), error
            return log.read_bytes(), None

    def test_restore_waits_for_a_briefly_held_log(self):
        def copy(real_copy, log):
            blocked = iter([True, True, False])

            def fake(source, target, *args, **kwargs):
                if Path(target) == log and next(blocked, False):
                    raise PermissionError(13, "in use")
                return real_copy(source, target, *args, **kwargs)
            return fake

        payload, error = self._preserve_with_copy(copy)
        self.assertIsNone(error)
        self.assertEqual(payload, b"last game boot")

    def test_a_log_that_stays_locked_is_kept_not_lost(self):
        def copy(real_copy, log):
            def fake(source, target, *args, **kwargs):
                if Path(target) == log:
                    raise PermissionError(13, "in use")
                return real_copy(source, target, *args, **kwargs)
            return fake

        _payload, error = self._preserve_with_copy(copy)
        self.assertIsNotNone(error)
        message = str(error)
        self.assertIn("previous log is saved as", message)
        self.assertIn("RPCS3.log.before-decrypt", message)

    def test_kept_copy_sits_beside_the_locked_log(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "RPCS3"
            (root / "log").mkdir(parents=True)
            log = root / "log" / "RPCS3.log"
            log.write_bytes(b"last game boot")
            real_copy = eboot_source.shutil.copy2

            def fake(source, target, *args, **kwargs):
                if Path(target) == log and Path(source).parent != log.parent:
                    raise PermissionError(13, "in use")
                return real_copy(source, target, *args, **kwargs)

            with mock.patch.object(eboot_source.time, "sleep"), \
                    mock.patch.object(eboot_source.shutil, "copy2",
                                      side_effect=fake):
                with self.assertRaises(eboot_source.EbootSourceError):
                    with eboot_source.preserved_run_files(
                            root, Path(temp) / "saved"):
                        log.write_bytes(b"decrypt run")
            self.assertEqual(
                (root / "log" / "RPCS3.log.before-decrypt").read_bytes(),
                b"last game boot")

    def test_known_executable_is_answered_from_the_cache(self):
        if not ELVES["01.00"].is_file():
            self.skipTest("decrypted reference ELF absent")
        with tempfile.TemporaryDirectory() as temp:
            root = make_rpcs3_tree(Path(temp) / "RPCS3")
            usrdir = root / "dev_hdd0" / "game" / TITLE_ID / "USRDIR"
            usrdir.mkdir()
            # An "encrypted" EBOOT: only the cache can answer for it.
            (usrdir / "EBOOT.BIN").write_bytes(b"SCE\0" + b"x" * 64)
            game = game_detect.detect_game(root)
            cache = {}
            with mock.patch.object(
                    game_detect.eboot_source, "decrypt_with_rpcs3",
                    return_value=(ELVES["01.00"].read_bytes(),
                                  Path(temp) / "gone")), \
                    mock.patch.object(game_detect.patch_installer,
                                      "rpcs3_is_running",
                                      return_value=False):
                first = game_detect.check_executable(game, cache=cache)
            self.assertEqual(first.ppu_hash, V100)
            self.assertEqual(len(cache), 1)
            # RPCS3 now open: no decrypt is possible, but the cache knows.
            with mock.patch.object(game_detect.patch_installer,
                                   "rpcs3_is_running", return_value=True):
                second = game_detect.check_executable(game, cache=cache)
                self.assertEqual(second.status,
                                 game_detect.STATUS_SUPPORTED)
                with self.assertRaises(game_detect.RPCS3RunningError):
                    game_detect.check_executable(game, cache={})


if __name__ == "__main__":
    unittest.main()
