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
class ReleasePatchTests(unittest.TestCase):
    def test_refresh_completion_patch_is_in_both_distributed_yamls(self):
        for path in PATCH_FILES:
            with self.subTest(path=path):
                contents = path.read_text(encoding="utf-8")
                self.assertIn('Patch Version: "4.0"', contents)
                self.assertIn(REFRESH_COMPLETION_PATCH, contents)


if __name__ == "__main__":
    unittest.main()
