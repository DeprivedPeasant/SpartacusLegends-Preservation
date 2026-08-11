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
            self.memory64[record] = (slot + 1) << 56 | backing
            for offset in range(0, rb.BACKING_STRIDE, 8):
                self.memory64[backing + offset] = (slot + 9) << 56 | offset

    def status(self):
        return 0

    def read32(self, address):
        return self.memory32.get(address, self.memory64.get(address, 0) & 0xFFFFFFFF)

    def read64(self, address):
        return self.memory64.get(address, 0)

    def write32(self, address, value):
        self.writes.append((32, address, value))
        self.memory32[address] = value

    def write64(self, address, value):
        self.writes.append((64, address, value))
        self.memory64[address] = value
        self.memory32[address] = value & 0xFFFFFFFF


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
            self.assertEqual(document["schema_version"], 2)
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
            path.write_text(json.dumps(document), encoding="utf-8")

            migrated = bridge.store.load()
            self.assertEqual(migrated.count, 3)
            self.assertEqual(migrated.unlocked_slots, 3)


if __name__ == "__main__":
    unittest.main()
