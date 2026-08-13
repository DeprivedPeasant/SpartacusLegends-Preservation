import struct
import tempfile
import unittest
from pathlib import Path

from tools.patch_installer import (
    COMPATIBILITY_PATCH,
    GAME_VERSION,
    PPU_HEADER,
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
        self.assertEqual(merged.count('  "Spartacus Legends - Server emulator compatibility":'), 1)
        self.assertEqual(merged.count(
            '  "Spartacus Legends - Online matchmaking compatibility (experimental)":'), 1)
        self.assertIn('Patch Version: "4.0"', merged)

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
        self.assertEqual(merged.count(f"  {COMPATIBILITY_PATCH}:"), 1)
        required = merged.index(f"  {COMPATIBILITY_PATCH}:")
        optional = merged.index("  Optional patch:")
        self.assertIn("          Enabled: true", merged[required:optional])

    def test_full_setup_configures_rpc3_and_clears_game_cache(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
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

            result = install_setup(root)

            custom = result.custom_config.read_text(encoding="utf-8")
            self.assertIn("  PPU Decoder: Recompiler (LLVM)", custom)
            self.assertIn("  IP swap list: onlineconfigservice.ubi.com=127.0.0.1", custom)
            self.assertIn("  Internet enabled: Connected", custom)
            self.assertIn("  PSN status: RPCN", custom)
            self.assertIn("  UPNP Enabled: false", custom)
            self.assertIn(f"  {COMPATIBILITY_PATCH}:", result.patch_config.read_text())
            self.assertEqual(
                result.ipc_config.read_text(encoding="utf-8"),
                "IPC Server enabled: true\nIPC Port: 28012\n",
            )
            self.assertFalse(cache.exists())
            self.assertTrue(result.cache_cleared)
            self.assertEqual(len(result.backups), 3)
            self.assertTrue(all(path.is_file() for path in result.backups))
            self.assertIn('  "Mine": {}', result.imported_patch.read_text())


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
    def test_verification_fails_before_install_and_passes_after(self):
        with tempfile.TemporaryDirectory() as temp:
            root = make_rpcs3_tree(Path(temp) / "RPCS3")
            before = verify_setup(root)
            self.assertTrue(any(not passed for passed, _, required in before if required))

            install_setup(root)
            after = verify_setup(root)
            failed = [message for passed, message, _ in after if not passed]
            self.assertEqual(failed, [])

    def test_verification_reports_a_patch_disabled_in_rpcs3(self):
        with tempfile.TemporaryDirectory() as temp:
            root = make_rpcs3_tree(Path(temp) / "RPCS3")
            install_setup(root)
            patch_config = root / "config" / "patch_config.yml"
            patch_config.write_text(
                patch_config.read_text(encoding="utf-8")
                .replace("Enabled: true", "Enabled: false"), encoding="utf-8")
            failed = [message for passed, message, _ in verify_setup(root) if not passed]
            self.assertEqual(len(failed), 1)
            self.assertIn("enabled", failed[0])

    def test_verification_reports_an_unsupported_game_without_failing_install(self):
        with tempfile.TemporaryDirectory() as temp:
            root = make_rpcs3_tree(Path(temp) / "RPCS3", app_version="01.01")
            install_setup(root)
            checks = verify_setup(root)
            self.assertTrue(all(passed for passed, _, required in checks if required))
            advisory = [message for passed, message, required in checks
                        if not required and not passed]
            self.assertEqual(len(advisory), 1)
            self.assertIn("01.01", advisory[0])


if __name__ == "__main__":
    unittest.main()
