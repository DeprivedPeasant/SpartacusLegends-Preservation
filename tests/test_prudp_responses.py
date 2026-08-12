import struct
import sys
from pathlib import Path
import unittest


TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))

import prudp_server as p


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


if __name__ == "__main__":
    unittest.main()
