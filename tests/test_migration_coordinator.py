"""Phase 1 tests for the v0.3 -> v0.4 migration coordinator."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import migration_coordinator as mc


VALID_ROSTER = {
    "schema_version": 2,
    "records": [{"name": "Legend"}],
    "game": "NPUB30746",
    "captured_at": "2026-01-01T00:00:00",
}
VALID_CAMPAIGN = {
    "schema_version": 1,
    "cells": [1, 2, 3],
    "game": "NPUB30746",
    "captured_at": "2026-01-01T00:00:00",
}
VALID_PROFILE = {"gold": 100, "silver": 200, "owned_items": {}, "version": 1}

SIZES = {0x80000001: 0x1238, 0x80000002: 0x1804, 0x80000003: 0x53C4}


class TempInstall:
    """A throwaway release data directory for one test."""

    def __enter__(self):
        self.root = Path(tempfile.mkdtemp(prefix="spartacus-migration-"))
        self.data = self.root / "data"
        self.data.mkdir()
        return self

    def __exit__(self, *exc):
        import shutil
        shutil.rmtree(self.root, ignore_errors=True)

    def write_legacy(self, roster=False, campaign=False, profile=False):
        if roster:
            (self.data / "roster.json").write_text(
                json.dumps(VALID_ROSTER), encoding="utf-8")
        if campaign:
            (self.data / "campaign.json").write_text(
                json.dumps(VALID_CAMPAIGN), encoding="utf-8")
        if profile:
            (self.data / "profile.json").write_text(
                json.dumps(VALID_PROFILE), encoding="utf-8")

    def write_native(self, type_id, size=None, byte=b"\x00"):
        size = SIZES[type_id] if size is None else size
        path = self.data / "usercontent" / f"{type_id:08x}" / "1.bin"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(byte * size)
        return path

    def report(self):
        return mc.evaluate_installation(self.data)


class FreshInstall(unittest.TestCase):
    def test_no_legacy_and_no_native_is_never_pending(self):
        with TempInstall() as install:
            report = install.report()
            self.assertFalse(report.migration_needed)
            self.assertEqual(report.pending_types, [])
            for type_id in SIZES:
                self.assertIs(report.assessments[type_id].state,
                              mc.ObjectState.NOT_NEEDED, hex(type_id))


class CompletedInstall(unittest.TestCase):
    def test_valid_natives_are_authoritative(self):
        with TempInstall() as install:
            install.write_legacy(roster=True, campaign=True, profile=True)
            for type_id in SIZES:
                install.write_native(type_id)
            report = install.report()
            self.assertFalse(report.migration_needed)
            for type_id in SIZES:
                self.assertIs(report.assessments[type_id].state,
                              mc.ObjectState.NOT_NEEDED, hex(type_id))

    def test_complete_marker_short_circuits_detection(self):
        with TempInstall() as install:
            install.write_legacy(roster=True, campaign=True)
            mc.write_marker(install.data, {"status": "complete"})
            report = install.report()
            self.assertFalse(report.migration_needed)
            self.assertEqual(report.pending_types, [])

    def test_complete_marker_leaves_native_files_untouched(self):
        with TempInstall() as install:
            native = install.write_native(0x80000003)
            before = native.read_bytes()
            mc.write_marker(install.data, {"status": "complete"})
            install.report()
            self.assertEqual(native.read_bytes(), before)


class PendingMigration(unittest.TestCase):
    def test_full_legacy_set_without_natives_is_pending(self):
        with TempInstall() as install:
            install.write_legacy(roster=True, campaign=True, profile=True)
            report = install.report()
            self.assertEqual(report.pending_types,
                             [0x80000001, 0x80000002, 0x80000003])
            self.assertIn(0x80000002, report.pending_types)
            a3 = report.assessments[0x80000003]
            self.assertTrue(a3.eligible_for_restore)
            self.assertEqual(a3.legacy_source,
                             install.data / "roster.json")

    def test_type_1_pending_requires_only_profile_json(self):
        with TempInstall() as install:
            install.write_legacy(profile=True)
            report = install.report()
            self.assertEqual(report.pending_types, [0x80000001])
            self.assertFalse(report.assessments[0x80000002].eligible_for_restore)

    def test_partial_migration_is_independent_per_type(self):
        with TempInstall() as install:
            install.write_legacy(roster=True, campaign=True)
            install.write_native(0x80000003)
            report = install.report()
            self.assertEqual(report.pending_types, [0x80000002])
            self.assertIs(report.assessments[0x80000003].state,
                          mc.ObjectState.NOT_NEEDED)

    def test_invalid_legacy_json_is_not_a_migration_source(self):
        with TempInstall() as install:
            (install.data / "roster.json").write_text(
                "{ not json", encoding="utf-8")
            (install.data / "campaign.json").write_text(
                json.dumps({"schema_version": 1}), encoding="utf-8")
            report = install.report()
            self.assertEqual(report.pending_types, [])


class MalformedNative(unittest.TestCase):
    def test_wrong_size_native_blocks_migration(self):
        with TempInstall() as install:
            install.write_legacy(roster=True, campaign=True, profile=True)
            install.write_native(0x80000003, size=SIZES[0x80000003] - 1)
            report = install.report()
            self.assertTrue(report.blocked)
            a3 = report.assessments[0x80000003]
            self.assertIs(a3.state, mc.ObjectState.BLOCKED)
            self.assertFalse(a3.eligible_for_restore)
            # Malformed type must not be treated as absent: no pending even
            # though valid legacy roster JSON exists.
            self.assertNotIn(0x80000003, report.pending_types)
            # Other types stay independent.
            self.assertEqual(report.pending_types,
                             [0x80000001, 0x80000002])

    def test_blocked_native_file_is_preserved(self):
        with TempInstall() as install:
            install.write_legacy(roster=True)
            native = install.write_native(0x80000003, size=17, byte=b"\xAB")
            install.report()
            self.assertEqual(native.stat().st_size, 17)
            self.assertEqual(native.read_bytes()[:1], b"\xAB")


class BackupTests(unittest.TestCase):
    def test_backup_copies_complete_data_directory(self):
        with TempInstall() as install:
            install.write_legacy(roster=True, campaign=True, profile=True)
            native = install.write_native(0x80000001)
            report = install.report()
            backup = mc.create_backup(install.data, report)
            self.assertNotIn(install.data, backup.parents)
            self.assertTrue((backup / "roster.json").is_file())
            self.assertTrue((backup / "campaign.json").is_file())
            self.assertTrue((backup / "profile.json").is_file())
            self.assertEqual((backup / "usercontent" /
                              f"{0x80000001:08x}" / "1.bin").read_bytes(),
                             native.read_bytes())

    def test_existing_marker_backup_is_reused_not_duplicated(self):
        with TempInstall() as install:
            install.write_legacy(roster=True)
            first = mc.create_backup(install.data, install.report())
            mc.write_marker(install.data, {
                "status": "pending",
                "backup_path": str(first),
                "objects": {},
            })
            second = mc.create_backup(
                install.data, install.report())
            self.assertEqual(first, second)
            siblings = list(first.parent.glob("data-*"))
            self.assertEqual(len(siblings), 1)


class MarkerTests(unittest.TestCase):
    def test_marker_round_trip_is_atomic_and_lossless(self):
        with TempInstall() as install:
            install.write_legacy(roster=True, campaign=True, profile=True)
            install.write_native(0x80000003)
            report = install.report()
            backup = mc.create_backup(install.data, report)
            marker = mc.build_marker(install.data, report, backup, "pending")
            mc.write_marker(install.data, marker)
            self.assertEqual(mc.read_marker(install.data), marker)
            self.assertEqual(
                list((install.data / mc.MIGRATION_MARKER_NAME)
                     .parent.glob(mc.MIGRATION_MARKER_NAME + ".tmp")), [])

    def test_marker_records_sizes_hashes_and_backup(self):
        with TempInstall() as install:
            install.write_legacy(roster=True)
            native = install.write_native(0x80000001)
            report = install.report()
            backup = mc.create_backup(install.data, report)
            marker = mc.build_marker(install.data, report, backup, "complete")
            entry = marker["objects"]["0x80000001"]
            self.assertEqual(entry["native_size"], len(native.read_bytes()))
            self.assertEqual(entry["expected_size"], SIZES[0x80000001])
            self.assertEqual(entry["native_sha256"],
                             mc.native_sha256(native))
            self.assertEqual(marker["backup_path"], str(backup))
            self.assertEqual(marker["objects"]["0x80000003"]["state"],
                             "pending")

    def test_unreadable_marker_is_ignored(self):
        with TempInstall() as install:
            install.write_legacy(roster=True)
            (install.data / mc.MIGRATION_MARKER_NAME).write_text(
                "{ broken", encoding="utf-8")
            report = install.report()
            self.assertEqual(report.pending_types, [0x80000003])


class ResumeTests(unittest.TestCase):
    def test_interrupted_pending_migration_resumes(self):
        with TempInstall() as install:
            install.write_legacy(roster=True, campaign=True, profile=True)
            report = install.report()
            backup = mc.create_backup(install.data, report)
            mc.write_marker(install.data, mc.build_marker(
                install.data, report, backup, "pending"))

            # Simulate a captured campaign arriving before an interruption.
            install.write_native(0x80000002)
            resumed = install.report()
            self.assertEqual(resumed.pending_types,
                             [0x80000001, 0x80000003])
            self.assertEqual(resumed.backup_path, backup)
            self.assertIs(resumed.assessments[0x80000002].state,
                          mc.ObjectState.NOT_NEEDED)

    def test_resume_never_weakens_backup(self):
        with TempInstall() as install:
            install.write_legacy(roster=True)
            report = install.report()
            backup = mc.create_backup(install.data, report)
            marker = mc.build_marker(install.data, report, backup, "pending")
            mc.write_marker(install.data, marker)

            # Progress happens after the backup: capture the roster natively.
            install.write_native(0x80000003)
            resumed = install.report()
            reused = mc.create_backup(install.data, resumed)
            self.assertEqual(reused, backup)
            # The backup still contains the pre-migration legacy JSON.
            self.assertTrue((backup / "roster.json").is_file())


if __name__ == "__main__":
    unittest.main()
