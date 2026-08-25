import datetime
import http.client
import json
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
        self.assertEqual(struct.unpack_from("<Q", body, 36)[0], packed_time)

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
