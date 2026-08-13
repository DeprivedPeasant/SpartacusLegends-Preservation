import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATCH_FILES = (
    ROOT / "patches" / "SpartacusLegends_OfflineFix.yml",
    ROOT / "packaging" / "SpartacusLegends_ServerPatch.yml",
)
REFRESH_COMPLETION_PATCH = (
    "- [ be32, 0x00174A9C, 0x98090022 ] "
    "# accept recruit-pool refresh completion"
)
MATCHMAKING_PATCH = '"Spartacus Legends - Online matchmaking compatibility (experimental)"'
MATCHMAKING_INSTRUCTIONS = (
    "- [ be32, 0x001ACB80, 0x60000000 ]",
    "- [ be32, 0x001AC9E4, 0x60000000 ]",
    "- [ be32, 0x001B8E8C, 0x38A00001 ]",
    "- [ be32, 0x001B8F0C, 0x38A00001 ]",
)


class ReleasePatchTests(unittest.TestCase):
    def test_refresh_completion_patch_is_in_both_distributed_yamls(self):
        for path in PATCH_FILES:
            with self.subTest(path=path):
                contents = path.read_text(encoding="utf-8")
                self.assertIn('Patch Version: "4.0"', contents)
                self.assertIn(REFRESH_COMPLETION_PATCH, contents)

    def test_experimental_matchmaking_patch_is_in_both_distributed_yamls(self):
        for path in PATCH_FILES:
            with self.subTest(path=path):
                contents = path.read_text(encoding="utf-8")
                self.assertEqual(contents.count(MATCHMAKING_PATCH), 1)
                self.assertIn('Patch Version: "0.3-test"', contents)
                for instruction in MATCHMAKING_INSTRUCTIONS:
                    self.assertIn(instruction, contents)


if __name__ == "__main__":
    unittest.main()
