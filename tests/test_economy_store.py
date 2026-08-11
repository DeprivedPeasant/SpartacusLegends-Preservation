import json
import struct
import tempfile
import unittest
import datetime
from pathlib import Path

from tools.prudp_server import (
    EconomyStore,
    STORE_REFRESH_SENTINEL,
    encode_qdatetime,
    encode_purchase_result,
)


class EconomyStoreTests(unittest.TestCase):
    def make_store(self, profile):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / "profile.json"
        path.write_text(json.dumps(profile), encoding="utf-8")
        return EconomyStore(path), path

    def test_load_discards_legacy_refresh_sentinel(self):
        store, _ = self.make_store({
            "gold": 2,
            "silver": 500,
            "owned_items": [10236, STORE_REFRESH_SENTINEL],
        })

        self.assertEqual(store.data["owned_items"], [10236])
        self.assertEqual(
            store.requested_owned_items([10236, STORE_REFRESH_SENTINEL]),
            [10236],
        )

    def test_refresh_debits_cost_without_creating_inventory(self):
        store, path = self.make_store({
            "gold": 10,
            "silver": 500,
            "owned_items": [10236],
        })

        self.assertEqual(store.refresh_store(5, -1), (5, 500))
        self.assertEqual(store.data["owned_items"], [10236])

        persisted = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(persisted["gold"], 5)
        self.assertNotIn(STORE_REFRESH_SENTINEL, persisted["owned_items"])

    def test_refresh_receipt_uses_refresh_transaction_category(self):
        transaction_time = encode_qdatetime(
            datetime.datetime(2026, 8, 11, 12, 34, 56,
                              tzinfo=datetime.timezone.utc)
        )
        self.assertEqual(
            (
                (transaction_time >> 26) & 0x3FFF,
                (transaction_time >> 22) & 0x0F,
                (transaction_time >> 17) & 0x1F,
                (transaction_time >> 12) & 0x1F,
                (transaction_time >> 6) & 0x3F,
                transaction_time & 0x3F,
            ),
            # The packed representation uses zero-based month and day.
            (2026, 7, 10, 12, 34, 56),
        )
        body = encode_purchase_result(
            4, 900, STORE_REFRESH_SENTINEL,
            transaction_time=transaction_time, quantity=1
        )

        self.assertEqual(
            struct.unpack("<IIIQI", body),
            (4, 900, STORE_REFRESH_SENTINEL, transaction_time, 1),
        )

    def test_normal_purchase_receipt_carries_transaction_time(self):
        transaction_time = encode_qdatetime(
            datetime.datetime(2026, 8, 12, 1, 2, 3,
                              tzinfo=datetime.timezone.utc)
        )
        body = encode_purchase_result(
            12, 3456, 80002,
            transaction_time=transaction_time, quantity=1,
        )

        self.assertEqual(
            struct.unpack("<IIIQI", body),
            (12, 3456, 80002, transaction_time, 1),
        )


if __name__ == "__main__":
    unittest.main()
