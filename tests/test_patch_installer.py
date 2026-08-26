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
            install_setup(root, server)
            checks = verify_setup(root, server)
            self.assertTrue(all(passed for passed, _, required in checks if required))
            advisory = [message for passed, message, required in checks
                        if not required and not passed]
            self.assertEqual(len(advisory), 1)
            self.assertIn("01.01", advisory[0])


if __name__ == "__main__":
    unittest.main()
