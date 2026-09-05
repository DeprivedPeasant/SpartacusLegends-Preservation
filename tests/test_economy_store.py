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
    V106_DAILY_LOGIN_REWARDS,
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

    def test_daily_login_grants_at_most_one_stage_per_utc_date(self):
        store, path = self.make_store({
            "gold": 0,
            "silver": 200,
            "fame": 0,
            "owned_items": [],
        })
        day1 = datetime.date(2026, 8, 27)
        day2 = datetime.date(2026, 8, 28)

        self.assertTrue(store.register_daily_login(day1))
        self.assertFalse(store.register_daily_login(day1))
        self.assertEqual(
            store.daily_login_rewards(),
            [V106_DAILY_LOGIN_REWARDS[1][0]],
        )
        self.assertTrue(store.register_daily_login(day2))
        self.assertEqual(
            [reward[0] for reward in store.daily_login_rewards()],
            [1, 2],
        )

        reloaded = EconomyStore(path)
        self.assertEqual(
            reloaded.daily_login_rewards(),
            store.daily_login_rewards(),
        )
        self.assertFalse(reloaded.register_daily_login(day2))

    def test_daily_login_grows_across_daily_server_restarts(self):
        store, path = self.make_store({})
        start = datetime.date(2026, 9, 1)
        schedule = None
        for offset in range(7):
            store = EconomyStore(path)
            day = start + datetime.timedelta(days=offset)
            self.assertTrue(store.register_daily_login(day))
            current_schedule, stage, _ = store.daily_login_info()
            if schedule is None:
                schedule = current_schedule
            self.assertEqual(current_schedule, schedule)
            self.assertEqual(stage, offset)
            self.assertEqual(store.daily_login_rewards(), schedule[:offset + 1])
            reloaded = EconomyStore(path)
            self.assertFalse(reloaded.register_daily_login(day))
            self.assertEqual(reloaded.daily_login_rewards(), schedule[:offset + 1])

    def test_daily_login_cash_in_each_day_restarts_at_day_one(self):
        store, path = self.make_store({})
        start = datetime.date(2026, 9, 1)
        for offset in range(3):
            store = EconomyStore(path)
            day = start + datetime.timedelta(days=offset)
            self.assertTrue(store.register_daily_login(day))
            self.assertEqual(store.claim_daily_login_rewards(),
                             [V106_DAILY_LOGIN_REWARDS[1][0]])
            reloaded = EconomyStore(path)
            self.assertFalse(reloaded.register_daily_login(day))
            self.assertEqual(reloaded.daily_login_rewards(), [])
            self.assertEqual(reloaded.data["daily_login"]["schedule"], [])

    def test_daily_login_info_exposes_stage_and_utc_reset_countdown(self):
        store, _ = self.make_store({
            "gold": 0,
            "silver": 0,
            "fame": 0,
            "owned_items": [],
        })
        day = datetime.date(2026, 8, 26)
        self.assertTrue(store.register_daily_login(day))

        schedule, current_stage, reset_seconds = store.daily_login_info(
            datetime.datetime(
                2026, 8, 26, 23, 59, 30,
                tzinfo=datetime.timezone.utc,
            )
        )

        self.assertEqual(len(schedule), 7)
        self.assertEqual(schedule[0], V106_DAILY_LOGIN_REWARDS[1][0])
        self.assertIn(schedule[1], V106_DAILY_LOGIN_REWARDS[2])
        self.assertEqual(
            [reward[0] for reward in schedule], list(range(1, 8))
        )
        self.assertEqual(current_stage, 0)
        self.assertEqual(reset_seconds, 30)

    def test_daily_login_stash_stops_at_seven_retail_stages(self):
        store, _ = self.make_store({
            "gold": 0,
            "silver": 0,
            "fame": 0,
            "owned_items": [],
        })
        start = datetime.date(2026, 8, 1)

        for offset in range(7):
            self.assertTrue(store.register_daily_login(
                start + datetime.timedelta(days=offset)
            ))
        self.assertFalse(store.register_daily_login(
            start + datetime.timedelta(days=7)
        ))
        self.assertEqual(
            [reward[0] for reward in store.daily_login_rewards()],
            list(range(1, 8)),
        )

    def test_claim_daily_login_rewards_credits_and_clears_atomically(self):
        store, path = self.make_store({
            "gold": 2,
            "silver": 100,
            "fame": 5,
            "owned_items": [],
        })
        start = datetime.date(2026, 8, 1)
        for offset in range(7):
            store.register_daily_login(start + datetime.timedelta(days=offset))

        rewards = store.claim_daily_login_rewards()
        self.assertEqual([reward[0] for reward in rewards], list(range(1, 8)))
        self.assertEqual(store.daily_login_rewards(), [])
        self.assertEqual(
            (store.data["gold"], store.data["silver"], store.data["fame"]),
            (12, 3100, 5),
        )
        self.assertIn(rewards[1][1], store.data["owned_items"])
        self.assertIn(60006, store.data["owned_items"])
        self.assertIn(120051, store.data["owned_items"])
        self.assertEqual(store.claim_daily_login_rewards(), [])

        reloaded = EconomyStore(path)
        self.assertEqual(reloaded.daily_login_rewards(), [])
        self.assertEqual(
            (reloaded.data["gold"], reloaded.data["silver"]),
            (12, 3100),
        )

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

    def test_method_8_transactions_replay_complete_purchase_history(self):
        store, _ = self.make_store({
            "owned_items": [
                80002, 10250, 30001, 50002, 60020, 60021, 60022, 120051,
            ],
            "item_quantities": {
                "60020": 17,
                "60021": 1,
                "60022": 0,
            },
        })

        self.assertEqual(
            store.method_8_transactions(),
            [
                (10250, 1),
                (30001, 1),
                (50002, 1),
                (60020, 17),
                (60021, 1),
                (80002, 1),
                (120051, 1),
            ],
        )

    def test_legacy_face_carver_ownership_migrates_to_five_uses(self):
        store, _ = self.make_store({
            "owned_items": [60020],
        })

        self.assertEqual(store.item_quantity(60020), 5)
        self.assertEqual(store.item_quantity(60021), 0)

    def test_consume_item_decrements_and_persists_remaining_uses(self):
        store, path = self.make_store({
            "owned_items": [60020],
            "item_quantities": {"60020": 4},
        })

        self.assertEqual(store.consume_item(60020), 3)
        self.assertEqual(store.item_quantity(60020), 3)
        persisted = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(persisted["item_quantities"]["60020"], 3)

    def test_face_carver_refill_adds_five_uses_and_debits_again(self):
        store, _ = self.make_store({
            "gold": 20,
            "silver": 0,
            "owned_items": [60020],
            "item_quantities": {"60020": 4},
        })

        self.assertEqual(store.purchase(60020, 10, -1), (10, 0))
        self.assertEqual(store.item_quantity(60020), 9)

    def test_all_retail_boost_refills_survive_consumption_and_restart(self):
        for item_id in range(60001, 60024):
            with self.subTest(item_id=item_id):
                store, path = self.make_store({
                    "gold": 100, "owned_items": [item_id],
                    "item_quantities": {str(item_id): 1},
                })
                self.assertEqual(store.purchase(item_id, 20, -1)[0], 80)
                self.assertEqual(store.item_quantity(item_id), 6)
                self.assertEqual(store.consume_item(item_id), 5)
                store = EconomyStore(path)
                self.assertEqual(store.item_quantity(item_id), 5)
                self.assertIn((item_id, 5), store.method_8_transactions())
                for remaining in range(4, -1, -1):
                    self.assertEqual(store.consume_item(item_id), remaining)
                self.assertEqual(store.consume_item(item_id), 0)
                self.assertEqual(store.purchase(item_id, 20, -1)[0], 60)
                self.assertEqual(EconomyStore(path).item_quantity(item_id), 5)

    def test_new_boost_purchase_grants_five_and_refill_caps_at_99(self):
        store, path = self.make_store({"gold": 100})
        store.purchase(60006, 20, -1)
        self.assertEqual(EconomyStore(path).item_quantity(60006), 5)
        store.data["item_quantities"][60006] = 98
        store.purchase(60006, 20, -1)
        self.assertEqual(EconomyStore(path).item_quantity(60006), 99)

    def test_boost_fix_preserves_legacy_and_explicit_zero_counts(self):
        store, _ = self.make_store({
            "owned_items": [60005, 60006, 60020],
            "item_quantities": {"60006": 0},
        })
        self.assertEqual(store.item_quantity(60005), 1)
        self.assertEqual(store.item_quantity(60006), 0)
        self.assertEqual(store.item_quantity(60020), 5)

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
