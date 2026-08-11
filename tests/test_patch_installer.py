import tempfile
import unittest
from pathlib import Path

from tools.patch_installer import (
    COMPATIBILITY_PATCH,
    PPU_HEADER,
    install_patch,
    install_setup,
    merge_patch,
    merge_patch_config,
)


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = (ROOT / "packaging" / "SpartacusLegends_ServerPatch.yml").read_text(encoding="utf-8")


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


if __name__ == "__main__":
    unittest.main()
