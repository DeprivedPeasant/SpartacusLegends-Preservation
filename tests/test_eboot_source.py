"""EBOOT source resolution: existing ELF vs RPCS3 --decrypt on a copy.

Every subprocess is mocked; no RPCS3 install is ever executed by these tests.
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))

import eboot_source

ENCRYPTED = b"SCE\0encrypted-self"
DECRYPTED = b"\x7fELFdecrypted"


def make_rpcs3(directory: Path) -> Path:
    folder = directory / "RPCS3"
    folder.mkdir()
    (folder / "rpcs3.exe").write_bytes(b"")
    return folder


class ExistingElfTests(unittest.TestCase):
    def test_existing_elf_is_used_without_running_rpcs3(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "EBOOT.elf"
            path.write_bytes(DECRYPTED)
            with mock.patch.object(eboot_source.subprocess, "run") as run:
                with eboot_source.open_eboot(path) as data:
                    self.assertEqual(data, DECRYPTED)
            run.assert_not_called()

    def test_missing_file_is_reported(self):
        with self.assertRaises(eboot_source.EbootSourceError):
            with eboot_source.open_eboot(Path("does-not-exist.bin")):
                pass

    def test_is_elf_rejects_self_header(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "EBOOT.BIN"
            path.write_bytes(ENCRYPTED)
            self.assertFalse(eboot_source.is_elf(path))


class UtilitiesMessageTests(unittest.TestCase):
    def test_encrypted_file_without_opt_in_returns_the_utilities_message(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "EBOOT.BIN"
            path.write_bytes(ENCRYPTED)
            with mock.patch.object(eboot_source.subprocess, "run") as run:
                with self.assertRaises(eboot_source.EbootSourceError) as raised:
                    with eboot_source.open_eboot(path):
                        pass
            run.assert_not_called()
        message = str(raised.exception)
        self.assertIn("not a decrypted ELF", message)
        self.assertIn("Utilities > Decrypt PS3 Binaries", message)

    def test_explicit_decrypt_without_a_folder_explains_what_is_needed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "EBOOT.BIN"
            path.write_bytes(ENCRYPTED)
            with self.assertRaises(eboot_source.EbootSourceError) as raised:
                with eboot_source.open_eboot(path, allow_decrypt=True):
                    pass
        self.assertIn("rpcs3.exe", str(raised.exception))
        self.assertIn("Utilities > Decrypt PS3 Binaries",
                      str(raised.exception))


class DecryptTests(unittest.TestCase):
    def test_explicit_decrypt_runs_on_a_copy_and_cleans_up(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rpcs3 = make_rpcs3(root)
            eboot = root / "game" / "EBOOT.BIN"
            eboot.parent.mkdir()
            eboot.write_bytes(ENCRYPTED)
            copy_dirs = []

            def fake_decrypt(cmd, **kwargs):
                copy = Path(cmd[-1])
                copy_dirs.append(copy.parent)
                (copy.parent / "EBOOT.ELF").write_bytes(DECRYPTED)
                return subprocess.CompletedProcess(cmd, 0, b"", b"")

            with mock.patch.object(
                    eboot_source.subprocess, "run",
                    side_effect=fake_decrypt) as run:
                with eboot_source.open_eboot(
                        eboot, rpcs3, allow_decrypt=True) as data:
                    self.assertEqual(data, DECRYPTED)
                    self.assertEqual(len(copy_dirs), 1)
                    self.assertNotEqual(copy_dirs[0], eboot.parent)
                    self.assertTrue(copy_dirs[0].is_dir())
            self.assertEqual(run.call_count, 1)
            command = run.call_args.args[0]
            self.assertEqual(command[1], "--decrypt")
            self.assertEqual(Path(command[0]), rpcs3 / "rpcs3.exe")
            self.assertEqual(eboot.read_bytes(), ENCRYPTED)
            self.assertFalse(copy_dirs[0].exists())

    def test_nonzero_exit_reports_the_failure_and_cleans_up(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rpcs3 = make_rpcs3(root)
            eboot = root / "EBOOT.BIN"
            eboot.write_bytes(ENCRYPTED)
            copy_dirs = []

            def failing_decrypt(cmd, **kwargs):
                copy_dirs.append(Path(cmd[-1]).parent)
                return subprocess.CompletedProcess(cmd, 1, b"", b"bad licence")

            with mock.patch.object(
                    eboot_source.subprocess, "run",
                    side_effect=failing_decrypt):
                with self.assertRaises(eboot_source.EbootSourceError) as raised:
                    with eboot_source.open_eboot(
                            eboot, rpcs3, allow_decrypt=True):
                        pass
            self.assertIn("exit code 1", str(raised.exception))
            self.assertIn("bad licence", str(raised.exception))
            self.assertIn("Utilities > Decrypt PS3 Binaries",
                          str(raised.exception))
            self.assertFalse(copy_dirs[0].exists())

    def test_timeout_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rpcs3 = make_rpcs3(root)
            eboot = root / "EBOOT.BIN"
            eboot.write_bytes(ENCRYPTED)
            with mock.patch.object(
                    eboot_source.subprocess, "run",
                    side_effect=subprocess.TimeoutExpired("rpcs3.exe", 60)):
                with self.assertRaises(eboot_source.EbootSourceError) as raised:
                    with eboot_source.open_eboot(
                            eboot, rpcs3, allow_decrypt=True):
                        pass
        self.assertIn("did not finish", str(raised.exception))
        self.assertIn("Utilities > Decrypt PS3 Binaries",
                      str(raised.exception))

    def test_missing_decrypted_output_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rpcs3 = make_rpcs3(root)
            eboot = root / "EBOOT.BIN"
            eboot.write_bytes(ENCRYPTED)
            with mock.patch.object(
                    eboot_source.subprocess, "run",
                    return_value=subprocess.CompletedProcess([], 0, b"", b"")):
                with self.assertRaises(eboot_source.EbootSourceError) as raised:
                    with eboot_source.open_eboot(
                            eboot, rpcs3, allow_decrypt=True):
                        pass
        message = str(raised.exception)
        self.assertIn("could not decrypt the executable", message)
        self.assertIn("Utilities > Decrypt PS3 Binaries", message)

    def test_missing_rpcs3_exe_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            empty = root / "NotRPCS3"
            empty.mkdir()
            eboot = root / "EBOOT.BIN"
            eboot.write_bytes(ENCRYPTED)
            with self.assertRaises(eboot_source.EbootSourceError) as raised:
                with eboot_source.open_eboot(
                        eboot, empty, allow_decrypt=True):
                    pass
        self.assertIn("rpcs3.exe was not found", str(raised.exception))

    def test_find_decrypted_elf_requires_exactly_one_candidate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            nested = root / "sub"
            nested.mkdir()
            self.assertIsNone(eboot_source.find_decrypted_elf(root))
            nested.joinpath("EBOOT.ELF").write_bytes(DECRYPTED)
            self.assertEqual(eboot_source.find_decrypted_elf(root),
                             nested / "EBOOT.ELF")
            root.joinpath("OTHER.elf").write_bytes(DECRYPTED)
            self.assertIsNone(eboot_source.find_decrypted_elf(root))


if __name__ == "__main__":
    unittest.main()
