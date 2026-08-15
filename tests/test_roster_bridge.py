import json
from pathlib import Path
import sys
import tempfile
import unittest


TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))

import roster_bridge as rb


class NullLog:
    def write(self, _message):
        pass


class MemoryPine:
    def __init__(self, count=2):
        self.memory32 = {
            rb.BACKEND_MANAGER_SLOT: rb.EXPECTED_BACKEND_MANAGER,
            rb.EXPECTED_BACKEND_MANAGER: rb.BACKEND_READY_STATE,
            rb.STORE_COUNT: 6,
            rb.OWNED_COUNT: count,
            rb.UNLOCKED_SLOT_INDEX: max(2, count) - 1,
        }
        self.memory64 = {}
        self.writes = []
        for slot in range(rb.MAX_ROSTER):
            record = rb.OWNED_BASE + slot * rb.RECORD_STRIDE
            backing = rb.OWNED_BACKING_BASE + slot * rb.BACKING_STRIDE
            self.memory32[record] = backing
            for offset in range(0, rb.RECORD_STRIDE, 8):
                self.memory64[record + offset] = (slot + 1) << 56 | offset
            self.memory64[record] = backing << 32 | (slot + 1)
            self.memory32[record + 4] = slot + 1
            for offset in range(0, rb.BACKING_STRIDE, 8):
                self.memory64[backing + offset] = (slot + 9) << 56 | offset
        # Campaign manager 5: slot points to the expected manager; dirty flag
        # set; completion cells default to zero (empty) until populated.
        self.memory32[rb.CAMPAIGN_MANAGER_SLOT] = rb.EXPECTED_CAMPAIGN_MANAGER
        self.memory32[rb.EXPECTED_CAMPAIGN_MANAGER + rb.CAMPAIGN_DIRTY_OFFSET] = 1

    def set_campaign_cell(self, index, words):
        base = rb.EXPECTED_CAMPAIGN_MANAGER + rb.CAMPAIGN_TABLE_OFFSET
        address = base + index * rb.CAMPAIGN_CELL_STRIDE
        for word_index, word in enumerate(words):
            self.memory64[address + word_index * 8] = word

    def set_legend(self, slot, root=None):
        root = root or (0x31800000 + slot * 0x1000)
        record = rb.OWNED_BASE + slot * rb.RECORD_STRIDE
        backing = rb.OWNED_BACKING_BASE + slot * rb.BACKING_STRIDE
        self.memory64[record] = backing << 32 | root
        self.memory32[record] = backing
        self.memory32[record + 4] = root
        self.memory64[record + 0x28] = (root + 0x2C) << 32 | (root + 0x30)
        for offset in range(0, rb.LEGEND_BLOCK_SIZE, 8):
            self.memory64[root + offset] = (0x1000 + offset) << 32 | (0x2000 + offset)
        self.memory64[root] = (root + 0x10) << 32 | (root + 0x20)
        return root

    def status(self):
        return 0

    def read32(self, address):
        if address in self.memory32:
            return self.memory32[address]
        base = address & ~7
        word = self.memory64.get(base, 0)
        return (word >> 32) & 0xFFFFFFFF if address == base else word & 0xFFFFFFFF

    def read64(self, address):
        return self.memory64.get(address, 0)

    def write32(self, address, value):
        self.writes.append((32, address, value))
        self.memory32[address] = value

    def write64(self, address, value):
        self.writes.append((64, address, value))
        self.memory64[address] = value
        self.memory32[address] = (value >> 32) & 0xFFFFFFFF
        self.memory32[address + 4] = value & 0xFFFFFFFF


class RosterBridgeTests(unittest.TestCase):
    def bridge(self, path):
        return rb.RosterBridge(rb.RosterStore(path), NullLog())

    def test_snapshot_json_round_trip_and_build_guard(self):
        pine = MemoryPine()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "roster.json"
            bridge = self.bridge(path)
            snapshot = bridge.read_snapshot(pine)
            bridge.store.save(snapshot)
            self.assertEqual(bridge.store.load(), snapshot)

            document = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(document["schema_version"], 3)
            self.assertEqual(document["unlocked_slots"], 2)
            document["game"]["uuid"] = "wrong-build"
            path.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "different game build"):
                bridge.store.load()

    def test_capture_rejects_bad_pointer_and_moving_count(self):
        pine = MemoryPine()
        with tempfile.TemporaryDirectory() as directory:
            bridge = self.bridge(Path(directory) / "roster.json")
            pine.memory32[rb.OWNED_BASE + rb.RECORD_STRIDE] = 0xDEADBEEF
            with self.assertRaisesRegex(rb.PineError, "slot 1 backing pointer"):
                bridge.read_snapshot(pine)

            pine = MemoryPine()
            original_read32 = pine.read32
            count_reads = iter((2, 1))

            def changing_count(address):
                if address == rb.OWNED_COUNT:
                    return next(count_reads)
                return original_read32(address)

            pine.read32 = changing_count
            with self.assertRaisesRegex(rb.PineError, "changed during capture"):
                bridge.read_snapshot(pine)

    def test_restore_writes_backings_then_inactive_records_then_zero_then_count(self):
        source = MemoryPine(count=2)
        target = MemoryPine(count=1)
        with tempfile.TemporaryDirectory() as directory:
            bridge = self.bridge(Path(directory) / "roster.json")
            snapshot = bridge.read_snapshot(source)
            target.memory64 = {address: 0 for address in target.memory64}
            bridge.restore_snapshot(target, snapshot)

            writes = target.writes
            self.assertEqual(
                writes[0], (32, rb.UNLOCKED_SLOT_INDEX, 1)
            )
            writes = writes[1:]
            backing_writes = snapshot.count * rb.BACKING_WORDS
            record_writes = snapshot.count * rb.RECORD_WORDS
            self.assertTrue(all(width == 64 for width, _, _ in writes[:backing_writes]))
            self.assertTrue(all(
                rb.OWNED_BACKING_BASE <= address <
                rb.OWNED_BACKING_BASE + snapshot.count * rb.BACKING_STRIDE
                for _, address, _ in writes[:backing_writes]
            ))
            records = writes[backing_writes:backing_writes + record_writes]
            self.assertEqual(records[0][1], rb.OWNED_BASE + rb.RECORD_STRIDE)
            self.assertEqual(records[rb.RECORD_WORDS][1], rb.OWNED_BASE)
            self.assertEqual(writes[-1], (32, rb.OWNED_COUNT, snapshot.count))
            self.assertEqual(bridge.read_snapshot(target), snapshot)

    def test_ready_requires_every_runtime_guard(self):
        pine = MemoryPine()
        with tempfile.TemporaryDirectory() as directory:
            bridge = self.bridge(Path(directory) / "roster.json")
            self.assertTrue(bridge._ready(pine))
            for address, unsafe in (
                (rb.BACKEND_MANAGER_SLOT, 0),
                (rb.EXPECTED_BACKEND_MANAGER, rb.BACKEND_READY_STATE - 1),
                (rb.STORE_COUNT, 5),
                (rb.OWNED_COUNT, 0),
                (rb.UNLOCKED_SLOT_INDEX, 0),
            ):
                original = pine.memory32[address]
                pine.memory32[address] = unsafe
                self.assertFalse(bridge._ready(pine))
                pine.memory32[address] = original

    def test_schema_one_migrates_capacity_without_hiding_roster(self):
        pine = MemoryPine(count=3)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "roster.json"
            bridge = self.bridge(path)
            document = bridge.read_snapshot(pine).to_dict()
            document["schema_version"] = 1
            document.pop("unlocked_slots")
            document.pop("blocks")
            path.write_text(json.dumps(document), encoding="utf-8")

            migrated = bridge.store.load()
            self.assertEqual(migrated.count, 3)
            self.assertEqual(migrated.unlocked_slots, 3)

    def test_legend_graph_is_captured_relocated_and_round_trips(self):
        source = MemoryPine(count=2)
        old_root = source.set_legend(1)
        target = MemoryPine(count=1)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "roster.json"
            bridge = self.bridge(path)
            snapshot = bridge.read_snapshot(source)
            self.assertEqual(snapshot.blocks[1].base, old_root)
            bridge.store.save(snapshot)
            self.assertEqual(bridge.store.load(), snapshot)

            restored = bridge.restore_snapshot(target, snapshot)
            # Relocation is packed by Legend ordinal, not roster slot, so
            # procedural slots do not waste the bounded backing arena.
            new_root = rb.LEGEND_ARENA_BASE
            self.assertEqual(target.read32(rb.OWNED_BASE + rb.RECORD_STRIDE + 4), new_root)
            self.assertEqual(restored.blocks[1].base, new_root)
            self.assertEqual(
                target.read64(new_root),
                (new_root + 0x10) << 32 | (new_root + 0x20),
            )
            self.assertEqual(restored, snapshot.materialize())

    def test_legacy_pointerful_roster_is_refused_before_writes(self):
        source = MemoryPine(count=2)
        source.set_legend(1)
        target = MemoryPine(count=1)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "roster.json"
            bridge = self.bridge(path)
            document = bridge.read_snapshot(source).to_dict()
            document["schema_version"] = 2
            document.pop("blocks")
            path.write_text(json.dumps(document), encoding="utf-8")

            legacy = bridge.store.load()
            self.assertEqual(legacy.unresolved_slots(), (1,))
            with self.assertRaisesRegex(ValueError, "Legend graph recovery"):
                bridge.restore_snapshot(target, legacy)
            self.assertEqual(target.writes, [])


class CampaignBridgeTests(unittest.TestCase):
    def bridge(self, path):
        return rb.RosterBridge(
            rb.RosterStore(path.with_name("roster.json")), NullLog(),
            campaign_store=rb.CampaignStore(path),
        )

    def test_campaign_round_trip_and_build_guard(self):
        pine = MemoryPine()
        pine.set_campaign_cell(1, (0x0000000300000000, 0x0000000000000001))
        pine.set_campaign_cell(70, (0x0000000000000000, 0x0000010000000000))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "campaign.json"
            bridge = self.bridge(path)
            snapshot = bridge.read_campaign(pine)
            self.assertEqual([index for index, _ in snapshot.cells], [1, 70])
            bridge.campaign_store.save(snapshot)
            self.assertEqual(bridge.campaign_store.load(), snapshot)

            document = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(document["schema_version"], 1)
            document["game"]["uuid"] = "wrong-build"
            path.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "different game build"):
                bridge.campaign_store.load()

    def test_campaign_restore_writes_cells_and_dirty_then_verifies(self):
        source = MemoryPine()
        source.set_campaign_cell(1, (0x0000000300000000, 0x0000000000000001))
        source.set_campaign_cell(200, (0x00000000000000AA, 0x0000000000000000))
        target = MemoryPine()
        target.memory32[rb.EXPECTED_CAMPAIGN_MANAGER + rb.CAMPAIGN_DIRTY_OFFSET] = 0
        with tempfile.TemporaryDirectory() as directory:
            bridge = self.bridge(Path(directory) / "campaign.json")
            snapshot = bridge.read_campaign(source)
            bridge.restore_campaign(target, snapshot)
            self.assertEqual(bridge.read_campaign(target), snapshot)
            # Dirty flag is forced true so the game treats the table as populated.
            self.assertEqual(
                target.memory32[rb.EXPECTED_CAMPAIGN_MANAGER + rb.CAMPAIGN_DIRTY_OFFSET],
                1,
            )
            # Cells the game sets itself must not fail read-back verification.
            target.set_campaign_cell(5, (0x0000000000000001, 0))
            bridge.restore_campaign(target, snapshot)

    def test_campaign_pointer_guard_rejects_live_heap_value(self):
        pine = MemoryPine()
        pine.set_campaign_cell(3, (0x000000003183A7B4, 0))
        with tempfile.TemporaryDirectory() as directory:
            bridge = self.bridge(Path(directory) / "campaign.json")
            with self.assertRaisesRegex(ValueError, "live pointer"):
                bridge.read_campaign(pine)
            # A poll swallows the fault and leaves state untouched.
            state = (rb.CampaignSnapshot(1, ()), None, 0)
            self.assertEqual(bridge._poll_campaign(pine, state), state)

    def test_campaign_manager_guard(self):
        pine = MemoryPine()
        pine.memory32[rb.CAMPAIGN_MANAGER_SLOT] = 0x00000000
        with tempfile.TemporaryDirectory() as directory:
            bridge = self.bridge(Path(directory) / "campaign.json")
            with self.assertRaisesRegex(rb.PineError, "campaign manager"):
                bridge.read_campaign(pine)

    def test_start_campaign_restores_when_live_differs(self):
        pine = MemoryPine()  # live table empty
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "campaign.json"
            bridge = self.bridge(path)
            saved = rb.CampaignSnapshot(
                1, ((1, (0x0000000300000000, 0x0000000000000001)),)
            )
            bridge.campaign_store.save(saved)
            authoritative = bridge._start_campaign(pine)
            self.assertIsNotNone(authoritative)
            self.assertEqual(bridge.read_campaign(pine), saved)


if __name__ == "__main__":
    unittest.main()
