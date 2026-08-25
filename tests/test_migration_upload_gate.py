"""Phase 3 tests: migration-aware native upload gating in the HTTP service."""

import http.client
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(TOOLS / "UbiOnlineConfigService"))

import migration_coordinator as mc
import spartacus_onlineconfig as soc


PROFILE_TYPE = 0x80000001
CAMPAIGN_TYPE = 0x80000002
ROSTER_TYPE = 0x80000003
SIZES = {PROFILE_TYPE: 0x1238, CAMPAIGN_TYPE: 0x1804, ROSTER_TYPE: 0x53C4}


class NullLog:
    def write(self, _message):
        pass


class UploadGateTests(unittest.TestCase):
    def test_pending_restore_types_are_deferred_retryably(self):
        gate = mc.UploadGate(states={
            ROSTER_TYPE: mc.ObjectState.PENDING,
            CAMPAIGN_TYPE: mc.ObjectState.PENDING,
        })
        for type_id in (ROSTER_TYPE, CAMPAIGN_TYPE):
            decision = gate.check(type_id, SIZES[type_id])
            self.assertFalse(decision.allowed)
            self.assertTrue(decision.retryable)
            self.assertEqual(decision.state, "pending")

    def test_type_1_is_always_uploadable_during_migration(self):
        gate = mc.UploadGate(states={PROFILE_TYPE: mc.ObjectState.PENDING})
        decision = gate.check(PROFILE_TYPE, SIZES[PROFILE_TYPE])
        self.assertTrue(decision.allowed)

    def test_restored_and_captured_types_accept_exact_lengths(self):
        gate = mc.UploadGate(states={
            ROSTER_TYPE: mc.ObjectState.RESTORED,
            CAMPAIGN_TYPE: mc.ObjectState.CAPTURED,
        })
        for type_id in (ROSTER_TYPE, CAMPAIGN_TYPE):
            self.assertTrue(gate.check(type_id, SIZES[type_id]).allowed)

    def test_wrong_length_is_never_accepted_while_a_gate_is_active(self):
        gate = mc.UploadGate()
        for type_id, state in (
            (ROSTER_TYPE, mc.ObjectState.RESTORED),
            (ROSTER_TYPE, mc.ObjectState.CAPTURED),
            (ROSTER_TYPE, mc.ObjectState.NOT_NEEDED),
            (CAMPAIGN_TYPE, mc.ObjectState.PENDING),
        ):
            gate.set_state(type_id, state)
            decision = gate.check(type_id, SIZES[type_id] - 1)
            self.assertFalse(decision.allowed)
            self.assertFalse(decision.retryable, str(state))

    def test_blocked_types_reject_even_exact_lengths(self):
        gate = mc.UploadGate(states={ROSTER_TYPE: mc.ObjectState.BLOCKED})
        decision = gate.check(ROSTER_TYPE, SIZES[ROSTER_TYPE])
        self.assertFalse(decision.allowed)
        self.assertFalse(decision.retryable)

    def test_record_stored_captures_only_unfinished_types(self):
        gate = mc.UploadGate(states={
            ROSTER_TYPE: mc.ObjectState.RESTORED,
            CAMPAIGN_TYPE: mc.ObjectState.COMPLETE,
        })
        self.assertIs(gate.record_stored(ROSTER_TYPE, SIZES[ROSTER_TYPE]),
                      mc.ObjectState.CAPTURED)
        self.assertIs(gate.record_stored(CAMPAIGN_TYPE, SIZES[CAMPAIGN_TYPE]),
                      mc.ObjectState.COMPLETE)

    def test_gate_from_report_maps_assessment_states(self):
        report = mc.InstallationReport()
        report.assessments = {
            PROFILE_TYPE: mc.TypeAssessment(PROFILE_TYPE,
                                            mc.ObjectState.PENDING),
            ROSTER_TYPE: mc.TypeAssessment(ROSTER_TYPE,
                                           mc.ObjectState.NOT_NEEDED),
        }
        gate = mc.UploadGate.from_report(report)
        # The roster already has a valid native object, so only the exact-size
        # rule applies to it; the pending profile is freely uploadable.
        self.assertTrue(gate.check(ROSTER_TYPE, SIZES[ROSTER_TYPE]).allowed)
        self.assertTrue(gate.check(PROFILE_TYPE, SIZES[PROFILE_TYPE]).allowed)


class HttpUploadGateTests(unittest.TestCase):
    """End-to-end PUT behavior through the real handler."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="spartacus-http-")
        self.root = Path(self._tmp.name)
        self.content_dir = self.root / "usercontent"
        self.gate = mc.UploadGate()
        self.server = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            soc.make_handler("127.0.0.1", 21000, NullLog(),
                             user_content_dir=self.content_dir,
                             upload_gate=self.gate))
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever,
                         kwargs={"poll_interval": 0.05}, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self._tmp.cleanup()

    def put(self, type_id, body):
        connection = http.client.HTTPConnection("127.0.0.1", self.port,
                                                timeout=10)
        connection.request(
            "PUT", f"/usercontent/{type_id:08x}/1.bin", body=body)
        response = connection.getresponse()
        response.read()
        connection.close()
        return response.status

    def native_path(self, type_id):
        return self.content_dir / f"{type_id:08x}" / "1.bin"

    def test_pending_fallback_upload_is_deferred_and_not_stored(self):
        self.gate.set_state(ROSTER_TYPE, mc.ObjectState.PENDING)
        status = self.put(ROSTER_TYPE, b"\x00" * SIZES[ROSTER_TYPE])
        self.assertEqual(status, 503)
        self.assertFalse(self.native_path(ROSTER_TYPE).exists())
        self.assertEqual(list(self.content_dir.rglob("*.tmp-*")), [])

    def test_restore_then_exact_upload_is_captured_atomically(self):
        self.gate.set_state(ROSTER_TYPE, mc.ObjectState.PENDING)
        self.gate.set_state(ROSTER_TYPE, mc.ObjectState.RESTORED)
        body = (bytes(range(256)) * 84)[:SIZES[ROSTER_TYPE]]
        status = self.put(ROSTER_TYPE, body)
        self.assertEqual(status, 200)
        self.assertEqual(self.native_path(ROSTER_TYPE).read_bytes(), body)
        self.assertIs(self.gate.state(ROSTER_TYPE), mc.ObjectState.CAPTURED)
        self.assertEqual(list(self.content_dir.rglob("*.tmp-*")), [])

    def test_invalid_length_never_replaces_a_valid_native_file(self):
        self.gate.set_state(CAMPAIGN_TYPE, mc.ObjectState.COMPLETE)
        body = b"\x11" * SIZES[CAMPAIGN_TYPE]
        self.assertEqual(self.put(CAMPAIGN_TYPE, body), 200)
        self.assertEqual(
            self.put(CAMPAIGN_TYPE, b"\x00" * (SIZES[CAMPAIGN_TYPE] - 8)), 400)
        self.assertEqual(self.native_path(CAMPAIGN_TYPE).read_bytes(), body)
        self.assertIs(self.gate.state(CAMPAIGN_TYPE), mc.ObjectState.COMPLETE)

    def test_blocked_type_rejects_exact_upload(self):
        self.gate.set_state(CAMPAIGN_TYPE, mc.ObjectState.BLOCKED)
        status = self.put(CAMPAIGN_TYPE, b"\x00" * SIZES[CAMPAIGN_TYPE])
        self.assertEqual(status, 400)
        self.assertFalse(self.native_path(CAMPAIGN_TYPE).exists())

    def test_resumed_upload_after_a_deferral_stores(self):
        self.gate.set_state(ROSTER_TYPE, mc.ObjectState.PENDING)
        body = b"\x22" * SIZES[ROSTER_TYPE]
        self.assertEqual(self.put(ROSTER_TYPE, body), 503)
        # The bridge finished its restore while the client was retrying.
        self.gate.set_state(ROSTER_TYPE, mc.ObjectState.RESTORED)
        self.assertEqual(self.put(ROSTER_TYPE, body), 200)
        self.assertEqual(self.native_path(ROSTER_TYPE).read_bytes(), body)
        self.assertIs(self.gate.state(ROSTER_TYPE), mc.ObjectState.CAPTURED)

    def test_without_a_gate_length_validation_is_unchanged(self):
        server = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            soc.make_handler("127.0.0.1", 21000, NullLog(),
                             user_content_dir=self.content_dir))
        port = server.server_address[1]
        threading.Thread(target=server.serve_forever,
                         kwargs={"poll_interval": 0.05}, daemon=True).start()
        try:
            connection = http.client.HTTPConnection("127.0.0.1", port,
                                                    timeout=10)
            connection.request("PUT", "/usercontent/80000003/1.bin",
                               body=b"\x00" * 17)
            response = connection.getresponse()
            response.read()
            connection.close()
            self.assertEqual(response.status, 200)
            # v0.4.0 behavior: no gate means no exact-size enforcement.
            self.assertEqual(
                (self.content_dir / "80000003" / "1.bin").read_bytes(),
                b"\x00" * 17)
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
