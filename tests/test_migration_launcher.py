"""Phase 4 tests: automatic migration detection and control in the launcher."""

import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tools"))

from tools.spartacus_server import MigrationController
import migration_coordinator as mc

PROFILE_TYPE = 0x80000001
CAMPAIGN_TYPE = 0x80000002
ROSTER_TYPE = 0x80000003
SIZES = {PROFILE_TYPE: 0x1238, CAMPAIGN_TYPE: 0x1804, ROSTER_TYPE: 0x53C4}


class TempRelease:
    def __enter__(self):
        self.root = Path(tempfile.mkdtemp(prefix="spartacus-launcher-"))
        self.base = self.root / "release"
        (self.base / "data").mkdir(parents=True)
        self.messages = []
        return self

    def __exit__(self, *exc):
        import shutil
        shutil.rmtree(self.root, ignore_errors=True)

    def write_legacy(self, roster=False, campaign=False, profile=False):
        if roster:
            (self.base / "data" / "roster.json").write_text(json.dumps({
                "schema_version": 3, "records": [1],
                "game": {"serial": "NPUB30746",
                         "game_version": "01.00",
                         "uuid": "PPU-81471d050c14f4d20b4027686f8b571dafd32394"},
            }), encoding="utf-8")
        if campaign:
            (self.base / "data" / "campaign.json").write_text(json.dumps({
                "schema_version": 1, "cells": [],
                "game": {"serial": "NPUB30746",
                         "game_version": "01.00",
                         "uuid": "PPU-81471d050c14f4d20b4027686f8b571dafd32394"},
            }), encoding="utf-8")
        if profile:
            (self.base / "data" / "profile.json").write_text(
                json.dumps({"gold": 1, "silver": 2, "owned_items": {},
                            "version": 1}), encoding="utf-8")

    def write_native(self, type_id, size=None):
        size = SIZES[type_id] if size is None else size
        path = (self.base / "data" / "usercontent" / f"{type_id:08x}" /
                "1.bin")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\x00" * size)
        return path

    def controller(self, title_version=None):
        return MigrationController(
            self.base, announce=self.messages.append,
            title_version=title_version)


class LauncherMigrationTests(unittest.TestCase):
    def test_v106_ignores_v100_legacy_sources_and_never_opens_pine(self):
        with TempRelease() as release:
            release.write_legacy(roster=True, campaign=True, profile=True)
            controller = release.controller("01.06")
            self.assertFalse(controller.report.migration_needed)
            self.assertFalse(controller.start(28012, release.base / "logs"))
            self.assertIsNone(controller.gate)
            self.assertIsNone(controller.bridge)
            self.assertFalse(release.messages)

    def test_fresh_install_starts_no_migration_and_no_gate(self):
        with TempRelease() as release:
            controller = release.controller()
            self.assertFalse(controller.report.migration_needed)
            self.assertFalse(controller.start(28012, release.base / "logs"))
            self.assertIsNone(controller.gate)
            self.assertIsNone(controller.bridge)
            self.assertFalse(any("migration" in m.lower()
                                 for m in release.messages))

    def test_completed_marker_never_reactivates_migration(self):
        with TempRelease() as release:
            release.write_legacy(roster=True, campaign=True, profile=True)
            mc.write_marker(release.base / "data", {"status": "complete"})
            controller = release.controller()
            self.assertFalse(controller.start(28012, release.base / "logs"))
            self.assertIsNone(controller.gate)
            self.assertIsNone(controller.bridge)

    def test_pending_install_enables_gate_backup_marker_and_bridge(self):
        with TempRelease() as release:
            release.write_legacy(roster=True, campaign=True, profile=True)
            controller = release.controller()
            self.assertTrue(controller.start(28012, release.base / "logs"))
            self.assertIsNotNone(controller.gate)
            self.assertEqual(controller.pending_types,
                             [PROFILE_TYPE, CAMPAIGN_TYPE, ROSTER_TYPE])
            # Backup exists beside data and the marker records it.
            self.assertTrue(controller.report.backup_path.is_dir())
            self.assertTrue((controller.report.backup_path /
                             "roster.json").is_file())
            marker = mc.read_marker(release.base / "data")
            self.assertEqual(marker["status"], "pending")
            self.assertEqual(marker["backup_path"],
                             str(controller.report.backup_path))
            # The bridge restores only the PINE-eligible types.
            self.assertTrue(controller.bridge.select_roster)
            self.assertTrue(controller.bridge.select_campaign)
            # Fallback uploads are deferred until the restores happen.
            for type_id in (CAMPAIGN_TYPE, ROSTER_TYPE):
                decision = controller.gate.check(type_id, SIZES[type_id])
                self.assertFalse(decision.allowed)
                self.assertTrue(decision.retryable)
            self.assertTrue(any(
                "one-time native migration enabled" in m
                for m in release.messages))

    def test_partial_install_only_migrates_missing_types(self):
        with TempRelease() as release:
            release.write_legacy(roster=True, campaign=True, profile=True)
            release.write_native(ROSTER_TYPE)
            controller = release.controller()
            self.assertTrue(controller.start(28012, release.base / "logs"))
            self.assertEqual(controller.pending_types,
                             [PROFILE_TYPE, CAMPAIGN_TYPE])
            self.assertTrue(controller.bridge.select_campaign)
            self.assertFalse(controller.bridge.select_roster)
            self.assertTrue(controller.gate.check(
                ROSTER_TYPE, SIZES[ROSTER_TYPE]).allowed)

    def test_blocked_install_gates_without_pine(self):
        with TempRelease() as release:
            release.write_legacy(roster=True)
            release.write_native(ROSTER_TYPE, size=SIZES[ROSTER_TYPE] - 4)
            controller = release.controller()
            self.assertTrue(controller.start(28012, release.base / "logs"))
            self.assertIsNone(controller.bridge)
            self.assertIsNotNone(controller.gate)
            decision = controller.gate.check(ROSTER_TYPE, SIZES[ROSTER_TYPE])
            self.assertFalse(decision.allowed)
            self.assertFalse(decision.retryable)
            self.assertTrue(any("malformed" in m for m in release.messages))
            self.assertIsNone(mc.read_marker(release.base / "data"))

    def test_watch_completes_after_exact_uploads_and_writes_marker(self):
        with TempRelease() as release:
            release.write_legacy(roster=True, campaign=True, profile=True)
            controller = release.controller()
            controller.start(28012, release.base / "logs")
            stop = threading.Event()
            result = {}

            def watcher():
                result["exit"] = controller.watch(stop)

            thread = threading.Thread(target=watcher, daemon=True)
            thread.start()

            # The bridge restored both legacy objects...
            controller.gate.set_state(CAMPAIGN_TYPE,
                                      mc.ObjectState.RESTORED)
            controller.gate.set_state(ROSTER_TYPE, mc.ObjectState.RESTORED)
            # ...and the client uploaded all three exact-size objects.
            for type_id in SIZES:
                release.write_native(type_id)
                controller.gate.record_stored(type_id, SIZES[type_id])

            self.assertTrue(controller.completed.wait(timeout=10))
            stop.set()
            thread.join(timeout=5)
            marker = mc.read_marker(release.base / "data")
            self.assertEqual(marker["status"], "complete")
            for type_id in SIZES:
                entry = marker["objects"][f"0x{type_id:08X}"]
                self.assertEqual(entry["state"], "complete")
                self.assertIn("native_sha256", entry)
            self.assertTrue(any("PINE is no longer required" in m
                                for m in release.messages))
            self.assertTrue(controller.stop_bridge.is_set())

    def test_watch_records_blocked_state_and_stops_the_bridge(self):
        with TempRelease() as release:
            release.write_legacy(campaign=True, profile=True)
            controller = release.controller()
            controller.start(28012, release.base / "logs")
            stop = threading.Event()
            thread = threading.Thread(
                target=controller.watch, args=(stop,), daemon=True)
            thread.start()
            controller.gate.set_state(CAMPAIGN_TYPE,
                                      mc.ObjectState.BLOCKED)
            deadline = time.monotonic() + 10
            while (not controller.stop_bridge.is_set()
                    and time.monotonic() < deadline):
                time.sleep(0.05)
            stop.set()
            thread.join(timeout=5)
            self.assertTrue(controller.stop_bridge.is_set())
            self.assertFalse(controller.completed.is_set())
            marker = mc.read_marker(release.base / "data")
            self.assertEqual(marker["status"], "blocked")

    def test_profile_only_migration_never_opens_pine(self):
        with TempRelease() as release:
            release.write_legacy(profile=True)
            controller = release.controller()
            self.assertTrue(controller.start(28012, release.base / "logs"))
            self.assertEqual(controller.pending_types, [PROFILE_TYPE])
            self.assertIsNone(controller.bridge)
            component = controller.bridge_component()
            self.assertIsNone(component)


if __name__ == "__main__":
    unittest.main()
