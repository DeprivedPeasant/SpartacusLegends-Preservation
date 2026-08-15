#!/usr/bin/env python3
"""All-in-one local server launcher for Spartacus Legends (PS3)."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import queue
import socket
import sys
import threading
import time
import traceback

from _version import __version__ as VERSION


DEFAULT_HTTP_PORT = 80
DEFAULT_AUTH_PORT = 21000
DEFAULT_SECURE_PORT = 21001
DEFAULT_PINE_PORT = 28012


def application_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def running_from_temp(base_dir: Path) -> bool:
    """Detect the exe being run from inside the ZIP (Windows unpacks to %TEMP%)."""
    for variable in ("TEMP", "TMP"):
        value = os.environ.get(variable)
        if not value:
            continue
        try:
            temp_dir = Path(value).resolve()
        except OSError:
            continue
        if base_dir == temp_dir or temp_dir in base_dir.parents:
            return True
    return False


def configure_environment(log_dir: Path, secure_port: int,
                          advertise_host: str = "127.0.0.1") -> None:
    """Set the exact response matrix validated by the preservation tests.

    advertise_host reaches the Quazal server through RDV_HOST, which it reads at
    import time to build the connection string that redirects the client from
    the auth server to the secure one. It has to agree with the address the
    online-config response hands out, or the client is sent somewhere it cannot
    reach and login stalls until it times out.
    """
    defaults = {
        "RDV_HOST": advertise_host,
        "RDV_ADVERTISE_PORT": str(secure_port),
        "RDV_SCHEME": "prudps",
        "GENERIC_ACK": "1",
        "GENERIC_BODY": "empty",
        "P53M1": "zero",
        "P31M13": "zero",
        "P29M12": "echo_list",
        "PUSH_NOTIFICATION": "0",
        "SPARTACUS_PROFILE": str(application_dir() / "data" / "profile.json"),
        "SPARTACUS_PRUDP_LOG": str(log_dir / "prudp.log"),
        "SPARTACUS_CONFIG_LOG": str(log_dir / "online_config.log"),
        "SPARTACUS_ROSTER_PROFILE": str(application_dir() / "data" / "roster.json"),
        "SPARTACUS_CAMPAIGN_PROFILE": str(application_dir() / "data" / "campaign.json"),
        "SPARTACUS_ROSTER_LOG": str(log_dir / "roster_bridge.log"),
    }
    for key, value in defaults.items():
        os.environ.setdefault(key, value)


def reserve_ports(host: str, http_port: int, auth_port: int, secure_port: int):
    reservations = []
    specs = [
        ("OnlineConfig", socket.SOCK_STREAM, http_port),
        ("Quazal auth", socket.SOCK_DGRAM, auth_port),
        ("Quazal secure", socket.SOCK_DGRAM, secure_port),
    ]
    try:
        for label, kind, port in specs:
            sock = socket.socket(socket.AF_INET, kind)
            if os.name == "nt" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            try:
                sock.bind((host, port))
                if kind == socket.SOCK_STREAM:
                    sock.listen(1)
            except OSError as error:
                sock.close()
                raise RuntimeError(
                    f"{label} cannot bind {host}:{port}: {error}. "
                    "Close the program using that port and try again."
                ) from error
            reservations.append(sock)
        return reservations
    except Exception:
        for sock in reservations:
            sock.close()
        raise


def run_component(name, target, failures: queue.Queue, stop_event, *args):
    try:
        target(*args)
    except Exception as error:
        failures.put((name, error, traceback.format_exc()))
        stop_event.set()


def wait_for_services(ready_events, failures, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not failures.empty():
            return False
        if all(event.is_set() for event in ready_events):
            return True
        time.sleep(0.05)
    return False


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--advertise-host", default=None,
                        help="address the online-config response hands the game "
                             "for the Quazal endpoint. Defaults to 127.0.0.1, "
                             "which is correct unless RPCS3's 'Bind address' is "
                             "set - a bound game socket cannot reach loopback, "
                             "so pair --host 0.0.0.0 with the bind address here")
    parser.add_argument("--http-port", type=int, default=DEFAULT_HTTP_PORT)
    parser.add_argument("--auth-port", type=int, default=DEFAULT_AUTH_PORT)
    parser.add_argument("--secure-port", type=int, default=DEFAULT_SECURE_PORT)
    parser.add_argument("--pine-port", type=int, default=DEFAULT_PINE_PORT,
                        help="RPCS3 IPC/PINE port used for roster persistence")
    parser.add_argument("--no-roster-bridge", action="store_true",
                        help="disable automatic roster capture/restore")
    parser.add_argument("--check", action="store_true",
                        help="check ports and configuration, then exit")
    parser.add_argument("--recover-legends", type=Path, metavar="RPCS3_FOLDER",
                        help="inspect owned Legends for re-recruitment and exit")
    parser.add_argument("--apply-recovery", action="store_true",
                        help="apply --recover-legends after making a full backup")
    parser.add_argument("--no-wait", action="store_true",
                        help="do not pause on a startup error")
    parser.add_argument("--run-seconds", type=float, default=0,
                        help=argparse.SUPPRESS)
    return parser.parse_args()


def maybe_pause(no_wait: bool) -> None:
    if not no_wait and sys.stdin.isatty():
        try:
            input("Press Enter to close...")
        except (EOFError, KeyboardInterrupt):
            pass


def main() -> int:
    # Keep this window readable when a user pipes it into a log file: unbuffered
    # stderr would otherwise overtake the buffered startup messages.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)
    args = parse_args()
    base_dir = application_dir()
    if args.apply_recovery and args.recover_legends is None:
        print("STARTUP ERROR: --apply-recovery requires --recover-legends",
              file=sys.stderr)
        maybe_pause(args.no_wait)
        return 2
    if args.recover_legends is not None:
        import legend_recovery
        try:
            return legend_recovery.run_recovery(
                base_dir / "data", rpcs3_root=args.recover_legends,
                apply=args.apply_recovery, pine_port=args.pine_port,
            )
        except legend_recovery.RecoveryError as error:
            print(f"RECOVERY ERROR: {error}", file=sys.stderr)
            maybe_pause(args.no_wait)
            return 2
    log_dir = base_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    # The game connects to whatever address these responses name, so this is an
    # advertised address and not a bind address - they only coincide in the
    # default loopback setup. Both the online-config response and the Quazal
    # auth->secure redirect must carry it.
    advertise_host = args.advertise_host or "127.0.0.1"
    configure_environment(log_dir, args.secure_port, advertise_host)

    print(f"Spartacus Legends Preservation Server v{VERSION}")
    print(f"Logs: {log_dir}")
    if running_from_temp(base_dir):
        print("\nWARNING: this server is running from a temporary folder:")
        print(f"  {base_dir}")
        print("That happens when the release is started from inside the ZIP. Windows "
              "deletes this folder, taking your saved profile, roster and campaign "
              "progress with it.")
        print("Close this window, extract the ZIP to a real folder, and run the "
              "extracted SpartacusLegendsServer.exe instead.\n")
    try:
        reservations = reserve_ports(
            args.host, args.http_port, args.auth_port, args.secure_port
        )
    except RuntimeError as error:
        print(f"\nSTARTUP ERROR: {error}", file=sys.stderr)
        maybe_pause(args.no_wait)
        return 2

    for reservation in reservations:
        reservation.close()
    print(f"Port check passed: TCP {args.http_port}, "
          f"UDP {args.auth_port}, UDP {args.secure_port}")
    if args.check:
        return 0

    # Import after setting the known-good environment; the protocol module
    # intentionally reads its response matrix once at startup.
    import prudp_server
    import roster_bridge
    from UbiOnlineConfigService import spartacus_onlineconfig

    stop_event = threading.Event()
    failures = queue.Queue()
    ready_http = threading.Event()
    ready_auth = threading.Event()
    ready_secure = threading.Event()
    ready_roster = threading.Event()

    components = [
        ("OnlineConfig", spartacus_onlineconfig.serve,
         (args.host, args.http_port, advertise_host, args.auth_port,
          log_dir / "online_config.log", stop_event, ready_http)),
        ("Quazal auth", prudp_server.main,
         (args.auth_port, stop_event, ready_auth, args.host)),
        ("Quazal secure", prudp_server.main,
         (args.secure_port, stop_event, ready_secure, args.host)),
    ]
    if not args.no_roster_bridge:
        components.append(
            ("Roster companion", roster_bridge.run_roster_bridge,
             (stop_event, ready_roster, "127.0.0.1", args.pine_port))
        )
    threads = []
    for name, target, component_args in components:
        thread = threading.Thread(
            target=run_component,
            args=(name, target, failures, stop_event, *component_args),
            name=name,
            daemon=True,
        )
        thread.start()
        threads.append(thread)

    ready_events = [ready_http, ready_auth, ready_secure]
    if not args.no_roster_bridge:
        ready_events.append(ready_roster)
    if not wait_for_services(ready_events, failures):
        stop_event.set()
        if not failures.empty():
            name, error, detail = failures.get()
            print(f"\nSTARTUP ERROR in {name}: {error}\n{detail}", file=sys.stderr)
        else:
            print("\nSTARTUP ERROR: services did not become ready in 5 seconds.",
                  file=sys.stderr)
        for thread in threads:
            thread.join(timeout=1)
        maybe_pause(args.no_wait)
        return 3

    print("\nAll services are ready.")
    print(f"RPCS3 IP swap: onlineconfigservice.ubi.com={advertise_host}")
    print("Enable patch: Spartacus Legends - Server emulator compatibility")
    if not args.no_roster_bridge:
        print(f"Roster persistence: RPCS3 IPC must be enabled on port {args.pine_port}")
    print("Start the game, log in, and leave this window open.")
    print("Press Ctrl+C to stop the server.\n")

    deadline = (time.monotonic() + args.run_seconds
                if args.run_seconds > 0 else None)
    try:
        while not stop_event.wait(0.5):
            if deadline is not None and time.monotonic() >= deadline:
                return_code = 0
                break
            if not failures.empty():
                name, error, detail = failures.get()
                print(f"\nSERVICE ERROR in {name}: {error}\n{detail}",
                      file=sys.stderr)
                return_code = 4
                break
        else:
            return_code = 0
    except KeyboardInterrupt:
        print("\nStopping services...")
        return_code = 0
    finally:
        stop_event.set()
        for thread in threads:
            thread.join(timeout=2)
    print("Server stopped cleanly.")
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
