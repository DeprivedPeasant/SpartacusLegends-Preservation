import tempfile
import unittest
from pathlib import Path

from tools.patch_installer import PPU_HEADER, install_patch, merge_patch


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


if __name__ == "__main__":
    unittest.main()
