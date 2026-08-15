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

# Retail initializes storage for 40 owned records/backing strings even though
# the playable Ludus is capped at eight.  Procedural fighters are flat, but
# Legends carry shallow pointers into a packed definition/string catalog.  A
# live Oenomaus record references a string beginning at root+0xB4 and ending at
# root+0xF1, so the earlier 0xB0 estimate (distance between nearby catalog
# entries) was not a complete payload. Capture a conservative 0x200-byte
# window. Relocated windows are packed into backing-string slots 8..39; using
# inactive owned records caused the post-fight native serializer to stall.
# The retail A->B copy intentionally shares the live catalog for the duration
# of a process; a persisted snapshot must instead relocate it across boots.
RETAIL_OWNED_CAPACITY = 40
LEGEND_BLOCK_SIZE = 0x200
LEGEND_BLOCK_WORDS = LEGEND_BLOCK_SIZE // 8
OWNED_BACKING_END = OWNED_BACKING_BASE + RETAIL_OWNED_CAPACITY * BACKING_STRIDE
LEGEND_ARENA_BASE = OWNED_BACKING_BASE + MAX_ROSTER * BACKING_STRIDE
LEGEND_ARENA_CAPACITY = ((OWNED_BACKING_END - LEGEND_ARENA_BASE) //
                         LEGEND_BLOCK_SIZE)
LEGEND_ARENA_END = LEGEND_ARENA_BASE + LEGEND_ARENA_CAPACITY * LEGEND_BLOCK_SIZE

if LEGEND_ARENA_CAPACITY < 3 or LEGEND_ARENA_END > OWNED_BACKING_END:
    raise RuntimeError("legend relocation arena exceeds inactive backing storage")

# Campaign (Primus/mission) completion.  Manager 5 (the 6-district x 64-event
# grid) stores completion in a table of 0x10-byte cells at manager+0xC4, indexed
# by district*64 + event, with a dirty flag at manager+0x18C8.  The game's
# section-1 boot apply (FUN_001e08b4) walks this grid but breaks on the first
# null entry; because the grid is not yet built when section 1 loads, zero
# Primus cells are marked and the chain reverts.  Managers 1-4 (simple flags)
# apply correctly, so only this manager is restored here.  A real win writes
# small integer scalars (e.g. +0x4=3, +0x8=1) into the event's cell.
CAMPAIGN_MANAGER_SLOT = 0x008C1A7C
EXPECTED_CAMPAIGN_MANAGER = 0x019D4D64
CAMPAIGN_TABLE_OFFSET = 0xC4
CAMPAIGN_DIRTY_OFFSET = 0x18C8
CAMPAIGN_DISTRICTS = 6
CAMPAIGN_EVENTS = 64
CAMPAIGN_CELL_STRIDE = 0x10
CAMPAIGN_CELL_COUNT = CAMPAIGN_DISTRICTS * CAMPAIGN_EVENTS
CAMPAIGN_CELL_WORDS = CAMPAIGN_CELL_STRIDE // 8
# RPCS3 places the game's dynamic heap in this band.  Completion cells hold
# scalars (counts/ratings/ids); a value here would be a live pointer that is not
# stable across boots, so a snapshot containing one is refused rather than saved.
HEAP_POINTER_LOW = 0x30000000
HEAP_POINTER_HIGH = 0x40000000


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


def _word_halves(word: int):
    """Return both guest 32-bit fields represented by a PINE 64-bit word."""
    return ((word >> 32) & 0xFFFFFFFF, word & 0xFFFFFFFF)


def _map_word_halves(word: int, transform):
    high, low = _word_halves(word)
    return ((transform(high) & 0xFFFFFFFF) << 32) | (transform(low) & 0xFFFFFFFF)


def _address_in_block(address: int, base: int):
    return base <= address < base + LEGEND_BLOCK_SIZE


@dataclass(frozen=True)
class RelocatableBlock:
    base: int
    words: tuple[int, ...]

    def __post_init__(self):
        if not 0 < self.base <= 0xFFFFFFFF:
            raise ValueError("invalid relocatable block base")
        if len(self.words) != LEGEND_BLOCK_WORDS:
            raise ValueError("invalid relocatable block length")
        for word in self.words:
            if not 0 <= word <= 0xFFFFFFFFFFFFFFFF:
                raise ValueError("invalid relocatable block word")

    def to_dict(self):
        return {"base": f"{self.base:08X}", "words": _hex_words(self.words)}

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict):
            raise ValueError("relocatable block must be an object")
        base_value = data.get("base")
        base = int(base_value, 16) if isinstance(base_value, str) else int(base_value)
        return cls(base, _parse_words(data.get("words", []), LEGEND_BLOCK_WORDS,
                                      "relocatable block"))

    def rebase(self, destination: int):
        def relocate(value):
            if _address_in_block(value, self.base):
                return destination + (value - self.base)
            return value

        return RelocatableBlock(
            destination, tuple(_map_word_halves(word, relocate) for word in self.words)
        )


@dataclass(frozen=True)
class RosterSnapshot:
    count: int
    unlocked_slots: int
    records: tuple[tuple[int, ...], ...]
    backings: tuple[tuple[int, ...], ...]
    blocks: tuple[RelocatableBlock | None, ...] = ()

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
        if not self.blocks:
            object.__setattr__(self, "blocks", (None,) * self.count)
        if len(self.blocks) != self.count:
            raise ValueError("roster count does not match relocatable blocks")
        if sum(block is not None for block in self.blocks) > LEGEND_ARENA_CAPACITY:
            raise ValueError(
                f"roster exceeds {LEGEND_ARENA_CAPACITY}-Legend relocation capacity"
            )
        for slot, block in enumerate(self.blocks):
            if block is None:
                continue
            fields = [
                value for word in self.records[slot] for value in _word_halves(word)
            ]
            if not any(_address_in_block(value, block.base) for value in fields):
                raise ValueError("relocatable block has no record pointer")
            heap_fields = [
                value for value in fields
                if HEAP_POINTER_LOW <= value < HEAP_POINTER_HIGH
            ]
            if any(not _address_in_block(value, block.base) for value in heap_fields):
                raise ValueError("record contains a pointer outside its relocatable block")

    def unresolved_slots(self):
        unresolved = []
        for slot, (record, block) in enumerate(zip(self.records, self.blocks)):
            if block is None and any(_looks_like_pointer(word) for word in record):
                unresolved.append(slot)
        return tuple(unresolved)

    def materialize(self):
        """Relocate every captured Legend graph into reboot-stable manager storage."""
        if self.unresolved_slots():
            slots = ", ".join(str(slot) for slot in self.unresolved_slots())
            raise ValueError(f"legacy roster slots require Legend graph recovery: {slots}")

        records = []
        blocks = []
        legend_ordinal = 0
        for slot, (record, block) in enumerate(zip(self.records, self.blocks)):
            if block is None:
                records.append(record)
                blocks.append(None)
                continue
            destination = LEGEND_ARENA_BASE + legend_ordinal * LEGEND_BLOCK_SIZE
            legend_ordinal += 1

            def relocate(value):
                if _address_in_block(value, block.base):
                    return destination + (value - block.base)
                return value

            records.append(tuple(_map_word_halves(word, relocate) for word in record))
            blocks.append(block.rebase(destination))
        return RosterSnapshot(
            self.count, self.unlocked_slots, tuple(records), self.backings, tuple(blocks)
        )

    def to_dict(self):
        return {
            "schema_version": 3,
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
            "blocks": [block.to_dict() if block is not None else None
                       for block in self.blocks],
            "captured_at": _datetime.datetime.now().astimezone().isoformat(),
        }

    @classmethod
    def from_dict(cls, data):
        schema_version = int(data.get("schema_version", 0))
        if schema_version not in (1, 2, 3):
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
        if schema_version < 3:
            blocks = (None,) * count
        else:
            raw_blocks = data.get("blocks", [])
            if not isinstance(raw_blocks, list) or len(raw_blocks) != count:
                raise ValueError("roster count does not match relocatable blocks")
            blocks = tuple(
                RelocatableBlock.from_dict(value) if value is not None else None
                for value in raw_blocks
            )
        return cls(count, unlocked_slots, records, backings, blocks)


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


def _looks_like_pointer(word: int) -> bool:
    """True if either 32-bit half of a 64-bit word lands in the RPCS3 heap band."""
    for half in (word & 0xFFFFFFFF, (word >> 32) & 0xFFFFFFFF):
        if HEAP_POINTER_LOW <= half < HEAP_POINTER_HIGH:
            return True
    return False


@dataclass(frozen=True)
class CampaignSnapshot:
    """Non-empty manager-5 completion cells plus the table dirty flag."""

    dirty: int
    cells: tuple[tuple[int, tuple[int, ...]], ...]

    def __post_init__(self):
        previous = -1
        for index, words in self.cells:
            if not 0 <= index < CAMPAIGN_CELL_COUNT:
                raise ValueError("campaign cell index out of range")
            if index <= previous:
                raise ValueError("campaign cells must be sorted and unique")
            previous = index
            if len(words) != CAMPAIGN_CELL_WORDS:
                raise ValueError("invalid campaign cell length")
            for word in words:
                if not 0 <= word <= 0xFFFFFFFFFFFFFFFF:
                    raise ValueError("invalid campaign cell word")
                if _looks_like_pointer(word):
                    raise ValueError("campaign cell looks like a live pointer")

    def to_dict(self):
        return {
            "schema_version": 1,
            "game": {
                "title": EXPECTED_TITLE,
                "serial": EXPECTED_SERIAL,
                "game_version": EXPECTED_GAME_VERSION,
                "uuid": EXPECTED_UUID,
            },
            "layout": {
                "manager_slot": CAMPAIGN_MANAGER_SLOT,
                "table_offset": CAMPAIGN_TABLE_OFFSET,
                "cell_stride": CAMPAIGN_CELL_STRIDE,
                "cell_count": CAMPAIGN_CELL_COUNT,
            },
            "dirty": self.dirty,
            "cells": [
                {"index": index, "words": _hex_words(words)}
                for index, words in self.cells
            ],
            "captured_at": _datetime.datetime.now().astimezone().isoformat(),
        }

    @classmethod
    def from_dict(cls, data):
        if int(data.get("schema_version", 0)) != 1:
            raise ValueError("unsupported campaign schema")
        game = data.get("game", {})
        if (game.get("serial") != EXPECTED_SERIAL or
                game.get("game_version") != EXPECTED_GAME_VERSION or
                game.get("uuid") != EXPECTED_UUID):
            raise ValueError("campaign belongs to a different game build")
        layout = data.get("layout", {})
        if (int(layout.get("cell_stride", 0)) != CAMPAIGN_CELL_STRIDE or
                int(layout.get("cell_count", 0)) != CAMPAIGN_CELL_COUNT):
            raise ValueError("unsupported campaign memory layout")
        dirty = int(data["dirty"])
        cells = tuple(
            (int(entry["index"]),
             _parse_words(entry["words"], CAMPAIGN_CELL_WORDS, "campaign cell"))
            for entry in data.get("cells", [])
        )
        return cls(dirty, cells)


class CampaignStore:
    def __init__(self, path):
        self.path = Path(path).resolve()
        self.lock = threading.RLock()

    def load(self):
        with self.lock:
            try:
                with self.path.open("r", encoding="utf-8") as handle:
                    return CampaignSnapshot.from_dict(json.load(handle))
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
                 poll_seconds=1.0, stable_reads=2, client_factory=PineClient,
                 campaign_store=None):
        self.store = store
        self.log = logger
        self.host = host
        self.port = int(port)
        self.poll_seconds = max(0.2, float(poll_seconds))
        self.stable_reads = max(2, int(stable_reads))
        self.client_factory = client_factory
        self.campaign_store = campaign_store

    @staticmethod
    def _record_address(slot):
        return OWNED_BASE + slot * RECORD_STRIDE

    @staticmethod
    def _backing_address(slot):
        return OWNED_BACKING_BASE + slot * BACKING_STRIDE

    @staticmethod
    def _capture_block(client, slot, record_address, record):
        root = client.read32(record_address + 4)
        record_heap_fields = [
            value for word in record for value in _word_halves(word)
            if HEAP_POINTER_LOW <= value < HEAP_POINTER_HIGH
        ]
        root_is_heap = HEAP_POINTER_LOW <= root < HEAP_POINTER_HIGH
        root_is_arena = LEGEND_ARENA_BASE <= root < LEGEND_ARENA_END
        if not root_is_heap and not root_is_arena:
            if record_heap_fields:
                raise PineError(
                    f"slot {slot} contains live heap pointers without a Legend block root"
                )
            return None

        if record_heap_fields and any(
                not _address_in_block(value, root) for value in record_heap_fields):
            raise PineError(f"slot {slot} Legend record escapes its 0xB0-byte block")

        words = tuple(
            client.read64(root + offset)
            for offset in range(0, LEGEND_BLOCK_SIZE, 8)
        )
        for word in words:
            for value in _word_halves(word):
                if HEAP_POINTER_LOW <= value < HEAP_POINTER_HIGH:
                    if not _address_in_block(value, root):
                        raise PineError(
                            f"slot {slot} Legend block contains an external heap pointer"
                        )
                elif LEGEND_ARENA_BASE <= value < LEGEND_ARENA_END:
                    if not _address_in_block(value, root):
                        raise PineError(
                            f"slot {slot} Legend block crosses relocation arenas"
                        )
        return RelocatableBlock(root, words)

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
        blocks = []
        for slot in range(count_before):
            record_address = self._record_address(slot)
            backing_address = self._backing_address(slot)
            pointer = client.read32(record_address)
            if pointer != backing_address:
                raise PineError(
                    f"slot {slot} backing pointer 0x{pointer:08X}, "
                    f"expected 0x{backing_address:08X}"
                )
            record = tuple(
                client.read64(record_address + offset)
                for offset in range(0, RECORD_STRIDE, 8)
            )
            records.append(record)
            backings.append(tuple(
                client.read64(backing_address + offset)
                for offset in range(0, BACKING_STRIDE, 8)
            ))
            blocks.append(self._capture_block(client, slot, record_address, record))
        count_after = client.read32(OWNED_COUNT)
        if count_after != count_before:
            raise PineError("roster changed during capture")
        return RosterSnapshot(
            count_before, unlocked_slots, tuple(records), tuple(backings), tuple(blocks)
        )

    def restore_snapshot(self, client, snapshot):
        snapshot = snapshot.materialize()
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

        # Legend definition graphs must exist before any active record points
        # at them. Their pointers have already been rebased into the fixed
        # arena formed from inactive retail-owned backing slots 8..39.
        for block in snapshot.blocks:
            if block is None:
                continue
            for index, word in enumerate(block.words):
                client.write64(block.base + index * 8, word)

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
        return verified

    @staticmethod
    def _campaign_manager(client):
        manager = client.read32(CAMPAIGN_MANAGER_SLOT)
        if manager != EXPECTED_CAMPAIGN_MANAGER:
            raise PineError(
                f"campaign manager 0x{manager:08X}, "
                f"expected 0x{EXPECTED_CAMPAIGN_MANAGER:08X}"
            )
        return manager

    def read_campaign(self, client):
        manager = self._campaign_manager(client)
        base = manager + CAMPAIGN_TABLE_OFFSET
        cells = []
        for index in range(CAMPAIGN_CELL_COUNT):
            address = base + index * CAMPAIGN_CELL_STRIDE
            words = tuple(
                client.read64(address + word * 8)
                for word in range(CAMPAIGN_CELL_WORDS)
            )
            if any(words):
                cells.append((index, words))
        dirty = client.read32(manager + CAMPAIGN_DIRTY_OFFSET)
        # CampaignSnapshot enforces the pointer guard; an unstable heap pointer
        # in a cell raises here and simply skips this capture cycle.
        return CampaignSnapshot(dirty, tuple(cells))

    def restore_campaign(self, client, snapshot):
        manager = self._campaign_manager(client)
        base = manager + CAMPAIGN_TABLE_OFFSET
        for index, words in snapshot.cells:
            address = base + index * CAMPAIGN_CELL_STRIDE
            for word_index, word in enumerate(words):
                client.write64(address + word_index * 8, word)
        client.write32(manager + CAMPAIGN_DIRTY_OFFSET, snapshot.dirty or 1)

        # Verify only the cells we wrote; the game may set additional cells of
        # its own at boot, so a whole-table compare would spuriously fail.
        for index, words in snapshot.cells:
            address = base + index * CAMPAIGN_CELL_STRIDE
            got = tuple(
                client.read64(address + word * 8)
                for word in range(CAMPAIGN_CELL_WORDS)
            )
            if got != words:
                raise PineError(f"campaign cell {index} read-back mismatch")

    def _start_campaign(self, client):
        """First-ready campaign restore/capture. Best-effort; roster is primary.

        Returns the authoritative snapshot, or None to disable campaign
        persistence for this session on any campaign-specific fault.
        """
        if self.campaign_store is None:
            return None
        try:
            saved = self.campaign_store.load()
            if saved is None:
                authoritative = self.read_campaign(client)
                self.campaign_store.save(authoritative)
                self.log.write(
                    f"created initial campaign profile "
                    f"({len(authoritative.cells)} completion cell(s))"
                )
                return authoritative
            current = self.read_campaign(client)
            if current == saved:
                self.log.write(
                    f"live campaign already matches saved "
                    f"{len(saved.cells)} completion cell(s)"
                )
                return saved
            self.restore_campaign(client, saved)
            # Re-read: the game may also set cells of its own at boot, so the
            # authoritative live state is the union, not just what we wrote.
            authoritative = self.read_campaign(client)
            self.log.write(
                f"restored {len(saved.cells)} campaign completion cell(s)"
            )
            return authoritative
        except (PineError, ValueError) as error:
            self.log.write(
                f"campaign persistence unavailable this session ({error})"
            )
            return None

    def _poll_campaign(self, client, state):
        """Capture a campaign mutation that is stable across `stable_reads`.

        `state` and the return value are (authoritative, pending, pending_reads).
        """
        authoritative, pending, pending_reads = state
        if self.campaign_store is None or authoritative is None:
            return state
        try:
            candidate = self.read_campaign(client)
        except (PineError, ValueError):
            return state  # transient (e.g. mid-write); retry next poll
        if candidate == authoritative:
            return (authoritative, None, 0)
        if candidate == pending:
            pending_reads += 1
            if pending_reads >= self.stable_reads:
                try:
                    self.campaign_store.save(candidate)
                except (OSError, ValueError) as error:
                    self.log.write(f"campaign save failed ({error})")
                    return (authoritative, None, 0)
                self.log.write(
                    f"saved stable campaign update "
                    f"({len(candidate.cells)} completion cell(s))"
                )
                return (candidate, None, 0)
            return (authoritative, pending, pending_reads)
        return (authoritative, candidate, 1)

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
        campaign_state = (None, None, 0)

        while not stop_event.is_set():
            if not self._ready(client):
                if session_active:
                    self.log.write("login session ended; capture suspended")
                session_active = False
                stable_ready = 0
                authoritative = None
                pending = None
                pending_reads = 0
                campaign_state = (None, None, 0)
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
                    unresolved = saved.unresolved_slots()
                    if unresolved:
                        slots = ", ".join(str(slot) for slot in unresolved)
                        self.log.write(
                            "legacy roster contains unrecoverable live Legend pointers "
                            f"in slot(s) {slots}; restore/capture disabled for this session "
                            "and the original roster.json was preserved"
                        )
                        authoritative = None
                    else:
                        current = self.read_snapshot(client)
                        if current != saved:
                            authoritative = self.restore_snapshot(client, saved)
                            if authoritative != saved:
                                self.store.save(authoritative)
                                self.log.write("rebased saved Legend graph(s) into fixed roster storage")
                            self.log.write(
                                f"restored {saved.count} gladiator(s); count published last"
                            )
                        else:
                            self.log.write(
                                f"live roster already matches saved "
                                f"{saved.count}-gladiator snapshot"
                            )
                            authoritative = saved
                else:
                    authoritative = self.read_snapshot(client)
                    self.store.save(authoritative)
                    self.log.write(f"created initial {authoritative.count}-gladiator roster profile")
                campaign_state = (self._start_campaign(client), None, 0)
                session_active = True
                pending = None
                pending_reads = 0
                if self._wait(stop_event):
                    return
                continue

            if authoritative is not None:
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
                        self.log.write(
                            f"saved stable {candidate.count}-gladiator roster update"
                        )
                else:
                    pending = candidate
                    pending_reads = 1
            campaign_state = self._poll_campaign(client, campaign_state)
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
                      profile_path=None, log_path=None, poll_seconds=1.0,
                      campaign_path=None):
    base = Path(__file__).resolve().parents[1]
    profile_path = profile_path or os.environ.get(
        "SPARTACUS_ROSTER_PROFILE", str(base / "data" / "roster.json")
    )
    log_path = log_path or os.environ.get(
        "SPARTACUS_ROSTER_LOG", str(base / "logs" / "roster_bridge.log")
    )
    campaign_path = campaign_path or os.environ.get(
        "SPARTACUS_CAMPAIGN_PROFILE", str(base / "data" / "campaign.json")
    )
    bridge = RosterBridge(
        RosterStore(profile_path), BridgeLog(log_path), host, port, poll_seconds,
        campaign_store=CampaignStore(campaign_path),
    )
    bridge.run(stop_event, ready_event)
