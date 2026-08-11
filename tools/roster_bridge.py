#!/usr/bin/env python3
"""Persistent RPCS3/PINE roster companion for Spartacus Legends.

The retail game keeps complete gladiator instances in live memory but writes
only a compact product manifest to PRG-DATA.  This bridge snapshots the proven
bounded live representation and restores it after each login.  It intentionally
uses only Python's standard library so it can be bundled with the preservation
server.
"""

from __future__ import annotations

from dataclasses import dataclass
import datetime as _datetime
import json
import os
from pathlib import Path
import socket
import struct
import threading
import time
from typing import Iterable


PINE_READ32 = 0x02
PINE_READ64 = 0x03
PINE_WRITE32 = 0x06
PINE_WRITE64 = 0x07
PINE_VERSION = 0x08
PINE_TITLE = 0x0B
PINE_ID = 0x0C
PINE_UUID = 0x0D
PINE_GAME_VERSION = 0x0E
PINE_STATUS = 0x0F

EXPECTED_TITLE = "Spartacus Legends"
EXPECTED_SERIAL = "NPUB30746"
EXPECTED_GAME_VERSION = "01.00"
EXPECTED_UUID = "PPU-81471d050c14f4d20b4027686f8b571dafd32394"

BACKEND_MANAGER_SLOT = 0x008C0554
BACKEND_READY_STATE = 26
EXPECTED_BACKEND_MANAGER = 0x01992530

ROSTER_MANAGER = 0x019CE3B0
STORE_COUNT = ROSTER_MANAGER + 0x53C0
OWNED_COUNT = ROSTER_MANAGER + 0x53C4
OWNED_BASE = ROSTER_MANAGER + 0x820
OWNED_BACKING_BASE = ROSTER_MANAGER + 0x44C0
# Section-1 profile field used by the Ludus as the highest unlocked zero-based
# slot index.  A fresh profile contains 1 (two usable slots); purchasing item
# 80002 changes it to 2 (three usable slots).
UNLOCKED_SLOT_INDEX = 0x008FF448
RECORD_STRIDE = 0x158
BACKING_STRIDE = 0x40
RECORD_WORDS = RECORD_STRIDE // 8
BACKING_WORDS = BACKING_STRIDE // 8
MAX_ROSTER = 8


class PineError(RuntimeError):
    pass


class PineClient:
    """Small synchronous PINE client; exactly one request is in flight."""

    def __init__(self, host="127.0.0.1", port=28012, timeout=2.0):
        self.host = host
        self.port = int(port)
        self.timeout = float(timeout)
        self.socket = None

    def connect(self):
        if self.socket is not None:
            return
        sock = socket.create_connection((self.host, self.port), self.timeout)
        sock.settimeout(self.timeout)
        self.socket = sock

    def close(self):
        if self.socket is not None:
            try:
                self.socket.close()
            except OSError:
                pass
            self.socket = None

    def _recv_exact(self, length):
        chunks = []
        remaining = length
        while remaining:
            data = self.socket.recv(remaining)
            if not data:
                raise PineError("PINE connection closed")
            chunks.append(data)
            remaining -= len(data)
        return b"".join(chunks)

    def call(self, opcode, arguments=b""):
        self.connect()
        frame = struct.pack("<IB", 5 + len(arguments), opcode) + arguments
        try:
            self.socket.sendall(frame)
            total = struct.unpack("<I", self._recv_exact(4))[0]
            if total < 5 or total > 1024 * 1024:
                raise PineError(f"invalid PINE reply length {total}")
            reply = self._recv_exact(total - 4)
        except (OSError, struct.error, PineError):
            self.close()
            raise
        result = reply[0]
        if result == 0xFF:
            raise PineError(f"PINE rejected opcode 0x{opcode:02X}")
        if result != 0:
            raise PineError(f"unknown PINE result 0x{result:02X}")
        return reply[1:]

    def read32(self, address):
        return struct.unpack("<I", self.call(PINE_READ32, struct.pack("<I", address)))[0]

    def read64(self, address):
        return struct.unpack("<Q", self.call(PINE_READ64, struct.pack("<I", address)))[0]

    def write32(self, address, value):
        self.call(PINE_WRITE32, struct.pack("<II", address, value & 0xFFFFFFFF))

    def write64(self, address, value):
        self.call(PINE_WRITE64, struct.pack("<IQ", address, value & 0xFFFFFFFFFFFFFFFF))

    def _string(self, opcode):
        payload = self.call(opcode)
        if len(payload) < 4:
            raise PineError("short PINE string reply")
        length = struct.unpack_from("<I", payload)[0]
        return payload[4:4 + length].rstrip(b"\0").decode("utf-8", "replace")

    def version(self):
        return self._string(PINE_VERSION)

    def title(self):
        return self._string(PINE_TITLE)

    def serial(self):
        return self._string(PINE_ID)

    def uuid(self):
        return self._string(PINE_UUID)

    def game_version(self):
        return self._string(PINE_GAME_VERSION)

    def status(self):
        return struct.unpack("<I", self.call(PINE_STATUS))[0]


def _hex_words(words: Iterable[int]):
    return [f"{word:016X}" for word in words]


def _parse_words(values, expected, label):
    if not isinstance(values, list) or len(values) != expected:
        raise ValueError(f"{label} must contain {expected} words")
    words = []
    for value in values:
        word = int(value, 16) if isinstance(value, str) else int(value)
        if not 0 <= word <= 0xFFFFFFFFFFFFFFFF:
            raise ValueError(f"invalid {label} word")
        words.append(word)
    return tuple(words)


@dataclass(frozen=True)
class RosterSnapshot:
    count: int
    unlocked_slots: int
    records: tuple[tuple[int, ...], ...]
    backings: tuple[tuple[int, ...], ...]

    def __post_init__(self):
        if not 1 <= self.count <= MAX_ROSTER:
            raise ValueError("roster count outside supported range")
        if not max(2, self.count) <= self.unlocked_slots <= MAX_ROSTER:
            raise ValueError("unlocked slot count outside supported range")
        if len(self.records) != self.count or len(self.backings) != self.count:
            raise ValueError("roster count does not match payload")
        if any(len(record) != RECORD_WORDS for record in self.records):
            raise ValueError("invalid roster record length")
        if any(len(backing) != BACKING_WORDS for backing in self.backings):
            raise ValueError("invalid roster backing length")

    def to_dict(self):
        return {
            "schema_version": 2,
            "game": {
                "title": EXPECTED_TITLE,
                "serial": EXPECTED_SERIAL,
                "game_version": EXPECTED_GAME_VERSION,
                "uuid": EXPECTED_UUID,
            },
            "layout": {
                "record_stride": RECORD_STRIDE,
                "backing_stride": BACKING_STRIDE,
                "max_roster": MAX_ROSTER,
            },
            "count": self.count,
            "unlocked_slots": self.unlocked_slots,
            "records": [_hex_words(record) for record in self.records],
            "backings": [_hex_words(backing) for backing in self.backings],
            "captured_at": _datetime.datetime.now().astimezone().isoformat(),
        }

    @classmethod
    def from_dict(cls, data):
        schema_version = int(data.get("schema_version", 0))
        if schema_version not in (1, 2):
            raise ValueError("unsupported roster schema")
        game = data.get("game", {})
        if (game.get("serial") != EXPECTED_SERIAL or
                game.get("game_version") != EXPECTED_GAME_VERSION or
                game.get("uuid") != EXPECTED_UUID):
            raise ValueError("roster belongs to a different game build")
        layout = data.get("layout", {})
        if (int(layout.get("record_stride", 0)) != RECORD_STRIDE or
                int(layout.get("backing_stride", 0)) != BACKING_STRIDE):
            raise ValueError("unsupported roster memory layout")
        count = int(data["count"])
        if schema_version == 1:
            # Schema 1 predated capacity capture. Never hide a stored
            # gladiator, while retaining the retail profile's two free slots.
            unlocked_slots = max(2, count)
        else:
            unlocked_slots = int(data["unlocked_slots"])
        records = tuple(
            _parse_words(values, RECORD_WORDS, "record")
            for values in data.get("records", [])
        )
        backings = tuple(
            _parse_words(values, BACKING_WORDS, "backing")
            for values in data.get("backings", [])
        )
        return cls(count, unlocked_slots, records, backings)


class RosterStore:
    def __init__(self, path):
        self.path = Path(path).resolve()
        self.lock = threading.RLock()

    def load(self):
        with self.lock:
            try:
                with self.path.open("r", encoding="utf-8") as handle:
                    return RosterSnapshot.from_dict(json.load(handle))
            except FileNotFoundError:
                return None

    def save(self, snapshot):
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(self.path.suffix + ".tmp")
            with temporary.open("w", encoding="utf-8", newline="\n") as handle:
                json.dump(snapshot.to_dict(), handle, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)


class BridgeLog:
    def __init__(self, path):
        self.path = Path(path).resolve()
        self.lock = threading.Lock()

    def write(self, message):
        timestamp = _datetime.datetime.now().strftime("%H:%M:%S.%f")
        line = f"[{timestamp}] [roster] {message}"
        with self.lock:
            print(line, flush=True)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8", errors="replace") as handle:
                handle.write(line + "\n")


class RosterBridge:
    def __init__(self, store, logger, host="127.0.0.1", port=28012,
                 poll_seconds=1.0, stable_reads=2, client_factory=PineClient):
        self.store = store
        self.log = logger
        self.host = host
        self.port = int(port)
        self.poll_seconds = max(0.2, float(poll_seconds))
        self.stable_reads = max(2, int(stable_reads))
        self.client_factory = client_factory

    @staticmethod
    def _record_address(slot):
        return OWNED_BASE + slot * RECORD_STRIDE

    @staticmethod
    def _backing_address(slot):
        return OWNED_BACKING_BASE + slot * BACKING_STRIDE

    def _validate_game(self, client):
        title = client.title()
        serial = client.serial()
        version = client.game_version()
        uuid = client.uuid()
        if (title, serial, version, uuid) != (
                EXPECTED_TITLE, EXPECTED_SERIAL, EXPECTED_GAME_VERSION, EXPECTED_UUID):
            raise PineError(
                f"unsupported game/build: {title!r} {serial!r} {version!r} {uuid!r}"
            )

    def _ready(self, client):
        if client.status() == 2:
            return False
        manager = client.read32(BACKEND_MANAGER_SLOT)
        if manager != EXPECTED_BACKEND_MANAGER:
            return False
        if client.read32(manager) != BACKEND_READY_STATE:
            return False
        if client.read32(STORE_COUNT) != 6:
            return False
        count = client.read32(OWNED_COUNT)
        unlocked_slots = client.read32(UNLOCKED_SLOT_INDEX) + 1
        return (1 <= count <= MAX_ROSTER and
                max(2, count) <= unlocked_slots <= MAX_ROSTER)

    def read_snapshot(self, client):
        count_before = client.read32(OWNED_COUNT)
        if not 1 <= count_before <= MAX_ROSTER:
            raise PineError(f"unsafe owned count {count_before}")
        unlocked_slots = client.read32(UNLOCKED_SLOT_INDEX) + 1
        if not max(2, count_before) <= unlocked_slots <= MAX_ROSTER:
            raise PineError(f"unsafe unlocked slot count {unlocked_slots}")
        records = []
        backings = []
        for slot in range(count_before):
            record_address = self._record_address(slot)
            backing_address = self._backing_address(slot)
            pointer = client.read32(record_address)
            if pointer != backing_address:
                raise PineError(
                    f"slot {slot} backing pointer 0x{pointer:08X}, "
                    f"expected 0x{backing_address:08X}"
                )
            records.append(tuple(
                client.read64(record_address + offset)
                for offset in range(0, RECORD_STRIDE, 8)
            ))
            backings.append(tuple(
                client.read64(backing_address + offset)
                for offset in range(0, BACKING_STRIDE, 8)
            ))
        count_after = client.read32(OWNED_COUNT)
        if count_after != count_before:
            raise PineError("roster changed during capture")
        return RosterSnapshot(
            count_before, unlocked_slots, tuple(records), tuple(backings)
        )

    def restore_snapshot(self, client, snapshot):
        # Validate every destination pointer before mutating any state.
        for slot in range(snapshot.count):
            pointer = client.read32(self._record_address(slot))
            expected = self._backing_address(slot)
            if pointer != expected:
                raise PineError(
                    f"refusing restore: slot {slot} pointer 0x{pointer:08X}, "
                    f"expected 0x{expected:08X}"
                )

        # Restore capacity before publishing roster occupancy. The Ludus UI
        # copies this section-1 field into its view state on first entry.
        client.write32(UNLOCKED_SLOT_INDEX, snapshot.unlocked_slots - 1)

        # Backing storage first.  Inactive B[1..] records follow while the live
        # count still hides them; B[0] is written last, then count publishes the
        # complete roster atomically from the UI's perspective.
        for slot, words in enumerate(snapshot.backings):
            base = self._backing_address(slot)
            for index, word in enumerate(words):
                client.write64(base + index * 8, word)

        order = list(range(1, snapshot.count)) + [0]
        for slot in order:
            base = self._record_address(slot)
            for index, word in enumerate(snapshot.records[slot]):
                client.write64(base + index * 8, word)
        client.write32(OWNED_COUNT, snapshot.count)

        verified = self.read_snapshot(client)
        if verified != snapshot:
            raise PineError("roster read-back did not match persisted snapshot")

    def _wait(self, stop_event, seconds=None):
        return stop_event.wait(self.poll_seconds if seconds is None else seconds)

    def _run_connection(self, client, stop_event):
        self._validate_game(client)
        self.log.write(
            f"connected to {client.version()} for {EXPECTED_SERIAL}; "
            "waiting for post-login state 26"
        )
        session_active = False
        stable_ready = 0
        authoritative = None
        pending = None
        pending_reads = 0

        while not stop_event.is_set():
            if not self._ready(client):
                if session_active:
                    self.log.write("login session ended; capture suspended")
                session_active = False
                stable_ready = 0
                authoritative = None
                pending = None
                pending_reads = 0
                if self._wait(stop_event):
                    return
                continue

            if not session_active:
                stable_ready += 1
                if stable_ready < self.stable_reads:
                    if self._wait(stop_event):
                        return
                    continue
                saved = self.store.load()
                if saved is not None:
                    current = self.read_snapshot(client)
                    if current != saved:
                        self.restore_snapshot(client, saved)
                        self.log.write(f"restored {saved.count} gladiator(s); count published last")
                    else:
                        self.log.write(f"live roster already matches saved {saved.count}-gladiator snapshot")
                    authoritative = saved
                else:
                    authoritative = self.read_snapshot(client)
                    self.store.save(authoritative)
                    self.log.write(f"created initial {authoritative.count}-gladiator roster profile")
                session_active = True
                pending = None
                pending_reads = 0
                if self._wait(stop_event):
                    return
                continue

            candidate = self.read_snapshot(client)
            if candidate == authoritative:
                pending = None
                pending_reads = 0
            elif candidate == pending:
                pending_reads += 1
                if pending_reads >= self.stable_reads:
                    self.store.save(candidate)
                    authoritative = candidate
                    pending = None
                    pending_reads = 0
                    self.log.write(f"saved stable {candidate.count}-gladiator roster update")
            else:
                pending = candidate
                pending_reads = 1
            if self._wait(stop_event):
                return

    def run(self, stop_event, ready_event=None):
        if ready_event is not None:
            ready_event.set()
        self.log.write(f"companion enabled; RPCS3 IPC target {self.host}:{self.port}")
        warned = False
        while not stop_event.is_set():
            client = self.client_factory(self.host, self.port)
            try:
                client.connect()
                warned = False
                self._run_connection(client, stop_event)
            except (OSError, PineError, ValueError, json.JSONDecodeError) as error:
                if not warned:
                    self.log.write(
                        f"waiting for compatible RPCS3 IPC ({error}); "
                        "enable RPCS3 IPC on port 28012"
                    )
                    warned = True
                if stop_event.wait(2.0):
                    return
            finally:
                client.close()


def run_roster_bridge(stop_event, ready_event=None, host="127.0.0.1", port=28012,
                      profile_path=None, log_path=None, poll_seconds=1.0):
    base = Path(__file__).resolve().parents[1]
    profile_path = profile_path or os.environ.get(
        "SPARTACUS_ROSTER_PROFILE", str(base / "data" / "roster.json")
    )
    log_path = log_path or os.environ.get(
        "SPARTACUS_ROSTER_LOG", str(base / "logs" / "roster_bridge.log")
    )
    bridge = RosterBridge(
        RosterStore(profile_path), BridgeLog(log_path), host, port, poll_seconds
    )
    bridge.run(stop_event, ready_event)
