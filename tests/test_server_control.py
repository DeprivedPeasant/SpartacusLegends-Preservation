"""Control channel and live economy editing.

The command parser is exercised directly against a temporary EconomyStore; one
subprocess test starts the real launcher on free high ports with its data
directory redirected into a temp folder.
"""

import json
import os
import queue
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

TOOLS = Path(__file__).resolve().parents[1] / "tools"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

import prudp_server as p
import server_control


def command(store, payload):
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return server_control.handle_line(store, text)


class ControlStoreTestCase(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.path = Path(self._temp.name) / "profile.json"
        self.store = p.EconomyStore(self.path)
        # The live-economy methods log to the detail log; keep those lines out
        # of the real notes/prudp_server_log.txt and off the test console.
        log_patch = mock.patch.object(
            p, "LOG_PATH", str(Path(self._temp.name) / "prudp.log"))
        log_patch.start()
        self.addCleanup(log_patch.stop)
        console_patch = mock.patch.object(p, "CONSOLE_DETAIL", False)
        console_patch.start()
        self.addCleanup(console_patch.stop)

    def reloaded(self):
        return p.EconomyStore(self.path)


class CommandParsingTests(ControlStoreTestCase):
    def test_get_economy_returns_default_balances(self):
        reply = command(self.store, {"id": 1, "cmd": "get_economy"})
        self.assertEqual(reply["id"], 1)
        self.assertTrue(reply["ok"])
        self.assertEqual((reply["gold"], reply["silver"], reply["fame"]),
                         (0, 200, 0))
        self.assertEqual(reply["owned_items"], [])

    def test_id_is_echoed_only_when_provided(self):
        self.assertNotIn("id", command(self.store, {"cmd": "get_economy"}))
        self.assertEqual(command(self.store, {"id": "abc",
                                              "cmd": "get_economy"})["id"],
                         "abc")

    def test_set_balances_updates_both_values_and_persists(self):
        reply = command(self.store, {"cmd": "set_balances",
                                     "gold": 1234, "silver": 5678})
        self.assertTrue(reply["ok"])
        self.assertEqual((reply["gold"], reply["silver"]), (1234, 5678))
        reloaded = self.reloaded()
        self.assertEqual((reloaded.data["gold"], reloaded.data["silver"]),
                         (1234, 5678))

    def test_set_balances_keeps_the_unchanged_currency(self):
        command(self.store, {"cmd": "set_balances", "gold": 10})
        self.assertEqual(self.reloaded().data["silver"], 200)
        command(self.store, {"cmd": "set_balances", "silver": 20})
        self.assertEqual(self.reloaded().data["gold"], 10)

    def test_set_balances_clamps_to_u32(self):
        reply = command(self.store, {"cmd": "set_balances",
                                     "gold": -5, "silver": 2 ** 32 + 7})
        self.assertEqual((reply["gold"], reply["silver"]), (0, 0xFFFFFFFF))
        self.assertEqual(self.reloaded().data["silver"], 0xFFFFFFFF)

    def test_set_balances_rejects_non_integers(self):
        for payload in ({"cmd": "set_balances", "gold": True},
                        {"cmd": "set_balances", "silver": "12"},
                        {"cmd": "set_balances", "gold": 1.5},
                        {"cmd": "set_balances"}):
            with self.subTest(payload=payload):
                reply = command(self.store, payload)
                self.assertFalse(reply["ok"])
                self.assertIn("error", reply)

    def test_add_item_stores_ownership_and_quantity(self):
        reply = command(self.store, {"cmd": "add_item",
                                     "item_id": 60006, "quantity": 5})
        self.assertTrue(reply["ok"])
        self.assertEqual((reply["item_id"], reply["quantity"]), (60006, 5))
        state = command(self.store, {"cmd": "get_economy"})
        self.assertEqual(state["owned_items"], [60006])
        self.assertEqual(state["item_quantities"], {"60006": 5})
        self.assertEqual(self.reloaded().item_quantity(60006), 5)

    def test_add_item_defaults_to_quantity_one(self):
        command(self.store, {"cmd": "add_item", "item_id": 10250})
        self.assertEqual(self.reloaded().item_quantity(10250), 1)

    def test_add_item_rejects_refresh_sentinel_and_bad_quantities(self):
        for payload in (
            {"cmd": "add_item", "item_id": p.STORE_REFRESH_SENTINEL},
            {"cmd": "add_item", "item_id": 60001, "quantity": 100},
            {"cmd": "add_item", "item_id": 60001, "quantity": -1},
            {"cmd": "add_item", "item_id": 60001, "quantity": "3"},
            {"cmd": "add_item"},
        ):
            with self.subTest(payload=payload):
                reply = command(self.store, payload)
                self.assertFalse(reply["ok"])
        self.assertEqual(self.reloaded().data["owned_items"], [])

    def test_set_item_quantity_requires_ownership(self):
        unowned = command(self.store, {"cmd": "set_item_quantity",
                                       "item_id": 60001, "quantity": 3})
        self.assertFalse(unowned["ok"])
        self.assertIn("not owned", unowned["error"])

        command(self.store, {"cmd": "add_item", "item_id": 60001})
        reply = command(self.store, {"cmd": "set_item_quantity",
                                     "item_id": 60001, "quantity": 7})
        self.assertTrue(reply["ok"])
        self.assertEqual(reply["quantity"], 7)
        self.assertEqual(self.reloaded().item_quantity(60001), 7)

    def test_set_item_quantity_range_and_sentinel(self):
        command(self.store, {"cmd": "add_item", "item_id": 60001})
        for quantity in (100, -1):
            with self.subTest(quantity=quantity):
                reply = command(self.store, {"cmd": "set_item_quantity",
                                             "item_id": 60001,
                                             "quantity": quantity})
                self.assertFalse(reply["ok"])
        sentinel = command(self.store, {"cmd": "set_item_quantity",
                                        "item_id": p.STORE_REFRESH_SENTINEL,
                                        "quantity": 1})
        self.assertFalse(sentinel["ok"])

    def test_remove_item_removes_ownership_and_quantity(self):
        command(self.store, {"cmd": "add_item", "item_id": 60001,
                             "quantity": 4})
        reply = command(self.store, {"cmd": "remove_item", "item_id": 60001})
        self.assertTrue(reply["ok"])
        reloaded = self.reloaded()
        self.assertEqual(reloaded.data["owned_items"], [])
        self.assertNotIn(60001, reloaded.data["item_quantities"])

    def test_remove_item_refuses_ludus_slot_entitlements(self):
        command(self.store, {"cmd": "add_item", "item_id": 80002})
        for slot in (p.SLOT_ENTITLEMENT_MIN, p.SLOT_ENTITLEMENT_MAX):
            with self.subTest(slot=slot):
                if slot != p.SLOT_ENTITLEMENT_MIN:
                    command(self.store, {"cmd": "add_item", "item_id": slot})
                reply = command(self.store, {"cmd": "remove_item",
                                             "item_id": slot})
                self.assertFalse(reply["ok"])
                self.assertIn("Ludus slot", reply["error"])

    def test_remove_item_rejects_unowned_item(self):
        reply = command(self.store, {"cmd": "remove_item", "item_id": 10250})
        self.assertFalse(reply["ok"])
        self.assertIn("not owned", reply["error"])

    def test_set_fame_is_refused_with_an_offline_explanation(self):
        reply = command(self.store, {"cmd": "set_fame", "fame": 10})
        self.assertFalse(reply["ok"])
        self.assertIn("offline", reply["error"])
        self.assertIn("Stop the server", reply["error"])
        self.assertEqual(self.reloaded().data["fame"], 0)

    def test_fame_in_set_balances_is_refused_on_01_00(self):
        reply = command(self.store, {"cmd": "set_balances", "gold": 5,
                                     "fame": 10})
        self.assertFalse(reply["ok"])
        self.assertIn("01.00", reply["error"])
        # Nothing at all is applied when part of the request is refused.
        self.assertEqual(self.reloaded().data["fame"], 0)
        self.assertNotEqual(self.reloaded().data["gold"], 5)

    def test_live_fame_is_allowed_on_01_06(self):
        # 01.06 Shop m19 (login) and m20 (after fights) push all three
        # absolute balances, so the server can change fame mid-session.
        reply = server_control.handle_line(
            self.store, json.dumps({"cmd": "set_fame", "fame": 4321}),
            "01.06")
        self.assertTrue(reply["ok"], reply)
        self.assertEqual(reply["fame"], 4321)
        self.assertEqual(self.reloaded().data["fame"], 4321)
        reply = server_control.handle_line(
            self.store, json.dumps({"cmd": "set_balances", "gold": 9,
                                    "silver": 8, "fame": 7}), "01.06")
        self.assertEqual((reply["gold"], reply["silver"], reply["fame"]),
                         (9, 8, 7))
        self.assertEqual(self.reloaded().data["fame"], 7)

    def test_next_01_06_method_19_reply_carries_the_edited_fame(self):
        server_control.handle_line(
            self.store, json.dumps({"cmd": "set_balances", "gold": 11,
                                    "silver": 22, "fame": 33}), "01.06")
        with self.store.lock:
            body = p.encode_reward_balances(
                self.store.data["gold"], self.store.data["silver"],
                self.store.data["fame"])
        self.assertEqual(body, p.encode_reward_balances(11, 22, 33))

    def test_save_retries_a_briefly_locked_profile(self):
        real_replace = p.os.replace
        calls = []

        def flaky_replace(source, target):
            calls.append(target)
            if len(calls) < 3:
                raise PermissionError(13, "Access is denied")
            return real_replace(source, target)

        with mock.patch.object(p.os, "replace", side_effect=flaky_replace), \
                mock.patch.object(p.time, "sleep"):
            self.store.set_balances(gold=77)
        self.assertEqual(len(calls), 3)
        self.assertEqual(self.reloaded().data["gold"], 77)

        with mock.patch.object(p.os, "replace",
                               side_effect=PermissionError(13, "denied")), \
                mock.patch.object(p.time, "sleep"):
            with self.assertRaises(PermissionError):
                self.store.set_balances(gold=1)

    def test_native_enumeration_confirms_the_patch_once_per_session(self):
        with mock.patch.object(p.user_events, "emit") as emit, \
                mock.patch.object(p, "_CLIENT_SESSION_COUNT", 0):
            p._note_client_session(True)
            # The remote-config object is fetched before the patch matters.
            self.assertFalse(p.note_native_save_enumeration(0x80000004))
            self.assertTrue(p.note_native_save_enumeration(0x80000001))
            self.assertFalse(p.note_native_save_enumeration(0x80000003))
            kinds = [call.args[0] for call in emit.call_args_list]
            self.assertEqual(kinds.count("patch_confirmed"), 1)
            # A new game session needs its own confirmation.
            p._note_client_session(False)
            p._note_client_session(True)
            self.assertTrue(p.note_native_save_enumeration(0x80000002))
            p._note_client_session(False)

    def test_unknown_and_malformed_commands_are_json_errors(self):
        for payload in (
            {"cmd": "explode"},
            {"cmd": None},
            {"not_a_command": True},
            "not json at all",
            "[1, 2, 3]",
        ):
            with self.subTest(payload=payload):
                reply = command(self.store, payload)
                self.assertFalse(reply["ok"])
                self.assertIn("error", reply)


class ChannelLoopTests(ControlStoreTestCase):
    def test_stop_sets_the_event_and_replies_are_prefixed_json(self):
        stop = threading.Event()
        replies = []
        server_control.serve_control_channel(
            stop, self.store,
            iter(['{"id": 2, "cmd": "get_economy"}\n', "stop\n", "\n"]),
            replies.append,
        )
        self.assertTrue(stop.is_set())
        self.assertEqual(len(replies), 1)
        self.assertTrue(replies[0].startswith(server_control.REPLY_PREFIX))
        payload = json.loads(replies[0][len(server_control.REPLY_PREFIX):])
        self.assertEqual(payload["id"], 2)
        self.assertTrue(payload["ok"])

    def test_end_of_input_does_not_stop_the_server(self):
        stop = threading.Event()
        server_control.serve_control_channel(
            stop, self.store, iter([]), lambda line: None)
        self.assertFalse(stop.is_set())


class LockSafetyTests(ControlStoreTestCase):
    def test_concurrent_add_item_commands_never_lose_ownership(self):
        failures = []

        def worker(item_id):
            for _ in range(30):
                reply = command(self.store, {"cmd": "add_item",
                                             "item_id": item_id})
                if not reply.get("ok"):
                    failures.append(reply)

        threads = [threading.Thread(target=worker, args=(10000 + index,))
                   for index in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
        self.assertEqual(failures, [])
        expected = {10000, 10001, 10002, 10003}
        self.assertEqual(set(self.reloaded().data["owned_items"]), expected)

    def test_balance_writes_and_reads_share_the_lock(self):
        errors = []
        stop = threading.Event()

        def writer():
            for gold in range(100):
                self.store.set_balances(gold=gold)

        def reader():
            while not stop.is_set():
                state = server_control._economy_state(self.store)
                if not 0 <= state["gold"] <= 99:
                    errors.append(state)

        read_thread = threading.Thread(target=reader)
        read_thread.start()
        writer_thread = threading.Thread(target=writer)
        writer_thread.start()
        writer_thread.join(timeout=10)
        stop.set()
        read_thread.join(timeout=10)
        self.assertEqual(errors, [])
        self.assertEqual(self.reloaded().data["gold"], 99)


class LiveBalanceEncodingTests(ControlStoreTestCase):
    def test_next_m6_and_m7_responses_encode_the_edited_absolute_values(self):
        self.store.set_balances(gold=1234, silver=5678)
        with self.store.lock:
            gold = self.store.data["gold"]
            silver = self.store.data["silver"]
        # m6/m11/m13-balances use the same two-u32 pair helper.
        self.assertEqual(p.encode_balance_pair(gold, silver),
                         struct.pack("<II", 1234, 5678))
        # m7 sends the pair followed by the 16-byte purchase receipt.
        receipt = p.encode_purchase_result(
            gold, silver, 60006,
            transaction_time=p.encode_qdatetime(), quantity=1,
        )
        self.assertEqual(receipt[:8], struct.pack("<II", 1234, 5678))
        self.assertEqual(len(receipt), 24)

    def test_balance_synced_event_carries_the_values_sent(self):
        emitted = []
        with mock.patch.object(
                p.user_events, "emit",
                side_effect=lambda kind, message, **fields:
                emitted.append((kind, message, fields))):
            p.emit_balance_synced(1234, 5678)
            p.emit_balance_synced(42)
        self.assertEqual(emitted, [
            ("balance_synced", "Balance synced: 1234 gold, 5678 silver",
             {"gold": 1234, "silver": 5678}),
            ("balance_synced", "Balance synced: 42 gold", {"gold": 42}),
        ])


class LauncherControlChannelTests(unittest.TestCase):
    """Start the real launcher; every path is redirected into a temp folder."""

    def free_port(self, kind):
        with socket.socket(socket.AF_INET, kind) as sock:
            sock.bind(("127.0.0.1", 0))
            return sock.getsockname()[1]

    def test_control_stdin_stop_shuts_the_server_down_cleanly(self):
        http_port = self.free_port(socket.SOCK_STREAM)
        auth_port = self.free_port(socket.SOCK_DGRAM)
        secure_port = self.free_port(socket.SOCK_DGRAM)
        with tempfile.TemporaryDirectory() as directory:
            env = dict(os.environ)
            env["SPARTACUS_BASE_DIR"] = directory
            for key in ("SPARTACUS_PROFILE", "SPARTACUS_PRUDP_LOG",
                        "SPARTACUS_CONFIG_LOG", "SPARTACUS_USER_CONTENT_DIR",
                        "SPARTACUS_TITLE_VERSION", "SPARTACUS_ROSTER_PROFILE",
                        "SPARTACUS_CAMPAIGN_PROFILE", "SPARTACUS_ROSTER_LOG",
                        "SPARTACUS_CONSOLE_DETAIL",
                        "SPARTACUS_MACHINE_OUTPUT"):
                env.pop(key, None)
            process = subprocess.Popen(
                [sys.executable, str(TOOLS / "spartacus_server.py"),
                 "--no-wait", "--control-stdin", "--run-seconds", "20",
                 "--host", "127.0.0.1", "--advertise-host", "127.0.0.1",
                 "--http-port", str(http_port),
                 "--auth-port", str(auth_port),
                 "--secure-port", str(secure_port),
                 "--title-version", "01.00"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                env=env,
                cwd=str(ROOT),
            )
            lines: queue.Queue = queue.Queue()

            def read_output():
                for line in process.stdout:
                    lines.put(line)

            reader = threading.Thread(target=read_output, daemon=True)
            reader.start()
            output = []
            try:
                self._wait_for(process, lines, output, '"kind":"ready"')
                self.assertIn("@@EVENT ", output[-1])

                process.stdin.write('{"id": 7, "cmd": "get_economy"}\n')
                process.stdin.flush()
                reply = self._wait_for(process, lines, output, '"id":7')
                payload = json.loads(
                    reply[len(server_control.REPLY_PREFIX):])
                self.assertTrue(payload["ok"])
                self.assertEqual((payload["gold"], payload["silver"]),
                                 (0, 200))

                process.stdin.write("stop\n")
                process.stdin.flush()
                return_code = process.wait(timeout=20)
            finally:
                if process.poll() is None:
                    process.kill()
                try:
                    process.stdin.close()
                except OSError:
                    pass
                process.stdout.close()
                reader.join(timeout=2)
            while not lines.empty():
                output.append(lines.get_nowait())
            self.assertEqual(return_code, 0, "".join(output))
            self.assertIn("Server stopped cleanly.", "".join(output))
            # The launcher's data/log directories were redirected by the
            # SPARTACUS_BASE_DIR override, so nothing touched the repo.
            self.assertTrue((Path(directory) / "logs").is_dir())
            self.assertTrue(
                (Path(directory) / "logs" / "prudp.log").is_file())

    def _wait_for(self, process, lines, output, needle, timeout=20.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            remaining = max(0.05, deadline - time.monotonic())
            try:
                line = lines.get(timeout=remaining)
            except queue.Empty:
                if process.poll() is not None:
                    break
                continue
            output.append(line)
            if needle in line:
                return line
        raise AssertionError(
            f"timed out waiting for {needle!r}; output so far:\n"
            + "".join(output)
        )


if __name__ == "__main__":
    unittest.main()
