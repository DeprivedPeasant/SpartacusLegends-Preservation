#!/usr/bin/env python3
"""Diagnose why a TCP/UDP port cannot be bound on Windows.

Only the standard library is used: the console server must keep working on a
bare Python install.  Every OS query is a small function so the tests can mock
it, and nothing here raises out of :func:`diagnose` - a diagnostic failing must
never replace the original bind error.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import os
from dataclasses import dataclass
from pathlib import Path
import socket
import struct
import subprocess

NETSH_TIMEOUT = 5.0

# WinError 10013 is WSAEACCES, which is what an occupied port looks like when
# bound with SO_EXCLUSIVEADDRUSE; 10048 is the ordinary "address in use".
BLOCKED_WINERRORS = {10013: "access denied (the port is in use or reserved)",
                     10048: "address already in use"}
ERROR_EXPLANATIONS = dict(BLOCKED_WINERRORS)

# Executables this project ships or runs from source. A leftover copy is the
# most common cause after a crash or a second double-click on the exe.
OWN_SERVER_NAMES = {
    "spartacuslegendsserver.exe",
    "spartacuslegendsservergui.exe",
    "spartacus_server.py",
}
PYTHON_NAMES = {"python.exe", "pythonw.exe"}

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


@dataclass(frozen=True)
class Cause:
    summary: str
    detail: str
    fix: str


@dataclass(frozen=True)
class Diagnosis:
    port: int
    proto: str
    winerror: int | None
    error_text: str
    causes: tuple[Cause, ...]

    def format(self) -> str:
        lines = [f"Port {self.port} ({self.proto.upper()}) could not be opened."]
        if self.winerror is not None:
            explanation = ERROR_EXPLANATIONS.get(
                self.winerror,
                "this Windows socket error is not port-specific",
            )
            lines.append(
                f"Windows error {self.winerror}: {explanation}."
            )
        if self.error_text:
            # Usually localised; the English line above carries the meaning.
            lines.append(f"Windows reported: {self.error_text}")
        for index, cause in enumerate(self.causes, 1):
            lines.append(f"Cause {index}: {cause.summary}")
            if cause.detail:
                lines.append(f"  {cause.detail}")
            if cause.fix:
                lines.append(f"  Fix: {cause.fix}")
        if self.port == 80:
            lines.append(
                "Port 80 cannot be changed: the game reaches "
                "onlineconfigservice.ubi.com on port 80 through RPCS3's IP "
                "swap, so the server has to answer there. Free port 80 or "
                "stop whatever is holding it."
            )
        return "\n".join(lines)


# ------------------------------------------------------------------ OS queries

def _run_netsh(arguments: list[str]) -> str:
    """Run netsh and return its text output; '' on any failure or timeout."""
    if os.name != "nt":
        return ""
    try:
        completed = subprocess.run(
            ["netsh", *arguments],
            capture_output=True,
            timeout=NETSH_TIMEOUT,
            check=False,
            creationflags=CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    data = (completed.stdout or b"") + (completed.stderr or b"")
    for encoding in ("oem", "mbcs", "utf-8"):
        try:
            return data.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", "replace")


def http_sys_state() -> str:
    """Return ``netsh http show servicestate`` output, or '' if unavailable."""
    return _run_netsh(["http", "show", "servicestate"])


def excluded_ranges(proto: str) -> list[tuple[int, int]]:
    """Return Windows' excluded port ranges for ``proto`` ('tcp' or 'udp')."""
    if proto.lower() not in ("tcp", "udp"):
        raise ValueError(f"unsupported protocol {proto!r}")
    text = _run_netsh([
        "int", "ipv4", "show", "excludedportrange",
        f"protocol={proto.lower()}",
    ])
    return _parse_excluded_ranges(text)


def _parse_excluded_ranges(text: str) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 2 or not parts[0].isdigit() or not parts[1].isdigit():
            continue
        start, end = int(parts[0]), int(parts[1])
        if 0 <= start <= end <= 0xFFFF:
            ranges.append((start, end))
    return ranges


def _listener_rows(proto: str) -> list[tuple[str, int, int]]:
    """(address, port, pid) rows from the ctypes table, else netstat."""
    try:
        if proto == "tcp":
            return _tcp_rows_ctypes()
        return _udp_rows_ctypes()
    except (AttributeError, OSError, ValueError, struct.error):
        return _netstat_rows(proto)


def tcp_listeners() -> list[tuple[str, int, int]]:
    return _listener_rows("tcp")


def udp_listeners() -> list[tuple[str, int, int]]:
    return _listener_rows("udp")


def _netstat_rows(proto: str) -> list[tuple[str, int, int]]:
    if os.name != "nt":
        return []
    try:
        completed = subprocess.run(
            ["netstat", "-ano", "-p", proto],
            capture_output=True,
            timeout=NETSH_TIMEOUT,
            check=False,
            creationflags=CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    rows: list[tuple[str, int, int]] = []
    for line in completed.stdout.decode("mbcs", "replace").splitlines():
        parts = line.split()
        if len(parts) < 4 or parts[0].lower() != proto:
            continue
        local, pid_text = parts[1], parts[-1]
        address, separator, port_text = local.rpartition(":")
        if not separator or not pid_text.isdigit() or not port_text.isdigit():
            continue
        rows.append((address.strip("[]"), int(port_text), int(pid_text)))
    return rows


def _tcp_rows_ctypes() -> list[tuple[str, int, int]]:
    if os.name != "nt":
        return []
    AF_INET, TABLE_CLASS = 2, 3  # TCP_TABLE_OWNER_PID_LISTENER
    buffer = ctypes.create_string_buffer(4)
    size = ctypes.wintypes.DWORD(len(buffer))
    get_table = ctypes.windll.iphlpapi.GetExtendedTcpTable
    result = get_table(buffer, ctypes.byref(size), False, AF_INET,
                       TABLE_CLASS, 0)
    if result not in (0, 122):  # 122 = ERROR_INSUFFICIENT_BUFFER
        raise OSError(result, "GetExtendedTcpTable failed")
    if size.value > len(buffer):
        buffer = ctypes.create_string_buffer(size.value)
        result = get_table(buffer, ctypes.byref(size), False, AF_INET,
                           TABLE_CLASS, 0)
        if result != 0:
            raise OSError(result, "GetExtendedTcpTable failed")
    data = buffer.raw[:size.value]
    count = struct.unpack_from("<I", data, 0)[0]
    rows = []
    # MIB_TCPROW_OWNER_PID: state, local addr, local port, remote addr,
    # remote port, owning pid (6 x u32). The ports are network byte order.
    for index in range(count):
        offset = 4 + index * 24
        _state, local_addr, local_port = struct.unpack_from(
            "<III", data, offset)
        pid = struct.unpack_from("<I", data, offset + 20)[0]
        rows.append((_address(local_addr),
                     socket.ntohs(local_port & 0xFFFF), pid))
    return rows


def _udp_rows_ctypes() -> list[tuple[str, int, int]]:
    if os.name != "nt":
        return []
    AF_INET, TABLE_CLASS = 2, 1  # UDP_TABLE_OWNER_PID
    buffer = ctypes.create_string_buffer(4)
    size = ctypes.wintypes.DWORD(len(buffer))
    get_table = ctypes.windll.iphlpapi.GetExtendedUdpTable
    result = get_table(buffer, ctypes.byref(size), False, AF_INET,
                       TABLE_CLASS, 0)
    if result not in (0, 122):
        raise OSError(result, "GetExtendedUdpTable failed")
    if size.value > len(buffer):
        buffer = ctypes.create_string_buffer(size.value)
        result = get_table(buffer, ctypes.byref(size), False, AF_INET,
                           TABLE_CLASS, 0)
        if result != 0:
            raise OSError(result, "GetExtendedUdpTable failed")
    data = buffer.raw[:size.value]
    count = struct.unpack_from("<I", data, 0)[0]
    rows = []
    # MIB_UDPROW_OWNER_PID: local addr, local port, owning pid (3 x u32).
    for index in range(count):
        offset = 4 + index * 12
        local_addr, local_port, pid = struct.unpack_from(
            "<III", data, offset)
        rows.append((_address(local_addr),
                     socket.ntohs(local_port & 0xFFFF), pid))
    return rows


def _address(value: int) -> str:
    return socket.inet_ntoa(struct.pack("<I", value))


def process_name(pid: int) -> str | None:
    """Best-effort image name for a PID; None when Windows will not say."""
    if os.name != "nt":
        return None
    try:
        return _process_name_ctypes(pid)
    except (AttributeError, OSError):
        pass
    return _process_name_tasklist(pid)


def _process_name_ctypes(pid: int) -> str | None:
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    handle = ctypes.windll.kernel32.OpenProcess(
        PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not handle:
        raise OSError(ctypes.GetLastError(), "OpenProcess failed")
    try:
        capacity = ctypes.wintypes.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(capacity.value)
        if not ctypes.windll.kernel32.QueryFullProcessImageNameW(
                handle, 0, buffer, ctypes.byref(capacity)):
            raise OSError(ctypes.GetLastError(), "QueryFullProcessImageNameW")
        return Path(buffer.value).name or None
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


def _process_name_tasklist(pid: int) -> str | None:
    try:
        completed = subprocess.run(
            ["tasklist", "/FI", f"PID eq {int(pid)}", "/FO", "CSV", "/NH"],
            capture_output=True,
            timeout=NETSH_TIMEOUT,
            check=False,
            creationflags=CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    for line in completed.stdout.decode("mbcs", "replace").splitlines():
        if not line.startswith('"'):
            continue
        name = line.split('"')[1]
        if name:
            return name
    return None


# ---------------------------------------------------------------- diagnosis

def diagnose(port: int, proto: str, error: OSError) -> Diagnosis:
    """Collect every likely cause for a failed bind. Never raises."""
    proto = proto.lower()
    winerror = getattr(error, "winerror", None)
    causes: list[Cause] = []
    try:
        listeners = tcp_listeners() if proto == "tcp" else udp_listeners()
    except Exception:  # A diagnostic must never replace the bind error.
        listeners = []
    listeners = [row for row in listeners if row[1] == int(port)]

    by_pid: dict[int, list[str]] = {}
    for address, _row_port, pid in listeners:
        by_pid.setdefault(pid, []).append(address)
    for pid in sorted(by_pid):
        name = None
        try:
            name = process_name(pid)
        except Exception:
            name = None
        causes.append(_owner_cause(pid, name, proto, int(port), by_pid[pid]))

    # http.sys can hold a registered URL without a visible TCP listener row.
    if not causes and winerror == 10013:
        try:
            state = http_sys_state()
        except Exception:
            state = ""
        if state and _servicestate_mentions_port(state, int(port)):
            causes.append(_http_sys_cause(state))

    try:
        ranges = excluded_ranges(proto)
    except Exception:
        ranges = []
    for start, end in ranges:
        if start <= int(port) <= end:
            causes.append(Cause(
                f"Windows has reserved {proto.upper()} port {port} "
                f"(excluded range {start}-{end}).",
                "Hyper-V, WSL, Docker or another virtual network component "
                "reserves a block of ports that user programs then cannot "
                "bind, even when no process is listening.",
                "From an administrator prompt run: net stop winnat, then "
                "net start winnat. If the range is a persistent Hyper-V or "
                "WSL reservation, also run: netsh int ipv4 set dynamicport "
                f"{proto} start=<a free range start> num=<size>.",
            ))
            break

    if not causes:
        causes.append(Cause(
            f"No program or reserved port range was found holding "
            f"{proto.upper()} port {port}.",
            "Antivirus/web-shield, a firewall driver, or another network "
            "filter can still prevent a program from listening even though "
            "Windows' own tables look clear.",
            "Temporarily disable the security software's web shield or "
            "firewall and try again; if it works, add "
            "SpartacusLegendsServer.exe to its allow list.",
        ))

    return Diagnosis(int(port), proto, winerror, str(error), tuple(causes))


def _owner_cause(pid: int, name: str | None, proto: str, port: int,
                 addresses: list[str]) -> Cause:
    base = (name or "").lower()
    where = ", ".join(sorted(set(addresses))) or "the port"
    if pid == 4 or base == "system":
        state = ""
        try:
            state = http_sys_state()
        except Exception:
            state = ""
        return _http_sys_cause(state, addresses=addresses)
    if base in OWN_SERVER_NAMES:
        return Cause(
            f"Another copy of the preservation server is already running "
            f"(PID {pid}).",
            f"{name} owns {proto.upper()} {where}:{port}.",
            "Close the other server window (or stop it from the GUI), then "
            "start the server again. Only one copy can bind port 80.",
        )
    if base in PYTHON_NAMES:
        return Cause(
            f"A Python process is using {proto.upper()} port {port} "
            f"(PID {pid}).",
            f"{name} owns {where}:{port}.",
            "If you started tools\\spartacus_server.py from a terminal, close "
            "that window. Otherwise close the other Python program.",
        )
    label = name or "an unidentified process"
    return Cause(
        f"{label} (PID {pid}) is using {proto.upper()} port {port}.",
        f"It is listening on {where}:{port}.",
        "Close that program (or stop its Windows service), then start the "
        "server again.",
    )


def _servicestate_mentions_port(state: str, port: int) -> bool:
    return f":{port}" in state or f"*:{port}/" in state or f"*:{port} " in state


def _http_sys_cause(state: str, addresses: list[str] | None = None) -> Cause:
    where = ", ".join(sorted(set(addresses))) if addresses else "0.0.0.0"
    detail = ("Windows reports the socket owner as PID 4 (System): the kernel "
              "HTTP driver http.sys holds it on behalf of a registered "
              f"service ({where}).")
    lowered = state.lower()
    fix = ("From an administrator prompt run: netsh http show servicestate, "
           "find the request queue listening on port 80, then stop that "
           "service.")
    if "w3svc" in lowered or "was" in lowered or "defaultapppool" in lowered:
        fix = ("This is IIS. From an administrator prompt run: net stop w3svc "
               "(and net stop was /y if IIS is still listening). Alternatively "
               "remove or rebind the IIS site that uses port 80 in IIS Manager.")
    elif "reportserver" in lowered or "ssrs" in lowered:
        fix = ("SQL Server Reporting Services is holding port 80. Stop the "
               "service from an administrator prompt (for example: net stop "
               "ReportServer) or move its URL reservation.")
    elif "branchcache" in lowered:
        fix = ("BranchCache is holding port 80. From an administrator prompt "
               "run: net stop branchcache, or disable BranchCache in Windows "
               "Features.")
    elif "web deployment agent" in lowered or "msdepsvc" in lowered:
        fix = ("The Web Deployment Agent Service is holding port 80. From an "
               "administrator prompt run: net stop msdepsvc.")
    snippet = " ".join(
        line.strip() for line in state.splitlines() if line.strip()
    )[:400]
    if snippet:
        detail += f" netsh http show servicestate reported: {snippet}"
    return Cause(
        "The Windows HTTP service (http.sys, PID 4) is holding port 80.",
        detail,
        fix,
    )
