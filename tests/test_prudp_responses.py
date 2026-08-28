import datetime
import http.client
import json
import os
import struct
import sys
import tempfile
import threading
from pathlib import Path
import unittest
from http.server import ThreadingHTTPServer


TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))

import prudp_server as p
from UbiOnlineConfigService import spartacus_onlineconfig


class MonetizationInventoryResponseTests(unittest.TestCase):
    def test_price_probe_parser_accepts_multiple_u32_rows(self):
        self.assertEqual(
            p.parse_inventory_price_probe("60001:10:0, 60020:0:500"),
            {60001: (10, 0), 60020: (0, 500)},
        )

    def test_price_probe_parser_rejects_malformed_or_negative_rows(self):
        for value in ("60001:10", "60001:-1:0"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                p.parse_inventory_price_probe(value)

    def test_price_probe_can_advertise_one_unowned_requested_item(self):
        self.assertEqual(
            p.method_3_response_items(
                [60100, 60101],
                [],
                title_version="01.06",
                price_probe={60101: (10, 0)},
            ),
            [60101],
        )

    def test_v106_advertises_prices_for_owned_and_unowned_boosts(self):
        self.assertEqual(
            p.method_3_response_items(
                [60001, 60002, 60003, 10250],
                [60002, 10250],
                title_version="01.06",
                price_probe={},
            ),
            [60001, 60002, 60003, 10250],
        )

    def test_v106_gold_boost_row_repeats_retail_as_ordinary_price(self):
        row = p.encode_inventory_item(60003, title_version="01.06")

        self.assertEqual(struct.unpack_from("<I", row, 0)[0], 60003)
        self.assertEqual(
            struct.unpack_from("<I?II?II", row, 7),
            (0, False, 10, 0, False, 0, 0),
        )

    def test_v106_silver_boost_row_preserves_both_catalog_price_words(self):
        row = p.encode_inventory_item(60020, title_version="01.06")

        self.assertEqual(
            struct.unpack_from("<I?II?II", row, 7),
            (0, False, 1, 500, False, 0, 0),
        )

    def test_v100_inventory_row_bytes_are_unchanged(self):
        row = p.encode_inventory_item(60003, title_version="01.00")

        self.assertEqual(
            struct.unpack_from("<I?II?II", row, 7),
            (0, False, 0, 0, False, 1, 0),
        )

    def test_v106_omits_consumables_that_method_8_restores(self):
        items = [10250, 60000, 60020, 60063, 80002]

        self.assertEqual(
            p.method_3_inventory_items(items, title_version="01.06"),
            [10250, 80002],
        )

    def test_v100_inventory_behavior_is_unchanged(self):
        items = [10250, 60000, 60020, 60063, 80002]

        self.assertEqual(
            p.method_3_inventory_items(items, title_version="01.00"),
            items,
        )

    def test_only_the_exact_consumable_family_is_suppressed(self):
        items = [59999, 60000, 60063, 60064]

        self.assertEqual(
            p.method_3_inventory_items(items, title_version="01.06"),
            [59999, 60064],
        )


class TournamentResponseTests(unittest.TestCase):
    """Protocol 105 method 7, GetJoinedSeason in title version 01.06."""

    def test_not_joined_body_matches_client_decoder_layout(self):
        body = p.encode_no_joined_tournament_season()

        self.assertEqual(len(body), 39)
        self.assertEqual(struct.unpack_from("<I", body, 0)[0], 0)
        self.assertEqual(struct.unpack_from("<H", body, 4)[0], 1)
        self.assertEqual(body[6:7], b"\x00")
        self.assertEqual(
            struct.unpack_from("<QQIIII", body, 7),
            (0, 0, 0, 0, 0, 0),
        )

    def test_not_joined_response_frame_is_well_formed(self):
        body = p.encode_no_joined_tournament_season()
        frame = p.build_rmc_response(p.PROTO_TOURNAMENT, 80, 7, body)

        self.assertEqual(struct.unpack_from("<I", frame, 0)[0], len(frame) - 4)
        self.assertEqual(frame[4], p.PROTO_TOURNAMENT)
        self.assertEqual(frame[5], 1)
        self.assertEqual(struct.unpack_from("<II", frame, 6), (80, 0x8007))
        self.assertEqual(frame[14:], body)

    def test_protocol_number_is_105(self):
        self.assertEqual(p.PROTO_TOURNAMENT, 105)

    def test_no_tournament_lists_body_is_two_zero_counts(self):
        body = p.encode_v106_protocol_response(p.PROTO_TOURNAMENT, 14)
        self.assertEqual(body, struct.pack("<II", 0, 0))

    def test_boot_tournament_responses_match_top_level_decoders(self):
        method2 = p.encode_v106_protocol_response(p.PROTO_TOURNAMENT, 2)
        self.assertEqual(len(method2), 33)
        self.assertEqual(struct.unpack("<I?QQIII", method2),
                         (0, False, 0, 0, 0, 0, 0))
        self.assertEqual(
            p.encode_v106_protocol_response(p.PROTO_TOURNAMENT, 5),
            struct.pack("<II", 0, 0),
        )


class V106InactiveResponseTests(unittest.TestCase):
    """Exact no-active-event layouts recovered from 01.06 decoders."""

    def test_login_reward_methods(self):
        now = datetime.datetime(
            2026, 8, 26, 12, 34, 56, tzinfo=datetime.timezone.utc
        )
        self.assertEqual(
            p.encode_v106_protocol_response(p.PROTO_LOGIN_REWARD, 1),
            b"\x00",
        )
        self.assertEqual(
            p.encode_v106_protocol_response(p.PROTO_LOGIN_REWARD, 2),
            struct.pack("<III", 0, 0, 0),
        )
        body = p.encode_v106_protocol_response(
            p.PROTO_LOGIN_REWARD, 3, now=now
        )
        self.assertEqual(len(body), 20)
        self.assertEqual(struct.unpack("<IIIQ", body),
                         (0, 0, 0, p.encode_qdatetime(now)))
        self.assertEqual(
            p.encode_v106_protocol_response(p.PROTO_LOGIN_REWARD, 4),
            struct.pack("<I", 0),
        )

    def test_daily_popup_inactive_object(self):
        body = p.encode_v106_protocol_response(p.PROTO_DAILY_POPUP, 1)
        self.assertEqual(len(body), 11)
        self.assertEqual(struct.unpack("<?I??I", body),
                         (False, 0, False, False, 0))

    def test_login_reward_list_preserves_retail_database_order(self):
        rewards = [
            (1, 0, 0, 300, 0, 0),
            (2, 60008, 1, 0, 0, 0),
        ]
        body = p.encode_v106_daily_login_reward_list(rewards)

        self.assertEqual(len(body), 4 + 2 * 24)
        self.assertEqual(struct.unpack_from("<I", body), (2,))
        self.assertEqual(
            struct.unpack_from("<6I", body, 4),
            (1, 0, 0, 300, 0, 0),
        )
        self.assertEqual(
            struct.unpack_from("<6I", body, 28),
            (2, 60008, 1, 0, 0, 0),
        )

    def test_login_reward_wire_order_differs_from_challenge_wire_order(self):
        reward = (9, 130031, 2, 4000, 20, 3000)

        self.assertEqual(
            struct.unpack("<6I", p.encode_v106_daily_login_reward(reward)),
            reward,
        )
        self.assertEqual(
            struct.unpack("<6I", p.encode_v106_challenge_reward(reward)),
            (9, 20, 4000, 3000, 130031, 2),
        )

    def test_challenge_empty_lists(self):
        for method in (2, 4):
            with self.subTest(method=method):
                self.assertEqual(
                    p.encode_v106_protocol_response(p.PROTO_CHALLENGE, method),
                    struct.pack("<I", 0),
                )

    def test_community_boss_empty_lists(self):
        for method in (1, 5):
            with self.subTest(method=method):
                self.assertEqual(
                    p.encode_v106_protocol_response(
                        p.PROTO_COMMUNITY_BOSS_FIGHT, method
                    ),
                    struct.pack("<I", 0),
                )

    def test_unproven_methods_fall_through(self):
        self.assertIsNone(
            p.encode_v106_protocol_response(p.PROTO_TOURNAMENT, 1)
        )
        self.assertIsNone(
            p.encode_v106_protocol_response(p.PROTO_CHALLENGE, 5)
        )

    def test_observed_challenge_claims_translate_db_rows_to_rpc_order(self):
        for challenge_id, expected in (
            (4, (4, 0, 1000, 0, 0, 0)),
            (43, (43, 0, 2000, 0, 0, 0)),
        ):
            with self.subTest(challenge_id=challenge_id):
                body = p.encode_v106_protocol_response(
                    p.PROTO_CHALLENGE, 1,
                    struct.pack("<II", 0x2000, challenge_id),
                )
                self.assertEqual(len(body), 24)
                self.assertEqual(struct.unpack("<6I", body), expected)

    def test_challenge_claim_rpc_order_covers_every_reward_component(self):
        body = p.encode_v106_challenge_reward(
            (9, 130031, 2, 4000, 20, 3000)
        )
        self.assertEqual(
            struct.unpack("<6I", body),
            (9, 20, 4000, 3000, 130031, 2),
        )

    def test_unknown_challenge_claim_is_structural_zero_reward(self):
        body = p.encode_v106_protocol_response(
            p.PROTO_CHALLENGE, 1, struct.pack("<II", 0x2000, 999)
        )
        self.assertEqual(body, struct.pack("<6I", 0, 0, 0, 0, 0, 0))

    def test_observed_daily_challenge_claim_request_returns_daily_reward(self):
        body = p.encode_v106_protocol_response(
            p.PROTO_CHALLENGE, 3,
            struct.pack("<IQ", 52, 0x0000001FA9F293E3),
        )
        self.assertEqual(
            struct.unpack("<6I", body),
            (52, 0, 2000, 2000, 0, 0),
        )

    def test_protocol_numbers(self):
        self.assertEqual(
            (p.PROTO_LOGIN_REWARD, p.PROTO_DAILY_POPUP,
             p.PROTO_CHALLENGE, p.PROTO_COMMUNITY_BOSS_FIGHT),
            (107, 108, 109, 110),
        )


class PatchVersionResponseTests(unittest.TestCase):
    """Protocol 106 method 1, the 01.06 boot gate.

    Live 2026-08-26: CheckPatchVersions compares fields 0, 1 and 2 against
    s_application +0x1A08/+0x1A0C/+0x1A10, which read 3, 2, 2 on this
    install. See notes/13-v106-port.md.
    """

    def setUp(self):
        self._saved = {k: v for k, v in os.environ.items()
                       if k.startswith("P106M1_")}
        for key in self._saved:
            del os.environ[key]

    def tearDown(self):
        for key in [k for k in os.environ if k.startswith("P106M1_")]:
            del os.environ[key]
        os.environ.update(self._saved)

    def test_body_is_exactly_five_u32_and_defaults_to_live_triple(self):
        body, fields = p.encode_patch_version_response()
        self.assertEqual(len(body), 20)
        self.assertEqual(fields, [3, 2, 2, 0, 0])
        self.assertEqual(struct.unpack("<5I", body), (3, 2, 2, 0, 0))

    def test_default_matches_the_live_client_side_check(self):
        _body, fields = p.encode_patch_version_response()
        app_x360, app_scea, app_scee = 3, 2, 2
        self.assertEqual(fields[0], app_x360)
        self.assertEqual(fields[1], app_scea)
        self.assertEqual(fields[2], app_scee)

    def test_body_is_not_empty(self):
        # An empty body starves the client's decoder and reproduces the
        # observed ASYNC_STATUS_NONE hang; length alone guards that.
        body, _fields = p.encode_patch_version_response()
        self.assertNotEqual(body, b"")

    def test_fields_are_overridable_for_a_config_that_sets_versions(self):
        os.environ["P106M1_0"] = "7"
        os.environ["P106M1_1"] = "0x10"
        os.environ["P106M1_2"] = "9"
        body, fields = p.encode_patch_version_response()
        self.assertEqual(fields, [7, 16, 9, 0, 0])
        self.assertEqual(struct.unpack("<5I", body), (7, 16, 9, 0, 0))

    def test_response_frame_is_well_formed(self):
        body, _fields = p.encode_patch_version_response()
        frame = p.build_rmc_response(p.PROTO_PATCH_VERSION, 55, 1, body)
        length = struct.unpack_from("<I", frame, 0)[0]
        self.assertEqual(length, len(frame) - 4)
        self.assertEqual(frame[4], p.PROTO_PATCH_VERSION)
        self.assertEqual(frame[5], 1)                      # success
        call_id, method = struct.unpack_from("<II", frame, 6)
        self.assertEqual(call_id, 55)
        self.assertEqual(method, 1 | 0x8000)
        self.assertEqual(frame[14:], body)

    def test_explicit_override_still_wins(self):
        # The dispatch branch defers to PROTO_OVERRIDES so a live test can
        # force a different shape without a code change.
        self.assertNotIn((p.PROTO_PATCH_VERSION, 1), p.PROTO_OVERRIDES)
        p.PROTO_OVERRIDES[(p.PROTO_PATCH_VERSION, 1)] = "empty"
        try:
            self.assertIn((p.PROTO_PATCH_VERSION, 1), p.PROTO_OVERRIDES)
        finally:
            del p.PROTO_OVERRIDES[(p.PROTO_PATCH_VERSION, 1)]

    def test_protocol_number_is_106(self):
        self.assertEqual(p.PROTO_PATCH_VERSION, 106)
        self.assertEqual(p.PATCH_VERSION_FIELDS, 5)


class MonetizationResponseTests(unittest.TestCase):
    """Encoding invariants behind the unhandled-shop-method fallback.

    Protocol 102 is excluded from the generic fallback, so an unrecognised
    method used to get a bare transport ACK and hang the client forever. The
    fallback answers with the m7/m13 receipt by default; these tests pin the
    properties that make that default safe.
    """

    def test_receipt_is_a_superset_of_the_balance_pair(self):
        # A client expecting only <gold, silver> (m6/m11) must be able to read
        # those two fields from the longer receipt and ignore the remainder.
        # This is why the receipt is the default fallback shape.
        gold, silver = 1234, 5678
        receipt = p.encode_purchase_result(
            gold, silver, 4242, transaction_time=p.encode_qdatetime(),
            quantity=1,
        )
        self.assertEqual(receipt[:8], struct.pack("<II", gold, silver))
        self.assertEqual(len(receipt), 24)

    def test_success_response_frame_is_well_formed(self):
        body = struct.pack("<II", 5, 6)
        frame = p.build_rmc_response(102, 42, 17, body)
        declared = struct.unpack_from("<I", frame, 0)[0]
        self.assertEqual(declared, len(frame) - 4)
        self.assertEqual(frame[4], 102)          # protocol
        self.assertEqual(frame[5], 1)            # success
        call_id, method = struct.unpack_from("<II", frame, 6)
        self.assertEqual(call_id, 42)
        self.assertEqual(method, 17 | 0x8000)    # response marker
        self.assertEqual(frame[14:], body)

    def test_error_response_frame_is_well_formed(self):
        frame = p.build_rmc_error(102, 42, 0x80010001)
        declared = struct.unpack_from("<I", frame, 0)[0]
        self.assertEqual(declared, len(frame) - 4)
        self.assertEqual(frame[4], 102)          # protocol
        self.assertEqual(frame[5], 0)            # failure
        code, call_id = struct.unpack_from("<II", frame, 6)
        self.assertEqual(code, 0x80010001)
        self.assertEqual(call_id, 42)

    def test_quazal_timestamp_is_nonzero(self):
        # A zero timestamp decodes as an invalid pre-epoch value and caused the
        # v0.3.1 recruit-pool refresh loop; every receipt must carry a real one.
        self.assertNotEqual(p.encode_qdatetime(), 0)

    def test_monetization_method_8_encodes_empty_list_and_quazal_time(self):
        value = datetime.datetime(
            2026, 8, 24, 21, 3, 27, tzinfo=datetime.timezone.utc
        )
        body = p.encode_monetization_server_time(value)

        self.assertEqual(len(body), 12)
        count, server_time = struct.unpack("<IQ", body)
        self.assertEqual(count, 0)
        self.assertEqual(server_time, p.encode_qdatetime(value))

    def test_monetization_method_8_encodes_slot_transactions(self):
        value = datetime.datetime(
            2026, 8, 24, 21, 3, 27, tzinfo=datetime.timezone.utc
        )
        packed_time = p.encode_qdatetime(value)
        body = p.encode_monetization_server_time(
            value, transactions=[80002, 80004]
        )

        self.assertEqual(len(body), 44)
        self.assertEqual(struct.unpack_from("<I", body, 0)[0], 2)
        self.assertEqual(
            struct.unpack_from("<IQI", body, 4),
            (80002, packed_time, 1),
        )
        self.assertEqual(
            struct.unpack_from("<IQI", body, 20),
            (80004, packed_time, 1),
        )

    def test_monetization_method_8_preserves_consumable_quantity(self):
        value = datetime.datetime(
            2026, 8, 24, 21, 3, 27, tzinfo=datetime.timezone.utc
        )
        packed_time = p.encode_qdatetime(value)
        body = p.encode_monetization_server_time(
            value, transactions=[(80002, 1), (60020, 17)]
        )

        self.assertEqual(struct.unpack_from("<I", body, 0)[0], 2)
        self.assertEqual(
            struct.unpack_from("<IQI", body, 4),
            (80002, packed_time, 1),
        )
        self.assertEqual(
            struct.unpack_from("<IQI", body, 20),
            (60020, packed_time, 17),
        )
        self.assertEqual(struct.unpack_from("<Q", body, 36)[0], packed_time)

    def test_affected_monetization_histories_are_fragmented(self):
        # The affected user's successive logs contained 73 and 97 persisted
        # transactions, yielding 1194- and 1578-byte RMC messages. Both must
        # cross the wire as two packets rather than one oversized datagram.
        for transaction_count, expected_body_size in ((73, 1180), (97, 1564)):
            with self.subTest(transaction_count=transaction_count):
                body = p.encode_monetization_server_time(
                    transactions=[
                        (60000 + index, 1)
                        for index in range(transaction_count)
                    ]
                )
                rmc = p.build_rmc_response(102, 42, 8, body)

                self.assertEqual(len(body), expected_body_size)
                self.assertGreater(len(rmc), p.PRUDP_FRAGMENT_SIZE)
                self.assertEqual(p.data_fragment_count(rmc), 2)
                packets = p.build_data_fragments(
                    0x10, 0x2F, 0xA5, 100, 0x12345678, rmc
                )
                decoded = [self.decode_fragment(packet) for packet in packets]
                self.assertEqual(len(packets), 2)
                self.assertEqual(
                    [entry[0]["fragment_id"] for entry in decoded], [1, 0]
                )
                self.assertEqual(b"".join(entry[1] for entry in decoded), rmc)
                self.assertTrue(all(len(packet) <= 1000 for packet in packets))

    def decode_fragment(self, packet):
        info = p.parse(packet)
        self.assertIsNotNone(info)
        self.assertTrue(info["checksum_ok"])
        plain = p.rc4(p.KEY_DATA, info["payload"])
        self.assertEqual(plain[0], 0)
        return info, plain[1:]

    def test_large_response_uses_ordered_fragments_and_final_zero(self):
        payload = bytes(index & 0xFF for index in range(2000))
        packets = p.build_data_fragments(
            0x10, 0x2F, 0xA5, 100, 0x12345678, payload
        )

        self.assertEqual(len(packets), 3)
        decoded = [self.decode_fragment(packet) for packet in packets]
        infos = [entry[0] for entry in decoded]
        self.assertEqual([info["fragment_id"] for info in infos], [1, 2, 0])
        self.assertEqual([info["sequence_id"] for info in infos], [100, 101, 102])
        self.assertTrue(all(
            info["flags"] == p.FLAG_NEED_ACK
            for info in infos
        ))
        self.assertEqual([len(entry[1]) for entry in decoded], [962, 962, 76])
        self.assertEqual(b"".join(entry[1] for entry in decoded), payload)

    def test_single_fragment_retains_final_zero_marker(self):
        packets = p.build_data_fragments(
            0x10, 0x2F, 0xA5, 0xFFFF, 0x12345678, b"small"
        )

        self.assertEqual(len(packets), 1)
        info, payload = self.decode_fragment(packets[0])
        self.assertEqual(info["fragment_id"], 0)
        self.assertEqual(info["sequence_id"], 0xFFFF)
        self.assertEqual(payload, b"small")

    def test_explicit_reliable_flag_is_preserved_for_push_messages(self):
        packets = p.build_data_fragments(
            0x10, 0x2F, 0xA5, 10, 0x12345678, b"push",
            flags=p.FLAG_RELIABLE | p.FLAG_NEED_ACK,
        )

        info, payload = self.decode_fragment(packets[0])
        self.assertEqual(
            info["flags"], p.FLAG_RELIABLE | p.FLAG_NEED_ACK
        )
        self.assertEqual(payload, b"push")

    def test_fragment_sequence_wraps_at_u16_boundary(self):
        packets = p.build_data_fragments(
            0x10, 0x2F, 0xA5, 0xFFFF, 0x12345678,
            b"x" * (p.PRUDP_FRAGMENT_SIZE + 1),
        )

        infos = [self.decode_fragment(packet)[0] for packet in packets]
        self.assertEqual([info["sequence_id"] for info in infos], [0xFFFF, 0])
        self.assertEqual([info["fragment_id"] for info in infos], [1, 0])

    def test_shop_method_24_encodes_exact_owned_record_shape(self):
        body = p.encode_shop_records([(1000, 1), (1007, 0)])

        self.assertEqual(len(body), 4 + 2 * 21)
        self.assertEqual(struct.unpack_from("<I", body, 0)[0], 2)
        self.assertEqual(
            struct.unpack_from("<IIIIBI", body, 4),
            (1000, 0, 0, 0, 1, 0),
        )
        self.assertEqual(
            struct.unpack_from("<IIIIBI", body, 25),
            (1007, 0, 0, 0, 0, 0),
        )

    def test_recruit_request_layouts_match_live_title_captures(self):
        v100 = bytes.fromhex(
            "ee030000 00000000 ffffffff a4010000"
        )
        v106 = bytes.fromhex(
            "f0030000 00000000 06000000 ffffffff a4010000"
        )

        self.assertEqual(
            p.decode_recruit_request(v100, "01.00"),
            (1006, 0, None, -1, 420),
        )
        self.assertEqual(
            p.decode_recruit_request(v106, "01.06"),
            (1008, 0, 6, -1, 420),
        )

    def test_shop_method_24_reads_keys_from_v106_native_roster(self):
        payload = bytearray(p.V106_ROSTER_OWNED_COUNT_OFFSET + 4)
        struct.pack_into(">I", payload, p.V106_ROSTER_OWNED_COUNT_OFFSET, 2)
        struct.pack_into(
            ">I", payload,
            p.V106_ROSTER_FIRST_OWNED_OFFSET + p.V106_ROSTER_OWNED_KEY_OFFSET,
            1000,
        )
        struct.pack_into(
            ">I", payload,
            p.V106_ROSTER_FIRST_OWNED_OFFSET + p.V106_ROSTER_RECORD_STRIDE
            + p.V106_ROSTER_OWNED_KEY_OFFSET,
            1007,
        )
        payload[
            p.V106_ROSTER_FIRST_OWNED_OFFSET
            + p.V106_ROSTER_OWNED_ACTIVE_OFFSET
        ] = 1
        old_dir = os.environ.get("SPARTACUS_USER_CONTENT_DIR")
        try:
            with tempfile.TemporaryDirectory() as directory:
                os.environ["SPARTACUS_USER_CONTENT_DIR"] = directory
                path = Path(p.user_content_path(p.V106_ROSTER_TYPE_ID, 1))
                path.parent.mkdir(parents=True)
                path.write_bytes(payload)
                self.assertEqual(
                    p.read_v106_owned_gladiator_records(),
                    ((1000, 1), (1007, 0)),
                )
        finally:
            if old_dir is None:
                os.environ.pop("SPARTACUS_USER_CONTENT_DIR", None)
            else:
                os.environ["SPARTACUS_USER_CONTENT_DIR"] = old_dir

    def test_shop_method_24_rejects_impossible_native_count(self):
        payload = bytearray(p.V106_ROSTER_OWNED_COUNT_OFFSET + 4)
        struct.pack_into(
            ">I", payload, p.V106_ROSTER_OWNED_COUNT_OFFSET,
            p.V106_ROSTER_MAX_OWNED + 1,
        )
        old_dir = os.environ.get("SPARTACUS_USER_CONTENT_DIR")
        try:
            with tempfile.TemporaryDirectory() as directory:
                os.environ["SPARTACUS_USER_CONTENT_DIR"] = directory
                path = Path(p.user_content_path(p.V106_ROSTER_TYPE_ID, 1))
                path.parent.mkdir(parents=True)
                path.write_bytes(payload)
                self.assertEqual(p.read_v106_owned_gladiator_records(), ())
        finally:
            if old_dir is None:
                os.environ.pop("SPARTACUS_USER_CONTENT_DIR", None)
            else:
                os.environ["SPARTACUS_USER_CONTENT_DIR"] = old_dir

    def test_user_content_url_uses_three_quazal_strings(self):
        body = p.encode_user_content_url(
            "http://", "127.0.0.1", "/remoteconfig.bin")
        values = []
        offset = 0
        for _ in range(3):
            size = struct.unpack_from("<H", body, offset)[0]
            offset += 2
            values.append(body[offset:offset + size])
            offset += size
        self.assertEqual(values, [
            b"http://\0", b"127.0.0.1\0", b"/remoteconfig.bin\0"
        ])
        self.assertEqual(offset, len(body))

    def test_userstorage_create_upload_result_contains_url_id_and_empty_list(self):
        old_host = p.os.environ.get("SPARTACUS_USER_CONTENT_HOST")
        try:
            p.os.environ["SPARTACUS_USER_CONTENT_HOST"] = "127.0.0.1"
            body = p.encode_user_content_upload_result(0x80000003, 7)
        finally:
            if old_host is None:
                p.os.environ.pop("SPARTACUS_USER_CONTENT_HOST", None)
            else:
                p.os.environ["SPARTACUS_USER_CONTENT_HOST"] = old_host

        values = []
        offset = 0
        for _ in range(3):
            size = struct.unpack_from("<H", body, offset)[0]
            offset += 2
            values.append(body[offset:offset + size].rstrip(b"\0"))
            offset += size
        content_id, header_count = struct.unpack_from("<QI", body, offset)
        self.assertEqual(values, [
            b"http://", b"127.0.0.1", b"/usercontent/80000003/7.bin"
        ])
        self.assertEqual((content_id, header_count), (7, 0))
        self.assertEqual(offset + 12, len(body))

    def test_get_own_contents_returns_one_exact_matching_key(self):
        body = p.encode_user_content_rows(0x80000003, 1, 0x2000, 2)
        self.assertEqual(len(body), 37)
        self.assertEqual(
            struct.unpack_from("<IIQII", body),
            (1, 0x80000003, 1, 0x2000, 1),
        )
        self.assertEqual(struct.unpack_from("<IBQ", body, 24), (100, 1, 2))

    def test_type1_profile_readback_uses_full_payload_format(self):
        self.assertEqual(p.USER_CONTENT_FORMAT_VERSIONS[0x80000001], 2)
        body = p.encode_user_content_rows(
            0x80000001, 1, 0x2000,
            p.USER_CONTENT_FORMAT_VERSIONS[0x80000001],
        )
        self.assertEqual(struct.unpack_from("<IBQ", body, 24), (100, 1, 2))

    def test_v106_readback_replays_writer_format_selectors(self):
        self.assertEqual(
            {
                type_id: p.user_content_format_version(type_id, "01.06")
                for type_id in (0x80000001, 0x80000002, 0x80000003)
            },
            {
                0x80000001: 5,
                0x80000002: 2,
                0x80000003: 4,
            },
        )
        for type_id, expected_format in (
            (0x80000001, 5),
            (0x80000002, 2),
            (0x80000003, 4),
        ):
            body = p.encode_user_content_rows(
                type_id, 1, 0x2000, expected_format
            )
            self.assertEqual(
                struct.unpack_from("<IBQ", body, 24),
                (100, 1, expected_format),
            )

    def test_download_url_points_at_persisted_content_key(self):
        old_host = p.os.environ.get("SPARTACUS_USER_CONTENT_HOST")
        try:
            p.os.environ["SPARTACUS_USER_CONTENT_HOST"] = "127.0.0.1"
            body = p.encode_user_content_download_url(0x80000003, 1)
        finally:
            if old_host is None:
                p.os.environ.pop("SPARTACUS_USER_CONTENT_HOST", None)
            else:
                p.os.environ["SPARTACUS_USER_CONTENT_HOST"] = old_host
        values = []
        offset = 0
        for _ in range(3):
            size = struct.unpack_from("<H", body, offset)[0]
            offset += 2
            values.append(body[offset:offset + size].rstrip(b"\0"))
            offset += size
        self.assertEqual(values, [
            b"http://", b"127.0.0.1", b"/usercontent/80000003/1.bin"
        ])
        self.assertEqual(offset, len(body))

    def test_user_content_http_put_then_get_round_trip(self):
        class QuietLog:
            def write(self, _message):
                pass

        payload = bytes(range(256)) * 3
        with tempfile.TemporaryDirectory() as directory:
            handler = spartacus_onlineconfig.make_handler(
                "127.0.0.1", 21000, QuietLog(), Path(directory)
            )
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                connection = http.client.HTTPConnection(
                    "127.0.0.1", server.server_port, timeout=2
                )
                route = "/usercontent/80000003/7.bin"
                connection.request("PUT", route, payload)
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                response.read()
                connection.close()

                connection = http.client.HTTPConnection(
                    "127.0.0.1", server.server_port, timeout=2
                )
                connection.request("GET", route)
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                self.assertEqual(response.read(), payload)
                connection.close()
                self.assertEqual(
                    (Path(directory) / "80000003" / "7.bin").read_bytes(),
                    payload,
                )
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

    def test_remote_config_row_contains_hash_and_version_properties(self):
        digest = "7913A13830F32D6E2F8314A4A343422C" \
                 "BBC4F0F98ABEB10373C908E9AC7F8E30"
        body = p.encode_remote_config_content(0x80000004, 1, 0x2000, digest)
        count, type_id = struct.unpack_from("<II", body, 0)
        content_id, owner_pid, property_count = struct.unpack_from(
            "<QII", body, 8)
        self.assertEqual(
            (count, type_id, content_id, owner_pid, property_count),
            (1, 0x80000004, 1, 0x2000, 3),
        )
        self.assertEqual(struct.unpack_from("<IBQ", body, 24), (5, 5, 1))
        self.assertEqual(struct.unpack_from("<IBQ", body, 37), (100, 1, 1))
        property_id, variant_type = struct.unpack_from("<IB", body, 50)
        self.assertEqual((property_id, variant_type), (101, 4))
        size = struct.unpack_from("<H", body, 55)[0]
        self.assertEqual(body[57:57 + size], digest.encode() + b"\0")

    def test_remote_config_body_is_empty_big_endian_kff_v1(self):
        self.assertEqual(
            spartacus_onlineconfig.make_remote_config_response(),
            b"\x00\x00\x00\x01\x00\x00\x00\x00",
        )

    def test_userstorage_capture_preserves_raw_params_and_identity(self):
        params = b"\x00\xff\x01\x80raw\x00"
        rmc = {
            "protocol": p.PROTO_USER_STORAGE,
            "is_request": True,
            "call_id": 0x1234,
            "method_id": 77,
            "params": params,
        }
        packet = {
            "source": 0x2F,
            "destination": 0x10,
            "session_id": 0xAB,
            "sequence_id": 9,
            "signature": 0x10203040,
        }
        state = {"account_username": "PepisMax", "account_pid": 0x2000}
        old_dir = p.USERSTORAGE_CAPTURE_DIR
        old_enabled = p.USERSTORAGE_CAPTURE_ENABLED
        try:
            with tempfile.TemporaryDirectory() as directory:
                p.USERSTORAGE_CAPTURE_DIR = directory
                p.USERSTORAGE_CAPTURE_ENABLED = True
                payload_path = p.capture_userstorage_request(
                    rmc, packet, ("127.0.0.1", 21000), state
                )
                self.assertIsNotNone(payload_path)
                self.assertEqual(Path(payload_path).read_bytes(), params)
                metadata = json.loads(
                    Path(payload_path).with_suffix(".json").read_text(
                        encoding="utf-8"
                    )
                )
                self.assertEqual(metadata["method_id"], 77)
                self.assertFalse(metadata["known_method"])
                self.assertEqual(metadata["params_length"], len(params))
                self.assertEqual(metadata["account"], {
                    "username": "PepisMax", "pid": 0x2000
                })
                self.assertEqual(metadata["transport"]["session_id"], 0xAB)
        finally:
            p.USERSTORAGE_CAPTURE_DIR = old_dir
            p.USERSTORAGE_CAPTURE_ENABLED = old_enabled


if __name__ == "__main__":
    unittest.main()
