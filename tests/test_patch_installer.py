import struct
import tempfile
import unittest
from pathlib import Path

from tools.patch_installer import (
    COMPATIBILITY_PATCH,
    GAME_VERSION,
    PPU_HEADER,
    SUPPORTED_BUILDS,
    TITLE_ID,
    game_version_problem,
    install_patch,
    install_setup,
    merge_patch,
    merge_patch_config,
    read_param_sfo,
    rpcn_problem,
    verify_setup,
)
from tools.server_config import read_title_version


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = (ROOT / "packaging" / "SpartacusLegends_ServerPatch.yml").read_text(encoding="utf-8")


def write_param_sfo(path: Path, fields: dict[str, str]) -> None:
    """Write a minimal PARAM.SFO holding the given UTF-8 string fields."""
    keys = b"".join(key.encode() + b"\x00" for key in fields)
    values = b"".join(value.encode() + b"\x00" for value in fields.values())
    key_table = 20 + 16 * len(fields)
    data_table = key_table + len(keys)
    index = b""
    key_offset = data_offset = 0
    for key, value in fields.items():
        size = len(value.encode()) + 1
        index += struct.pack("<HHIII", key_offset, 0x0204, size, size, data_offset)
        key_offset += len(key.encode()) + 1
        data_offset += size
    header = struct.pack("<4sIIII", b"\x00PSF", 0x00000101, key_table,
                         data_table, len(fields))
    path.write_bytes(header + index + keys + values)


def make_rpcs3_tree(root: Path, *, app_version: str = GAME_VERSION,
                    npid: str = "player") -> Path:
    (root / "patches").mkdir(parents=True)
    (root / "config" / "custom_configs").mkdir(parents=True)
    (root / "config" / "config.yml").write_text(
        "Core:\n  PPU Decoder: Recompiler (LLVM)\nNet:\n"
        "  IP swap list: ''\n  Internet enabled: Disconnected\n"
        "  PSN status: Disconnected\n",
        encoding="utf-8")
    (root / "config" / "rpcn.yml").write_text(
        f"Host: np.rpcs3.net\nNPID: {npid}\n", encoding="utf-8")
    game = root / "dev_hdd0" / "game" / TITLE_ID
    game.mkdir(parents=True)
    write_param_sfo(game / "PARAM.SFO",
                    {"APP_VER": app_version, "TITLE_ID": TITLE_ID,
                     "TITLE": "Spartacus Legends"})
    return root


def pin_medium_integrity(test):
    """Run as if at Medium integrity: the suite itself may run from a folder
    with a Low integrity label (a sandbox tool's), which the installer now
    reports instead of installing."""
    import sys as _sys
    from unittest import mock as _mock
    import tools.patch_installer  # noqa: F401  (ensure both names exist)
    for name in ("patch_installer", "tools.patch_installer"):
        module = _sys.modules.get(name)
        if module is not None:
            patcher = _mock.patch.object(module, "low_integrity_problem",
                                         return_value=None)
            patcher.start()
            test.addCleanup(patcher.stop)


class PatchInstallerTests(unittest.TestCase):
    def test_merge_retains_other_patches_and_replaces_project_block(self):
        old = """Version: 1.2

PPU-other:
  \"Other patch\":
    Patch: []

PPU-81471d050c14f4d20b4027686f8b571dafd32394:
  \"Spartacus Legends - Server emulator compatibility\":
    Patch Version: \"2.0\"
    Patch: []
  \"Existing compatible patch\":
    Patch: []
"""
        merged = merge_patch(old, TEMPLATE)
        self.assertIn('  "Other patch":', merged)
        self.assertIn('  "Existing compatible patch":', merged)
        # Both supported builds are installed, each exactly once.
        for name in ('  "Spartacus Legends - Server emulator compatibility":',
                     '  "Spartacus Legends - Online matchmaking '
                     'compatibility (experimental)":'):
            self.assertEqual(merged.count(name), len(SUPPORTED_BUILDS), name)
        for header in SUPPORTED_BUILDS.values():
            self.assertEqual(merged.count(header), 1, header)
        self.assertIn('Patch Version: "4.2"', merged)

    def test_merges_are_idempotent_across_both_ppu_sections(self):
        # A second install must not duplicate entries, swallow the blank
        # separator between PPU sections, or insert one build's entries
        # into another build's section.
        for existing in (
            "Version: 1.2\n",
            'Version: 1.2\n\nPPU-custom:\n  "Mine": {}\n',
            TEMPLATE,
        ):
            once = merge_patch(existing, TEMPLATE)
            self.assertEqual(merge_patch(once, TEMPLATE), once)
            for header in SUPPORTED_BUILDS.values():
                self.assertEqual(once.count(header), 1, header)

    def test_patch_config_merge_is_idempotent(self):
        once = merge_patch_config("")
        self.assertEqual(merge_patch_config(once), once)
        for version, header in SUPPORTED_BUILDS.items():
            self.assertIn(header, once)
            self.assertIn(f"        {version}:", once)

    def test_patch_config_merge_handles_rpcs3_empty_document(self):
        # RPCS3 writes a lone "{}" for an empty patch_config.yml; appending
        # block mappings after it produces a file YAML cannot parse.
        for empty in ("", "{}", "{}\n"):
            merged = merge_patch_config(empty)
            self.assertNotIn("{}", merged)
            self.assertEqual(merge_patch_config(merged), merged)
            for header in SUPPORTED_BUILDS.values():
                self.assertIn(header, merged)

    def test_install_creates_backup_and_preserves_custom_patch(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            patches = root / "patches"
            patches.mkdir()
            target = patches / "imported_patch.yml"
            target.write_text("Version: 1.2\n\nPPU-custom:\n  \"Mine\": {}\n", encoding="utf-8")
            installed, backup = install_patch(root)
            self.assertEqual(installed, target)
            self.assertIsNotNone(backup)
            self.assertTrue(backup.is_file())
            contents = target.read_text(encoding="utf-8")
            self.assertIn('  "Mine": {}', contents)
            self.assertIn(PPU_HEADER, contents)

    def test_patch_config_enables_required_patch_and_retains_others(self):
        existing = f"""PPU-other:
  Other patch:
    Game: {{}}
{PPU_HEADER}
  \"{COMPATIBILITY_PATCH}\":
    Spartacus Legends:
      NPUB30746:
        01.00:
          Enabled: false
  Optional patch:
    Spartacus Legends:
      NPUB30746:
        01.00:
          Enabled: true
"""
        merged = merge_patch_config(existing)
        self.assertIn("  Other patch:", merged)
        self.assertIn("  Optional patch:", merged)
        # One entry per supported build, never duplicated within a section.
        self.assertEqual(merged.count(f"  {COMPATIBILITY_PATCH}:"),
                         len(SUPPORTED_BUILDS))
        for version, header in SUPPORTED_BUILDS.items():
            section = merged[merged.index(header):]
            end = section.find(chr(10) + "PPU-", 1)
            if end != -1:
                section = section[:end]
            self.assertEqual(section.count(f"  {COMPATIBILITY_PATCH}:"), 1)
            self.assertIn(f"        {version}:", section)
        required = merged.index(f"  {COMPATIBILITY_PATCH}:")
        optional = merged.index("  Optional patch:")
        self.assertIn("          Enabled: true", merged[required:optional])

    def test_full_setup_configures_rpc3_and_clears_game_cache(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            server = root / "release"
            (root / "patches").mkdir()
            (root / "config" / "custom_configs").mkdir(parents=True)
            cache = root / "cache" / "NPUB30746"
            cache.mkdir(parents=True)
            (cache / "compiled.bin").write_bytes(b"cache")

            # The game is installed: a folder with neither the game nor an
            # RPCN account is refused as "probably the wrong RPCS3".
            (root / "dev_hdd0" / "game" / TITLE_ID).mkdir(parents=True)
            write_param_sfo(root / "dev_hdd0" / "game" / TITLE_ID /
                            "PARAM.SFO",
                            {"APP_VER": GAME_VERSION, "TITLE_ID": TITLE_ID})
            (root / "patches" / "imported_patch.yml").write_text(
                "Version: 1.2\n\nPPU-custom:\n  \"Mine\": {}\n", encoding="utf-8")
            (root / "config" / "config.yml").write_text(
                "Core:\n  PPU Decoder: Recompiler (LLVM)\nNet:\n"
                "  IP swap list: old.example=192.0.2.1\n"
                "  Internet enabled: Disconnected\n"
                "  PSN status: Disconnected\n"
                "  UPNP Enabled: false\n",
                encoding="utf-8",
            )
            (root / "config" / "patch_config.yml").write_text(
                f"{PPU_HEADER}\n  Optional patch:\n    Game: {{}}\n",
                encoding="utf-8",
            )
            (root / "config" / "ipc.yml").write_text(
                "IPC Server enabled: false\nIPC Port: 12345\n",
                encoding="utf-8",
            )

            result = install_setup(root, server)

            custom = result.custom_config.read_text(encoding="utf-8")
            self.assertIn("  PPU Decoder: Recompiler (LLVM)", custom)
            self.assertIn("  IP swap list: onlineconfigservice.ubi.com=127.0.0.1", custom)
            self.assertIn("  Internet enabled: Connected", custom)
            self.assertIn("  PSN status: RPCN", custom)
            self.assertIn("  UPNP Enabled: false", custom)
            self.assertIn(f"  {COMPATIBILITY_PATCH}:", result.patch_config.read_text())
            self.assertEqual(
                (root / "config" / "ipc.yml").read_text(encoding="utf-8"),
                "IPC Server enabled: false\nIPC Port: 12345\n",
            )
            self.assertFalse(cache.exists())
            self.assertTrue(result.cache_cleared)
            self.assertEqual(len(result.backups), 2)
            self.assertTrue(all(path.is_file() for path in result.backups))
            self.assertIn('  "Mine": {}', result.imported_patch.read_text())
            self.assertEqual(result.server_config,
                             server / "data" / "server-config.json")
            self.assertEqual(result.title_version, "01.00")
            self.assertEqual(read_title_version(result.server_config), "01.00")

    def test_updated_game_configures_v106_and_backs_up_a_version_switch(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp)
            root = make_rpcs3_tree(workspace / "RPCS3",
                                   app_version="01.06")
            server = workspace / "release"
            config = server / "data" / "server-config.json"
            config.parent.mkdir(parents=True)
            config.write_text('{"title_version":"01.00"}\n',
                              encoding="utf-8")

            result = install_setup(root, server)

            self.assertEqual(result.title_version, "01.06")
            self.assertEqual(read_title_version(config), "01.06")
            config_backups = [path for path in result.backups
                              if path.name.startswith("server-config.json.")]
            self.assertEqual(len(config_backups), 1)
            self.assertEqual(read_title_version(config_backups[0]), "01.00")


class PreflightTests(unittest.TestCase):
    def test_param_sfo_fields_are_read(self):
        with tempfile.TemporaryDirectory() as temp:
            sfo = Path(temp) / "PARAM.SFO"
            write_param_sfo(sfo, {"APP_VER": "01.00", "TITLE_ID": TITLE_ID})
            self.assertEqual(read_param_sfo(sfo),
                             {"APP_VER": "01.00", "TITLE_ID": TITLE_ID})

    def test_supported_install_reports_no_problem(self):
        with tempfile.TemporaryDirectory() as temp:
            root = make_rpcs3_tree(Path(temp) / "RPCS3")
            self.assertIsNone(game_version_problem(root))
            self.assertIsNone(rpcn_problem(root))

    def test_updated_game_is_reported_as_unsupported(self):
        with tempfile.TemporaryDirectory() as temp:
            root = make_rpcs3_tree(Path(temp) / "RPCS3", app_version="01.01")
            problem = game_version_problem(root)
            self.assertIsNotNone(problem)
            self.assertIn("01.01", problem)

    def test_missing_game_and_rpcn_account_are_reported(self):
        with tempfile.TemporaryDirectory() as temp:
            root = make_rpcs3_tree(Path(temp) / "RPCS3", npid="")
            (root / "dev_hdd0" / "game" / TITLE_ID / "PARAM.SFO").unlink()
            self.assertIn("Could not find", game_version_problem(root))
            self.assertIn("RPCN", rpcn_problem(root))

    def test_game_is_found_through_games_config(self):
        with tempfile.TemporaryDirectory() as temp:
            root = make_rpcs3_tree(Path(temp) / "RPCS3")
            (root / "dev_hdd0" / "game" / TITLE_ID / "PARAM.SFO").unlink()
            library = Path(temp) / "library" / "Spartacus"
            (library / "PS3_GAME").mkdir(parents=True)
            write_param_sfo(library / "PS3_GAME" / "PARAM.SFO",
                            {"APP_VER": GAME_VERSION, "TITLE_ID": TITLE_ID})
            (root / "config" / "games.yml").write_text(
                f"{TITLE_ID}: {library.as_posix()}\n", encoding="utf-8")
            self.assertIsNone(game_version_problem(root))


class VerifyTests(unittest.TestCase):
    def test_verification_accepts_an_explicitly_empty_bind_address(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp)
            root = make_rpcs3_tree(workspace / "RPCS3")
            server = workspace / "release"
            install_setup(root, server)
            custom = root / "config" / "custom_configs" / \
                f"config_{TITLE_ID}.yml"
            custom.write_text(
                custom.read_text(encoding="utf-8")
                .replace("Net:\n", "Net:\n  Bind address: ''\n"),
                encoding="utf-8",
            )

            failed = [message for passed, message, _
                      in verify_setup(root, server) if not passed]

            self.assertEqual(failed, [])

    def test_verification_warns_about_an_explicit_rpc3_bind_address(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp)
            root = make_rpcs3_tree(workspace / "RPCS3")
            server = workspace / "release"
            install_setup(root, server)
            custom = root / "config" / "custom_configs" / \
                f"config_{TITLE_ID}.yml"
            custom.write_text(
                custom.read_text(encoding="utf-8")
                .replace("Net:\n", "Net:\n  Bind address: 192.168.1.10\n"),
                encoding="utf-8",
            )

            checks = verify_setup(root, server)

            advisory = [message for passed, message, required in checks
                        if not required and not passed]
            self.assertEqual(len(advisory), 1)
            self.assertIn("Bind address is 192.168.1.10", advisory[0])
            self.assertIn("--advertise-host <server-LAN-IP>", advisory[0])
            self.assertIn("not RPCS3's Bind address", advisory[0])

    def test_verification_fails_before_install_and_passes_after(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp)
            root = make_rpcs3_tree(workspace / "RPCS3")
            server = workspace / "release"
            before = verify_setup(root, server)
            self.assertTrue(any(not passed for passed, _, required in before if required))

            install_setup(root, server)
            after = verify_setup(root, server)
            failed = [message for passed, message, _ in after if not passed]
            self.assertEqual(failed, [])

    def test_verification_reports_a_patch_disabled_in_rpcs3(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp)
            root = make_rpcs3_tree(workspace / "RPCS3")
            server = workspace / "release"
            install_setup(root, server)
            patch_config = root / "config" / "patch_config.yml"
            patch_config.write_text(
                patch_config.read_text(encoding="utf-8")
                .replace("Enabled: true", "Enabled: false"), encoding="utf-8")
            failed = [message for passed, message, _
                      in verify_setup(root, server) if not passed]
            self.assertEqual(len(failed), 1)
            self.assertIn("enabled", failed[0])

    def test_verification_reports_an_unsupported_game_without_failing_install(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp)
            root = make_rpcs3_tree(workspace / "RPCS3",
                                   app_version="01.01")
            server = workspace / "release"
            result = install_setup(root, server)
            # 01.01 is not a supported build, so no server version is
            # guessed: server-config.json is not written.
            self.assertFalse(result.server_config_written)
            self.assertIsNone(result.title_version)
            self.assertFalse(result.server_config.exists())
            checks = verify_setup(root, server)
            failed_required = [message for passed, message, required in checks
                               if required and not passed]
            self.assertEqual(len(failed_required), 1)
            self.assertIn("could not be detected", failed_required[0])
            advisory = [message for passed, message, required in checks
                        if not required and not passed]
            self.assertEqual(len(advisory), 1)
            self.assertIn("01.01", advisory[0])


class WrongFolderAndVersionTests(unittest.TestCase):
    """User report: an unused RPCS3 copy was patched instead of the real one,
    and the server was silently switched to 01.00."""

    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.workspace = Path(self._temp.name)
        self.server = self.workspace / "release"
        pin_medium_integrity(self)

    def unused_rpcs3(self) -> Path:
        """A fresh RPCS3 copy: no game installed and no RPCN account."""
        root = make_rpcs3_tree(self.workspace / "PS3. NEW")
        (root / "dev_hdd0" / "game" / TITLE_ID / "PARAM.SFO").unlink()
        (root / "config" / "rpcn.yml").unlink()
        return root

    def snapshot(self, root: Path) -> dict:
        return {path: path.read_bytes() for path in sorted(root.rglob("*"))
                if path.is_file()}

    def write_server_config(self, version: str) -> Path:
        config = self.server / "data" / "server-config.json"
        config.parent.mkdir(parents=True)
        config.write_text(f'{{"title_version":"{version}"}}\n',
                          encoding="utf-8")
        return config

    def test_unused_folder_is_one_wrong_folder_result(self):
        from tools.patch_installer import UNUSED_FOLDER_MESSAGE
        root = self.unused_rpcs3()
        checks = verify_setup(root, self.server)
        self.assertEqual(len(checks), 1)
        passed, message, required = checks[0]
        self.assertFalse(passed)
        self.assertTrue(required)
        self.assertEqual(message, UNUSED_FOLDER_MESSAGE)
        self.assertIn("Open Install Folder", message)
        self.assertIn("rpcs3.exe", message)

    def test_unused_folder_install_writes_nothing(self):
        from tools.patch_installer import UnusedRPCS3FolderError
        root = self.unused_rpcs3()
        config = self.write_server_config("01.06")
        before = self.snapshot(root)
        with self.assertRaises(UnusedRPCS3FolderError):
            install_setup(root, self.server)
        self.assertEqual(self.snapshot(root), before)
        self.assertEqual(read_title_version(config), "01.06")
        self.assertEqual(list(config.parent.iterdir()), [config])

    def test_unused_folder_cli_writes_nothing_without_confirmation(self):
        from unittest import mock
        from tools import patch_installer
        root = self.unused_rpcs3()
        config = self.write_server_config("01.06")
        before = self.snapshot(root)
        namespace = mock.Mock(
            rpcs3_folder=str(root), verify=False, eboot=None, eboot_elf=None,
            adaptive=False, no_adaptive=False, no_hash_check=False,
            allow_unused_folder=False, title_version=None, yes=True,
            no_wait=True)
        with mock.patch.object(patch_installer, "rpcs3_is_running",
                               return_value=False), \
                mock.patch.object(patch_installer, "application_dir",
                                  return_value=self.server), \
                mock.patch("builtins.print") as printed:
            self.assertEqual(patch_installer.run(namespace), 1)
        output = " ".join(str(arg) for call in printed.call_args_list
                          for arg in call.args)
        self.assertIn("never been used to play", output)
        self.assertNotIn("No RPCN account", output)
        self.assertEqual(self.snapshot(root), before)
        self.assertEqual(read_title_version(config), "01.06")

    def test_confirmed_unused_folder_installs_but_keeps_server_version(self):
        root = self.unused_rpcs3()
        config = self.write_server_config("01.06")
        result = install_setup(root, self.server, allow_unused_folder=True)
        self.assertTrue(result.imported_patch.is_file())
        self.assertFalse(result.server_config_written)
        self.assertEqual(read_title_version(config), "01.06")

    def test_game_not_found_leaves_server_config_unchanged(self):
        # An RPCS3 that has been used (RPCN set up) but where the game is not
        # where the installer can see it: the version is unknown.
        root = make_rpcs3_tree(self.workspace / "RPCS3")
        (root / "dev_hdd0" / "game" / TITLE_ID / "PARAM.SFO").unlink()
        config = self.write_server_config("01.06")
        payload = config.read_bytes()
        result = install_setup(root, self.server)
        self.assertFalse(result.server_config_written)
        self.assertIsNone(result.title_version)
        self.assertEqual(config.read_bytes(), payload)
        self.assertFalse([path for path in result.backups
                          if path.name.startswith("server-config.json")])
        messages = [message for passed, message, required
                    in verify_setup(root, self.server)
                    if required and not passed]
        self.assertTrue(any("could not be detected" in message
                            and "01.06" in message for message in messages))

    def test_game_not_found_and_no_config_writes_none(self):
        root = make_rpcs3_tree(self.workspace / "RPCS3")
        (root / "dev_hdd0" / "game" / TITLE_ID / "PARAM.SFO").unlink()
        result = install_setup(root, self.server)
        self.assertFalse(result.server_config.exists())

    def test_explicit_title_version_is_written_when_undetectable(self):
        root = make_rpcs3_tree(self.workspace / "RPCS3")
        (root / "dev_hdd0" / "game" / TITLE_ID / "PARAM.SFO").unlink()
        config = self.write_server_config("01.00")
        result = install_setup(root, self.server, title_version="01.06")
        self.assertTrue(result.server_config_written)
        self.assertEqual(read_title_version(config), "01.06")
        with self.assertRaises(ValueError):
            install_setup(root, self.server, title_version="01.01")

    def test_relocated_dev_hdd0_from_vfs_yml_is_searched(self):
        from tools.patch_installer import dev_hdd0_dir, find_param_sfo
        root = make_rpcs3_tree(self.workspace / "RPCS3", app_version="01.06")
        default_game = root / "dev_hdd0" / "game" / TITLE_ID
        (default_game / "PARAM.SFO").unlink()
        moved = self.workspace / "Big Drive" / "PS3 HDD"
        (moved / "game" / TITLE_ID).mkdir(parents=True)
        write_param_sfo(moved / "game" / TITLE_ID / "PARAM.SFO",
                        {"APP_VER": "01.06", "TITLE_ID": TITLE_ID})
        (root / "config" / "vfs.yml").write_text(
            '$(EmulatorDir): ""\n'
            f"/dev_hdd0/: {moved.as_posix()}/\n"
            "/dev_hdd1/: $(EmulatorDir)dev_hdd1/\n"
            "/dev_usb***/:\n"
            "  /dev_usb000: $(EmulatorDir)dev_usb000/\n",
            encoding="utf-8")
        self.assertEqual(dev_hdd0_dir(root), Path(moved.as_posix() + "/"))
        self.assertEqual(find_param_sfo(root),
                         moved / "game" / TITLE_ID / "PARAM.SFO")
        result = install_setup(root, self.server)
        self.assertEqual(result.title_version, "01.06")

    def test_emulator_dir_variable_is_expanded(self):
        from tools.patch_installer import dev_hdd0_dir
        root = make_rpcs3_tree(self.workspace / "RPCS3")
        self.assertEqual(dev_hdd0_dir(root), root / "dev_hdd0")
        (root / "config" / "vfs.yml").write_text(
            '$(EmulatorDir): ""\n/dev_hdd0/: $(EmulatorDir)hdd/\n',
            encoding="utf-8")
        self.assertEqual(dev_hdd0_dir(root), Path(str(root) + "/hdd/"))
        (root / "config" / "vfs.yml").write_text(
            "$(EmulatorDir): D:/Emu/\n/dev_hdd0/: $(EmulatorDir)dev_hdd0/\n",
            encoding="utf-8")
        self.assertEqual(dev_hdd0_dir(root), Path("D:/Emu/dev_hdd0/"))


class WriteRefusalTests(unittest.TestCase):
    """User report: "Permission denied" creating config_NPUB30746.yml.*.bak
    although the folder allowed writing; the GUI then claimed nothing was
    written without checking."""

    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.workspace = Path(self._temp.name)
        self.root = make_rpcs3_tree(self.workspace / "RPCS3",
                                    app_version="01.06")
        self.server = self.workspace / "release"
        pin_medium_integrity(self)
        # An earlier install, so every file already exists and differs.
        (self.root / "patches" / "imported_patch.yml").write_text(
            "Version: 1.2\n", encoding="utf-8")
        custom = (self.root / "config" / "custom_configs" /
                  f"config_{TITLE_ID}.yml")
        custom.write_text("Net:\n  PSN status: Disconnected\n",
                          encoding="utf-8")

    def snapshot(self):
        return {path: path.read_bytes()
                for path in sorted(self.workspace.rglob("*"))
                if path.is_file()}

    def test_refused_backup_mid_install_is_rolled_back(self):
        from unittest import mock
        from tools import patch_installer
        before = self.snapshot()
        real_copy = patch_installer.shutil.copy2

        def refuse_config_backup(source, target, *args, **kwargs):
            if Path(target).name.startswith(f"config_{TITLE_ID}.yml.") \
                    and Path(target).suffix == ".bak":
                raise PermissionError(13, "Permission denied", str(target))
            return real_copy(source, target, *args, **kwargs)

        with mock.patch.object(patch_installer.shutil, "copy2",
                               side_effect=refuse_config_backup):
            with self.assertRaises(patch_installer.InstallWriteError) as raised:
                install_setup(self.root, self.server)
        self.assertTrue(raised.exception.rolled_back)
        self.assertIn("nothing was changed", str(raised.exception))
        # Every file is back, and the rollback's own backups are gone.
        self.assertEqual(self.snapshot(), before)

    def test_preflight_refusal_changes_nothing(self):
        from unittest import mock
        from tools import patch_installer
        before = self.snapshot()
        blocked = self.root / "config" / "custom_configs"
        real_write = Path.write_bytes

        def refuse_probe(path, data):
            if path.parent == blocked and path.name.startswith(
                    "~spartacus-write-check"):
                raise PermissionError(13, "Permission denied")
            return real_write(path, data)

        with mock.patch.object(Path, "write_bytes", refuse_probe):
            with self.assertRaises(patch_installer.InstallWriteError) as raised:
                install_setup(self.root, self.server)
        message = str(raised.exception)
        self.assertTrue(raised.exception.rolled_back)
        self.assertIn("Nothing was changed", message)
        self.assertIn(str(blocked), message)
        self.assertIn("double-clicking", message)
        self.assertEqual(self.snapshot(), before)

    def test_low_integrity_explains_itself_instead_of_installing(self):
        from unittest import mock
        from tools import patch_installer
        before = self.snapshot()
        namespace = mock.Mock(
            rpcs3_folder=str(self.root), verify=False, eboot=None,
            eboot_elf=None, adaptive=False, no_adaptive=False,
            no_hash_check=True, allow_unused_folder=False,
            title_version=None, yes=True, no_wait=True)
        with mock.patch.object(patch_installer, "low_integrity_problem",
                               return_value=patch_installer.LOW_INTEGRITY_HELP), \
                mock.patch.object(patch_installer, "rpcs3_is_running",
                                  return_value=False), \
                mock.patch.object(patch_installer, "application_dir",
                                  return_value=self.server), \
                mock.patch("builtins.print") as printed:
            self.assertEqual(patch_installer.run(namespace), 1)
        output = " ".join(str(arg) for call in printed.call_args_list
                          for arg in call.args)
        self.assertIn("Low integrity", output)
        self.assertEqual(self.snapshot(), before)

    def test_refused_probe_names_low_integrity_when_that_is_the_cause(self):
        from unittest import mock
        from tools import patch_installer
        real_write = Path.write_bytes

        def refuse(path, data):
            if path.name.startswith("~spartacus-write-check"):
                raise PermissionError(13, "Access is denied")
            return real_write(path, data)

        with mock.patch.object(Path, "write_bytes", refuse), \
                mock.patch.object(patch_installer, "low_integrity_problem",
                                  return_value=patch_installer.LOW_INTEGRITY_HELP):
            message = patch_installer.write_access_problem([self.root])
        self.assertIn("Low integrity", message)

    def test_integrity_level_is_read_on_windows(self):
        from tools import patch_installer
        level = patch_installer.process_integrity_level()
        if level is None:
            self.skipTest("not Windows")
        self.assertIn(level & 0xF000, (0x1000, 0x2000, 0x3000, 0x4000))

    def test_probe_files_are_never_left_behind(self):
        install_setup(self.root, self.server)
        leftovers = list(self.workspace.rglob("~spartacus-write-check*"))
        self.assertEqual(leftovers, [])


if __name__ == "__main__":
    unittest.main()
