import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

# spartacus_server imports its siblings by module name, exactly as the frozen
# executable does.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from tools.spartacus_server import running_from_temp


class TempFolderGuardTests(unittest.TestCase):
    def test_release_extracted_to_a_normal_folder_is_accepted(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp) / "Games" / "SpartacusLegends-Preservation"
            base.mkdir(parents=True)
            with unittest.mock.patch.dict(
                    "os.environ", {"TEMP": str(Path(temp) / "Temp"),
                                   "TMP": str(Path(temp) / "Temp")}):
                self.assertFalse(running_from_temp(base.resolve()))

    def test_release_run_from_inside_the_zip_is_detected(self):
        with tempfile.TemporaryDirectory() as temp:
            temp_root = Path(temp) / "Temp"
            base = temp_root / "Temp1_SpartacusLegends-Preservation-v0.3.7.zip"
            base.mkdir(parents=True)
            with unittest.mock.patch.dict(
                    "os.environ", {"TEMP": str(temp_root), "TMP": str(temp_root)}):
                self.assertTrue(running_from_temp(base.resolve()))


if __name__ == "__main__":
    unittest.main()
