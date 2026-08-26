import json
import struct
import tempfile
import unittest
import datetime
from pathlib import Path

from tools.prudp_server import (
    EconomyStore,
    STORE_REFRESH_SENTINEL,
    V106_CHALLENGE_REWARDS,
    V106_DAILY_CHALLENGE_IDS,
    encode_qdatetime,
    encode_purchase_result,
    encode_reward_balances,
    encode_shop_records,
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

    def test_legacy_profile_without_fame_migrates_to_zero(self):
        store, _ = self.make_store({
            "gold": 2,
            "silver": 500,
            "owned_items": [],
        })

        self.assertEqual(store.data["fame"], 0)

    def test_add_rewards_updates_and_persists_all_three_balances(self):
        store, path = self.make_store({
            "gold": 5,
            "silver": 60,
            "fame": 10,
            "owned_items": [],
        })

        self.assertEqual(store.add_rewards(1, 199, 56), (6, 259, 66))
        persisted = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(
            (persisted["gold"], persisted["silver"], persisted["fame"]),
            (6, 259, 66),
        )

    def test_all_retail_v106_challenge_reward_rows_are_present(self):
        self.assertEqual(set(V106_CHALLENGE_REWARDS), set(range(1, 73)))
        self.assertEqual(V106_CHALLENGE_REWARDS[4],
                         (4, 0, 0, 1000, 0, 0))
        self.assertEqual(V106_CHALLENGE_REWARDS[43],
                         (43, 0, 0, 2000, 0, 0))
        self.assertEqual(V106_CHALLENGE_REWARDS[58],
                         (58, 60009, 1, 0, 0, 500))
        self.assertEqual(V106_CHALLENGE_REWARDS[72],
                         (72, 60007, 1, 0, 0, 4000))
        self.assertEqual(V106_DAILY_CHALLENGE_IDS,
                         frozenset(range(52, 73)))

    def test_challenge_claim_credits_and_persists_exactly_once(self):
        store, path = self.make_store({
            "gold": 1,
            "silver": 20,
            "fame": 3,
            "owned_items": [],
        })

        reward = V106_CHALLENGE_REWARDS[3]
        self.assertTrue(store.claim_challenge_reward(reward))
        self.assertFalse(store.claim_challenge_reward(reward))
        self.assertEqual(
            (store.data["gold"], store.data["silver"], store.data["fame"]),
            (11, 4020, 4003),
        )
        self.assertIn(130078, store.data["owned_items"])
        self.assertEqual(store.completed_challenges(), [3])

        reloaded = EconomyStore(path)
        self.assertEqual(reloaded.completed_challenges(), [3])
        self.assertFalse(reloaded.claim_challenge_reward(reward))

    def test_daily_challenge_claims_reset_by_utc_date(self):
        store, _ = self.make_store({
            "gold": 0,
            "silver": 0,
            "fame": 0,
            "owned_items": [],
        })
        day1 = datetime.date(2026, 8, 26)
        day2 = datetime.date(2026, 8, 27)
        reward = V106_CHALLENGE_REWARDS[52]

        self.assertTrue(store.claim_challenge_reward(
            reward, daily=True, claim_date=day1
        ))
        self.assertFalse(store.claim_challenge_reward(
            reward, daily=True, claim_date=day1
        ))
        self.assertEqual(store.completed_challenges(True, day1), [52])
        self.assertEqual(store.completed_challenges(True, day2), [])
        self.assertTrue(store.claim_challenge_reward(
            reward, daily=True, claim_date=day2
        ))
        self.assertEqual(store.data["silver"], 4000)
        self.assertEqual(store.data["fame"], 4000)

    def test_reward_balances_are_exactly_three_u32(self):
        body = encode_reward_balances(1, 259, 56)

        self.assertEqual(len(body), 12)
        self.assertEqual(struct.unpack("<III", body), (1, 259, 56))

    def test_reward_balances_preserve_login_fame_slot(self):
        body = encode_reward_balances(1, 292, 140)

        self.assertEqual(struct.unpack("<III", body), (1, 292, 140))

    def test_shop_record_enumeration_without_native_ids_is_an_empty_list(self):
        body = encode_shop_records()

        self.assertEqual(body, struct.pack("<I", 0))

    def test_slot_entitlements_returns_only_roster_slot_purchases(self):
        store, _ = self.make_store({
            "owned_items": [10236, 80007, 80001, 80002, 80008],
        })

        self.assertEqual(store.slot_entitlements(), [80002, 80007])

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
