"""Phase 2 tests: restore-once PINE migration bridge."""

import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest

TESTS = Path(__file__).resolve().parent
TOOLS = TESTS.parent / "tools"
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(TESTS))

import roster_bridge as rb
from test_roster_bridge import MemoryPine, NullLog


class MigrationPine(MemoryPine):
    """MemoryPine plus the connection/identity calls the bridge uses."""

    def __init__(self, count=2):
        super().__init__(count=count)
        self.closed = False

    def connect(self):
        pass

    def close(self):
        self.closed = True

    def version(self):
        return "0.0.42-19803"

    def title(self):
        return rb.EXPECTED_TITLE

    def serial(self):
        return rb.EXPECTED_SERIAL

    def uuid(self):
        return rb.EXPECTED_UUID

    def game_version(self):
        return rb.EXPECTED_GAME_VERSION


class MigrationBridgeTests(unittest.TestCase):
    def make_bridge(self, directory, **kwargs):
        kwargs.setdefault("poll_seconds", 0.2)
        bridge = rb.MigrationBridge(
            rb.RosterStore(Path(directory) / "roster.json"), NullLog(),
            campaign_store=rb.CampaignStore(Path(directory) / "campaign.json"),
            **kwargs,
        )
        return bridge

    def saved_roster(self, directory, source):
        """Store a schema-3 roster snapshot as the legacy source file."""
        capture = rb.RosterBridge(rb.RosterStore(
            Path(directory) / "roster.json"), NullLog())
        capture.store.save(capture.read_snapshot(source))

    def saved_campaign(self, directory, pine):
        store = rb.CampaignStore(Path(directory) / "campaign.json")
        store.save(rb.RosterBridge(
            rb.RosterStore(Path(directory) / "roster.json"), NullLog(),
        ).read_campaign(pine))

    def test_roster_and_campaign_restore_once(self):
        source = MigrationPine(count=3)
        source.set_campaign_cell(1, (0x0000000300000000, 0x0000000000000001))
        target = MigrationPine(count=1)  # fallback roster, empty campaign
        events = []
        with tempfile.TemporaryDirectory() as directory:
            self.saved_roster(directory, source)
            self.saved_campaign(directory, source)
            bridge = self.make_bridge(
                directory, callbacks=[lambda t, r: events.append((t, r))])
            stop = threading.Event()
            self.assertTrue(bridge.run_migration(target, stop))
            self.assertEqual(
                bridge.outcome(rb.MIGRATION_ROSTER_TYPE),
                rb.MigrationOutcome.RESTORED)
            self.assertEqual(
                bridge.outcome(rb.MIGRATION_CAMPAIGN_TYPE),
                rb.MigrationOutcome.RESTORED)
            self.assertTrue(
                bridge.proceed_events[rb.MIGRATION_ROSTER_TYPE].is_set())
            self.assertTrue(
                bridge.proceed_events[rb.MIGRATION_CAMPAIGN_TYPE].is_set())
            self.assertEqual(events, [
                (rb.MIGRATION_ROSTER_TYPE, rb.MigrationOutcome.RESTORED),
                (rb.MIGRATION_CAMPAIGN_TYPE, rb.MigrationOutcome.RESTORED),
            ])
            # The fallback roster was replaced by the legacy one.
            self.assertEqual(target.read32(rb.OWNED_COUNT), 3)
            self.assertEqual(target.read32(rb.UNLOCKED_SLOT_INDEX), 2)
            # The legacy campaign cells were written and the dirty flag set.
            base = (rb.EXPECTED_CAMPAIGN_MANAGER + rb.CAMPAIGN_TABLE_OFFSET +
                    1 * rb.CAMPAIGN_CELL_STRIDE)
            self.assertEqual(
                target.read64(base), 0x0000000300000000)
            self.assertEqual(
                target.read32(rb.EXPECTED_CAMPAIGN_MANAGER +
                              rb.CAMPAIGN_DIRTY_OFFSET), 1)

    def test_matching_live_state_counts_as_restored_without_writes(self):
        source = MigrationPine(count=2)
        target = MigrationPine(count=2)
        with tempfile.TemporaryDirectory() as directory:
            self.saved_roster(directory, source)
            self.saved_campaign(directory, source)
            bridge = self.make_bridge(directory)
            bridge.run_migration(target, threading.Event())
            self.assertEqual(
                bridge.outcome(rb.MIGRATION_ROSTER_TYPE),
                rb.MigrationOutcome.RESTORED)
            self.assertEqual(target.writes, [])

    def test_native_becoming_valid_skips_instead_of_overwriting(self):
        target = MigrationPine(count=1)  # fallback roster must not be touched
        with tempfile.TemporaryDirectory() as directory:
            self.saved_roster(directory, MigrationPine(count=3))
            self.saved_campaign(directory, MigrationPine())
            bridge = self.make_bridge(directory, native_valid=lambda t: True)
            bridge.run_migration(target, threading.Event())
            self.assertEqual(
                bridge.outcome(rb.MIGRATION_ROSTER_TYPE),
                rb.MigrationOutcome.SKIPPED)
            self.assertEqual(
                bridge.outcome(rb.MIGRATION_CAMPAIGN_TYPE),
                rb.MigrationOutcome.SKIPPED)
            self.assertTrue(
                bridge.proceed_events[rb.MIGRATION_ROSTER_TYPE].is_set())
            self.assertEqual(target.writes, [])
            self.assertEqual(target.read32(rb.OWNED_COUNT), 1)

    def test_unusable_legacy_roster_blocks_without_fallback(self):
        pine = MigrationPine(count=3)
        with tempfile.TemporaryDirectory() as directory:
            self.saved_roster(directory, pine)
            document = json.loads(
                (Path(directory) / "roster.json").read_text(encoding="utf-8"))
            document["game"]["uuid"] = "another-build"
            (Path(directory) / "roster.json").write_text(
                json.dumps(document), encoding="utf-8")
            original = (Path(directory) / "roster.json").read_bytes()
            target = MigrationPine(count=1)
            bridge = self.make_bridge(directory, restore_campaign=False)
            bridge.run_migration(target, threading.Event())
            self.assertEqual(
                bridge.outcome(rb.MIGRATION_ROSTER_TYPE),
                rb.MigrationOutcome.BLOCKED)
            self.assertFalse(
                bridge.proceed_events[rb.MIGRATION_ROSTER_TYPE].is_set())
            # No fallback roster and the source file is preserved verbatim.
            self.assertEqual(target.writes, [])
            self.assertEqual(
                (Path(directory) / "roster.json").read_bytes(), original)

    def test_unresolvable_legacy_legend_blocks_and_preserves_source(self):
        source = MigrationPine(count=2)
        source.set_legend_token(1)
        root = source.set_legend(1)
        with tempfile.TemporaryDirectory() as directory:
            capture = rb.RosterBridge(rb.RosterStore(
                Path(directory) / "roster.json"), NullLog())
            document = capture.read_snapshot(source).to_dict()
            document["schema_version"] = 2
            document.pop("blocks")
            (Path(directory) / "roster.json").write_text(
                json.dumps(document), encoding="utf-8")
            original = (Path(directory) / "roster.json").read_bytes()

            # Nothing at the recorded catalog address this boot.
            target = MigrationPine(count=1)
            bridge = self.make_bridge(directory, restore_campaign=False)
            bridge.run_migration(target, threading.Event())
            self.assertEqual(
                bridge.outcome(rb.MIGRATION_ROSTER_TYPE),
                rb.MigrationOutcome.BLOCKED)
            self.assertEqual(target.writes, [])
            self.assertEqual(
                (Path(directory) / "roster.json").read_bytes(), original)
            self.assertEqual(
                list(Path(directory).glob("roster.json.legacy-*")), [])

    def test_missing_campaign_json_never_creates_a_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            target = MigrationPine()
            bridge = self.make_bridge(directory, restore_roster=False)
            bridge.run_migration(target, threading.Event())
            self.assertEqual(
                bridge.outcome(rb.MIGRATION_CAMPAIGN_TYPE),
                rb.MigrationOutcome.BLOCKED)
            self.assertFalse(
                bridge.proceed_events[rb.MIGRATION_CAMPAIGN_TYPE].is_set())
            self.assertEqual(target.writes, [])
            self.assertFalse((Path(directory) / "campaign.json").exists())

    def test_selection_is_independent_per_type(self):
        source = MigrationPine(count=3)
        source.set_campaign_cell(2, (0x0000000000000005, 0))
        target = MigrationPine(count=1)
        with tempfile.TemporaryDirectory() as directory:
            self.saved_roster(directory, source)
            self.saved_campaign(directory, source)
            bridge = self.make_bridge(directory, restore_campaign=False)
            bridge.run_migration(target, threading.Event())
            self.assertEqual(
                bridge.outcome(rb.MIGRATION_ROSTER_TYPE),
                rb.MigrationOutcome.RESTORED)
            self.assertIsNone(bridge.outcome(rb.MIGRATION_CAMPAIGN_TYPE))
            self.assertFalse(
                bridge.proceed_events[rb.MIGRATION_CAMPAIGN_TYPE].is_set())
            # The roster was restored but the campaign table was not touched.
            self.assertEqual(target.read32(rb.OWNED_COUNT), 3)
            base = (rb.EXPECTED_CAMPAIGN_MANAGER + rb.CAMPAIGN_TABLE_OFFSET +
                    2 * rb.CAMPAIGN_CELL_STRIDE)
            self.assertEqual(target.read64(base), 0)

    def test_restore_happens_at_most_once_per_type(self):
        source = MigrationPine(count=3)
        with tempfile.TemporaryDirectory() as directory:
            self.saved_roster(directory, source)
            bridge = self.make_bridge(directory, restore_campaign=False)
            target = MigrationPine(count=1)
            bridge.run_migration(target, threading.Event())
            writes_after_first = list(target.writes)
            # A second pass (e.g. run() reconnecting) must not restore again.
            bridge.run_migration(target, threading.Event())
            self.assertEqual(target.writes, writes_after_first)

    def test_run_connects_and_exits_after_one_pass(self):
        source = MigrationPine(count=3)
        target = MigrationPine(count=1)
        with tempfile.TemporaryDirectory() as directory:
            self.saved_roster(directory, source)
            self.saved_campaign(directory, source)
            bridge = self.make_bridge(
                directory, client_factory=lambda host, port: target)
            ready = threading.Event()
            finished = threading.Event()

            def worker():
                bridge.run(threading.Event(), ready)
                finished.set()

            thread = threading.Thread(target=worker, daemon=True)
            thread.start()
            self.assertTrue(finished.wait(timeout=10))
            thread.join(timeout=5)
            self.assertTrue(ready.is_set())
            self.assertTrue(target.closed)
            self.assertEqual(
                bridge.outcome(rb.MIGRATION_ROSTER_TYPE),
                rb.MigrationOutcome.RESTORED)

    def test_requires_at_least_one_selected_type(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "at least one object"):
                self.make_bridge(directory, restore_roster=False,
                                 restore_campaign=False)


if __name__ == "__main__":
    unittest.main()
