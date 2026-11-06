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
    resolve_title_version,
    running_from_temp,
)
from server_config import TitleVersionUnknownError
from tools.server_config import encode_title_version


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

    def test_title_version_is_forwarded_to_user_content_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            release_dir = Path(temp) / "release"
            with unittest.mock.patch.dict(os.environ, {}, clear=True), \
                    unittest.mock.patch(
                        "tools.spartacus_server.application_dir",
                        return_value=release_dir,
                    ):
                configure_environment(release_dir / "logs", 21001,
                                      "127.0.0.1", "01.06")
                self.assertEqual(os.environ["SPARTACUS_TITLE_VERSION"],
                                 "01.06")
                self.assertEqual(
                    Path(os.environ["SPARTACUS_USER_CONTENT_DIR"]),
                    release_dir / "data" / "usercontent" / "01.06")
                self.assertEqual(
                    Path(os.environ["SPARTACUS_PROFILE"]),
                    release_dir / "data" / "profile-01.06.json")


class TitleSelectionTests(unittest.TestCase):
    def test_installer_configuration_selects_v106(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            config = base / "data" / "server-config.json"
            config.parent.mkdir()
            config.write_text(encode_title_version("01.06"), encoding="utf-8")
            self.assertEqual(resolve_title_version(None, base),
                             ("01.06", "patch-installer configuration"))

    def test_command_line_override_wins_even_if_config_is_invalid(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            config = base / "data" / "server-config.json"
            config.parent.mkdir()
            config.write_text("not json", encoding="utf-8")
            self.assertEqual(resolve_title_version("01.00", base),
                             ("01.00", "command-line override"))

    @staticmethod
    def write_save(base, relative, size):
        path = base / "data" / "usercontent" / relative / "1.bin"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\x00" * size)

    def test_fresh_folder_refuses_to_guess_a_version(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(TitleVersionUnknownError):
                resolve_title_version(None, Path(temp))

    def test_a_companion_profile_alone_does_not_decide_the_version(self):
        # Any earlier run leaves profile.json, whichever version it assumed.
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            (base / "data").mkdir()
            (base / "data" / "profile.json").write_text("{}", encoding="utf-8")
            with self.assertRaises(TitleVersionUnknownError):
                resolve_title_version(None, base)

    def test_existing_01_00_saves_keep_working_without_configuration(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            self.write_save(base, "80000003", 0x53C4)
            self.assertEqual(resolve_title_version(None, base),
                             ("01.00", "existing saves"))

    def test_existing_01_06_saves_select_01_06_without_configuration(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            self.write_save(base, "01.06/80000003", 0x53C8)
            self.assertEqual(resolve_title_version(None, base),
                             ("01.06", "existing saves"))

    def test_misplaced_saves_do_not_decide_the_version(self):
        # 01.06 objects in the 01.00 folder: choosing either version without
        # asking would hide them or block them.
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            self.write_save(base, "80000003", 0x53C8)
            with self.assertRaises(TitleVersionUnknownError):
                resolve_title_version(None, base)

    def test_saves_for_both_versions_do_not_decide_the_version(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            self.write_save(base, "80000003", 0x53C4)
            self.write_save(base, "01.06/80000003", 0x53C8)
            with self.assertRaises(TitleVersionUnknownError):
                resolve_title_version(None, base)

    def test_legacy_json_is_01_00(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            (base / "data").mkdir()
            (base / "data" / "roster.json").write_text(
                '{"schema_version": 1, "records": []}', encoding="utf-8")
            self.assertEqual(resolve_title_version(None, base),
                             ("01.00", "existing saves"))

    def test_invalid_configuration_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            config = base / "data" / "server-config.json"
            config.parent.mkdir()
            config.write_text("{}", encoding="utf-8")
            with self.assertRaises(ValueError):
                resolve_title_version(None, base)


class PersistenceModeTests(unittest.TestCase):
    def test_native_persistence_is_the_default(self):
        args = parse_args([])
        self.assertFalse(args.legacy_roster_bridge)

    def test_legacy_pine_bridge_requires_explicit_opt_in(self):
        args = parse_args(["--legacy-roster-bridge"])
        self.assertTrue(args.legacy_roster_bridge)

    def test_daily_login_rewards_are_enabled_by_default(self):
        self.assertTrue(parse_args([]).daily_login_rewards)
        self.assertTrue(
            parse_args(["--daily-login-rewards"]).daily_login_rewards
        )
        self.assertFalse(
            parse_args(["--no-daily-login-rewards"]).daily_login_rewards
        )

    def test_title_save_replacement_requires_two_explicit_flags(self):
        args = parse_args([
            "--migrate-01.00-to-01.06",
            "--replace-existing-01.06",
        ])
        self.assertTrue(args.migrate_01_00_to_01_06)
        self.assertTrue(args.replace_existing_01_06)


if __name__ == "__main__":
    unittest.main()
