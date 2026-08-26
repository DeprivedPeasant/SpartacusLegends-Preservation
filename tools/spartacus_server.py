#!/usr/bin/env python3
"""All-in-one local server launcher for Spartacus Legends (PS3)."""

from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import queue
import socket
import sys
import threading
import time
import traceback

from _version import __version__ as VERSION
from server_config import (
    DEFAULT_TITLE_VERSION,
    config_path as server_config_path,
    read_title_version,
)


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
                          advertise_host: str = "127.0.0.1",
                          title_version: str = "01.00") -> None:
    """Set the exact response matrix validated by the preservation tests.

    advertise_host reaches the Quazal server through RDV_HOST, which it reads at
    import time to build the connection string that redirects the client from
    the auth server to the secure one. It has to agree with the address the
    online-config response hands out, or the client is sent somewhere it cannot
    reach and login stalls until it times out.
    """
    base_dir = application_dir()
    data_dir = base_dir / "data"
    user_content_dir = data_dir / "usercontent"
    economy_profile = data_dir / "profile.json"
    if title_version != DEFAULT_TITLE_VERSION:
        user_content_dir /= title_version
        economy_profile = data_dir / f"profile-{title_version}.json"
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
        "SPARTACUS_PROFILE": str(economy_profile),
        "SPARTACUS_PRUDP_LOG": str(log_dir / "prudp.log"),
        "SPARTACUS_CONFIG_LOG": str(log_dir / "online_config.log"),
        # PyInstaller extracts imported modules beneath a temporary _MEIPASS
        # directory. Never let the HTTP upload handler derive persistence from
        # __file__; native user-content must live beside the release executable.
        "SPARTACUS_USER_CONTENT_DIR": str(user_content_dir),
        "SPARTACUS_USER_CONTENT_HOST": advertise_host,
        # UserContent property 100 selects different native apply routines in
        # 01.00 and 01.06. prudp_server uses this to replay the exact metadata
        # emitted by the matching title's writer.
        "SPARTACUS_TITLE_VERSION": title_version,
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


def parse_args(argv=None):
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
                        help="RPCS3 IPC/PINE port used only by the optional "
                             "legacy roster bridge")
    parser.add_argument("--legacy-roster-bridge", action="store_true",
                        help="enable the legacy PINE roster/campaign bridge; "
                             "normal persistence uses native server storage")
    # Accepted so existing scripts do not fail after the default changed. It is
    # now a no-op unless combined with --legacy-roster-bridge.
    parser.add_argument("--no-roster-bridge", action="store_true",
                        help=argparse.SUPPRESS)
    parser.add_argument("--title-version", default=None,
                        choices=["01.00", "01.06"],
                        help="Spartacus Legends build being served. Selects "
                             "the native save-object size table and the "
                             "matching required client patch. Defaults to "
                             "the version recorded by the patch installer")
    parser.add_argument("--check", action="store_true",
                        help="check ports and configuration, then exit")
    parser.add_argument("--recover-legends", type=Path, metavar="RPCS3_FOLDER",
                        help="inspect owned Legends for re-recruitment and exit")
    parser.add_argument("--apply-recovery", action="store_true",
                        help="apply --recover-legends after making a full backup")
    parser.add_argument("--migrate-01.00-to-01.06",
                        dest="migrate_01_00_to_01_06",
                        action="store_true",
                        help="create an isolated, backup-first 01.06 save "
                             "from complete 01.00 native saves, "
                             "then exit; existing 01.06 data is not "
                             "overwritten unless the separate replacement "
                             "flag is supplied")
    parser.add_argument("--replace-existing-01.06",
                        dest="replace_existing_01_06",
                        action="store_true",
                        help="with --migrate-01.00-to-01.06, replace an "
                             "existing unwanted 01.06 save only after the "
                             "complete data directory is backed up")
    parser.add_argument("--no-wait", action="store_true",
                        help="do not pause on a startup error")
    parser.add_argument("--run-seconds", type=float, default=0,
                        help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def maybe_pause(no_wait: bool) -> None:
    if not no_wait and sys.stdin.isatty():
        try:
            input("Press Enter to close...")
        except (EOFError, KeyboardInterrupt):
            pass


def resolve_title_version(cli_value: str | None,
                          base_dir: Path) -> tuple[str, str]:
    """Resolve the served build while preserving an explicit recovery override."""
    if cli_value is not None:
        return cli_value, "command-line override"
    configured = read_title_version(server_config_path(base_dir))
    if configured is not None:
        return configured, "patch-installer configuration"
    return DEFAULT_TITLE_VERSION, "01.00 backward-compatible default"


MIGRATION_TYPE_NAMES = {
    0x80000001: "profile",
    0x80000002: "campaign",
    0x80000003: "roster",
}


class MigrationController:
    """Automatic v0.3 -> v0.4 save migration for one server run.

    Owns detection, the timestamped backup, the migration marker, the
    upload gate, and (only when a PINE-restorable object is actually
    pending) the restore-once bridge. Fresh and completed installations
    never reach start(), so they never open a PINE connection.
    """

    def __init__(self, base_dir: Path, announce=None, title_version=None):
        import migration_coordinator
        self.mc = migration_coordinator
        self.base_dir = Path(base_dir)
        self.data_dir = self.base_dir / "data"
        self.announce = announce or print
        self.title_version = migration_coordinator.coerce_title_version(
            title_version)
        self.report = migration_coordinator.evaluate_installation(
            self.data_dir, self.title_version)
        self.gate = None
        self.pending_types = []
        self.stop_bridge = threading.Event()
        self.bridge = None
        self.completed = threading.Event()

    def _native_valid(self, type_id):
        info = self.mc.native_objects(self.title_version)[type_id]
        path = (self.mc.native_content_dir(
                    self.data_dir, self.title_version) /
                f"{type_id:08x}" /
                f"{self.mc.NATIVE_CONTENT_ID}.bin")
        try:
            return path.is_file() and info.accepts(path.stat().st_size)
        except OSError:
            return False

    def _refresh_assessment(self, type_id, state):
        assessment = self.report.assessments[type_id]
        assessment.state = state
        if state in (self.mc.ObjectState.CAPTURED,
                     self.mc.ObjectState.COMPLETE):
            path = (self.mc.native_content_dir(
                        self.data_dir, self.title_version) /
                    f"{type_id:08x}" /
                    f"{self.mc.NATIVE_CONTENT_ID}.bin")
            if path.is_file():
                assessment.native_path = path
                assessment.native_size = path.stat().st_size
                assessment.native_sha256 = \
                    self.mc.native_sha256(path)

    def _write_marker(self, status):
        self.mc.write_marker(self.data_dir, self.mc.build_marker(
            self.data_dir, self.report, self.report.backup_path, status))

    def _on_bridge_outcome(self, type_id, result):
        mc = self.mc
        name = MIGRATION_TYPE_NAMES.get(type_id, hex(type_id))
        if result == "restored":
            self.gate.set_state(type_id, mc.ObjectState.RESTORED)
            self.announce(f"Legacy {name} restored; waiting for native "
                          "upload.")
        elif result == "skipped":
            self.gate.set_state(type_id, mc.ObjectState.COMPLETE)
            self._refresh_assessment(type_id, mc.ObjectState.COMPLETE)
            self.announce(f"Native {name} became valid before restore; "
                          "left untouched.")
        else:
            self.gate.set_state(type_id, mc.ObjectState.BLOCKED)
            self.announce(
                f"Migration blocked for the {name}: the legacy source "
                "cannot be restored safely. Both the legacy file and any "
                "existing native object were preserved. Resolve the "
                "condition (or remove the blocked native file only after "
                "backing it up) and restart the server.")

    def start(self, pine_port: int, log_dir: Path):
        """Install the upload gate; start PINE only when eligible.

        Returns True when a migration gate is active and must be handed to
        the OnlineConfig component.
        """
        mc = self.mc
        if not self.report.migration_needed and not self.report.blocked:
            return False

        if self.report.blocked:
            # A malformed native object is a recovery condition. Keep the
            # gate up so no upload can silently replace it, but never start
            # PINE for it.
            self.gate = mc.UploadGate.from_report(self.report)
            for assessment in self.report.assessments.values():
                if assessment.state is mc.ObjectState.BLOCKED:
                    self.announce(f"STARTUP WARNING: {assessment.detail}.")
            self.announce(
                "Migration is disabled until the malformed object is "
                "resolved; uploads for it are being rejected.")
            return True

        backup = mc.create_backup(self.data_dir, self.report)
        self.report.backup_path = backup
        self.pending_types = sorted(
            t for t, a in self.report.assessments.items()
            if a.state is mc.ObjectState.PENDING)
        self.gate = mc.UploadGate.from_report(self.report)
        self._write_marker("pending")
        self.announce(
            "Legacy v0.3 save detected; one-time native migration enabled.")
        self.announce(f"Pre-migration backup: {backup}")

        pine_types = [t for t in self.pending_types if t != 0x80000001]
        if pine_types:
            self.announce(
                f"Waiting for RPCS3 IPC on port {pine_port}. Enable RPCS3 "
                "IPC (Configuration > GUI) if the game is already running.")
            import roster_bridge
            self.bridge = roster_bridge.MigrationBridge(
                roster_bridge.RosterStore(self.data_dir / "roster.json"),
                roster_bridge.BridgeLog(log_dir / "roster_bridge.log"),
                "127.0.0.1", pine_port,
                campaign_store=roster_bridge.CampaignStore(
                    self.data_dir / "campaign.json"),
                restore_roster=0x80000003 in pine_types,
                restore_campaign=0x80000002 in pine_types,
                native_valid=self._native_valid,
                callbacks=[self._on_bridge_outcome],
            )
        return True

    def bridge_component(self):
        """Component tuple for the restore-once bridge, or None."""
        if self.bridge is None:
            return None
        ready = threading.Event()
        # ready is set immediately by run(); treat the bridge as optional so
        # a PINE-less machine still boots the migration session.
        return ("Migration companion", self.bridge.run,
                (self.stop_bridge, ready))

    def watch(self, stop_event) -> None:
        """Component loop: track captures and finish the migration."""
        mc = self.mc
        announced = set()
        try:
            while not stop_event.wait(0.5):
                blocked = False
                for type_id in self.pending_types:
                    state = self.gate.state(type_id)
                    name = MIGRATION_TYPE_NAMES.get(type_id, hex(type_id))
                    if state is mc.ObjectState.BLOCKED:
                        blocked = True
                        continue
                    if (state is mc.ObjectState.CAPTURED
                            and type_id not in announced):
                        announced.add(type_id)
                        self._refresh_assessment(
                            type_id, mc.ObjectState.CAPTURED)
                        size = self.report.assessments[type_id].native_size
                        self.announce(
                            f"Native {name} upload verified ({size} bytes).")
                        self._write_marker("pending")
                if blocked:
                    self.stop_bridge.set()
                    self._write_marker("blocked")
                    return
                if all(self.gate.state(t) in (mc.ObjectState.CAPTURED,
                                              mc.ObjectState.COMPLETE)
                       for t in self.pending_types):
                    for type_id in self.pending_types:
                        if self.gate.state(type_id) is mc.ObjectState.CAPTURED:
                            self._refresh_assessment(
                                type_id, mc.ObjectState.COMPLETE)
                    self._write_marker("complete")
                    self.announce(
                        "Migration complete. PINE is no longer required.")
                    self.stop_bridge.set()
                    self.completed.set()
                    return
        finally:
            self.stop_bridge.set()


def main() -> int:
    # Keep this window readable when a user pipes it into a log file: unbuffered
    # stderr would otherwise overtake the buffered startup messages.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)
    args = parse_args()
    base_dir = application_dir()
    if args.replace_existing_01_06 and not args.migrate_01_00_to_01_06:
        print("MIGRATION ERROR: --replace-existing-01.06 requires "
              "--migrate-01.00-to-01.06", file=sys.stderr)
        maybe_pause(args.no_wait)
        return 2
    if args.migrate_01_00_to_01_06:
        if args.apply_recovery or args.recover_legends is not None:
            print("MIGRATION ERROR: the title-save migration cannot be "
                  "combined with Legend recovery", file=sys.stderr)
            maybe_pause(args.no_wait)
            return 2
        import title_save_migration
        try:
            result = title_save_migration.migrate_v100_to_v106(
                base_dir / "data",
                replace_existing=args.replace_existing_01_06,
            )
        except title_save_migration.TitleSaveMigrationError as error:
            print(f"MIGRATION ERROR: {error}", file=sys.stderr)
            maybe_pause(args.no_wait)
            return 2
        print("01.00 -> 01.06 save migration created.")
        print(f"Pre-migration backup: {result.backup_path}")
        print(f"01.06 native saves: {result.destination_root}")
        print(f"01.06 economy profile: {result.companion_path}")
        print("Recovered balances: "
              f"gold {result.balances['gold']}, "
              f"silver {result.balances['silver']}, "
              f"fame {result.balances['fame']}")
        print(f"Audit record: {result.marker_path}")
        print("Cold-boot 01.06 and validate campaign, roster, "
              "balances, Daily Goals, and Nemesis state before relying on it.")
        return 0
    try:
        args.title_version, version_source = resolve_title_version(
            args.title_version, base_dir)
    except ValueError as error:
        print(f"STARTUP ERROR: {error}", file=sys.stderr)
        maybe_pause(args.no_wait)
        return 2
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
    configure_environment(
        log_dir, args.secure_port, advertise_host, args.title_version
    )

    # The remote-config metadata row carries the expected digest of the exact
    # body served by the HTTP component. Derive it from the same response
    # builder before prudp_server reads its environment at import time.
    from UbiOnlineConfigService import spartacus_onlineconfig
    remote_config_body = spartacus_onlineconfig.make_remote_config_response()
    os.environ.setdefault(
        "SPARTACUS_REMOTE_CONFIG_SHA256",
        hashlib.sha256(remote_config_body).hexdigest().upper(),
    )

    print(f"Spartacus Legends Preservation Server v{VERSION}")
    print(f"Game version: {args.title_version} ({version_source})")
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
    legacy_roster_bridge = (args.legacy_roster_bridge and
                            not args.no_roster_bridge)
    if legacy_roster_bridge:
        import roster_bridge

    stop_event = threading.Event()
    failures = queue.Queue()
    ready_http = threading.Event()
    ready_auth = threading.Event()
    ready_secure = threading.Event()
    ready_roster = threading.Event()

    # Automatic legacy migration runs only in normal native mode; the
    # explicit --legacy-roster-bridge recovery/debug mode stays separate.
    migration = None
    if not legacy_roster_bridge:
        migration = MigrationController(base_dir,
                                        title_version=args.title_version)
        migration.start(args.pine_port, log_dir)

    onlineconfig_args = (args.host, args.http_port, advertise_host,
                         args.auth_port, log_dir / "online_config.log",
                         stop_event, ready_http)
    if migration is not None and migration.gate is not None:
        onlineconfig_args += (migration.gate,)

    components = [
        ("OnlineConfig", spartacus_onlineconfig.serve, onlineconfig_args),
        ("Quazal auth", prudp_server.main,
         (args.auth_port, stop_event, ready_auth, args.host)),
        ("Quazal secure", prudp_server.main,
         (args.secure_port, stop_event, ready_secure, args.host)),
    ]
    if legacy_roster_bridge:
        components.append(
            ("Roster companion", roster_bridge.run_roster_bridge,
             (stop_event, ready_roster, "127.0.0.1", args.pine_port))
        )
    if migration is not None:
        bridge_component = migration.bridge_component()
        if bridge_component is not None:
            components.append(bridge_component)
            components.append(
                ("Migration coordinator", migration.watch, (stop_event,)))
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
    if legacy_roster_bridge:
        ready_events.append(ready_roster)
    # The migration components manage their own readiness: the restore-once
    # bridge waits for RPCS3 IPC, which may not exist yet.
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
    print("Native save persistence: "
          f"{Path(os.environ['SPARTACUS_USER_CONTENT_DIR'])}")
    if legacy_roster_bridge:
        print(f"Legacy roster bridge: RPCS3 IPC port {args.pine_port}")
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
