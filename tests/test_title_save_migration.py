"""Tests for the explicit 01.00 -> 01.06 native-save candidate."""

import hashlib
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[1]
TOOLS = REPO / "tools"
sys.path.insert(0, str(TOOLS))

import title_save_migration as tsm


class TitleSaveMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(
            prefix="spartacus-title-migration-"
        )
        self.root = Path(self.temp.name)
        self.data = self.root / "data"
        self.data.mkdir()
        self.profile = bytearray(0x1238)
        struct.pack_into(">I", self.profile, 0x04, 123)
        struct.pack_into(">I", self.profile, 0x0C, 4567)
        struct.pack_into(">I", self.profile, 0x14, 890)
        self.campaign = bytes((index % 251 for index in range(0x1804)))
        self.roster = bytes(((index * 3) % 251 for index in range(0x53C4)))
        for type_id, payload in (
            (tsm.PROFILE_TYPE, self.profile),
            (tsm.CAMPAIGN_TYPE, self.campaign),
            (tsm.ROSTER_TYPE, self.roster),
        ):
            path = self.data / "usercontent" / f"{type_id:08x}" / "1.bin"
            path.parent.mkdir(parents=True)
            path.write_bytes(payload)
        self.companion = {
            "version": 1,
            "gold": 123,
            "silver": 4567,
            "owned_items": [80002, 10012],
        }
        (self.data / "profile.json").write_text(
            json.dumps(self.companion), encoding="utf-8"
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_complete_conversion_is_isolated_and_auditable(self):
        source_hashes = {
            path: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (self.data / "usercontent").rglob("1.bin")
        }

        result = tsm.migrate_v100_to_v106(self.data)

        destination = self.data / "usercontent" / "01.06"
        migrated_profile = (
            destination / "80000001" / "1.bin"
        ).read_bytes()
        migrated_campaign = (
            destination / "80000002" / "1.bin"
        ).read_bytes()
        migrated_roster = (
            destination / "80000003" / "1.bin"
        ).read_bytes()
        self.assertEqual(migrated_profile, bytes(self.profile))
        self.assertEqual(migrated_roster[:0x53C4], self.roster)
        self.assertEqual(migrated_roster[0x53C4:], bytes(4))
        self.assertEqual(len(migrated_roster), 0x53C8)
        self.assertEqual(migrated_campaign[:0x1804], self.campaign)
        self.assertEqual(migrated_campaign[0x1804:], bytes(0x400))
        self.assertEqual(len(migrated_campaign), 0x1C04)

        economy = json.loads(result.companion_path.read_text("utf-8"))
        self.assertEqual(economy["gold"], 123)
        self.assertEqual(economy["silver"], 4567)
        self.assertEqual(economy["fame"], 890)
        self.assertEqual(economy["owned_items"], [80002, 10012])
        self.assertEqual(economy["claimed_challenges"], [])
        self.assertEqual(economy["daily_challenges"],
                         {"date": "", "claimed": []})

        marker = json.loads(result.marker_path.read_text("utf-8"))
        self.assertEqual(marker["status"],
                         "created_pending_client_rewrite")
        self.assertEqual(marker["campaign_conversion"]["extension_size"],
                         0x400)
        self.assertEqual(marker["roster_conversion"]["extension_size"], 4)
        self.assertEqual(marker["balances"],
                         {"gold": 123, "silver": 4567, "fame": 890})
        self.assertTrue(result.backup_path.is_dir())
        self.assertEqual(
            (result.backup_path / "profile.json").read_text("utf-8"),
            (self.data / "profile.json").read_text("utf-8"),
        )
        for path, digest in source_hashes.items():
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),
                             digest)

    def test_existing_destination_refuses_before_backup(self):
        destination = self.data / "usercontent" / "01.06"
        destination.mkdir(parents=True)

        with self.assertRaisesRegex(tsm.TitleSaveMigrationError,
                                    "refusing to overwrite"):
            tsm.migrate_v100_to_v106(self.data)

        self.assertFalse((self.root / "backups").exists())
        self.assertFalse((self.data / "profile-01.06.json").exists())

    def test_wrong_sized_source_refuses_before_backup(self):
        campaign = self.data / "usercontent" / "80000002" / "1.bin"
        campaign.write_bytes(b"short")

        with self.assertRaisesRegex(tsm.TitleSaveMigrationError,
                                    "wrong-sized 01.00 save"):
            tsm.migrate_v100_to_v106(self.data)

        self.assertFalse((self.root / "backups").exists())
        self.assertFalse((self.data / "usercontent" / "01.06").exists())

    def test_explicit_replace_backs_up_existing_v106_before_overwrite(self):
        destination = self.data / "usercontent" / "01.06"
        old_roster = destination / "80000003" / "1.bin"
        old_roster.parent.mkdir(parents=True)
        old_roster.write_bytes(b"unwanted fallback roster")
        old_companion = self.data / "profile-01.06.json"
        old_companion.write_text('{"gold": 9}', encoding="utf-8")

        result = tsm.migrate_v100_to_v106(
            self.data, replace_existing=True
        )

        self.assertEqual(
            (result.backup_path / "usercontent" / "01.06" /
             "80000003" / "1.bin").read_bytes(),
            b"unwanted fallback roster",
        )
        self.assertEqual(
            (result.backup_path / "profile-01.06.json").read_text("utf-8"),
            '{"gold": 9}',
        )
        self.assertEqual(old_roster.stat().st_size, 0x53C8)
        marker = json.loads(result.marker_path.read_text("utf-8"))
        self.assertTrue(marker["replaced_existing_01.06"])

    def test_inconsistent_economy_refuses_before_backup(self):
        self.companion["gold"] = 999
        (self.data / "profile.json").write_text(
            json.dumps(self.companion), encoding="utf-8"
        )

        with self.assertRaisesRegex(tsm.TitleSaveMigrationError,
                                    "gold mismatch"):
            tsm.migrate_v100_to_v106(self.data)

        self.assertFalse((self.root / "backups").exists())
        self.assertFalse((self.data / "usercontent" / "01.06").exists())

    def test_existing_fame_must_match_native_profile(self):
        self.companion["fame"] = 891
        (self.data / "profile.json").write_text(
            json.dumps(self.companion), encoding="utf-8"
        )

        with self.assertRaisesRegex(tsm.TitleSaveMigrationError,
                                    "fame mismatch"):
            tsm.migrate_v100_to_v106(self.data)


if __name__ == "__main__":
    unittest.main()
