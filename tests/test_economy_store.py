import json
import struct
import tempfile
import unittest
from pathlib import Path

from tools.prudp_server import (
    EconomyStore,
    STORE_REFRESH_SENTINEL,
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
            "gold": 5,
            "silver": 500,
            "owned_items": [10236],
        })

        self.assertEqual(store.refresh_store(2, -1), (3, 500))
        self.assertEqual(store.data["owned_items"], [10236])

        persisted = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(persisted["gold"], 3)
        self.assertNotIn(STORE_REFRESH_SENTINEL, persisted["owned_items"])

    def test_refresh_receipt_reports_zero_item_quantity(self):
        body = encode_purchase_result(4, 900, STORE_REFRESH_SENTINEL, quantity=0)

        self.assertEqual(
            struct.unpack("<IIIQI", body),
            (4, 900, STORE_REFRESH_SENTINEL, 0, 0),
        )


if __name__ == "__main__":
    unittest.main()
