import sys
import os
import tempfile
import unittest
import unittest.mock
from pathlib import Path

# spartacus_server imports its siblings by module name, exactly as the frozen
# executable does.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from tools.spartacus_server import (
    configure_environment,
    parse_args,
    running_from_temp,
)


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


class AdvertisedHostTests(unittest.TestCase):
    def test_lan_advertised_host_reaches_quazal_redirect_environment(self):
        with tempfile.TemporaryDirectory() as temp:
            release_dir = Path(temp) / "release"
            log_dir = release_dir / "logs"
            with unittest.mock.patch.dict(os.environ, {}, clear=True), \
                    unittest.mock.patch(
                        "tools.spartacus_server.application_dir",
                        return_value=release_dir,
                    ):
                configure_environment(log_dir, 21001, "192.168.0.153")
                self.assertEqual(os.environ["RDV_HOST"], "192.168.0.153")
                self.assertEqual(os.environ["RDV_ADVERTISE_PORT"], "21001")
                self.assertEqual(
                    os.environ["SPARTACUS_USER_CONTENT_HOST"],
                    "192.168.0.153",
                )
                self.assertEqual(
                    Path(os.environ["SPARTACUS_USER_CONTENT_DIR"]),
                    release_dir / "data" / "usercontent",
                )


class PersistenceModeTests(unittest.TestCase):
    def test_native_persistence_is_the_default(self):
        args = parse_args([])
        self.assertFalse(args.legacy_roster_bridge)

    def test_legacy_pine_bridge_requires_explicit_opt_in(self):
        args = parse_args(["--legacy-roster-bridge"])
        self.assertTrue(args.legacy_roster_bridge)


if __name__ == "__main__":
    unittest.main()
