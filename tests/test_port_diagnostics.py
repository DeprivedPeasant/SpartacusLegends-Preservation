"""Port-blocked diagnostics for the OnlineConfig bind failure.

Every OS query is mocked: these tests never run netsh, netstat or tasklist and
never bind a real port.
"""

import sys
import subprocess
import unittest
from pathlib import Path
from unittest import mock

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))

import port_diagnostics


IIS_SERVICESTATE = """\
HTTP Service Configuration
--------------------------
Request queue name: DefaultAppPool
    Process ID: 4567
    Registered URLs:
        http://*:80/
    State: Running
    W3SVC is serving the request queue.
"""


def bind_error(winerror=10013, text="Access is denied."):
    error = OSError(winerror, text)
    error.winerror = winerror
    return error


class DiagnosisBranchTests(unittest.TestCase):
    def diagnose(self, *, listeners=(), udp=(), process="", state="",
                 ranges=(), proto="tcp", winerror=10013):
        with mock.patch.object(
                    port_diagnostics, "tcp_listeners",
                    return_value=list(listeners)), \
                mock.patch.object(
                    port_diagnostics, "udp_listeners",
                    return_value=list(udp)), \
                mock.patch.object(
                    port_diagnostics, "process_name",
                    side_effect=lambda pid: process), \
                mock.patch.object(
                    port_diagnostics, "http_sys_state",
                    return_value=state), \
                mock.patch.object(
                    port_diagnostics, "excluded_ranges",
                    return_value=list(ranges)):
            return port_diagnostics.diagnose(
                80, proto, bind_error(winerror))

    def test_iis_owner_is_named_through_servicestate(self):
        diagnosis = self.diagnose(
            listeners=[("0.0.0.0", 80, 4)],
            process="System",
            state=IIS_SERVICESTATE,
        )
        report = diagnosis.format()
        self.assertIn("http.sys", diagnosis.causes[0].summary)
        self.assertIn("net stop w3svc", report)
        self.assertIn("W3SVC", report)
        # English explanation accompanies the localised OS message.
        self.assertIn("Windows error 10013", report)
        self.assertIn("access denied", report)
        self.assertIn("Port 80 cannot be changed", report)

    def test_user_mode_apache_owner_is_named_with_pid(self):
        diagnosis = self.diagnose(
            listeners=[("0.0.0.0", 80, 1234)],
            process="httpd.exe",
        )
        report = diagnosis.format()
        self.assertIn("httpd.exe (PID 1234)", diagnosis.causes[0].summary)
        self.assertIn("port 80", diagnosis.causes[0].summary)
        self.assertIn("Close that program", report)

    def test_our_own_server_copy_is_recognised(self):
        for name in ("SpartacusLegendsServer.exe", "spartacus_server.py"):
            with self.subTest(name=name):
                diagnosis = self.diagnose(
                    listeners=[("127.0.0.1", 80, 4321)], process=name)
                self.assertIn("Another copy of the preservation server",
                              diagnosis.causes[0].summary)
                self.assertIn("Close the other server window",
                              diagnosis.causes[0].fix)

    def test_excluded_range_alone_is_reported(self):
        diagnosis = self.diagnose(ranges=[(80, 80)])
        self.assertIn("reserved", diagnosis.causes[0].summary)
        self.assertIn("80-80", diagnosis.causes[0].summary)
        self.assertIn("winnat", diagnosis.causes[0].fix)

    def test_combined_iis_and_excluded_range_reports_both(self):
        diagnosis = self.diagnose(
            listeners=[("0.0.0.0", 80, 4)],
            process="System",
            state=IIS_SERVICESTATE,
            ranges=[(80, 80)],
        )
        self.assertEqual(len(diagnosis.causes), 2)
        report = diagnosis.format()
        self.assertIn("http.sys", report)
        self.assertIn("excluded range 80-80", report)
        self.assertIn("Cause 1:", report)
        self.assertIn("Cause 2:", report)

    def test_nothing_found_mentions_antivirus(self):
        diagnosis = self.diagnose()
        self.assertIn("No program or reserved port range",
                      diagnosis.causes[0].summary)
        self.assertIn("Antivirus", diagnosis.causes[0].detail)
        self.assertIn("allow list", diagnosis.causes[0].fix)

    def test_udp_protocol_uses_udp_listener_table(self):
        with mock.patch.object(
                port_diagnostics, "tcp_listeners",
                return_value=[("0.0.0.0", 80, 999)]), \
                mock.patch.object(
                    port_diagnostics, "udp_listeners",
                    return_value=[("0.0.0.0", 80, 777)]), \
                mock.patch.object(
                    port_diagnostics, "process_name",
                    return_value="other.exe"), \
                mock.patch.object(
                    port_diagnostics, "http_sys_state", return_value=""), \
                mock.patch.object(
                    port_diagnostics, "excluded_ranges", return_value=[]):
            diagnosis = port_diagnostics.diagnose(
                80, "udp", bind_error(10048))
        self.assertIn("other.exe (PID 777)", diagnosis.causes[0].summary)
        self.assertIn("UDP port 80", diagnosis.causes[0].summary)
        self.assertIn("address already in use", diagnosis.format())

    def test_localised_error_text_is_preserved_alongside_english(self):
        error = bind_error(10013, "O acesso foi negado.")
        with mock.patch.object(port_diagnostics, "tcp_listeners",
                               return_value=[]), \
                mock.patch.object(port_diagnostics, "http_sys_state",
                                  return_value=""), \
                mock.patch.object(port_diagnostics, "excluded_ranges",
                                  return_value=[]):
            report = port_diagnostics.diagnose(80, "tcp", error).format()
        self.assertIn("O acesso foi negado.", report)
        self.assertIn("access denied", report)

    def test_non_port_error_still_returns_a_usable_report(self):
        with mock.patch.object(port_diagnostics, "tcp_listeners",
                               return_value=[]), \
                mock.patch.object(port_diagnostics, "http_sys_state",
                                  return_value=""), \
                mock.patch.object(port_diagnostics, "excluded_ranges",
                                  return_value=[]):
            diagnosis = port_diagnostics.diagnose(
                21000, "udp", bind_error(10049, "Cannot assign address."))
        self.assertIn("21000", diagnosis.format())
        self.assertIn("No program or reserved port range",
                      diagnosis.causes[0].summary)


class ParsingTests(unittest.TestCase):
    def test_excluded_port_ranges_parse_header_and_rows(self):
        text = (
            "\r\nProtocol tcp Port Exclusion Ranges\r\n\r\n"
            "Start Port    End Port\r\n"
            "----------    --------\r\n"
            "      80          80\r\n"
            "    5357        5357\r\n"
        )
        self.assertEqual(
            port_diagnostics._parse_excluded_ranges(text),
            [(80, 80), (5357, 5357)],
        )

    def test_servicestate_port_detection(self):
        self.assertTrue(port_diagnostics._servicestate_mentions_port(
            IIS_SERVICESTATE, 80))
        self.assertFalse(port_diagnostics._servicestate_mentions_port(
            "nothing registered", 80))


class NetshFailureTests(unittest.TestCase):
    def test_netsh_timeout_never_raises(self):
        with mock.patch.object(
                port_diagnostics.subprocess, "run",
                side_effect=subprocess.TimeoutExpired("netsh", 5)):
            self.assertEqual(port_diagnostics.http_sys_state(), "")
            self.assertEqual(port_diagnostics.excluded_ranges("tcp"), [])
            self.assertEqual(port_diagnostics.excluded_ranges("udp"), [])

    def test_timeout_during_diagnose_still_returns_a_report(self):
        with mock.patch.object(port_diagnostics, "tcp_listeners",
                               return_value=[]), \
                mock.patch.object(
                    port_diagnostics.subprocess, "run",
                    side_effect=subprocess.TimeoutExpired("netsh", 5)):
            diagnosis = port_diagnostics.diagnose(
                80, "tcp", bind_error(10013))
        self.assertIn("Antivirus", diagnosis.causes[0].detail)

    def test_os_error_from_netsh_never_raises(self):
        with mock.patch.object(
                port_diagnostics.subprocess, "run",
                side_effect=OSError("netsh is missing")):
            self.assertEqual(port_diagnostics.http_sys_state(), "")
            self.assertEqual(port_diagnostics.excluded_ranges("tcp"), [])


class ReservePortsIntegrationTests(unittest.TestCase):
    def test_bind_failure_message_keeps_original_text_and_adds_report(self):
        import spartacus_server

        fake_socket = mock.Mock()
        fake_socket.bind.side_effect = bind_error(10013)
        report = port_diagnostics.Diagnosis(
            80, "tcp", 10013, "Access is denied.",
            (port_diagnostics.Cause("something", "detail", "fix"),),
        )
        with mock.patch.object(
                    spartacus_server.socket, "socket",
                    return_value=fake_socket), \
                mock.patch.object(
                    port_diagnostics, "diagnose", return_value=report) as called:
            with self.assertRaises(RuntimeError) as raised:
                spartacus_server.reserve_ports("127.0.0.1", 80, 21000, 21001)
        message = str(raised.exception)
        self.assertTrue(message.startswith(
            "OnlineConfig cannot bind 127.0.0.1:80:"), message)
        self.assertIn("Close the program using that port", message)
        self.assertIn("Cause 1: something", message)
        called.assert_called_once()
        self.assertEqual(called.call_args.args[0], 80)
        fake_socket.close.assert_called()

    def test_diagnostic_failure_never_hides_the_bind_error(self):
        import spartacus_server

        fake_socket = mock.Mock()
        fake_socket.bind.side_effect = bind_error(10048)
        with mock.patch.object(
                    spartacus_server.socket, "socket",
                    return_value=fake_socket), \
                mock.patch.object(
                    port_diagnostics, "diagnose",
                    side_effect=RuntimeError("diagnostic exploded")):
            with self.assertRaises(RuntimeError) as raised:
                spartacus_server.reserve_ports("127.0.0.1", 80, 21000, 21001)
        self.assertTrue(str(raised.exception).startswith(
            "OnlineConfig cannot bind 127.0.0.1:80:"))


if __name__ == "__main__":
    unittest.main()
