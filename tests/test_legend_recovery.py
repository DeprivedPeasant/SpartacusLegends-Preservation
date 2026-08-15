import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
import unittest.mock


TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))

import legend_recovery as recovery


def backing(token):
    raw = token.encode("ascii").ljust(64, b"\0")
    return [raw[offset:offset + 8].hex().upper() for offset in range(0, 64, 8)]


def record(product_id):
    return ["0000000000000000", f"{product_id:08X}00000000"]


def native_entry(product_id, marker):
    return struct.pack(">H", product_id) + bytes([marker]) * 14


def make_prg(products):
    section_start = 0xB4
    data_start = section_start + recovery.SECTION_DATA_OFFSET
    size = data_start + recovery.SECTION_ONE_SIZE + 0x20
    result = bytearray(size)
    result[section_start:section_start + 8] = recovery.SECTION_MAGIC
    struct.pack_into(">I", result, section_start + 8, 1)
    structure = data_start + recovery.NATIVE_ROSTER_OFFSET
    struct.pack_into(">I", result,
                     structure + recovery.NATIVE_ROSTER_VERSION_OFFSET,
                     recovery.NATIVE_ROSTER_VERSION)
    struct.pack_into(">H", result,
                     structure + recovery.NATIVE_ROSTER_COUNT_OFFSET,
                     len(products))
    entries = structure + recovery.NATIVE_ROSTER_ENTRIES_OFFSET
    for index, product in enumerate(products):
        start = entries + index * recovery.NATIVE_ROSTER_ENTRY_SIZE
        result[start:start + recovery.NATIVE_ROSTER_ENTRY_SIZE] = native_entry(
            product, index + 1
        )
    return bytes(result)


class LegendRecoveryTests(unittest.TestCase):
    def fixture(self, root):
        data = root / "server" / "data"
        save = root / "rpcs3" / "dev_hdd0" / "home" / "00000001" / "savedata" / recovery.TITLE_SAVE_DIR
        data.mkdir(parents=True)
        save.mkdir(parents=True)
        roster = {
            "schema_version": 2,
            "count": 5,
            "records": [record(product) for product in (1004, 12, 1007, 14, 10)],
            "backings": [
                backing("!!GLADIATOR_NAME_1"),
                backing("!!GLADIATOR_NAME_LEGEND_IXION"),
                backing("!!GLADIATOR_NAME_2"),
                backing("!!GLADIATOR_NAME_LEGEND_MASONIUS"),
                backing("!!GLADIATOR_NAME_LEGEND_ACOLYTUS"),
            ],
            "captured_at": "old",
            "unlocked_slots": 8,
        }
        (data / "roster.json").write_text(json.dumps(roster), encoding="utf-8")
        (data / "campaign.json").write_bytes(b'{"cells":[{"state":3}]}\n')
        (data / "profile.json").write_bytes(b'{"silver":123}\n')
        (save / recovery.PRG_NAME).write_bytes(
            make_prg((1004, 12, 1007, 14, 10))
        )
        (save / "PARAM.SFO").write_bytes(b"fixture")
        return data, save

    def test_plan_derives_legend_ids_from_legacy_roster(self):
        with tempfile.TemporaryDirectory() as temp:
            data, save = self.fixture(Path(temp))
            plan = recovery.build_plan(data, save)
            self.assertEqual(plan.product_ids, (12, 14, 10))
            self.assertEqual(plan.native.product_ids, (1004, 12, 1007, 14, 10))

    def test_apply_compacts_both_rosters_and_preserves_campaign(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            data, save = self.fixture(root)
            campaign_before = (data / "campaign.json").read_bytes()
            prg_before = (save / recovery.PRG_NAME).read_bytes()
            plan = recovery.build_plan(data, save)
            with unittest.mock.patch.object(
                    recovery, "_pine_is_reachable", return_value=False):
                backup = recovery.apply_plan(plan, root / "backups")

            roster_after = json.loads((data / "roster.json").read_text())
            self.assertEqual(roster_after["count"], 2)
            self.assertEqual(
                [int(item[1][:8], 16) for item in roster_after["records"]],
                [1004, 1007],
            )
            native_after = recovery.parse_native_roster(
                (save / recovery.PRG_NAME).read_bytes()
            )
            self.assertEqual(native_after.product_ids, (1004, 1007))
            self.assertEqual((data / "campaign.json").read_bytes(), campaign_before)
            self.assertEqual(
                (backup / "native-save" / recovery.PRG_NAME).read_bytes(),
                prg_before,
            )
            self.assertTrue((backup / "recovery.json").is_file())

    def test_apply_refuses_while_rpcs3_pine_is_reachable(self):
        with tempfile.TemporaryDirectory() as temp:
            data, save = self.fixture(Path(temp))
            plan = recovery.build_plan(data, save)
            with unittest.mock.patch.object(
                    recovery, "_pine_is_reachable", return_value=True):
                with self.assertRaisesRegex(recovery.RecoveryError, "close RPCS3"):
                    recovery.apply_plan(plan)

    def test_missing_native_product_is_already_clean_and_does_not_block(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            data, save = self.fixture(root)
            (save / recovery.PRG_NAME).write_bytes(make_prg((1004, 12, 1007, 10)))
            plan = recovery.build_plan(data, save)
            with unittest.mock.patch.object(
                    recovery, "_pine_is_reachable", return_value=False):
                recovery.apply_plan(plan, root / "backups")
            roster_after = json.loads((data / "roster.json").read_text())
            self.assertEqual(roster_after["count"], 2)
            native_after = recovery.parse_native_roster(
                (save / recovery.PRG_NAME).read_bytes()
            )
            self.assertEqual(native_after.product_ids, (1004, 1007))

    def test_schema_three_filters_parallel_blocks(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            data, save = self.fixture(root)
            roster_path = data / "roster.json"
            roster = json.loads(roster_path.read_text())
            roster["schema_version"] = 3
            roster["blocks"] = [None, {"legend": 12}, None,
                                {"legend": 14}, {"legend": 10}]
            roster_path.write_text(json.dumps(roster), encoding="utf-8")
            plan = recovery.build_plan(data, save)
            with unittest.mock.patch.object(
                    recovery, "_pine_is_reachable", return_value=False):
                recovery.apply_plan(plan, root / "backups")
            roster_after = json.loads(roster_path.read_text())
            self.assertEqual(roster_after["count"], 2)
            self.assertEqual(roster_after["blocks"], [None, None])

    def test_duplicate_native_entries_are_all_removed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            data, save = self.fixture(root)
            (save / recovery.PRG_NAME).write_bytes(
                make_prg((1004, 12, 12, 1007, 14, 10, 10))
            )
            plan = recovery.build_plan(data, save)
            with unittest.mock.patch.object(
                    recovery, "_pine_is_reachable", return_value=False):
                recovery.apply_plan(plan, root / "backups")
            native_after = recovery.parse_native_roster(
                (save / recovery.PRG_NAME).read_bytes()
            )
            self.assertEqual(native_after.product_ids, (1004, 1007))

    def test_all_legend_roster_removes_empty_bridge_snapshot(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            data, save = self.fixture(root)
            roster_path = data / "roster.json"
            roster = json.loads(roster_path.read_text())
            keep = (1, 3, 4)
            roster["records"] = [roster["records"][index] for index in keep]
            roster["backings"] = [roster["backings"][index] for index in keep]
            roster["count"] = 3
            roster_path.write_text(json.dumps(roster), encoding="utf-8")
            (save / recovery.PRG_NAME).write_bytes(make_prg((12, 14, 10)))
            plan = recovery.build_plan(data, save)
            with unittest.mock.patch.object(
                    recovery, "_pine_is_reachable", return_value=False):
                backup = recovery.apply_plan(plan, root / "backups")
            self.assertFalse(roster_path.exists())
            self.assertEqual(
                recovery.parse_native_roster(
                    (save / recovery.PRG_NAME).read_bytes()
                ).count,
                0,
            )
            self.assertTrue((backup / "server-data" / "roster.json").is_file())


if __name__ == "__main__":
    unittest.main()
