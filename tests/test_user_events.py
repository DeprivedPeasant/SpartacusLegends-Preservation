"""User-facing event stream and quiet-console detail logging.

The console user view is a small, fixed vocabulary; the detail log must keep
receiving everything (byte-identical line format) even when the console shows
only the user view.
"""

import http.client
import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))

import user_events
import prudp_server
from UbiOnlineConfigService import spartacus_onlineconfig


def capture_print():
    """Record print() calls (including flush=) without writing to the console."""
    lines = []

    def fake_print(*args, **kwargs):
        lines.append(" ".join(str(arg) for arg in args))

    return lines, mock.patch("builtins.print", new=fake_print)


class UserEventLineTests(unittest.TestCase):
    def setUp(self):
        self._machine = user_events.MACHINE_OUTPUT
        user_events.set_machine_output(False)

    def tearDown(self):
        user_events.set_machine_output(self._machine)

    def test_line_is_timestamped_plain_language(self):
        lines, patch = capture_print()
        with patch:
            user_events.emit("ready", "Server ready - start the game in RPCS3")
        self.assertEqual(len(lines), 1)
        self.assertRegex(
            lines[0],
            r"^\[\d{2}:\d{2}:\d{2}\] "
            r"Server ready - start the game in RPCS3$",
        )

    def test_machine_line_round_trips_through_json(self):
        lines, patch = capture_print()
        user_events.set_machine_output(True)
        with patch:
            user_events.emit(
                "purchase", "Shop purchase: item 60006",
                item_id=60006, gold=1200,
            )
        self.assertEqual(len(lines), 2)
        self.assertTrue(lines[1].startswith(user_events.MACHINE_PREFIX))
        payload = json.loads(
            lines[1][len(user_events.MACHINE_PREFIX):]
        )
        self.assertEqual(payload, {
            "kind": "purchase",
            "message": "Shop purchase: item 60006",
            "item_id": 60006,
            "gold": 1200,
        })

    def test_machine_output_is_off_by_default(self):
        lines, patch = capture_print()
        with patch:
            user_events.emit("connected", "Game connected")
        self.assertEqual(len(lines), 1)
        self.assertFalse(lines[0].startswith(user_events.MACHINE_PREFIX))

    def test_unknown_kind_is_rejected(self):
        with self.assertRaises(ValueError):
            user_events.emit("custom-event", "not part of the vocabulary")

    def test_every_documented_kind_is_accepted(self):
        for kind in sorted(user_events.KINDS):
            with self.subTest(kind=kind):
                lines, patch = capture_print()
                with patch:
                    user_events.emit(kind, f"test {kind}")
                self.assertEqual(len(lines), 1)


class QuietDetailLogTests(unittest.TestCase):
    """--verbose off: file logging unchanged, console detail suppressed."""

    def test_prudp_detail_goes_to_file_but_not_console(self):
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "prudp.log"
            lines, patch = capture_print()
            with mock.patch.object(prudp_server, "LOG_PATH", str(log_path)), \
                    mock.patch.object(prudp_server, "CONSOLE_DETAIL", False), \
                    patch:
                prudp_server.log("detail line")
            self.assertEqual(lines, [])
            text = log_path.read_text(encoding="utf-8")
            self.assertRegex(
                text, r"^\[\d{2}:\d{2}:\d{2}\.\d{6}\] \[prudp\] detail line\n$"
            )

    def test_prudp_verbose_restores_console_output(self):
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "prudp.log"
            lines, patch = capture_print()
            with mock.patch.object(prudp_server, "LOG_PATH", str(log_path)), \
                    mock.patch.object(prudp_server, "CONSOLE_DETAIL", True), \
                    patch:
                prudp_server.log("detail line")
            self.assertEqual(len(lines), 1)
            self.assertIn("[prudp] detail line", lines[0])
            self.assertIn("detail line",
                          log_path.read_text(encoding="utf-8"))

    def test_onlineconfig_detail_goes_to_file_but_not_console(self):
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "online_config.log"
            lines, patch = capture_print()
            with mock.patch.object(
                    spartacus_onlineconfig, "CONSOLE_DETAIL", False), patch:
                spartacus_onlineconfig.ServiceLog(log_path).write("served=1")
            self.assertEqual(lines, [])
            text = log_path.read_text(encoding="utf-8")
            self.assertRegex(
                text, r"^\[\d{2}:\d{2}:\d{2}\.\d{6}\] \[config\] served=1\n$"
            )

    def test_launcher_verbose_flag_defaults_off(self):
        from tools.spartacus_server import parse_args
        self.assertFalse(parse_args([]).verbose)
        self.assertTrue(parse_args(["--verbose"]).verbose)


class NativeSaveEventTests(unittest.TestCase):
    """Exact-size UserContent PUT/GET emit the save events; other bodies do not."""

    def test_exact_size_put_and_get_emit_save_events(self):
        events = []
        payload = b"\x00" * 0x1238
        with tempfile.TemporaryDirectory() as directory:
            log = spartacus_onlineconfig.ServiceLog(Path(directory) / "c.log")
            handler = spartacus_onlineconfig.make_handler(
                "127.0.0.1", 21000, log, Path(directory) / "usercontent")
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with mock.patch.object(
                        spartacus_onlineconfig.user_events, "emit",
                        side_effect=lambda kind, message, **fields:
                        events.append((kind, message))), \
                        mock.patch.dict(
                            os.environ, {"SPARTACUS_TITLE_VERSION": "01.00"}):
                    for method, body in (("PUT", payload),
                                         ("GET", b"")):
                        connection = http.client.HTTPConnection(
                            "127.0.0.1", server.server_port, timeout=2)
                        connection.request(
                            method, "/usercontent/80000001/1.bin", body)
                        response = connection.getresponse()
                        self.assertEqual(response.status, 200)
                        response.read()
                        connection.close()
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)
        self.assertEqual(events, [
            ("save_uploaded", "Progress saved (profile)"),
            ("save_restored", "Save restored (profile)"),
        ])

    def test_wrong_sized_body_emits_no_save_event(self):
        events = []
        with tempfile.TemporaryDirectory() as directory:
            log = spartacus_onlineconfig.ServiceLog(Path(directory) / "c.log")
            handler = spartacus_onlineconfig.make_handler(
                "127.0.0.1", 21000, log, Path(directory) / "usercontent")
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with mock.patch.object(
                        spartacus_onlineconfig.user_events, "emit",
                        side_effect=lambda *args, **kwargs:
                        events.append(args)), \
                        mock.patch.dict(
                            os.environ, {"SPARTACUS_TITLE_VERSION": "01.00"}):
                    connection = http.client.HTTPConnection(
                        "127.0.0.1", server.server_port, timeout=2)
                    connection.request(
                        "PUT", "/usercontent/80000001/1.bin", b"too short")
                    response = connection.getresponse()
                    self.assertEqual(response.status, 200)
                    response.read()
                    connection.close()
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)
        self.assertEqual(events, [])


if __name__ == "__main__":
    unittest.main()
