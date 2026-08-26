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
COMMERCE_ENUMERATION_PATCH = (
    "- [ be32, 0x00105710, 0x38000001 ] "
    "# supply Commerce readiness to the native save enumerator"
)
MATCHMAKING_PATCH = '"Spartacus Legends - Online matchmaking compatibility (experimental)"'
MATCHMAKING_INSTRUCTIONS = (
    "- [ be32, 0x001ACB80, 0x60000000 ]",
    "- [ be32, 0x001AC9E4, 0x60000000 ]",
    "- [ be32, 0x001B8E8C, 0x38A00001 ]",
    "- [ be32, 0x001B8F0C, 0x38A00001 ]",
)
PPU_SECTIONS = (
    "PPU-81471d050c14f4d20b4027686f8b571dafd32394:",
    "PPU-131aece6ae8526d13307be925f48c87f73c43799:",
)
V106_REQUIRED_INSTRUCTIONS = (
    "- [ be32, 0x0057BE8C, 0x60000000 ]",
    "- [ be32, 0x0057BF24, 0x60000000 ]",
    "- [ be32, 0x0057BAF8, 0x4800034C ]",
    "- [ be32, 0x00156DB4, 0x38000001 ]",
    "- [ be32, 0x000B7908, 0x60000000 ]",
    "- [ be32, 0x001DBD34, 0x98090022 ]",
)
V106_MATCHMAKING_INSTRUCTIONS = (
    "- [ be32, 0x00225BB0, 0x60000000 ]",
    "- [ be32, 0x00225A14, 0x60000000 ]",
    "- [ be32, 0x002333A8, 0x38A00001 ]",
    "- [ be32, 0x00233428, 0x38A00001 ]",
)


class ReleasePatchTests(unittest.TestCase):
    def test_required_patch_is_in_both_distributed_yamls(self):
        for path in PATCH_FILES:
            with self.subTest(path=path):
                contents = path.read_text(encoding="utf-8")
                self.assertIn('Patch Version: "4.2"', contents)
                self.assertIn(COMMERCE_ENUMERATION_PATCH, contents)
                self.assertNotIn("0x00108798", contents)
                self.assertIn(REFRESH_COMPLETION_PATCH, contents)

    def test_experimental_matchmaking_patch_is_in_both_distributed_yamls(self):
        for path in PATCH_FILES:
            with self.subTest(path=path):
                contents = path.read_text(encoding="utf-8")
                self.assertEqual(contents.count(MATCHMAKING_PATCH),
                                 len(PPU_SECTIONS))
                self.assertIn('Patch Version: "0.3-test"', contents)
                for instruction in MATCHMAKING_INSTRUCTIONS:
                    self.assertIn(instruction, contents)


    def test_both_supported_builds_have_a_required_patch(self):
        for path in PATCH_FILES:
            with self.subTest(path=path):
                contents = path.read_text(encoding="utf-8")
                for section in PPU_SECTIONS:
                    self.assertIn(section, contents)
                for instruction in V106_REQUIRED_INSTRUCTIONS:
                    self.assertIn(instruction, contents)
                self.assertIn('Patch Version: "4.4"', contents)
                for instruction in V106_MATCHMAKING_INSTRUCTIONS:
                    self.assertIn(instruction, contents)
                self.assertEqual(contents.count("NPUB30746: [ 01.06 ]"), 4)
                self.assertEqual(contents.count("NPUB30746: [ 01.00 ]"), 4)

    def test_distributed_patch_files_are_byte_identical(self):
        first, second = (path.read_bytes() for path in PATCH_FILES)
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
