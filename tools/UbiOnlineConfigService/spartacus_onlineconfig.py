#!/usr/bin/env python3
"""Standard-library OnlineConfigService for Spartacus Legends (PS3)."""

from __future__ import annotations

import argparse
import datetime as _datetime
import hashlib
import json
import os
import struct
from pathlib import Path
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse


SPARTACUS_ONLINE_CONFIG_ID = "423eddd2469548bcb7e78d2d45606d5d"
DEFAULT_RDV_HOST = os.environ.get("RDV_HOST", "127.0.0.1")
DEFAULT_RDV_PORT = int(os.environ.get("SPARTACUS_AUTH_PORT", "21000"))
DEFAULT_HTTP_PORT = int(os.environ.get("SPARTACUS_HTTP_PORT", "80"))
DEFAULT_LOG_PATH = Path(os.environ.get(
    "SPARTACUS_CONFIG_LOG",
    Path(__file__).resolve().parents[2] / "logs" / "online_config.log",
))
DEFAULT_USER_CONTENT_DIR = Path(os.environ.get(
    "SPARTACUS_USER_CONTENT_DIR",
    Path(__file__).resolve().parents[2] / "data" / "usercontent",
))


class ServiceLog:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.Lock()

    def write(self, message: str) -> None:
        timestamp = _datetime.datetime.now().strftime("%H:%M:%S.%f")
        line = f"[{timestamp}] [config] {message}"
        with self._lock:
            print(line, flush=True)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8", errors="replace") as stream:
                stream.write(line + "\n")


def make_response(rdv_host: str = DEFAULT_RDV_HOST,
                  rdv_port: int = DEFAULT_RDV_PORT) -> bytes:
    endpoint = f"prudp:/address={rdv_host};port={rdv_port}"
    values = [
        {"Name": "SandboxUrlPS3", "Values": [endpoint]},
        {"Name": "TrackingSandboxURLPS3", "Values": [endpoint]},
        {"Name": "SandboxUrl", "Values": [endpoint]},
        {"Name": "SandboxUrlWS", "Values": [f"{rdv_host}:{rdv_port}"]},
        {"Name": "uplay_DownloadServiceUrl", "Values": [
            "https://secure.ubi.com/UplayServices/UplayFacade/"
            "DownloadServicesRESTXML.svc/REST/XML/?url="
        ]},
        {"Name": "uplay_DynContentBaseUrl", "Values": [
            "http://static8.cdn.ubi.com/u/Uplay/"
        ]},
        {"Name": "uplay_DynContentSecureBaseUrl", "Values": [
            "http://static8.cdn.ubi.com/"
        ]},
        {"Name": "uplay_LinkappBaseUrl", "Values": [
            "http://static8.cdn.ubi.com/u/Uplay/Packages/linkapp/1.1/"
        ]},
        {"Name": "uplay_PackageBaseUrl", "Values": [
            "http://static8.cdn.ubi.com/u/Uplay/Packages/1.0.1/"
        ]},
        {"Name": "uplay_WebServiceBaseUrl", "Values": [
            "https://secure.ubi.com/UplayServices/UplayFacade/"
            "ProfileServicesFacadeRESTXML.svc/REST/"
        ]},
    ]
    return json.dumps(values, separators=(",", ":")).encode("utf-8")


def make_remote_config_response() -> bytes:
    """Minimal KFF mode-3 object: version 1 and no fixed records."""
    return struct.pack(">II", 1, 0)


def make_handler(rdv_host: str, rdv_port: int, service_log: ServiceLog,
                 user_content_dir: Path = DEFAULT_USER_CONTENT_DIR,
                 upload_gate=None):
    response_body = make_response(rdv_host, rdv_port)
    remote_config_body = make_remote_config_response()
    user_content_dir = Path(user_content_dir)

    class OnlineConfigHandler(BaseHTTPRequestHandler):
        server_version = "SpartacusOnlineConfig/1.0"

        @staticmethod
        def _user_content_target(route: str):
            """Return (path, type_id) for a usercontent route, else None."""
            parts = route.strip("/").split("/")
            if len(parts) != 3 or parts[0] != "usercontent" \
                    or not parts[2].endswith(".bin"):
                return None
            try:
                type_id = int(parts[1], 16)
                content_id = int(parts[2][:-4], 10)
            except ValueError:
                return None
            return (user_content_dir / f"{type_id:08x}" /
                    f"{content_id}.bin", type_id)

        def _send_body(self, status: int, body: bytes,
                       content_type: str = "application/octet-stream") -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            if self.command != "HEAD" and body:
                self.wfile.write(body)

        def _respond(self) -> None:
            parsed = urlparse(self.path)
            user_content = self._user_content_target(parsed.path)
            if user_content is not None:
                user_content_target, type_id = user_content
                if self.command in ("POST", "PUT"):
                    try:
                        length = int(self.headers.get("Content-Length", "0"))
                    except ValueError:
                        length = -1
                    if length < 0 or length > 0x100000:
                        service_log.write(
                            f"{self.command} {self.path} rejected length={length}"
                        )
                        self._send_body(413, b"")
                        return
                    if upload_gate is not None:
                        decision = upload_gate.check(type_id, length)
                        if not decision.allowed:
                            status = 503 if decision.retryable else 400
                            service_log.write(
                                f"{self.command} {self.path} "
                                f"{'deferred' if decision.retryable else 'rejected'} "
                                f"length={length} state={decision.state}: "
                                f"{decision.reason}"
                            )
                            self._send_body(status, b"")
                            return
                    body = self.rfile.read(length)
                    user_content_target.parent.mkdir(parents=True, exist_ok=True)
                    temporary = user_content_target.with_name(
                        user_content_target.name +
                        f".tmp-{threading.get_ident()}"
                    )
                    temporary.write_bytes(body)
                    os.replace(temporary, user_content_target)
                    digest = hashlib.sha256(body).hexdigest()
                    stored_state = ""
                    if upload_gate is not None:
                        stored_state = upload_gate.record_stored(
                            type_id, len(body)).value
                    service_log.write(
                        f"{self.command} {self.path} stored={len(body)} "
                        f"sha256={digest}"
                        + (f" state={stored_state}" if stored_state else "")
                    )
                    self._send_body(200, b"")
                    return
                if self.command in ("GET", "HEAD"):
                    if not user_content_target.is_file():
                        service_log.write(
                            f"{self.command} {self.path} user content not found"
                        )
                        self._send_body(404, b"")
                        return
                    body = user_content_target.read_bytes()
                    service_log.write(
                        f"{self.command} {self.path} served={len(body)}"
                    )
                    self._send_body(200, body)
                    return
                self._send_body(405, b"")
                return

            query = parse_qs(parsed.query)
            config_id = query.get("onlineConfigID", [None])[0]
            target = query.get("target", [None])[0]
            ticket = query.get("psnTicket", [None])[0]
            host = self.headers.get("Host")
            known_route = parsed.path in (
                "/OnlineConfigService.svc/GetOnlineConfig",
                "/OnlineConfigService.svc/GetOnlineConfigPSN",
            )
            is_remote_config = parsed.path == "/remoteconfig.bin"
            ticket_state = f"present({len(ticket)})" if ticket else "absent"
            service_log.write(
                f"{self.command} {self.path} host={host!r} target={target!r} "
                f"config_id={config_id!r} psn_ticket={ticket_state}"
                + ("" if known_route else " [fallback route]")
            )
            if config_id and config_id != SPARTACUS_ONLINE_CONFIG_ID:
                service_log.write("warning: unknown OnlineConfig ID; responding anyway")
            body = remote_config_body if is_remote_config else response_body
            content_type = ("application/octet-stream" if is_remote_config
                            else "application/json")
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        do_GET = _respond
        do_POST = _respond
        do_PUT = _respond
        do_HEAD = _respond

        def log_message(self, fmt, *args):
            return

    return OnlineConfigHandler


def serve(host: str = "0.0.0.0", port: int = DEFAULT_HTTP_PORT,
          rdv_host: str = DEFAULT_RDV_HOST, rdv_port: int = DEFAULT_RDV_PORT,
          log_path: Path = DEFAULT_LOG_PATH, stop_event=None, ready_event=None,
          upload_gate=None):
    owns_stop_event = stop_event is None
    if stop_event is None:
        stop_event = threading.Event()
    service_log = ServiceLog(Path(log_path))
    server = ThreadingHTTPServer(
        (host, int(port)),
        make_handler(rdv_host, int(rdv_port), service_log,
                     upload_gate=upload_gate)
    )
    server.timeout = 0.5
    service_log.write(
        f"listening on {host}:{port}; auth endpoint={rdv_host}:{rdv_port}"
    )
    if ready_event is not None:
        ready_event.set()
    try:
        while not stop_event.is_set():
            server.handle_request()
    except KeyboardInterrupt:
        if owns_stop_event:
            service_log.write("shutting down")
    finally:
        server.server_close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=DEFAULT_HTTP_PORT)
    parser.add_argument("--rdv-host", default=DEFAULT_RDV_HOST)
    parser.add_argument("--rdv-port", type=int, default=DEFAULT_RDV_PORT)
    parser.add_argument("--log", type=Path, default=DEFAULT_LOG_PATH)
    args = parser.parse_args()
    serve(args.host, args.port, args.rdv_host, args.rdv_port, args.log)


if __name__ == "__main__":
    main()
