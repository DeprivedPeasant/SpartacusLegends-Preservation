"""Per-title-version native object tables for the 01.00 and 01.06 builds."""

import json
from pathlib import Path
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
TOOLS = REPO / "tools"
sys.path.insert(0, str(TOOLS))

import migration_coordinator as mc


PROFILE = 0x80000001
CAMPAIGN = 0x80000002
ROSTER = 0x80000003


class TitleVersionTests(unittest.TestCase):
    def test_default_is_the_shipped_baseline(self):
        self.assertIs(mc.DEFAULT_TITLE_VERSION, mc.TitleVersion.V100)
        self.assertEqual(mc.NATIVE_OBJECTS,
                         mc.native_objects(mc.TitleVersion.V100))

    def test_coercion_accepts_strings_and_rejects_others(self):
        self.assertIs(mc.coerce_title_version("01.06"), mc.TitleVersion.V106)
        self.assertIs(mc.coerce_title_version("1.06"), mc.TitleVersion.V106)
        self.assertIs(mc.coerce_title_version(None), mc.DEFAULT_TITLE_VERSION)
        with self.assertRaises(ValueError):
            mc.coerce_title_version("01.05")

    def test_v100_sizes_are_unchanged_and_exact(self):
        table = mc.native_objects("01.00")
        self.assertEqual(table[PROFILE].expected_size, 0x1238)
        self.assertEqual(table[CAMPAIGN].expected_size, 0x1804)
        self.assertEqual(table[ROSTER].expected_size, 0x53C4)
        for info in table.values():
            self.assertEqual(info.accepted_sizes, (info.expected_size,))

    def test_v106_sizes_match_the_static_dispatcher(self):
        table = mc.native_objects("01.06")
        self.assertEqual(table[PROFILE].expected_size, 0x15B8)
        self.assertEqual(table[PROFILE].accepted_sizes,
                         (0x15B8, 0x1590, 0x1238))
        self.assertEqual(table[CAMPAIGN].expected_size, 0x1C04)
        self.assertEqual(table[CAMPAIGN].accepted_sizes, (0x1C04,))
        self.assertEqual(table[ROSTER].expected_size, 0x53C8)
        self.assertEqual(table[ROSTER].accepted_sizes, (0x53C8, 0x53C4))

    def test_v106_does_not_accept_the_v100_campaign_size(self):
        # 01.06 dropped 0x1804 from its campaign size validation, so a
        # 01.00 campaign object must never be served to a 01.06 client.
        self.assertFalse(mc.native_objects("01.06")[CAMPAIGN].accepts(0x1804))

    def test_ppu_hashes_cover_both_supported_builds(self):
        self.assertEqual(mc.PPU_HASHES[mc.TitleVersion.V100],
                         "81471d050c14f4d20b4027686f8b571dafd32394")
        self.assertEqual(mc.PPU_HASHES[mc.TitleVersion.V106],
                         "131aece6ae8526d13307be925f48c87f73c43799")


class VersionedUploadGateTests(unittest.TestCase):
    def test_gate_defaults_to_v100_exact_sizes(self):
        gate = mc.UploadGate()
        self.assertTrue(gate.check(CAMPAIGN, 0x1804).allowed)
        decision = gate.check(CAMPAIGN, 0x1C04)
        self.assertFalse(decision.allowed)
        self.assertFalse(decision.retryable)

    def test_v106_gate_accepts_forward_read_sizes(self):
        gate = mc.UploadGate(title_version="01.06")
        for size in (0x15B8, 0x1590, 0x1238):
            self.assertTrue(gate.check(PROFILE, size).allowed, hex(size))
        for size in (0x53C8, 0x53C4):
            self.assertTrue(gate.check(ROSTER, size).allowed, hex(size))
        self.assertTrue(gate.check(CAMPAIGN, 0x1C04).allowed)

    def test_v106_gate_still_rejects_unknown_sizes(self):
        gate = mc.UploadGate(title_version="01.06")
        decision = gate.check(PROFILE, 0x1239)
        self.assertFalse(decision.allowed)
        self.assertIn("expected one of", decision.reason)

    def test_pending_deferral_survives_multi_size_types(self):
        gate = mc.UploadGate(title_version="01.06",
                             states={ROSTER: mc.ObjectState.PENDING})
        decision = gate.check(ROSTER, 0x53C4)
        self.assertFalse(decision.allowed)
        self.assertTrue(decision.retryable)

    def test_explicit_expected_sizes_override_stays_exact(self):
        gate = mc.UploadGate(expected_sizes={PROFILE: 0x1238},
                             title_version="01.06")
        self.assertTrue(gate.check(PROFILE, 0x1238).allowed)
        self.assertFalse(gate.check(PROFILE, 0x15B8).allowed)


class VersionedAssessmentTests(unittest.TestCase):
    def _install(self, tmp, type_id, size, version="01.00"):
        directory = (mc.native_content_dir(tmp, version) /
                     f"{type_id:08x}")
        directory.mkdir(parents=True)
        path = directory / f"{mc.NATIVE_CONTENT_ID}.bin"
        path.write_bytes(b"\0" * size)
        return path

    def test_each_version_reads_only_its_own_namespace(self):
        with tempfile.TemporaryDirectory() as raw:
            data = Path(raw) / "data"
            data.mkdir()
            v100 = self._install(data, CAMPAIGN, 0x1804, "01.00")
            v106 = self._install(data, CAMPAIGN, 0x1C04, "01.06")
            report100 = mc.evaluate_installation(data, "01.00")
            report106 = mc.evaluate_installation(data, "01.06")
            self.assertEqual(report100.assessments[CAMPAIGN].native_path,
                             v100)
            self.assertEqual(report106.assessments[CAMPAIGN].native_path,
                             v106)
            self.assertIs(report100.assessments[CAMPAIGN].state,
                          mc.ObjectState.NOT_NEEDED)
            self.assertIs(report106.assessments[CAMPAIGN].state,
                          mc.ObjectState.NOT_NEEDED)
            self.assertEqual(report100.assessments[CAMPAIGN].detail,
                             "valid native object")
            self.assertEqual(report106.assessments[CAMPAIGN].detail,
                             "valid native object")

    def test_marker_records_the_title_version_and_accepted_sizes(self):
        with tempfile.TemporaryDirectory() as raw:
            data = Path(raw) / "data"
            data.mkdir()
            self._install(data, PROFILE, 0x1238, "01.06")
            report = mc.evaluate_installation(data, "01.06")
            marker = mc.build_marker(data, report, data.parent / "backups",
                                     "complete")
            self.assertEqual(marker["title_version"], "01.06")
            entry = marker["objects"][f"0x{PROFILE:08X}"]
            self.assertEqual(entry["expected_size"], 0x15B8)
            self.assertEqual(entry["accepted_sizes"], [0x15B8, 0x1590, 0x1238])
            json.dumps(marker)

    def test_gate_from_report_inherits_the_version(self):
        with tempfile.TemporaryDirectory() as raw:
            data = Path(raw) / "data"
            data.mkdir()
            report = mc.evaluate_installation(data, "01.06")
            gate = mc.UploadGate.from_report(report)
            self.assertIs(gate.title_version, mc.TitleVersion.V106)
            self.assertTrue(gate.check(CAMPAIGN, 0x1C04).allowed)

    def test_v106_never_treats_v100_legacy_json_as_migration_input(self):
        with tempfile.TemporaryDirectory() as raw:
            data = Path(raw) / "data"
            data.mkdir()
            (data / "campaign.json").write_text("{}", encoding="utf-8")
            report = mc.evaluate_installation(data, "01.06")
            self.assertFalse(report.migration_needed)
            self.assertIs(report.assessments[CAMPAIGN].state,
                          mc.ObjectState.NOT_NEEDED)
            self.assertIn("only to title 01.00",
                          report.assessments[CAMPAIGN].detail)


if __name__ == "__main__":
    unittest.main()
