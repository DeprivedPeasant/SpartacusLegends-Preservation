#!/usr/bin/env python3
"""
Minimal Quazal RendezVous (PRUDP) server for Spartacus Legends.

Status: full PRUDP handshake works (SYN -> CONNECT -> DATA), and the
client's first RMC call has been decoded as:

    AuthenticationProtocol(10)::Login(1)  username="PepisMax"

This module now answers that Login call.

--- Protocol facts established for THIS title -------------------------
access key            : "pbuT0dSs"   (found beside KFFQuazal.cpp and the
                        onlineConfigID in the binary; sum & 0xFF = 0xF5,
                        which reproduces observed packet checksums)
checksum "setting"    : 0xF5         (= sum(access_key) & 0xFF)
DATA payload RC4 key  : "CD&ML"      (Quazal default, per GROBackendWV)
header                : 10 bytes, type = byte2 & 0x7, flags = byte2 >> 3
                        (NOT Nintendo NEX's 4-bit type in a 2-byte field)

Reference implementation consulted: github.com/zeroKilo/GROBackendWV
(Ghost Recon Online). Note GRO implements Login *CustomData* (method 2);
this title uses plain Login (method 1), so the response body here is
modelled on GRO's LoginCustomData response, which shares the shape.
"""
import socket
import struct
import sys
import hashlib
import hmac
import zlib
import datetime
import time
import os
import threading
import json

PORT = 21000

ACCESS_KEY = b"pbuT0dSs"
CHECKSUM_BASE = sum(ACCESS_KEY) & 0xFF
KEY_DATA = b"CD&ML"

# GRO derives the kerberos ticket key from the account password, defaulting
# to "UbiDummyPwd". This title's binary contains "PS3NPDummyPwd" (next to
# "DummySonyNP@quazal.com"), which is very likely the PS3 equivalent - the
# client must derive the same key to decrypt our ticket. Override via env
# if this turns out to be wrong.
DUMMY_PWD = os.environ.get("DUMMY_PWD", "PS3NPDummyPwd")

# Service accounts have their OWN credentials, and the client derives the
# kerberos key from them. "JaDe!" sits immediately after "Tracking" in the
# binary's string table (JaDe is Ubisoft's analytics platform); encrypting the
# Tracking ticket with PS3NPDummyPwd instead made the client silently drop the
# login result - it never sent the RequestTicket that follows every accepted
# Login. Distinct accounts get distinct PIDs so RequestTicket can tell, from
# source_pid alone, which password to key the ticket with.
TRACKING_PID = 0x00002001
TRACKING_PWD = os.environ.get("TRACKING_PWD", "JaDe!")

USER_PID = 0x00002000
SERVER_PID = 0x00000002

# username -> (pid, password), and the pid -> password map the ticket builder
# uses so Login and RequestTicket always agree on the key.
ACCOUNTS = {b"Tracking": (TRACKING_PID, TRACKING_PWD)}
PID_PASSWORDS = {USER_PID: DUMMY_PWD, TRACKING_PID: TRACKING_PWD}

# (addr, source stream/port) -> RVCID handed out by Register/RegisterEx.
CONN_IDS = {}

# VERBATIM_URL=1 -> answer Register with the client's own URL unchanged,
# keeping its RVCID and parameter order.
VERBATIM_URL = os.environ.get("VERBATIM_URL", "") not in ("", "0")
SERVER_CONN_SIG_VALUE = 0x1000
SESSION_KEY = bytes([0x9C, 0xB0, 0x1D, 0x7A, 0x2C, 0x5A, 0x6C, 0x5B,
                     0xED, 0x12, 0x68, 0x45, 0x69, 0xAE, 0x09, 0x0D])
TICKET_BLOB = bytes(range(36))
ADVERTISED_HOST = os.environ.get("RDV_HOST", "127.0.0.1")
# Reply to otherwise-unhandled RMC requests with an empty success body.
# Useful for probing whether a method returns void.
#   GENERIC_ACK=0 python prudp_server.py   to disable
GENERIC_ACK = os.environ.get("GENERIC_ACK", "1") != "0"
# "empty" is measurably the best default: with it the client accepts and
# walks the whole service chain (proto 53 -> 39 -> 31 -> 29). Sending a
# leading qResult u32 instead ("result") makes it disconnect immediately
# after proto53, so these game methods return void, unlike Login/RegisterEx.
GENERIC_BODY = os.environ.get("GENERIC_BODY", "empty")
GENERIC_BODIES = {
    "empty": b"",                                   # void return
    "zero": struct.pack("<I", 0),                   # empty list / count 0
    "result": struct.pack("<I", 0x00010001),        # bare qResult success
    "result_zero": struct.pack("<II", 0x00010001, 0),   # qResult + empty list
    "zero_zero": struct.pack("<II", 0, 0),          # two empty counts
    # Two primitive u32 output parameters. Monetization(102) method 6 uses
    # this response shape; values are supplied by P<proto>M<method>_0/_1.
    "u32_pair": None,
    # Monetization(102) purchase result: updated gold/silver followed by the
    # 16-byte transaction object decoded as {u32, u64, u32}.
    "monetization_purchase": None,
    # Not a fixed body: mirror the request's own (u32 count, count x u32) list
    # back. Built per-request, see ECHO_LIST handling below.
    "echo_list": None,
    # UserStorage(53) m1 SearchContents response. The DDL and decoder agree on
    # qlist<UserContent>, where UserContent is UserContentKey(u32 typeID,
    # u64 contentID), u32 pid, qlist<ContentProperty>. Built per request.
    "user_content_stub": None,
}

# Per-(protocol, method) overrides so a single service can be varied while
# everything else is held constant. Values name a shape in GENERIC_BODIES.
# Set via env, e.g.  P29M12=zero  P31M13=zero  python prudp_server.py 21001
PROTO_OVERRIDES = {}
for _k, _v in os.environ.items():
    _m = None
    if _k.startswith("P") and "M" in _k:
        try:
            _p, _mm = _k[1:].split("M", 1)
            _m = (int(_p), int(_mm))
        except ValueError:
            _m = None
    if _m and _v in GENERIC_BODIES:
        PROTO_OVERRIDES[_m] = _v

# Opt-in server-push experiment. The live ClientProtocolRequestBroker registry
# contains exactly one incoming protocol: GlobalNotificationEventProtocol=14.
# Schedule one method-1 notification from a selectable point on the main
# player connection. p29m12 covers the short path; p49m1 targets the end of
# the complete startup chain without consuming the one-shot trigger early.
PUSH_NOTIFICATION = os.environ.get("PUSH_NOTIFICATION", "0") not in ("", "0")
NOTIFY_DELAY = float(os.environ.get("NOTIFY_DELAY", "2") or 2)
NOTIFY_TRIGGER = os.environ.get("NOTIFY_TRIGGER", "p29m12").lower()
NOTIFY_TRIGGER_RMC = {"p29m12": (29, 12), "p49m1": (49, 1)}
if NOTIFY_TRIGGER not in NOTIFY_TRIGGER_RMC:
    raise ValueError("NOTIFY_TRIGGER must be p29m12 or p49m1")
NOTIFY_SOURCE = int(os.environ.get("NOTIFY_SOURCE", "0"), 0)
NOTIFY_TYPE = int(os.environ.get("NOTIFY_TYPE", "0"), 0)
NOTIFY_SUBTYPE = int(os.environ.get("NOTIFY_SUBTYPE", "0"), 0)
NOTIFY_PARAM1 = int(os.environ.get("NOTIFY_PARAM1", "0"), 0)
NOTIFY_PARAM2 = int(os.environ.get("NOTIFY_PARAM2", "0"), 0)
NOTIFY_PARAM3 = int(os.environ.get("NOTIFY_PARAM3", "0"), 0)
NOTIFY_STRING = os.environ.get("NOTIFY_STRING", "")

HEADER_FMT = "<BBBBIH"
HEADER_SIZE = struct.calcsize(HEADER_FMT)  # 10

TYPE_SYN, TYPE_CONNECT, TYPE_DATA, TYPE_DISCONNECT, TYPE_PING, TYPE_NATPING = range(6)
TYPE_NAMES = {0: "SYN", 1: "CONNECT", 2: "DATA", 3: "DISCONNECT", 4: "PING", 5: "NATPING"}
TYPE_MASK, FLAG_SHIFT = 0x7, 3

FLAG_ACK, FLAG_RELIABLE, FLAG_NEED_ACK, FLAG_HAS_SIZE, FLAG_UNKNOWN = 1, 2, 4, 8, 16
FLAG_NAMES = {1: "ACK", 2: "RELIABLE", 4: "NEED_ACK", 8: "HAS_SIZE", 16: "UNKNOWN"}

PROTO_AUTHENTICATION = 0x0A
PROTO_SECURE = 0x0B          # SecureConnectionProtocol
PROTO_NOTIFICATION = 0x0E    # GlobalNotificationEventProtocol (live-confirmed)
PROTO_MONETIZATION = 102
STORE_REFRESH_SENTINEL = 99999
PROTO_NAMES = {0x0A: "TicketGranting", 0x0B: "SecureConnection",
               0x0E: "GlobalNotificationEvent", 102: "Monetization"}


class EconomyStore:
    """Small atomic JSON store for the title's server-side economy."""

    def __init__(self, path):
        self.path = os.path.abspath(path)
        self.lock = threading.RLock()
        # Confirmed clean post-tutorial economy. Existing JSON profiles always
        # override these values, so upgrades preserve their current balances.
        self.data = {"version": 1, "gold": 0, "silver": 200, "owned_items": []}
        self._load()

    def _load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            self.data["gold"] = max(0, int(loaded.get("gold", 0)))
            self.data["silver"] = max(0, int(loaded.get("silver", 0)))
            # Older server builds treated the recruitment-store refresh
            # command (99999) as a normal item purchase.  It is not an item
            # and must never be returned by RequestInventory.
            self.data["owned_items"] = sorted({
                int(item) & 0xFFFFFFFF
                for item in loaded.get("owned_items", [])
                if (int(item) & 0xFFFFFFFF) != STORE_REFRESH_SENTINEL
            })
        except FileNotFoundError:
            pass
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
            log(f"WARNING: could not load economy profile {self.path}: {error}")

    def _save(self):
        directory = os.path.dirname(self.path)
        os.makedirs(directory, exist_ok=True)
        temporary = self.path + ".tmp"
        with open(temporary, "w", encoding="utf-8", newline="\n") as f:
            json.dump(self.data, f, indent=2, sort_keys=True)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, self.path)

    def add_income(self, gold_delta, silver_delta):
        with self.lock:
            self.data["gold"] = max(0, self.data["gold"] + gold_delta)
            self.data["silver"] = max(0, self.data["silver"] + silver_delta)
            self._save()
            return self.data["gold"], self.data["silver"]

    def purchase(self, item_id, gold_cost, silver_cost):
        with self.lock:
            owned = set(self.data["owned_items"])
            if item_id not in owned:
                if gold_cost >= 0:
                    self.data["gold"] = max(0, self.data["gold"] - gold_cost)
                if silver_cost >= 0:
                    self.data["silver"] = max(0, self.data["silver"] - silver_cost)
                owned.add(item_id)
                self.data["owned_items"] = sorted(owned)
                self._save()
            return self.data["gold"], self.data["silver"]

    def refresh_store(self, gold_cost, silver_cost):
        """Debit a recruit-pool refresh without creating an owned item."""
        with self.lock:
            if gold_cost >= 0:
                self.data["gold"] = max(0, self.data["gold"] - gold_cost)
            if silver_cost >= 0:
                self.data["silver"] = max(0, self.data["silver"] - silver_cost)
            self._save()
            return self.data["gold"], self.data["silver"]

    def requested_owned_items(self, requested):
        with self.lock:
            owned = set(self.data["owned_items"])
            return [item for item in requested if item in owned]


INVENTORY_PROBE = os.environ.get(
    "SPARTACUS_INVENTORY_PROBE", ""
) not in ("", "0")

# Diagnostic-only Method 3 records for three known-owned weapons.  Keeping
# the price/count fields at zero isolates the two boolean fields and their
# possible interaction in a single cold boot.
INVENTORY_PROBE_FIELDS = {
    10236: (0, True,  0, 0, False, 0, 0),  # boolean field 4 only
    10250: (0, False, 0, 0, True,  0, 0),  # boolean field 7 only
    10265: (0, True,  0, 0, True,  0, 0),  # both boolean fields
}


def inventory_item_fields(item_id):
    if INVENTORY_PROBE and item_id in INVENTORY_PROBE_FIELDS:
        return INVENTORY_PROBE_FIELDS[item_id]
    return (0, False, 0, 0, False, 1, 0)


def encode_inventory_item(item_id):
    """Encode the 9 fields read by Monetization method 3's item decoder."""
    return (struct.pack("<I", item_id)
            + struct.pack("<H", 1) + b"\x00"  # empty Quazal string
            # The third field is rendered by the shop as a gold price when
            # its following flag is true; our former (1, true) placeholder
            # therefore changed owned items to "1 gold".  GetPurchasedItems
            # carries field 8 forward as part of the client inventory state,
            # making it the best-supported quantity/ownership candidate.
            + struct.pack("<I?II?II", *inventory_item_fields(item_id)))


def encode_inventory(items):
    return struct.pack("<I", len(items)) + b"".join(
        encode_inventory_item(item) for item in items
    )


def encode_purchase_result(gold, silver, item_id, quantity=1):
    """Encode method 7/13 balances and its 16-byte transaction receipt."""
    return struct.pack("<IIIQI", gold, silver, item_id, 0, quantity)


LOG_PATH = os.environ.get(
    "SPARTACUS_PRUDP_LOG",
    os.path.join(os.path.dirname(os.path.abspath(__file__)),
                 "..", "notes", "prudp_server_log.txt"),
)
_LOG_LOCK = threading.Lock()
_LOG_CONTEXT = threading.local()


def log(msg):
    ts = datetime.datetime.now().strftime("%H:%M:%S.%f")
    prefix = getattr(_LOG_CONTEXT, "prefix", "prudp")
    line = f"[{ts}] [{prefix}] {msg}"
    with _LOG_LOCK:
        print(line, flush=True)
        with open(LOG_PATH, "a", encoding="utf-8", errors="replace") as f:
            f.write(line + "\n")


ECONOMY = EconomyStore(os.environ.get(
    "SPARTACUS_PROFILE",
    os.path.join(os.path.dirname(os.path.abspath(__file__)),
                 "..", "data", "profile.json"),
))


# ---------------------------------------------------------------- crypto

def rc4(key: bytes, data: bytes) -> bytes:
    s = list(range(256))
    j = 0
    for i in range(256):
        j = (j + key[i % len(key)] + s[i]) & 0xFF
        s[i], s[j] = s[j], s[i]
    out = bytearray()
    i = j = 0
    for b in data:
        i = (i + 1) & 0xFF
        j = (j + s[i]) & 0xFF
        s[i], s[j] = s[j], s[i]
        out.append(b ^ s[(s[i] + s[j]) & 0xFF])
    return bytes(out)


# If set, use this literal 16-byte key instead of deriving one. Recovered
# by breakpointing the client's ticket-validate function (0x00448D98) and
# reading the key out of its crypto context - we do not need to reproduce
# the derivation, only to use the same value the client uses.
#   KERBEROS_KEY=8fb84406b684ce3af9e172a356bc08e5 python prudp_server.py
KERBEROS_KEY_HEX = os.environ.get("KERBEROS_KEY", "").strip()


def derive_key(pid: int, password: str = None) -> bytes:
    """Iterated MD5, count keyed off the PID (GRO's Helper.DeriveKey)."""
    if KERBEROS_KEY_HEX:
        key = bytes.fromhex(KERBEROS_KEY_HEX)
        if len(key) != 16:
            raise ValueError(f"KERBEROS_KEY must be 16 bytes, got {len(key)}")
        return key
    password = DUMMY_PWD if password is None else password
    count = 65000 + (pid % 1024)
    buff = password.encode("ascii")
    for _ in range(count):
        buff = hashlib.md5(buff).digest()
    return buff


def calc_checksum(data, base=CHECKSUM_BASE):
    words = struct.unpack_from("<%iI" % (len(data) // 4), data)
    temp = sum(words) & 0xFFFFFFFF
    checksum = base
    checksum += sum(data[len(data) & ~3:])
    checksum += sum(struct.pack("<I", temp))
    return checksum & 0xFF


# ---------------------------------------------------------------- packets

def describe_flags(flags):
    named = [n for bit, n in FLAG_NAMES.items() if flags & bit]
    return "|".join(named) if named else "none"


def parse(pkt):
    if len(pkt) < HEADER_SIZE + 1:
        return None
    body, checksum = pkt[:-1], pkt[-1]
    src, dst, type_flags, session_id, signature, sequence_id = \
        struct.unpack_from(HEADER_FMT, pkt, 0)
    ptype = type_flags & TYPE_MASK
    rest = pkt[HEADER_SIZE:-1]
    info = {
        "source": src, "destination": dst,
        "type": ptype, "flags": type_flags >> FLAG_SHIFT,
        "session_id": session_id, "signature": signature,
        "sequence_id": sequence_id,
        "conn_sig": None, "fragment_id": None, "payload": b"",
        "tail": rest, "checksum": checksum,
        "checksum_ok": calc_checksum(body) == checksum,
    }
    if ptype in (TYPE_SYN, TYPE_CONNECT) and len(rest) >= 4:
        info["conn_sig"] = struct.unpack_from("<I", rest, 0)[0]
        info["payload"] = rest[4:]
    elif ptype == TYPE_DATA and len(rest) >= 1:
        info["fragment_id"] = rest[0]
        info["payload"] = rest[1:]
    return info


def build(source, destination, ptype, flags, session_id, sequence_id,
          signature=0, conn_sig=None, fragment_id=None, payload=b"",
          encrypt=True):
    pkt = struct.pack(HEADER_FMT, source, destination,
                      (flags << FLAG_SHIFT) | ptype, session_id, signature,
                      sequence_id)
    if conn_sig is not None:
        pkt += struct.pack("<I", conn_sig)
    if fragment_id is not None:
        pkt += bytes([fragment_id])
    if payload:
        # Uncompressed: prefix a zero "compression count", then RC4 the lot
        # (OldRVSec stream only).
        body = b"\x00" + payload
        pkt += rc4(KEY_DATA, body) if encrypt else body
    return pkt + bytes([calc_checksum(pkt)])


# ---------------------------------------------------------------- RMC

def parse_rmc(payload_plain):
    """payload_plain excludes the compression-count byte."""
    if len(payload_plain) < 13:
        return None
    size = struct.unpack_from("<I", payload_plain, 0)[0]
    proto = payload_plain[4]
    return {
        "size": size,
        "is_request": bool(proto & 0x80),
        "protocol": proto & 0x7F,
        "call_id": struct.unpack_from("<I", payload_plain, 5)[0],
        "method_id": struct.unpack_from("<I", payload_plain, 9)[0],
        "params": payload_plain[13:],
    }


def q_string(s: str) -> bytes:
    """Quazal String: u16 length (incl. NUL) then NUL-terminated ASCII."""
    raw = s.encode("ascii") + b"\x00"
    return struct.pack("<H", len(raw)) + raw


def read_q_string(buf: bytes, off: int):
    """Inverse of q_string; returns (text, new_offset)."""
    n = struct.unpack_from("<H", buf, off)[0]
    off += 2
    return buf[off:off + n].rstrip(b"\x00").decode("ascii", "replace"), off + n


def decompress_payload(plain: bytes):
    """
    Split a decrypted PRUDP payload into (compression_byte, body).

    Byte 0 is a compression indicator: 0 means the rest is raw, non-zero
    means the rest is zlib-compressed (the value is a size ratio, not a
    flag). Secure-channel traffic is compressed; the auth channel was not.
    """
    comp, rest = plain[0], plain[1:]
    if comp != 0:
        try:
            rest = zlib.decompress(rest)
        except zlib.error as e:
            log(f"   !! zlib decompress failed ({e}) - using raw bytes")
    return comp, rest


def build_register_ex_response(client_url: str, connection_id: int) -> bytes:
    """
    Body of SecureConnectionProtocol::RegisterEx (method 4).

        u32    resultCode
        u32    connectionId
        String urlPublic     - the client's address as the server sees it
    """
    return (struct.pack("<II", 0x00010001, connection_id)
            + q_string(client_url))


def build_kerberos_ticket(user_pid: int, server_pid: int) -> bytes:
    inner = SESSION_KEY + struct.pack("<II", server_pid, len(TICKET_BLOB)) + TICKET_BLOB
    # Key off the principal the ticket is FOR: the player uses the PS3 dummy
    # password, service accounts use their own.
    key = derive_key(user_pid, PID_PASSWORDS.get(user_pid, DUMMY_PWD))
    enc = rc4(key, inner)
    mac = hmac.new(key, enc, hashlib.md5).digest()
    return enc + mac


def build_login_response(user_pid: int, server_pid: int) -> bytes:
    """Body of AuthenticationProtocol::Login's response."""
    ticket = build_kerberos_ticket(user_pid, server_pid)
    # Field ORDER matches this game's own sprintf template, recovered from
    # its binary:
    #   "prudps:/address=%s;port=%d;stream=%d;sid=%d;PID=%d;CID=1;type=%d"
    # GRO emits a different order (CID/PID/sid/stream); if this title's
    # parser is order-sensitive that would break the secure-connection URL,
    # which matches the observed symptom (auth completes, then the client
    # silently gives up without opening any new socket).
    # "prudps" (secure) is REQUIRED here - tested: advertising plain "prudp"
    # makes the client reject the login result outright and it never even
    # sends RequestTicket. With "prudps" both TicketGranting calls succeed
    # and we get as far as the secure-connect step.
    scheme = os.environ.get("RDV_SCHEME", "prudps")
    # The advertised port can differ from the port we listen on, so we can
    # test whether the client refuses to build a second endpoint pointing at
    # the address:port its auth connection already occupies.
    #   RDV_ADVERTISE_PORT=21001 python prudp_server.py 21000
    adv_port = os.environ.get("RDV_ADVERTISE_PORT", str(PORT))
    conn_str = (f"{scheme}:/address={ADVERTISED_HOST};port={adv_port};stream=3;"
                f"sid=1;PID={server_pid};CID=1;type=2")
    m = struct.pack("<II", 0x00010001, user_pid)          # result, pid
    m += struct.pack("<I", len(ticket)) + ticket           # pbufResponse
    m += q_string(conn_str)                                # RVConnectionData
    m += struct.pack("<IHHHH", 0, 0, 0, 1, 0)              # trailing unknowns
    return m


def build_request_ticket_response(user_pid: int, server_pid: int) -> bytes:
    """Body of AuthenticationProtocol::RequestTicket's response."""
    ticket = build_kerberos_ticket(user_pid, server_pid)
    return struct.pack("<II", 0x00010001, len(ticket)) + ticket


def make_connect_payload(encrypted_payload: bytes) -> bytes:
    """
    Answer the secure service's CONNECT challenge.

    The client sends (after the usual RC4(keyDATA) + compression byte):
        u32 ticketLen || ticket
        u32 dataLen   || RC4(sessionKey, requestData)   # trailing 16 = HMAC
        requestData = u32 pid, u32 unknown, u32 challenge
    and expects back:
        u32 4, u32 (challenge + 1)

    Verified against a real captured packet: the ticket came back byte-for-byte
    as the blob we issued, and the decrypted pid matched the PID we assigned.
    """
    plain = rc4(KEY_DATA, encrypted_payload)
    body = plain[1:]                      # drop compression-count byte
    off = 0
    ticket_len = struct.unpack_from("<I", body, off)[0]; off += 4
    off += ticket_len                     # skip the ticket we issued
    data_len = struct.unpack_from("<I", body, off)[0]; off += 4
    enc = body[off:off + max(0, data_len - 16)]   # last 16 bytes are an HMAC
    dec = rc4(SESSION_KEY, enc)
    if len(dec) < 12:
        log(f"   !! connect challenge too short ({len(dec)} bytes) - "
            f"cannot answer")
        return b""
    pid, unknown, challenge = struct.unpack_from("<III", dec, 0)
    log(f"   challenge: pid=0x{pid:08x} unk=0x{unknown:08x} "
        f"value=0x{challenge:08x} -> replying 0x{(challenge + 1) & 0xFFFFFFFF:08x}")
    return struct.pack("<II", 4, (challenge + 1) & 0xFFFFFFFF)


def build_rmc_response(protocol: int, call_id: int, method_id: int,
                       body: bytes) -> bytes:
    inner = bytes([protocol]) + b"\x01"                    # proto, success
    inner += struct.pack("<II", call_id, method_id | 0x8000)
    inner += body
    return struct.pack("<I", len(inner)) + inner


def build_rmc_request(protocol: int, call_id: int, method_id: int,
                      params: bytes) -> bytes:
    """Build a server-initiated RMC request (high bit set on protocol)."""
    inner = bytes([protocol | 0x80])
    inner += struct.pack("<II", call_id, method_id)
    inner += params
    return struct.pack("<I", len(inner)) + inner


def build_notification_params() -> bytes:
    """GRO-compatible GlobalNotificationEventProtocol::ProcessNotification."""
    return (struct.pack("<IIII", NOTIFY_SOURCE,
                        NOTIFY_TYPE * 1000 + NOTIFY_SUBTYPE,
                        NOTIFY_PARAM1, NOTIFY_PARAM2)
            + q_string(NOTIFY_STRING)
            + struct.pack("<I", NOTIFY_PARAM3))


# ---------------------------------------------------------------- server

def main(port=None, stop_event=None, ready_event=None, host="0.0.0.0"):
    """Run one PRUDP endpoint.

    ``stop_event`` and ``ready_event`` are optional threading Events used by
    the all-in-one preservation launcher. Standalone command-line behavior is
    retained for protocol research.
    """
    port = PORT if port is None else int(port)
    _LOG_CONTEXT.prefix = f"udp:{port}"
    owns_stop_event = stop_event is None
    if stop_event is None:
        stop_event = threading.Event()
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    log(f"PRUDP server on {host}:{port}")
    log(f"access key={ACCESS_KEY.decode()} checksum_base=0x{CHECKSUM_BASE:02x} "
        f"dummy_pwd={DUMMY_PWD!r} user_pid=0x{USER_PID:x}")
    # Echo the response shapes at startup: a mistyped env var silently falls
    # back to GENERIC_BODY and costs a whole game-boot test cycle to notice.
    log(f"generic body default={GENERIC_BODY!r}; overrides="
        + (", ".join(f"P{p}M{m}={v}" for (p, m), v in sorted(PROTO_OVERRIDES.items()))
           or "(none)"))
    log("notification push=" +
        (f"enabled trigger={NOTIFY_TRIGGER} delay={NOTIFY_DELAY:g}s "
         f"source={NOTIFY_SOURCE} "
         f"type={NOTIFY_TYPE} subtype={NOTIFY_SUBTYPE} "
         f"params=({NOTIFY_PARAM1},{NOTIFY_PARAM2},{NOTIFY_PARAM3}) "
         f"string={NOTIFY_STRING!r}" if PUSH_NOTIFICATION else "disabled"))
    # The auth server MUST advertise the secure server's port, not its own -
    # forgetting RDV_ADVERTISE_PORT makes the client stop dead after
    # RequestTicket, with nothing at all arriving on the secure channel.
    log(f"advertising {os.environ.get('RDV_SCHEME', 'prudps')}:/"
        f"address={ADVERTISED_HOST};"
        f"port={os.environ.get('RDV_ADVERTISE_PORT', str(port))}")

    srv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    # Windows raises ConnectionResetError (WinError 10054) on the NEXT
    # recvfrom after a datagram bounces off a closed port - which happens
    # every time the client tears down. Disable that behaviour.
    if hasattr(socket, "SIO_UDP_CONNRESET"):
        try:
            srv.ioctl(socket.SIO_UDP_CONNRESET, False)
        except OSError:
            pass
    srv.bind((host, port))
    srv.settimeout(0.5)
    if ready_event is not None:
        ready_event.set()

    client_conn_sig = {}
    connection_state = {}
    state_lock = threading.Lock()
    notification_scheduled = set()
    seen = set()

    def remember_server_sequence(key, next_sequence):
        with state_lock:
            state = connection_state.get(key)
            if state is not None:
                state["next_seq"] = next_sequence & 0xFFFF

    def schedule_notification(key):
        if not PUSH_NOTIFICATION or key in notification_scheduled:
            return
        with state_lock:
            scheduled_state = connection_state.get(key)
            if scheduled_state is None:
                return
            notification_scheduled.add(key)

        def send_notification():
            with state_lock:
                state = connection_state.get(key)
                if state is not scheduled_state:
                    log("   !! notification cancelled: connection was replaced or closed")
                    return
                state = dict(state)
                connection_state[key]["next_seq"] = (state["next_seq"] + 1) & 0xFFFF
                connection_state[key]["next_call"] = (state["next_call"] + 1) & 0xFFFFFFFF

            params = build_notification_params()
            rmc_msg = build_rmc_request(PROTO_NOTIFICATION,
                                        state["next_call"], 1, params)
            pkt = build(state["server_port"], state["client_port"],
                        TYPE_DATA, FLAG_RELIABLE | FLAG_NEED_ACK,
                        state["session"], state["next_seq"],
                        signature=state["signature"], fragment_id=0,
                        payload=rmc_msg)
            try:
                srv.sendto(pkt, state["addr"])
                log(f"-> PUSH GlobalNotificationEvent(14) method=1 "
                    f"call={state['next_call']} seq={state['next_seq']} "
                    f"({len(pkt)}B, rmc={len(rmc_msg)}B)")
            except OSError as e:
                log(f"   !! notification send failed: {e}")

        timer = threading.Timer(NOTIFY_DELAY, send_notification)
        timer.daemon = True
        timer.start()
        log(f"   notification scheduled in {NOTIFY_DELAY:g}s for "
            f"client vport 0x{key[1]:02x}")

    try:
        while not stop_event.is_set():
            try:
                data, addr = srv.recvfrom(65536)
            except socket.timeout:
                continue
            except ConnectionResetError:
                # Belt-and-braces alongside SIO_UDP_CONNRESET above.
                continue
            info = parse(data)
            if info is None:
                log(f"<- {addr} {len(data)}B unparseable: {data.hex()}")
                continue

            tname = TYPE_NAMES.get(info["type"], f"?{info['type']}")
            new = "   *** NEW PACKET TYPE ***" if info["type"] not in seen else ""
            seen.add(info["type"])
            log(f"<- {addr} {len(data)}B {tname} flags={describe_flags(info['flags'])} "
                f"src=0x{info['source']:02x}(st{info['source'] >> 4}/p{info['source'] & 0xF}) "
                f"dst=0x{info['destination']:02x}(st{info['destination'] >> 4}/p{info['destination'] & 0xF}) "
                f"sess=0x{info['session_id']:02x} seq={info['sequence_id']} "
                f"sig=0x{info['signature']:08x} "
                f"cksum={'OK' if info['checksum_ok'] else 'BAD'}{new}")
            log(f"   raw: {data.hex()}")

            src, dst = info["destination"], info["source"]
            sess, seq = info["session_id"], info["sequence_id"]

            # A packet carrying FLAG_ACK is acknowledging something we sent.
            # Never reply to it (and it has no payload to process).
            if info["flags"] & FLAG_ACK:
                log("   (ACK from client - our packet was accepted)")
                continue

            if info["type"] == TYPE_SYN:
                resp = build(src, dst, TYPE_SYN, FLAG_ACK, sess, seq,
                             signature=info["signature"],
                             conn_sig=SERVER_CONN_SIG_VALUE)
                srv.sendto(resp, addr)
                log(f"-> SYN|ACK conn_sig=0x{SERVER_CONN_SIG_VALUE:08x}")

            elif info["type"] == TYPE_CONNECT:
                client_conn_sig[addr] = info["conn_sig"] or 0
                log(f"   client conn_sig=0x{client_conn_sig[addr]:08x}")

                conn_key = (addr, info["source"])
                with state_lock:
                    # A reconnect reuses the same UDP address/vport key. Let
                    # the new session schedule its own one-shot push.
                    notification_scheduled.discard(conn_key)
                    connection_state[conn_key] = {
                        "addr": addr,
                        "server_port": info["destination"],
                        "client_port": info["source"],
                        "session": sess,
                        "signature": client_conn_sig[addr],
                        "next_seq": (seq + 1) & 0xFFFF,
                        "next_call": 0x70000000,
                    }

                # A CONNECT on the SECURE service carries a payload: the
                # ticket we issued plus a challenge encrypted with that
                # ticket's session key. We must answer with challenge+1.
                # Plain auth-service CONNECTs have no payload.
                reply_payload = b""
                if info["payload"]:
                    reply_payload = make_connect_payload(info["payload"])

                resp = build(src, dst, TYPE_CONNECT, FLAG_ACK, sess, seq,
                             signature=client_conn_sig[addr],
                             conn_sig=SERVER_CONN_SIG_VALUE,
                             payload=reply_payload)
                srv.sendto(resp, addr)
                log("-> CONNECT|ACK" +
                    (" + challenge response" if reply_payload else ""))

            elif info["type"] == TYPE_PING:
                resp = build(src, dst, TYPE_PING, FLAG_ACK, sess, seq,
                             signature=client_conn_sig.get(addr, 0))
                srv.sendto(resp, addr)
                log("-> PING|ACK")

            elif info["type"] == TYPE_DATA:
                if not info["payload"]:
                    log("   (DATA with empty payload - nothing to do)")
                    continue
                plain = rc4(KEY_DATA, info["payload"])
                comp, body = decompress_payload(plain)
                log(f"   decrypted (comp={comp}, {len(body)}B): {body.hex()[:160]}"
                    f"{'...' if len(body) > 80 else ''}")
                rmc = parse_rmc(body)
                if rmc:
                    pname = PROTO_NAMES.get(rmc["protocol"], f"proto{rmc['protocol']}")
                    log(f"   RMC {'REQ' if rmc['is_request'] else 'RESP'} "
                        f"{pname}({rmc['protocol']}) call={rmc['call_id']} "
                        f"method={rmc['method_id']} params={rmc['params'].hex()[:120]}")

                # Always ACK the DATA packet first.
                ack = build(src, dst, TYPE_DATA, FLAG_ACK, sess, seq,
                            signature=client_conn_sig.get(addr, 0),
                            fragment_id=0)
                srv.sendto(ack, addr)
                log("-> DATA|ACK")

                resp_body = None
                label = None
                if rmc and rmc["is_request"] \
                        and rmc["protocol"] == PROTO_SECURE \
                        and rmc["method_id"] in (1, 4):   # Register / RegisterEx
                    # params: u32 urlCount, then that many Quazal Strings,
                    # then a class name and the platform ticket blob.
                    try:
                        n = struct.unpack_from("<I", rmc["params"], 0)[0]
                        off = 4
                        urls = []
                        for _ in range(n):
                            u, off = read_q_string(rmc["params"], off)
                            urls.append(u)
                        # Register(1) sends only the URL vector; RegisterEx(4)
                        # appends a class name and the platform ticket blob.
                        # Don't let the missing tail discard the URLs we parsed.
                        cls = None
                        if rmc["method_id"] == 4:
                            cls, off = read_q_string(rmc["params"], off)
                    except Exception as e:
                        urls, cls = [], f"<parse error {e}>"
                    name = "Register" if rmc["method_id"] == 1 else "RegisterEx"
                    log(f"   *** {name} urls={urls} class={cls!r} ***")
                    # Echo the client's own URL back as its public URL,
                    # tagging it with the connection id we assign.
                    # Each client CONNECTION gets its own RVCID. The Tracking
                    # service opens a SECOND secure connection (stream/port 14
                    # alongside the main 15) and registers on it; handing both
                    # the same id makes two stations claim one RVCID. Key on
                    # the client's source stream/port, which is what
                    # distinguishes the two connections.
                    conn_key = (addr, info["source"])
                    if conn_key not in CONN_IDS:
                        CONN_IDS[conn_key] = 78 + len(CONN_IDS)
                    conn_id = CONN_IDS[conn_key]
                    # If the client already carries an RVCID it assigned itself
                    # from a previous registration, agree with it rather than
                    # renaming its station: echo that id and leave the URL's
                    # parameter order untouched. Rewriting it is the more
                    # invasive choice and neither id (78 shared, 79 fresh)
                    # stopped the post-Register teardown.
                    existing = None
                    if urls:
                        for p in urls[0].split(";"):
                            if p.startswith("RVCID="):
                                try:
                                    existing = int(p[6:])
                                except ValueError:
                                    pass
                    if existing is not None and VERBATIM_URL:
                        conn_id = existing
                    if urls:
                        # By the time Register(1) is called the client's URL
                        # already carries the RVCID we handed back from the
                        # earlier RegisterEx(4). Appending another one yields
                        # "...;RVCID=78;sid=14;RVCID=78" - a duplicated key.
                        # Drop any existing RVCID before adding ours.
                        if VERBATIM_URL and existing is not None:
                            public = urls[0]
                        else:
                            base = ";".join(p for p in urls[0].split(";")
                                            if not p.startswith("RVCID="))
                            public = f"{base};RVCID={conn_id}"
                    else:
                        public = (f"prudp:/address={ADVERTISED_HOST};port=3658;"
                                  f"sid=15;RVCID={conn_id}")
                    resp_body = build_register_ex_response(public, conn_id)
                    label = name.upper()

                elif rmc and rmc["is_request"] \
                        and rmc["protocol"] == PROTO_AUTHENTICATION:
                    if rmc["method_id"] == 1:          # Login
                        name_len = struct.unpack_from("<H", rmc["params"], 0)[0]
                        username = rmc["params"][2:2 + name_len].rstrip(b"\x00")
                        acct_pid, acct_pwd = ACCOUNTS.get(username,
                                                          (USER_PID, DUMMY_PWD))
                        log(f"   *** Login request for user {username!r} "
                            f"-> pid=0x{acct_pid:x} pwd={acct_pwd!r} ***")
                        resp_body = build_login_response(acct_pid, SERVER_PID)
                        label = "LOGIN"
                    elif rmc["method_id"] == 3:        # RequestTicket
                        source_pid, target_pid = struct.unpack_from(
                            "<II", rmc["params"], 0)
                        log(f"   *** RequestTicket source=0x{source_pid:08x} "
                            f"target=0x{target_pid:08x} ***")
                        resp_body = build_request_ticket_response(
                            source_pid, target_pid)
                        label = "REQUEST_TICKET"

                elif rmc and rmc["is_request"] \
                        and rmc["protocol"] == PROTO_MONETIZATION:
                    if rmc["method_id"] == 3:       # RequestInventory
                        try:
                            count = struct.unpack_from("<I", rmc["params"], 0)[0]
                            requested = list(struct.unpack_from(
                                f"<{count}I", rmc["params"], 4
                            )) if count else []
                        except struct.error:
                            requested = []
                        owned = ECONOMY.requested_owned_items(requested)
                        resp_body = encode_inventory(owned)
                        label = "MONETIZATION_INVENTORY"
                        log(f"   *** Inventory requested={requested} owned={owned} ***")
                        if INVENTORY_PROBE:
                            probed = {
                                item: inventory_item_fields(item)
                                for item in owned
                                if item in INVENTORY_PROBE_FIELDS
                            }
                            if probed:
                                log(f"   *** Method 3 probe fields={probed} ***")
                    elif rmc["method_id"] == 6:     # Deposit income
                        try:
                            gold_delta, silver_delta = struct.unpack_from(
                                "<ii", rmc["params"], 0)
                        except struct.error:
                            gold_delta = silver_delta = 0
                        gold, silver = ECONOMY.add_income(
                            gold_delta, silver_delta
                        )
                        resp_body = struct.pack("<II", gold, silver)
                        label = "MONETIZATION_INCOME"
                        log(f"   *** Income gold={gold_delta:+d} "
                            f"silver={silver_delta:+d} -> balances "
                            f"gold={gold} silver={silver} ***")
                    elif rmc["method_id"] == 7:     # Purchase item
                        try:
                            item_id, gold_cost, silver_cost = struct.unpack_from(
                                "<Iii", rmc["params"], 0
                            )
                        except struct.error:
                            item_id, gold_cost, silver_cost = 0, -1, -1
                        if item_id == STORE_REFRESH_SENTINEL:
                            # 99999 is a command used to refresh the timed
                            # gladiator pool, including a free post-fight
                            # refresh.  It is not a purchasable inventory item.
                            # The receipt still has the method-7 structure, but
                            # quantity zero tells the client no item was minted.
                            gold, silver = ECONOMY.refresh_store(
                                gold_cost, silver_cost
                            )
                            resp_body = encode_purchase_result(
                                gold, silver, item_id, quantity=0
                            )
                            label = "MONETIZATION_STORE_REFRESH"
                            log(f"   *** Recruit pool refresh gold_cost={gold_cost} "
                                f"silver_cost={silver_cost} -> balances "
                                f"gold={gold} silver={silver} ***")
                        else:
                            gold, silver = ECONOMY.purchase(
                                item_id, gold_cost, silver_cost
                            )
                            # The final three fields form the purchased-item
                            # receipt: item id, an eight-byte transaction/time
                            # value, and the resulting quantity.
                            resp_body = encode_purchase_result(
                                gold, silver, item_id
                            )
                            label = "MONETIZATION_PURCHASE"
                            log(f"   *** Purchase item={item_id} "
                                f"gold_cost={gold_cost} "
                                f"silver_cost={silver_cost} -> balances "
                                f"gold={gold} silver={silver} ***")
                    elif rmc["method_id"] == 13:    # Recruit gladiator
                        # Live-traced (2026-08-11): the Recruit-store purchase
                        # sends 102/m13 and blocks until answered - the infinite
                        # spinner. Params mirror method 7 (purchase) but for a
                        # gladiator; the user confirmed p3 is the silver cost and
                        # that gladiators cost gold OR silver (the unused currency
                        # is -1):
                        #   u32 gladiator_id, u32 unk, i32 gold_cost, i32 silver_cost
                        try:
                            gladiator_id, unk, gold_cost, silver_cost = \
                                struct.unpack_from("<IIii", rmc["params"], 0)
                        except struct.error:
                            gladiator_id, unk, gold_cost, silver_cost = 0, 0, -1, -1
                        # Debit via add_income (negative delta) so the gladiator
                        # id does NOT pollute the item inventory (owned_items),
                        # unlike purchase(); -1 costs are skipped.
                        gold_delta = -gold_cost if gold_cost >= 0 else 0
                        silver_delta = -silver_cost if silver_cost >= 0 else 0
                        gold, silver = ECONOMY.add_income(gold_delta, silver_delta)
                        # Best-supported response shape: mirror the proven m7
                        # receipt (balances + id/txn/quantity). The recruited
                        # gladiator's full data is already client-side (the store
                        # pool), so a success receipt should let the client move
                        # it into the owned roster. Overridable for iteration via
                        # P102M13_SHAPE if this proves wrong.
                        shape = os.environ.get("P102M13_SHAPE", "m7")
                        if shape == "balances":
                            resp_body = struct.pack("<II", gold, silver)
                        elif shape == "empty":
                            resp_body = b""
                        else:  # "m7"
                            resp_body = encode_purchase_result(
                                gold, silver, gladiator_id
                            )
                        label = "MONETIZATION_RECRUIT"
                        log(f"   *** Recruit gladiator={gladiator_id} unk={unk} "
                            f"gold_cost={gold_cost} silver_cost={silver_cost} "
                            f"shape={shape} -> balances gold={gold} silver={silver} ***")

                elif rmc and rmc["is_request"] and GENERIC_ACK:
                    # Probe for protocols we haven't reversed yet. Every
                    # response we DO know the shape of (Login, RequestTicket,
                    # RegisterEx) begins with a qResult success code, so a
                    # bare u32 0x00010001 is a far better guess than an empty
                    # body - which the client accepted structurally but which
                    # left it with no result field to read.
                    #   GENERIC_BODY=empty  -> send nothing
                    #   GENERIC_BODY=zero   -> send u32 0 (empty list/count)
                    #   GENERIC_BODY=result -> send u32 0x00010001 (default)
                    key = (rmc["protocol"], rmc["method_id"])
                    shape = PROTO_OVERRIDES.get(key, GENERIC_BODY)
                    if shape == "user_content_stub":
                        # SearchContents(UserStorageQuery) returns a
                        # qlist<UserContent>. One metadata record with an
                        # empty property list is structurally complete and
                        # should cause the title to request the content body.
                        try:
                            type_id = struct.unpack_from(
                                "<I", rmc["params"], 0
                            )[0]
                        except struct.error:
                            type_id = 0x80000004
                        content_id = int(os.environ.get(
                            "SPARTACUS_USER_CONTENT_ID", "1"
                        ), 0)
                        owner_pid = int(os.environ.get(
                            "SPARTACUS_USER_CONTENT_PID", str(USER_PID)
                        ), 0)
                        resp_body = struct.pack(
                            "<IIQII", 1, type_id, content_id,
                            owner_pid, 0
                        )
                        shape = ("user_content_stub["
                                 f"type=0x{type_id:08x}, "
                                 f"content={content_id}, "
                                 f"pid=0x{owner_pid:08x}, properties=0]")
                    elif shape == "echo_list":
                        # e.g. UbiAccountManagement(29) m12: the request is
                        # (u32 count, count x u32 pid) and the response decoder
                        # at 0x007201F0 builds a std::set<u32> from the same
                        # shape. Echoing the requested ids back means "all of
                        # these resolved"; an empty set means "none exist",
                        # which the game reads as a missing account.
                        try:
                            n = struct.unpack_from("<I", rmc["params"], 0)[0]
                            ids = list(struct.unpack_from(
                                f"<{n}I", rmc["params"], 4)) if n else []
                        except struct.error:
                            ids = []
                        resp_body = struct.pack(f"<I{len(ids)}I",
                                                len(ids), *ids)
                        shape = f"echo_list{ids}"
                    elif shape == "u32_pair":
                        prefix = f"P{rmc['protocol']}M{rmc['method_id']}"
                        first = int(os.environ.get(prefix + "_0", "0"), 0)
                        second = int(os.environ.get(prefix + "_1", "0"), 0)
                        resp_body = struct.pack("<II", first, second)
                        shape = f"u32_pair[{first}, {second}]"
                    elif shape == "monetization_purchase":
                        prefix = f"P{rmc['protocol']}M{rmc['method_id']}"
                        gold = int(os.environ.get(prefix + "_0", "0"), 0)
                        silver = int(os.environ.get(prefix + "_1", "0"), 0)
                        record_id = int(os.environ.get(prefix + "_ID", "0"), 0)
                        record_value = int(os.environ.get(prefix + "_VALUE", "0"), 0)
                        record_state = int(os.environ.get(prefix + "_STATE", "0"), 0)
                        resp_body = struct.pack(
                            "<IIIQI", gold, silver, record_id,
                            record_value, record_state
                        )
                        shape = (f"monetization_purchase[gold={gold}, "
                                 f"silver={silver}, id={record_id}, "
                                 f"value={record_value}, state={record_state}]")
                    else:
                        resp_body = GENERIC_BODIES.get(shape,
                                                       GENERIC_BODIES["empty"])
                    tag = "override" if key in PROTO_OVERRIDES else "generic"
                    log(f"   ({tag} reply [{shape}] for proto="
                        f"{rmc['protocol']} method={rmc['method_id']})")
                    label = f"GENERIC(p{rmc['protocol']}m{rmc['method_id']})"

                elif rmc:
                    log(f"   (no handler for proto={rmc['protocol']} "
                        f"method={rmc['method_id']})")

                if resp_body is not None:
                    # Optional stall before answering a specific method, so a
                    # breakpoint can be armed in RPCS3 during the window and
                    # fire on THIS message rather than earlier traffic.
                    #   DELAY_P29M12=15 python prudp_server.py 21001
                    dkey = f"DELAY_P{rmc['protocol']}M{rmc['method_id']}"
                    dsecs = float(os.environ.get(dkey, "0") or 0)
                    if dsecs > 0:
                        log(f"   >>> DELAYING this response {dsecs:g}s - "
                            f"arm your breakpoint NOW <<<")
                        time.sleep(dsecs)
                        log("   >>> delay over, sending <<<")
                    rmc_msg = build_rmc_response(rmc["protocol"],
                                                 rmc["call_id"],
                                                 rmc["method_id"], resp_body)
                    pkt = build(src, dst, TYPE_DATA, FLAG_NEED_ACK, sess,
                                seq + 1,
                                signature=client_conn_sig.get(addr, 0),
                                fragment_id=0, payload=rmc_msg)
                    srv.sendto(pkt, addr)
                    conn_key = (addr, info["source"])
                    remember_server_sequence(conn_key, seq + 2)
                    log(f"-> {label} RESPONSE ({len(pkt)}B, rmc={len(rmc_msg)}B)")

                    if ((rmc["protocol"], rmc["method_id"]) ==
                            NOTIFY_TRIGGER_RMC[NOTIFY_TRIGGER]
                            and (info["source"] & 0x0F) == 0x0F):
                        schedule_notification(conn_key)

            elif info["type"] == TYPE_DISCONNECT:
                resp = build(src, dst, TYPE_DISCONNECT, FLAG_ACK, sess, seq,
                             signature=client_conn_sig.get(addr, 0))
                srv.sendto(resp, addr)
                log("-> DISCONNECT|ACK")
                with state_lock:
                    conn_key = (addr, info["source"])
                    connection_state.pop(conn_key, None)
                    notification_scheduled.discard(conn_key)
            else:
                log(f"   (no handler for {tname})")
    except KeyboardInterrupt:
        if owns_stop_event:
            log("Shutting down.")
    finally:
        srv.close()


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else PORT)
